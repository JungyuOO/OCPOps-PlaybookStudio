"""Sanitizers for text that is shown back to users or the answer prompt."""

from __future__ import annotations

import re


SPACE_RE = re.compile(r"[ \t]+")
INTERNAL_MARKUP_RE = re.compile(r"\[/?(?:CODE|TABLE)(?:[^\]]*)?\]", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*|\s*```$", re.MULTILINE)
SECTION_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")


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
    return cleaned.strip("` ")


def sanitize_section_label(label: str) -> str:
    cleaned = strip_internal_markup(label)
    cleaned = SECTION_PREFIX_RE.sub("", cleaned)
    return SPACE_RE.sub(" ", cleaned).strip()


__all__ = [
    "sanitize_cli_command",
    "sanitize_section_label",
    "strip_internal_markup",
]
