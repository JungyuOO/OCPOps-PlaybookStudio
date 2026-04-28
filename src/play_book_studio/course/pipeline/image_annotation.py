from __future__ import annotations

import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import Any

import requests
from PIL import Image

from play_book_studio.config.settings import Settings

from .common import normalize_text


def _normalize_annotation_fields(ocr_text: str, visual_summary: str, raw_content: str = "") -> tuple[str, str]:
    ocr = normalize_text(ocr_text)
    summary = normalize_text(visual_summary)
    candidate = str(raw_content or "").strip()
    if candidate:
        json_match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if json_match:
            blob = json_match.group(0)
            try:
                parsed = json.loads(blob)
                ocr = ocr or normalize_text(str(parsed.get("ocr_text") or ""))
                summary = summary or normalize_text(str(parsed.get("visual_summary") or ""))
            except Exception:  # noqa: BLE001
                pass
            if not ocr:
                match = re.search(r'"ocr_text"\s*:\s*"((?:[^"\\]|\\.)*)"', blob, re.DOTALL)
                if match:
                    ocr = normalize_text(bytes(match.group(1), "utf-8").decode("unicode_escape"))
            if not summary:
                match = re.search(r'"visual_summary"\s*:\s*"((?:[^"\\]|\\.)*)"', blob, re.DOTALL)
                if match:
                    summary = normalize_text(bytes(match.group(1), "utf-8").decode("unicode_escape"))
        if not ocr:
            match = re.search(r"ocr[_ ]?text\s*:\s*(.+?)(?:\n[A-Z_ -]+:|\Z)", candidate, re.IGNORECASE | re.DOTALL)
            if match:
                ocr = normalize_text(match.group(1))
        if not summary:
            match = re.search(r"(?:visual[_ ]?summary|summary)\s*:\s*(.+)$", candidate, re.IGNORECASE | re.DOTALL)
            if match:
                summary = normalize_text(match.group(1))
    if summary.startswith("```"):
        summary = ""
    if ocr.startswith("```"):
        ocr = ""
    return ocr, summary


def _attachment_content_type(ext: str) -> str:
    normalized = str(ext or "png").strip().lower()
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    if normalized == "webp":
        return "image/webp"
    return "image/png"


def _prepare_image_payload(content: bytes, content_type: str) -> tuple[bytes, str]:
    try:
        with Image.open(BytesIO(content)) as image:
            image = image.convert("RGB")
            max_size = 1280
            width, height = image.size
            if max(width, height) > max_size:
                scale = max_size / float(max(width, height))
                image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=82, optimize=True)
            return buffer.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return content, content_type


def _llm_headers(settings: Settings) -> dict[str, str]:
    api_key = str(settings.llm_api_key or "").strip()
    if not api_key:
        return {}
    if " " in api_key:
        return {"Authorization": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _probe_vlm(settings: Settings) -> tuple[bool, str]:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        return False, "llm_not_configured"
    try:
        response = requests.get(
            f"{endpoint}/models",
            headers=_llm_headers(settings),
            timeout=max(settings.request_timeout_seconds, 15),
        )
        response.raise_for_status()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _describe_image_with_vlm(
    *,
    settings: Settings,
    filename: str,
    content: bytes,
    content_type: str,
    role: str,
) -> tuple[str, str]:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        raise RuntimeError("llm_not_configured")

    prepared_content, prepared_type = _prepare_image_payload(content, content_type)
    image_b64 = base64.b64encode(prepared_content).decode("ascii")
    image_url = f"data:{prepared_type};base64,{image_b64}"
    prompt = (
        "이 이미지는 PPT 슬라이드 내부에서 잘려 나온 일부 영역이다. "
        "가능한 경우 이미지 안의 텍스트를 OCR처럼 추출하고, 그 이미지가 무엇을 보여주는지 짧게 설명하라. "
        "작은 상태바, 테이블 행, Running/Ready/Succeeded/Failed/CrashLoopBackOff 같은 상태 표시는 교육 검증 증적이므로 "
        "작아도 텍스트와 상태를 반드시 보이는 범위에서 추출하라. "
        "반드시 아래 2줄 형식만 반환하라.\n"
        "OCR_TEXT: <텍스트 없으면 비움>\n"
        "VISUAL_SUMMARY: <한국어 한두 문장>\n"
        "추측은 하지 말고 보이는 범위만 작성하라. "
        f"role={role or 'illustration'}, filename={filename}"
    )

    response = requests.post(
        f"{endpoint}/chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "너는 PPT 내부 이미지 영역을 읽고 OCR 텍스트와 짧은 설명을 JSON으로 반환하는 도우미다.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "temperature": 0.0,
            "max_tokens": 300,
        },
        headers=_llm_headers(settings),
        timeout=max(settings.request_timeout_seconds, 120),
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError("vlm_response_missing_choices")
    message = choices[0].get("message") or {}
    content_payload = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content_payload, list):
        content_text = "\n".join(str(item.get("text") or "") for item in content_payload if isinstance(item, dict))
    else:
        content_text = str(content_payload or "")
    content_text = content_text.strip()
    if not content_text:
        raise RuntimeError("vlm_response_missing_content")
    ocr_match = re.search(r"OCR_TEXT\s*:\s*(.+?)(?:\nVISUAL_SUMMARY:|\Z)", content_text, re.IGNORECASE | re.DOTALL)
    summary_match = re.search(r"VISUAL_SUMMARY\s*:\s*(.+)$", content_text, re.IGNORECASE | re.DOTALL)
    return _normalize_annotation_fields(
        ocr_match.group(1) if ocr_match else "",
        summary_match.group(1) if summary_match else "",
        raw_content=content_text,
    )


def _summarize_image_with_vlm(
    *,
    settings: Settings,
    filename: str,
    content: bytes,
    content_type: str,
    role: str,
    ocr_hint: str,
) -> str:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        raise RuntimeError("llm_not_configured")

    prepared_content, prepared_type = _prepare_image_payload(content, content_type)
    image_b64 = base64.b64encode(prepared_content).decode("ascii")
    image_url = f"data:{prepared_type};base64,{image_b64}"
    prompt = (
        "이 이미지는 PPT 슬라이드 내부에서 잘려 나온 일부 영역이다. "
        "OCR 원문을 다시 길게 쓰지 말고, 보이는 사실만 근거로 한국어 한 문장 visual_summary만 작성하라. "
        "표나 텍스트 이미지라면 표의 주제와 주요 열/항목만 요약한다. "
        "스크린샷이면 화면 종류와 확인 포인트만 요약한다. "
        "작은 상태바나 테이블 행도 장식으로 보지 말고, 사용자가 확인해야 하는 상태가 보이면 그 상태를 요약한다. "
        "로고/장식처럼 정보가 거의 없으면 보이는 범위에서만 설명한다. "
        "추측 금지. JSON 하나만 반환하라: {\"visual_summary\":\"...\"}. "
        f"role={role or 'illustration'}, filename={filename}"
    )
    hint = normalize_text(ocr_hint)[:500]
    if hint:
        prompt += f"\n이미 추출된 OCR 일부: {hint}"

    response = requests.post(
        f"{endpoint}/chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "너는 PPT 이미지 asset의 시각 요약만 작성하는 검수 도구다. 반드시 짧은 JSON만 반환한다.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "temperature": 0.0,
            "max_tokens": 160,
        },
        headers=_llm_headers(settings),
        timeout=max(settings.request_timeout_seconds, 120),
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content_payload = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content_payload, list):
        content_text = "\n".join(str(item.get("text") or "") for item in content_payload if isinstance(item, dict))
    else:
        content_text = str(content_payload or "")
    _, visual_summary = _normalize_annotation_fields("", "", raw_content=content_text)
    if visual_summary:
        return visual_summary
    match = re.search(r'"visual_summary"\s*:\s*"((?:[^"\\]|\\.)*)"', content_text, re.DOTALL)
    if match:
        return normalize_text(bytes(match.group(1), "utf-8").decode("unicode_escape"))
    return ""


def annotate_slide_graph_attachments(slide_graphs: list[dict[str, Any]], *, settings: Settings) -> dict[str, int]:
    stats = {
        "attachments_total": 0,
        "attachments_ocr_ok": 0,
        "attachments_summary_ok": 0,
        "attachments_failed": 0,
        "vlm_available": 0,
    }
    vlm_available, vlm_reason = _probe_vlm(settings)
    stats["vlm_available"] = 1 if vlm_available else 0

    attachments_to_process: list[dict[str, Any]] = []
    for graph in slide_graphs:
        for slide in graph.get("slides") if isinstance(graph.get("slides"), list) else []:
            for attachment in slide.get("attachments") if isinstance(slide.get("attachments"), list) else []:
                if isinstance(attachment, dict):
                    attachments_to_process.append(attachment)

    stats["attachments_total"] = len(attachments_to_process)
    if not vlm_available:
        for attachment in attachments_to_process:
            attachment["ocr_text"] = ""
            attachment["caption_text"] = ""
            attachment["visual_summary"] = ""
            attachment["ocr_error"] = vlm_reason
        stats["attachments_failed"] = len(attachments_to_process)
        return stats

    def run_attachment(attachment: dict[str, Any]) -> tuple[dict[str, Any], str, str, str | None]:
        blob = attachment.get("_blob")
        if not isinstance(blob, (bytes, bytearray)):
            return attachment, "", "", "missing_blob"
        ext = str(attachment.get("_ext") or "png")
        filename = f"{attachment.get('attachment_id')}.{ext}"
        try:
            ocr_text, visual_summary = _describe_image_with_vlm(
                settings=settings,
                filename=filename,
                content=bytes(blob),
                content_type=_attachment_content_type(ext),
                role=str(attachment.get("role") or ""),
            )
            if not visual_summary:
                visual_summary = _summarize_image_with_vlm(
                    settings=settings,
                    filename=filename,
                    content=bytes(blob),
                    content_type=_attachment_content_type(ext),
                    role=str(attachment.get("role") or ""),
                    ocr_hint=ocr_text,
                )
            return attachment, ocr_text, visual_summary, None
        except Exception as exc:  # noqa: BLE001
            return attachment, "", "", str(exc)

    max_workers = 6
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_attachment, attachment) for attachment in attachments_to_process]
        for future in as_completed(futures):
            attachment, ocr_text, visual_summary, error = future.result()
            if error:
                attachment["ocr_text"] = ""
                attachment["caption_text"] = ""
                attachment["visual_summary"] = ""
                attachment["ocr_error"] = error
                stats["attachments_failed"] += 1
                continue
            attachment["ocr_text"] = ocr_text
            attachment["caption_text"] = ocr_text[:300]
            attachment["visual_summary"] = visual_summary
            attachment["searchable"] = bool(ocr_text or visual_summary)
            if ocr_text:
                stats["attachments_ocr_ok"] += 1
            if visual_summary:
                stats["attachments_summary_ok"] += 1

    return stats


def summarize_attachment_coverage(slide_graphs: list[dict[str, Any]]) -> dict[str, int]:
    total = 0
    ocr_ok = 0
    summary_ok = 0
    for graph in slide_graphs:
        for slide in graph.get("slides") if isinstance(graph.get("slides"), list) else []:
            for attachment in slide.get("attachments") if isinstance(slide.get("attachments"), list) else []:
                if not isinstance(attachment, dict):
                    continue
                total += 1
                if normalize_text(str(attachment.get("ocr_text") or "")):
                    ocr_ok += 1
                if normalize_text(str(attachment.get("visual_summary") or "")):
                    summary_ok += 1
    return {
        "attachments_total": total,
        "attachments_ocr_ok": ocr_ok,
        "attachments_summary_ok": summary_ok,
    }


__all__ = ["annotate_slide_graph_attachments", "summarize_attachment_coverage"]
