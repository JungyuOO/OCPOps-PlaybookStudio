"""customer-pack viewer and listing helpers."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.service import evaluate_canonical_book_quality

from .presenters import _default_customer_pack_summary
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


def load_customer_pack_book(root_dir: Path, draft_id: str) -> dict[str, Any] | None:
    resolved_draft_id = draft_id
    asset_slug = ""
    if "::" in draft_id:
        resolved_draft_id, asset_slug = draft_id.split("::", 1)
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
    payload.update(_customer_pack_boundary_payload(record))
    payload.update(evaluate_canonical_book_quality(payload))
    return payload


def internal_customer_pack_viewer_html(root_dir: Path, viewer_path: str) -> str | None:
    parsed = parse_customer_pack_viewer_path(viewer_path)
    if parsed is None:
        return None

    request = urlparse((viewer_path or "").strip())
    embedded = "embed=1" in request.query
    draft_id, target_anchor = parsed
    canonical_book = load_customer_pack_book(root_dir, draft_id)
    if canonical_book is None:
        return None

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
    if str(canonical_book.get("quality_status") or "ready") != "ready":
        summary = f"{summary} 이 자산은 아직 review needed 상태입니다."
    runtime_truth_label = str(canonical_book.get("runtime_truth_label") or "Customer Source-First Pack").strip()
    approval_state = str(canonical_book.get("approval_state") or "unreviewed").strip()
    publication_state = str(canonical_book.get("publication_state") or "draft").strip()
    source_lane = str(canonical_book.get("source_lane") or "customer_source_first_pack").strip()
    parser_backend = str(canonical_book.get("parser_backend") or "").strip()
    evidence_badges = [
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
                summary["degraded_pdf"] = payload.get("degraded_pdf")
                summary["degraded_reason"] = payload.get("degraded_reason")
                summary["fallback_used"] = payload.get("fallback_used")
                summary["fallback_backend"] = payload.get("fallback_backend")
                summary["fallback_status"] = payload.get("fallback_status")
                summary["fallback_reason"] = payload.get("fallback_reason")
                summary["playable_asset_count"] = payload.get("playable_asset_count", 1)
                summary["derived_asset_count"] = payload.get("derived_asset_count", 0)
                summary["derived_assets"] = payload.get("derived_assets", [])
        drafts.append(summary)
    return {"drafts": drafts}


__all__ = [
    "internal_customer_pack_viewer_html",
    "list_customer_pack_drafts",
    "load_customer_pack_book",
    "parse_customer_pack_viewer_path",
]
