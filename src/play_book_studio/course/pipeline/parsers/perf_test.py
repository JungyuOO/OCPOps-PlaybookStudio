from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common import apply_chunk_identity, collect_image_attachments, deck_key_from_path, deck_metadata, document_front_matter_id, finalize_chunk, normalize_text
from ..layout_semantics import derive_slide_semantics
from ..slide_graph import iter_graph_slides
from ..slide_assets import load_render_index, resolve_slide_png


SECTION_RE = re.compile(r"(\d+)\.\s*([^\n|]+)")


def _has_detail_signal(body_text: str, attachments: list[dict[str, Any]], zones: list[dict[str, Any]]) -> bool:
    if normalize_text(body_text) or attachments:
        return True
    return any(isinstance(zone, dict) and normalize_text(str(zone.get("text") or "")) for zone in zones)


def _perf_section(slide: dict[str, Any]) -> tuple[str, str]:
    title = normalize_text(str(slide.get("title") or ""))
    text_blob = normalize_text(str(slide.get("text_blob") or ""))
    for candidate in (title, text_blob):
        match = SECTION_RE.search(candidate)
        if match:
            return match.group(1), normalize_text(match.group(2))
    return f"slide-{int(slide.get('slide_no') or 0):03d}", title or f"Perf Section {int(slide.get('slide_no') or 0)}"


def parse_perf_test_deck(pptx_path: Path, slide_rows: list[dict[str, Any]]) -> dict[str, Any]:
    render_index = load_render_index(Path("tmp/ppt-render/_index.csv"))
    source_dir = Path("study-docs")
    deck_key = deck_key_from_path(pptx_path)
    grouped: dict[str, dict[str, Any]] = {}

    for slide in slide_rows:
        slide_no = int(slide.get("slide_no") or 0)
        section_no, section_title = _perf_section(slide)
        if section_no.startswith("slide-"):
            section_no = document_front_matter_id(pptx_path)
            section_title = section_title or "문서 앞부분"
        zones, relations = derive_slide_semantics(slide)
        parent_chunk_id = f"PERF-{deck_key}-{section_no}"
        parent = grouped.setdefault(
            section_no,
            {
                "canonical_model": "course_chunk_v1",
                "chunk_id": parent_chunk_id,
                "stage_id": "perf_test",
                "title": section_title or f"Performance Section {section_no}",
                "native_id": section_no,
                "variant": None,
                "chunk_kind": "perf_section_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"section_id": section_no},
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
        body_text = normalize_text(str(slide.get("text_blob") or ""))
        parent["body_parts"].append(body_text)
        attachments = collect_image_attachments(slide, source_pptx=pptx_path)
        parent["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": resolve_slide_png(render_index, source_dir, pptx_path, slide_no),
                "caption": "",
            }
        )
        parent["image_attachments"].extend(attachments)
        parent["semantic_zones"].extend(zones)
        parent["zone_relations"].extend(relations)
        parent["source_slide_range"][1] = slide_no

        title_text = normalize_text(str(slide.get("title") or "")).lower()
        has_images = bool(attachments)
        has_table_like = any(str(zone.get("zone_type") or "") == "table_block" for zone in zones)
        has_title_keyword = any(keyword in title_text for keyword in ("상세", "결과", "방법론", "그래프"))
        if (has_images or has_table_like) and has_title_keyword and _has_detail_signal(body_text, attachments, zones):
            child_chunk_id = f"{parent_chunk_id}--slide-{slide_no:03d}"
            parent["child_chunk_ids"].append(child_chunk_id)
            child = {
                "canonical_model": "course_chunk_v1",
                "chunk_id": child_chunk_id,
                "stage_id": "perf_test",
                "title": str(slide.get("title") or f"{section_title} detail"),
                "native_id": section_no,
                "variant": None,
                "chunk_kind": "perf_slide_detail",
                "parent_chunk_id": parent_chunk_id,
                "child_chunk_ids": [],
                "body_md": body_text,
                "structured": {"section_id": section_no, "slide_no": slide_no},
                "slide_refs": [parent["slide_refs"][-1]],
                "image_attachments": attachments,
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": zones,
                "zone_relations": relations,
                "related_official_docs": [],
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            }
            grouped.setdefault("__children__", {}).setdefault("items", []).append(finalize_chunk(child, native_id=section_no))

    children = grouped.pop("__children__", {}).get("items", [])
    parents: list[dict[str, Any]] = []
    for bucket in grouped.values():
        parent = {
            **bucket,
            "body_md": "\n\n".join(part for part in bucket.pop("body_parts") if part),
        }
        parents.append(finalize_chunk(parent, native_id=str(parent["native_id"])))
    chunks = sorted(parents, key=lambda item: str(item.get("chunk_id") or "")) + children
    return {
        "deck": deck_metadata(pptx_path=pptx_path, template_family="perf_test", slide_rows=slide_rows, chunk_count=len(chunks)),
        "chunks": chunks,
    }


def parse_perf_test_graph(pptx_path: Path, slide_graph: dict[str, Any]) -> dict[str, Any]:
    graph_rows = iter_graph_slides(slide_graph)
    grouped: dict[str, dict[str, Any]] = {}

    for slide in graph_rows:
        slide_no = int(slide.get("slide_no") or 0)
        section_no, section_title = _perf_section(slide)
        if section_no.startswith("slide-"):
            section_no = document_front_matter_id(pptx_path)
            section_title = section_title or "문서 앞부분"
        zones = slide.get("zones") if isinstance(slide.get("zones"), list) else []
        relations = slide.get("relations") if isinstance(slide.get("relations"), list) else []
        attachments = slide.get("attachments") if isinstance(slide.get("attachments"), list) else []
        parent = grouped.setdefault(
            section_no,
            {
                "canonical_model": "course_chunk_v1",
                "stage_id": "perf_test",
                "title": section_title or f"Performance Section {section_no}",
                "native_id": section_no,
                "variant": None,
                "chunk_kind": "perf_section_summary",
                "parent_chunk_id": None,
                "child_chunk_ids": [],
                "body_parts": [],
                "structured": {"section_id": section_no, "layout_type": str(slide.get("layout_type") or "mixed")},
                "slide_refs": [],
                "image_attachments": [],
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": [],
                "zone_relations": [],
                "related_official_docs": [],
                "facets": {"section_ids": [section_no]},
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            },
        )
        apply_chunk_identity(
            parent,
            family="perf_test",
            native_id=section_no,
            chunk_kind="perf_section_summary",
            variant=str(slide.get("design_variant") or "default"),
            local_key="summary",
        )
        body_text = normalize_text(str(slide.get("text_blob") or ""))
        parent["body_parts"].append(body_text)
        parent["slide_refs"].append(
            {
                "pptx": str(pptx_path),
                "slide_no": slide_no,
                "png_path": str(((slide.get("qa_refs") or {}) if isinstance(slide.get("qa_refs"), dict) else {}).get("full_slide_png") or ""),
                "caption": "",
            }
        )
        parent["image_attachments"].extend(attachments)
        parent["semantic_zones"].extend(zones)
        parent["zone_relations"].extend(relations)
        parent["source_slide_range"][1] = slide_no

        title_text = normalize_text(str(slide.get("title") or "")).lower()
        has_images = bool(attachments)
        has_table_like = any(str(zone.get("zone_type") or "") == "table_block" for zone in zones if isinstance(zone, dict))
        has_title_keyword = any(keyword in title_text for keyword in ("상세", "결과", "방법론", "그래프"))
        if (has_images or has_table_like) and has_title_keyword and _has_detail_signal(body_text, attachments, zones):
            child = {
                "canonical_model": "course_chunk_v1",
                "stage_id": "perf_test",
                "title": str(slide.get("title") or f"{section_title} detail"),
                "native_id": section_no,
                "variant": None,
                "chunk_kind": "perf_slide_detail",
                "parent_chunk_id": parent["chunk_id"],
                "child_chunk_ids": [],
                "body_md": body_text,
                "structured": {"section_id": section_no, "slide_no": slide_no},
                "facets": {"section_ids": [section_no], "slide_nos": [slide_no]},
                "slide_refs": [parent["slide_refs"][-1]],
                "image_attachments": attachments,
                "visual_summary": None,
                "visual_text": "",
                "search_text": "",
                "semantic_zones": zones,
                "zone_relations": relations,
                "related_official_docs": [],
                "source_pptx": str(pptx_path),
                "source_slide_range": [slide_no, slide_no],
            }
            apply_chunk_identity(
                child,
                family="perf_test",
                native_id=section_no,
                chunk_kind="perf_slide_detail",
                variant=str(slide.get("design_variant") or "default"),
                local_key=f"slide-{slide_no:03d}",
                root_chunk_id=parent["chunk_id"],
            )
            child_chunk_id = child["chunk_id"]
            parent["child_chunk_ids"].append(child_chunk_id)
            grouped.setdefault("__children__", {}).setdefault("items", []).append(finalize_chunk(child, native_id=section_no))

    children = grouped.pop("__children__", {}).get("items", [])
    parents: list[dict[str, Any]] = []
    for bucket in grouped.values():
        parent = {
            **bucket,
            "body_md": "\n\n".join(part for part in bucket.pop("body_parts") if part),
        }
        parents.append(finalize_chunk(parent, native_id=str(parent["native_id"])))
    chunks = sorted(parents, key=lambda item: str(item.get("chunk_id") or "")) + children
    return {
        "deck": deck_metadata(pptx_path=pptx_path, template_family="perf_test", slide_rows=graph_rows, chunk_count=len(chunks)),
        "chunks": chunks,
    }


__all__ = ["parse_perf_test_deck", "parse_perf_test_graph"]
