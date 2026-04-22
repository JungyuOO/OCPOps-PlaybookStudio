from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.ingestion.chunking import chunk_sections
from play_book_studio.ingestion.models import NormalizedSection
from play_book_studio.ingestion.sentence_model import load_sentence_model
from play_book_studio.intake.models import CustomerPackDraftRecord
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary


PRIVATE_CORPUS_VERSION = "customer_private_corpus_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def customer_pack_private_corpus_dir(settings: Settings, draft_id: str) -> Path:
    return settings.customer_pack_corpus_dir / str(draft_id).strip()


def customer_pack_private_chunks_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "chunks.jsonl"


def customer_pack_private_bm25_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "bm25_corpus.jsonl"


def customer_pack_private_vector_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "vector_store.jsonl"


def customer_pack_private_manifest_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "manifest.json"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _review_status(record: CustomerPackDraftRecord) -> str:
    approval_state = str(record.approval_state or "").strip()
    if approval_state == "approved":
        return "approved"
    if approval_state == "rejected":
        return "rejected"
    if approval_state == "review_required":
        return "needs_review"
    return "unreviewed"


def _record_access_groups(record: CustomerPackDraftRecord) -> tuple[str, ...]:
    explicit = tuple(str(item).strip() for item in (record.access_groups or ()) if str(item).strip())
    if explicit:
        return explicit
    fallback = (
        str(record.workspace_id or "").strip() or "default-workspace",
        str(record.tenant_id or "").strip() or "default-tenant",
    )
    return tuple(item for item in fallback if item)


def _section_to_normalized_section(
    payload: dict[str, Any],
    section: dict[str, Any],
    *,
    record: CustomerPackDraftRecord,
) -> NormalizedSection:
    title = str(payload.get("title") or payload.get("book_slug") or record.draft_id).strip() or record.draft_id
    heading = str(section.get("heading") or title).strip() or title
    language_hint = str(payload.get("language_hint") or "ko").strip() or "ko"
    section_path = [
        str(item).strip()
        for item in (section.get("section_path") or [])
        if str(item).strip()
    ]
    provider_egress_policy = str(record.provider_egress_policy or "").strip() or "local_only"
    source_type = str(payload.get("playbook_family") or payload.get("source_type") or "customer_pack").strip()
    return NormalizedSection(
        book_slug=str(payload.get("book_slug") or record.draft_id).strip() or record.draft_id,
        book_title=title,
        heading=heading,
        section_level=int(section.get("section_level") or 2),
        section_path=section_path,
        anchor=str(section.get("anchor") or "").strip(),
        source_url=str(section.get("source_url") or payload.get("source_uri") or "").strip(),
        viewer_path=str(section.get("viewer_path") or "").strip(),
        text=str(section.get("text") or "").strip(),
        section_id=str(section.get("section_key") or section.get("anchor") or "").strip(),
        semantic_role=str(section.get("semantic_role") or "unknown").strip() or "unknown",
        block_kinds=tuple(str(item) for item in (section.get("block_kinds") or []) if str(item).strip()),
        source_language=language_hint,
        display_language=language_hint,
        translation_status="approved_ko" if language_hint == "ko" else "original",
        translation_stage="approved_ko" if language_hint == "ko" else "original",
        source_id=f"customer_pack:{record.draft_id}",
        source_lane=str(record.source_lane or "customer_source_first_pack").strip() or "customer_source_first_pack",
        source_type=source_type,
        source_collection="uploaded",
        product=str(payload.get("inferred_product") or "customer_pack").strip() or "customer_pack",
        version=str(payload.get("inferred_version") or record.draft_id).strip() or record.draft_id,
        locale=language_hint,
        original_title=title,
        review_status=_review_status(record),
        trust_score=1.0,
        verifiability="anchor_backed",
        updated_at=str(record.updated_at or ""),
        parsed_artifact_id=f"customer-pack:{record.draft_id}",
        tenant_id=str(record.tenant_id or "").strip() or "default-tenant",
        workspace_id=str(record.workspace_id or "").strip() or "default-workspace",
        parent_pack_id=str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}",
        pack_version=str(record.draft_id),
        bundle_scope="customer_pack",
        classification=str(record.classification or "").strip() or "private",
        access_groups=_record_access_groups(record),
        provider_egress_policy=provider_egress_policy,
        approval_state=str(record.approval_state or "").strip() or "unreviewed",
        publication_state=str(record.publication_state or "").strip() or "draft",
        redaction_state=str(record.redaction_state or "").strip() or "raw",
        cli_commands=tuple(str(item) for item in (section.get("cli_commands") or []) if str(item).strip()),
        error_strings=tuple(str(item) for item in (section.get("error_strings") or []) if str(item).strip()),
        k8s_objects=tuple(str(item) for item in (section.get("k8s_objects") or []) if str(item).strip()),
        operator_names=tuple(str(item) for item in (section.get("operator_names") or []) if str(item).strip()),
        verification_hints=tuple(str(item) for item in (section.get("verification_hints") or []) if str(item).strip()),
    )


def _bm25_row(chunk_row: dict[str, Any]) -> dict[str, Any]:
    chunk_type = str(chunk_row.get("chunk_type", "reference"))
    return {
        "chunk_id": chunk_row["chunk_id"],
        "book_slug": chunk_row["book_slug"],
        "chapter": chunk_row["chapter"],
        "section": chunk_row["section"],
        "anchor": chunk_row["anchor"],
        "source_url": chunk_row["source_url"],
        "viewer_path": chunk_row["viewer_path"],
        "text": chunk_row["text"],
        "section_path": list(chunk_row.get("section_path") or []),
        "chunk_type": chunk_type,
        "source_id": chunk_row["source_id"],
        "source_lane": chunk_row["source_lane"],
        "source_type": chunk_row["source_type"],
        "source_collection": chunk_row["source_collection"],
        "product": chunk_row["product"],
        "version": chunk_row["version"],
        "locale": chunk_row["locale"],
        "translation_status": chunk_row["translation_status"],
        "review_status": chunk_row["review_status"],
        "trust_score": chunk_row["trust_score"],
        "semantic_role": (
            "procedure"
            if chunk_type in {"procedure", "command"}
            else ("concept" if chunk_type == "concept" else "reference")
        ),
        "cli_commands": list(chunk_row.get("cli_commands") or []),
        "error_strings": list(chunk_row.get("error_strings") or []),
        "k8s_objects": list(chunk_row.get("k8s_objects") or []),
        "operator_names": list(chunk_row.get("operator_names") or []),
        "verification_hints": list(chunk_row.get("verification_hints") or []),
    }


def _encode_texts_locally(
    settings: Settings,
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []
    model = load_sentence_model(settings.embedding_model, settings.embedding_device)
    encoded = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [list(map(float, row.tolist())) for row in encoded]


def _failed_private_corpus_payload(
    *,
    error: str,
    book_count: int,
) -> dict[str, Any]:
    return {
        "normalized_sections": [],
        "chunk_rows": [],
        "bm25_rows": [],
        "vector_rows": [],
        "materialization_status": "failed",
        "materialization_error": str(error or "").strip(),
        "vector_status": "materialization_failed",
        "vector_error": "",
        "book_count": int(book_count),
    }


def build_customer_pack_private_corpus_rows(
    *,
    settings: Settings,
    record: CustomerPackDraftRecord,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    payloads = [dict(canonical_payload), *[dict(item) for item in derived_payloads]]
    normalized_sections: list[NormalizedSection] = []
    for payload in payloads:
        sections = [
            dict(section)
            for section in (payload.get("sections") or [])
            if isinstance(section, dict)
        ]
        for section in sections:
            text = str(section.get("text") or "").strip()
            if not text:
                continue
            normalized_sections.append(
                _section_to_normalized_section(payload, section, record=record)
            )
    materialization_status = "empty"
    materialization_error = ""
    chunks = []
    chunk_rows: list[dict[str, Any]] = []
    bm25_rows: list[dict[str, Any]] = []
    if normalized_sections:
        try:
            chunks = chunk_sections(normalized_sections, settings)
            chunk_rows = [chunk.to_dict() for chunk in chunks]
            bm25_rows = [_bm25_row(row) for row in chunk_rows]
            materialization_status = "ready" if chunk_rows else "empty"
        except Exception as exc:  # noqa: BLE001
            materialization_status = "failed"
            materialization_error = str(exc)
    vector_rows: list[dict[str, Any]] = []
    vector_status = "skipped"
    vector_error = ""
    if chunk_rows:
        try:
            vectors = _encode_texts_locally(settings, [str(chunk.text) for chunk in chunks])
            vector_rows = [
                {
                    **row,
                    "vector": vector,
                }
                for row, vector in zip(chunk_rows, vectors, strict=False)
            ]
            vector_status = "ready"
        except Exception as exc:  # noqa: BLE001
            vector_status = "skipped"
            vector_error = str(exc)
    return {
        "normalized_sections": [section.to_dict() for section in normalized_sections],
        "chunk_rows": chunk_rows,
        "bm25_rows": bm25_rows,
        "vector_rows": vector_rows,
        "materialization_status": materialization_status,
        "materialization_error": materialization_error,
        "vector_status": vector_status,
        "vector_error": vector_error,
        "book_count": len(payloads),
    }


def materialize_customer_pack_private_corpus(
    root_dir: str | Path,
    *,
    record: CustomerPackDraftRecord,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    draft_id = str(record.draft_id).strip()
    corpus_dir = customer_pack_private_corpus_dir(settings, draft_id)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = build_customer_pack_private_corpus_rows(
            settings=settings,
            record=record,
            canonical_payload=canonical_payload,
            derived_payloads=derived_payloads,
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failed_private_corpus_payload(
            error=str(exc),
            book_count=1 + len(derived_payloads),
        )
    chunk_rows = payload["chunk_rows"]
    bm25_rows = payload["bm25_rows"]
    vector_rows = payload["vector_rows"]
    _write_jsonl(customer_pack_private_chunks_path(settings, draft_id), chunk_rows)
    _write_jsonl(customer_pack_private_bm25_path(settings, draft_id), bm25_rows)
    if vector_rows:
        _write_jsonl(customer_pack_private_vector_path(settings, draft_id), vector_rows)
    else:
        customer_pack_private_vector_path(settings, draft_id).unlink(missing_ok=True)
    manifest = {
        "artifact_version": PRIVATE_CORPUS_VERSION,
        "draft_id": draft_id,
        "tenant_id": str(record.tenant_id or "").strip() or "default-tenant",
        "workspace_id": str(record.workspace_id or "").strip() or "default-workspace",
        "pack_id": str(record.plan.pack_id or "").strip() or f"customer-pack:{draft_id}",
        "pack_version": draft_id,
        "classification": str(record.classification or "").strip() or "private",
        "access_groups": list(_record_access_groups(record)),
        "provider_egress_policy": str(record.provider_egress_policy or "").strip() or "local_only",
        "approval_state": str(record.approval_state or "").strip() or "unreviewed",
        "publication_state": str(record.publication_state or "").strip() or "draft",
        "redaction_state": str(record.redaction_state or "").strip() or "raw",
        "source_lane": str(record.source_lane or "customer_source_first_pack").strip() or "customer_source_first_pack",
        "source_collection": "uploaded",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
        "book_count": int(payload["book_count"]),
        "section_count": len(payload["normalized_sections"]),
        "materialization_status": str(payload["materialization_status"]),
        "materialization_error": str(payload["materialization_error"] or ""),
        "chunk_count": len(chunk_rows),
        "bm25_ready": bool(bm25_rows),
        "vector_status": str(payload["vector_status"]),
        "vector_chunk_count": len(vector_rows),
        "vector_error": str(payload["vector_error"] or ""),
        "updated_at": _utc_now(),
    }
    boundary_summary = summarize_private_runtime_boundary(manifest)
    manifest["runtime_eligible"] = bool(boundary_summary["runtime_eligible"])
    manifest["boundary_fail_reasons"] = list(boundary_summary["fail_reasons"])
    customer_pack_private_manifest_path(settings, draft_id).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def delete_customer_pack_private_corpus(root_dir: str | Path, draft_id: str) -> None:
    settings = load_settings(root_dir)
    corpus_dir = customer_pack_private_corpus_dir(settings, draft_id)
    if not corpus_dir.exists():
        return
    for path in sorted(corpus_dir.glob("*")):
        path.unlink(missing_ok=True)
    corpus_dir.rmdir()


__all__ = [
    "PRIVATE_CORPUS_VERSION",
    "build_customer_pack_private_corpus_rows",
    "customer_pack_private_bm25_path",
    "customer_pack_private_chunks_path",
    "customer_pack_private_corpus_dir",
    "customer_pack_private_manifest_path",
    "customer_pack_private_vector_path",
    "delete_customer_pack_private_corpus",
    "materialize_customer_pack_private_corpus",
]
