from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

from .source_books_viewer_resolver import parse_figure_viewer_path
from .source_books_wiki_relations import (
    _candidate_relations,
    _figure_asset_by_name,
    _figure_asset_filename,
    _figure_assets,
    _figure_section_match,
    _figure_viewer_href,
    _figure_viewer_sections,
    _preferred_book_href,
    _rewrite_book_href,
    _wiki_relation_items,
)
from .viewer_page import _render_page_overlay_toolbar
from .viewers import (
    _build_section_metrics,
    _build_section_outline,
    _build_study_section_cards,
    _render_study_viewer_html,
)


def _build_figure_supplementary_blocks(root_dir: Path, slug: str, asset_name: str, asset: dict[str, object]) -> list[str]:
    relation = _candidate_relations().get(slug, {})
    section_match = _figure_section_match(slug, asset_name)
    parent_title = slug.replace("_", " ").title()
    parent_summary = "이 figure 가 포함된 부모 북으로 돌아간다."
    related_entities = [
        item for item in (asset.get("related_entities") or [])
        if isinstance(item, dict) and str(item.get("href") or "").strip()
    ]
    related_entity_links = "".join(
        f'<a href="{html.escape(str(item.get("href") or ""), quote=True)}">{html.escape(str(item.get("label") or ""))}</a>'
        for item in related_entities
    )
    related_books = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(_rewrite_book_href(root_dir, str(item.get("href") or "")), quote=True),
            label=html.escape(str(item.get("label") or "")),
            summary=html.escape(str(item.get("summary") or "")),
        ).strip()
        for item in _wiki_relation_items(relation, "related_docs")
    )
    next_path_links = "".join(
        """
        <div class="wiki-path">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(_rewrite_book_href(root_dir, str(item.get("href") or "")), quote=True),
            label=html.escape(str(item.get("label") or "")),
            summary=html.escape(str(item.get("summary") or "")),
        ).strip()
        for item in _wiki_relation_items(relation, "next_reading_path")
    )
    sibling_figures = [
        item for item in _figure_assets().get(slug, [])
        if isinstance(item, dict) and _figure_asset_filename(item) != asset_name
    ]
    sibling_figure_links = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(_figure_viewer_href(slug, item), quote=True),
            label=html.escape(str(item.get("caption") or _figure_asset_filename(item) or "Figure")),
            summary=html.escape(str(item.get("section_hint") or "같은 문서의 다른 figure 자산")),
        ).strip()
        for item in sibling_figures[:6]
    )
    related_section_block = ""
    if isinstance(section_match, dict) and str(section_match.get("section_href") or "").strip():
        related_section_block = """
        <article class="wiki-card">
          <h3>Related Section</h3>
          <div class="wiki-links">
            <a href="{href}">{label}</a>
            <span>{summary}</span>
          </div>
        </article>
        """.format(
            href=html.escape(str(section_match.get("section_href") or ""), quote=True),
            label=html.escape(str(section_match.get("section_heading") or "Related Section")),
            summary=html.escape(str(section_match.get("section_path") or str(section_match.get("section_hint") or ""))),
        ).strip()
    return [
        """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">Parent Book</div>
          <a href="{href}">{label}</a>
          <p>{summary}</p>
        </section>
        <section class="wiki-grid">
          <article class="wiki-card">
            <h3>Entities</h3>
            <div class="wiki-entity-list">{entity_links}</div>
          </article>
          <article class="wiki-card">
            <h3>Documents</h3>
            {related_books}
          </article>
          <article class="wiki-card">
            <h3>Recommended Path</h3>
            {next_path_links}
          </article>
        </section>
        <section class="wiki-grid wiki-grid-secondary">
          {related_section_block}
          <article class="wiki-card">
            <h3>Figures</h3>
            {sibling_figure_links}
          </article>
        </section>
        """.format(
            href=html.escape(_preferred_book_href(root_dir, slug), quote=True),
            label=html.escape(parent_title),
            summary=html.escape(parent_summary),
            entity_links=related_entity_links or '<div class="wiki-empty">연결된 엔터티가 아직 없습니다.</div>',
            related_books=related_books or '<div class="wiki-empty">연관 문서가 아직 없습니다.</div>',
            next_path_links=next_path_links or '<div class="wiki-empty">연결된 경로가 아직 없습니다.</div>',
            related_section_block=related_section_block or '<article class="wiki-card"><h3>Section Match</h3><div class="wiki-empty">정확한 섹션 매칭이 아직 없습니다.</div></article>',
            sibling_figure_links=sibling_figure_links or '<div class="wiki-empty">같은 문서의 다른 figure 자산이 없습니다.</div>',
        ).strip(),
    ]


def internal_figure_viewer_html(root_dir: Path, viewer_path: str) -> str | None:
    parsed = parse_figure_viewer_path(viewer_path)
    if parsed is None:
        return None
    slug, asset_name = parsed
    asset = _figure_asset_by_name(slug, asset_name)
    if asset is None:
        return None
    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    title = str(asset.get("caption") or asset.get("alt") or asset_name).strip() or asset_name
    sections = _figure_viewer_sections(slug, asset_name, asset)
    cards = _build_study_section_cards(sections, book_slug=slug, target_anchor=request.fragment.strip(), embedded=embedded)
    return _render_study_viewer_html(
        title=title,
        source_url=str(asset.get("asset_url") or "").strip(),
        cards=cards,
        supplementary_blocks=_build_figure_supplementary_blocks(root_dir, slug, asset_name, asset),
        section_count=len(sections),
        eyebrow="Figure Asset",
        summary=f"{slug.replace('_', ' ').title()} 문서에서 추출한 figure 자산이다.",
        embedded=embedded,
        section_outline=_build_section_outline(sections),
        section_metrics=_build_section_metrics(sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind="figure",
            target_ref=f"figure:{slug}:{asset_name}",
            title=title,
            book_slug=slug,
            asset_name=asset_name,
            viewer_path=f"/wiki/figures/{slug}/{asset_name}/index.html",
        ),
    )


__all__ = ["internal_figure_viewer_html"]
