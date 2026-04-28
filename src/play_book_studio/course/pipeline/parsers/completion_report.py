from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common import apply_chunk_identity, collect_image_attachments, deck_metadata, finalize_chunk, normalize_text
from ..layout_semantics import derive_slide_semantics
from ..slide_assets import load_render_index, resolve_slide_png
from ..slide_graph import iter_graph_slides


CHAPTER_ROMAN_RE = re.compile(r"([ⅠⅡⅢⅣⅤⅥIVX]+)\.")


def _chapter_marker(slide: dict[str, Any]) -> str:
    title = normalize_text(str(slide.get("title") or ""))
    text_blob = normalize_text(str(slide.get("text_blob") or ""))
    match = CHAPTER_ROMAN_RE.search(f"{title} {text_blob}")
    return match.group(1).upper() if match else ""


def parse_completion_report_deck(pptx_path: Path, slide_rows: list[dict[str, Any]]) -> dict[str, Any]:
    render_index = load_render_index(Path("tmp/ppt-render/_index.csv"))
    source_dir = Path("study-docs")
    grouped: dict[str, dict[str, Any]] = {}
    current_chapter_index = 1
    current_marker = "I"

    for slide in slide_rows:
        slide_no = int(slide.get("slide_no") or 0)
        marker = _chapter_marker(slide)
        if slide_no != 1 and marker and marker != current_marker:
            current_chapter_index += 1
            current_marker = marker

        current_chapter = f"CH-{current_chapter_index:02d}"
        chunk_title = normalize_text(str(slide.get("title") or current_chapter)) or current_chapter
        bucket = grouped.setdefault(
            current_chapter,
            {
                "canonical_model": "course_chunk_v1",
                "stage_id": "completion",
                "title": chunk_title,
                "native_id": current_chapter,
                "variant": None,
                "chunk_kind": "chapter_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"chapter": current_chapter},
                "slide_refs": [],
                "image_attachments": [],
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": [],
                "zone_relations": [],
                "related_official_docs": [],
                "facets": {"chapter_ids": [current_chapter]},
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            },
        )
        apply_chunk_identity(
            bucket,
            family="completion",
            native_id=current_chapter,
            chunk_kind="chapter_summary",
            variant=str(slide.get("design_variant") or "default"),
            local_key="summary",
        )

        zones, relations = derive_slide_semantics(slide)
        body_text = normalize_text(str(slide.get("text_blob") or ""))
        attachments = collect_image_attachments(slide, source_pptx=pptx_path)

        bucket["body_parts"].append(body_text)
        bucket["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": resolve_slide_png(render_index, source_dir, pptx_path, slide_no),
                "caption": "",
            }
        )
        bucket["image_attachments"].extend(attachments)
        bucket["semantic_zones"].extend(zones)
        bucket["zone_relations"].extend(relations)
        bucket["source_slide_range"][1] = slide_no

        title_text = normalize_text(str(slide.get("title") or ""))
        has_images = bool(attachments)
        has_table_like = any(str(zone.get("zone_type") or "") == "table_block" for zone in zones)
        has_title_keyword = any(keyword in title_text for keyword in ("WBS", "과업이행대비표", "목표 아키텍처", "구성", "결과"))
        if (has_images or has_table_like) and has_title_keyword:
            child_chunk_id = f"{current_chapter}--slide-{slide_no:03d}"
            bucket["child_chunk_ids"].append(child_chunk_id)
            grouped.setdefault("__children__", {}).setdefault("items", []).append(
                finalize_chunk(
                    {
                        "canonical_model": "course_chunk_v1",
                        "chunk_id": child_chunk_id,
                        "stage_id": "completion",
                        "title": chunk_title or f"{current_chapter} slide {slide_no}",
                        "native_id": current_chapter,
                        "variant": None,
                        "chunk_kind": "chapter_slide_detail",
                        "parent_chunk_id": current_chapter,
                        "child_chunk_ids": [],
                        "body_md": body_text,
                        "structured": {"chapter": current_chapter, "slide_no": slide_no},
                        "slide_refs": [bucket["slide_refs"][-1]],
                        "image_attachments": attachments,
                        "visual_summary": None,
                        "visual_text": "",
                        "search_text": "",
                        "semantic_zones": zones,
                        "zone_relations": relations,
                        "related_official_docs": [],
                        "source_pptx": str(pptx_path),
                        "source_slide_range": [slide_no, slide_no],
                    },
                    native_id=current_chapter,
                )
            )

    children = grouped.pop("__children__", {}).get("items", [])
    chunks: list[dict[str, Any]] = []
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
    chunks.extend(children)
    return {
        "deck": deck_metadata(pptx_path=pptx_path, template_family="completion_report", slide_rows=slide_rows, chunk_count=len(chunks)),
        "chunks": chunks,
    }


def parse_completion_report_graph(pptx_path: Path, slide_graph: dict[str, Any]) -> dict[str, Any]:
    graph_rows = iter_graph_slides(slide_graph)
    grouped: dict[str, dict[str, Any]] = {}
    current_chapter_index = 1
    current_marker = "I"

    for slide in graph_rows:
        slide_no = int(slide.get("slide_no") or 0)
        marker = _chapter_marker(slide)
        if slide_no != 1 and marker and marker != current_marker:
            current_chapter_index += 1
            current_marker = marker
        current_chapter = f"CH-{current_chapter_index:02d}"
        chunk_title = normalize_text(str(slide.get("title") or current_chapter)) or current_chapter
        bucket = grouped.setdefault(
            current_chapter,
            {
                "canonical_model": "course_chunk_v1",
                "stage_id": "completion",
                "title": chunk_title,
                "native_id": current_chapter,
                "variant": None,
                "chunk_kind": "chapter_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"chapter": current_chapter, "layout_type": str(slide.get("layout_type") or "narrative")},
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
        apply_chunk_identity(
            bucket,
            family="completion",
            native_id=current_chapter,
            chunk_kind="chapter_summary",
            variant=str(slide.get("design_variant") or "default"),
            local_key="summary",
        )
        body_text = normalize_text(str(slide.get("text_blob") or ""))
        attachments = slide.get("attachments") or []
        bucket["body_parts"].append(body_text)
        bucket["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": str(((slide.get("qa_refs") or {}) if isinstance(slide.get("qa_refs"), dict) else {}).get("full_slide_png") or ""),
                "caption": "",
            }
        )
        bucket["image_attachments"].extend(attachments)
        bucket["semantic_zones"].extend(slide.get("zones") or [])
        bucket["zone_relations"].extend(slide.get("relations") or [])
        bucket["source_slide_range"][1] = slide_no

        title_text = normalize_text(str(slide.get("title") or ""))
        has_images = bool(attachments)
        has_table_like = any(str(zone.get("zone_type") or "") == "table_block" for zone in (slide.get("zones") or []))
        has_title_keyword = any(keyword in title_text for keyword in ("WBS", "과업이행대비표", "목표 아키텍처", "구성", "결과"))
        if (has_images or has_table_like) and has_title_keyword:
            child = {
                "canonical_model": "course_chunk_v1",
                "stage_id": "completion",
                "title": chunk_title or f"{current_chapter} slide {slide_no}",
                "native_id": current_chapter,
                "variant": None,
                "chunk_kind": "chapter_slide_detail",
                "parent_chunk_id": bucket["chunk_id"],
                "child_chunk_ids": [],
                "body_md": body_text,
                "structured": {"chapter": current_chapter, "slide_no": slide_no},
                "facets": {"chapter_ids": [current_chapter], "slide_nos": [slide_no]},
                "slide_refs": [bucket["slide_refs"][-1]],
                "image_attachments": attachments,
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": slide.get("zones") or [],
                "zone_relations": slide.get("relations") or [],
                "related_official_docs": [],
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            }
            apply_chunk_identity(
                child,
                family="completion",
                native_id=current_chapter,
                chunk_kind="chapter_slide_detail",
                variant=str(slide.get("design_variant") or "default"),
                local_key=f"slide-{slide_no:03d}",
                root_chunk_id=bucket["chunk_id"],
            )
            child_chunk_id = child["chunk_id"]
            bucket["child_chunk_ids"].append(child_chunk_id)
            grouped.setdefault("__children__", {}).setdefault("items", []).append(
                finalize_chunk(child, native_id=current_chapter)
            )

    children = grouped.pop("__children__", {}).get("items", [])
    chunks: list[dict[str, Any]] = []
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
    chunks.extend(children)
    return {
        "deck": deck_metadata(pptx_path=pptx_path, template_family="completion_report", slide_rows=graph_rows, chunk_count=len(chunks)),
        "chunks": chunks,
    }


__all__ = ["parse_completion_report_deck", "parse_completion_report_graph"]
