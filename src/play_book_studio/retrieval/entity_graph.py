"""Entity-graph aware retrieval expansion.

질문에서 운영 entity(namespace, route, pvc 등)를 탐지하고 graph_entity_* 테이블의
1-hop 관계를 확장해, 고객 환경값이 담긴 evidence chunk를 boost/주입한다.
기존 book 단위 graph_runtime과 별개의 최소 단계이며 실패 시 원본 hits를 그대로 반환한다.
"""

from __future__ import annotations

import time
from typing import Any

from play_book_studio.db import graph_repository
from play_book_studio.db.graph_repository import GraphScopeFilter
from play_book_studio.graph.rules import detect_kind_hints, query_name_tokens
from play_book_studio.retrieval.payload import retrieval_payload_from_row

from .chunk_hydration import load_document_chunk_payload_rows
from .models import RetrievalHit, SessionContext
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event
from .vector import hit_from_payload

ENTITY_GRAPH_BOOST_CAP = 0.24
_SEED_HIT_COUNT = 8
_MAX_SEED_ENTITIES = 12
_MAX_TRACE_RELATIONS = 20
_LIGHTSPEED_EVIDENCE_LIMIT = 5


def _skipped_payload(*, enabled: bool, reason: str) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "status": "skipped",
        "reason": reason,
        "seed_entities": [],
        "neighbor_entities": [],
        "relations": [],
        "boosted_count": 0,
        "injected_count": 0,
    }


def _scope_filter(context: SessionContext | None) -> GraphScopeFilter:
    if context is None:
        return GraphScopeFilter()
    return GraphScopeFilter(
        owner_user_id=str(context.owner_user_id or ""),
        enabled_source_scopes=tuple(
            str(scope).strip()
            for scope in (context.enabled_source_scopes or [])
            if str(scope).strip()
        ),
    )


def _order_seed_entities(
    entities: list[dict[str, Any]],
    *,
    kind_hints: tuple[str, ...],
) -> list[dict[str, Any]]:
    hint_rank = {kind: index for index, kind in enumerate(kind_hints)}

    def sort_key(entity: dict[str, Any]) -> tuple[int, str]:
        kind = str(entity.get("entity_kind") or "")
        return (hint_rank.get(kind, len(hint_rank) + 1), str(entity.get("entity_key") or ""))

    return sorted(entities, key=sort_key)[:_MAX_SEED_ENTITIES]


def maybe_expand_entity_graph(
    retriever,
    *,
    query: str,
    hits: list[RetrievalHit],
    context: SessionContext | None,
    candidate_k: int,
    trace_callback=None,
    timings_ms: dict[str, float] | None = None,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    settings = retriever.settings
    if not bool(getattr(settings, "entity_graph_enabled", False)):
        return hits, _skipped_payload(enabled=False, reason="entity_graph_disabled")
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        return hits, _skipped_payload(enabled=True, reason="no_database_url")
    if not hits:
        return hits, _skipped_payload(enabled=True, reason="no_hits")

    started_at = time.perf_counter()
    _emit_trace_event(
        trace_callback,
        step="entity_graph",
        label="운영 엔티티 그래프 확장 중",
        status="running",
    )
    try:
        result = _expand(
            settings,
            database_url=database_url,
            query=query,
            hits=hits,
            scope=_scope_filter(context),
            candidate_k=candidate_k,
        )
    except Exception as exc:  # noqa: BLE001 - graph expansion must never break retrieval
        elapsed = _duration_ms(started_at)
        if timings_ms is not None:
            timings_ms["entity_graph"] = elapsed
        payload = {
            **_skipped_payload(enabled=True, reason=f"entity_graph_failed:{exc}"),
            "status": "failed",
        }
        payload["duration_ms"] = elapsed
        _emit_trace_event(
            trace_callback,
            step="entity_graph",
            label="운영 엔티티 그래프 확장 실패",
            status="warning",
            detail=str(exc),
            duration_ms=elapsed,
        )
        return hits, payload

    expanded_hits, payload = result
    elapsed = _duration_ms(started_at)
    payload["duration_ms"] = elapsed
    if timings_ms is not None:
        timings_ms["entity_graph"] = elapsed
    seed_keys = payload.get("seed_entities") or []
    detail = ""
    if seed_keys:
        first_name = str(seed_keys[0]).split(":", 1)[-1]
        detail = f"{first_name} 외 {max(0, len(seed_keys) - 1)}개 엔티티 · 관계 {len(payload.get('relations') or [])}건"
    _emit_trace_event(
        trace_callback,
        step="entity_graph",
        label="운영 엔티티 그래프 확장 완료",
        status="done",
        detail=detail or payload.get("reason", "seed entity 없음"),
        duration_ms=elapsed,
        meta={
            "seed_count": len(seed_keys),
            "neighbor_count": len(payload.get("neighbor_entities") or []),
            "boosted_count": payload.get("boosted_count", 0),
            "injected_count": payload.get("injected_count", 0),
            "lightspeed_evidence_count": len(payload.get("lightspeed_evidence") or []),
        },
    )
    return expanded_hits, payload


def _expand(
    settings,
    *,
    database_url: str,
    query: str,
    hits: list[RetrievalHit],
    scope: GraphScopeFilter,
    candidate_k: int,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    import psycopg

    kind_hints = detect_kind_hints(query)
    name_tokens = list(query_name_tokens(query))
    seed_chunk_ids = [hit.chunk_id for hit in hits[:_SEED_HIT_COUNT] if hit.chunk_id]

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            seeds_by_id: dict[str, dict[str, Any]] = {}
            for row in graph_repository.find_entities_by_names(cursor, name_tokens, scope=scope):
                seeds_by_id[str(row["entity_id"])] = row
            for row in graph_repository.find_entities_for_chunks(
                cursor, seed_chunk_ids, scope=scope
            ):
                seeds_by_id.setdefault(str(row["entity_id"]), row)

            seeds = _order_seed_entities(list(seeds_by_id.values()), kind_hints=kind_hints)
            seed_ids = [str(entity["entity_id"]) for entity in seeds]
            if not seed_ids:
                return hits, _skipped_payload(enabled=True, reason="no_seed_entities")

            relations = graph_repository.expand_relations(
                cursor,
                seed_ids,
                scope=scope,
                limit=int(getattr(settings, "entity_graph_max_neighbors", 20)),
            )
            neighbor_keys: dict[str, str] = {}
            all_entity_ids = dict.fromkeys(seed_ids)
            for relation in relations:
                for id_field, key_field in (
                    ("subject_entity_id", "subject_key"),
                    ("object_entity_id", "object_key"),
                ):
                    entity_id = str(relation.get(id_field) or "")
                    if entity_id and entity_id not in all_entity_ids:
                        all_entity_ids[entity_id] = None
                        neighbor_keys[entity_id] = str(relation.get(key_field) or "")

            evidence_rows = graph_repository.load_evidence_chunk_rows(
                cursor,
                list(all_entity_ids),
                scope=scope,
                limit=max(20, int(candidate_k)),
            )
            lightspeed_rows = graph_repository.load_lightspeed_evidence_rows(
                cursor,
                list(all_entity_ids),
                limit=_LIGHTSPEED_EVIDENCE_LIMIT,
            )

        entities_by_chunk: dict[str, set[str]] = {}
        quotes_by_chunk: dict[str, str] = {}
        for row in evidence_rows:
            chunk_id = str(row.get("chunk_id") or "")
            entity_key = str(row.get("entity_key") or "")
            if not chunk_id or not entity_key:
                continue
            entities_by_chunk.setdefault(chunk_id, set()).add(entity_key)
            quotes_by_chunk.setdefault(chunk_id, str(row.get("quote") or ""))

        boost_weight = float(getattr(settings, "entity_graph_boost_weight", 0.08))
        boosted_count = 0
        existing_chunk_ids = {hit.chunk_id for hit in hits}
        enriched_hits = list(hits)
        boosted_scores: list[float] = []
        for hit in enriched_hits:
            matched = entities_by_chunk.get(hit.chunk_id)
            if not matched:
                continue
            boost = round(min(ENTITY_GRAPH_BOOST_CAP, boost_weight * len(matched)), 4)
            hit.component_scores["entity_graph_score"] = boost
            hit.component_scores["entity_graph_entity_count"] = float(len(matched))
            hit.fused_score = round(float(hit.fused_score or hit.raw_score) + boost, 6)
            boosted_scores.append(hit.fused_score)
            boosted_count += 1

        max_injected = int(getattr(settings, "entity_graph_max_injected_hits", 3))
        injectable_chunk_ids = [
            chunk_id
            for chunk_id in entities_by_chunk
            if chunk_id not in existing_chunk_ids
        ][:max_injected]
        injected_hits: list[RetrievalHit] = []
        if injectable_chunk_ids:
            floor_score = min(
                boosted_scores
                or [min((float(hit.fused_score or 0.0) for hit in enriched_hits), default=0.0)]
            )
            rows_by_chunk_id = load_document_chunk_payload_rows(
                connection, chunk_ids=injectable_chunk_ids
            )
            for index, chunk_id in enumerate(injectable_chunk_ids):
                row = rows_by_chunk_id.get(chunk_id)
                if row is None:
                    continue
                injected = hit_from_payload(
                    retrieval_payload_from_row(row),
                    source="entity_graph",
                    score=max(0.0, floor_score - 0.001 * (index + 1)),
                )
                matched = entities_by_chunk.get(chunk_id) or set()
                injected.component_scores["entity_graph_score"] = round(
                    min(ENTITY_GRAPH_BOOST_CAP, boost_weight * len(matched)), 4
                )
                injected.component_scores["entity_graph_entity_count"] = float(len(matched))
                injected_hits.append(injected)

    merged_hits = sorted(
        [*enriched_hits, *injected_hits],
        key=lambda hit: (-float(hit.fused_score or 0.0), hit.book_slug, hit.chunk_id),
    )
    budget = max(len(hits), min(int(candidate_k), len(hits) + len(injected_hits)))
    merged_hits = merged_hits[:budget]

    payload = {
        "enabled": True,
        "status": "expanded",
        "reason": "",
        "kind_hints": list(kind_hints),
        "query_name_tokens": name_tokens,
        "seed_entities": [str(entity.get("entity_key") or "") for entity in seeds],
        "neighbor_entities": sorted(value for value in neighbor_keys.values() if value),
        "relations": [
            {
                "subject": str(relation.get("subject_key") or ""),
                "relation_type": str(relation.get("relation_type") or ""),
                "object": str(relation.get("object_key") or ""),
                "quote": str(relation.get("quote") or "")[:300],
                "chunk_id": str(relation.get("chunk_id") or ""),
                "confidence": float(relation.get("confidence") or 0.0),
            }
            for relation in relations[:_MAX_TRACE_RELATIONS]
        ],
        "evidence_chunk_count": len(entities_by_chunk),
        "boosted_count": boosted_count,
        "injected_count": len(injected_hits),
        "injected_chunk_ids": [hit.chunk_id for hit in injected_hits],
        "lightspeed_evidence": [
            {
                "entity_key": str(row.get("entity_key") or ""),
                "artifact_id": str(row.get("source_ref") or ""),
                "quote": str(row.get("quote") or "")[:300],
            }
            for row in lightspeed_rows
        ],
    }
    return merged_hits, payload
