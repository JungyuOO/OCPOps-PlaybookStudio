from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common import apply_chunk_identity, deck_metadata, finalize_chunk, normalize_text
from ..slide_graph import iter_graph_slides


UNIT_TEST_ID_RE = re.compile(r"TEST-UN-OCP-\d{2}-\d{2}", re.IGNORECASE)
QUADRANT_LABELS = ("method", "expected", "verification", "result")


def _extract_unit_test_id(text_blob: str) -> str | None:
    match = UNIT_TEST_ID_RE.search(text_blob)
    return match.group(0).upper() if match else None


def _variant_from_filename(pptx_path: Path) -> str:
    name = pptx_path.stem.lower()
    if "결과" in name:
        return "result"
    if "서비스" in name:
        return "service-plan"
    return "plan"


def _quadrant_label(zone: dict[str, Any]) -> str:
    bbox = zone.get("bbox_norm") if isinstance(zone.get("bbox_norm"), list) else []
    if len(bbox) != 4:
        return "result"
    left, top, right, bottom = [float(value or 0) for value in bbox]
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    if center_x < 0.5 and center_y < 0.5:
        return "method"
    if center_x >= 0.5 and center_y < 0.5:
        return "expected"
    if center_x < 0.5 and center_y >= 0.5:
        return "verification"
    return "result"


def parse_unit_test_graph(pptx_path: Path, slide_graph: dict[str, Any]) -> dict[str, Any]:
    graph_rows = iter_graph_slides(slide_graph)
    variant = _variant_from_filename(pptx_path)
    chunks: list[dict[str, Any]] = []

    for slide in graph_rows:
        text_blob = normalize_text(str(slide.get("text_blob") or ""))
        test_id = _extract_unit_test_id(f"{slide.get('title') or ''} {text_blob}")
        if not test_id:
            continue
        slide_no = int(slide.get("slide_no") or 0)
        zones = [zone for zone in (slide.get("zones") or []) if isinstance(zone, dict)]
        relations = [relation for relation in (slide.get("relations") or []) if isinstance(relation, dict)]
        attachments = [attachment for attachment in (slide.get("attachments") or []) if isinstance(attachment, dict)]
        buckets = {label: [] for label in QUADRANT_LABELS}
        for zone in zones:
            text = normalize_text(str(zone.get("text") or ""))
            if not text or test_id in text.upper():
                continue
            role = str(zone.get("role") or "")
            if role in {"title", "footer", "caption", "legend"}:
                continue
            buckets[_quadrant_label(zone)].append(text)

        parent = {
            "canonical_model": "course_chunk_v1",
            "stage_id": "unit_test",
            "title": normalize_text(str(slide.get("title") or test_id)) or test_id,
            "variant": variant,
            "chunk_kind": "test_case_summary",
            "parent_chunk_id": None,
            "child_chunk_ids": [],
            "body_md": text_blob,
            "structured": {key: "\n".join(values).strip() for key, values in buckets.items() if values},
            "facets": {"test_ids": [test_id]},
            "slide_refs": [
                {
                    "pptx": str(pptx_path),
                    "slide_no": slide_no,
                    "png_path": str(((slide.get("qa_refs") or {}) if isinstance(slide.get("qa_refs"), dict) else {}).get("full_slide_png") or ""),
                    "caption": "",
                }
            ],
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
            parent,
            family="unit_test",
            native_id=test_id,
            chunk_kind="test_case_summary",
            variant=variant,
            local_key="summary",
        )
        parent["root_chunk_id"] = parent["chunk_id"]

        children: list[dict[str, Any]] = []
        for section_name in QUADRANT_LABELS:
            section_text = "\n".join(buckets[section_name]).strip()
            if not section_text:
                continue
            child = {
                "canonical_model": "course_chunk_v1",
                "stage_id": "unit_test",
                "title": f"{test_id} {section_name}",
                "variant": variant,
                "chunk_kind": f"test_case_{section_name}",
                "parent_chunk_id": parent["chunk_id"],
                "child_chunk_ids": [],
                "body_md": section_text,
                "structured": {"section_name": section_name},
                "facets": {"test_ids": [test_id], "section_names": [section_name]},
                "slide_refs": parent["slide_refs"],
                "image_attachments": [],
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
                family="unit_test",
                native_id=test_id,
                chunk_kind=f"test_case_{section_name}",
                variant=variant,
                local_key=section_name,
                root_chunk_id=parent["chunk_id"],
            )
            parent["child_chunk_ids"].append(child["chunk_id"])
            children.append(finalize_chunk(child, native_id=test_id))

        chunks.append(finalize_chunk(parent, native_id=test_id))
        chunks.extend(children)

    return {
        "deck": deck_metadata(pptx_path=pptx_path, template_family="unit_test", slide_rows=graph_rows, chunk_count=len(chunks)),
        "chunks": chunks,
    }


__all__ = ["parse_unit_test_graph", "UNIT_TEST_ID_RE"]
