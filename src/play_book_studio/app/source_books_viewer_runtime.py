from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

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
    _local_figure_asset_url,
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


def _target_anchor_from_request(viewer_path: str) -> str:
    request = urlparse(str(viewer_path or "").strip())
    fragment = unquote(str(request.fragment or "").strip())
    if fragment:
        return fragment
    params = parse_qs(request.query, keep_blank_values=False)
    for key in ("section", "anchor", "section_anchor"):
        value = unquote(str((params.get(key) or [""])[0]).strip())
        if value:
            return value
    return ""


def _viewer_path_without_query_or_fragment(viewer_path: str) -> str:
    request = urlparse(str(viewer_path or "").strip())
    return urlunparse(request._replace(query="", fragment=""))


def _normalize_anchor_value(value: object) -> str:
    text = unquote(str(value or "").strip()).strip().lstrip("#").rstrip(":")
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def _lookup_key(value: object) -> str:
    text = _normalize_anchor_value(value)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _heading_key(value: object) -> str:
    text = _normalize_anchor_value(value)
    text = re.sub(r"^\s*(?:제\s*)?\d+(?:\.\d+)*\.?\s*", "", text).strip(": ")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _section_candidate_values(section: dict) -> list[str]:
    values = [
        str(section.get("anchor") or ""),
        str(section.get("anchor_id") or ""),
        str(section.get("section_id") or ""),
        str(section.get("section_key") or ""),
        str(section.get("heading") or ""),
    ]
    viewer_path = str(section.get("viewer_path") or "")
    if "#" in viewer_path:
        values.append(viewer_path.split("#", 1)[1])
    for key in ("section_path", "path"):
        for item in section.get(key) or []:
            if str(item or "").strip():
                values.append(str(item))
    return values


def _is_probable_heading_match(left: object, right: object) -> bool:
    left_key = _heading_key(left)
    right_key = _heading_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if len(left_key) >= 6 and len(right_key) >= 6 and (left_key in right_key or right_key in left_key):
        return True
    if len(left_key) < 6 or len(right_key) < 6:
        return False
    return SequenceMatcher(None, left_key, right_key).ratio() >= 0.74


def _find_section_index(
    sections: list[dict],
    target_anchor: str,
    *,
    section_hints: list[str] | None = None,
) -> int | None:
    target = _normalize_anchor_value(target_anchor)
    if not target:
        return None
    for index, row in enumerate(sections):
        if _normalize_anchor_value(row.get("anchor")) == target:
            return index

    target_key = _lookup_key(target)
    if target_key:
        for index, row in enumerate(sections):
            for value in _section_candidate_values(row):
                if _lookup_key(value) == target_key:
                    return index

    for hint in section_hints or []:
        if not str(hint or "").strip():
            continue
        hint_key = _lookup_key(hint)
        for index, row in enumerate(sections):
            for value in _section_candidate_values(row):
                if hint_key and _lookup_key(value) == hint_key:
                    return index
            if _is_probable_heading_match(hint, row.get("heading")):
                return index
    return None


def _single_section_href(viewer_path: str, anchor: str) -> str:
    normalized_anchor = str(anchor or "").strip()
    if not normalized_anchor:
        return "#"
    request = urlparse(str(viewer_path or "").strip())
    params = parse_qs(request.query, keep_blank_values=False)
    params["page_mode"] = ["single"]
    params["section"] = [normalized_anchor]
    return urlunparse(
        request._replace(
            query=urlencode(params, doseq=True),
            fragment=normalized_anchor,
        )
    )


def _section_outline_for_view(
    sections: list[dict],
    *,
    page_mode: str,
    viewer_path: str,
) -> list[dict[str, str]]:
    outline = _build_section_outline(sections)
    if _resolve_page_mode(page_mode) != "single":
        return outline
    enriched: list[dict[str, str]] = []
    for item in outline:
        next_item = dict(item)
        next_item["href"] = _single_section_href(viewer_path, str(item.get("anchor") or ""))
        enriched.append(next_item)
    return enriched


def _select_view_sections(
    sections: list[dict],
    *,
    target_anchor: str,
    page_mode: str,
    section_hints: list[str] | None = None,
) -> list[dict]:
    if _resolve_page_mode(page_mode) == "multi":
        return sections
    if not sections:
        return sections
    if str(target_anchor or "").strip():
        index = _find_section_index(sections, target_anchor, section_hints=section_hints)
        if index is not None:
            return [sections[index]]
    return [sections[0]]


def _section_block_text(section: dict) -> str:
    block_texts: list[str] = []
    for block in section.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or block.get("caption") or block.get("alt") or "").strip()
        if text:
            block_texts.append(text)
    text = str(section.get("text") or "").strip()
    if text:
        block_texts.append(text)
    return " ".join(" ".join(item.split()) for item in block_texts if item).strip()


def _is_leading_source_cover_stub(section: dict) -> bool:
    section_path = [str(item).strip() for item in (section.get("section_path") or []) if str(item).strip()]
    if len(section_path) != 1:
        return False
    block_rows = [block for block in (section.get("blocks") or []) if isinstance(block, dict)]
    block_kinds = {str(block.get("kind") or "").strip().lower() for block in block_rows}
    if block_kinds - {"", "paragraph"}:
        return False
    text = _section_block_text(section)
    if not text or len(text) > 260:
        return False
    normalized_text = text.lower()
    return (
        "법적 고지" in normalized_text
        or "legal notice" in normalized_text
        or ("red hat" in normalized_text and "overview" in normalized_text)
    )


def _trim_leading_runtime_cover_section(sections: list[dict], *, title: str) -> list[dict]:
    del title
    if len(sections) < 2:
        return sections
    if _is_leading_source_cover_stub(sections[0]):
        return sections[1:]
    return sections


def _build_section_navigation(
    sections: list[dict],
    *,
    target_anchor: str,
    page_mode: str,
    viewer_path: str = "",
    section_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    if _resolve_page_mode(page_mode) != "single" or not sections:
        return []
    current_index = 0
    if str(target_anchor or "").strip():
        matched_index = _find_section_index(sections, target_anchor, section_hints=section_hints)
        if matched_index is not None:
            current_index = matched_index
    navigation: list[dict[str, str]] = []
    if current_index > 0:
        previous_row = sections[current_index - 1]
        previous_anchor = str(previous_row.get("anchor") or "").strip()
        previous_heading = str(previous_row.get("heading") or previous_anchor).strip()
        if previous_anchor:
            navigation.append(
                {
                    "label": "이전",
                    "href": _single_section_href(viewer_path, previous_anchor) if viewer_path else f"#{previous_anchor}",
                    "title": previous_heading,
                }
            )
    if current_index + 1 < len(sections):
        next_row = sections[current_index + 1]
        next_anchor = str(next_row.get("anchor") or "").strip()
        next_heading = str(next_row.get("heading") or next_anchor).strip()
        if next_anchor:
            navigation.append(
                {
                    "label": "다음",
                    "href": _single_section_href(viewer_path, next_anchor) if viewer_path else f"#{next_anchor}",
                    "title": next_heading,
                }
            )
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


def _merge_relation_figure_block(blocks: list[dict], figure_block: dict[str, str]) -> bool:
    asset_url = figure_block.get("asset_url", "")
    viewer_path = figure_block.get("viewer_path", "")
    asset_ref = figure_block.get("asset_ref", "")
    for block in blocks:
        if str(block.get("kind") or "").strip() != "figure":
            continue
        matched = (
            bool(asset_url and str(block.get("asset_url") or block.get("src") or "").strip() == asset_url)
            or bool(viewer_path and str(block.get("viewer_path") or "").strip() == viewer_path)
            or bool(asset_ref and str(block.get("asset_ref") or "").strip() == asset_ref)
        )
        if not matched:
            continue
        for key, value in figure_block.items():
            if value and not str(block.get(key) or "").strip():
                block[key] = value
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


def _relation_section_hints(root_dir: Path, book_slug: str, anchor: str) -> list[str]:
    payload = _load_root_json(root_dir, "data/wiki_relations/figure_section_index.json")
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    records = by_slug.get(str(book_slug or "").strip())
    if not isinstance(records, list):
        return []
    hints: list[str] = []
    target_anchor = _normalize_anchor_value(anchor)
    target_key = _lookup_key(anchor)
    for record in records:
        if not isinstance(record, dict):
            continue
        record_anchor = str(record.get("section_anchor") or "").strip()
        if _normalize_anchor_value(record_anchor) != target_anchor and _lookup_key(record_anchor) != target_key:
            continue
        hint = str(record.get("section_heading") or "").strip()
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def _relation_record_matches_section(record: dict, section: dict) -> bool:
    record_anchor = str(record.get("section_anchor") or "").strip()
    section_anchor = str(section.get("anchor") or "").strip()
    if record_anchor and _normalize_anchor_value(record_anchor) == _normalize_anchor_value(section_anchor):
        return True
    if record_anchor and _lookup_key(record_anchor) and _lookup_key(record_anchor) == _lookup_key(section_anchor):
        return True
    return _is_probable_heading_match(record.get("section_heading"), section.get("heading"))


def _relation_figure_blocks_for_section(root_dir: Path, book_slug: str, section: dict) -> list[dict[str, str]]:
    payload = _load_root_json(root_dir, "data/wiki_relations/figure_section_index.json")
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    records = by_slug.get(str(book_slug or "").strip())
    if not isinstance(records, list):
        return []
    anchor = str(section.get("anchor") or "").strip()
    blocks: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if not _relation_record_matches_section(record, section):
            continue
        asset_name = str(record.get("asset_name") or "").strip()
        asset = _root_figure_asset_by_name(root_dir, book_slug, asset_name)
        asset_url = _local_figure_asset_url(root_dir, book_slug, asset_name) or str(asset.get("asset_url") or "").strip()
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
        relation_blocks = _relation_figure_blocks_for_section(root_dir, book_slug, next_row)
        if not relation_blocks:
            enriched.append(next_row)
            continue
        blocks = [dict(block) for block in (next_row.get("blocks") or []) if isinstance(block, dict)]
        if blocks:
            for figure_block in relation_blocks:
                if not _merge_relation_figure_block(blocks, figure_block):
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
    if _resolve_page_mode(page_mode) == "single" and visible_sections:
        resolved_anchor = str(visible_sections[0].get("anchor") or "").strip() or resolved_anchor
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
    book_slug, parsed_anchor = parsed
    target_anchor = _target_anchor_from_request(viewer_path) or parsed_anchor
    base_viewer_path = _viewer_path_without_query_or_fragment(viewer_path)
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

    content_sections = _trim_leading_runtime_cover_section(content_sections, title=book_title)
    content_sections = _sections_with_relation_figures(root_dir, book_slug, content_sections)
    section_hints = _relation_section_hints(root_dir, book_slug, target_anchor)
    visible_sections = _select_view_sections(
        content_sections,
        target_anchor=target_anchor,
        page_mode=page_mode,
        section_hints=section_hints,
    )
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
        section_outline=_section_outline_for_view(content_sections, page_mode=page_mode, viewer_path=base_viewer_path),
        section_navigation=_build_section_navigation(
            content_sections,
            target_anchor=target_anchor,
            page_mode=page_mode,
            viewer_path=base_viewer_path,
            section_hints=section_hints,
        ),
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
    target_anchor = _target_anchor_from_request(viewer_path)
    base_viewer_path = _viewer_path_without_query_or_fragment(viewer_path)
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
    content_sections = _trim_leading_runtime_cover_section(content_sections, title=str(title))
    content_sections = _sections_with_relation_figures(root_dir, slug, content_sections)
    section_hints = _relation_section_hints(root_dir, slug, target_anchor)
    visible_sections = _select_view_sections(
        content_sections,
        target_anchor=target_anchor,
        page_mode=page_mode,
        section_hints=section_hints,
    )
    cards = _build_study_section_cards(visible_sections, book_slug=slug, target_anchor=target_anchor, embedded=embedded, root_dir=root_dir)
    overlay_target = _overlay_target_for_view(
        book_slug=slug,
        title=str(title),
        viewer_path=_preferred_book_href(root_dir, slug),
        target_anchor=target_anchor,
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
        section_outline=_section_outline_for_view(content_sections, page_mode=page_mode, viewer_path=base_viewer_path),
        section_navigation=_build_section_navigation(
            content_sections,
            target_anchor=target_anchor,
            page_mode=page_mode,
            viewer_path=base_viewer_path,
            section_hints=section_hints,
        ),
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
