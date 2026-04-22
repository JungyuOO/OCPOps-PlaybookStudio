from __future__ import annotations

from functools import lru_cache
from pathlib import Path

try:  # pragma: no cover - optional runtime dependency
    from markitdown import MarkItDown
except Exception:  # noqa: BLE001
    MarkItDown = None


MARKITDOWN_SOURCE_TYPES = frozenset({"pdf", "docx", "pptx", "xlsx"})


@lru_cache(maxsize=1)
def _converter():
    if MarkItDown is None:
        raise RuntimeError("markitdown dependency is unavailable")
    return MarkItDown(enable_plugins=False)


def convert_with_markitdown(path: Path) -> str:
    converter = _converter()
    result = converter.convert(str(path))
    text = str(getattr(result, "text_content", "") or "").strip()
    if not text:
        raise ValueError(f"MarkItDown produced empty markdown for {path.name}.")
    return text


__all__ = ["MARKITDOWN_SOURCE_TYPES", "convert_with_markitdown"]
