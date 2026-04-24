"""customer-pack viewer and listing helpers."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore

from .presenters import _default_customer_pack_summary
from .customer_pack_read_boundary import load_customer_pack_read_boundary
from .viewer_page import _render_page_overlay_toolbar
from .viewers import (
    _build_section_metrics,
    _build_section_outline,
    _build_study_section_cards,
    _render_study_viewer_html,
)


CUSTOMER_PACK_VIEWER_PREFIX = "/playbooks/customer-packs/"


def _customer_pack_boundary_payload(record: Any) -> dict[str, Any]:
    truth_label = "Customer Source-First Pack"
    boundary_badge = "Private Pack Runtime"
    evidence = {
        "source_lane": str(getattr(record, "source_lane", "") or "customer_source_first_pack"),
        "source_fingerprint": str(getattr(record, "source_fingerprint", "") or ""),
        "parser_route": str(getattr(record, "parser_route", "") or ""),
        "parser_backend": str(getattr(record, "parser_backend", "") or ""),
        "parser_version": str(getattr(record, "parser_version", "") or ""),
        "ocr_used": bool(getattr(record, "ocr_used", False)),
        "extraction_confidence": float(getattr(record, "extraction_confidence", 0.0) or 0.0),
        "degraded_pdf": bool(getattr(record, "degraded_pdf", False)),
        "degraded_reason": str(getattr(record, "degraded_reason", "") or ""),
        "fallback_used": bool(getattr(record, "fallback_used", False)),
        "fallback_backend": str(getattr(record, "fallback_backend", "") or ""),
        "fallback_status": str(getattr(record, "fallback_status", "") or ""),
        "fallback_reason": str(getattr(record, "fallback_reason", "") or ""),
        "tenant_id": str(getattr(record, "tenant_id", "") or ""),
        "workspace_id": str(getattr(record, "workspace_id", "") or ""),
        "approval_state": str(getattr(record, "approval_state", "") or "unreviewed"),
        "publication_state": str(getattr(record, "publication_state", "") or "draft"),
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": truth_label,
        "boundary_badge": boundary_badge,
    }
    return {
        **evidence,
        "customer_pack_evidence": evidence,
    }


def parse_customer_pack_viewer_path(viewer_path: str) -> tuple[str, str] | None:
    parsed = urlparse((viewer_path or "").strip())
    path = parsed.path.strip()
    if not path.startswith(CUSTOMER_PACK_VIEWER_PREFIX):
        return None
    remainder = path.removeprefix(CUSTOMER_PACK_VIEWER_PREFIX).strip("/")
    parts = [part for part in remainder.split("/") if part]
    if len(parts) == 2 and parts[1] == "index.html":
        return parts[0], parsed.fragment.strip()
    if len(parts) == 4 and parts[1] == "assets" and parts[3] == "index.html":
        return f"{parts[0]}::{parts[2]}", parsed.fragment.strip()
    return None


def _resolve_page_mode(page_mode: str) -> str:
    return "multi" if str(page_mode or "").strip().lower() == "multi" else "single"


def _customer_pack_slide_summary(payload: dict[str, Any]) -> str:
    return (
        "업로드한 PPT를 슬라이드 단위로 보존한 내부 review view입니다. "
        "텍스트, 표, 이미지 자산을 같은 슬라이드 truth에서 함께 보여줍니다."
    )


def _customer_pack_slide_mode_label(page_mode: str) -> str:
    return "카드식 슬라이드 목록" if _resolve_page_mode(page_mode) == "multi" else "원본 슬라이드 1장"


def _customer_pack_slide_focus_label(slide: dict[str, Any]) -> str:
    ordinal = int(slide.get("ordinal") or 0)
    title = str(slide.get("title") or slide.get("slide_anchor") or "Slide").strip() or "Slide"
    matched_heading = str(slide.get("matched_section_heading") or "").strip()
    parts = [f"Slide {ordinal}" if ordinal > 0 else "Slide", title]
    if matched_heading and matched_heading != title:
        parts.append(matched_heading)
    return " · ".join(part for part in parts if part)


def _customer_pack_slide_subject(slide: dict[str, Any]) -> str:
    title = str(slide.get("title") or slide.get("slide_anchor") or "Slide").strip() or "Slide"
    matched_heading = str(slide.get("matched_section_heading") or "").strip()
    return matched_heading if matched_heading and matched_heading != title else title


def _customer_pack_slide_number_label(slide: dict[str, Any], *, total_slides: int) -> str:
    ordinal = int(slide.get("ordinal") or 0)
    if ordinal > 0 and total_slides > 0:
        return f"Slide {ordinal} / {total_slides}"
    if ordinal > 0:
        return f"Slide {ordinal}"
    return "Slide"


def _load_customer_pack_slide_packets(payload: dict[str, Any]) -> dict[str, Any] | None:
    artifact_bundle = dict(payload.get("artifact_bundle") or {})
    slide_packets_path = Path(str(artifact_bundle.get("slide_packets_path") or "").strip())
    if slide_packets_path.as_posix() in {"", "."} or not slide_packets_path.exists() or not slide_packets_path.is_file():
        return None
    try:
        slide_packets = json.loads(slide_packets_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(slide_packets, dict):
        return None
    if str(slide_packets.get("surface_kind") or "").strip() != "slide_deck":
        return None
    return slide_packets


def _customer_pack_artifact_url(draft_id: str, storage_relpath: str) -> str:
    parts = [quote(part) for part in str(storage_relpath or "").replace("\\", "/").split("/") if str(part).strip()]
    relative = "/".join(parts)
    return f"{CUSTOMER_PACK_VIEWER_PREFIX}{draft_id}/artifacts/{relative}" if relative else ""


def _customer_pack_slide_asset_allowlist(root_dir: Path, draft_id: str) -> set[str]:
    payload = load_customer_pack_book(root_dir, draft_id)
    if payload is None or str(payload.get("surface_kind") or "").strip() != "slide_deck":
        return set()
    slide_packets = _load_customer_pack_slide_packets(payload)
    if slide_packets is None:
        return set()
    allowed: set[str] = set()
    for asset in slide_packets.get("embedded_assets") or []:
        if not isinstance(asset, dict):
            continue
        relpath = str(asset.get("storage_relpath") or "").replace("\\", "/").strip().lstrip("/")
        if relpath:
            allowed.add(relpath)
    for asset in slide_packets.get("rendered_slide_assets") or []:
        if not isinstance(asset, dict):
            continue
        relpath = str(asset.get("storage_relpath") or "").replace("\\", "/").strip().lstrip("/")
        if relpath:
            allowed.add(relpath)
    for slide in slide_packets.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        preview_asset = dict(slide.get("rendered_slide_asset") or {})
        relpath = str(preview_asset.get("storage_relpath") or "").replace("\\", "/").strip().lstrip("/")
        if relpath:
            allowed.add(relpath)
    return allowed


def resolve_customer_pack_asset_path(root_dir: Path, request_path: str) -> Path | None:
    parsed = urlparse(str(request_path or "").strip())
    path = parsed.path.strip()
    if not path.startswith(CUSTOMER_PACK_VIEWER_PREFIX):
        return None
    remainder = path.removeprefix(CUSTOMER_PACK_VIEWER_PREFIX).strip("/")
    parts = [part for part in remainder.split("/") if part]
    if len(parts) < 4 or parts[1] != "artifacts":
        return None
    draft_id = str(parts[0]).strip()
    if not draft_id or not bool(load_customer_pack_read_boundary(root_dir, draft_id).get("read_allowed", False)):
        return None
    relative_path = "/".join(parts[2:]).strip().lstrip("/")
    if not relative_path:
        return None
    allowed_relpaths = _customer_pack_slide_asset_allowlist(root_dir, draft_id)
    if relative_path.replace("\\", "/") not in allowed_relpaths:
        return None
    books_root = load_settings(root_dir).customer_pack_books_dir.resolve()
    asset_path = (books_root / relative_path).resolve()
    if not asset_path.is_file() or (asset_path != books_root and books_root not in asset_path.parents):
        return None
    return asset_path


def _slide_bbox_style(bbox: dict[str, Any], slide_size: dict[str, Any], *, z_index: int) -> str:
    width = max(float(slide_size.get("width") or 0.0), 1.0)
    height = max(float(slide_size.get("height") or 0.0), 1.0)
    left = max(0.0, min(100.0, (float(bbox.get("left") or 0.0) / width) * 100.0))
    top = max(0.0, min(100.0, (float(bbox.get("top") or 0.0) / height) * 100.0))
    box_width = max(3.0, min(100.0, (float(bbox.get("width") or width) / width) * 100.0))
    box_height = max(3.0, min(100.0, (float(bbox.get("height") or height) / height) * 100.0))
    return (
        f"left:{left:.3f}%;top:{top:.3f}%;width:{box_width:.3f}%;height:{box_height:.3f}%;"
        f"z-index:{z_index};"
    )


def _render_slide_text_node(block: dict[str, Any], slide_size: dict[str, Any]) -> str:
    text = str(block.get("text") or "").strip()
    if not text:
        return ""
    font_size = max(12.0, min(34.0, float(block.get("font_size") or 15.0) * 0.9))
    title_class = " customer-slide-node-title" if bool(block.get("is_title_candidate")) else ""
    return """
    <div class="customer-slide-node customer-slide-node-text{title_class}" style="{style} font-size:{font_size:.1f}px;">
      <div class="customer-slide-node-text-body">{text}</div>
    </div>
    """.format(
        title_class=title_class,
        style=_slide_bbox_style(dict(block.get("bbox") or {}), slide_size, z_index=3),
        font_size=font_size,
        text=html.escape(text).replace("\n", "<br/>"),
    ).strip()


def _render_slide_table_node(block: dict[str, Any], slide_size: dict[str, Any]) -> str:
    rows = [row for row in (block.get("rows") or []) if isinstance(row, list)]
    if not rows:
        body_text = str(block.get("body_text") or block.get("title") or "").strip()
        if not body_text:
            return ""
        return """
        <div class="customer-slide-node customer-slide-node-table" style="{style}">
          <div class="customer-slide-node-table-fallback">{text}</div>
        </div>
        """.format(
            style=_slide_bbox_style(dict(block.get("bbox") or {}), slide_size, z_index=2),
            text=html.escape(body_text).replace("\n", "<br/>"),
        ).strip()
    row_html = "".join(
        "<tr>{cells}</tr>".format(
            cells="".join(
                "<td>{}</td>".format(html.escape(str(cell or "")))
                for cell in row
            )
        )
        for row in rows
    )
    return """
    <div class="customer-slide-node customer-slide-node-table" style="{style}">
      <div class="customer-slide-node-table-wrap">
        <table class="customer-slide-node-table-grid">{rows}</table>
      </div>
    </div>
    """.format(
        style=_slide_bbox_style(dict(block.get("bbox") or {}), slide_size, z_index=2),
        rows=row_html,
    ).strip()


def _render_slide_asset_node(asset: dict[str, Any], slide_size: dict[str, Any], *, draft_id: str) -> str:
    asset_url = _customer_pack_artifact_url(draft_id, str(asset.get("storage_relpath") or "").strip())
    if not asset_url:
        return ""
    return """
    <figure class="customer-slide-node customer-slide-node-image" style="{style}">
      <img src="{src}" alt="{alt}" loading="lazy" />
    </figure>
    """.format(
        style=_slide_bbox_style(dict(asset.get("bbox") or {}), slide_size, z_index=1),
        src=html.escape(asset_url, quote=True),
        alt=html.escape(str(asset.get("alt") or asset.get("asset_name") or "slide image")),
    ).strip()


def _render_slide_preview_node(asset: dict[str, Any], *, draft_id: str) -> str:
    asset_url = _customer_pack_artifact_url(draft_id, str(asset.get("storage_relpath") or "").strip())
    if not asset_url:
        return ""
    return """
    <figure class="customer-slide-preview">
      <img src="{src}" alt="{alt}" loading="lazy" />
    </figure>
    """.format(
        src=html.escape(asset_url, quote=True),
        alt=html.escape(str(asset.get("alt") or asset.get("asset_name") or "slide preview")),
    ).strip()


def _render_slide_preview_missing_node(*, title: str) -> str:
    return """
    <div class="customer-slide-preview-missing" role="status" aria-live="polite">
      <div class="customer-slide-preview-missing-title">원본 슬라이드 preview 미준비</div>
      <div class="customer-slide-preview-missing-copy">{title} 슬라이드는 preview asset이 준비된 뒤 원본 그대로 표시됩니다.</div>
    </div>
    """.format(
        title=html.escape(title),
    ).strip()


def _render_customer_pack_slide_cards(
    slides: list[dict[str, Any]],
    *,
    draft_id: str,
    document_title: str,
    target_anchor: str,
    embedded: bool,
    page_mode: str,
) -> list[str]:
    cards: list[str] = []
    resolved_page_mode = _resolve_page_mode(page_mode)
    show_card_header = resolved_page_mode == "multi"
    safe_document_title = str(document_title or "").strip()
    for slide in slides:
        slide_anchor = str(slide.get("slide_anchor") or "").strip()
        title = str(slide.get("title") or slide_anchor or "Slide").strip() or "Slide"
        matched_heading = str(slide.get("matched_section_heading") or "").strip()
        slide_role = str(slide.get("slide_role") or "content").strip() or "content"
        slide_size = dict(slide.get("slide_size") or {})
        is_target = bool(target_anchor) and slide_anchor == target_anchor
        rendered_slide_asset = dict(slide.get("rendered_slide_asset") or {})
        preview_node = _render_slide_preview_node(rendered_slide_asset, draft_id=draft_id) if rendered_slide_asset else ""
        title_nodes = [
            _render_slide_text_node(dict(block), slide_size)
            for block in (slide.get("text_blocks") or [])
            if isinstance(block, dict) and bool(block.get("is_title_candidate"))
        ]
        body_nodes = [
            _render_slide_asset_node(dict(asset), slide_size, draft_id=draft_id)
            for asset in (slide.get("embedded_assets") or [])
            if isinstance(asset, dict) and str(asset.get("asset_kind") or "").strip() == "image"
        ]
        body_nodes.extend(
            _render_slide_table_node(dict(block), slide_size)
            for block in (slide.get("table_blocks") or [])
            if isinstance(block, dict)
        )
        body_nodes.extend(
            _render_slide_text_node(dict(block), slide_size)
            for block in (slide.get("text_blocks") or [])
            if isinstance(block, dict) and not bool(block.get("is_title_candidate"))
        )
        if preview_node:
            title_nodes = []
            body_nodes = [preview_node]
        else:
            title_nodes = []
            body_nodes = [_render_slide_preview_missing_node(title=title)]
        body_nodes = [node for node in body_nodes if node]
        notes_text = str(slide.get("notes_text") or "").strip()
        meta_parts = [f"Slide {int(slide.get('ordinal') or 0)}"]
        if matched_heading and matched_heading != title:
            meta_parts.append(matched_heading)
        elif slide_role and slide_role != "content":
            meta_parts.append(slide_role.replace("_", " "))
        canvas_ratio = max(float(slide_size.get("width") or 16.0), 1.0) / max(float(slide_size.get("height") or 9.0), 1.0)
        subject_block = ""
        if matched_heading and matched_heading != title:
            subject_block = '<div class="customer-slide-card-subject">{}</div>'.format(html.escape(matched_heading))
        card_header = """
          <div class="customer-slide-card-header">
            <div class="customer-slide-card-document">{document_title}</div>
            <div class="customer-slide-card-meta">{meta}</div>
            <div class="customer-slide-card-title">{title}</div>
            {subject_block}
          </div>
        """.format(
            document_title=html.escape(safe_document_title),
            meta=html.escape(" · ".join(part for part in meta_parts if part)),
            title=html.escape(title),
            subject_block=subject_block,
        ).strip()
        section_class = "embedded-section" if embedded else "section-card"
        section_class = f"{section_class} customer-slide-card-section"
        if not show_card_header:
            section_class = f"{section_class} customer-slide-card-section-single"
        if is_target:
            section_class = f"{section_class} is-target"
        cards.append(
            """
            <section id="{anchor}" class="{section_class}">
              <div class="section-body">
                {card_header}
                <div class="customer-slide-stage" style="position:relative; aspect-ratio:{ratio:.6f}; background:linear-gradient(180deg, #ffffff 0%, #f6f8fb 100%); border:1px solid rgba(15,23,42,0.08); border-radius:18px; overflow:hidden; box-shadow:0 20px 50px rgba(15,23,42,0.08);">
                  {title_nodes}
                  {body_nodes}
                </div>
                {notes_block}
              </div>
            </section>
            """.format(
                anchor=html.escape(slide_anchor, quote=True),
                section_class=section_class,
                card_header=card_header if show_card_header else "",
                ratio=canvas_ratio,
                title_nodes="".join(title_nodes),
                body_nodes="".join(body_nodes),
                notes_block=(
                    """
                    <details class="customer-slide-notes">
                      <summary>발표자 노트</summary>
                      <div class="customer-slide-notes-body">{notes}</div>
                    </details>
                    """.format(notes=html.escape(notes_text).replace("\n", "<br/>")).strip()
                    if notes_text
                    else ""
                ),
            ).strip()
        )
    return cards


def _render_customer_pack_slide_toolbar_chrome(
    canonical_book: dict[str, Any],
    *,
    all_slides: list[dict[str, Any]],
    visible_slides: list[dict[str, Any]],
    page_mode: str,
) -> str:
    resolved_page_mode = _resolve_page_mode(page_mode)
    mode_label = _customer_pack_slide_mode_label(page_mode)
    title = str(canonical_book.get("title") or canonical_book.get("draft_id") or "Customer Slide Deck").strip()
    family_label = str(canonical_book.get("family_label") or "Customer Slide Deck").strip() or "Customer Slide Deck"
    focus_slide = visible_slides[0] if resolved_page_mode == "single" and visible_slides else None
    if focus_slide is not None:
        focus_grid = """
        <div class="customer-slide-toolbar-focus-grid">
          <div class="customer-slide-toolbar-focus-item">
            <div class="customer-slide-toolbar-focus-label">슬라이드</div>
            <div class="customer-slide-toolbar-focus-value">{slide_number}</div>
          </div>
          <div class="customer-slide-toolbar-focus-item">
            <div class="customer-slide-toolbar-focus-label">주제</div>
            <div class="customer-slide-toolbar-focus-value">{slide_subject}</div>
          </div>
        </div>
        """.format(
            slide_number=html.escape(_customer_pack_slide_number_label(focus_slide, total_slides=len(all_slides))),
            slide_subject=html.escape(_customer_pack_slide_subject(focus_slide)),
        ).strip()
    else:
        focus_grid = """
        <div class="customer-slide-toolbar-focus-grid">
          <div class="customer-slide-toolbar-focus-item">
            <div class="customer-slide-toolbar-focus-label">모드</div>
            <div class="customer-slide-toolbar-focus-value">{mode_label}</div>
          </div>
          <div class="customer-slide-toolbar-focus-item">
            <div class="customer-slide-toolbar-focus-label">슬라이드</div>
            <div class="customer-slide-toolbar-focus-value">총 {slide_count}장</div>
          </div>
        </div>
        """.format(
            mode_label=html.escape(mode_label),
            slide_count=len(all_slides),
        ).strip()
    return """
    <div class="customer-slide-toolbar-chrome customer-slide-toolbar-chrome-{mode}">
      <div class="customer-slide-toolbar-meta">
        <span class="customer-slide-toolbar-eyebrow">{eyebrow}</span>
        <span class="meta-pill meta-pill-accent">{mode_label}</span>
        <span class="meta-pill">총 {slide_count}장</span>
      </div>
      <div class="customer-slide-toolbar-title">{title}</div>
      <div class="customer-slide-toolbar-focus">{focus_grid}</div>
    </div>
    """.format(
        mode=html.escape(resolved_page_mode, quote=True),
        eyebrow=html.escape(family_label),
        mode_label=html.escape(mode_label),
        slide_count=len(all_slides),
        title=html.escape(title),
        focus_grid=focus_grid,
    ).strip()


def _render_customer_pack_save_to_wiki_dock(
    canonical_book: dict[str, Any],
    *,
    visible_slides: list[dict[str, Any]],
    total_slides: int,
    viewer_path: str,
    slide_navigation: list[dict[str, str]] | None = None,
) -> str:
    focus_slide = visible_slides[0] if visible_slides else {}
    focus_anchor = str(focus_slide.get("slide_anchor") or "").strip()
    focus_viewer_path = str(viewer_path or "").split("#", 1)[0]
    if focus_anchor:
        focus_viewer_path = f"{focus_viewer_path}#{focus_anchor}"
    focus_summary = (
        f"{_customer_pack_slide_number_label(focus_slide, total_slides=total_slides)} · {_customer_pack_slide_subject(focus_slide)}"
        if focus_slide
        else str(canonical_book.get("title") or "Customer Slide Deck")
    )
    navigation_links = "".join(
        """
        <a class="customer-save-wiki-dock-nav-link customer-save-wiki-dock-nav-link-{kind}" href="{href}" title="{title}">{label}</a>
        """.format(
            kind=html.escape("previous" if str(item.get("label") or "").strip() == "이전" else "next", quote=True),
            href=html.escape(str(item.get("href") or ""), quote=True),
            title=html.escape(str(item.get("title") or "")),
            label=html.escape(str(item.get("label") or "")),
        ).strip()
        for item in (slide_navigation or [])
        if str(item.get("href") or "").strip() and str(item.get("label") or "").strip()
    )
    return """
    <div class="customer-save-wiki-dock">
      <div class="customer-save-wiki-dock-copy">
        <div class="customer-save-wiki-dock-title">Save to Wiki</div>
        <div class="customer-save-wiki-dock-summary">{focus_summary}</div>
      </div>
      {navigation_block}
      <div class="customer-save-wiki-dock-meta">
        <span class="meta-pill meta-pill-accent">{book_title}</span>
      </div>
      {overlay_target}
    </div>
    """.format(
        focus_summary=html.escape(focus_summary),
        navigation_block=(
            """
            <div class="customer-save-wiki-dock-nav">
              {navigation_links}
            </div>
            """.format(navigation_links=navigation_links).strip()
            if navigation_links
            else ""
        ),
        book_title=html.escape(str(canonical_book.get("title") or canonical_book.get("draft_id") or "Customer Slide Deck")),
        overlay_target=_render_page_overlay_toolbar(
            target_kind="book",
            target_ref=f"book:{str(canonical_book.get('book_slug') or canonical_book.get('draft_id') or '')}",
            title=str(canonical_book.get("title") or canonical_book.get("draft_id") or "Customer Slide Deck"),
            book_slug=str(canonical_book.get("book_slug") or canonical_book.get("draft_id") or ""),
            anchor=focus_anchor,
            viewer_path=focus_viewer_path,
        ),
    ).strip()


def _customer_pack_slide_outline(slides: list[dict[str, Any]]) -> list[dict[str, str]]:
    outline: list[dict[str, str]] = []
    for slide in slides:
        anchor = str(slide.get("slide_anchor") or "").strip()
        title = str(slide.get("title") or anchor).strip()
        ordinal = int(slide.get("ordinal") or 0)
        matched_heading = str(slide.get("matched_section_heading") or "").strip()
        if not anchor or not title:
            continue
        path = f"Slide {ordinal}" if ordinal > 0 else "Slide"
        if matched_heading:
            path = f"{path} > {matched_heading}"
        outline.append(
            {
                "anchor": anchor,
                "heading": title,
                "path": path,
            }
        )
    return outline


def _customer_pack_slide_metrics(slides: list[dict[str, Any]]) -> list[str]:
    table_count = sum(len([block for block in (slide.get("table_blocks") or []) if isinstance(block, dict)]) for slide in slides)
    image_count = sum(len([asset for asset in (slide.get("embedded_assets") or []) if isinstance(asset, dict)]) for slide in slides)
    visual_only_count = sum(1 for slide in slides if str(slide.get("slide_role") or "").strip() == "visual_only")
    metrics = [f"슬라이드 {len(slides)}"]
    if image_count:
        metrics.append(f"이미지 {image_count}")
    if table_count:
        metrics.append(f"표 {table_count}")
    if visual_only_count:
        metrics.append(f"visual {visual_only_count}")
    return metrics[:5]


def _customer_pack_slide_navigation(
    slides: list[dict[str, Any]],
    *,
    target_anchor: str,
    viewer_path: str,
    page_mode: str,
) -> list[dict[str, str]]:
    if _resolve_page_mode(page_mode) != "single" or not slides:
        return []
    current_index = 0
    normalized_anchor = str(target_anchor or "").strip()
    if normalized_anchor:
        for index, slide in enumerate(slides):
            if str(slide.get("slide_anchor") or "").strip() == normalized_anchor:
                current_index = index
                break
    base_viewer_path = str(viewer_path or "").split("#", 1)[0]
    navigation: list[dict[str, str]] = []
    if current_index > 0:
        previous_slide = slides[current_index - 1]
        previous_anchor = str(previous_slide.get("slide_anchor") or "").strip()
        if previous_anchor:
            navigation.append(
                {
                    "label": "이전",
                    "href": f"{base_viewer_path}#{previous_anchor}",
                    "title": str(previous_slide.get("title") or previous_anchor).strip() or previous_anchor,
                }
            )
    if current_index + 1 < len(slides):
        next_slide = slides[current_index + 1]
        next_anchor = str(next_slide.get("slide_anchor") or "").strip()
        if next_anchor:
            navigation.append(
                {
                    "label": "다음",
                    "href": f"{base_viewer_path}#{next_anchor}",
                    "title": str(next_slide.get("title") or next_anchor).strip() or next_anchor,
                }
            )
    return navigation


def _visible_customer_pack_slides(
    slides: list[dict[str, Any]],
    *,
    target_anchor: str,
    page_mode: str,
) -> list[dict[str, Any]]:
    if _resolve_page_mode(page_mode) == "multi":
        return slides
    normalized_anchor = str(target_anchor or "").strip()
    if normalized_anchor:
        for slide in slides:
            if str(slide.get("slide_anchor") or "").strip() == normalized_anchor:
                return [slide]
    return slides[:1]


def _merge_customer_pack_surface_truth(
    payload: dict[str, Any],
    corpus_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    manifest = dict(corpus_manifest or {})
    grade_gate = dict(manifest.get("grade_gate") or payload.get("grade_gate") or {})
    citation_gate = dict(grade_gate.get("citation_gate") or {})
    retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})

    def _value(key: str, fallback: Any = "") -> Any:
        if key in manifest:
            return manifest.get(key)
        if key in payload:
            return payload.get(key)
        return fallback

    payload["quality_status"] = str(_value("quality_status", "") or "")
    payload["quality_score"] = int(_value("quality_score", 0) or 0)
    payload["quality_flags"] = list(_value("quality_flags", []) or [])
    payload["quality_summary"] = str(_value("quality_summary", "") or "")
    payload["shared_grade"] = str(_value("shared_grade", "blocked") or "blocked")
    payload["grade_gate"] = grade_gate
    payload["citation_landing_status"] = str(
        _value("citation_landing_status", citation_gate.get("status") or "missing") or "missing"
    )
    payload["retrieval_ready"] = bool(_value("retrieval_ready", retrieval_gate.get("ready")))
    payload["read_ready"] = bool(_value("read_ready", promotion_gate.get("read_ready")))
    payload["publish_ready"] = bool(_value("publish_ready", promotion_gate.get("publish_ready")))
    return payload


def load_customer_pack_book(root_dir: Path, draft_id: str) -> dict[str, Any] | None:
    resolved_draft_id = draft_id
    asset_slug = ""
    if "::" in draft_id:
        resolved_draft_id, asset_slug = draft_id.split("::", 1)
    boundary = load_customer_pack_read_boundary(root_dir, resolved_draft_id)
    if not bool(boundary.get("read_allowed", False)):
        return None
    store = CustomerPackDraftStore(root_dir)
    record = store.get(draft_id)
    if record is None and resolved_draft_id != draft_id:
        record = store.get(resolved_draft_id)
    if record is None or not record.canonical_book_path.strip():
        return None
    canonical_path = (
        load_settings(root_dir).customer_pack_books_dir / f"{asset_slug}.json"
        if asset_slug
        else Path(record.canonical_book_path)
    )
    if not canonical_path.exists():
        return None
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    payload["draft_id"] = record.draft_id
    payload["target_viewer_path"] = (
        f"{CUSTOMER_PACK_VIEWER_PREFIX}{record.draft_id}/assets/{asset_slug}/index.html"
        if asset_slug
        else f"{CUSTOMER_PACK_VIEWER_PREFIX}{record.draft_id}/index.html"
    )
    payload["target_anchor"] = payload.get("target_anchor") or ""
    payload["source_origin_url"] = f"/api/customer-packs/captured?draft_id={record.draft_id}"
    payload.setdefault("source_collection", record.plan.source_collection)
    payload.setdefault("pack_id", record.plan.pack_id)
    payload.setdefault("pack_label", record.plan.pack_label)
    payload.setdefault("inferred_product", record.plan.inferred_product)
    payload.setdefault("inferred_version", record.plan.inferred_version)
    boundary_payload = _customer_pack_boundary_payload(record)
    existing_evidence = payload.get("customer_pack_evidence")
    merged_evidence: dict[str, Any] = {}
    if isinstance(existing_evidence, dict):
        merged_evidence.update(existing_evidence)
    payload.update(boundary_payload)
    merged_evidence.update(boundary_payload.get("customer_pack_evidence") or {})
    if merged_evidence:
        payload["customer_pack_evidence"] = merged_evidence
        if str(merged_evidence.get("primary_parse_strategy") or "").strip():
            payload["primary_parse_strategy"] = str(merged_evidence["primary_parse_strategy"])
    corpus_manifest_path = Path(str(getattr(record, "private_corpus_manifest_path", "") or "").strip())
    corpus_manifest = (
        json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
        if corpus_manifest_path.as_posix() not in {"", "."} and corpus_manifest_path.exists()
        else None
    )
    return _merge_customer_pack_surface_truth(payload, corpus_manifest)


def internal_customer_pack_viewer_html(root_dir: Path, viewer_path: str, *, page_mode: str = "single") -> str | None:
    parsed = parse_customer_pack_viewer_path(viewer_path)
    if parsed is None:
        return None

    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    draft_id, target_anchor = parsed
    canonical_book = load_customer_pack_book(root_dir, draft_id)
    if canonical_book is None:
        return None

    slide_packets = (
        _load_customer_pack_slide_packets(canonical_book)
        if str(canonical_book.get("surface_kind") or "").strip() == "slide_deck"
        else None
    )
    if slide_packets is not None:
        all_slides = [dict(slide) for slide in (slide_packets.get("slides") or []) if isinstance(slide, dict)]
        if not all_slides:
            return None
        visible_slides = _visible_customer_pack_slides(
            all_slides,
            target_anchor=target_anchor,
            page_mode=page_mode,
        )
        cards = _render_customer_pack_slide_cards(
            visible_slides,
            draft_id=str(canonical_book.get("draft_id") or draft_id).split("::", 1)[0],
            document_title=str(canonical_book.get("title") or draft_id),
            target_anchor=target_anchor,
            embedded=embedded,
            page_mode=page_mode,
        )
        family_label = str(canonical_book.get("family_label") or "").strip()
        viewer_target = str(canonical_book.get("target_viewer_path") or f"{CUSTOMER_PACK_VIEWER_PREFIX}{draft_id}/index.html")
        toolbar_chrome = _render_customer_pack_slide_toolbar_chrome(
            canonical_book,
            all_slides=all_slides,
            visible_slides=visible_slides,
            page_mode=page_mode,
        )
        slide_navigation = _customer_pack_slide_navigation(
            all_slides,
            target_anchor=target_anchor,
            viewer_path=viewer_target,
            page_mode=page_mode,
        )
        save_to_wiki_dock = _render_customer_pack_save_to_wiki_dock(
            canonical_book,
            visible_slides=visible_slides,
            total_slides=len(all_slides),
            viewer_path=viewer_target,
            slide_navigation=slide_navigation,
        )
        return _render_study_viewer_html(
            title=str(canonical_book.get("title") or draft_id),
            source_url=str(canonical_book.get("source_origin_url") or canonical_book.get("source_uri") or ""),
            cards=cards,
            supplementary_blocks=[],
            section_count=len(all_slides),
            eyebrow=family_label or "Customer Slide Deck",
            summary="",
            embedded=embedded,
            section_outline=[],
            section_navigation=[],
            section_metrics=_customer_pack_slide_metrics(all_slides),
            viewer_header_chrome=toolbar_chrome,
            viewer_footer_chrome=save_to_wiki_dock,
            hero_mode="hidden",
        )

    sections = list(canonical_book.get("sections") or [])
    if not sections:
        return None
    cards = _build_study_section_cards(sections, target_anchor=target_anchor, embedded=embedded)
    family_label = str(canonical_book.get("family_label") or "").strip()
    family_summary = str(canonical_book.get("family_summary") or "").strip()
    derived_asset_count = int(canonical_book.get("derived_asset_count") or 0)
    if family_label:
        base_summary = family_summary or _default_customer_pack_summary(canonical_book)
    else:
        base_summary = _default_customer_pack_summary(canonical_book)
        if derived_asset_count > 0:
            base_summary = (
                f"{base_summary} 이 초안에서 {derived_asset_count}개의 파생 플레이북 자산이 추가로 생성되었습니다."
            )
    quality_summary = str(canonical_book.get("quality_summary") or "").strip()
    summary = f"{base_summary} {quality_summary}".strip() if quality_summary else base_summary
    shared_grade = str(canonical_book.get("shared_grade") or "blocked").strip() or "blocked"
    grade_gate = dict(canonical_book.get("grade_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})
    citation_gate = dict(grade_gate.get("citation_gate") or {})
    retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
    citation_status = str(
        canonical_book.get("citation_landing_status")
        or citation_gate.get("status")
        or "missing"
    ).strip() or "missing"
    if shared_grade not in {"gold", "silver"}:
        summary = f"{summary} 현재 승급선은 {shared_grade} 상태입니다."
    if not bool(promotion_gate.get("read_ready")):
        summary = f"{summary} citation landing 또는 retrieval gate가 아직 read-ready가 아닙니다.".strip()
    runtime_truth_label = str(canonical_book.get("runtime_truth_label") or "Customer Source-First Pack").strip()
    approval_state = str(canonical_book.get("approval_state") or "unreviewed").strip()
    publication_state = str(canonical_book.get("publication_state") or "draft").strip()
    source_lane = str(canonical_book.get("source_lane") or "customer_source_first_pack").strip()
    parser_backend = str(canonical_book.get("parser_backend") or "").strip()
    evidence_badges = [
        f"grade: {shared_grade}",
        f"citation: {citation_status}",
        f"retrieval: {'ready' if retrieval_gate.get('ready') else 'pending'}",
        f"read: {'ready' if promotion_gate.get('read_ready') else 'blocked'}",
        f"approval: {approval_state}",
        f"publication: {publication_state}",
    ]
    if parser_backend:
        evidence_badges.append(f"parser: {parser_backend}")
    if source_lane and source_lane != "customer_source_first_pack":
        evidence_badges.append(f"lane: {source_lane}")
    supplementary_blocks = [
        """
        <section class="wiki-parent-card">
          <div class="wiki-parent-eyebrow">Pack Runtime Truth</div>
          <div class="viewer-truth-topline">
            <span class="viewer-truth-badge">{badge}</span>
            <a class="viewer-truth-link" href="{source_url}" target="_blank" rel="noreferrer">원본 캡처 열기</a>
          </div>
          <div class="viewer-truth-title">{title}</div>
          <p>Customer pack runtime evidence</p>
          <div class="wiki-entity-list">{badges}</div>
        </section>
        """.format(
            source_url=html.escape(
                str(canonical_book.get("source_origin_url") or canonical_book.get("source_uri") or ""),
                quote=True,
            ),
            badge=html.escape(str(canonical_book.get("boundary_badge") or "Private Pack Runtime")),
            title=html.escape(runtime_truth_label),
            badges="".join(
                f'<span class="meta-pill">{html.escape(item)}</span>'
                for item in evidence_badges
                if item.strip()
            ),
        ).strip()
    ]
    return _render_study_viewer_html(
        title=str(canonical_book.get("title") or draft_id),
        source_url=str(canonical_book.get("source_origin_url") or canonical_book.get("source_uri") or ""),
        cards=cards,
        supplementary_blocks=supplementary_blocks,
        section_count=len(sections),
        eyebrow=family_label or "Customer Playbook Draft",
        summary=summary,
        embedded=embedded,
        section_outline=_build_section_outline(sections),
        section_metrics=_build_section_metrics(sections),
        page_overlay_toolbar=_render_page_overlay_toolbar(
            target_kind="book",
            target_ref=f"book:{str(canonical_book.get('book_slug') or draft_id)}",
            title=str(canonical_book.get("title") or draft_id),
            book_slug=str(canonical_book.get("book_slug") or draft_id),
            viewer_path=str(canonical_book.get("target_viewer_path") or f"{CUSTOMER_PACK_VIEWER_PREFIX}{draft_id}/index.html"),
        ),
    )


def list_customer_pack_drafts(root_dir: Path) -> dict[str, Any]:
    drafts: list[dict[str, Any]] = []
    store = CustomerPackDraftStore(root_dir)
    for record in store.list():
        summary = record.to_summary()
        if record.canonical_book_path.strip():
            payload = load_customer_pack_book(root_dir, record.draft_id)
            if payload is not None:
                summary["quality_status"] = payload.get("quality_status")
                summary["quality_score"] = payload.get("quality_score")
                summary["quality_summary"] = payload.get("quality_summary")
                summary["quality_flags"] = payload.get("quality_flags")
                summary["shared_grade"] = payload.get("shared_grade")
                summary["grade_gate"] = payload.get("grade_gate")
                summary["citation_landing_status"] = payload.get("citation_landing_status")
                summary["retrieval_ready"] = payload.get("retrieval_ready")
                summary["read_ready"] = payload.get("read_ready")
                summary["publish_ready"] = payload.get("publish_ready")
                summary["degraded_pdf"] = payload.get("degraded_pdf")
                summary["degraded_reason"] = payload.get("degraded_reason")
                summary["fallback_used"] = payload.get("fallback_used")
                summary["fallback_backend"] = payload.get("fallback_backend")
                summary["fallback_status"] = payload.get("fallback_status")
                summary["fallback_reason"] = payload.get("fallback_reason")
                summary["playable_asset_count"] = payload.get("playable_asset_count", 1)
                summary["derived_asset_count"] = payload.get("derived_asset_count", 0)
                summary["derived_assets"] = payload.get("derived_assets", [])
                summary["surface_kind"] = payload.get("surface_kind")
                summary["source_unit_kind"] = payload.get("source_unit_kind")
                summary["source_unit_count"] = payload.get("source_unit_count")
                summary["slide_packet_count"] = payload.get("slide_packet_count")
                summary["slide_asset_count"] = payload.get("slide_asset_count")
        drafts.append(summary)
    return {"drafts": drafts}


__all__ = [
    "internal_customer_pack_viewer_html",
    "list_customer_pack_drafts",
    "load_customer_pack_book",
    "parse_customer_pack_viewer_path",
    "resolve_customer_pack_asset_path",
]
