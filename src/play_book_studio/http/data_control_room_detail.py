"""Control Tower detail helpers for corpus and playbook observability."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.private_corpus import customer_pack_private_chunks_path


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _draft_id_from_book_slug(book_slug: str) -> str:
    slug = str(book_slug or "").strip()
    if not slug:
        return ""
    return slug.split("--", 1)[0].strip() if "--" in slug else slug


def _customer_pack_source_origin_label(record: Any, fallback_title: str = "") -> str:
    uploaded_file_name = str(getattr(record, "uploaded_file_name", "") or "").strip()
    if uploaded_file_name:
        return uploaded_file_name
    request = getattr(record, "request", None)
    request_uri = str(getattr(request, "uri", "") or "").strip()
    if request_uri:
        if "://" not in request_uri:
            name = Path(request_uri).name.strip()
            if name:
                return name
        tail = request_uri.rstrip("/").rsplit("/", 1)[-1].strip()
        if tail:
            return tail
        return request_uri
    plan = getattr(record, "plan", None)
    title = str(getattr(plan, "title", "") or fallback_title).strip()
    return title or fallback_title


def load_customer_pack_private_chunk_rows(
    root_dir: str | Path,
    *,
    draft_records_by_id: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    records = draft_records_by_id or {
        record.draft_id: record
        for record in CustomerPackDraftStore(root).list()
        if str(record.draft_id or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for draft_id in sorted(records):
        rows.extend(_safe_read_jsonl_rows(customer_pack_private_chunks_path(settings, draft_id)))
    return rows


def _base_document_viewer_path(viewer_path: str) -> str:
    raw = str(viewer_path or "").strip()
    if not raw:
        return ""
    return raw.split("#", 1)[0].strip()


def _customer_pack_primary_viewer_path(draft_id: str) -> str:
    normalized = str(draft_id or "").strip()
    if not normalized:
        return ""
    return f"/playbooks/customer-packs/{normalized}/index.html"


def _chunk_payload_row(row: dict[str, Any]) -> dict[str, Any]:
    anchor = str(row.get("anchor_id") or row.get("anchor") or "").strip()
    viewer_path = str(row.get("viewer_path") or "").strip()
    if anchor and viewer_path and "#" not in viewer_path:
        viewer_path = f"{viewer_path}#{anchor}"
    return {
        "chunk_id": str(row.get("chunk_id") or "").strip(),
        "ordinal": _safe_int(row.get("ordinal")),
        "chunk_type": str(row.get("chunk_type") or "reference").strip() or "reference",
        "token_count": _safe_int(row.get("token_count")),
        "chapter": str(row.get("chapter") or "").strip(),
        "section": str(row.get("section") or "").strip(),
        "section_path": [
            str(item).strip()
            for item in (row.get("section_path") or [])
            if str(item).strip()
        ],
        "anchor": anchor,
        "viewer_path": viewer_path,
        "source_url": str(row.get("source_url") or "").strip(),
        "text": str(row.get("text") or "").strip(),
        "cli_commands": [
            str(item).strip()
            for item in (row.get("cli_commands") or [])
            if str(item).strip()
        ],
        "error_strings": [
            str(item).strip()
            for item in (row.get("error_strings") or [])
            if str(item).strip()
        ],
        "k8s_objects": [
            str(item).strip()
            for item in (row.get("k8s_objects") or [])
            if str(item).strip()
        ],
        "operator_names": [
            str(item).strip()
            for item in (row.get("operator_names") or [])
            if str(item).strip()
        ],
        "verification_hints": [
            str(item).strip()
            for item in (row.get("verification_hints") or [])
            if str(item).strip()
        ],
    }


def build_data_control_room_chunk_payload(
    root_dir: str | Path,
    *,
    scope: str,
    book_slug: str,
    draft_id: str = "",
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    normalized_scope = str(scope or "").strip()
    normalized_slug = str(book_slug or "").strip()
    if normalized_scope not in {"runtime", "customer_pack"}:
        raise ValueError("scope must be runtime or customer_pack")
    if not normalized_slug:
        raise ValueError("book_slug is required")

    source_origin_label = ""
    source_origin_url = ""
    runtime_truth_label = ""
    boundary_badge = ""
    vector_status = ""
    corpus_runtime_eligible = False
    effective_draft_id = ""

    if normalized_scope == "runtime":
        chunk_rows = _safe_read_jsonl_rows(settings.chunks_path)
    else:
        effective_draft_id = str(draft_id or _draft_id_from_book_slug(normalized_slug)).strip()
        if not effective_draft_id:
            raise ValueError("draft_id is required for customer_pack scope")
        chunk_rows = _safe_read_jsonl_rows(customer_pack_private_chunks_path(settings, effective_draft_id))
        record = CustomerPackDraftStore(root).get(effective_draft_id)
        if record is not None:
            source_origin_label = _customer_pack_source_origin_label(record)
            source_origin_url = f"/api/customer-packs/captured?draft_id={effective_draft_id}"
            runtime_truth_label = "Customer Source-First Pack"
            boundary_badge = "Private Pack Runtime"
            vector_status = str(getattr(record, "private_corpus_vector_status", "") or "").strip()
            corpus_runtime_eligible = str(getattr(record, "private_corpus_status", "") or "").strip() == "ready"

    filtered = [
        row
        for row in chunk_rows
        if str(row.get("book_slug") or "").strip() == normalized_slug
    ]
    if not filtered and normalized_scope == "customer_pack" and effective_draft_id:
        primary_viewer_path = _customer_pack_primary_viewer_path(effective_draft_id)
        filtered = [
            row
            for row in chunk_rows
            if _base_document_viewer_path(str(row.get("viewer_path") or "")) == primary_viewer_path
        ]
    if not filtered:
        raise FileNotFoundError(f"chunk rows not found for {normalized_slug}")

    chunks = sorted(
        (_chunk_payload_row(row) for row in filtered),
        key=lambda item: (
            int(item.get("ordinal") or 0),
            " > ".join(item.get("section_path") or []),
            str(item.get("chunk_id") or ""),
        ),
    )
    chunk_type_breakdown = Counter(str(item.get("chunk_type") or "reference") for item in chunks)
    first = chunks[0]
    first_row = filtered[0]
    title = (
        str(first_row.get("book_title") or "").strip()
        or str(first_row.get("title") or "").strip()
        or normalized_slug
    )
    document_viewer_path = _base_document_viewer_path(str(first.get("viewer_path") or ""))
    top_source_url = str(first.get("source_url") or first_row.get("source_url") or "").strip()
    source_origin_label = source_origin_label or str(
        first_row.get("source_origin_label")
        or first_row.get("current_source_label")
        or first_row.get("source_collection")
        or title
    ).strip()
    if not source_origin_url:
        source_origin_url = str(first_row.get("source_origin_url") or top_source_url).strip()
    runtime_truth_label = runtime_truth_label or str(first_row.get("runtime_truth_label") or "").strip()
    boundary_badge = boundary_badge or str(first_row.get("boundary_badge") or "").strip()
    vector_status = vector_status or str(first_row.get("corpus_vector_status") or "").strip()
    corpus_runtime_eligible = bool(corpus_runtime_eligible or first_row.get("corpus_runtime_eligible"))
    return {
        "scope": normalized_scope,
        "scope_label": "User Corpus" if normalized_scope == "customer_pack" else "Runtime Corpus",
        "book_slug": normalized_slug,
        "title": title,
        "draft_id": effective_draft_id,
        "document_viewer_path": document_viewer_path,
        "source_lane": str(first_row.get("source_lane") or "").strip(),
        "source_type": str(first_row.get("source_type") or "").strip(),
        "source_collection": str(first_row.get("source_collection") or "").strip(),
        "source_origin_label": source_origin_label,
        "source_origin_url": source_origin_url,
        "runtime_truth_label": runtime_truth_label,
        "boundary_badge": boundary_badge,
        "vector_status": vector_status,
        "corpus_runtime_eligible": corpus_runtime_eligible,
        "chunk_count": len(chunks),
        "token_total": sum(_safe_int(item.get("token_count")) for item in chunks),
        "command_chunk_count": sum(1 for item in chunks if item.get("cli_commands")),
        "error_chunk_count": sum(1 for item in chunks if item.get("error_strings")),
        "chunk_type_breakdown": dict(sorted(chunk_type_breakdown.items())),
        "chunks": chunks,
    }


__all__ = [
    "build_data_control_room_chunk_payload",
    "load_customer_pack_private_chunk_rows",
]
