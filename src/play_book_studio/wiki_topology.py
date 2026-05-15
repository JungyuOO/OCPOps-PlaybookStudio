"""Deterministic topology contract for persisted wiki documents.

This is intentionally source-grounded. The graph starts from stored document
chunks and assets, and every relation carries evidence back to a chunk or asset.
LLM extractors can enrich this later, but the base contract must not invent
relations without evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable


TOPOLOGY_SCHEMA_VERSION = "wiki_topology_v1"

_COMMAND_RE = re.compile(
    r"(?im)(?:^|\n)\s*((?:oc|kubectl|helm|podman|docker|ansible-playbook|terraform|python\s+-m)\b[^\n`$]*)"
)
_YAML_KIND_RE = re.compile(r"(?im)^\s*kind:\s*([A-Za-z][A-Za-z0-9._-]+)\s*$")
_CODE_FENCE_RE = re.compile(r"```(?:bash|shell|sh|console|yaml|yml)?\s*\n(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)

_KNOWN_CONCEPT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("OpenShift Container Platform", "OpenShift"),
    ("OpenShift", "OpenShift"),
    ("Kubernetes", "Kubernetes"),
    ("Namespace", "Namespace"),
    ("Pod", "Pod"),
    ("Deployment", "Deployment"),
    ("Service", "Service"),
    ("Route", "Route"),
    ("Ingress", "Ingress"),
    ("Operator", "Operator"),
    ("OLM", "OLM"),
    ("PersistentVolumeClaim", "PVC"),
    ("Persistent Volume Claim", "PVC"),
    ("StorageClass", "StorageClass"),
    ("ConfigMap", "ConfigMap"),
    ("Secret", "Secret"),
    ("YAML", "YAML"),
    ("Qdrant", "Qdrant"),
    ("RAGAS", "RAGAS"),
    ("Gold", "Gold"),
    ("Judge", "Judge"),
    ("Bronze", "Bronze"),
    ("Silver", "Silver"),
)


@dataclass(frozen=True, slots=True)
class TopologyEvidence:
    document_source_id: str
    parsed_document_id: str = ""
    chunk_id: str = ""
    asset_id: str = ""
    page_number: int | None = None
    field: str = ""
    quote: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_source_id": self.document_source_id,
            "parsed_document_id": self.parsed_document_id,
            "chunk_id": self.chunk_id,
            "asset_id": self.asset_id,
            "field": self.field,
            "quote": self.quote,
        }
        if self.page_number is not None:
            payload["page_number"] = self.page_number
        return {key: value for key, value in payload.items() if value not in ("", None)}


@dataclass(frozen=True, slots=True)
class TopologyNode:
    id: str
    kind: str
    label: str
    role: str = ""
    status: str = ""
    evidence: tuple[TopologyEvidence, ...] = ()
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "role": self.role,
            "status": self.status,
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True, slots=True)
class TopologyEdge:
    id: str
    source: str
    target: str
    relation: str
    label: str
    confidence: float
    evidence: tuple[TopologyEvidence, ...] = ()
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "label": self.label,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True, slots=True)
class WikiTopology:
    schema_version: str
    document_source_id: str
    parsed_document_id: str
    summary: dict[str, Any]
    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_source_id": self.document_source_id,
            "parsed_document_id": self.parsed_document_id,
            "summary": dict(self.summary),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


def _stable_id(kind: str, *parts: object) -> str:
    body = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:14]
    return f"{kind}:{digest}"


def _clean_text(value: object, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _node_sort_key(node: TopologyNode) -> tuple[str, str]:
    order = {
        "document": "00",
        "section": "10",
        "chunk": "20",
        "asset": "30",
        "command": "40",
        "concept": "50",
        "judge": "60",
    }
    return (order.get(node.kind, "99"), node.label.lower(), node.id)


def _edge_sort_key(edge: TopologyEdge) -> tuple[str, str, str]:
    return (edge.relation, edge.source, edge.target)


def _chunk_text(chunk: dict[str, Any]) -> str:
    return "\n".join(
        str(chunk.get(key) or "")
        for key in ("heading_title", "markdown", "text")
        if str(chunk.get(key) or "").strip()
    )


def _asset_text(asset: dict[str, Any]) -> str:
    return "\n".join(
        str(asset.get(key) or "")
        for key in ("caption_text", "ocr_text", "qwen_description", "filename")
        if str(asset.get(key) or "").strip()
    )


def _extract_concepts(text: str) -> list[str]:
    concepts: set[str] = set()
    searchable = text or ""
    for pattern, label in _KNOWN_CONCEPT_PATTERNS:
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(pattern)}(?![A-Za-z0-9_-])", searchable, re.IGNORECASE):
            concepts.add(label)
    for match in _YAML_KIND_RE.finditer(searchable):
        concepts.add(match.group(1))
    return sorted(concepts, key=str.casefold)


def _extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    candidates = [text]
    candidates.extend(match.group("body") for match in _CODE_FENCE_RE.finditer(text or ""))
    for candidate in candidates:
        for match in _COMMAND_RE.finditer(candidate or ""):
            command = _clean_text(match.group(1), limit=180)
            if command and command not in seen:
                seen.add(command)
                commands.append(command)
    return commands[:24]


def build_document_topology(
    document: dict[str, Any],
    *,
    chunks: Iterable[dict[str, Any]] | None = None,
    assets: Iterable[dict[str, Any]] | None = None,
) -> WikiTopology:
    """Build a deterministic topology snapshot from persisted document rows."""

    document_source_id = str(document.get("document_source_id") or "").strip()
    parsed_document_id = str(document.get("parsed_document_id") or "").strip()
    title = _clean_text(document.get("title") or document.get("filename") or document_source_id or "문서")
    chunk_rows = [dict(row) for row in (chunks if chunks is not None else document.get("chunks") or [])]
    asset_rows = [dict(row) for row in (assets if assets is not None else document.get("assets") or [])]
    gold_build_run = document.get("gold_build_run")
    if not isinstance(gold_build_run, dict):
        metadata = document.get("metadata")
        gold_build_run = metadata.get("gold_build_run") if isinstance(metadata, dict) else {}
    if not isinstance(gold_build_run, dict):
        gold_build_run = {}

    nodes: dict[str, TopologyNode] = {}
    edges: dict[str, TopologyEdge] = {}

    def add_node(node: TopologyNode) -> None:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
            return
        evidence = tuple({tuple(item.to_dict().items()): item for item in (*existing.evidence, *node.evidence)}.values())
        metadata = {**dict(existing.metadata or {}), **dict(node.metadata or {})}
        nodes[node.id] = TopologyNode(
            id=existing.id,
            kind=existing.kind,
            label=existing.label,
            role=existing.role or node.role,
            status=existing.status or node.status,
            evidence=evidence,
            metadata=metadata,
        )

    def add_edge(edge: TopologyEdge) -> None:
        edges.setdefault(edge.id, edge)

    document_node_id = _stable_id("document", document_source_id or parsed_document_id or title)
    add_node(
        TopologyNode(
            id=document_node_id,
            kind="document",
            label=title,
            role="source",
            status=str(document.get("parse_status") or "parsed"),
            metadata={
                "filename": str(document.get("filename") or ""),
                "source_scope": str(document.get("source_scope") or ""),
                "total_chunks": int(document.get("total_chunks") or len(chunk_rows) or 0),
            },
        )
    )

    chunk_id_by_asset_id: dict[str, list[str]] = {}
    section_node_by_label: dict[str, str] = {}
    concept_count = 0
    command_count = 0

    for index, chunk in enumerate(chunk_rows, start=1):
        raw_chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or chunk.get("chunk_key") or index)
        chunk_node_id = _stable_id("chunk", document_source_id, parsed_document_id, raw_chunk_id)
        chunk_title = _clean_text(
            chunk.get("heading_title")
            or (list(chunk.get("section_path") or [])[-1] if chunk.get("section_path") else "")
            or chunk.get("source_anchor")
            or f"조각 {index}",
            limit=140,
        )
        page_number = chunk.get("page_start") or chunk.get("page_number")
        evidence = TopologyEvidence(
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            chunk_id=raw_chunk_id,
            page_number=int(page_number) if isinstance(page_number, int) else None,
            field="chunk",
            quote=_clean_text(chunk.get("markdown") or chunk.get("text") or chunk_title, limit=180),
        )
        add_node(
            TopologyNode(
                id=chunk_node_id,
                kind="chunk",
                label=chunk_title,
                role=str(chunk.get("chunk_type") or "document"),
                evidence=(evidence,),
                metadata={
                    "ordinal": int(chunk.get("ordinal") or index),
                    "token_count": int(chunk.get("token_count") or 0),
                    "section_path": list(chunk.get("section_path") or []),
                },
            )
        )
        add_edge(
            TopologyEdge(
                id=_stable_id("edge", document_node_id, "CONTAINS", chunk_node_id),
                source=document_node_id,
                target=chunk_node_id,
                relation="CONTAINS",
                label="문서가 조각을 포함",
                confidence=1.0,
                evidence=(evidence,),
            )
        )

        section_path = [str(part).strip() for part in list(chunk.get("section_path") or []) if str(part).strip()]
        if section_path:
            section_label = " / ".join(section_path[-2:])
            section_node_id = section_node_by_label.setdefault(
                section_label,
                _stable_id("section", document_source_id, parsed_document_id, section_label),
            )
            add_node(
                TopologyNode(
                    id=section_node_id,
                    kind="section",
                    label=_clean_text(section_label, limit=140),
                    role="outline",
                    evidence=(evidence,),
                    metadata={"path": section_path},
                )
            )
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", document_node_id, "CONTAINS", section_node_id),
                    source=document_node_id,
                    target=section_node_id,
                    relation="CONTAINS",
                    label="문서가 섹션을 포함",
                    confidence=1.0,
                    evidence=(evidence,),
                )
            )
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", section_node_id, "CONTAINS", chunk_node_id),
                    source=section_node_id,
                    target=chunk_node_id,
                    relation="CONTAINS",
                    label="섹션이 조각을 포함",
                    confidence=1.0,
                    evidence=(evidence,),
                )
            )

        text = _chunk_text(chunk)
        for concept in _extract_concepts(text):
            concept_count += 1
            concept_node_id = _stable_id("concept", concept)
            add_node(
                TopologyNode(
                    id=concept_node_id,
                    kind="concept",
                    label=concept,
                    role="operational-concept",
                    evidence=(evidence,),
                )
            )
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", chunk_node_id, "MENTIONS", concept_node_id),
                    source=chunk_node_id,
                    target=concept_node_id,
                    relation="MENTIONS",
                    label="조각이 개념을 언급",
                    confidence=0.82,
                    evidence=(evidence,),
                )
            )

        for command in _extract_commands(text):
            command_count += 1
            command_node_id = _stable_id("command", document_source_id, parsed_document_id, command)
            command_evidence = TopologyEvidence(
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                chunk_id=raw_chunk_id,
                page_number=evidence.page_number,
                field="command",
                quote=command,
            )
            add_node(
                TopologyNode(
                    id=command_node_id,
                    kind="command",
                    label=command,
                    role="operational-command",
                    evidence=(command_evidence,),
                )
            )
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", chunk_node_id, "CONTAINS", command_node_id),
                    source=chunk_node_id,
                    target=command_node_id,
                    relation="CONTAINS",
                    label="조각이 명령어를 포함",
                    confidence=0.92,
                    evidence=(command_evidence,),
                )
            )

        for asset_id in [str(item).strip() for item in list(chunk.get("asset_ids") or []) if str(item).strip()]:
            chunk_id_by_asset_id.setdefault(asset_id, []).append(chunk_node_id)

    described_asset_count = 0
    for index, asset in enumerate(asset_rows, start=1):
        raw_asset_id = str(asset.get("asset_id") or asset.get("id") or index)
        asset_node_id = _stable_id("asset", document_source_id, parsed_document_id, raw_asset_id)
        description = _clean_text(
            asset.get("qwen_description") or asset.get("caption_text") or asset.get("ocr_text") or asset.get("filename"),
            limit=180,
        )
        has_description = bool(str(asset.get("qwen_description") or asset.get("caption_text") or asset.get("ocr_text") or "").strip())
        if has_description:
            described_asset_count += 1
        page_number = asset.get("page_number")
        evidence = TopologyEvidence(
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            asset_id=raw_asset_id,
            page_number=int(page_number) if isinstance(page_number, int) else None,
            field="asset",
            quote=description,
        )
        add_node(
            TopologyNode(
                id=asset_node_id,
                kind="asset",
                label=description or f"이미지 {index}",
                role=str(asset.get("asset_type") or "asset"),
                status="described" if has_description else "missing_description",
                evidence=(evidence,),
                metadata={
                    "mime_type": str(asset.get("mime_type") or ""),
                    "storage_key": str(asset.get("storage_key") or ""),
                    "page_number": page_number,
                    "width": asset.get("width"),
                    "height": asset.get("height"),
                },
            )
        )
        add_edge(
            TopologyEdge(
                id=_stable_id("edge", document_node_id, "CONTAINS", asset_node_id),
                source=document_node_id,
                target=asset_node_id,
                relation="CONTAINS",
                label="문서가 이미지를 포함",
                confidence=1.0,
                evidence=(evidence,),
            )
        )
        for chunk_node_id in chunk_id_by_asset_id.get(raw_asset_id, []):
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", asset_node_id, "VISUALIZES", chunk_node_id),
                    source=asset_node_id,
                    target=chunk_node_id,
                    relation="VISUALIZES",
                    label="이미지가 조각 내용을 시각화",
                    confidence=0.86 if has_description else 0.64,
                    evidence=(evidence,),
                )
            )

        for concept in _extract_concepts(_asset_text(asset)):
            concept_node_id = _stable_id("concept", concept)
            add_node(
                TopologyNode(
                    id=concept_node_id,
                    kind="concept",
                    label=concept,
                    role="operational-concept",
                    evidence=(evidence,),
                )
            )
            add_edge(
                TopologyEdge(
                    id=_stable_id("edge", asset_node_id, "MENTIONS", concept_node_id),
                    source=asset_node_id,
                    target=concept_node_id,
                    relation="MENTIONS",
                    label="이미지 설명이 개념을 언급",
                    confidence=0.78 if has_description else 0.55,
                    evidence=(evidence,),
                )
            )

    if gold_build_run:
        grade = str(gold_build_run.get("final_grade") or gold_build_run.get("status") or "judge").strip()
        judge_node_id = _stable_id("judge", document_source_id, parsed_document_id, grade)
        judge_evidence = TopologyEvidence(
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            field="gold_build_run",
            quote=_clean_text(gold_build_run.get("summary") or gold_build_run.get("blocking_message") or grade),
        )
        add_node(
            TopologyNode(
                id=judge_node_id,
                kind="judge",
                label=f"Judge: {grade}",
                role="certification",
                status=grade,
                evidence=(judge_evidence,),
                metadata=gold_build_run,
            )
        )
        add_edge(
            TopologyEdge(
                id=_stable_id("edge", document_node_id, "VALIDATED_BY", judge_node_id),
                source=document_node_id,
                target=judge_node_id,
                relation="VALIDATED_BY",
                label="문서가 Judge 판정을 가짐",
                confidence=1.0,
                evidence=(judge_evidence,),
            )
        )

    node_items = tuple(sorted(nodes.values(), key=_node_sort_key))
    edge_items = tuple(sorted(edges.values(), key=_edge_sort_key))
    node_kind_counts: dict[str, int] = {}
    edge_relation_counts: dict[str, int] = {}
    for node in node_items:
        node_kind_counts[node.kind] = node_kind_counts.get(node.kind, 0) + 1
    for edge in edge_items:
        edge_relation_counts[edge.relation] = edge_relation_counts.get(edge.relation, 0) + 1

    missing_asset_descriptions = max(0, len(asset_rows) - described_asset_count)
    blockers: list[str] = []
    if not chunk_rows:
        blockers.append("문서 조각이 없습니다.")
    if len(asset_rows) > 0 and missing_asset_descriptions > 0:
        blockers.append(f"이미지 {missing_asset_descriptions}개에 설명 근거가 없습니다.")
    if node_kind_counts.get("concept", 0) == 0 and chunk_rows:
        blockers.append("추출된 운영 개념이 없습니다.")
    if not edge_items:
        blockers.append("근거 edge가 없습니다.")
    partial = bool(document.get("has_more")) or int(document.get("total_chunks") or len(chunk_rows) or 0) > len(chunk_rows)

    summary = {
        "state": "needs_review" if blockers else "ready",
        "partial": partial,
        "node_count": len(node_items),
        "edge_count": len(edge_items),
        "node_kind_counts": node_kind_counts,
        "edge_relation_counts": edge_relation_counts,
        "chunk_count": len(chunk_rows),
        "asset_count": len(asset_rows),
        "described_asset_count": described_asset_count,
        "missing_asset_description_count": missing_asset_descriptions,
        "concept_count": node_kind_counts.get("concept", 0),
        "command_count": node_kind_counts.get("command", 0),
        "raw_concept_mentions": concept_count,
        "raw_command_mentions": command_count,
        "blockers": blockers,
    }
    return WikiTopology(
        schema_version=TOPOLOGY_SCHEMA_VERSION,
        document_source_id=document_source_id,
        parsed_document_id=parsed_document_id,
        summary=summary,
        nodes=node_items,
        edges=edge_items,
    )


__all__ = [
    "TOPOLOGY_SCHEMA_VERSION",
    "TopologyEdge",
    "TopologyEvidence",
    "TopologyNode",
    "WikiTopology",
    "build_document_topology",
]
