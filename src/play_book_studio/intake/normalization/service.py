from __future__ import annotations

# captured source를 canonical study asset으로 바꾸는 normalize service 구현.

import json
from datetime import datetime, timezone
from pathlib import Path

from play_book_studio.config.settings import load_settings

from ..artifact_bundle import build_customer_pack_artifact_bundle, write_json_payload
from ..books.store import CustomerPackDraftStore
from ..models import CustomerPackDraftRecord
from ..pptx_ocr_augment import augment_slide_packets_with_optional_ocr
from ..pptx_slide_packets import build_customer_pack_slide_packets_payload
from ..planner import CustomerPackPlanner
from ..private_boundary import summarize_private_remote_ocr_boundary, summarize_private_runtime_boundary
from ..private_corpus import materialize_customer_pack_private_corpus
from ..service import build_customer_pack_playable_books, evaluate_canonical_book_quality
from .builders import (
    build_canonical_book,
    build_image_canonical_book_from_markdown,
    extract_image_markdown_with_docling,
    image_markdown_is_low_confidence,
)
from .degraded_pdf import (
    PdfFallbackAttempt,
    assess_degraded_pdf_payload,
    attempt_optional_image_markdown_fallback,
    attempt_optional_pdf_markdown_fallback,
)
from .pdf import (
    extract_pdf_markdown_with_docling,
    extract_pdf_markdown_with_docling_ocr,
    extract_pdf_outline,
    extract_pdf_pages,
)
from .pdf_rows import (
    _build_pdf_rows_from_docling_markdown,
    _prepare_pdf_page_text,
    _segment_pdf_page,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalization_notes(payload: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        str(item).strip()
        for item in (payload.get("normalization_notes") or payload.get("notes") or [])
        if str(item).strip()
    )


def _primary_parse_strategy(source_type: str) -> str:
    if source_type in {"pptx", "docx", "xlsx"}:
        return "native_ooxml_first"
    if source_type in {"hwp", "hwpx"}:
        return "structured_hwp_first"
    if source_type == "pdf":
        return "structured_pdf_first"
    if source_type == "image":
        return "ocr_image_first"
    if source_type == "web":
        return "html_extract_first"
    if source_type in {"md", "asciidoc", "txt"}:
        return "structured_text_first"
    return "source_first"


def _parser_backend_label(
    *,
    source_type: str,
    canonical_payload: dict[str, object],
    fallback_attempt: PdfFallbackAttempt,
) -> str:
    notes_blob = " ".join(_normalization_notes(canonical_payload)).lower()
    if "unhwp structured rows first" in notes_blob:
        return "unhwp_structured_rows"
    if "unhwp (" in notes_blob:
        return "unhwp_markdown_bridge"
    if "source-first docx native structured lane" in notes_blob:
        return "docx_native_structure"
    if "source-first pptx native slide lane" in notes_blob:
        return "pptx_native_slide_extract"
    if "source-first xlsx native sheet lane" in notes_blob:
        return "xlsx_native_sheet_extract"
    if "source-first pdf native lane" in notes_blob:
        return "docling_pdf"
    if source_type in {"docx", "pptx", "xlsx", "pdf"} and "markitdown fallback" in notes_blob:
        return f"markitdown_{source_type}"
    if source_type == "pdf":
        if fallback_attempt.used and str(fallback_attempt.backend).strip():
            return str(fallback_attempt.backend).strip()
        return "docling_pdf"
    if source_type == "image":
        if fallback_attempt.used and str(fallback_attempt.backend).strip():
            return str(fallback_attempt.backend).strip()
        return "docling_image_ocr"
    if source_type == "web":
        return "html_section_extract"
    if source_type in {"md", "asciidoc", "txt"}:
        return "structured_text_builder"
    return "customer_pack_normalize_service"


def _finalize_pdf_evidence(
    record: CustomerPackDraftRecord,
    *,
    canonical_payload: dict[str, object],
    derived_payloads: list[dict[str, object]],
    book_path: Path,
    fallback_attempt: PdfFallbackAttempt,
    trigger_degraded: dict[str, object] | None = None,
) -> dict[str, object]:
    quality = evaluate_canonical_book_quality(canonical_payload)
    degraded = assess_degraded_pdf_payload(canonical_payload, quality=quality)
    if trigger_degraded:
        trigger_reasons = [
            str(item).strip()
            for item in (trigger_degraded.get("degraded_reasons") or [])
            if str(item).strip()
        ]
        merged_reasons = list(dict.fromkeys([*trigger_reasons, *degraded["degraded_reasons"]]))
        degraded = {
            "degraded_pdf": bool(trigger_degraded.get("degraded_pdf") or degraded["degraded_pdf"]),
            "degraded_reasons": merged_reasons,
            "degraded_reason": "|".join(merged_reasons),
        }
    evidence = {
        "source_lane": record.source_lane,
        "source_ref": record.request.uri,
        "source_fingerprint": record.source_fingerprint,
        "parser_route": f"{record.request.source_type}_customer_pack_normalize_v1",
        "parser_backend": _parser_backend_label(
            source_type=record.request.source_type,
            canonical_payload=canonical_payload,
            fallback_attempt=fallback_attempt,
        ),
        "parser_version": "v1",
        "primary_parse_strategy": _primary_parse_strategy(record.request.source_type),
        "ocr_used": record.request.source_type in {"pdf", "image"},
        "extraction_confidence": 0.95,
        "quality_status": str(quality["quality_status"]),
        "quality_score": int(quality["quality_score"]),
        "quality_flags": list(quality["quality_flags"]),
        "quality_summary": str(quality["quality_summary"]),
        "shared_grade": str(quality.get("shared_grade") or "blocked"),
        "grade_gate": dict(quality.get("grade_gate") or {}),
        "degraded_pdf": bool(degraded["degraded_pdf"]),
        "degraded_reasons": list(degraded["degraded_reasons"]),
        "degraded_reason": str(degraded["degraded_reason"]),
        "fallback_used": bool(fallback_attempt.used),
        "fallback_backend": str(fallback_attempt.backend),
        "fallback_status": str(fallback_attempt.status),
        "fallback_reason": str(fallback_attempt.reason),
        "tenant_id": record.tenant_id,
        "workspace_id": record.workspace_id,
        "pack_id": record.plan.pack_id,
        "pack_version": record.draft_id,
        "approval_state": record.approval_state,
        "publication_state": record.publication_state,
        "canonical_book_path": str(book_path),
        "normalization_notes": list(_normalization_notes(canonical_payload)),
    }
    payload_patch = {
        **quality,
        **degraded,
        "fallback_used": bool(fallback_attempt.used),
        "fallback_backend": str(fallback_attempt.backend),
        "fallback_status": str(fallback_attempt.status),
        "fallback_reason": str(fallback_attempt.reason),
    }
    canonical_payload.update(payload_patch)
    for derived_payload in derived_payloads:
        derived_payload.update(payload_patch)
    return evidence


def _build_pdf_canonical_book_from_fallback_markdown(
    record: CustomerPackDraftRecord,
    markdown: str,
):
    rows = _build_pdf_rows_from_docling_markdown(markdown, record)
    if not rows:
        raise ValueError("fallback parser returned no canonical rows")
    return CustomerPackPlanner().build_canonical_book(rows, request=record.request)


def _remote_ocr_boundary_payload(record: CustomerPackDraftRecord) -> dict[str, object]:
    access_groups = tuple(str(item).strip() for item in (record.access_groups or ()) if str(item).strip())
    if not access_groups:
        access_groups = tuple(
            item
            for item in (
                str(record.workspace_id or "").strip(),
                str(record.tenant_id or "").strip(),
            )
            if item
        )
    return {
        "tenant_id": record.tenant_id,
        "workspace_id": record.workspace_id,
        "pack_id": str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}",
        "pack_version": record.draft_id,
        "classification": str(record.classification or "").strip() or "private",
        "access_groups": list(access_groups),
        "provider_egress_policy": str(record.provider_egress_policy or "").strip(),
        "approval_state": str(record.approval_state or "").strip(),
        "publication_state": str(record.publication_state or "").strip(),
        "redaction_state": str(record.redaction_state or "").strip(),
    }


def _remote_ocr_allowed(record: CustomerPackDraftRecord) -> bool:
    boundary = summarize_private_remote_ocr_boundary(_remote_ocr_boundary_payload(record))
    return bool(boundary["remote_ocr_allowed"])


def _build_image_book_with_optional_fallback(
    record: CustomerPackDraftRecord,
    *,
    settings,
    allow_remote_ocr: bool,
):
    capture_path = Path(record.capture_artifact_path)
    fallback_attempt = PdfFallbackAttempt(status="not_needed")
    try:
        docling_markdown = extract_image_markdown_with_docling(capture_path)
    except Exception as exc:  # noqa: BLE001
        fallback_attempt = attempt_optional_image_markdown_fallback(
            capture_path,
            settings=settings,
            allow_remote=allow_remote_ocr,
        )
        if fallback_attempt.used and fallback_attempt.markdown:
            return build_image_canonical_book_from_markdown(record, fallback_attempt.markdown), fallback_attempt
        raise ValueError(f"image_docling_failed:{exc}|{fallback_attempt.reason or fallback_attempt.status}") from exc

    chosen_markdown = docling_markdown
    if image_markdown_is_low_confidence(docling_markdown):
        fallback_attempt = attempt_optional_image_markdown_fallback(
            capture_path,
            settings=settings,
            allow_remote=allow_remote_ocr,
        )
        if fallback_attempt.used and fallback_attempt.markdown:
            chosen_markdown = fallback_attempt.markdown
            fallback_attempt.status = "applied"
    return build_image_canonical_book_from_markdown(record, chosen_markdown), fallback_attempt


def _load_json_payload(path: Path) -> dict[str, object] | None:
    if path.as_posix() in {"", "."} or not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _refresh_private_corpus_manifest_runtime_boundary(
    manifest_path: Path,
    *,
    record: CustomerPackDraftRecord,
    updated_at: str,
    quality_payload: dict[str, object] | None = None,
) -> dict[str, object] | None:
    payload = _load_json_payload(manifest_path)
    if payload is None:
        return None
    payload["tenant_id"] = str(record.tenant_id or "").strip() or "default-tenant"
    payload["workspace_id"] = str(record.workspace_id or "").strip() or "default-workspace"
    payload["pack_id"] = str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}"
    payload["pack_version"] = str(record.draft_id)
    payload["classification"] = str(record.classification or "").strip() or "private"
    payload["access_groups"] = list(record.access_groups or ())
    payload["provider_egress_policy"] = str(record.provider_egress_policy or "").strip() or "local_only"
    payload["approval_state"] = str(record.approval_state or "").strip() or "unreviewed"
    payload["publication_state"] = str(record.publication_state or "").strip() or "draft"
    payload["redaction_state"] = str(record.redaction_state or "").strip() or "raw"
    payload["source_lane"] = str(record.source_lane or "").strip() or "customer_source_first_pack"
    payload["source_collection"] = str(record.plan.source_collection or "uploaded").strip() or "uploaded"
    payload["boundary_truth"] = "private_customer_pack_runtime"
    payload["runtime_truth_label"] = "Customer Source-First Pack"
    payload["boundary_badge"] = "Private Pack Runtime"
    if quality_payload:
        payload["quality_status"] = str(quality_payload.get("quality_status") or "")
        payload["quality_score"] = int(quality_payload.get("quality_score") or 0)
        payload["quality_flags"] = list(quality_payload.get("quality_flags") or [])
        payload["quality_summary"] = str(quality_payload.get("quality_summary") or "")
        payload["shared_grade"] = str(quality_payload.get("shared_grade") or "blocked")
        payload["grade_gate"] = dict(quality_payload.get("grade_gate") or {})
    grade_gate = dict(payload.get("grade_gate") or {})
    if grade_gate:
        surface_gates = dict(grade_gate.get("surface_gates") or {})
        promotion_gate = dict(grade_gate.get("promotion_gate") or {})
        shared_grade = str(payload.get("shared_grade") or grade_gate.get("shared_grade") or "blocked").strip() or "blocked"
        llmwiki_ready = bool(
            surface_gates.get("llmwiki_ready")
            or (payload.get("retrieval_ready") and shared_grade in {"gold", "silver"})
        )
        wikibook_ready = bool(
            surface_gates.get("wikibook_ready")
            or (
                str(payload.get("citation_landing_status") or "") == "exact"
                and shared_grade in {"gold", "silver"}
            )
        )
        approval_state = str(payload["approval_state"])
        publication_state = str(payload["publication_state"])
        read_ready = llmwiki_ready and wikibook_ready and approval_state == "approved"
        publish_ready = read_ready and publication_state in {"active", "published"}
        blocked_reasons = [
            str(reason).strip()
            for reason in (promotion_gate.get("blocked_reasons") or [])
            if str(reason).strip()
            and not str(reason).startswith("approval_not_ready:")
            and not str(reason).startswith("publication_not_publish_ready:")
        ]
        if approval_state != "approved":
            blocked_reasons.append(f"approval_not_ready:{approval_state or 'missing'}")
        if publication_state not in {"active", "published"}:
            blocked_reasons.append(f"publication_not_publish_ready:{publication_state or 'missing'}")
        promotion_gate.update(
            {
                "status": (
                    "promoted"
                    if publish_ready
                    else ("candidate" if llmwiki_ready and wikibook_ready and approval_state == "approved" else "blocked")
                ),
                "read_ready": read_ready,
                "publish_ready": publish_ready,
                "approval_state": approval_state,
                "publication_state": publication_state,
                "blocked_reasons": blocked_reasons,
            }
        )
        grade_gate["promotion_gate"] = promotion_gate
        payload["grade_gate"] = grade_gate
        payload["read_ready"] = read_ready
        payload["publish_ready"] = publish_ready
    boundary_summary = summarize_private_runtime_boundary(payload)
    payload["runtime_eligible"] = bool(boundary_summary.get("runtime_eligible", False))
    payload["boundary_fail_reasons"] = list(boundary_summary.get("fail_reasons") or [])
    payload["updated_at"] = updated_at
    write_json_payload(manifest_path, payload)
    return payload


def _quality_runtime_patch(corpus_manifest: dict[str, object], updated_at: str) -> dict[str, object]:
    grade_gate = dict(corpus_manifest.get("grade_gate") or {})
    citation_gate = dict(grade_gate.get("citation_gate") or {})
    retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})
    return {
        "quality_status": str(corpus_manifest.get("quality_status") or ""),
        "quality_score": int(corpus_manifest.get("quality_score") or 0),
        "quality_flags": list(corpus_manifest.get("quality_flags") or []),
        "quality_summary": str(corpus_manifest.get("quality_summary") or ""),
        "shared_grade": str(corpus_manifest.get("shared_grade") or "blocked"),
        "grade_gate": grade_gate,
        "citation_landing_status": str(corpus_manifest.get("citation_landing_status") or citation_gate.get("status") or "missing"),
        "retrieval_ready": bool(corpus_manifest.get("retrieval_ready") or retrieval_gate.get("ready")),
        "read_ready": bool(corpus_manifest.get("read_ready") or promotion_gate.get("read_ready")),
        "publish_ready": bool(corpus_manifest.get("publish_ready") or promotion_gate.get("publish_ready")),
        "runtime_eligible": bool(corpus_manifest.get("runtime_eligible")),
        "boundary_fail_reasons": list(corpus_manifest.get("boundary_fail_reasons") or []),
        "updated_at": updated_at,
    }


def _record_runtime_patch(record: CustomerPackDraftRecord) -> dict[str, object]:
    return {
        "source_collection": str(record.plan.source_collection or "uploaded").strip() or "uploaded",
        "pack_id": str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}",
        "pack_label": str(record.plan.pack_label or "").strip() or "User Custom Pack",
        "inferred_product": str(record.plan.inferred_product or "").strip() or "unknown",
        "inferred_version": str(record.plan.inferred_version or "").strip() or "unknown",
        "source_lane": str(record.source_lane or "").strip() or "customer_source_first_pack",
        "tenant_id": str(record.tenant_id or "").strip() or "default-tenant",
        "workspace_id": str(record.workspace_id or "").strip() or "default-workspace",
        "classification": str(record.classification or "").strip() or "private",
        "access_groups": list(record.access_groups or ()),
        "provider_egress_policy": str(record.provider_egress_policy or "").strip() or "local_only",
        "approval_state": str(record.approval_state or "").strip() or "unreviewed",
        "publication_state": str(record.publication_state or "").strip() or "draft",
        "redaction_state": str(record.redaction_state or "").strip() or "raw",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
    }


def _refresh_customer_pack_book_payload(
    book_path: Path,
    *,
    record: CustomerPackDraftRecord,
    corpus_manifest: dict[str, object],
    updated_at: str,
) -> dict[str, object] | None:
    payload = _load_json_payload(book_path)
    if payload is None:
        return None
    runtime_patch = _record_runtime_patch(record)
    quality_patch = _quality_runtime_patch(corpus_manifest, updated_at)
    payload.update(runtime_patch)
    payload.update(quality_patch)
    evidence = dict(payload.get("customer_pack_evidence") or {})
    evidence.update(runtime_patch)
    evidence.update(quality_patch)
    payload["customer_pack_evidence"] = evidence
    artifact_bundle = dict(payload.get("artifact_bundle") or {})
    if artifact_bundle:
        artifact_bundle.update(
            {
                "source_lane": str(runtime_patch["source_lane"]),
                "runtime_truth_label": str(runtime_patch["runtime_truth_label"]),
                "shared_grade": str(quality_patch["shared_grade"]),
                "read_ready": bool(quality_patch["read_ready"]),
                "publish_ready": bool(quality_patch["publish_ready"]),
                "corpus_manifest_path": str(corpus_manifest.get("manifest_path") or artifact_bundle.get("corpus_manifest_path") or ""),
            }
        )
        payload["artifact_bundle"] = artifact_bundle
    write_json_payload(book_path, payload)
    return payload


def _refresh_customer_pack_artifact_manifest(
    manifest_path: Path,
    *,
    record: CustomerPackDraftRecord,
    corpus_manifest: dict[str, object],
    updated_at: str,
) -> dict[str, object] | None:
    payload = _load_json_payload(manifest_path)
    if payload is None:
        return None
    payload.update(_record_runtime_patch(record))
    payload.update(_quality_runtime_patch(corpus_manifest, updated_at))
    write_json_payload(manifest_path, payload)
    return payload


def _asset_slugs_from_canonical_payload(payload: dict[str, object]) -> list[str]:
    slugs: list[str] = []

    def _append(slug: object) -> None:
        normalized = str(slug or "").strip()
        if normalized and normalized not in slugs:
            slugs.append(normalized)

    _append(payload.get("asset_slug"))
    for key in ("playable_assets", "derived_assets"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                _append(item.get("asset_slug"))
    return slugs


class CustomerPackNormalizeService:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.settings = load_settings(self.root_dir)
        self.store = CustomerPackDraftStore(self.root_dir)

    def _try_fast_refresh_existing_normalized_payloads(
        self,
        *,
        record: CustomerPackDraftRecord,
    ) -> CustomerPackDraftRecord | None:
        if str(record.status or "").strip() != "normalized":
            return None
        canonical_path = Path(str(record.canonical_book_path or "").strip())
        manifest_path = Path(str(record.private_corpus_manifest_path or "").strip())
        if canonical_path.as_posix() in {"", "."} or manifest_path.as_posix() in {"", "."}:
            return None
        if not canonical_path.exists() or not manifest_path.exists():
            return None
        canonical_payload = _load_json_payload(canonical_path)
        if canonical_payload is None:
            return None
        updated_at = _utc_now()
        quality_payload = evaluate_canonical_book_quality(canonical_payload)
        corpus_manifest = _refresh_private_corpus_manifest_runtime_boundary(
            manifest_path,
            record=record,
            updated_at=updated_at,
            quality_payload=quality_payload,
        )
        if corpus_manifest is None:
            return None
        quality_payload = evaluate_canonical_book_quality(
            canonical_payload,
            corpus_manifest=corpus_manifest,
        )
        corpus_manifest = _refresh_private_corpus_manifest_runtime_boundary(
            manifest_path,
            record=record,
            updated_at=updated_at,
            quality_payload=quality_payload,
        )
        if corpus_manifest is None:
            return None
        refreshed_canonical = _refresh_customer_pack_book_payload(
            canonical_path,
            record=record,
            corpus_manifest=corpus_manifest,
            updated_at=updated_at,
        )
        if refreshed_canonical is None:
            return None
        books_dir = canonical_path.parent
        for asset_slug in _asset_slugs_from_canonical_payload(refreshed_canonical):
            asset_path = books_dir / f"{asset_slug}.json"
            manifest_sidecar_path = books_dir / f"{asset_slug}.manifest.json"
            if asset_path != canonical_path:
                _refresh_customer_pack_book_payload(
                    asset_path,
                    record=record,
                    corpus_manifest=corpus_manifest,
                    updated_at=updated_at,
                )
            _refresh_customer_pack_artifact_manifest(
                manifest_sidecar_path,
                record=record,
                corpus_manifest=corpus_manifest,
                updated_at=updated_at,
            )
        record.normalize_error = ""
        record.updated_at = updated_at
        record.private_corpus_status = str(
            corpus_manifest.get("materialization_status", "") or ""
        ) or ("ready" if bool(corpus_manifest.get("bm25_ready")) else "empty")
        record.private_corpus_chunk_count = int(corpus_manifest.get("chunk_count", 0) or 0)
        record.private_corpus_vector_status = str(corpus_manifest.get("vector_status", "") or "")
        self.store.save(record)
        return record

    def normalize(self, *, draft_id: str, force_rebuild: bool = False) -> CustomerPackDraftRecord:
        record = self.store.get(draft_id.strip())
        if record is None:
            raise ValueError("업로드 플레이북 초안을 찾을 수 없습니다.")
        if not record.capture_artifact_path.strip():
            raise ValueError("먼저 capture를 실행해서 source artifact를 확보해야 합니다.")
        if not force_rebuild:
            refreshed_record = self._try_fast_refresh_existing_normalized_payloads(record=record)
            if refreshed_record is not None:
                return refreshed_record

        try:
            allow_remote_ocr = _remote_ocr_allowed(record)
            fallback_attempt = PdfFallbackAttempt(status="not_applicable")
            if record.request.source_type == "image":
                canonical_book, fallback_attempt = _build_image_book_with_optional_fallback(
                    record,
                    settings=self.settings,
                    allow_remote_ocr=allow_remote_ocr,
                )
            else:
                canonical_book = build_canonical_book(
                    record,
                    settings=self.settings,
                    extract_pdf_markdown_with_docling_fn=extract_pdf_markdown_with_docling,
                    extract_pdf_markdown_with_docling_ocr_fn=extract_pdf_markdown_with_docling_ocr,
                    extract_pdf_outline_fn=extract_pdf_outline,
                    extract_pdf_pages_fn=extract_pdf_pages,
                )
            canonical_payload, derived_payloads = build_customer_pack_playable_books(
                canonical_book.to_dict(),
                draft_id=record.draft_id,
            )
            self.settings.customer_pack_books_dir.mkdir(parents=True, exist_ok=True)
            book_path = self.settings.customer_pack_books_dir / f"{record.draft_id}.json"
            slide_packets_payload = None
            if record.request.source_type == "pptx":
                slide_packets_payload = build_customer_pack_slide_packets_payload(
                    record=record,
                    payload=canonical_payload,
                    asset_slug=str(canonical_payload.get("asset_slug") or canonical_payload.get("book_slug") or record.draft_id).strip()
                    or record.draft_id,
                    book_path=book_path,
                )
                if slide_packets_payload:
                    slide_packets_payload = augment_slide_packets_with_optional_ocr(
                        slide_packets_payload,
                        books_dir=book_path.parent,
                        settings=self.settings,
                        allow_remote_ocr=allow_remote_ocr,
                    )
                    canonical_payload.update(
                        {
                            "surface_kind": "slide_deck",
                            "source_unit_kind": "slide",
                            "source_unit_count": int(slide_packets_payload.get("slide_count") or 0),
                            "slide_packet_count": int(slide_packets_payload.get("slide_count") or 0),
                            "slide_asset_count": int(slide_packets_payload.get("embedded_asset_count") or 0),
                            "slide_preview_count": int(slide_packets_payload.get("rendered_slide_asset_count") or 0),
                            "origin_method": str(slide_packets_payload.get("origin_method") or "native").strip() or "native",
                            "ocr_status": str(slide_packets_payload.get("ocr_status") or "not_run").strip() or "not_run",
                            "ocr_backends": list(slide_packets_payload.get("ocr_backends") or []),
                            "ocr_target_kinds": list(slide_packets_payload.get("ocr_target_kinds") or []),
                            "ocr_candidate_count": int(slide_packets_payload.get("ocr_candidate_count") or 0),
                            "ocr_applied_count": int(slide_packets_payload.get("ocr_applied_count") or 0),
                        }
                    )
            initial_quality = evaluate_canonical_book_quality(canonical_payload)
            initial_degraded = assess_degraded_pdf_payload(canonical_payload, quality=initial_quality)
            if bool(initial_degraded["degraded_pdf"]):
                fallback_attempt = attempt_optional_pdf_markdown_fallback(
                    record.capture_artifact_path,
                    settings=self.settings,
                    allow_remote=allow_remote_ocr,
                )
                if fallback_attempt.used and fallback_attempt.markdown:
                    try:
                        fallback_book = _build_pdf_canonical_book_from_fallback_markdown(
                            record,
                            fallback_attempt.markdown,
                        )
                    except Exception as exc:  # noqa: BLE001
                        fallback_attempt = PdfFallbackAttempt(
                            backend=fallback_attempt.backend,
                            status="fallback_rejected",
                            reason=f"{fallback_attempt.backend}_fallback_rejected:{exc}",
                        )
                    else:
                        canonical_book = fallback_book
                        canonical_payload, derived_payloads = build_customer_pack_playable_books(
                            fallback_book.to_dict(),
                            draft_id=record.draft_id,
                        )
                        fallback_attempt.status = "applied"
            elif record.request.source_type == "pdf":
                fallback_attempt = PdfFallbackAttempt(status="not_needed")
            evidence = _finalize_pdf_evidence(
                record,
                canonical_payload=canonical_payload,
                derived_payloads=derived_payloads,
                book_path=book_path,
                fallback_attempt=fallback_attempt,
                trigger_degraded=initial_degraded if bool(initial_degraded["degraded_pdf"]) else None,
            )
            if slide_packets_payload:
                evidence["ocr_used"] = bool(int(slide_packets_payload.get("ocr_applied_count") or 0) > 0)
                evidence["ocr_status"] = str(slide_packets_payload.get("ocr_status") or "not_run")
                evidence["ocr_backends"] = list(slide_packets_payload.get("ocr_backends") or [])
                evidence["ocr_target_kinds"] = list(slide_packets_payload.get("ocr_target_kinds") or [])
                evidence["ocr_candidate_count"] = int(slide_packets_payload.get("ocr_candidate_count") or 0)
                evidence["ocr_applied_count"] = int(slide_packets_payload.get("ocr_applied_count") or 0)
                evidence["origin_method"] = str(slide_packets_payload.get("origin_method") or "native")
                evidence["slide_preview_count"] = int(slide_packets_payload.get("rendered_slide_asset_count") or 0)
            for stale_path in self.settings.customer_pack_books_dir.glob(f"{record.draft_id}--*.json"):
                stale_path.unlink(missing_ok=True)
            canonical_payload["customer_pack_evidence"] = evidence
            private_corpus_manifest = materialize_customer_pack_private_corpus(
                self.root_dir,
                record=record,
                canonical_payload=canonical_payload,
                derived_payloads=derived_payloads,
                slide_packets_payload=slide_packets_payload,
            )
            final_quality = evaluate_canonical_book_quality(
                canonical_payload,
                corpus_manifest=private_corpus_manifest,
            )
            final_grade_gate = dict(final_quality.get("grade_gate") or {})
            final_promotion_gate = dict(final_grade_gate.get("promotion_gate") or {})
            final_citation_gate = dict(final_grade_gate.get("citation_gate") or {})
            final_retrieval_gate = dict(final_grade_gate.get("retrieval_gate") or {})
            evidence.update(
                {
                    "quality_status": str(final_quality["quality_status"]),
                    "quality_score": int(final_quality["quality_score"]),
                    "quality_flags": list(final_quality["quality_flags"]),
                    "quality_summary": str(final_quality["quality_summary"]),
                    "shared_grade": str(final_quality.get("shared_grade") or "blocked"),
                    "grade_gate": final_grade_gate,
                    "read_ready": bool(final_promotion_gate.get("read_ready")),
                    "publish_ready": bool(final_promotion_gate.get("publish_ready")),
                    "citation_landing_status": str(final_citation_gate.get("status") or "missing"),
                    "retrieval_ready": bool(final_retrieval_gate.get("ready")),
                }
            )
            quality_patch = {
                "quality_status": str(final_quality["quality_status"]),
                "quality_score": int(final_quality["quality_score"]),
                "quality_flags": list(final_quality["quality_flags"]),
                "quality_summary": str(final_quality["quality_summary"]),
                "shared_grade": str(final_quality.get("shared_grade") or "blocked"),
                "grade_gate": final_grade_gate,
            }
            canonical_payload.update(quality_patch)
            canonical_payload["customer_pack_evidence"] = evidence
            for derived_payload in derived_payloads:
                derived_payload.update(quality_patch)
                derived_payload["customer_pack_evidence"] = {
                    **evidence,
                    "canonical_book_path": str(
                        self.settings.customer_pack_books_dir
                        / f"{str(derived_payload.get('asset_slug') or '').strip()}.json"
                    ),
                }
            canonical_bundle = build_customer_pack_artifact_bundle(
                record=record,
                payload=canonical_payload,
                book_path=book_path,
                corpus_manifest=private_corpus_manifest,
                slide_packets_payload=slide_packets_payload,
            )
            canonical_payload = dict(canonical_bundle["book"])
            write_json_payload(book_path, canonical_payload)
            write_json_payload(Path(str(canonical_payload["artifact_manifest_path"])), canonical_bundle["manifest"])
            write_json_payload(
                Path(str((canonical_payload.get("artifact_bundle") or {}).get("relations_path") or "")),
                canonical_bundle["relations"],
            )
            write_json_payload(
                Path(str((canonical_payload.get("artifact_bundle") or {}).get("figure_assets_path") or "")),
                canonical_bundle["figure_assets"],
            )
            write_json_payload(
                Path(str((canonical_payload.get("artifact_bundle") or {}).get("citations_path") or "")),
                canonical_bundle["citations"],
            )
            slide_packets_path = Path(str((canonical_payload.get("artifact_bundle") or {}).get("slide_packets_path") or ""))
            if slide_packets_path.as_posix() not in {"", "."} and canonical_bundle.get("slide_packets"):
                write_json_payload(slide_packets_path, canonical_bundle["slide_packets"])
            for derived_payload in derived_payloads:
                asset_slug = str(derived_payload.get("asset_slug") or "").strip()
                if not asset_slug:
                    continue
                asset_path = self.settings.customer_pack_books_dir / f"{asset_slug}.json"
                derived_payload["customer_pack_evidence"] = {**evidence, "canonical_book_path": str(asset_path)}
                derived_bundle = build_customer_pack_artifact_bundle(
                    record=record,
                    payload=derived_payload,
                    book_path=asset_path,
                    corpus_manifest=private_corpus_manifest,
                )
                derived_payload = dict(derived_bundle["book"])
                write_json_payload(asset_path, derived_payload)
                write_json_payload(Path(str(derived_payload["artifact_manifest_path"])), derived_bundle["manifest"])
                write_json_payload(
                    Path(str((derived_payload.get("artifact_bundle") or {}).get("relations_path") or "")),
                    derived_bundle["relations"],
                )
                write_json_payload(
                    Path(str((derived_payload.get("artifact_bundle") or {}).get("figure_assets_path") or "")),
                    derived_bundle["figure_assets"],
                )
                write_json_payload(
                    Path(str((derived_payload.get("artifact_bundle") or {}).get("citations_path") or "")),
                    derived_bundle["citations"],
                )
                slide_packets_path = Path(str((derived_payload.get("artifact_bundle") or {}).get("slide_packets_path") or ""))
                if slide_packets_path.as_posix() not in {"", "."} and derived_bundle.get("slide_packets"):
                    write_json_payload(slide_packets_path, derived_bundle["slide_packets"])
            record.status = "normalized"
            record.canonical_book_path = str(book_path)
            record.normalized_section_count = len(canonical_book.sections)
            record.parser_route = str(evidence["parser_route"])
            record.parser_backend = str(evidence["parser_backend"])
            record.parser_version = str(evidence["parser_version"])
            record.ocr_used = bool(evidence["ocr_used"])
            record.extraction_confidence = float(evidence["extraction_confidence"])
            record.degraded_pdf = bool(evidence["degraded_pdf"])
            record.degraded_reason = str(evidence["degraded_reason"])
            record.fallback_used = bool(evidence["fallback_used"])
            record.fallback_backend = str(evidence["fallback_backend"])
            record.fallback_status = str(evidence["fallback_status"])
            record.fallback_reason = str(evidence["fallback_reason"])
            record.normalize_error = ""
            record.private_corpus_manifest_path = str(
                self.settings.customer_pack_corpus_dir / record.draft_id / "manifest.json"
            )
            record.private_corpus_status = str(
                private_corpus_manifest.get("materialization_status", "") or ""
            ) or ("ready" if bool(private_corpus_manifest.get("bm25_ready")) else "empty")
            record.private_corpus_chunk_count = int(private_corpus_manifest.get("chunk_count", 0) or 0)
            record.private_corpus_vector_status = str(private_corpus_manifest.get("vector_status", "") or "")
        except Exception as exc:  # noqa: BLE001
            record.status = "normalize_failed"
            record.normalize_error = str(exc)
            record.updated_at = _utc_now()
            self.store.save(record)
            raise

        record.updated_at = _utc_now()
        self.store.save(record)
        return record
