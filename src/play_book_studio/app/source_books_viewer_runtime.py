from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from play_book_studio.config.settings import load_settings

from .presenters import _manifest_entry_for_book
from .runtime_truth import official_runtime_truth_payload
from .source_books_viewer_markdown import (
    _markdown_sections,
    _markdown_summary,
    _normalized_book_summary,
    _playbook_viewer_chrome,
    _trim_leading_title_section,
)
from .source_books_viewer_resolver import (
    _load_normalized_book_sections,
    _load_playbook_book,
    parse_active_runtime_markdown_viewer_path,
)
from .source_books_viewer_wiki import _build_wiki_supplementary_blocks
from .source_books_wiki_relations import (
    _active_runtime_markdown_path,
    _figure_asset_filename,
    _figure_viewer_href,
    _preferred_book_href,
)
from .viewer_page import _render_page_overlay_toolbar
from .viewers import (
    _build_section_metrics,
    _build_section_outline,
    _build_study_section_cards,
    _parse_viewer_path,
    _render_study_viewer_html,
)


def _resolve_page_mode(page_mode: str) -> str:
    normalized = str(page_mode or "").strip().lower()
    return "multi" if normalized == "multi" else "single"


def _select_view_sections(
    sections: list[dict],
    *,
    target_anchor: str,
    page_mode: str,
) -> list[dict]:
    if _resolve_page_mode(page_mode) == "multi":
        return sections
    if not sections:
        return sections
    normalized_anchor = str(target_anchor or "").strip()
    if normalized_anchor:
        for row in sections:
            if str(row.get("anchor") or "").strip() == normalized_anchor:
                return [row]
    return [sections[0]]


def _build_section_navigation(
    sections: list[dict],
    *,
    target_anchor: str,
    page_mode: str,
) -> list[dict[str, str]]:
    if _resolve_page_mode(page_mode) != "single" or not sections:
        return []
    current_index = 0
    normalized_anchor = str(target_anchor or "").strip()
    if normalized_anchor:
        for index, row in enumerate(sections):
            if str(row.get("anchor") or "").strip() == normalized_anchor:
                current_index = index
                break
    navigation: list[dict[str, str]] = []
    if current_index > 0:
        previous_row = sections[current_index - 1]
        previous_anchor = str(previous_row.get("anchor") or "").strip()
        previous_heading = str(previous_row.get("heading") or previous_anchor).strip()
        if previous_anchor:
            navigation.append({"label": "이전", "href": f"#{previous_anchor}", "title": previous_heading})
    if current_index + 1 < len(sections):
        next_row = sections[current_index + 1]
        next_anchor = str(next_row.get("anchor") or "").strip()
        next_heading = str(next_row.get("heading") or next_anchor).strip()
        if next_anchor:
            navigation.append({"label": "다음", "href": f"#{next_anchor}", "title": next_heading})
    return navigation


def _marker_attr_value(value: str) -> str:
    return " ".join(str(value or "").replace('"', "'").split()).strip()


def _figure_marker(block: dict[str, str]) -> str:
    attrs = []
    for key in (
        "src",
        "asset_url",
        "asset_ref",
        "alt",
        "viewer_path",
        "source_anchor",
        "asset_kind",
        "diagram_type",
        "kind_label",
    ):
        value = _marker_attr_value(block.get(key, ""))
        if value:
            attrs.append(f'{key}="{value}"')
    caption = str(block.get("caption") or "").strip()
    return "[FIGURE {attrs}]\n{caption}\n[/FIGURE]".format(
        attrs=" ".join(attrs),
        caption=caption,
    )


def _section_has_figure(blocks: list[dict], *, asset_url: str, viewer_path: str, asset_ref: str) -> bool:
    for block in blocks:
        if str(block.get("kind") or "").strip() != "figure":
            continue
        if asset_url and str(block.get("asset_url") or block.get("src") or "").strip() == asset_url:
            return True
        if viewer_path and str(block.get("viewer_path") or "").strip() == viewer_path:
            return True
        if asset_ref and str(block.get("asset_ref") or "").strip() == asset_ref:
            return True
    return False


def _load_root_json(root_dir: Path, relative_path: str) -> dict:
    path = root_dir / relative_path
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _root_figure_asset_by_name(root_dir: Path, slug: str, asset_name: str) -> dict:
    payload = _load_root_json(root_dir, "data/wiki_relations/figure_assets.json")
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    items = entries.get(str(slug or "").strip()) if isinstance(entries, dict) else []
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if _figure_asset_filename(item) == str(asset_name or "").strip():
            return item
    return {}


def _relation_figure_blocks(root_dir: Path, book_slug: str, anchor: str) -> list[dict[str, str]]:
    payload = _load_root_json(root_dir, "data/wiki_relations/figure_section_index.json")
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    records = by_slug.get(str(book_slug or "").strip())
    if not isinstance(records, list):
        return []
    blocks: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("section_anchor") or "").strip() != str(anchor or "").strip():
            continue
        asset_name = str(record.get("asset_name") or "").strip()
        asset = _root_figure_asset_by_name(root_dir, book_slug, asset_name)
        asset_url = str(asset.get("asset_url") or "").strip()
        viewer_path = str(record.get("viewer_path") or "").strip() or _figure_viewer_href(book_slug, asset)
        asset_ref = str(asset.get("source_asset_ref") or asset_name or _figure_asset_filename(asset)).strip()
        blocks.append(
            {
                "kind": "figure",
                "src": asset_url,
                "asset_url": asset_url,
                "asset_ref": asset_ref,
                "caption": str(record.get("caption") or asset.get("caption") or asset.get("alt") or asset_name or "Figure").strip(),
                "alt": str(asset.get("alt") or record.get("caption") or asset_name or "Figure").strip(),
                "viewer_path": viewer_path,
                "source_anchor": str(anchor or "").strip(),
                "asset_kind": str(asset.get("asset_kind") or "figure").strip() or "figure",
                "diagram_type": str(asset.get("diagram_type") or "").strip(),
                "kind_label": str(asset.get("asset_kind") or "").strip(),
            }
        )
    return blocks


def _sections_with_relation_figures(root_dir: Path, book_slug: str, sections: list[dict]) -> list[dict]:
    if not book_slug or not sections:
        return sections
    enriched: list[dict] = []
    for row in sections:
        next_row = dict(row)
        anchor = str(next_row.get("anchor") or "").strip()
        relation_blocks = _relation_figure_blocks(root_dir, book_slug, anchor)
        if not relation_blocks:
            enriched.append(next_row)
            continue
        blocks = [dict(block) for block in (next_row.get("blocks") or []) if isinstance(block, dict)]
        if blocks:
            for figure_block in relation_blocks:
                if not _section_has_figure(
                    blocks,
                    asset_url=figure_block["asset_url"],
                    viewer_path=figure_block["viewer_path"],
                    asset_ref=figure_block["asset_ref"],
                ):
                    blocks.append(figure_block)
            next_row["blocks"] = blocks
            next_row["block_kinds"] = [str(block.get("kind") or "") for block in blocks if str(block.get("kind") or "")]
        else:
            existing_text = str(next_row.get("text") or "").strip()
            figure_text = "\n\n".join(_figure_marker(block) for block in relation_blocks).strip()
            next_row["text"] = "\n\n".join(part for part in (existing_text, figure_text) if part).strip()
        enriched.append(next_row)
    return enriched


def _overlay_target_for_view(
    *,
    book_slug: str,
    title: str,
    viewer_path: str,
    target_anchor: str,
    visible_sections: list[dict],
    page_mode: str,
) -> dict[str, str]:
    resolved_anchor = str(target_anchor or "").strip()
    if not resolved_anchor and _resolve_page_mode(page_mode) == "single" and visible_sections:
        resolved_anchor = str(visible_sections[0].get("anchor") or "").strip()
    if resolved_anchor:
        return {
            "target_kind": "section",
            "target_ref": f"section:{book_slug}#{resolved_anchor}",
            "title": str(visible_sections[0].get("heading") or title or book_slug),
            "anchor": resolved_anchor,
            "viewer_path": f"{viewer_path}#{resolved_anchor}" if "#" not in viewer_path else viewer_path,
        }
    return {
        "target_kind": "book",
        "target_ref": f"book:{book_slug}",
        "title": title,
        "anchor": "",
        "viewer_path": viewer_path,
    }


def internal_viewer_html(root_dir: Path, viewer_path: str, *, page_mode: str = "single") -> str | None:
    parsed = _parse_viewer_path(viewer_path)
    if parsed is None:
        return None

    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    book_slug, target_anchor = parsed
    playbook_book = _load_playbook_book(root_dir, book_slug)
    manifest_entry = _manifest_entry_for_book(root_dir, book_slug)
    settings = load_settings(root_dir)
    if playbook_book is None:
        sections = _load_normalized_book_sections(root_dir, book_slug)
        source_url = (
            str(manifest_entry.get("source_url") or "").strip()
            or _preferred_book_href(root_dir, book_slug)
        )
        if not sections:
            markdown_path = _active_runtime_markdown_path(root_dir, book_slug)
            if markdown_path is None or not markdown_path.exists() or not markdown_path.is_file():
                return None
            sections = _markdown_sections(markdown_path.read_text(encoding="utf-8"))
            if not sections:
                return None
            book_title = (
                str(manifest_entry.get("title") or "").strip()
                or str(sections[0].get("heading") or "").strip()
                or book_slug.replace("_", " ").title()
            )
            content_sections = _trim_leading_title_section(sections, title=book_title)
            if not content_sections:
                content_sections = sections
        else:
            book_title = (
                str(manifest_entry.get("title") or "").strip()
                or str(sections[0].get("book_title") or "").strip()
                or book_slug.replace("_", " ").title()
            )
            content_sections = sections
        eyebrow = official_runtime_truth_payload(settings=settings, manifest_entry=manifest_entry).get("boundary_badge") or "Source-First Candidate"
        summary = _normalized_book_summary(content_sections)
    else:
        sections = [dict(section) for section in (playbook_book.get("sections") or []) if isinstance(section, dict)]
        if not sections:
            return None
        book_title = str(playbook_book.get("title") or book_slug)
        source_url = str(playbook_book.get("source_uri") or "")
        eyebrow, summary = _playbook_viewer_chrome(playbook_book)
        content_sections = sections

    content_sections = _sections_with_relation_figures(root_dir, book_slug, content_sections)
    visible_sections = _select_view_sections(content_sections, target_anchor=target_anchor, page_mode=page_mode)
    cards = _build_study_section_cards(visible_sections, book_slug=book_slug, target_anchor=target_anchor, embedded=embedded, root_dir=root_dir)
    overlay_target = _overlay_target_for_view(
        book_slug=book_slug,
        title=book_title,
        viewer_path=f"/docs/ocp/{settings.ocp_version}/{settings.docs_language}/{book_slug}/index.html",
        target_anchor=target_anchor,
        visible_sections=visible_sections,
        page_mode=page_mode,
    )
    return _render_study_viewer_html(
        title=book_title,
        source_url=source_url,
        cards=cards,
        section_count=len(content_sections),
        eyebrow=eyebrow,
        summary=summary,
        embedded=embedded,
        section_outline=_build_section_outline(content_sections),
        section_navigation=_build_section_navigation(content_sections, target_anchor=target_anchor, page_mode=page_mode),
        section_metrics=_build_section_metrics(content_sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind=overlay_target["target_kind"],
            target_ref=overlay_target["target_ref"],
            title=overlay_target["title"],
            book_slug=book_slug,
            anchor=overlay_target["anchor"],
            viewer_path=overlay_target["viewer_path"],
        ),
    )


def internal_active_runtime_markdown_viewer_html(root_dir: Path, viewer_path: str, *, page_mode: str = "single") -> str | None:
    slug = parse_active_runtime_markdown_viewer_path(viewer_path)
    if not slug:
        return None
    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    manifest_entry = _manifest_entry_for_book(root_dir, slug)
    playbook_book = _load_playbook_book(root_dir, slug)
    if playbook_book is not None:
        sections = [dict(section) for section in (playbook_book.get("sections") or []) if isinstance(section, dict)]
        if not sections:
            return None
        title = str(playbook_book.get("title") or slug)
        content_sections = sections
        summary = _playbook_viewer_chrome(playbook_book)[1]
        source_url = str(playbook_book.get("source_uri") or "")
    else:
        sections = _load_normalized_book_sections(root_dir, slug)
        if sections:
            title = (
                str(manifest_entry.get("title") or "").strip()
                or str(sections[0].get("book_title") or "").strip()
                or slug.replace("_", " ").title()
            )
            content_sections = sections
            summary = _normalized_book_summary(content_sections)
            source_url = (
                str(manifest_entry.get("source_url") or "").strip()
                or _preferred_book_href(root_dir, slug)
            )
        else:
            markdown_path = _active_runtime_markdown_path(root_dir, slug)
            if markdown_path is None or not markdown_path.exists() or not markdown_path.is_file():
                return None
            sections = _markdown_sections(markdown_path.read_text(encoding="utf-8"))
            if not sections:
                return None
            title = sections[0].get("heading") or slug.replace("_", " ").title()
            content_sections = _trim_leading_title_section(sections, title=str(title))
            summary = _markdown_summary(content_sections)
            source_url = ""
    content_sections = _sections_with_relation_figures(root_dir, slug, content_sections)
    visible_sections = _select_view_sections(content_sections, target_anchor=request.fragment.strip(), page_mode=page_mode)
    cards = _build_study_section_cards(visible_sections, book_slug=slug, target_anchor=request.fragment.strip(), embedded=embedded, root_dir=root_dir)
    overlay_target = _overlay_target_for_view(
        book_slug=slug,
        title=str(title),
        viewer_path=_preferred_book_href(root_dir, slug),
        target_anchor=request.fragment.strip(),
        visible_sections=visible_sections,
        page_mode=page_mode,
    )
    return _render_study_viewer_html(
        title=str(title),
        source_url=source_url,
        cards=cards,
        supplementary_blocks=_build_wiki_supplementary_blocks(root_dir, slug),
        section_count=len(content_sections),
        eyebrow=official_runtime_truth_payload(settings=load_settings(root_dir), manifest_entry=manifest_entry).get("boundary_badge") or "Source-First Candidate",
        summary=summary,
        embedded=embedded,
        section_outline=_build_section_outline(content_sections),
        section_navigation=_build_section_navigation(content_sections, target_anchor=request.fragment.strip(), page_mode=page_mode),
        section_metrics=_build_section_metrics(content_sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind=overlay_target["target_kind"],
            target_ref=overlay_target["target_ref"],
            title=overlay_target["title"],
            book_slug=slug,
            anchor=overlay_target["anchor"],
            viewer_path=overlay_target["viewer_path"],
        ),
    )


__all__ = [
    "internal_active_runtime_markdown_viewer_html",
    "internal_viewer_html",
]
