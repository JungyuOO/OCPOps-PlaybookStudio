from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_course_chunks(course_dir: Path) -> list[dict[str, Any]]:
    chunks_jsonl = course_dir / "chunks.jsonl"
    if chunks_jsonl.exists():
        chunks: list[dict[str, Any]] = []
        for line in chunks_jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "").strip():
                chunks.append(chunk)
        return chunks
    chunks_dir = course_dir / "chunks"
    if not chunks_dir.exists():
        raise FileNotFoundError(f"course chunks file not found: {chunks_jsonl}")
    chunks: list[dict[str, Any]] = []
    for path in sorted(chunks_dir.glob("*.json")):
        chunk = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "").strip():
            chunks.append(chunk)
    return chunks


__all__ = ["load_course_chunks"]
