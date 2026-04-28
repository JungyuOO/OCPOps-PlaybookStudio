from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


STAGE_OFFICIAL_BOOKS = {
    "architecture": [
        "architecture",
        "overview",
        "nodes",
        "networking_overview",
        "ingress_and_load_balancing",
        "storage",
    ],
    "unit_test": [
        "cli_tools",
        "web_console",
        "nodes",
        "storage",
        "monitoring",
        "etcd",
        "backup_and_restore",
    ],
    "integration_test": [
        "operators",
        "ingress_and_load_balancing",
        "networking_overview",
        "validation_and_troubleshooting",
    ],
    "perf_test": [
        "monitoring",
        "observability_overview",
        "nodes",
        "logging",
        "validation_and_troubleshooting",
    ],
    "completion": [
        "overview",
        "architecture",
        "support",
        "postinstallation_configuration",
        "validation_and_troubleshooting",
    ],
}


def _official_corpus_rows(root_dir: Path) -> list[dict[str, Any]]:
    path = root_dir / "data" / "gold_corpus_ko" / "chunks.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(payload)
    return rows


def _pick_book_entry(rows: list[dict[str, Any]], book_slug: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if str(row.get("book_slug") or "") == book_slug]
    if not candidates:
        return None
    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        section = str(row.get("section") or row.get("chapter") or "")
        title = str(row.get("book_title") or "")
        section_path = row.get("section_path") if isinstance(row.get("section_path"), list) else []
        path_label = " ".join(str(item) for item in section_path)
        if "개요" in section or "overview" in section.lower() or "개요" in path_label:
            overview_rank = 0
        elif title and title in section:
            overview_rank = 1
        else:
            overview_rank = 2
        type_rank = 0 if str(row.get("chunk_type") or "") in {"concept", "reference"} else 1
        return (
            overview_rank,
            len(section_path) or 99,
            type_rank,
            int(row.get("ordinal") or 0),
            section,
        )
    candidates.sort(
        key=sort_key
    )
    return candidates[0]


def build_stage_official_refs(root_dir: Path, stage_id: str, *, limit: int = 4) -> list[dict[str, Any]]:
    rows = _official_corpus_rows(root_dir)
    refs: list[dict[str, Any]] = []
    for book_slug in STAGE_OFFICIAL_BOOKS.get(stage_id, [])[:limit]:
        entry = _pick_book_entry(rows, book_slug)
        if not entry:
            continue
        text = re.sub(r"\s+", " ", str(entry.get("text") or "")).strip()
        refs.append(
            {
                "book_slug": str(entry.get("book_slug") or ""),
                "section_id": str(entry.get("section_id") or entry.get("anchor_id") or ""),
                "title": str(entry.get("book_title") or entry.get("book_slug") or ""),
                "section_title": str(entry.get("section") or entry.get("chapter") or ""),
                "snippet": text[:260],
                "viewer_path": str(entry.get("viewer_path") or ""),
                "score": 0.66,
                "trusted": True,
                "match_reason": f"stage-level official route for {stage_id}; broad reference, not a chunk-specific assertion",
            }
        )
    return refs


def attach_stage_official_routes(manifest: dict[str, Any], *, root_dir: Path) -> dict[str, Any]:
    stages = manifest.get("stages") if isinstance(manifest.get("stages"), list) else []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        stage["official_route_refs"] = build_stage_official_refs(root_dir, stage_id)
    tour = manifest.get("tour") if isinstance(manifest.get("tour"), dict) else {}
    tour_stages = tour.get("stages") if isinstance(tour.get("stages"), list) else []
    by_stage = {str(stage.get("stage_id") or ""): stage for stage in stages if isinstance(stage, dict)}
    for tour_stage in tour_stages:
        if not isinstance(tour_stage, dict):
            continue
        stage = by_stage.get(str(tour_stage.get("stage_id") or ""))
        if stage:
            tour_stage["official_route_refs"] = stage.get("official_route_refs") or []
    return manifest


__all__ = ["attach_stage_official_routes", "build_stage_official_refs"]
