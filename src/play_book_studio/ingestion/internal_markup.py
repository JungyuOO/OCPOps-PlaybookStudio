"""Helpers for rendering internal parser markup into retrieval-safe text."""

from __future__ import annotations

import re


CODE_BLOCK_RE = re.compile(r"\[CODE(?P<attrs>[^\]]*)\]\s*(?P<body>.*?)\s*\[/CODE\]", re.DOTALL | re.IGNORECASE)
TABLE_BLOCK_RE = re.compile(r"\[TABLE(?P<attrs>[^\]]*)\]\s*(?P<body>.*?)\s*\[/TABLE\]", re.DOTALL | re.IGNORECASE)
LANGUAGE_RE = re.compile(r'language="([^"]+)"', re.IGNORECASE)
CAPTION_RE = re.compile(r'caption="([^"]+)"', re.IGNORECASE)


def _caption(attrs: str) -> str:
    match = CAPTION_RE.search(attrs or "")
    return str(match.group(1)).strip() if match else ""


def _language(attrs: str) -> str:
    match = LANGUAGE_RE.search(attrs or "")
    language = str(match.group(1)).strip() if match else ""
    if language in {"shell-session", "terminal"}:
        return "shell"
    if language == "plaintext":
        return "text"
    return language


def render_internal_markup_for_retrieval(text: str) -> str:
    """Convert `[CODE]`/`[TABLE]` parser markers into user-facing markdown."""

    def code_replacement(match: re.Match[str]) -> str:
        attrs = str(match.group("attrs") or "")
        body = str(match.group("body") or "").strip()
        if not body:
            return ""
        language = _language(attrs)
        caption = _caption(attrs)
        caption_text = f"{caption}\n" if caption else ""
        return f"{caption_text}```{language}\n{body}\n```".strip()

    def table_replacement(match: re.Match[str]) -> str:
        attrs = str(match.group("attrs") or "")
        body = str(match.group("body") or "").strip()
        if not body:
            return ""
        caption = _caption(attrs)
        return f"{caption}\n{body}".strip() if caption else body

    rendered = CODE_BLOCK_RE.sub(code_replacement, str(text or ""))
    rendered = TABLE_BLOCK_RE.sub(table_replacement, rendered)
    return re.sub(r"\n{3,}", "\n\n", rendered).strip()
