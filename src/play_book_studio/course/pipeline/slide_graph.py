from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from .common import deck_key_from_path, normalize_text, relative_project_path
from .layout_semantics import derive_slide_semantics
from .slide_assets import load_render_index, resolve_slide_png
from .template_classifier import DESIGN_ID_RE, UNIT_TEST_ID_RE


CHAPTER_ROMAN_RE = re.compile(r"([A-ZIVX]+)\.", re.IGNORECASE)
SLIDE_FALLBACK_RE = re.compile(r"^slide\s+\d+$", re.IGNORECASE)


def _is_placeholder_title(text: str) -> bool:
    normalized = normalize_text(text)
    return not normalized or bool(SLIDE_FALLBACK_RE.match(normalized))


def _semantic_title_from_zones(zones_raw: list[dict[str, Any]], *, exclude_tokens: list[str] | None = None) -> str:
    exclude = {normalize_text(token).lower() for token in (exclude_tokens or []) if normalize_text(token)}
    for role in ("title", "step", "label", "body"):
        candidates: list[str] = []
        for zone in zones_raw:
            if not isinstance(zone, dict):
                continue
            if str(zone.get("zone_role") or "") != role:
                continue
            text = normalize_text(str(zone.get("text") or ""))
            if _is_placeholder_title(text):
                continue
            lowered = text.lower()
            if lowered in exclude:
                continue
            if exclude and any(lowered == token or lowered.startswith(f"{token} ") for token in exclude):
                continue
            candidates.append(text)
        if candidates:
            candidates.sort(key=len, reverse=True)
            return candidates[0]
    return ""


def _deck_title_fallback(deck_path: Path) -> str:
    stem = normalize_text(deck_path.stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\bFINAL\b", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\b\d{8}\b", "", stem)
    stem = normalize_text(stem)
    return stem


def _slide_identity(family: str, slide: dict[str, Any], zones_raw: list[dict[str, Any]], *, deck_path: Path) -> tuple[str, str, str]:
    text_blob = normalize_text(str(slide.get("text_blob") or ""))
    title = normalize_text(str(slide.get("title") or ""))
    safe_title = "" if _is_placeholder_title(title) else title
    combined = f"{safe_title} {text_blob}"

    if family == "architecture":
        match = DESIGN_ID_RE.search(combined)
        if match:
            design_id = match.group(0).upper()
            semantic_title = _semantic_title_from_zones(zones_raw, exclude_tokens=[design_id])
            return design_id, semantic_title or safe_title or design_id, "default"

    if family == "unit_test":
        match = UNIT_TEST_ID_RE.search(combined)
        if match:
            test_id = match.group(0).upper()
            semantic_title = _semantic_title_from_zones(zones_raw, exclude_tokens=[test_id])
            return test_id, semantic_title or safe_title or test_id, "default"

    if family == "completion_report":
        match = CHAPTER_ROMAN_RE.search(combined)
        if match:
            marker = match.group(1).upper()
            semantic_title = _semantic_title_from_zones(zones_raw, exclude_tokens=[f"CH-{marker}", marker])
            return f"CH-{marker}", semantic_title or safe_title or f"Chapter {marker}", "default"

    semantic_title = _semantic_title_from_zones(zones_raw)
    if semantic_title or safe_title:
        return "", semantic_title or safe_title, "default"
    if int(slide.get("slide_no") or 0) == 1:
        deck_title = _deck_title_fallback(deck_path)
        if deck_title:
            return "", deck_title, "default"
    return "", f"Slide {int(slide.get('slide_no') or 0)}", "default"


def _layout_type(family: str, slide: dict[str, Any], zones: list[dict[str, Any]], relations: list[dict[str, Any]]) -> str:
    if family == "completion_report":
        return "narrative"
    has_table = any(str(zone.get("zone_role") or "") == "table" for zone in zones)
    has_steps = any(str(zone.get("zone_role") or "") == "step" for zone in zones)
    has_images = any(str(zone.get("zone_role") or "") == "image" for zone in zones)
    if has_steps and any(str(rel.get("type") or "") == "step_next" for rel in relations):
        return "flow"
    if has_table and has_images:
        return "table_with_notes"
    if has_table:
        return "table"
    if family == "architecture" and has_images:
        return "component_diagram"
    if family == "integration_test":
        return "comparison"
    if family == "perf_test":
        return "table_with_notes"
    return "mixed"


def _region_for_bbox(top: int, height: int, slide_height: int) -> str:
    center = top + height / 2
    if center < slide_height * 0.2:
        return "top"
    if center > slide_height * 0.8:
        return "bottom"
    return "middle"


def _discard_rules(slide_rows: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()
    for slide in slide_rows:
        shapes = slide.get("shapes") if isinstance(slide.get("shapes"), list) else []
        slide_height = max((int(shape.get("top", 0)) + int(shape.get("height", 0)) for shape in shapes), default=1)
        for shape in shapes:
            if not isinstance(shape, dict):
                continue
            text = normalize_text(str(shape.get("text") or ""))
            if not text:
                continue
            top = int(shape.get("top") or 0)
            height = int(shape.get("height") or 0)
            region = _region_for_bbox(top, height, slide_height)
            if region == "top":
                top_counter[text] += 1
            elif region == "bottom":
                bottom_counter[text] += 1
    return top_counter, bottom_counter


def _attachment_records(deck_id: str, slide: dict[str, Any], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    zone_map = {int(zone.get("shape_index") or 0): zone for zone in zones}
    slide_no = int(slide.get("slide_no") or 0)
    for index, shape in enumerate(slide.get("shapes") or [], start=1):
        if not isinstance(shape, dict):
            continue
        if str(shape.get("shape_type") or "") != "picture":
            continue
        blob = shape.get("image_blob")
        if not isinstance(blob, (bytes, bytearray)):
            continue
        zone = zone_map.get(int(shape.get("shape_index") or 0))
        rows.append(
            {
                "attachment_id": f"att_{index:02d}",
                "type": "image_shape",
                "shape_index": int(shape.get("shape_index") or 0),
                "zone_id": str((zone or {}).get("zone_id") or ""),
                "asset_path": "",
                "bbox_norm": [],
                "role": "diagram" if str((zone or {}).get("zone_role") or "") == "image" else "illustration",
                "caption_text": "",
                "visual_summary": "",
                "confidence": 0.8,
                "_blob": bytes(blob),
                "_ext": str(shape.get("image_ext") or "png"),
                "_slide_no": slide_no,
                "_deck_id": deck_id,
            }
        )
    return rows


def build_slide_graph(deck_path: Path, family: str, slide_rows: list[dict[str, Any]], *, source_dir: Path) -> dict[str, Any]:
    deck_id = deck_key_from_path(deck_path, source_dir=source_dir)
    render_index = load_render_index(Path("tmp/ppt-render/_index.csv"))
    top_counter, bottom_counter = _discard_rules(slide_rows)
    slides_payload: list[dict[str, Any]] = []

    for slide in slide_rows:
        slide_no = int(slide.get("slide_no") or 0)
        zones_raw, relations = derive_slide_semantics(slide)
        design_id, design_title, design_variant = _slide_identity(family, slide, zones_raw, deck_path=deck_path)
        shapes = slide.get("shapes") if isinstance(slide.get("shapes"), list) else []
        slide_width = max((int(shape.get("left", 0)) + int(shape.get("width", 0)) for shape in shapes), default=1)
        slide_height = max((int(shape.get("top", 0)) + int(shape.get("height", 0)) for shape in shapes), default=1)
        zones: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []

        for order_hint, zone in enumerate(zones_raw):
            bbox = zone.get("bbox") if isinstance(zone.get("bbox"), dict) else {}
            text = normalize_text(str(zone.get("text") or ""))
            region = _region_for_bbox(int(bbox.get("top") or 0), int(bbox.get("height") or 0), slide_height)
            repeated = (region == "top" and text and top_counter[text] >= 3) or (region == "bottom" and text and bottom_counter[text] >= 3)
            record = {
                "zone_id": str(zone.get("zone_id") or ""),
                "source_shape_ids": [int(zone.get("shape_index") or 0)],
                "zone_type": "image" if str(zone.get("zone_role") or "") == "image" else ("table_block" if str(zone.get("zone_role") or "") == "table" else "text_cluster"),
                "role": str(zone.get("zone_role") or "body"),
                "bbox_norm": [
                    round(int(bbox.get("left") or 0) / max(slide_width, 1), 4),
                    round(int(bbox.get("top") or 0) / max(slide_height, 1), 4),
                    round((int(bbox.get("left") or 0) + int(bbox.get("width") or 0)) / max(slide_width, 1), 4),
                    round((int(bbox.get("top") or 0) + int(bbox.get("height") or 0)) / max(slide_height, 1), 4),
                ],
                "region": region,
                "text": text,
                "row_idx": None,
                "col_idx": None,
                "order_hint": order_hint,
                "confidence": 0.9,
                "flags": {
                    "repeated_across_deck": bool(repeated),
                    "decorative_only": False,
                    "discard_candidate": bool(repeated),
                },
            }
            if repeated:
                discarded.append({"zone_id": record["zone_id"], "reason": "repeated_header_footer", "text": text})
            else:
                zones.append(record)

        attachments = _attachment_records(deck_id, slide, zones)
        slides_payload.append(
            {
                "slide": {
                    "slide_no": slide_no,
                    "slide_uid": f"{deck_id}#{slide_no}",
                    "design_id": design_id,
                    "design_title": design_title,
                    "design_variant": design_variant,
                    "part_no": None,
                    "part_total": None,
                    "layout_type": _layout_type(family, slide, zones, relations),
                },
                "layout_hints": {
                    "has_numbered_steps": any(str(zone.get("role") or "") == "step" for zone in zones),
                    "has_swimlanes": False,
                    "has_table": any(str(zone.get("zone_type") or "") == "table_block" for zone in zones),
                    "has_large_image": any(str(zone.get("zone_type") or "") == "image" for zone in zones),
                    "has_repeated_header_footer": bool(discarded),
                },
                "zones": zones,
                "relations": relations,
                "attachments": attachments,
                "discarded_zones": discarded,
                "qa_refs": {
                    "full_slide_png": relative_project_path(
                        resolve_slide_png(render_index, source_dir, deck_path, slide_no),
                        project_root=source_dir.parent.resolve(),
                    ),
                },
            }
        )

    return {
        "schema_version": "ppt_slide_graph_v1",
        "deck": {
            "deck_id": deck_id,
            "family": family,
            "source_file": relative_project_path(deck_path, project_root=source_dir.parent.resolve()),
        },
        "slides": slides_payload,
    }


def graph_slide_text(slide_payload: dict[str, Any]) -> str:
    zones = slide_payload.get("zones") if isinstance(slide_payload.get("zones"), list) else []
    ordered = sorted((zone for zone in zones if isinstance(zone, dict)), key=lambda item: int(item.get("order_hint") or 0))
    return "\n".join(
        normalize_text(str(zone.get("text") or ""))
        for zone in ordered
        if normalize_text(str(zone.get("text") or ""))
    ).strip()


def iter_graph_slides(slide_graph: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slide_payload in slide_graph.get("slides") if isinstance(slide_graph.get("slides"), list) else []:
        if not isinstance(slide_payload, dict):
            continue
        slide_meta = slide_payload.get("slide") if isinstance(slide_payload.get("slide"), dict) else {}
        rows.append(
            {
                "slide_no": int(slide_meta.get("slide_no") or 0),
                "title": str(slide_meta.get("design_title") or ""),
                "design_id": str(slide_meta.get("design_id") or ""),
                "design_variant": str(slide_meta.get("design_variant") or "default"),
                "layout_type": str(slide_meta.get("layout_type") or "mixed"),
                "zones": slide_payload.get("zones") or [],
                "relations": slide_payload.get("relations") or [],
                "attachments": slide_payload.get("attachments") or [],
                "qa_refs": slide_payload.get("qa_refs") or {},
                "text_blob": graph_slide_text(slide_payload),
            }
        )
    return rows


def write_slide_graphs(output_dir: Path, slide_graphs: list[dict[str, Any]]) -> None:
    graphs_dir = output_dir / "slide_graphs"
    graph_assets_dir = output_dir / "slide_graph_assets"
    if graphs_dir.exists():
        shutil.rmtree(graphs_dir)
    if graph_assets_dir.exists():
        shutil.rmtree(graph_assets_dir)
    graphs_dir.mkdir(parents=True, exist_ok=True)
    graph_assets_dir.mkdir(parents=True, exist_ok=True)
    project_root = output_dir.parent.parent.resolve()

    for graph in slide_graphs:
        deck = graph.get("deck") if isinstance(graph.get("deck"), dict) else {}
        deck_id = str(deck.get("deck_id") or "deck")
        for slide in graph.get("slides") if isinstance(graph.get("slides"), list) else []:
            attachments = slide.get("attachments") if isinstance(slide.get("attachments"), list) else []
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                blob = attachment.pop("_blob", None)
                ext = str(attachment.pop("_ext", "png") or "png").strip().lower() or "png"
                slide_no = int(attachment.pop("_slide_no", 0) or 0)
                attachment.pop("_deck_id", None)
                if isinstance(blob, (bytes, bytearray)):
                    asset_dir = graph_assets_dir / deck_id / f"slide_{slide_no:03d}"
                    asset_dir.mkdir(parents=True, exist_ok=True)
                    asset_path = asset_dir / f"{attachment.get('attachment_id')}.{ext}"
                    asset_path.write_bytes(bytes(blob))
                    attachment["asset_path"] = relative_project_path(asset_path, project_root=project_root)
        (graphs_dir / f"{deck_id}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["build_slide_graph", "graph_slide_text", "iter_graph_slides", "write_slide_graphs"]
