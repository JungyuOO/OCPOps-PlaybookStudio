from __future__ import annotations

import re
from typing import Any


STEP_RE = re.compile(r"^\s*(\d+)[.)]\s*(.+)")


def _visible_shapes(slide: dict[str, Any]) -> list[dict[str, Any]]:
    shapes = slide.get("shapes") if isinstance(slide.get("shapes"), list) else []
    rows: list[dict[str, Any]] = []
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        width = int(shape.get("width") or 0)
        height = int(shape.get("height") or 0)
        left = int(shape.get("left") or 0)
        top = int(shape.get("top") or 0)
        if width <= 0 or height <= 0:
            continue
        if left < -100 or top < -100:
            continue
        rows.append(shape)
    return rows


def _zone_role(shape: dict[str, Any], slide: dict[str, Any]) -> str:
    text = str(shape.get("text") or "").strip()
    shape_type = str(shape.get("shape_type") or "")
    top = int(shape.get("top") or 0)
    width = int(shape.get("width") or 0)
    slide_width = max((int(item.get("left", 0)) + int(item.get("width", 0)) for item in _visible_shapes(slide)), default=1)
    if shape_type == "picture":
        return "image"
    if shape.get("has_table"):
        return "table"
    if text and top < 120 and width > slide_width * 0.35:
        return "title"
    if STEP_RE.match(text):
        return "step"
    if len(text) <= 60:
        return "label"
    return "body"


def derive_slide_semantics(slide: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shapes = _visible_shapes(slide)
    zones: list[dict[str, Any]] = []
    for shape in shapes:
        role = _zone_role(shape, slide)
        text = str(shape.get("text") or "").strip()
        zone_id = f"slide-{int(slide.get('slide_no') or 0):03d}-shape-{int(shape.get('shape_index') or 0):03d}"
        zones.append(
            {
                "zone_id": zone_id,
                "zone_role": role,
                "shape_index": int(shape.get("shape_index") or 0),
                "shape_type": str(shape.get("shape_type") or ""),
                "text": text,
                "bbox": {
                    "left": int(shape.get("left") or 0),
                    "top": int(shape.get("top") or 0),
                    "width": int(shape.get("width") or 0),
                    "height": int(shape.get("height") or 0),
                },
            }
        )
    relations: list[dict[str, Any]] = []
    for left in zones:
        for right in zones:
            if left["zone_id"] == right["zone_id"]:
                continue
            left_box = left["bbox"]
            right_box = right["bbox"]
            same_row = abs(left_box["top"] - right_box["top"]) < 80
            same_col = abs(left_box["left"] - right_box["left"]) < 120
            if same_row:
                relations.append({"type": "same_row", "from_zone": left["zone_id"], "to_zone": right["zone_id"]})
            if same_col:
                relations.append({"type": "same_col", "from_zone": left["zone_id"], "to_zone": right["zone_id"]})
            if left["zone_role"] == "image" and right["zone_role"] in {"body", "label"} and right_box["top"] > left_box["top"]:
                relations.append({"type": "caption_for", "from_zone": right["zone_id"], "to_zone": left["zone_id"]})
    step_zones = [zone for zone in zones if zone["zone_role"] == "step" and zone["text"]]
    step_zones.sort(key=lambda item: int(STEP_RE.match(item["text"]).group(1)) if STEP_RE.match(item["text"]) else 9999)
    for current, nxt in zip(step_zones, step_zones[1:], strict=False):
        if current is nxt:
            continue
        relations.append({"type": "step_next", "from_zone": current["zone_id"], "to_zone": nxt["zone_id"]})
    return zones, relations


__all__ = ["derive_slide_semantics"]
