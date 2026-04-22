# 업로드 문서를 retrieval overlay 인덱스로 바꾸는 보조 로직이다.
# canonical book JSON을 읽어서 BM25 overlay와 draft 선택 필터를 준비한다.
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.sentence_model import load_sentence_model
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.service import evaluate_canonical_book_quality
from play_book_studio.intake.private_corpus import (
    customer_pack_private_bm25_path,
    customer_pack_private_manifest_path,
    customer_pack_private_vector_path,
)

from .bm25 import BM25Index
from .models import RetrievalHit, SessionContext
from .vector import hit_from_payload

CUSTOMER_PACK_VIEWER_PATH_RE = re.compile(r"^/playbooks/customer-packs/([^/]+)/")


def draft_id_from_intake_hit(hit: RetrievalHit) -> str:
    viewer_path = str(hit.viewer_path or "").strip()
    match = CUSTOMER_PACK_VIEWER_PATH_RE.match(viewer_path)
    if match:
        return match.group(1).strip()
    chunk_id = str(hit.chunk_id or "").strip()
    if ":" in chunk_id:
        return chunk_id.split(":", 1)[0].strip()
    return ""


def filter_customer_pack_hits_by_selection(
    hits: list[RetrievalHit],
    *,
    context: SessionContext | None = None,
    allowed_draft_ids: tuple[str, ...] | None = None,
) -> list[RetrievalHit]:
    context = context or SessionContext()
    if not context.restrict_uploaded_sources:
        return hits
    selected = (
        {str(draft_id).strip() for draft_id in allowed_draft_ids if str(draft_id).strip()}
        if allowed_draft_ids is not None
        else {
            str(draft_id).strip()
            for draft_id in context.selected_draft_ids
            if str(draft_id).strip()
        }
    )
    if not selected:
        return []
    return [hit for hit in hits if draft_id_from_intake_hit(hit) in selected]


def has_active_customer_pack_selection(context: SessionContext | None = None) -> bool:
    context = context or SessionContext()
    if not context.restrict_uploaded_sources:
        return False
    return any(str(draft_id).strip() for draft_id in context.selected_draft_ids)


def _selected_draft_ids(context: SessionContext | None = None) -> tuple[str, ...]:
    context = context or SessionContext()
    if not context.restrict_uploaded_sources:
        return ()
    return tuple(
        str(draft_id).strip()
        for draft_id in context.selected_draft_ids
        if str(draft_id).strip()
    )


def _runtime_eligible_selected_draft_ids(
    settings: Settings,
    context: SessionContext | None = None,
) -> tuple[str, ...]:
    selected = _selected_draft_ids(context)
    if not selected:
        return ()
    eligible: list[str] = []
    for draft_id in selected:
        manifest_path = customer_pack_private_manifest_path(settings, draft_id)
        if not manifest_path.exists():
            continue
        manifest = _json_payload(manifest_path)
        summary = summarize_private_runtime_boundary(manifest)
        if bool(summary.get("runtime_eligible")):
            eligible.append(draft_id)
    return tuple(eligible)


def customer_pack_books_fingerprint(books_dir: Path) -> tuple[tuple[str, int], ...]:
    if not books_dir.exists():
        return ()
    return tuple(
        sorted(
            (path.name, path.stat().st_mtime_ns)
            for path in books_dir.glob("*.json")
            if path.is_file()
        )
    )


@lru_cache(maxsize=32)
def _read_jsonl_rows(path_str: str, mtime_ns: int) -> list[dict[str, Any]]:
    del mtime_ns
    path = Path(path_str)
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@lru_cache(maxsize=32)
def _read_json_payload(path_str: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl_rows(str(path), path.stat().st_mtime_ns)


def _json_payload(path: Path) -> dict[str, Any]:
    return _read_json_payload(str(path), path.stat().st_mtime_ns)


def load_selected_customer_pack_private_bm25_index(
    settings: Settings,
    *,
    context: SessionContext | None = None,
) -> BM25Index | None:
    selected = _runtime_eligible_selected_draft_ids(settings, context)
    if not selected:
        return None
    rows: list[dict[str, Any]] = []
    for draft_id in selected:
        path = customer_pack_private_bm25_path(settings, draft_id)
        if not path.exists():
            continue
        rows.extend(_jsonl_rows(path))
    if not rows:
        return None
    return BM25Index.from_rows(rows)


def _encode_query_vector_locally(settings: Settings, query: str) -> list[float]:
    model = load_sentence_model(settings.embedding_model, settings.embedding_device)
    encoded = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return list(map(float, encoded[0].tolist()))


def _cosine_score(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def search_selected_customer_pack_private_vectors(
    settings: Settings,
    *,
    context: SessionContext | None = None,
    query: str,
    top_k: int,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    requested = _selected_draft_ids(context)
    selected = _runtime_eligible_selected_draft_ids(settings, context)
    blocked_count = max(len(requested) - len(selected), 0)
    if not selected:
        return [], {
            "status": "blocked" if requested else "inactive",
            "selected_draft_count": len(requested),
            "eligible_selected_draft_count": 0,
            "blocked_draft_count": blocked_count,
            "hit_count": 0,
        }
    rows: list[dict[str, Any]] = []
    manifest_statuses: list[str] = []
    for draft_id in selected:
        manifest_path = customer_pack_private_manifest_path(settings, draft_id)
        if manifest_path.exists():
            manifest_payload = _json_payload(manifest_path)
            manifest_statuses.append(str(manifest_payload.get("vector_status") or "missing"))
        vector_path = customer_pack_private_vector_path(settings, draft_id)
        if not vector_path.exists():
            continue
        rows.extend(_jsonl_rows(vector_path))
    if not rows:
        status = "missing"
        if manifest_statuses and all(item == "skipped" for item in manifest_statuses):
            status = "skipped"
        return [], {
            "status": status,
            "selected_draft_count": len(requested),
            "eligible_selected_draft_count": len(selected),
            "blocked_draft_count": blocked_count,
            "manifest_vector_statuses": manifest_statuses,
            "hit_count": 0,
        }
    try:
        query_vector = _encode_query_vector_locally(settings, query)
    except Exception as exc:  # noqa: BLE001
        return [], {
            "status": "error",
            "selected_draft_count": len(requested),
            "eligible_selected_draft_count": len(selected),
            "blocked_draft_count": blocked_count,
            "manifest_vector_statuses": manifest_statuses,
            "error": str(exc),
            "hit_count": 0,
        }
    scored: list[tuple[float, RetrievalHit]] = []
    for row in rows:
        vector = [float(item) for item in (row.get("vector") or [])]
        score = _cosine_score(query_vector, vector)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                hit_from_payload(row, source="private_vector", score=score),
            )
        )
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].book_slug,
            item[1].chunk_id,
        )
    )
    hits = [hit for _, hit in scored[:top_k]]
    return hits, {
        "status": "ready",
        "selected_draft_count": len(requested),
        "eligible_selected_draft_count": len(selected),
        "blocked_draft_count": blocked_count,
        "manifest_vector_statuses": manifest_statuses,
        "hit_count": len(hits),
        "top_score": float(scored[0][0]) if scored else None,
    }


def customer_pack_row_from_section(
    payload: dict[str, object],
    section: dict[str, object],
    *,
    draft_id: str,
) -> dict[str, str]:
    anchor = str(section.get("anchor") or "").strip()
    viewer_path = str(section.get("viewer_path") or "").strip()
    if not viewer_path:
        viewer_path = f"/playbooks/customer-packs/{draft_id}/index.html"
        if anchor:
            viewer_path = f"{viewer_path}#{anchor}"
    section_path = [
        str(item).strip()
        for item in (section.get("section_path") or [])
        if str(item).strip()
    ]
    title = str(payload.get("title") or payload.get("book_slug") or draft_id).strip()
    return {
        "chunk_id": f"{draft_id}:{str(section.get('section_key') or anchor or section.get('ordinal') or 'section').strip()}",
        "book_slug": str(payload.get("book_slug") or draft_id).strip(),
        "chapter": section_path[0] if section_path else title,
        "section": str(section.get("heading") or section.get("section_path_label") or title).strip(),
        "section_path": section_path,
        "anchor": anchor,
        "source_url": str(section.get("source_url") or payload.get("source_uri") or "").strip(),
        "viewer_path": viewer_path,
        "text": str(section.get("text") or "").strip(),
        "source_id": f"customer_pack:{draft_id}",
        "source_lane": "customer_pack",
        "source_type": str(payload.get("playbook_family") or payload.get("source_type") or "customer_pack").strip(),
        "source_collection": "uploaded",
        "review_status": str(payload.get("quality_status") or "ready").strip() or "ready",
        "trust_score": 1.0,
        "semantic_role": str(section.get("semantic_role") or "unknown").strip(),
        "block_kinds": list(section.get("block_kinds") or []),
    }


@lru_cache(maxsize=4)
def load_customer_pack_overlay_index(
    books_dir_str: str,
    fingerprint: tuple[tuple[str, int], ...],
) -> BM25Index | None:
    del fingerprint
    books_dir = Path(books_dir_str)
    rows: list[dict[str, str]] = []
    for path in sorted(books_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(evaluate_canonical_book_quality(payload).get("quality_status") or "review") != "ready":
            continue
        sections = [
            dict(section)
            for section in (payload.get("sections") or [])
            if isinstance(section, dict)
        ]
        draft_id = path.stem
        for section in sections:
            row = customer_pack_row_from_section(payload, section, draft_id=draft_id)
            if row["text"]:
                rows.append(row)
    if not rows:
        return None
    return BM25Index.from_rows(rows)
