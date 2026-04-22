"""wiki relation and runtime helper primitives for source_books."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from play_book_studio.config.settings import load_settings
from play_book_studio.runtime_catalog_registry import official_runtime_book_entry

from .runtime_truth import official_runtime_truth_payload
from .wiki_relations import load_wiki_relation_assets


GOLD_CANDIDATE_BOOK_PREFIX = "/playbooks/gold-candidates/wave1"
ACTIVE_WIKI_RUNTIME_BOOK_PREFIX = "/playbooks/wiki-runtime/active"
LEGACY_WIKI_RUNTIME_BOOK_PREFIX = "/playbooks/wiki-runtime/wave1"
RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE = re.compile(r"^/playbooks/wiki-runtime/([^/]+)/([^/]+)/index\.html$")


def _wiki_relation_assets() -> dict[str, dict[str, Any]]:
    return load_wiki_relation_assets()


def _entity_hubs() -> dict[str, dict[str, Any]]:
    payload = _wiki_relation_assets().get("entity_hubs")
    return payload if isinstance(payload, dict) else {}


def _chat_navigation_aliases() -> dict[str, list[dict[str, str]]]:
    payload = _wiki_relation_assets().get("chat_navigation_aliases")
    return payload if isinstance(payload, dict) else {}


def _chat_link_truth_payload(root_dir: Path, href: str, kind: str) -> dict[str, str]:
    normalized_href = str(href or "").strip()
    normalized_kind = str(kind or "").strip()
    if normalized_kind == "entity":
        return {}
    settings = load_settings(root_dir)
    if normalized_href.startswith("/playbooks/customer-packs/"):
        return {
            "source_lane": "customer_source_first_pack",
            "boundary_truth": "private_customer_pack_runtime",
            "runtime_truth_label": "Customer Source-First Pack",
            "boundary_badge": "Private Runtime",
        }
    if normalized_href.startswith("/docs/ocp/"):
        parsed = urlparse(normalized_href)
        parts = [part for part in parsed.path.split("/") if part]
        slug = parts[-2] if len(parts) >= 5 and parts[-1] == "index.html" else ""
        registry_entry = official_runtime_book_entry(root_dir, slug) if slug else {}
        return official_runtime_truth_payload(settings=settings, manifest_entry=registry_entry)
    if normalized_href.startswith(f"{ACTIVE_WIKI_RUNTIME_BOOK_PREFIX}/"):
        parsed = urlparse(normalized_href)
        parts = [part for part in parsed.path.split("/") if part]
        slug = ""
        if len(parts) >= 4 and parts[-1] == "index.html":
            slug = parts[-2]
        elif len(parts) >= 3:
            slug = parts[-1]
        registry_entry = official_runtime_book_entry(root_dir, slug) if slug else {}
        return official_runtime_truth_payload(settings=settings, manifest_entry=registry_entry)
    return {}


def _contains_hangul(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in str(text or ""))


def _link_book_slug(href: str) -> str:
    match = RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE.match(str(href or "").strip())
    if match:
        return str(match.group(2) or "").strip()
    return ""


def _prefer_korean_book_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    korean_books = [
        link for link in links
        if str(link.get("kind") or "").strip() == "book" and _contains_hangul(str(link.get("label") or ""))
    ]
    if korean_books:
        return korean_books
    return links


def _is_final_runtime_href(href: str) -> bool:
    return str(href or "").strip().startswith(f"{ACTIVE_WIKI_RUNTIME_BOOK_PREFIX}/")


def _candidate_relations() -> dict[str, dict[str, Any]]:
    payload = _wiki_relation_assets().get("candidate_relations")
    return payload if isinstance(payload, dict) else {}


def _figure_assets() -> dict[str, list[dict[str, Any]]]:
    payload = _wiki_relation_assets().get("figure_assets")
    return payload.get("entries", {}) if isinstance(payload, dict) and isinstance(payload.get("entries"), dict) else {}


def _figure_entity_index() -> dict[str, Any]:
    payload = _wiki_relation_assets().get("figure_entity_index")
    return payload if isinstance(payload, dict) else {}


def _figure_section_index() -> dict[str, Any]:
    payload = _wiki_relation_assets().get("figure_section_index")
    return payload if isinstance(payload, dict) else {}


def _section_relation_index() -> dict[str, Any]:
    payload = _wiki_relation_assets().get("section_relation_index")
    return payload if isinstance(payload, dict) else {}


def _figure_asset_filename(asset: dict[str, Any]) -> str:
    asset_url = str(asset.get("asset_url") or "").strip()
    return Path(urlparse(asset_url).path).name.strip()


def _figure_viewer_href(slug: str, asset: dict[str, Any]) -> str:
    viewer_path = str(asset.get("viewer_path") or "").strip()
    if viewer_path:
        return viewer_path
    asset_name = _figure_asset_filename(asset)
    if not slug or not asset_name:
        return str(asset.get("asset_url") or "").strip()
    return f"/wiki/figures/{slug}/{asset_name}/index.html"


def _figure_asset_by_name(slug: str, asset_name: str) -> dict[str, Any] | None:
    normalized_slug = str(slug or "").strip()
    normalized_asset_name = str(asset_name or "").strip()
    if not normalized_slug or not normalized_asset_name:
        return None
    for item in _figure_assets().get(normalized_slug, []):
        if not isinstance(item, dict):
            continue
        if _figure_asset_filename(item) == normalized_asset_name:
            return item
    return None


def _figure_section_match(slug: str, asset_name: str) -> dict[str, Any] | None:
    payload = _figure_section_index()
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    records = by_slug.get(str(slug or "").strip())
    if not isinstance(records, list):
        return None
    normalized_asset_name = str(asset_name or "").strip()
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("asset_name") or "").strip() == normalized_asset_name:
            return item
    return None


def _book_related_sections(slug: str) -> list[dict[str, Any]]:
    payload = _section_relation_index()
    by_book = payload.get("by_book") if isinstance(payload.get("by_book"), dict) else {}
    items = by_book.get(str(slug or "").strip())
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _section_linked_figures(section_href: str) -> list[dict[str, Any]]:
    normalized_href = str(section_href or "").strip()
    if not normalized_href:
        return []
    payload = _figure_section_index()
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    results: list[dict[str, Any]] = []
    for source_slug, records in by_slug.items():
        if not isinstance(records, list):
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            if str(item.get("section_href") or "").strip() != normalized_href:
                continue
            asset_name = str(item.get("asset_name") or "").strip()
            asset = _figure_asset_by_name(str(source_slug or "").strip(), asset_name) or {}
            viewer_path = str(item.get("viewer_path") or "").strip()
            if not viewer_path:
                viewer_path = _figure_viewer_href(str(source_slug or "").strip(), asset)
            results.append(
                {
                    "book_slug": str(source_slug or "").strip(),
                    "viewer_path": viewer_path,
                    "asset_url": str(asset.get("asset_url") or "").strip(),
                    "caption": str(item.get("caption") or asset.get("caption") or asset.get("alt") or "Figure").strip(),
                    "section_hint": str(item.get("section_path") or item.get("section_hint") or asset.get("section_hint") or "").strip(),
                    "section_href": normalized_href,
                    "section_anchor": str(item.get("section_anchor") or "").strip(),
                    "source": "section_relation_figure",
                }
            )
    return results


def _book_related_figures(slug: str, *, limit: int = 6) -> list[dict[str, Any]]:
    normalized_slug = str(slug or "").strip()
    if not normalized_slug:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(item: dict[str, Any]) -> None:
        viewer_path = str(item.get("viewer_path") or "").strip()
        asset_url = str(item.get("asset_url") or "").strip()
        key = viewer_path or asset_url
        if not key or key in seen:
            return
        seen.add(key)
        results.append(item)

    for asset in _figure_assets().get(normalized_slug, []):
        if not isinstance(asset, dict):
            continue
        _append(
            {
                "book_slug": normalized_slug,
                "viewer_path": _figure_viewer_href(normalized_slug, asset),
                "asset_url": str(asset.get("asset_url") or "").strip(),
                "caption": str(asset.get("caption") or asset.get("alt") or "Figure").strip(),
                "section_hint": str(asset.get("section_hint") or "").strip(),
                "source": "book_figure",
            }
        )
        if len(results) >= limit:
            return results

    for section in _book_related_sections(normalized_slug):
        href = str(section.get("href") or "").strip()
        if not href:
            continue
        for figure in _section_linked_figures(href):
            _append(figure)
            if len(results) >= limit:
                return results
    return results


def _entity_related_sections(entity_slug: str) -> list[dict[str, Any]]:
    payload = _section_relation_index()
    by_entity = payload.get("by_entity") if isinstance(payload.get("by_entity"), dict) else {}
    items = by_entity.get(str(entity_slug or "").strip())
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _wiki_relation_items(relation: dict[str, Any], key: str) -> list[dict[str, str]]:
    return [item for item in relation.get(key, []) if isinstance(item, dict)]


def _runtime_markdown_path_from_manifest(root_dir: Path, manifest_filename: str, slug: str) -> Path | None:
    manifest_path = root_dir / "data" / "wiki_runtime_books" / manifest_filename
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return _runtime_markdown_path_from_entries(root_dir, entries, slug)


def _runtime_markdown_path_candidates(root_dir: Path, recorded_path: str) -> tuple[Path, ...]:
    normalized = str(recorded_path or "").strip()
    if not normalized:
        return ()
    candidates: list[Path] = [Path(normalized)]
    normalized_slash = normalized.replace("\\", "/")
    marker = "data/wiki_runtime_books/"
    relative_tail = ""
    if marker in normalized_slash:
        relative_tail = normalized_slash.split(marker, 1)[1].strip("/")
    elif normalized_slash.startswith(marker):
        relative_tail = normalized_slash[len(marker):].strip("/")
    if relative_tail:
        candidates.append(root_dir / "data" / "wiki_runtime_books" / Path(relative_tail))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique)


def _runtime_markdown_path_from_entries(root_dir: Path, entries: list[Any], slug: str) -> Path | None:
    normalized_slug = str(slug or "").strip()
    if not normalized_slug:
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_slug = str(entry.get("slug") or "").strip()
        if entry_slug != normalized_slug:
            continue
        for runtime_path in _runtime_markdown_path_candidates(root_dir, str(entry.get("runtime_path") or "")):
            if runtime_path.exists() and runtime_path.is_file():
                return runtime_path
    return None


def _active_runtime_markdown_path(root_dir: Path, slug: str) -> Path | None:
    path = _runtime_markdown_path_from_manifest(root_dir, "active_manifest.json", slug)
    if path is not None:
        return path
    return _runtime_markdown_path_from_manifest(root_dir, "full_rebuild_manifest.json", slug)


def _preferred_book_href(root_dir: Path, slug: str) -> str:
    normalized = str(slug or "").strip()
    if not normalized:
        return ""
    registry_entry = official_runtime_book_entry(root_dir, normalized)
    if registry_entry:
        viewer_path = str(registry_entry.get("viewer_path") or "").strip()
        if viewer_path:
            return viewer_path
    settings = load_settings(root_dir)
    return f"/docs/ocp/{settings.ocp_version}/{settings.docs_language}/{normalized}/index.html"


def _rewrite_book_href(root_dir: Path, href: str) -> str:
    normalized = str(href or "").strip()
    if normalized.startswith("/docs/ocp/"):
        parsed = urlparse(normalized)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 5 and parts[-1] == "index.html":
            slug = parts[-2]
            anchor = parsed.fragment
            rewritten = _preferred_book_href(root_dir, slug)
            if anchor:
                rewritten = f"{rewritten}#{anchor}"
            return rewritten
    if normalized.startswith(f"{GOLD_CANDIDATE_BOOK_PREFIX}/") or normalized.startswith(f"{LEGACY_WIKI_RUNTIME_BOOK_PREFIX}/"):
        parts = [part for part in normalized.split("/") if part]
        if len(parts) >= 4:
            slug = parts[-2]
            return _preferred_book_href(root_dir, slug)
    return normalized


def _relation_href_matches_slug(href: str, slug: str) -> bool:
    normalized = str(href or "").strip()
    docs_pattern = re.compile(rf"^/docs/ocp/[^/]+/[^/]+/{re.escape(slug)}/index\.html$")
    return normalized in {
        f"{GOLD_CANDIDATE_BOOK_PREFIX}/{slug}/index.html",
        f"{ACTIVE_WIKI_RUNTIME_BOOK_PREFIX}/{slug}/index.html",
        f"{LEGACY_WIKI_RUNTIME_BOOK_PREFIX}/{slug}/index.html",
    } or bool(docs_pattern.match(normalized))


def _build_backlinks(root_dir: Path, slug: str) -> list[dict[str, str]]:
    backlinks: list[dict[str, str]] = []
    seen: set[str] = set()
    for source_slug, relation in _candidate_relations().items():
        if source_slug == slug:
            continue
        items = (
            _wiki_relation_items(relation, "related_docs")
            + _wiki_relation_items(relation, "next_reading_path")
            + _wiki_relation_items(relation, "siblings")
        )
        for item in items:
            href = str(item.get("href") or "").strip()
            if not _relation_href_matches_slug(href, slug):
                continue
            if source_slug in seen:
                continue
            seen.add(source_slug)
            backlinks.append(
                {
                    "label": source_slug.replace("_", " ").title(),
                    "href": _preferred_book_href(root_dir, source_slug),
                    "summary": str(item.get("summary") or "").strip() or "이 문서에서 현재 문서로 이동한다.",
                }
            )
    return backlinks


def _build_entity_backlinks(root_dir: Path, entity_slug: str) -> list[dict[str, str]]:
    target_path = f"/wiki/entities/{entity_slug}/index.html"
    backlinks: list[dict[str, str]] = []
    seen: set[str] = set()
    for source_slug, relation in _candidate_relations().items():
        for item in _wiki_relation_items(relation, "entities"):
            href = str(item.get("href") or "").strip()
            if href != target_path or source_slug in seen:
                continue
            seen.add(source_slug)
            backlinks.append(
                {
                    "label": source_slug.replace("_", " ").title(),
                    "href": _preferred_book_href(root_dir, source_slug),
                    "summary": f"{item.get('label') or entity_slug} 엔터티를 이 문서에서 직접 다룬다.",
                }
            )
    return backlinks


def _entity_hub_sections(entity_slug: str) -> list[dict[str, Any]]:
    entity = _entity_hubs().get(entity_slug)
    if entity is None:
        return []
    overview_text = "\n\n".join(str(item).strip() for item in entity.get("overview", []) if str(item).strip())
    navigation_text = "\n\n".join(
        [
            "이 엔터티는 절차 문서, 장애 대응 문서, 상위 운영 문서 사이의 연결 허브다.",
            "관련 북, 역참조 문서, 연계 섹션을 함께 볼 수 있다.",
            "연결 구조를 따라 필요한 문서와 경로를 탐색한다.",
        ]
    )
    title = str(entity.get("title") or entity_slug)
    return [
        {
            "anchor": "overview",
            "heading": "Overview",
            "section_path": [title, "Overview"],
            "text": overview_text,
            "blocks": [],
        },
        {
            "anchor": "how-to-navigate",
            "heading": "How To Navigate",
            "section_path": [title, "How To Navigate"],
            "text": navigation_text,
            "blocks": [],
        },
    ]


def _figure_viewer_sections(slug: str, asset_name: str, asset: dict[str, Any]) -> list[dict[str, Any]]:
    caption = str(asset.get("caption") or asset.get("alt") or asset_name).strip() or asset_name
    asset_url = str(asset.get("asset_url") or "").strip()
    source_file = Path(str(asset.get("source_file") or "").strip()).name
    source_asset_ref = str(asset.get("source_asset_ref") or "").strip()
    section_hint = str(asset.get("section_hint") or "").strip()
    visual_text = "\n".join(
        [
            f"![{caption}]({asset_url})" if asset_url else "",
            "",
            caption,
            "",
            f"이 figure 는 `{slug}` 문서의 시각 자산이다.",
            f"섹션 힌트: {section_hint or 'unmatched'}",
        ]
    ).strip()
    source_text = "\n".join(
        [
            f"원본 파일: `{source_file}`" if source_file else "",
            f"원본 자산: `{source_asset_ref}`" if source_asset_ref else "",
        ]
    ).strip()
    return [
        {
            "anchor": "visual",
            "heading": "Figure",
            "section_path": [caption, "Figure"],
            "text": visual_text,
            "blocks": [],
        },
        {
            "anchor": "source-trace",
            "heading": "Source Trace",
            "section_path": [caption, "Source Trace"],
            "text": source_text,
            "blocks": [],
        },
    ]


__all__ = ["ACTIVE_WIKI_RUNTIME_BOOK_PREFIX", "GOLD_CANDIDATE_BOOK_PREFIX", "LEGACY_WIKI_RUNTIME_BOOK_PREFIX", "_active_runtime_markdown_path", "_book_related_figures", "_book_related_sections", "_build_backlinks", "_build_entity_backlinks", "_candidate_relations", "_chat_link_truth_payload", "_chat_navigation_aliases", "_contains_hangul", "_entity_hub_sections", "_entity_hubs", "_entity_related_sections", "_figure_asset_by_name", "_figure_asset_filename", "_figure_assets", "_figure_entity_index", "_runtime_markdown_path_candidates", "_section_linked_figures", "_figure_section_index", "_figure_section_match", "_figure_viewer_href", "_figure_viewer_sections", "_is_final_runtime_href", "_link_book_slug", "_preferred_book_href", "_prefer_korean_book_links", "_relation_href_matches_slug", "_rewrite_book_href", "_runtime_markdown_path_from_entries", "_runtime_markdown_path_from_manifest", "_section_relation_index", "_wiki_relation_items"]
