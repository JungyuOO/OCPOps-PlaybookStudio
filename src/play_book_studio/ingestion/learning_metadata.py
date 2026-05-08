"""Learning metadata helpers for corpus-backed RAG documents."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from play_book_studio.ingestion.document_parsing import DocumentChunk, ParsedUploadDocument


CATEGORY_ORDER = {
    "wiki": 10,
    "install": 20,
    "operations": 30,
    "networking": 40,
    "storage": 50,
    "security": 60,
    "observability": 70,
    "troubleshooting": 80,
    "repository": 90,
}

CATEGORY_LABELS = {
    "wiki": "Wiki",
    "install": "Install",
    "operations": "Operations",
    "networking": "Networking",
    "storage": "Storage",
    "security": "Security",
    "observability": "Observability",
    "troubleshooting": "Troubleshooting",
    "repository": "Repository",
}

_CATEGORY_KEYWORDS = (
    ("install", ("install", "installer", "ipi", "upi", "bootstrap", "cluster-install")),
    ("operations", ("operation", "operator", "node", "pod", "deployment", "workload", "scale", "rollout")),
    ("networking", ("network", "route", "ingress", "egress", "dns", "ovn", "sdn", "service")),
    ("storage", ("storage", "pv", "pvc", "persistent", "ceph", "odf", "volume")),
    ("security", ("security", "auth", "oauth", "rbac", "scc", "certificate", "secret")),
    ("observability", ("monitor", "observability", "logging", "metric", "alert", "prometheus")),
    ("troubleshooting", ("trouble", "debug", "diagnostic", "must-gather", "failure", "error")),
)


def build_learning_document_index(relative_paths: tuple[str, ...], *, corpus_kind: str) -> dict[str, dict[str, Any]]:
    """Build deterministic document-level learning metadata for a corpus import batch."""

    nodes: list[dict[str, Any]] = []
    for ordinal, relative_path in enumerate(relative_paths, start=1):
        category_key = infer_category_key(relative_path)
        nodes.append(
            {
                "relative_path": relative_path,
                "book_slug": _book_slug(relative_path),
                "category_key": category_key,
                "category_label": CATEGORY_LABELS.get(category_key, "Wiki"),
                "stage_order": CATEGORY_ORDER.get(category_key, 100) * 1000 + ordinal,
                "stage_id": f"{category_key}-{ordinal:03d}",
                "title_hint": _title_hint(Path(relative_path)),
            }
        )

    sorted_nodes = sorted(nodes, key=lambda item: (int(item["stage_order"]), str(item["book_slug"])))
    node_by_path = {str(item["relative_path"]): item for item in sorted_nodes}
    for index, item in enumerate(sorted_nodes):
        previous_item = sorted_nodes[index - 1] if index > 0 else None
        next_item = sorted_nodes[index + 1] if index + 1 < len(sorted_nodes) else None
        item["learning"] = {
            "track": "ocp-foundation" if _normalize_corpus_kind(corpus_kind) == "official_docs" else "workspace-study",
            "stage_id": item["stage_id"],
            "stage_order": item["stage_order"],
            "difficulty": "beginner",
            "persona": ["beginner", "platform-admin"],
            "estimated_minutes": 15,
            "prerequisite_refs": [_document_ref(previous_item, "이전 학습 단계") for previous_item in [previous_item] if previous_item],
            "next_refs": [_document_ref(next_item, "다음 학습 단계") for next_item in [next_item] if next_item],
            "related_refs": _related_refs(item, sorted_nodes),
            "lab_refs": [],
        }
    return node_by_path


def build_learning_book_index(book_slugs: tuple[str, ...], *, corpus_kind: str) -> dict[str, dict[str, Any]]:
    """Build learning metadata keyed by official book slug."""

    exact_slugs = tuple(str(slug or "").strip() for slug in book_slugs if str(slug or "").strip())
    nodes: list[dict[str, Any]] = []
    for ordinal, slug in enumerate(exact_slugs, start=1):
        category_key = infer_category_key(slug)
        nodes.append(
            {
                "relative_path": f"{slug}.json",
                "book_slug": slug,
                "category_key": category_key,
                "category_label": CATEGORY_LABELS.get(category_key, "Wiki"),
                "stage_order": CATEGORY_ORDER.get(category_key, 100) * 1000 + ordinal,
                "stage_id": f"{category_key}-{ordinal:03d}",
                "title_hint": _title_hint(Path(slug)),
            }
        )
    sorted_nodes = sorted(nodes, key=lambda item: (int(item["stage_order"]), str(item["book_slug"])))
    for index, item in enumerate(sorted_nodes):
        previous_item = sorted_nodes[index - 1] if index > 0 else None
        next_item = sorted_nodes[index + 1] if index + 1 < len(sorted_nodes) else None
        item["learning"] = {
            "track": "ocp-foundation" if _normalize_corpus_kind(corpus_kind) == "official_docs" else "workspace-study",
            "stage_id": item["stage_id"],
            "stage_order": item["stage_order"],
            "difficulty": "beginner",
            "persona": ["beginner", "platform-admin"],
            "estimated_minutes": 15,
            "prerequisite_refs": [_document_ref(previous_item, "이전 학습 단계") for previous_item in [previous_item] if previous_item],
            "next_refs": [_document_ref(next_item, "다음 학습 단계") for next_item in [next_item] if next_item],
            "related_refs": _related_refs(item, sorted_nodes),
            "lab_refs": [],
        }
    return {str(node["book_slug"]): node for node in sorted_nodes}


def attach_learning_metadata(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...],
    *,
    relative_path: str,
    corpus_kind: str,
    document_index: dict[str, dict[str, Any]],
) -> tuple[ParsedUploadDocument, tuple[DocumentChunk, ...]]:
    node = document_index.get(relative_path) or _fallback_node(relative_path, corpus_kind)
    document_learning = dict(node.get("learning") or {})
    document_metadata = {
        **dict(parsed.metadata),
        "book_slug": node["book_slug"],
        "book_title": _document_title(parsed, str(node.get("title_hint") or "")),
        "category_key": node["category_key"],
        "category_label": node["category_label"],
        "source_scope": _source_scope(corpus_kind),
        "learning": document_learning,
    }
    enriched_chunks = tuple(
        replace(
            chunk,
            metadata={
                **dict(chunk.metadata),
                "book_slug": node["book_slug"],
                "category_key": node["category_key"],
                "category_label": node["category_label"],
                "learning": _chunk_learning_metadata(chunk, document_learning),
            },
        )
        for chunk in chunks
    )
    return replace(parsed, metadata=document_metadata), enriched_chunks


def infer_category_key(relative_path: str) -> str:
    lowered = str(relative_path or "").lower().replace("\\", "/")
    token_blob = " ".join(part for part in re.split(r"[/_.\-\s]+", lowered) if part)
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in token_blob for keyword in keywords):
            return category
    return "wiki"


def _normalize_corpus_kind(corpus_kind: str) -> str:
    normalized = str(corpus_kind or "").strip().lower().replace("-", "_")
    return "official_docs" if normalized in {"official", "official_docs"} else "study_docs"


def _source_scope(corpus_kind: str) -> str:
    return "official_docs" if _normalize_corpus_kind(corpus_kind) == "official_docs" else "study_docs"


def _book_slug(relative_path: str) -> str:
    stem = Path(str(relative_path or "document")).with_suffix("").as_posix().lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", stem).strip("-")
    return slug or "document"


def _title_hint(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def _document_title(parsed: ParsedUploadDocument, fallback: str) -> str:
    for block in parsed.blocks:
        if block.block_type == "heading" and block.text.strip():
            return block.text.strip()
    return fallback or parsed.filename


def _document_ref(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "ref_type": "document",
        "relation": "next" if reason.startswith("다음") else "prerequisite",
        "book_slug": str(item.get("book_slug") or ""),
        "category_key": str(item.get("category_key") or ""),
        "stage_id": str(item.get("stage_id") or ""),
        "reason": reason,
    }


def _related_refs(item: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    category_key = str(item.get("category_key") or "")
    refs: list[dict[str, Any]] = []
    for candidate in nodes:
        if candidate is item or candidate.get("category_key") != category_key:
            continue
        refs.append(
            {
                "ref_type": "document",
                "relation": "related",
                "book_slug": str(candidate.get("book_slug") or ""),
                "category_key": category_key,
                "stage_id": str(candidate.get("stage_id") or ""),
                "reason": "같은 학습 카테고리의 보조 문서",
            }
        )
        if len(refs) >= 3:
            break
    return refs


def _chunk_learning_metadata(chunk: DocumentChunk, document_learning: dict[str, Any]) -> dict[str, Any]:
    heading = chunk.heading_title or (chunk.toc_path[-1] if chunk.toc_path else "")
    return build_chunk_learning_metadata(
        document_learning,
        ordinal=chunk.ordinal,
        section_number=chunk.section_number,
        heading=heading,
        text=chunk.embedding_text,
    )


def build_chunk_learning_metadata(
    document_learning: dict[str, Any],
    *,
    ordinal: int,
    section_number: str = "",
    heading: str = "",
    text: str = "",
) -> dict[str, Any]:
    return {
        "track": document_learning.get("track"),
        "stage_id": document_learning.get("stage_id"),
        "stage_order": document_learning.get("stage_order"),
        "section_role": "step" if section_number or heading else "context",
        "step_order": int(ordinal) + 1,
        "user_goal": heading,
        "next_refs": list(document_learning.get("next_refs") or []),
        "related_refs": list(document_learning.get("related_refs") or []),
        "command_hints": _command_hints(text),
    }


def _command_hints(text: str) -> list[str]:
    commands: list[str] = []
    for match in re.finditer(r"`([^`]*(?:oc|kubectl)\s+[^`]*)`", text or ""):
        command = match.group(1).strip()
        if command and command not in commands:
            commands.append(command)
        if len(commands) >= 5:
            break
    for match in re.finditer(r"\b((?:oc|kubectl)\s+[A-Za-z0-9_.:/=\- ]+)", text or ""):
        command = match.group(1).strip().rstrip(".,;")
        if command and command not in commands:
            commands.append(command)
        if len(commands) >= 5:
            break
    return commands


def _fallback_node(relative_path: str, corpus_kind: str) -> dict[str, Any]:
    category_key = infer_category_key(relative_path)
    node = {
        "relative_path": relative_path,
        "book_slug": _book_slug(relative_path),
        "category_key": category_key,
        "category_label": CATEGORY_LABELS.get(category_key, "Wiki"),
        "stage_id": f"{category_key}-001",
        "stage_order": CATEGORY_ORDER.get(category_key, 100) * 1000 + 1,
        "title_hint": _title_hint(Path(relative_path)),
    }
    node["learning"] = {
        "track": "ocp-foundation" if _normalize_corpus_kind(corpus_kind) == "official_docs" else "workspace-study",
        "stage_id": node["stage_id"],
        "stage_order": node["stage_order"],
        "difficulty": "beginner",
        "persona": ["beginner", "platform-admin"],
        "estimated_minutes": 15,
        "prerequisite_refs": [],
        "next_refs": [],
        "related_refs": [],
        "lab_refs": [],
    }
    return node


__all__ = [
    "attach_learning_metadata",
    "build_chunk_learning_metadata",
    "build_learning_book_index",
    "build_learning_document_index",
    "infer_category_key",
]
