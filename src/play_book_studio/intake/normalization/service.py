from __future__ import annotations

# captured source를 canonical study asset으로 바꾸는 normalize service 구현.

import json
from datetime import datetime, timezone
from pathlib import Path

from play_book_studio.config.settings import load_settings

from ..books.store import CustomerPackDraftStore
from ..models import CustomerPackDraftRecord
from ..planner import CustomerPackPlanner
from ..private_boundary import summarize_private_remote_ocr_boundary
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
        "parser_backend": "customer_pack_normalize_service",
        "parser_version": "v1",
        "ocr_used": record.request.source_type in {"pdf", "image"},
        "extraction_confidence": 0.95,
        "quality_status": str(quality["quality_status"]),
        "quality_score": int(quality["quality_score"]),
        "quality_flags": list(quality["quality_flags"]),
        "quality_summary": str(quality["quality_summary"]),
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


class CustomerPackNormalizeService:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.settings = load_settings(self.root_dir)
        self.store = CustomerPackDraftStore(self.root_dir)

    def normalize(self, *, draft_id: str) -> CustomerPackDraftRecord:
        record = self.store.get(draft_id.strip())
        if record is None:
            raise ValueError("업로드 플레이북 초안을 찾을 수 없습니다.")
        if not record.capture_artifact_path.strip():
            raise ValueError("먼저 capture를 실행해서 source artifact를 확보해야 합니다.")

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
            for stale_path in self.settings.customer_pack_books_dir.glob(f"{record.draft_id}--*.json"):
                stale_path.unlink(missing_ok=True)
            canonical_payload["customer_pack_evidence"] = evidence
            book_path.write_text(
                json.dumps(canonical_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            for derived_payload in derived_payloads:
                asset_slug = str(derived_payload.get("asset_slug") or "").strip()
                if not asset_slug:
                    continue
                asset_path = self.settings.customer_pack_books_dir / f"{asset_slug}.json"
                derived_payload["customer_pack_evidence"] = {
                    **evidence,
                    "canonical_book_path": str(asset_path),
                }
                asset_path.write_text(
                    json.dumps(derived_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            private_corpus_manifest = materialize_customer_pack_private_corpus(
                self.root_dir,
                record=record,
                canonical_payload=canonical_payload,
                derived_payloads=derived_payloads,
            )
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
