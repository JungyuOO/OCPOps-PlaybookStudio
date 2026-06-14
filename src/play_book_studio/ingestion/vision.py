"""Company LLM vision/OCR client for document image assets."""

from __future__ import annotations

import base64
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.document_parsing import DocumentAsset, ImageDescriber, render_pdf_page_image_bytes


DEFAULT_IMAGE_PROMPT = (
    "이 이미지는 업로드 문서 안의 페이지/도표/스크린샷입니다. "
    "먼저 보이는 텍스트를 가능한 한 원문 그대로 OCR 하세요. 한국어, 명령어, 코드, 표, 에러 메시지, "
    "OpenShift/Kubernetes 리소스명은 생략하지 마세요. 그 다음 이미지가 무엇을 설명하는지 짧게 요약하세요. "
    "보이지 않는 내용은 추측하지 말고, 검색/RAG에 바로 쓸 수 있는 한국어 Markdown으로 답하세요."
)


@dataclass(frozen=True, slots=True)
class CompanyLlmVisionClient:
    endpoint: str
    model: str
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    backoff_seconds: float = 2.0
    prompt: str = DEFAULT_IMAGE_PROMPT

    def describe_asset(self, document_path: Path, asset: DocumentAsset) -> str:
        image_bytes = load_asset_image_bytes(document_path, asset)
        if not image_bytes:
            return ""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _data_url(image_bytes, mime_type=asset.mime_type)},
                        },
                    ],
                }
            ],
            "temperature": 0,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = request.Request(_chat_completions_url(self.endpoint), data=body, headers=headers, method="POST")
        response_body = self._send_with_retries(req)
        try:
            payload_json = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Company LLM vision response was not valid JSON") from exc
        return _extract_description(payload_json).strip()

    def _send_with_retries(self, req: request.Request) -> str:
        attempts = max(1, int(self.max_attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with request.urlopen(req, timeout=max(float(self.timeout_seconds), 1.0)) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (TimeoutError, error.URLError) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                sleep_seconds = max(float(self.backoff_seconds), 0.0) * attempt
                if sleep_seconds:
                    time.sleep(sleep_seconds)
        assert last_error is not None
        raise RuntimeError(f"Company LLM vision request failed: {last_error}") from last_error


def build_company_llm_image_describer(settings: Settings) -> ImageDescriber | None:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        return None
    client = CompanyLlmVisionClient(
        endpoint=endpoint,
        model=model,
        timeout_seconds=settings.request_timeout_seconds,
        max_attempts=settings.request_retries,
        backoff_seconds=settings.request_backoff_seconds,
    )

    def describe(document_path: Path, asset: DocumentAsset) -> str:
        return client.describe_asset(document_path, asset)

    setattr(describe, "vision_provider", "company_llm")
    setattr(describe, "vision_model", model)
    setattr(describe, "vision_timeout_seconds", settings.request_timeout_seconds)
    setattr(describe, "vision_max_attempts", settings.request_retries)
    setattr(describe, "vision_backoff_seconds", settings.request_backoff_seconds)
    return describe


def load_asset_image_bytes(document_path: Path, asset: DocumentAsset) -> bytes:
    source_member = str(asset.metadata.get("source_member") or "").strip()
    pdf_xref = str(asset.metadata.get("pdf_xref") or "").strip()
    rendered_pdf_page = _metadata_int(asset.metadata.get("rendered_pdf_page"))
    if rendered_pdf_page:
        content = render_pdf_page_image_bytes(
            document_path,
            page_number=rendered_pdf_page,
            scale=_metadata_float(asset.metadata.get("rendered_pdf_scale"), default=2.0),
        )
        if content:
            return content
        raise RuntimeError(f"failed to render PDF page image {rendered_pdf_page}")
    if pdf_xref:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(document_path))
            try:
                payload = doc.extract_image(int(pdf_xref))
                return bytes(payload.get("image") or b"")
            finally:
                doc.close()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"failed to read embedded PDF image xref {pdf_xref}") from exc
    if source_member:
        try:
            with zipfile.ZipFile(document_path) as archive:
                return archive.read(source_member)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"failed to read embedded image asset {source_member}") from exc
    return document_path.read_bytes()


def _metadata_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _metadata_float(value: Any, *, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _chat_completions_url(endpoint: str) -> str:
    normalized = endpoint.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _data_url(image_bytes: bytes, *, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type or 'application/octet-stream'};base64,{encoded}"


def _extract_description(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            )
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    return ""


__all__ = [
    "CompanyLlmVisionClient",
    "build_company_llm_image_describer",
    "load_asset_image_bytes",
]
