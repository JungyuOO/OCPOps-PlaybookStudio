from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import deck_metadata


def build_deck_checkpoint(*, pptx_path: Path, template_family: str, slide_rows: list[dict[str, Any]], chunk_count: int) -> dict[str, Any]:
    return deck_metadata(
        pptx_path=pptx_path,
        template_family=template_family,
        slide_rows=slide_rows,
        chunk_count=chunk_count,
    )


def should_rebuild(existing: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not existing:
        return True
    return any(
        existing.get(key) != current.get(key)
        for key in ("source_mtime_ns", "source_size_bytes", "deck_fingerprint", "template_family")
    )


__all__ = ["build_deck_checkpoint", "should_rebuild"]
