from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

from .source_books_viewer_resolver import parse_entity_hub_viewer_path
from .source_books_wiki_relations import (
    _build_entity_backlinks,
    _entity_hub_sections,
    _entity_hubs,
    _entity_related_sections,
    _figure_entity_index,
    _rewrite_book_href,
)
from .viewer_page import _render_page_overlay_toolbar
from .viewers import (
    _build_section_metrics,
    _build_section_outline,
    _build_study_section_cards,
    _render_study_viewer_html,
)


def _build_entity_hub_supplementary_blocks(root_dir: Path, entity_slug: str) -> list[str]:
    entity = _entity_hubs().get(entity_slug)
    if entity is None:
        return []
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
        for item in entity.get("related_books", [])
        if isinstance(item, dict)
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
        for item in entity.get("next_reading_path", [])
        if isinstance(item, dict)
    )
    backlinks = _build_entity_backlinks(root_dir, entity_slug)
    figure_index = _figure_entity_index()
    related_figures = figure_index.get("by_entity", {}).get(entity_slug, []) if isinstance(figure_index.get("by_entity"), dict) else []
    related_sections = _entity_related_sections(entity_slug)
    backlink_links = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(str(item.get("href") or ""), quote=True),
            label=html.escape(str(item.get("label") or "")),
            summary=html.escape(str(item.get("summary") or "")),
        ).strip()
        for item in backlinks
    )
    figure_links = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(str(item.get("viewer_path") or item.get("asset_url") or ""), quote=True),
            label=html.escape(str(item.get("caption") or "Figure")),
            summary=html.escape(
                "{book} · {section}".format(
                    book=str(item.get("book_title") or item.get("book_slug") or "").strip() or "related book",
                    section=str(item.get("section_hint") or "unmatched").strip() or "unmatched",
                )
            ),
        ).strip()
        for item in related_figures[:6]
        if isinstance(item, dict)
    )
    section_links = "".join(
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
        for item in related_sections[:6]
        if isinstance(item, dict)
    )
    return [
        """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">Entity Hub</div>
          <a href="/wiki/entities/{entity_slug}/index.html">{title}</a>
          <p>{summary}</p>
        </section>
        <section class="wiki-grid wiki-grid-primary">
          <article class="wiki-card wiki-card-primary">
            <h3>Recommended Path</h3>
            {next_path_links}
          </article>
          <article class="wiki-card wiki-card-primary">
            <h3>Connections</h3>
            <div class="wiki-card-stack">
              <div>
                <h4>Books</h4>
                {related_books}
              </div>
              <div>
                <h4>Referenced By</h4>
                {backlink_links}
              </div>
            </div>
          </article>
        </section>
        <details class="wiki-details">
          <summary>More</summary>
          <section class="wiki-grid wiki-grid-secondary">
            <article class="wiki-card">
              <h3>Related Figures</h3>
              {figure_links}
            </article>
            <article class="wiki-card">
              <h3>Related Sections</h3>
              {section_links}
            </article>
          </section>
        </details>
        """.format(
            entity_slug=html.escape(entity_slug, quote=True),
            title=html.escape(str(entity.get("title") or entity_slug)),
            summary=html.escape(str(entity.get("summary") or "")),
            related_books=related_books or '<div class="wiki-empty">연결된 북이 아직 없습니다.</div>',
            next_path_links=next_path_links or '<div class="wiki-empty">연결된 경로가 아직 없습니다.</div>',
            backlink_links=backlink_links or '<div class="wiki-empty">이 엔터티를 참조하는 문서가 아직 없습니다.</div>',
            figure_links=figure_links or '<div class="wiki-empty">연결된 figure 자산이 아직 없습니다.</div>',
            section_links=section_links or '<div class="wiki-empty">연결된 절차 섹션이 아직 없습니다.</div>',
        ).strip(),
    ]


def internal_entity_hub_viewer_html(root_dir: Path, viewer_path: str) -> str | None:
    parsed = parse_entity_hub_viewer_path(viewer_path)
    if parsed is None:
        return None
    entity = _entity_hubs().get(parsed)
    if entity is None:
        return None
    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    sections = _entity_hub_sections(parsed)
    cards = _build_study_section_cards(sections, target_anchor=request.fragment.strip(), embedded=embedded)
    return _render_study_viewer_html(
        title=str(entity.get("title") or parsed),
        source_url="",
        cards=cards,
        supplementary_blocks=_build_entity_hub_supplementary_blocks(root_dir, parsed),
        section_count=len(sections),
        eyebrow=str(entity.get("eyebrow") or "Entity Hub"),
        summary=str(entity.get("summary") or ""),
        embedded=embedded,
        section_outline=_build_section_outline(sections),
        section_metrics=_build_section_metrics(sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind="entity_hub",
            target_ref=f"entity:{parsed}",
            title=str(entity.get("title") or parsed),
            entity_slug=parsed,
            viewer_path=f"/wiki/entities/{parsed}/index.html",
        ),
    )


__all__ = ["internal_entity_hub_viewer_html"]
