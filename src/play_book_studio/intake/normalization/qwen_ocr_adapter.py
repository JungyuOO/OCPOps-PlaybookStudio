from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import Settings


QWEN_OCR_SYSTEM_PROMPT = (
    "You are an OCR transcription engine for enterprise documents. "
    "Extract all visible text faithfully, preserve tables and lists when possible, "
    "and return markdown only."
)
QWEN_OCR_USER_PROMPT = (
    "Transcribe every readable word from this document image. "
    "Keep section headings, bullets, table cells, short labels inside diagrams, "
    "and brief connector text when visible. "
    "Do not summarize, do not explain, and do not add commentary. "
    "If no text is readable, return an empty string."
)


def _qwen_ocr_endpoint(*, settings: Settings | None = None) -> str:
    if settings is not None and str(settings.qwen_ocr_endpoint or "").strip():
        return str(settings.qwen_ocr_endpoint or "").strip().rstrip("/")
    configured = str(os.environ.get("QWEN_OCR_ENDPOINT") or "").strip()
    if configured:
        return configured.rstrip("/")
    if settings is not None and str(settings.llm_endpoint or "").strip():
        return str(settings.llm_endpoint or "").strip().rstrip("/")
    return str(os.environ.get("LLM_ENDPOINT") or "").strip().rstrip("/")


def _qwen_ocr_api_key(*, settings: Settings | None = None) -> str:
    if settings is not None and str(settings.qwen_ocr_api_key or "").strip():
        return str(settings.qwen_ocr_api_key or "").strip()
    configured = str(os.environ.get("QWEN_OCR_API_KEY") or "").strip()
    if configured:
        return configured
    if settings is not None and str(settings.llm_api_key or "").strip():
        return str(settings.llm_api_key or "").strip()
    return str(os.environ.get("LLM_API_KEY") or "").strip()


def _qwen_ocr_model(*, settings: Settings | None = None) -> str:
    if settings is not None and str(settings.qwen_ocr_model or "").strip():
        return str(settings.qwen_ocr_model or "").strip()
    configured = str(os.environ.get("QWEN_OCR_MODEL") or "").strip()
    if configured:
        return configured
    if settings is not None and str(settings.llm_model or "").strip():
        return str(settings.llm_model or "").strip()
    return str(os.environ.get("LLM_MODEL") or "").strip()


def _qwen_ocr_timeout_seconds(*, settings: Settings | None = None) -> float:
    if settings is not None and float(settings.qwen_ocr_timeout_seconds or 0.0) > 0:
        return float(settings.qwen_ocr_timeout_seconds or 120.0)
    configured = str(os.environ.get("QWEN_OCR_TIMEOUT_SECONDS") or "").strip()
    if configured:
        return float(configured)
    if settings is not None:
        return max(float(settings.request_timeout_seconds or 30), 120.0)
    return 120.0


def extract_image_markdown_with_qwen(
    source: str | Path,
    *,
    settings: Settings | None = None,
) -> str:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"captured artifact를 찾을 수 없습니다: {path}")
    page_text = _qwen_ocr_file(path, settings=settings)
    if not page_text:
        raise ValueError("qwen returned no OCR text for image")
    return f"# {path.stem}\n\n## OCR\n\n{page_text}".strip()


def extract_pdf_markdown_with_qwen(
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
        raise RuntimeError(f"pypdfium2 unavailable for qwen pdf fallback: {exc}") from exc

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
                page_text = _qwen_ocr_bytes(
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
        raise ValueError("qwen returned no OCR text for pdf")
    return f"# {path.stem}\n\n" + "\n\n".join(page_sections)


def _qwen_ocr_file(path: Path, *, settings: Settings | None = None) -> str:
    suffix = path.suffix.lower()
    content_type = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif suffix == ".webp":
        content_type = "image/webp"
    return _qwen_ocr_bytes(
        filename=path.name,
        content=path.read_bytes(),
        content_type=content_type,
        settings=settings,
    )


def _qwen_ocr_bytes(
    *,
    filename: str,
    content: bytes,
    content_type: str,
    settings: Settings | None = None,
) -> str:
    endpoint = _qwen_ocr_endpoint(settings=settings)
    model = _qwen_ocr_model(settings=settings)
    if not endpoint:
        raise RuntimeError("qwen_ocr_endpoint_not_configured")
    if not model:
        raise RuntimeError("qwen_ocr_model_not_configured")
    payload = _qwen_ocr_payload(
        model=model,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    response = requests.post(
        f"{endpoint}/chat/completions",
        json=payload,
        headers=_auth_headers(_qwen_ocr_api_key(settings=settings)),
        timeout=_qwen_ocr_timeout_seconds(settings=settings),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("qwen returned non-json OCR payload") from exc
    text = _openai_content_text(payload)
    if not text:
        raise RuntimeError("qwen returned empty OCR text")
    if _is_non_transcription_response(text):
        raise RuntimeError("qwen returned non-transcription OCR text")
    return text


def _qwen_ocr_payload(
    *,
    model: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    encoded = base64.b64encode(content).decode("ascii")
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "system",
                "content": QWEN_OCR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": QWEN_OCR_USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{encoded}",
                            "detail": "high",
                            "name": filename,
                        },
                    },
                ],
            },
        ],
    }


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    if " " in api_key.strip():
        return {"Authorization": api_key.strip()}
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _openai_content_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _is_non_transcription_response(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return True
    blocked_phrases = (
        "no visible text",
        "no readable text",
        "no text",
        "contains no visible text",
        "contains no readable text",
        "image provided is completely blank",
        "there is no text",
        "unable to read any text",
        "텍스트가 없습니다",
        "보이는 텍스트가 없습니다",
        "읽을 수 있는 텍스트가 없습니다",
        "이미지가 비어",
        "빈 이미지",
    )
    return any(phrase in normalized for phrase in blocked_phrases)


__all__ = [
    "extract_image_markdown_with_qwen",
    "extract_pdf_markdown_with_qwen",
]
