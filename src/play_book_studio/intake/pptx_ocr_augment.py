from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .normalization.builders import image_markdown_is_low_confidence
from .normalization.degraded_pdf import attempt_optional_image_markdown_fallback


def augment_slide_packets_with_optional_ocr(
    slide_packets_payload: dict[str, Any],
    *,
    books_dir: Path,
    settings: Any,
    allow_remote_ocr: bool,
) -> dict[str, Any]:
    payload = deepcopy(slide_packets_payload)
    slides = [dict(slide) for slide in (payload.get("slides") or []) if isinstance(slide, dict)]
    applied_count = 0
    blocked_count = 0
    failed_count = 0
    not_configured_count = 0

    for slide in slides:
        ocr_entries: list[dict[str, Any]] = []
        ocr_texts: list[str] = []
        slide_assets = [dict(asset) for asset in (slide.get("embedded_assets") or []) if isinstance(asset, dict)]
        for asset in slide_assets:
            if str(asset.get("asset_kind") or "").strip() != "image":
                asset["ocr_status"] = "not_applicable"
                continue
            storage_relpath = str(asset.get("storage_relpath") or "").strip()
            storage_path = books_dir / storage_relpath if storage_relpath else Path()
            if not storage_relpath or not storage_path.exists() or not storage_path.is_file():
                asset["ocr_status"] = "missing_asset"
                failed_count += 1
                continue
            attempt = attempt_optional_image_markdown_fallback(
                storage_path,
                settings=settings,
                allow_remote=allow_remote_ocr,
            )
            ocr_text = _ocr_markdown_text(str(attempt.markdown or ""))
            low_confidence = bool(ocr_text) and image_markdown_is_low_confidence(str(attempt.markdown or ""))
            asset["ocr_backend"] = str(attempt.backend or "").strip()
            asset["ocr_status"] = _asset_ocr_status(attempt.status, has_text=bool(ocr_text), low_confidence=low_confidence)
            asset["ocr_used"] = bool(ocr_text)
            asset["ocr_text"] = ocr_text
            asset["ocr_low_confidence"] = low_confidence
            if ocr_text:
                applied_count += 1
                ocr_texts.append(ocr_text)
                ocr_entries.append(
                    {
                        "asset_ref": str(asset.get("asset_ref") or "").strip(),
                        "asset_name": str(asset.get("asset_name") or "").strip(),
                        "asset_kind": str(asset.get("asset_kind") or "").strip(),
                        "storage_relpath": storage_relpath,
                        "ocr_backend": str(attempt.backend or "").strip(),
                        "ocr_status": str(asset.get("ocr_status") or "").strip(),
                        "ocr_text": ocr_text,
                        "ocr_low_confidence": low_confidence,
                        "bbox": dict(asset.get("bbox") or {}),
                    }
                )
            elif str(asset.get("ocr_status") or "") == "blocked":
                blocked_count += 1
            elif str(asset.get("ocr_status") or "") == "not_configured":
                not_configured_count += 1
            elif str(asset.get("ocr_status") or "") not in {"not_applicable"}:
                failed_count += 1

        slide["embedded_assets"] = slide_assets
        slide["ocr_entries"] = ocr_entries
        slide["ocr_text"] = "\n\n".join(text for text in ocr_texts if text).strip()
        if ocr_entries:
            slide["origin_method"] = "hybrid"
            slide["ocr_status"] = "applied"
        elif bool(slide.get("ocr_candidate")):
            slide["ocr_status"] = _slide_ocr_status(slide_assets)
        else:
            slide["ocr_status"] = "not_run"

    payload["slides"] = slides
    payload["ocr_applied_count"] = sum(1 for slide in slides if str(slide.get("ocr_status") or "") == "applied")
    payload["ocr_blocked_count"] = blocked_count
    payload["ocr_failed_count"] = failed_count
    payload["ocr_not_configured_count"] = not_configured_count
    payload["origin_method"] = "hybrid" if int(payload.get("ocr_applied_count") or 0) > 0 else "native"
    payload["ocr_status"] = _deck_ocr_status(slides)
    return payload


def _ocr_markdown_text(markdown: str) -> str:
    lines: list[str] = []
    for raw_line in str(markdown or "").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _asset_ocr_status(status: str, *, has_text: bool, low_confidence: bool) -> str:
    normalized = str(status or "").strip().lower()
    if has_text and not low_confidence:
        return "applied"
    if has_text and low_confidence:
        return "low_confidence"
    if normalized in {"blocked", "not_configured", "adapter_failed", "adapter_empty", "backend_unavailable"}:
        mapping = {
            "blocked": "blocked",
            "not_configured": "not_configured",
            "adapter_failed": "failed",
            "adapter_empty": "empty",
            "backend_unavailable": "backend_unavailable",
        }
        return mapping[normalized]
    return "not_run"


def _slide_ocr_status(slide_assets: list[dict[str, Any]]) -> str:
    statuses = [str(asset.get("ocr_status") or "").strip() for asset in slide_assets if isinstance(asset, dict)]
    if "applied" in statuses:
        return "applied"
    if "low_confidence" in statuses:
        return "low_confidence"
    if "blocked" in statuses:
        return "blocked"
    if "not_configured" in statuses:
        return "not_configured"
    if any(status in {"failed", "empty", "backend_unavailable", "missing_asset"} for status in statuses):
        return "failed"
    return "not_run"


def _deck_ocr_status(slides: list[dict[str, Any]]) -> str:
    statuses = [str(slide.get("ocr_status") or "").strip() for slide in slides]
    if "applied" in statuses:
        return "applied"
    if "low_confidence" in statuses:
        return "low_confidence"
    if "blocked" in statuses:
        return "blocked"
    if "not_configured" in statuses:
        return "not_configured"
    if "failed" in statuses:
        return "failed"
    return "not_run"


__all__ = ["augment_slide_packets_with_optional_ocr"]
