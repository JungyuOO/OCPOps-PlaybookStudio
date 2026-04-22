from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import Settings


def _surya_ocr_endpoint(*, settings: Settings | None = None) -> str:
    if settings is not None and str(settings.surya_ocr_endpoint or "").strip():
        return str(settings.surya_ocr_endpoint or "").strip()
    return str(os.environ.get("SURYA_OCR") or "").strip().rstrip("/")


def _surya_health_endpoint(*, settings: Settings | None = None) -> str:
    configured = ""
    if settings is not None and str(settings.surya_health_endpoint or "").strip():
        configured = str(settings.surya_health_endpoint or "").strip()
    elif str(os.environ.get("SURYA_HEALTH") or "").strip():
        configured = str(os.environ.get("SURYA_HEALTH") or "").strip()
    if configured:
        return configured.rstrip("/")
    ocr_endpoint = _surya_ocr_endpoint(settings=settings)
    if ocr_endpoint.endswith("/ocr"):
        return f"{ocr_endpoint[:-4]}/health"
    if ocr_endpoint:
        return f"{ocr_endpoint}/health"
    return ""


def _surya_timeout_seconds(*, settings: Settings | None = None) -> float:
    if settings is not None:
        return float(settings.surya_timeout_seconds or 30.0)
    return float(os.environ.get("SURYA_TIMEOUT_SECONDS") or "30")


def probe_surya_health(*, settings: Settings | None = None) -> dict[str, Any]:
    endpoint = _surya_health_endpoint(settings=settings)
    if not endpoint:
        return {
            "status": "not_configured",
            "ready": False,
            "endpoint": "",
            "reason": "surya_health_not_configured",
        }
    try:
        response = requests.get(endpoint, timeout=_surya_timeout_seconds(settings=settings))
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unreachable",
            "ready": False,
            "endpoint": endpoint,
            "reason": f"surya_health_unreachable:{exc}",
        }
    return {
        "status": str(payload.get("status") or "ok"),
        "ready": bool(payload.get("ready", False)),
        "endpoint": endpoint,
        "payload": payload,
    }


def extract_image_markdown_with_surya(
    source: str | Path,
    *,
    settings: Settings | None = None,
) -> str:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"captured artifact를 찾을 수 없습니다: {path}")
    page_text = _surya_ocr_file(path, settings=settings)
    if not page_text:
        raise ValueError("surya returned no OCR text for image")
    return f"# {path.stem}\n\n## OCR\n\n{page_text}".strip()


def extract_pdf_markdown_with_surya(
    source: str | Path,
    *,
    settings: Settings | None = None,
) -> str:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"captured artifact를 찾을 수 없습니다: {path}")
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pypdfium2 unavailable for surya pdf fallback: {exc}") from exc

    document = pdfium.PdfDocument(str(path))
    page_sections: list[str] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            bitmap = None
            pil_image = None
            try:
                bitmap = page.render(scale=2)
                pil_image = bitmap.to_pil()
                buffer = BytesIO()
                pil_image.save(buffer, format="PNG")
                page_text = _surya_ocr_bytes(
                    filename=f"{path.stem}-page-{page_index + 1}.png",
                    content=buffer.getvalue(),
                    content_type="image/png",
                    settings=settings,
                )
            finally:
                if pil_image is not None:
                    try:
                        pil_image.close()
                    except Exception:  # noqa: BLE001
                        pass
                if bitmap is not None:
                    try:
                        bitmap.close()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
            normalized = str(page_text or "").strip()
            if normalized:
                page_sections.append(f"## Page {page_index + 1}\n\n{normalized}")
    finally:
        document.close()

    if not page_sections:
        raise ValueError("surya returned no OCR text for pdf")
    return f"# {path.stem}\n\n" + "\n\n".join(page_sections)


def _surya_ocr_file(path: Path, *, settings: Settings | None = None) -> str:
    content_type = "image/png"
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif suffix == ".webp":
        content_type = "image/webp"
    elif suffix == ".pdf":
        content_type = "application/pdf"
    return _surya_ocr_bytes(
        filename=path.name,
        content=path.read_bytes(),
        content_type=content_type,
        settings=settings,
    )


def _surya_ocr_bytes(
    *,
    filename: str,
    content: bytes,
    content_type: str,
    settings: Settings | None = None,
) -> str:
    endpoint = _surya_ocr_endpoint(settings=settings)
    if not endpoint:
        raise RuntimeError("surya_ocr_not_configured")
    response = requests.post(
        endpoint,
        files={"file": (filename, content, content_type)},
        timeout=_surya_timeout_seconds(settings=settings),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("surya returned non-json OCR payload") from exc
    return _surya_payload_text(payload)


def _surya_payload_text(payload: Any) -> str:
    pages = payload.get("pages") if isinstance(payload, dict) else None
    collected_pages: list[str] = []
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_text = str(page.get("text") or "").strip()
            if page_text:
                collected_pages.append(page_text)
                continue
            result = page.get("result")
            if isinstance(result, dict):
                line_texts = []
                for line in result.get("text_lines") or []:
                    if isinstance(line, dict):
                        text = str(line.get("text") or "").strip()
                        if text:
                            line_texts.append(text)
                if line_texts:
                    collected_pages.append("\n".join(line_texts))
    if collected_pages:
        return "\n\n".join(collected_pages)
    text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    return text


__all__ = [
    "extract_image_markdown_with_surya",
    "extract_pdf_markdown_with_surya",
    "probe_surya_health",
]
