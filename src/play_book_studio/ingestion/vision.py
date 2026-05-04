"""Vision description client for document image assets."""

from __future__ import annotations

import base64
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.document_parsing import DocumentAsset, ImageDescriber


DEFAULT_IMAGE_PROMPT = (
    "Describe this document image for retrieval. Focus on visible text, diagrams, UI state, "
    "tables, error messages, command output, and OpenShift/Kubernetes entities. "
    "Return one concise Korean paragraph. Do not invent facts that are not visible."
)


@dataclass(frozen=True, slots=True)
class QwenVisionClient:
    endpoint: str
    model: str
    timeout_seconds: float = 30.0
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
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except error.URLError as exc:
            raise RuntimeError(f"Qwen vision request failed: {exc}") from exc
        return _extract_description(json.loads(response_body)).strip()


def build_qwen_image_describer(settings: Settings) -> ImageDescriber | None:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        return None
    client = QwenVisionClient(
        endpoint=endpoint,
        model=model,
    )

    def describe(document_path: Path, asset: DocumentAsset) -> str:
        return client.describe_asset(document_path, asset)

    setattr(describe, "qwen_model", model)
    return describe


def load_asset_image_bytes(document_path: Path, asset: DocumentAsset) -> bytes:
    source_member = str(asset.metadata.get("source_member") or "").strip()
    if source_member:
        try:
            with zipfile.ZipFile(document_path) as archive:
                return archive.read(source_member)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"failed to read embedded image asset {source_member}") from exc
    return document_path.read_bytes()


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
    "QwenVisionClient",
    "build_qwen_image_describer",
    "load_asset_image_bytes",
]
