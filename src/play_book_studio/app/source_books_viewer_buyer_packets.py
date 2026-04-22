from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

from .source_books_viewer_markdown import _markdown_sections, _markdown_summary, _trim_leading_title_section
from .source_books_viewer_resolver import _load_buyer_packet_entry, parse_buyer_packet_viewer_path
from .viewer_page import _render_page_overlay_toolbar
from .viewers import (
    _build_section_metrics,
    _build_section_outline,
    _build_study_section_cards,
    _render_study_viewer_html,
)


def _build_buyer_packet_supplementary_blocks(bundle: dict[str, object], packet: dict[str, object]) -> list[str]:
    stage = str(bundle.get("current_stage") or "").strip()
    commercial_truth = str(bundle.get("commercial_truth") or "").strip()
    purpose = str(packet.get("purpose") or "").strip()
    related_packets = [
        item for item in (bundle.get("packets") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip() != str(packet.get("id") or "").strip()
    ]
    related_links = "".join(
        """
        <div class="wiki-links">
          <a href="{href}">{label}</a>
          <span>{summary}</span>
        </div>
        """.format(
            href=html.escape(f"/buyer-packets/{str(item.get('id') or '').strip()}", quote=True),
            label=html.escape(str(item.get("title") or "")),
            summary=html.escape(str(item.get("purpose") or "")),
        ).strip()
        for item in related_packets[:4]
    )
    pills = "".join(
        f'<span class="meta-pill">{html.escape(bit)}</span>'
        for bit in [
            "Release Packet",
            stage if stage else "",
            "ready" if str(packet.get("status") or "") == "ok" else str(packet.get("status") or ""),
        ]
        if bit
    )
    return [
        """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">Release Packet</div>
          <div class="viewer-truth-topline">
            <span class="viewer-truth-badge">Release Packet</span>
            <a class="viewer-truth-link" href="/playbook-library">Playbook Library</a>
          </div>
          <div class="viewer-truth-title">{title}</div>
          <p>{summary}</p>
          <div class="wiki-entity-list">{pills}</div>
        </section>
        <section class="wiki-grid">
          <article class="wiki-card">
            <h3>Commercial Truth</h3>
            <div class="wiki-links">
              <a href="/playbook-library">Current Stage</a>
              <span>{commercial_truth}</span>
            </div>
          </article>
          <article class="wiki-card">
            <h3>Related Packets</h3>
            {related_links}
          </article>
        </section>
        """.format(
            title=html.escape(str(packet.get("title") or "")),
            summary=html.escape(purpose or "현재 판매/데모/릴리스 기준선을 고정하는 packet."),
            pills=pills or '<span class="meta-pill">Release Packet</span>',
            commercial_truth=html.escape(commercial_truth or "current commercial truth unavailable"),
            related_links=related_links or '<div class="wiki-empty">연결된 release packet 이 아직 없습니다.</div>',
        ).strip(),
    ]


def internal_buyer_packet_viewer_html(root_dir: Path, viewer_path: str) -> str | None:
    packet_id = parse_buyer_packet_viewer_path(viewer_path)
    if packet_id is None:
        return None
    loaded = _load_buyer_packet_entry(root_dir, packet_id)
    if loaded is None:
        return None
    bundle, packet = loaded
    markdown_path = root_dir / str(packet.get("markdown_path") or "")
    if not markdown_path.exists() or not markdown_path.is_file():
        return None
    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    sections = _markdown_sections(markdown_path.read_text(encoding="utf-8"))
    if not sections:
        return None
    title = str(packet.get("title") or packet_id)
    content_sections = _trim_leading_title_section(sections, title=title)
    summary = str(packet.get("purpose") or "").strip() or _markdown_summary(content_sections)
    cards = _build_study_section_cards(content_sections, target_anchor=request.fragment.strip(), embedded=embedded)
    return _render_study_viewer_html(
        title=title,
        source_url=f"/api/buyer-packet?packet_id={packet_id}",
        cards=cards,
        supplementary_blocks=_build_buyer_packet_supplementary_blocks(bundle, packet),
        section_count=len(content_sections),
        eyebrow="Buyer Packet",
        summary=summary,
        embedded=embedded,
        section_outline=_build_section_outline(content_sections),
        section_metrics=_build_section_metrics(content_sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind="buyer_packet",
            target_ref=f"buyer_packet:{packet_id}",
            title=title,
            viewer_path=f"/buyer-packets/{packet_id}",
        ),
    )


__all__ = ["internal_buyer_packet_viewer_html"]
