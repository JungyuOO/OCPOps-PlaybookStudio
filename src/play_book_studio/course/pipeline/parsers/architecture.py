from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common import apply_chunk_identity, collect_image_attachments, deck_key_from_path, deck_metadata, finalize_chunk, normalize_text
from ..layout_semantics import derive_slide_semantics
from ..slide_assets import load_render_index, resolve_slide_png
from ..slide_graph import iter_graph_slides


DESIGN_ID_RE = re.compile(r"DSGN-005-\d{3}", re.IGNORECASE)


def parse_architecture_deck(pptx_path: Path, slide_rows: list[dict[str, Any]]) -> dict[str, Any]:
    render_index = load_render_index(Path("tmp/ppt-render/_index.csv"))
    source_dir = Path("study-docs")
    deck_key = deck_key_from_path(pptx_path)
    grouped: dict[str, dict[str, Any]] = {}
    for slide in slide_rows:
        text_blob = str(slide.get("text_blob") or "")
        match = DESIGN_ID_RE.search(text_blob)
        if not match:
            continue
        design_id = match.group(0).upper()
        slide_no = int(slide.get("slide_no") or 0)
        bucket = grouped.setdefault(
            design_id,
            {
                "canonical_model": "course_chunk_v1",
                "stage_id": "architecture",
                "title": normalize_text(str(slide.get("title") or design_id)) or design_id,
                "native_id": design_id,
                "variant": None,
                "chunk_kind": "design_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"design_id": design_id},
                "slide_refs": [],
                "image_attachments": [],
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": [],
                "zone_relations": [],
                "related_official_docs": [],
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            },
        )
        zones, relations = derive_slide_semantics(slide)
        bucket["body_parts"].append(normalize_text(text_blob))
        bucket["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": resolve_slide_png(render_index, source_dir, pptx_path, slide_no),
                "caption": "",
            }
        )
        bucket["image_attachments"].extend(collect_image_attachments(slide, source_pptx=pptx_path))
        bucket["semantic_zones"].extend(zones)
        bucket["zone_relations"].extend(relations)
        bucket["source_slide_range"][1] = slide_no
    chunks = []
    for bucket in grouped.values():
        body_parts = bucket.pop("body_parts")
        chunks.append(
            finalize_chunk(
                {
                    **bucket,
                    "body_md": "\n\n".join(part for part in body_parts if part),
                },
                native_id=str(bucket.get("native_id") or ""),
            )
        )
    chunks.sort(key=lambda item: str(item.get("chunk_id") or ""))
    return {"deck": deck_metadata(pptx_path=pptx_path, template_family="architecture", slide_rows=slide_rows, chunk_count=len(chunks)), "chunks": chunks}


def parse_architecture_graph(pptx_path: Path, slide_graph: dict[str, Any]) -> dict[str, Any]:
    graph_rows = iter_graph_slides(slide_graph)
    grouped: dict[str, dict[str, Any]] = {}
    for slide in graph_rows:
        design_id = str(slide.get("design_id") or "").strip()
        if not design_id:
            continue
        slide_no = int(slide.get("slide_no") or 0)
        bucket = grouped.setdefault(
            design_id,
            {
                "canonical_model": "course_chunk_v1",
                "stage_id": "architecture",
                "title": normalize_text(str(slide.get("title") or design_id)) or design_id,
                "native_id": design_id,
                "variant": str(slide.get("design_variant") or "default"),
                "chunk_kind": "design_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"design_id": design_id, "layout_type": str(slide.get("layout_type") or "mixed")},
                "slide_refs": [],
                "image_attachments": [],
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": [],
                "zone_relations": [],
                "related_official_docs": [],
                "facets": {"design_ids": [design_id]},
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            },
        )
        apply_chunk_identity(
            bucket,
            family="architecture",
            native_id=design_id,
            chunk_kind="design_summary",
            variant=str(slide.get("design_variant") or "default"),
            local_key="summary",
        )
        bucket["body_parts"].append(normalize_text(str(slide.get("text_blob") or "")))
        bucket["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": str(((slide.get("qa_refs") or {}) if isinstance(slide.get("qa_refs"), dict) else {}).get("full_slide_png") or ""),
                "caption": "",
            }
        )
        bucket["image_attachments"].extend(slide.get("attachments") or [])
        bucket["semantic_zones"].extend(slide.get("zones") or [])
        bucket["zone_relations"].extend(slide.get("relations") or [])
        bucket["source_slide_range"][1] = slide_no
    chunks = []
    for bucket in grouped.values():
        body_parts = bucket.pop("body_parts")
        chunks.append(
            finalize_chunk(
                {
                    **bucket,
                    "body_md": "\n\n".join(part for part in body_parts if part),
                },
                native_id=str(bucket.get("native_id") or ""),
            )
        )
    chunks.sort(key=lambda item: str(item.get("chunk_id") or ""))
    return {"deck": deck_metadata(pptx_path=pptx_path, template_family="architecture", slide_rows=graph_rows, chunk_count=len(chunks)), "chunks": chunks}


__all__ = ["parse_architecture_deck", "parse_architecture_graph"]
