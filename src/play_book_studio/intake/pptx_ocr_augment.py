from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
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
    blocked_count = 0
    failed_count = 0
    not_configured_count = 0
    used_backends: list[str] = []
    used_target_kinds: list[str] = []

    for slide in slides:
        ocr_entries: list[dict[str, Any]] = []
        ocr_texts: list[str] = []
        slide_assets = [dict(asset) for asset in (slide.get("embedded_assets") or []) if isinstance(asset, dict)]
        preview_asset = dict(slide.get("rendered_slide_asset") or {})
        preview_bbox = _full_slide_bbox(slide)
        preview_asset, preview_entry = _augment_asset_with_optional_ocr(
            preview_asset,
            books_dir=books_dir,
            settings=settings,
            allow_remote_ocr=allow_remote_ocr,
            backend_chain=_preferred_ppt_ocr_backends(settings, target_kind="slide_preview", slide=slide),
            default_bbox=preview_bbox,
            target_kind="slide_preview",
        )
        if preview_asset:
            slide["rendered_slide_asset"] = preview_asset
        _collect_ocr_outcome(
            preview_asset,
            preview_entry,
            used_backends=used_backends,
            used_target_kinds=used_target_kinds,
            ocr_entries=ocr_entries,
            ocr_texts=ocr_texts,
        )
        blocked_count += int(str(preview_asset.get("ocr_status") or "") == "blocked")
        not_configured_count += int(str(preview_asset.get("ocr_status") or "") == "not_configured")
        if str(preview_asset.get("ocr_status") or "") in {"failed", "empty", "backend_unavailable", "missing_asset"}:
            failed_count += 1

        preview_usable = bool(preview_entry) and str(preview_asset.get("ocr_status") or "").strip() == "applied"
        preview_low_confidence = str(preview_asset.get("ocr_status") or "").strip() == "low_confidence"
        should_scan_embedded_assets = not preview_usable or preview_low_confidence

        for asset in slide_assets:
            if str(asset.get("asset_kind") or "").strip() != "image":
                asset["ocr_status"] = "not_applicable"
                continue
            if not should_scan_embedded_assets:
                asset["ocr_status"] = "covered_by_slide_preview"
                asset["ocr_used"] = False
                asset["ocr_text"] = ""
                asset["ocr_low_confidence"] = False
                continue
            asset, asset_entry = _augment_asset_with_optional_ocr(
                asset,
                books_dir=books_dir,
                settings=settings,
                allow_remote_ocr=allow_remote_ocr,
                backend_chain=_preferred_ppt_ocr_backends(settings, target_kind="embedded_image"),
                default_bbox=dict(asset.get("bbox") or {}),
                target_kind="embedded_image",
            )
            _collect_ocr_outcome(
                asset,
                asset_entry,
                used_backends=used_backends,
                used_target_kinds=used_target_kinds,
                ocr_entries=ocr_entries,
                ocr_texts=ocr_texts,
            )
            if str(asset.get("ocr_status") or "") == "blocked":
                blocked_count += 1
            elif str(asset.get("ocr_status") or "") == "not_configured":
                not_configured_count += 1
            elif str(asset.get("ocr_status") or "") not in {"applied", "low_confidence", "not_applicable", "covered_by_slide_preview"}:
                failed_count += 1
        slide["embedded_assets"] = slide_assets
        slide["ocr_entries"] = ocr_entries
        slide["ocr_text"] = "\n\n".join(text for text in ocr_texts if text).strip()
        slide["ocr_backends"] = [
            backend
            for backend in dict.fromkeys(
                str(entry.get("ocr_backend") or "").strip()
                for entry in ocr_entries
                if str(entry.get("ocr_backend") or "").strip()
            )
        ]
        slide["ocr_target_kinds"] = [
            target_kind
            for target_kind in dict.fromkeys(
                str(entry.get("ocr_target_kind") or "").strip()
                for entry in ocr_entries
                if str(entry.get("ocr_target_kind") or "").strip()
            )
        ]
        if ocr_entries:
            slide["origin_method"] = "hybrid"
            slide["ocr_status"] = "applied"
        elif bool(_slide_has_ocr_candidate(slide)):
            slide["ocr_status"] = _slide_ocr_status(
                slide_assets,
                preview_asset=dict(slide.get("rendered_slide_asset") or {}),
            )
        else:
            slide["ocr_status"] = "not_run"
        slide["ocr_candidate"] = bool(_slide_has_ocr_candidate(slide))

    payload["slides"] = slides
    payload["ocr_applied_count"] = sum(1 for slide in slides if str(slide.get("ocr_status") or "") == "applied")
    payload["ocr_blocked_count"] = blocked_count
    payload["ocr_failed_count"] = failed_count
    payload["ocr_not_configured_count"] = not_configured_count
    payload["origin_method"] = "hybrid" if int(payload.get("ocr_applied_count") or 0) > 0 else "native"
    payload["ocr_status"] = _deck_ocr_status(slides)
    payload["ocr_backends"] = used_backends
    payload["ocr_target_kinds"] = used_target_kinds
    payload["ocr_candidate_count"] = sum(1 for slide in slides if bool(slide.get("ocr_candidate")))
    return payload


def _preferred_ppt_ocr_backends(
    settings: Any,
    *,
    target_kind: str,
    slide: dict[str, Any] | None = None,
) -> list[str]:
    explicit_backend = str(getattr(settings, "customer_pack_pdf_fallback_backend", "") or "").strip().lower()
    if explicit_backend:
        return [explicit_backend]
    backends: list[str] = []
    if target_kind == "slide_preview":
        prefers_qwen_first = bool(
            isinstance(slide, dict)
            and (
                list(slide.get("table_blocks") or [])
                or str(slide.get("slide_role") or "").strip() == "table_heavy"
            )
        )
        if prefers_qwen_first and _qwen_backend_available(settings):
            backends.append("qwen")
        if _surya_backend_available(settings):
            backends.append("surya")
        if _qwen_backend_available(settings):
            backends.append("qwen")
    else:
        if _qwen_backend_available(settings):
            backends.append("qwen")
        if _surya_backend_available(settings):
            backends.append("surya")
    return [backend for backend in dict.fromkeys(backends) if backend]


def _qwen_backend_available(settings: Any) -> bool:
    qwen_endpoint = str(getattr(settings, "qwen_ocr_endpoint", "") or "").strip()
    qwen_model = str(getattr(settings, "qwen_ocr_model", "") or "").strip()
    if qwen_endpoint and qwen_model:
        return True
    shared_endpoint = str(getattr(settings, "llm_endpoint", "") or "").strip()
    shared_model = str(getattr(settings, "llm_model", "") or "").strip()
    return bool(shared_endpoint and shared_model and "qwen" in shared_model.lower())


def _surya_backend_available(settings: Any) -> bool:
    return bool(str(getattr(settings, "surya_ocr_endpoint", "") or "").strip())


def _slide_has_ocr_candidate(slide: dict[str, Any]) -> bool:
    preview_asset = dict(slide.get("rendered_slide_asset") or {})
    if str(preview_asset.get("storage_relpath") or "").strip():
        return True
    return any(
        isinstance(asset, dict) and str(asset.get("asset_kind") or "").strip() == "image"
        for asset in (slide.get("embedded_assets") or [])
    )


def _full_slide_bbox(slide: dict[str, Any]) -> dict[str, Any]:
    slide_size = dict(slide.get("slide_size") or {})
    width = float(slide_size.get("width") or 0.0)
    height = float(slide_size.get("height") or 0.0)
    return {
        "left": 0.0,
        "top": 0.0,
        "width": width,
        "height": height,
    }


def _augment_asset_with_optional_ocr(
    asset: dict[str, Any],
    *,
    books_dir: Path,
    settings: Any,
    allow_remote_ocr: bool,
    backend_chain: list[str],
    default_bbox: dict[str, Any],
    target_kind: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not asset:
        return asset, None
    storage_relpath = str(asset.get("storage_relpath") or "").strip()
    storage_path = books_dir / storage_relpath if storage_relpath else Path()
    asset["ocr_target_kind"] = target_kind
    if not storage_relpath or not storage_path.exists() or not storage_path.is_file():
        asset["ocr_status"] = "missing_asset"
        asset["ocr_used"] = False
        asset["ocr_text"] = ""
        asset["ocr_low_confidence"] = False
        return asset, None
    attempts = backend_chain or [""]
    selected_attempt = None
    selected_text = ""
    selected_low_confidence = False
    selected_score = -1
    for backend in attempts:
        attempt = attempt_optional_image_markdown_fallback(
            storage_path,
            settings=settings,
            allow_remote=allow_remote_ocr,
            backend_override=backend,
        )
        ocr_text = _ocr_markdown_text(str(attempt.markdown or ""))
        low_confidence = bool(ocr_text) and image_markdown_is_low_confidence(str(attempt.markdown or ""))
        score = 2 if ocr_text and not low_confidence else 1 if ocr_text else 0
        if score > selected_score:
            selected_attempt = attempt
            selected_text = ocr_text
            selected_low_confidence = low_confidence
            selected_score = score
        if score == 2:
            break
        if str(attempt.status or "").strip().lower() in {"blocked", "not_configured"} and not ocr_text:
            continue
    attempt = selected_attempt or attempt_optional_image_markdown_fallback(
        storage_path,
        settings=settings,
        allow_remote=allow_remote_ocr,
    )
    ocr_text = selected_text or _ocr_markdown_text(str(attempt.markdown or ""))
    low_confidence = selected_low_confidence or (bool(ocr_text) and image_markdown_is_low_confidence(str(attempt.markdown or "")))
    asset["ocr_backend"] = str(attempt.backend or "").strip()
    asset["ocr_status"] = _asset_ocr_status(attempt.status, has_text=bool(ocr_text), low_confidence=low_confidence)
    asset["ocr_used"] = bool(ocr_text)
    asset["ocr_text"] = ocr_text
    asset["ocr_low_confidence"] = low_confidence
    if not ocr_text:
        return asset, None
    return asset, {
        "asset_ref": str(asset.get("asset_ref") or "").strip(),
        "asset_name": str(asset.get("asset_name") or "").strip(),
        "asset_kind": str(asset.get("asset_kind") or "").strip() or target_kind,
        "storage_relpath": storage_relpath,
        "ocr_backend": str(attempt.backend or "").strip(),
        "ocr_status": str(asset.get("ocr_status") or "").strip(),
        "ocr_text": ocr_text,
        "ocr_low_confidence": low_confidence,
        "ocr_target_kind": target_kind,
        "bbox": dict(asset.get("bbox") or default_bbox),
    }


def _collect_ocr_outcome(
    asset: dict[str, Any],
    entry: dict[str, Any] | None,
    *,
    used_backends: list[str],
    used_target_kinds: list[str],
    ocr_entries: list[dict[str, Any]],
    ocr_texts: list[str],
) -> None:
    backend = str(asset.get("ocr_backend") or "").strip()
    if backend and backend not in used_backends:
        used_backends.append(backend)
    target_kind = str(asset.get("ocr_target_kind") or "").strip()
    if target_kind and target_kind not in used_target_kinds:
        used_target_kinds.append(target_kind)
    if entry:
        ocr_entries.append(entry)
        _append_unique_ocr_text(ocr_texts, str(entry.get("ocr_text") or ""))


def _append_unique_ocr_text(ocr_texts: list[str], text: str) -> None:
    normalized = str(text or "").strip()
    if not normalized:
        return
    if normalized not in ocr_texts:
        ocr_texts.append(normalized)


def _ocr_markdown_text(markdown: str) -> str:
    normalized_markdown = re.sub(r"<br\s*/?>", "\n", str(markdown or ""), flags=re.IGNORECASE)
    normalized_markdown = normalized_markdown.replace("```markdown", "").replace("```", "")
    lines: list[str] = []
    for raw_line in normalized_markdown.splitlines():
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


def _slide_ocr_status(
    slide_assets: list[dict[str, Any]],
    *,
    preview_asset: dict[str, Any] | None = None,
) -> str:
    statuses = [str(asset.get("ocr_status") or "").strip() for asset in slide_assets if isinstance(asset, dict)]
    if isinstance(preview_asset, dict):
        preview_status = str(preview_asset.get("ocr_status") or "").strip()
        if preview_status:
            statuses.append(preview_status)
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
