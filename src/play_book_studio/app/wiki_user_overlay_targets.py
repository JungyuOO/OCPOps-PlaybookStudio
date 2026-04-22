from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from play_book_studio.config.settings import load_settings

from .wiki_relations import load_wiki_relation_assets

VALID_TARGET_KINDS = {"book", "entity_hub", "section", "figure"}
BOOK_PREFIXES = (
    "/playbooks/wiki-runtime/active/",
    "/docs/ocp/",
)


def _parse_book_slug_from_viewer_path(viewer_path: str) -> str:
    normalized = str(viewer_path or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/docs/ocp/"):
        parts = [part for part in normalized.split("/") if part]
        if len(parts) >= 5 and parts[-1].startswith("index.html"):
            return parts[-2]
        return ""
    for prefix in BOOK_PREFIXES[:3]:
        if normalized.startswith(prefix):
            remainder = normalized[len(prefix) :]
            slug = remainder.split("/", 1)[0].strip()
            return slug
    return ""


def _parse_anchor_from_viewer_path(viewer_path: str) -> str:
    normalized = str(viewer_path or "").strip()
    if "#" not in normalized:
        return ""
    return normalized.split("#", 1)[1].strip()


def _canonical_book_ref(slug: str) -> str:
    return f"book:{slug}"


def _canonical_entity_ref(entity_slug: str) -> str:
    return f"entity:{entity_slug}"


def _canonical_section_ref(book_slug: str, anchor: str) -> str:
    return f"section:{book_slug}#{anchor}"


def _canonical_figure_ref(book_slug: str, asset_name: str) -> str:
    return f"figure:{book_slug}:{asset_name}"


def _active_runtime_entries(root_dir: Path) -> list[dict[str, Any]]:
    path = root_dir / "data" / "wiki_runtime_books" / "active_manifest.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = payload.get("entries")
    return [dict(item) for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []


def _active_runtime_entry_by_slug(root_dir: Path, slug: str) -> dict[str, Any]:
    for entry in _active_runtime_entries(root_dir):
        if str(entry.get("slug") or "").strip() == slug:
            return entry
    return {}


def _entity_hub_by_slug(root_dir: Path, slug: str) -> dict[str, Any]:
    del root_dir
    payload = load_wiki_relation_assets().get("entity_hubs")
    if not isinstance(payload, dict):
        return {}
    item = payload.get(str(slug or "").strip())
    return dict(item) if isinstance(item, dict) else {}


def _figure_asset_by_ref(root_dir: Path, book_slug: str, asset_name: str) -> dict[str, Any]:
    del root_dir
    payload = load_wiki_relation_assets().get("figure_assets")
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    records = entries.get(book_slug)
    if not isinstance(records, list):
        return {}
    for item in records:
        if not isinstance(item, dict):
            continue
        resolved_name = (
            str(item.get("asset_name") or "").strip()
            or Path(urlparse(str(item.get("asset_url") or "")).path).name.strip()
            or Path(urlparse(str(item.get("viewer_path") or "")).path).parent.name.strip()
        )
        if resolved_name == asset_name:
            return dict(item)
    return {}


def _candidate_relation_by_slug(slug: str) -> dict[str, Any]:
    payload = load_wiki_relation_assets().get("candidate_relations")
    if not isinstance(payload, dict):
        return {}
    item = payload.get(str(slug or "").strip())
    return dict(item) if isinstance(item, dict) else {}


def _section_record_by_ref(root_dir: Path, book_slug: str, anchor: str) -> dict[str, Any]:
    del root_dir
    payload = load_wiki_relation_assets().get("section_relation_index")
    if not isinstance(payload, dict):
        return {}
    by_book = payload.get("by_book")
    if not isinstance(by_book, dict):
        return {}
    items = by_book.get(book_slug)
    if not isinstance(items, list):
        return {}
    suffix = f"#{anchor}".lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or "").strip().lower()
        if href.endswith(suffix):
            return dict(item)
    return {}


def _book_title_lookup(root_dir: Path) -> dict[str, str]:
    return {
        str(entry.get("slug") or "").strip(): str(entry.get("title") or "").strip()
        for entry in _active_runtime_entries(root_dir)
        if str(entry.get("slug") or "").strip()
    }


def _normalize_overlay_target(payload: dict[str, Any]) -> tuple[str, str, str]:
    target_kind = str(payload.get("target_kind") or "").strip()
    if target_kind not in VALID_TARGET_KINDS:
        raise ValueError("target_kind는 book, entity_hub, section, figure 중 하나여야 합니다.")
    target_ref = str(payload.get("target_ref") or "").strip()
    viewer_path = str(payload.get("viewer_path") or "").strip()
    book_slug = str(payload.get("book_slug") or "").strip()
    if target_kind == "book":
        if not book_slug:
            book_slug = _parse_book_slug_from_viewer_path(viewer_path)
        if not book_slug and target_ref.startswith("book:"):
            book_slug = target_ref.split(":", 1)[1].strip()
        if not book_slug:
            raise ValueError("book target은 book_slug 또는 viewer_path가 필요합니다.")
        return target_kind, _canonical_book_ref(book_slug), book_slug
    if target_kind == "entity_hub":
        entity_slug = str(payload.get("entity_slug") or "").strip()
        if not entity_slug and target_ref.startswith("entity:"):
            entity_slug = target_ref.split(":", 1)[1].strip()
        if not entity_slug and viewer_path.startswith("/wiki/entities/"):
            parts = [part for part in viewer_path.split("/") if part]
            if len(parts) >= 3:
                entity_slug = parts[2]
        if not entity_slug:
            raise ValueError("entity_hub target은 entity_slug 또는 viewer_path가 필요합니다.")
        return target_kind, _canonical_entity_ref(entity_slug), book_slug
    if target_kind == "section":
        anchor = str(payload.get("anchor") or "").strip() or _parse_anchor_from_viewer_path(viewer_path)
        if not book_slug:
            book_slug = _parse_book_slug_from_viewer_path(viewer_path)
        if not target_ref and book_slug and anchor:
            target_ref = _canonical_section_ref(book_slug, anchor)
        if target_ref.startswith("section:"):
            remainder = target_ref.split(":", 1)[1]
            if "#" in remainder:
                book_slug = book_slug or remainder.split("#", 1)[0].strip()
                anchor = anchor or remainder.split("#", 1)[1].strip()
        if not book_slug or not anchor:
            raise ValueError("section target은 book_slug와 anchor 또는 viewer_path가 필요합니다.")
        return target_kind, _canonical_section_ref(book_slug, anchor), book_slug
    asset_name = str(payload.get("asset_name") or "").strip()
    if target_ref.startswith("figure:"):
        remainder = target_ref.split(":", 1)[1]
        if ":" in remainder:
            slug_part, asset_part = remainder.split(":", 1)
            book_slug = book_slug or slug_part.strip()
            asset_name = asset_name or asset_part.strip()
    if viewer_path.startswith("/wiki/figures/"):
        parts = [part for part in viewer_path.split("/") if part]
        if len(parts) >= 4:
            book_slug = book_slug or parts[2]
            asset_name = asset_name or parts[3]
    if not book_slug or not asset_name:
        raise ValueError("figure target은 book_slug와 asset_name 또는 viewer_path가 필요합니다.")
    return target_kind, _canonical_figure_ref(book_slug, asset_name), book_slug


def resolve_overlay_target(
    root_dir: Path,
    target_kind: str,
    target_ref: str,
    *,
    viewer_path: str | None = None,
) -> dict[str, Any]:
    normalized_kind = str(target_kind or "").strip()
    normalized_ref = str(target_ref or "").strip()
    normalized_viewer_path = str(viewer_path or "").strip()
    if normalized_kind == "book" and normalized_ref.startswith("book:"):
        slug = normalized_ref.split(":", 1)[1].strip()
        entry = _active_runtime_entry_by_slug(root_dir, slug)
        return {
            "target_kind": normalized_kind,
            "target_ref": normalized_ref,
            "book_slug": slug,
            "viewer_path": normalized_viewer_path or str(entry.get("viewer_path") or f"/playbooks/wiki-runtime/active/{slug}/index.html"),
            "title": str(entry.get("title") or slug.replace("_", " ").title()),
            "summary": str(entry.get("summary") or ""),
        }
    if normalized_kind == "entity_hub" and normalized_ref.startswith("entity:"):
        entity_slug = normalized_ref.split(":", 1)[1].strip()
        item = _entity_hub_by_slug(root_dir, entity_slug)
        return {
            "target_kind": normalized_kind,
            "target_ref": normalized_ref,
            "book_slug": "",
            "viewer_path": f"/wiki/entities/{entity_slug}/index.html",
            "title": str(item.get("title") or entity_slug),
            "summary": str(item.get("summary") or ""),
        }
    if normalized_kind == "section" and normalized_ref.startswith("section:"):
        remainder = normalized_ref.split(":", 1)[1]
        book_slug, anchor = remainder.split("#", 1)
        record = _section_record_by_ref(root_dir, book_slug.strip(), anchor.strip())
        return {
            "target_kind": normalized_kind,
            "target_ref": normalized_ref,
            "book_slug": book_slug.strip(),
            "viewer_path": normalized_viewer_path or str(record.get("href") or f"/playbooks/wiki-runtime/active/{book_slug.strip()}/index.html#{anchor.strip()}"),
            "title": str(record.get("label") or anchor.strip()),
            "summary": str(record.get("summary") or ""),
        }
    if normalized_kind == "figure" and normalized_ref.startswith("figure:"):
        remainder = normalized_ref.split(":", 1)[1]
        book_slug, asset_name = remainder.split(":", 1)
        asset = _figure_asset_by_ref(root_dir, book_slug.strip(), asset_name.strip())
        return {
            "target_kind": normalized_kind,
            "target_ref": normalized_ref,
            "book_slug": book_slug.strip(),
            "viewer_path": normalized_viewer_path or str(asset.get("viewer_path") or f"/wiki/figures/{book_slug.strip()}/{asset_name.strip()}/index.html"),
            "title": str(asset.get("caption") or asset.get("alt") or asset_name.strip()),
            "summary": str(asset.get("source_path") or ""),
        }
    return {
        "target_kind": normalized_kind,
        "target_ref": normalized_ref,
        "book_slug": "",
        "viewer_path": normalized_viewer_path,
        "title": normalized_ref,
        "summary": "",
    }


def _resolve_overlay_target_for_item(root_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    return resolve_overlay_target(
        root_dir,
        str(item.get("target_kind") or ""),
        str(item.get("target_ref") or ""),
        viewer_path=str(item.get("viewer_path") or ""),
    )


def _candidate_links_from_book(root_dir: Path, book_slug: str) -> list[dict[str, Any]]:
    relation = _candidate_relation_by_slug(book_slug)
    links: list[dict[str, Any]] = []
    for item in relation.get("next_reading_path") or []:
        if isinstance(item, dict):
            links.append({"label": str(item.get("label") or "").strip(), "href": str(item.get("href") or "").strip(), "kind": "book", "summary": str(item.get("summary") or "").strip()})
    for item in relation.get("entities") or []:
        if isinstance(item, dict):
            links.append({"label": str(item.get("label") or "").strip(), "href": str(item.get("href") or "").strip(), "kind": "entity", "summary": str(item.get("summary") or relation.get("parent_topic", {}).get("summary") or "").strip()})
    if not links:
        entry = _active_runtime_entry_by_slug(root_dir, book_slug)
        viewer_path = str(entry.get("viewer_path") or f"/playbooks/wiki-runtime/active/{book_slug}/index.html")
        links.append({"label": str(entry.get("title") or book_slug).strip(), "href": viewer_path, "kind": "book", "summary": ""})
    return links


def _candidate_links_from_entity(root_dir: Path, entity_slug: str) -> list[dict[str, Any]]:
    hub = _entity_hub_by_slug(root_dir, entity_slug)
    links: list[dict[str, Any]] = []
    for group in ("next_reading_path", "related_books"):
        for item in hub.get(group) or []:
            if isinstance(item, dict):
                links.append({"label": str(item.get("label") or "").strip(), "href": str(item.get("href") or "").strip(), "kind": "book", "summary": str(item.get("summary") or "").strip()})
    return links


def _candidate_links_from_figure(root_dir: Path, book_slug: str, asset_name: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    figure_sections = load_wiki_relation_assets().get("figure_section_index")
    by_book = figure_sections.get("by_book") if isinstance(figure_sections, dict) else {}
    if isinstance(by_book, dict):
        for item in by_book.get(book_slug) or []:
            if not isinstance(item, dict):
                continue
            viewer_path = str(item.get("viewer_path") or "").strip()
            if f"/{asset_name}/index.html" not in viewer_path:
                continue
            links.append({"label": str(item.get("section_label") or "관련 섹션").strip(), "href": str(item.get("section_href") or "").strip(), "kind": "section", "summary": str(item.get("section_summary") or "").strip()})
    links.extend(_candidate_links_from_book(root_dir, book_slug))
    return links


def _candidate_links_from_section(root_dir: Path, book_slug: str, anchor: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    section = _section_record_by_ref(root_dir, book_slug, anchor)
    if section:
        links.append({"label": str(section.get("label") or "현재 절차").strip(), "href": str(section.get("href") or "").strip(), "kind": "section", "summary": str(section.get("summary") or "").strip()})
    links.extend(_candidate_links_from_book(root_dir, book_slug))
    return links


__all__ = [
    "_book_title_lookup",
    "_candidate_links_from_book",
    "_candidate_links_from_entity",
    "_candidate_links_from_figure",
    "_candidate_links_from_section",
    "_normalize_overlay_target",
    "_resolve_overlay_target_for_item",
    "resolve_overlay_target",
]
