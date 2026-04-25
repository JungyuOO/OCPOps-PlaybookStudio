from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from play_book_studio.config.settings import Settings


OFFICIAL_FIGURE_RELATIONS_SCHEMA_VERSION = "official_figure_relations_v2"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _asset_name_from_block(block: dict[str, Any], ordinal: int) -> str:
    for key in ("asset_ref", "source_asset_ref"):
        value = Path(str(block.get(key) or "").strip()).name.strip()
        if value:
            return value
    for key in ("asset_url", "src"):
        value = str(block.get(key) or "").strip()
        if not value:
            continue
        name = Path(urlparse(value).path).name.strip()
        if name:
            return name
    return f"figure-{ordinal}.png"


def _figure_asset_url(block: dict[str, Any]) -> str:
    return str(block.get("asset_url") or block.get("src") or "").strip()


def _figure_viewer_path(book_slug: str, asset_name: str, block: dict[str, Any]) -> str:
    explicit = str(block.get("viewer_path") or "").strip()
    if explicit:
        return explicit
    if not book_slug or not asset_name:
        return ""
    return f"/wiki/figures/{book_slug}/{asset_name}/index.html"


def _section_anchor(section: dict[str, Any]) -> str:
    return str(section.get("anchor") or section.get("anchor_id") or "").strip()


def _section_href(book_slug: str, anchor: str) -> str:
    base = f"/playbooks/wiki-runtime/active/{book_slug}/index.html"
    return f"{base}#{anchor}" if anchor else base


def build_official_figure_relation_sidecars(playbook_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    generated_at = _utc_now()
    entries: dict[str, list[dict[str, Any]]] = {}
    by_slug: dict[str, list[dict[str, Any]]] = {}
    figure_count = 0

    for row in sorted(playbook_rows, key=lambda item: str(item.get("book_slug") or "")):
        book_slug = str(row.get("book_slug") or "").strip()
        if not book_slug:
            continue
        for section in row.get("sections") or []:
            if not isinstance(section, dict):
                continue
            anchor = _section_anchor(section)
            section_path_parts = [
                _clean_text(part)
                for part in (section.get("section_path") or section.get("path") or [])
                if _clean_text(part)
            ]
            section_path = " > ".join(section_path_parts)
            section_heading = _clean_text(section.get("heading") or anchor)
            for block in section.get("blocks") or []:
                if not isinstance(block, dict) or str(block.get("kind") or "").strip() != "figure":
                    continue
                figure_count += 1
                asset_name = _asset_name_from_block(block, figure_count)
                asset_url = _figure_asset_url(block)
                viewer_path = _figure_viewer_path(book_slug, asset_name, block)
                caption = _clean_text(block.get("caption") or block.get("alt") or asset_name or "Figure")
                section_hint = section_heading or section_path
                entries.setdefault(book_slug, []).append(
                    {
                        "caption": caption,
                        "alt": _clean_text(block.get("alt") or caption),
                        "asset_kind": _clean_text(block.get("asset_kind") or "figure") or "figure",
                        "diagram_type": _clean_text(block.get("diagram_type")),
                        "asset_url": asset_url,
                        "viewer_path": viewer_path,
                        "source_file": _clean_text(block.get("source_file")),
                        "source_asset_ref": asset_name,
                        "section_hint": section_hint,
                        "section_anchor": anchor,
                        "source": "playbook_document_figure_block",
                    }
                )
                by_slug.setdefault(book_slug, []).append(
                    {
                        "asset_name": asset_name,
                        "viewer_path": viewer_path,
                        "caption": caption,
                        "section_hint": section_hint,
                        "section_heading": section_heading,
                        "section_anchor": anchor,
                        "section_path": section_path,
                        "section_href": _section_href(book_slug, anchor),
                        "source": "playbook_document_figure_block",
                    }
                )

    figure_assets = {
        "schema_version": OFFICIAL_FIGURE_RELATIONS_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "producer": "playbook_documents.figure_blocks",
        "book_count": len(entries),
        "figure_count": figure_count,
        "entries": entries,
    }
    figure_section_index = {
        "schema_version": OFFICIAL_FIGURE_RELATIONS_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "producer": "playbook_documents.figure_blocks",
        "book_count": len(by_slug),
        "figure_count": figure_count,
        "matched_section_count": sum(len(items) for items in by_slug.values()),
        "by_slug": by_slug,
    }
    return {
        "figure_assets": figure_assets,
        "figure_section_index": figure_section_index,
    }


def write_official_figure_relation_sidecars(
    settings: Settings,
    playbook_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    payloads = build_official_figure_relation_sidecars(playbook_rows)
    relation_dir = settings.root_dir / "data" / "wiki_relations"
    relation_dir.mkdir(parents=True, exist_ok=True)
    (relation_dir / "figure_assets.json").write_text(
        json.dumps(payloads["figure_assets"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (relation_dir / "figure_section_index.json").write_text(
        json.dumps(payloads["figure_section_index"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "figure_count": int(payloads["figure_assets"].get("figure_count") or 0),
        "matched_section_count": int(payloads["figure_section_index"].get("matched_section_count") or 0),
        "figure_assets_path": str(relation_dir / "figure_assets.json"),
        "figure_section_index_path": str(relation_dir / "figure_section_index.json"),
    }


__all__ = [
    "OFFICIAL_FIGURE_RELATIONS_SCHEMA_VERSION",
    "build_official_figure_relation_sidecars",
    "write_official_figure_relation_sidecars",
]
