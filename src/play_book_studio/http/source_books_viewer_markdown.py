from __future__ import annotations

import re
from typing import Any


def _normalized_book_summary(sections: list[dict[str, Any]]) -> str:
    for section in sections:
        text = str(section.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            continue
        paragraph = re.sub(r"\s+", " ", text.split("\n\n", 1)[0]).strip()
        if len(paragraph) > 200:
            return paragraph[:197].rstrip() + "..."
        return paragraph
    return ""


def _playbook_viewer_chrome(playbook_book: dict[str, Any]) -> tuple[str, str]:
    source_metadata = (
        playbook_book.get("source_metadata")
        if isinstance(playbook_book.get("source_metadata"), dict)
        else {}
    )
    source_type = str(source_metadata.get("source_type") or "").strip()
    summary = str(playbook_book.get("topic_summary") or "").strip()
    parent_title = str(source_metadata.get("derived_from_title") or "").strip()
    if source_type == "topic_playbook":
        if not summary:
            summary = (
                f"{parent_title}에서 실행 절차만 추린 토픽 플레이북입니다."
                if parent_title
                else "실행 절차 중심으로 다시 엮은 토픽 플레이북입니다."
            )
        return "Topic Playbook", summary
    if source_type == "operation_playbook":
        if not summary:
            summary = (
                f"{parent_title}에서 운영 절차와 검증만 추린 운영 플레이북입니다."
                if parent_title
                else "운영 절차와 검증 중심으로 다시 엮은 운영 플레이북입니다."
            )
        return "Operation Playbook", summary
    if source_type == "troubleshooting_playbook":
        if not summary:
            summary = (
                f"{parent_title}에서 장애 대응 경로만 추린 트러블슈팅 플레이북입니다."
                if parent_title
                else "장애 대응 경로 중심으로 다시 엮은 트러블슈팅 플레이북입니다."
            )
        return "Troubleshooting Playbook", summary
    if source_type == "policy_overlay_book":
        if not summary:
            summary = (
                f"{parent_title}에서 제한, 요구 사항, 검증 기준만 다시 묶은 정책 오버레이입니다."
                if parent_title
                else "제한, 요구 사항, 검증 기준만 다시 묶은 정책 오버레이입니다."
            )
        return "Policy Overlay", summary
    if source_type == "synthesized_playbook":
        if not summary:
            summary = (
                f"{parent_title}에서 핵심 설명, 절차, 검증만 압축한 합성 플레이북입니다."
                if parent_title
                else "핵심 설명, 절차, 검증을 압축한 합성 플레이북입니다."
            )
        return "Synthesized Playbook", summary
    return "Manual Book", ""


def _parse_markdown_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    if level < 1 or level > 6:
        return None
    title = stripped[level:].strip()
    if not title:
        return None
    return level, title


def _anchorify_heading(text: str) -> str:
    normalized = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    return normalized or "section"


def _markdown_sections(markdown_text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    path_stack: list[str] = []
    for raw_line in markdown_text.splitlines():
        heading = _parse_markdown_heading(raw_line)
        if heading is not None:
            level, title = heading
            while len(path_stack) >= level:
                path_stack.pop()
            path_stack.append(title)
            current = {
                "anchor": _anchorify_heading(title),
                "heading": title,
                "section_path": list(path_stack),
                "text": "",
                "blocks": [],
            }
            sections.append(current)
            continue
        if current is None:
            continue
        existing = str(current.get("text") or "")
        current["text"] = f"{existing}\n{raw_line}" if existing else raw_line
    normalized_sections: list[dict[str, Any]] = []
    for section in sections:
        section_text = str(section.get("text") or "").strip()
        section_heading = str(section.get("heading") or "").strip()
        if not section_text and not section_heading:
            continue
        normalized = dict(section)
        normalized["text"] = section_text
        normalized_sections.append(normalized)
    return normalized_sections


def _markdown_summary(sections: list[dict[str, Any]]) -> str:
    for section in sections:
        raw_text = str(section.get("text") or "").strip()
        if not raw_text:
            continue
        paragraph = raw_text.split("\n\n", 1)[0].strip()
        paragraph = re.sub(r"\s+", " ", paragraph)
        if len(paragraph) > 180:
            paragraph = paragraph[:177].rstrip() + "..."
        if paragraph:
            return paragraph
    return ""


def _trim_leading_title_section(sections: list[dict[str, Any]], *, title: str) -> list[dict[str, Any]]:
    if not sections:
        return sections
    first = sections[0]
    first_heading = str(first.get("heading") or "").strip()
    if first_heading != str(title or "").strip():
        return sections
    section_path = [str(item).strip() for item in (first.get("section_path") or []) if str(item).strip()]
    if len(section_path) != 1:
        return sections
    remaining = sections[1:]
    if not remaining:
        return sections
    carry_text = str(first.get("text") or "").strip()
    if not carry_text:
        return remaining
    merged_first = dict(remaining[0])
    next_text = str(merged_first.get("text") or "").strip()
    merged_first["text"] = f"{carry_text}\n\n{next_text}".strip() if next_text else carry_text
    return [merged_first, *remaining[1:]]


__all__ = [
    "_markdown_sections",
    "_markdown_summary",
    "_normalized_book_summary",
    "_playbook_viewer_chrome",
    "_trim_leading_title_section",
]
