from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from play_book_studio.config.settings import Settings


PDF_FALLBACK_BACKEND_ENV = "PBS_CUSTOMER_PACK_PDF_FALLBACK_BACKEND"
REMOTE_OCR_FALLBACK_BACKENDS = {"surya"}
PDF_DEGRADED_QUALITY_FLAGS = {
    "no_sections",
    "too_many_page_summary_sections",
    "too_many_heading_only_sections",
    "too_many_short_sections",
    "structured_blocks_flattened",
    "section_count_too_high",
    "chapter_footer_contamination",
    "toc_artifacts_remaining",
}


@dataclass(slots=True)
class PdfFallbackAttempt:
    backend: str = ""
    status: str = "not_needed"
    reason: str = ""
    used: bool = False
    markdown: str = ""


def assess_degraded_pdf_payload(
    payload: dict[str, Any],
    *,
    quality: dict[str, Any],
) -> dict[str, Any]:
    if str(payload.get("source_type") or "").strip().lower() != "pdf":
        return {
            "degraded_pdf": False,
            "degraded_reasons": [],
            "degraded_reason": "",
        }

    quality_flags = [
        str(flag).strip()
        for flag in (quality.get("quality_flags") or [])
        if str(flag).strip()
    ]
    degraded_reasons = [
        flag
        for flag in quality_flags
        if flag in PDF_DEGRADED_QUALITY_FLAGS
    ]
    return {
        "degraded_pdf": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "degraded_reason": "|".join(degraded_reasons),
    }


def requested_pdf_fallback_backend(*, settings: Settings | None = None) -> str:
    if settings is not None and str(settings.customer_pack_pdf_fallback_backend or "").strip():
        return str(settings.customer_pack_pdf_fallback_backend or "").strip().lower()
    configured = str(os.environ.get(PDF_FALLBACK_BACKEND_ENV) or "").strip().lower()
    if configured:
        return configured
    if settings is not None and str(settings.surya_ocr_endpoint or "").strip():
        return "surya"
    if str(os.environ.get("SURYA_OCR") or "").strip():
        return "surya"
    return ""


def attempt_optional_ocr_markdown_fallback(
    source: str | Path,
    *,
    settings: Settings | None = None,
    allow_remote: bool = False,
    source_type: str = "pdf",
) -> PdfFallbackAttempt:
    backend = requested_pdf_fallback_backend(settings=settings)
    if not backend:
        return PdfFallbackAttempt(
            status="not_configured",
            reason="fallback_backend_not_configured",
        )
    if backend in REMOTE_OCR_FALLBACK_BACKENDS and not allow_remote:
        return PdfFallbackAttempt(
            backend=backend,
            status="blocked",
            reason=f"{backend}_remote_egress_not_allowed",
        )

    adapter = _resolve_adapter(backend, source_type=source_type)
    if adapter is None:
        return PdfFallbackAttempt(
            backend=backend,
            status="backend_unavailable",
            reason=f"{backend}_adapter_unavailable",
        )

    try:
        markdown = str(adapter(Path(source), settings=settings) or "").strip()
    except Exception as exc:  # noqa: BLE001
        return PdfFallbackAttempt(
            backend=backend,
            status="adapter_failed",
            reason=f"{backend}_adapter_failed:{exc}",
        )
    if not markdown:
        return PdfFallbackAttempt(
            backend=backend,
            status="adapter_empty",
            reason=f"{backend}_adapter_returned_empty_markdown",
        )
    return PdfFallbackAttempt(
        backend=backend,
        status="ready",
        used=True,
        markdown=markdown,
    )


def attempt_optional_pdf_markdown_fallback(
    source: str | Path,
    *,
    settings: Settings | None = None,
    allow_remote: bool = False,
) -> PdfFallbackAttempt:
    return attempt_optional_ocr_markdown_fallback(
        source,
        settings=settings,
        allow_remote=allow_remote,
        source_type="pdf",
    )


def attempt_optional_image_markdown_fallback(
    source: str | Path,
    *,
    settings: Settings | None = None,
    allow_remote: bool = False,
) -> PdfFallbackAttempt:
    return attempt_optional_ocr_markdown_fallback(
        source,
        settings=settings,
        allow_remote=allow_remote,
        source_type="image",
    )


def _resolve_adapter(backend: str, *, source_type: str) -> Callable[..., str] | None:
    target_map = {
        ("surya", "pdf"): (
            "play_book_studio.intake.normalization.surya_adapter",
            "extract_pdf_markdown_with_surya",
        ),
        ("surya", "image"): (
            "play_book_studio.intake.normalization.surya_adapter",
            "extract_image_markdown_with_surya",
        ),
        ("marker", "pdf"): (
            "play_book_studio.intake.normalization.marker_adapter",
            "extract_pdf_markdown_with_marker",
        ),
    }
    target = target_map.get((backend, source_type))
    if target is None:
        return None
    module_name, function_name = target
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001
        return None
    candidate = getattr(module, function_name, None)
    return candidate if callable(candidate) else None


__all__ = [
    "PDF_FALLBACK_BACKEND_ENV",
    "PdfFallbackAttempt",
    "assess_degraded_pdf_payload",
    "attempt_optional_image_markdown_fallback",
    "attempt_optional_ocr_markdown_fallback",
    "attempt_optional_pdf_markdown_fallback",
    "requested_pdf_fallback_backend",
]
