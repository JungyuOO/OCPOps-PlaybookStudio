from __future__ import annotations

import csv
from pathlib import Path


def load_render_index(index_path: Path) -> dict[str, Path]:
    if not index_path.exists():
        return {}
    mapping: dict[str, Path] = {}
    with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = str(row.get("file") or "").strip()
            out_dir = str(row.get("out") or "").strip()
            if not source or not out_dir:
                continue
            mapping[source.replace("/", "\\")] = Path(out_dir)
    return mapping


def resolve_slide_png(render_index: dict[str, Path], source_dir: Path, pptx_path: Path, slide_no: int) -> str:
    relative = str(pptx_path.resolve().relative_to(source_dir.resolve())).replace("/", "\\")
    out_dir = render_index.get(relative)
    if out_dir is None:
        return ""
    slide_path = out_dir / f"slide_{int(slide_no):03d}.png"
    return str(slide_path) if slide_path.exists() else ""


__all__ = ["load_render_index", "resolve_slide_png"]
