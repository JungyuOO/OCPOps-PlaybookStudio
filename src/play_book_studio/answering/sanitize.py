"""Sanitizers for text that is shown back to users or the answer prompt."""

from __future__ import annotations

import re


SPACE_RE = re.compile(r"[ \t]+")
INTERNAL_MARKUP_RE = re.compile(r"\[/?(?:CODE|TABLE)(?:[^\]]*)?\]", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*|\s*```$", re.MULTILINE)
SECTION_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
COMMAND_OUTPUT_MARKER_RE = re.compile(
    r"\s+(?:출력\s*예|출력예|결과|NAME\s+STATUS|추가\s+리소스|검증)\b",
    re.IGNORECASE,
)


def strip_internal_markup(text: str) -> str:
    """Remove corpus-only tags such as [CODE] without changing source meaning."""

    cleaned = INTERNAL_MARKUP_RE.sub(" ", str(text or ""))
    cleaned = CODE_FENCE_RE.sub("", cleaned)
    cleaned = SPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def sanitize_cli_command(command: str) -> str:
    cleaned = strip_internal_markup(command)
    cleaned = cleaned.removeprefix("$ ").strip()
    cleaned = cleaned.strip("` ")
    cleaned = COMMAND_OUTPUT_MARKER_RE.split(cleaned, maxsplit=1)[0].strip()
    cleaned = re.split(
        r"\s+(?:\d+\.\s+|출력\s*예|검증\b|추가\s+리소스|NAME\s+STATUS|command\s+output)",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if re.fullmatch(r"(?:oc|kubectl|tkn|helm|curl)", cleaned, flags=re.IGNORECASE):
        return ""
    return cleaned


def sanitize_section_label(label: str) -> str:
    cleaned = strip_internal_markup(label)
    cleaned = SECTION_PREFIX_RE.sub("", cleaned)
    return SPACE_RE.sub(" ", cleaned).strip()


__all__ = [
    "sanitize_cli_command",
    "sanitize_section_label",
    "strip_internal_markup",
]
