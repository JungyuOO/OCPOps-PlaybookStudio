"""Topology-backed retrieval expansion.

The expansion is deliberately evidence-bound: it only annotates or promotes
real BM25/vector candidates, never synthetic graph-only hits.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from typing import Any

from .models import RetrievalHit


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-/가-힣]{2,}")


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in _TOKEN_RE.findall(text or "")}


def _uuid_or_empty(value: str) -> str:
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except ValueError:
        return ""


def _snapshot_rows_from_database(database_url: str, source_ids: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not database_url.strip() or not source_ids:
        return [], {"enabled": False, "skip_reason": "database_url_or_source_ids_missing"}
    try:
        import psycopg

        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (document_source_id)
                        document_source_id::text,
                        schema_version,
                        state,
                        summary,
                        nodes,
                        edges,
                        metadata
                    FROM document_topology_snapshots
                    WHERE document_source_id = ANY(%s::uuid[])
                    ORDER BY document_source_id, updated_at DESC
                    """,
                    (source_ids,),
                )
                rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], {"enabled": True, "skip_reason": "snapshot_load_failed", "error": str(exc)}
    snapshots = [
        {
            "document_source_id": str(row[0] or ""),
            "schema_version": str(row[1] or ""),
            "state": str(row[2] or ""),
            "summary": dict(row[3] or {}),
            "nodes": list(row[4] or []),
            "edges": list(row[5] or []),
            "metadata": dict(row[6] or {}),
        }
        for row in rows
    ]
    return snapshots, {"enabled": True, "snapshot_count": len(snapshots)}


def _edge_evidence_matches_chunk(edge: dict[str, Any], chunk_id: str) -> bool:
    for item in edge.get("evidence") or []:
        if isinstance(item, dict) and str(item.get("chunk_id") or "") == chunk_id:
            return True
    return False


def _node_query_matches(node: dict[str, Any], query_terms: set[str]) -> bool:
    if not query_terms:
        return False
    label_terms = _tokens(str(node.get("label") or ""))
    return bool(label_terms & query_terms)


def _hit_topology_match(
    hit: RetrievalHit,
    snapshot: dict[str, Any],
    *,
    query_terms: set[str],
) -> dict[str, Any] | None:
    nodes = [node for node in snapshot.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in snapshot.get("edges") or [] if isinstance(edge, dict)]
    node_by_id = {str(node.get("id") or ""): node for node in nodes}
    matched_edges: list[dict[str, Any]] = []
    matched_node_ids: set[str] = set()
    for edge in edges:
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        source_node = node_by_id.get(source_id) or {}
        target_node = node_by_id.get(target_id) or {}
        chunk_match = _edge_evidence_matches_chunk(edge, hit.chunk_id)
        if chunk_match:
            matched_edges.append(edge)
            if source_id:
                matched_node_ids.add(source_id)
            if target_id:
                matched_node_ids.add(target_id)
    if not matched_edges:
        return None
    relations = tuple(
        sorted({str(edge.get("relation") or "") for edge in matched_edges if str(edge.get("relation") or "").strip()})
    )
    evidence: list[dict[str, Any]] = []
    for edge in matched_edges[:8]:
        evidence.append(
            {
                "edge_id": str(edge.get("id") or ""),
                "relation": str(edge.get("relation") or ""),
                "label": str(edge.get("label") or ""),
                "evidence": list(edge.get("evidence") or [])[:3],
            }
        )
    return {
        "node_ids": tuple(sorted(matched_node_ids)),
        "edge_ids": tuple(str(edge.get("id") or "") for edge in matched_edges if str(edge.get("id") or ""))[:12],
        "relations": relations,
        "evidence": tuple(evidence),
        "edge_count": len(matched_edges),
    }


def enrich_hits_from_topology_snapshots(
    query: str,
    *,
    hits: list[RetrievalHit],
    reservoir_hits: list[RetrievalHit] | None,
    snapshots: list[dict[str, Any]],
    inject_limit: int = 3,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    query_terms = _tokens(query)
    snapshot_by_source = {
        str(snapshot.get("document_source_id") or ""): snapshot
        for snapshot in snapshots
        if str(snapshot.get("document_source_id") or "").strip()
    }
    if not snapshot_by_source:
        return list(hits), {
            "enabled": True,
            "used": False,
            "skip_reason": "no_snapshots",
            "matched_hit_count": 0,
            "injected_hit_count": 0,
        }

    base_ids = {hit.chunk_id for hit in hits}
    enriched: list[RetrievalHit] = []
    matched_source_ids: set[str] = set()
    matches: list[dict[str, Any]] = []
    for hit in hits:
        snapshot = snapshot_by_source.get(str(hit.document_source_id or hit.source_id or ""))
        match = _hit_topology_match(hit, snapshot, query_terms=query_terms) if snapshot else None
        if not match:
            enriched.append(hit)
            continue
        matched_source_ids.add(str(hit.document_source_id or hit.source_id or ""))
        boosted_scores = dict(hit.component_scores)
        boosted_scores["topology_edge_count"] = float(match["edge_count"])
        boosted_scores["topology_boost"] = min(0.08, 0.01 * float(match["edge_count"]))
        enriched_hit = replace(
            hit,
            fused_score=hit.fused_score + boosted_scores["topology_boost"],
            topology_node_ids=tuple(match["node_ids"]),
            topology_edge_ids=tuple(match["edge_ids"]),
            topology_relations=tuple(match["relations"]),
            topology_evidence=tuple(match["evidence"]),
            component_scores=boosted_scores,
        )
        enriched.append(enriched_hit)
        matches.append(
            {
                "chunk_id": hit.chunk_id,
                "document_source_id": str(hit.document_source_id or hit.source_id or ""),
                "edge_ids": list(enriched_hit.topology_edge_ids[:5]),
                "relations": list(enriched_hit.topology_relations),
            }
        )

    injected: list[RetrievalHit] = []
    for candidate in reservoir_hits or []:
        if len(injected) >= inject_limit:
            break
        if candidate.chunk_id in base_ids:
            continue
        source_id = str(candidate.document_source_id or candidate.source_id or "")
        if source_id not in matched_source_ids:
            continue
        snapshot = snapshot_by_source.get(source_id)
        match = _hit_topology_match(candidate, snapshot, query_terms=query_terms) if snapshot else None
        if not match:
            continue
        component_scores = dict(candidate.component_scores)
        component_scores["topology_injected"] = 1.0
        component_scores["topology_edge_count"] = float(match["edge_count"])
        injected_hit = replace(
            candidate,
            fused_score=candidate.fused_score + 0.05,
            topology_node_ids=tuple(match["node_ids"]),
            topology_edge_ids=tuple(match["edge_ids"]),
            topology_relations=tuple(match["relations"]),
            topology_evidence=tuple(match["evidence"]),
            component_scores=component_scores,
        )
        injected.append(injected_hit)
        matches.append(
            {
                "chunk_id": candidate.chunk_id,
                "document_source_id": source_id,
                "edge_ids": list(injected_hit.topology_edge_ids[:5]),
                "relations": list(injected_hit.topology_relations),
                "injected": True,
            }
        )

    output = sorted([*enriched, *injected], key=lambda item: item.fused_score, reverse=True)
    return output, {
        "enabled": True,
        "used": bool(matches),
        "snapshot_count": len(snapshot_by_source),
        "matched_hit_count": sum(1 for item in enriched if item.topology_edge_ids),
        "injected_hit_count": len(injected),
        "matched_edge_count": sum(len(item.topology_edge_ids) for item in output),
        "matches": matches[:12],
    }


def expand_hits_with_topology(
    *,
    database_url: str,
    query: str,
    hits: list[RetrievalHit],
    reservoir_hits: list[RetrievalHit] | None = None,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    source_ids = sorted(
        {
            source_id
            for source_id in (
                _uuid_or_empty(str(hit.document_source_id or hit.source_id or ""))
                for hit in [*hits, *(reservoir_hits or [])]
            )
            if source_id
        }
    )
    snapshots, load_trace = _snapshot_rows_from_database(database_url, source_ids)
    if not snapshots:
        return list(hits), {
            "enabled": bool(load_trace.get("enabled", True)),
            "used": False,
            **load_trace,
        }
    enriched, trace = enrich_hits_from_topology_snapshots(
        query,
        hits=hits,
        reservoir_hits=reservoir_hits,
        snapshots=snapshots,
    )
    return enriched, {**load_trace, **trace, "candidate_document_count": len(source_ids)}


__all__ = [
    "enrich_hits_from_topology_snapshots",
    "expand_hits_with_topology",
]
