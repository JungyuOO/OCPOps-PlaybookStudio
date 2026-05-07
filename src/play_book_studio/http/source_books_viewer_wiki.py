from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.source_provenance import source_provenance_payload

from .presenters import _manifest_entry_for_book
from .runtime_truth import official_runtime_truth_payload
from .source_books_wiki_relations import (
    _book_related_figures,
    _book_related_sections,
    _build_backlinks,
    _candidate_relations,
    _preferred_book_href,
    _rewrite_book_href,
    _wiki_relation_items,
)


def _build_wiki_supplementary_blocks(root_dir: Path, slug: str) -> list[str]:
    relation = _candidate_relations().get(slug, {})
    manifest_entry = _manifest_entry_for_book(root_dir, slug)
    settings = load_settings(root_dir)
    truth = official_runtime_truth_payload(settings=settings, manifest_entry=manifest_entry)
    provenance = source_provenance_payload(manifest_entry)
    title = str(manifest_entry.get("title") or slug.replace("_", " ").title())
    summary = str(manifest_entry.get("summary") or "").strip()
    related_figures = _wiki_relation_items(relation, "related_figures") or _book_related_figures(slug)
    related_sections = _wiki_relation_items(relation, "related_sections") or _book_related_sections(slug)
    sibling_docs = _wiki_relation_items(relation, "sibling_docs") or _wiki_relation_items(relation, "siblings")
    parent_block = ""
    if summary:
        parent_block = """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">{eyebrow}</div>
          <a href="{href}">{label}</a>
          <p>{summary}</p>
        </section>
        """.format(
            eyebrow=html.escape(str(truth.get("boundary_badge") or "Source-First Candidate")),
            href=html.escape(_preferred_book_href(root_dir, slug), quote=True),
            label=html.escape(title),
            summary=html.escape(summary),
        ).strip()
    entity_links = "".join(
        f'<a href="{html.escape(str(item.get("href") or ""), quote=True)}">{html.escape(str(item.get("label") or ""))}</a>'
        for item in _wiki_relation_items(relation, "entities")
    )
    related_links = "".join(
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
    backlinks = _build_backlinks(root_dir, slug)
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
    sibling_blocks = "".join(
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
        for item in sibling_docs
    )
    figure_blocks = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(str(item.get("viewer_path") or item.get("asset_url") or ""), quote=True),
            label=html.escape(str(item.get("caption") or "Figure")),
            summary=html.escape(str(item.get("section_hint") or "related figure")),
        ).strip()
        for item in related_figures
    )
    section_blocks = "".join(
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
        for item in related_sections
    )
    source_repo = str(provenance.get("source_repo") or "").strip()
    source_branch = str(provenance.get("source_branch") or "").strip()
    source_binding_kind = str(provenance.get("source_binding_kind") or "").strip() or "file"
    source_ref = str(provenance.get("source_ref") or "").strip()
    source_fingerprint = str(provenance.get("source_fingerprint") or "").strip()
    fallback_source_url = str(provenance.get("fallback_source_url") or "").strip()
    source_relative_paths = [
        str(item).strip()
        for item in (provenance.get("source_relative_paths") or [])
        if str(item).strip()
    ]
    source_summary = (
        f"{source_repo}@{source_branch} 기준으로 {len(source_relative_paths)}개 경로를 바인딩한 active runtime이다."
        if source_repo and source_branch and source_relative_paths
        else "repo/AsciiDoc first 기준으로 생성한 active runtime이다."
    )
    repo_label = source_repo.rsplit("/", 1)[-1] if source_repo else "Repo Source"
    bound_path_links = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(source_repo or _preferred_book_href(root_dir, slug), quote=True),
            label=html.escape(path),
            summary=html.escape(f"{source_binding_kind} binding"),
        ).strip()
        for path in source_relative_paths[:4]
    )
    provenance_block = """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">Repo/AsciiDoc First</div>
          <div class="viewer-truth-topline">
            <span class="viewer-truth-badge">Source Trace</span>
            <a class="viewer-truth-link" href="{repo_href}">{repo_label}</a>
          </div>
          <div class="viewer-truth-title">{binding_title}</div>
          <p>{source_summary}</p>
          <div class="wiki-entity-list">
            <span class="meta-pill">binding: {binding_kind}</span>
            <span class="meta-pill">paths: {path_count}</span>
            <span class="meta-pill">fingerprint: {fingerprint}</span>
          </div>
        </section>
        <section class="wiki-grid wiki-grid-secondary">
          <article class="wiki-card">
            <h3>Source Binding</h3>
            <div class="wiki-links">
              <a href="{repo_href}">{source_ref_label}</a>
              <span>{source_ref_summary}</span>
            </div>
          </article>
          <article class="wiki-card">
            <h3>Benchmark Surface</h3>
            {benchmark_links}
          </article>
          <article class="wiki-card">
            <h3>Bound Paths</h3>
            {bound_path_links}
          </article>
        </section>
    """.format(
        repo_href=html.escape(source_repo or _preferred_book_href(root_dir, slug), quote=True),
        repo_label=html.escape(repo_label),
        binding_title=html.escape("Collection Binding" if source_binding_kind == "collection" else "File Binding"),
        source_summary=html.escape(source_summary),
        binding_kind=html.escape(source_binding_kind),
        path_count=len(source_relative_paths),
        fingerprint=html.escape(source_fingerprint or "untracked"),
        source_ref_label=html.escape(source_ref or title),
        source_ref_summary=html.escape(source_branch or "branch untracked"),
        benchmark_links=(
            """
            <div class="wiki-links">
              <a href="{href}">Red Hat HTML Single</a>
              <span>reader benchmark / verification / fallback</span>
            </div>
            """.format(href=html.escape(fallback_source_url, quote=True)).strip()
            if fallback_source_url
            else '<div class="wiki-empty">등록된 benchmark surface가 없습니다.</div>'
        ),
        bound_path_links=bound_path_links or '<div class="wiki-empty">표시할 source path가 없습니다.</div>',
    ).strip()
    return [
        provenance_block,
        """
        <section class="wiki-grid">
          <article class="wiki-card">
            <h3>Entities</h3>
            <div class="wiki-entity-list">{entity_links}</div>
          </article>
          <article class="wiki-card">
            <h3>Related Documents</h3>
            {related_links}
          </article>
          <article class="wiki-card">
            <h3>Recommended Path</h3>
            {next_path_links}
          </article>
        </section>
        <details class="wiki-details">
          <summary>More</summary>
          <section class="wiki-grid wiki-grid-secondary">
            <article class="wiki-card">
              <h3>Backlinks</h3>
              {backlink_links}
            </article>
            <article class="wiki-card">
              <h3>Sibling Documents</h3>
              {sibling_blocks}
            </article>
            <article class="wiki-card">
              <h3>Figures</h3>
              {figure_blocks}
            </article>
            <article class="wiki-card">
              <h3>Sections</h3>
              {section_blocks}
            </article>
          </section>
        </details>
        """.format(
            entity_links=entity_links or '<div class="wiki-empty">핵심 엔터티 연결이 아직 없습니다.</div>',
            related_links=related_links or '<div class="wiki-empty">연결된 문서가 아직 없습니다.</div>',
            next_path_links=next_path_links or '<div class="wiki-empty">연결된 경로가 아직 없습니다.</div>',
            backlink_links=backlink_links or '<div class="wiki-empty">아직 연결된 역방향 문서가 없습니다.</div>',
            sibling_blocks=sibling_blocks or '<div class="wiki-empty">같은 작업군 문서는 아직 준비 중입니다.</div>',
            figure_blocks=figure_blocks or '<div class="wiki-empty">연결된 figure 자산이 아직 없습니다.</div>',
            section_blocks=section_blocks or '<div class="wiki-empty">연결된 절차 섹션이 아직 없습니다.</div>',
        ).strip(),
    ]


__all__ = ["_build_wiki_supplementary_blocks"]
