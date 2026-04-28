from __future__ import annotations

import argparse
import base64
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from play_book_studio.config.settings import load_settings

from .build_index import _write_review_queue
from .pipeline.chunk_normalization import normalize_course_chunk
from .pipeline.common import normalize_text
from .pipeline.image_annotation import _llm_headers, _probe_vlm
from .pipeline.image_policy import apply_image_policy_to_chunk


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retry only missing visual summaries in generated course chunks.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of missing assets to retry. 0 means all.")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--include-short", action="store_true", help="Retry visual summaries shorter than --min-summary-chars.")
    parser.add_argument("--min-summary-chars", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _load_chunks(chunks_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(chunks_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["_chunk_path"] = path
            rows.append(payload)
    return rows


def _is_retryable_summary(summary: str, *, include_short: bool, min_summary_chars: int) -> tuple[bool, str]:
    normalized = normalize_text(summary)
    if not normalized:
        return True, "missing_visual_summary"
    stripped = normalized.strip("`{}[] \t\r\n")
    if stripped in {'"', "'", "}"} or normalized in {'" } ```', '"} ```'}:
        return True, "invalid_visual_summary"
    if include_short and len(normalized) < max(1, min_summary_chars):
        return True, "short_visual_summary"
    return False, ""


def _missing_attachments(
    chunks: list[dict[str, Any]],
    *,
    root_dir: Path,
    include_short: bool,
    min_summary_chars: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for index, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                continue
            retryable, reason = _is_retryable_summary(
                str(attachment.get("visual_summary") or ""),
                include_short=include_short,
                min_summary_chars=min_summary_chars,
            )
            if not retryable:
                continue
            asset_path = normalize_text(str(attachment.get("asset_path") or ""))
            if not asset_path:
                continue
            path = root_dir / asset_path
            rows.append(
                {
                    "chunk": chunk,
                    "attachment": attachment,
                    "attachment_index": index,
                    "asset_path": asset_path,
                    "path": path,
                    "asset_id": str(attachment.get("asset_id") or ""),
                    "role": str(attachment.get("role") or ""),
                    "ext": str(attachment.get("ext") or path.suffix.lstrip(".") or "png"),
                    "retry_reason": reason,
                }
            )
    return rows


def _refresh_chunk_review(chunk: dict[str, Any]) -> dict[str, Any]:
    notes = [str(item) for item in (chunk.get("review_notes") or []) if str(item).strip()]
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    has_missing_visual = any(
        isinstance(attachment, dict) and not normalize_text(str(attachment.get("visual_summary") or ""))
        for attachment in attachments
    )
    if has_missing_visual and attachments and "attachments_without_visual_summary" not in notes:
        notes.append("attachments_without_visual_summary")
    if not has_missing_visual:
        notes = [note for note in notes if note != "attachments_without_visual_summary"]
    chunk["review_notes"] = notes
    chunk["review_status"] = "needs_review" if notes else "approved"
    chunk["quality_score"] = round(max(0.35, 0.95 - (0.12 * len(notes))), 2) if notes else 0.98
    return normalize_course_chunk(chunk)


def _write_chunks(chunks: list[dict[str, Any]]) -> None:
    for chunk in chunks:
        path = chunk.pop("_chunk_path", None)
        if not isinstance(path, Path):
            continue
        path.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")


def _refresh_manifest_review_summary(course_dir: Path, chunks: list[dict[str, Any]]) -> None:
    manifest_path = course_dir / "manifests" / "course_v1.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return
    stages = manifest.get("stages") if isinstance(manifest.get("stages"), list) else []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        rows = [
            chunk
            for chunk in chunks
            if str(chunk.get("stage_id") or "") == stage_id and not str(chunk.get("parent_chunk_id") or "").strip()
        ]
        stage["review_summary"] = {
            "approved": sum(1 for chunk in rows if str(chunk.get("review_status") or "") == "approved"),
            "needs_review": sum(1 for chunk in rows if str(chunk.get("review_status") or "") == "needs_review"),
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _prepare_summary_image(content: bytes) -> tuple[bytes, str]:
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
        return content, "image/png"


def _extract_visual_summary(content: str) -> str:
    raw = str(content or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    json_start = raw.find("{")
    json_end = raw.rfind("}")
    if json_start >= 0 and json_end > json_start:
        try:
            payload = json.loads(raw[json_start : json_end + 1])
            if isinstance(payload, dict):
                return normalize_text(str(payload.get("visual_summary") or payload.get("summary") or ""))
        except Exception:  # noqa: BLE001
            pass
    for marker in ("visual_summary", "VISUAL_SUMMARY", "summary", "SUMMARY"):
        if marker in raw:
            tail = raw.split(marker, 1)[1]
            tail = tail.lstrip(" :=-")
            return normalize_text(tail.splitlines()[0] if tail.splitlines() else tail)
    return normalize_text(raw.splitlines()[0])


def _summarize_image_only(*, settings: Any, path: Path, role: str, existing_ocr: str) -> str:
    endpoint = str(settings.llm_endpoint or "").strip()
    model = str(settings.llm_model or "").strip()
    if not endpoint or not model:
        raise RuntimeError("llm_not_configured")
    prepared_content, prepared_type = _prepare_summary_image(path.read_bytes())
    image_url = f"data:{prepared_type};base64,{base64.b64encode(prepared_content).decode('ascii')}"
    ocr_hint = normalize_text(existing_ocr)[:500]
    prompt = (
        "이 이미지는 사내 교육자료 PPT에서 잘려 나온 이미지 asset이다. "
        "OCR 원문을 다시 길게 쓰지 말고, 보이는 사실만 근거로 한국어 한 문장 visual_summary만 작성하라. "
        "표나 텍스트 이미지라면 표의 주제와 주요 열/항목만 요약한다. "
        "스크린샷이면 화면 종류와 확인 포인트만 요약한다. "
        "작은 상태바, 테이블 행, Running/Ready/Succeeded/Failed/CrashLoopBackOff 상태도 교육 검증 증적이므로 상태를 요약한다. "
        "로고/장식처럼 정보가 거의 없으면 '로고 또는 장식 이미지'처럼 보이는 범위만 작성한다. "
        "추측 금지. JSON 하나만 반환: {\"visual_summary\":\"...\"}. "
        f"role={role or 'image'}"
    )
    if ocr_hint:
        prompt += f"\n이미 추출된 OCR 일부: {ocr_hint}"
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
    return _extract_visual_summary(content_text)


def main() -> int:
    args = build_parser().parse_args()
    root_dir = args.root_dir.resolve()
    course_dir = (root_dir / args.course_dir).resolve() if not args.course_dir.is_absolute() else args.course_dir.resolve()
    chunks_dir = course_dir / "chunks"
    chunks = _load_chunks(chunks_dir)
    missing = _missing_attachments(
        chunks,
        root_dir=root_dir,
        include_short=bool(args.include_short),
        min_summary_chars=int(args.min_summary_chars or 24),
    )
    if args.limit > 0:
        missing = missing[: args.limit]

    retry_reasons: dict[str, int] = {}
    for row in missing:
        reason = str(row.get("retry_reason") or "unknown")
        retry_reasons[reason] = retry_reasons.get(reason, 0) + 1

    report: dict[str, Any] = {
        "canonical_model": "course_visual_summary_retry_report_v1",
        "requested": len(missing),
        "attempted": 0,
        "updated": 0,
        "failed": 0,
        "dry_run": bool(args.dry_run),
        "include_short": bool(args.include_short),
        "min_summary_chars": int(args.min_summary_chars or 24),
        "retry_reasons": retry_reasons,
        "failures": [],
    }
    if args.dry_run or not missing:
        report_path = course_dir / "manifests" / "visual_summary_retry_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    settings = load_settings(root_dir)
    vlm_available, vlm_reason = _probe_vlm(settings)
    if not vlm_available:
        raise SystemExit(f"VLM is not available: {vlm_reason}")

    def run(row: dict[str, Any]) -> dict[str, Any]:
        path = row["path"]
        if not isinstance(path, Path) or not path.exists():
            return {**row, "ocr_text": "", "visual_summary": "", "error": "asset_not_found"}
        try:
            attachment = row.get("attachment") if isinstance(row.get("attachment"), dict) else {}
            visual_summary = _summarize_image_only(
                settings=settings,
                path=path,
                role=str(row.get("role") or ""),
                existing_ocr=str(attachment.get("ocr_text") or ""),
            )
            return {**row, "ocr_text": "", "visual_summary": visual_summary, "error": ""}
        except Exception as exc:  # noqa: BLE001
            return {**row, "ocr_text": "", "visual_summary": "", "error": str(exc)}

    touched_chunks: set[str] = set()
    max_workers = max(1, min(12, int(args.max_workers or 4)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run, row) for row in missing]
        for future in as_completed(futures):
            report["attempted"] += 1
            result = future.result()
            error = str(result.get("error") or "")
            visual_summary = normalize_text(str(result.get("visual_summary") or ""))
            attachment = result.get("attachment")
            chunk = result.get("chunk")
            if error or not visual_summary or not isinstance(attachment, dict) or not isinstance(chunk, dict):
                report["failed"] += 1
                report["failures"].append(
                    {
                        "asset_id": str(result.get("asset_id") or ""),
                        "asset_path": str(result.get("asset_path") or ""),
                        "retry_reason": str(result.get("retry_reason") or ""),
                        "error": error or "empty_visual_summary",
                    }
                )
                continue
            attachment["visual_summary"] = visual_summary
            ocr_text = normalize_text(str(result.get("ocr_text") or ""))
            if ocr_text and not normalize_text(str(attachment.get("ocr_text") or "")):
                attachment["ocr_text"] = ocr_text
            if ocr_text and not normalize_text(str(attachment.get("caption_text") or "")):
                attachment["caption_text"] = ocr_text[:300]
            attachment["searchable"] = True
            touched_chunks.add(str(chunk.get("chunk_id") or ""))
            report["updated"] += 1

    for chunk in chunks:
        if str(chunk.get("chunk_id") or "") in touched_chunks:
            _refresh_chunk_review(chunk)
            apply_image_policy_to_chunk(chunk, root_dir=root_dir)
    _write_chunks(chunks)
    clean_chunks = [{key: value for key, value in chunk.items() if key != "_chunk_path"} for chunk in chunks]
    _write_review_queue(course_dir, clean_chunks)
    _refresh_manifest_review_summary(course_dir, clean_chunks)

    report_path = course_dir / "manifests" / "visual_summary_retry_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
