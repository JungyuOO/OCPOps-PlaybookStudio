from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from play_book_studio.app.customer_pack_read_boundary import (
    customer_pack_draft_id_from_viewer_path,
    sanitize_customer_pack_source_meta_payload,
)
from play_book_studio.app.presenters import (
    _core_pack_payload,
    _customer_pack_meta_for_viewer_path,
    _humanize_book_slug,
    _manifest_entry_for_book,
    _resolve_normalized_row_for_viewer_path,
)
from play_book_studio.app.source_books import (
    _entity_hubs,
    _figure_asset_by_name,
    _figure_section_match,
    internal_active_runtime_markdown_viewer_html as _internal_active_runtime_markdown_viewer_html,
    internal_buyer_packet_viewer_html as _internal_buyer_packet_viewer_html,
    internal_entity_hub_viewer_html as _internal_entity_hub_viewer_html,
    internal_figure_viewer_html as _internal_figure_viewer_html,
    internal_viewer_html as _internal_viewer_html,
    parse_active_runtime_markdown_viewer_path,
    parse_entity_hub_viewer_path,
    parse_figure_viewer_path,
)
from play_book_studio.app.source_books_customer_pack import (
    internal_customer_pack_viewer_html as _internal_customer_pack_viewer_html,
)
from play_book_studio.app.viewer_paths import _viewer_path_to_local_html
from play_book_studio.app.viewers import _parse_viewer_path
from play_book_studio.config.settings import load_settings
from play_book_studio.source_provenance import source_provenance_payload

from .runtime_truth import official_runtime_truth_payload
from .server_routes_customer_pack import (
    _customer_pack_read_allowed,
    _send_customer_pack_read_blocked,
)

_BODY_RE = re.compile(r"<body(?P<attrs>[^>]*)>(?P<body>.*)</body>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>(?P<css>.*?)</style>", re.IGNORECASE | re.DOTALL)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_BODY_CLASS_RE = re.compile(r'class=(["\'])(?P<value>.*?)\1', re.IGNORECASE | re.DOTALL)
_RESOURCE_ATTR_RE = re.compile(r'(?P<attr>\b(?:src|href))=(?P<quote>["\'])(?P<value>.*?)(?P=quote)', re.IGNORECASE | re.DOTALL)
_DOCS_DIRECTORY_VIEWER_PATH_RE = re.compile(r"^/docs/ocp/[^/]+/[^/]+/[^/]+$")
_ACTIVE_RUNTIME_DIRECTORY_VIEWER_PATH_RE = re.compile(r"^/playbooks/wiki-runtime/active/[^/]+$")
_ENTITY_DIRECTORY_VIEWER_PATH_RE = re.compile(r"^/wiki/entities/[^/]+$")
_FIGURE_DIRECTORY_VIEWER_PATH_RE = re.compile(r"^/wiki/figures/[^/]+/[^/]+$")


def _scope_viewer_style(style_text: str) -> str:
    scoped = str(style_text or "")
    scoped = scoped.replace(":root", ".viewer-root")
    scoped = re.sub(r"(?<![-\w])body\.is-embedded(?![-\w])", ".viewer-root.is-embedded", scoped)
    return re.sub(r"(?<![-\w])body(?![-\w])", ".viewer-root", scoped)


def _canonicalize_viewer_path(viewer_path: str) -> str:
    raw = str(viewer_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path.strip()
    if not path:
        return raw
    normalized_path = path if path == "/" else path.rstrip("/")
    if (
        normalized_path
        and not normalized_path.endswith("/index.html")
        and (
            _DOCS_DIRECTORY_VIEWER_PATH_RE.fullmatch(normalized_path)
            or _ACTIVE_RUNTIME_DIRECTORY_VIEWER_PATH_RE.fullmatch(normalized_path)
            or _ENTITY_DIRECTORY_VIEWER_PATH_RE.fullmatch(normalized_path)
            or _FIGURE_DIRECTORY_VIEWER_PATH_RE.fullmatch(normalized_path)
        )
    ):
        normalized_path = f"{normalized_path}/index.html"
    if normalized_path == path:
        return raw
    return urlunparse(parsed._replace(path=normalized_path))


def _viewer_html_for_path(root_dir: Path, viewer_path: str, *, page_mode: str = "single") -> str | None:
    viewer_path = _canonicalize_viewer_path(viewer_path)
    internal_html = (
        _internal_buyer_packet_viewer_html(root_dir, viewer_path)
        or _internal_customer_pack_viewer_html(root_dir, viewer_path)
        or _internal_active_runtime_markdown_viewer_html(root_dir, viewer_path, page_mode=page_mode)
        or _internal_entity_hub_viewer_html(root_dir, viewer_path)
        or _internal_figure_viewer_html(root_dir, viewer_path)
        or _internal_viewer_html(root_dir, viewer_path, page_mode=page_mode)
    )
    if internal_html is not None:
        return internal_html
    local_html = _viewer_path_to_local_html(root_dir, viewer_path)
    if local_html is not None:
        return local_html.read_text(encoding="utf-8")
    return None


def resolve_viewer_html(root_dir: Path, viewer_path: str, *, page_mode: str = "single") -> str | None:
    viewer_path = _canonicalize_viewer_path(viewer_path)
    customer_pack_draft_id = customer_pack_draft_id_from_viewer_path(viewer_path)
    if customer_pack_draft_id and not _customer_pack_read_allowed(root_dir, customer_pack_draft_id):
        return None
    return _viewer_html_for_path(root_dir, viewer_path, page_mode=page_mode)


def _normalize_viewer_resource_urls(html_text: str, viewer_path: str) -> str:
    base = f"http://runtime.local{viewer_path}"

    def _replace(match: re.Match[str]) -> str:
        value = str(match.group("value") or "").strip()
        if not value or value.startswith("#") or re.match(r"^(?:data:|blob:|mailto:|tel:|javascript:)", value, re.IGNORECASE):
            return match.group(0)
        absolute = urljoin(base, value)
        normalized = absolute.replace("http://runtime.local", "", 1)
        return f'{match.group("attr")}={match.group("quote")}{normalized}{match.group("quote")}'

    return _RESOURCE_ATTR_RE.sub(_replace, html_text)


def _build_viewer_document_payload(html_text: str, viewer_path: str) -> dict[str, Any]:
    body_match = _BODY_RE.search(html_text)
    body_attrs = body_match.group("attrs") if body_match else ""
    body_html = body_match.group("body") if body_match else html_text
    class_match = _BODY_CLASS_RE.search(body_attrs)
    body_class_name = str(class_match.group("value") if class_match else "").strip()
    inline_styles = [
        _scope_viewer_style(match.group("css"))
        for match in _STYLE_RE.finditer(html_text)
        if str(match.group("css") or "").strip()
    ]
    normalized_body_html = _normalize_viewer_resource_urls(_SCRIPT_RE.sub("", body_html), viewer_path)
    return {
        "viewer_path": viewer_path,
        "body_class_name": body_class_name,
        "inline_styles": inline_styles,
        "html": normalized_body_html,
        "interaction_policy": {
            "code_copy": True,
            "code_wrap_toggle": True,
            "recent_position_tracking": True,
            "anchor_navigation": True,
        },
    }


def _official_runtime_source_meta(
    *,
    root_dir: Path,
    viewer_path: str,
    resolved_viewer_path: str,
    book_slug: str,
    anchor: str,
) -> dict[str, Any]:
    row, matched_exact = _resolve_normalized_row_for_viewer_path(root_dir, resolved_viewer_path)
    manifest_entry = _manifest_entry_for_book(root_dir, book_slug)
    settings = load_settings(root_dir)
    book_title = (
        str((row or {}).get("book_title") or "")
        or str(manifest_entry.get("title") or "")
        or _humanize_book_slug(book_slug)
    )
    section_path = [str(item) for item in ((row or {}).get("section_path") or []) if str(item).strip()]
    pack_label = str(manifest_entry.get("pack_label") or settings.active_pack.pack_label or "").strip()
    runtime_truth_label = f"{pack_label} Runtime" if pack_label else "Validated Pack Runtime"
    provenance = source_provenance_payload(manifest_entry)
    truth = official_runtime_truth_payload(settings=settings, manifest_entry=manifest_entry)
    return {
        "book_slug": book_slug,
        "book_title": book_title,
        "anchor": anchor,
        "section": str((row or {}).get("heading") or ""),
        "section_path": section_path,
        "section_path_label": " > ".join(section_path) if section_path else str((row or {}).get("heading") or ""),
        "source_url": str((row or {}).get("source_url") or manifest_entry.get("source_url") or ""),
        "viewer_path": viewer_path,
        "section_match_exact": matched_exact,
        "source_lane": str(truth.get("source_lane") or manifest_entry.get("source_lane") or ""),
        "approval_state": str(truth.get("approval_state") or ""),
        "publication_state": str(truth.get("publication_state") or "active"),
        "parser_backend": str(truth.get("parser_backend") or manifest_entry.get("parser_backend") or ""),
        "boundary_truth": str(truth.get("boundary_truth") or ""),
        "runtime_truth_label": str(truth.get("runtime_truth_label") or runtime_truth_label),
        "boundary_badge": str(truth.get("boundary_badge") or ""),
        "updated_at": str(manifest_entry.get("updated_at") or ""),
        "source_manifest_path": str(manifest_entry.get("source_manifest_path") or settings.source_manifest_path.resolve()),
        **provenance,
        **_core_pack_payload(version=settings.ocp_version, language=settings.docs_language),
    }


def _viewer_source_meta(root_dir: Path, viewer_path: str) -> dict[str, Any] | None:
    viewer_path = _canonicalize_viewer_path(viewer_path)
    customer_pack_meta = _customer_pack_meta_for_viewer_path(root_dir, viewer_path)
    if customer_pack_meta is not None:
        return customer_pack_meta
    parsed = _parse_viewer_path(viewer_path)
    if parsed is not None:
        book_slug, anchor = parsed
        return _official_runtime_source_meta(
            root_dir=root_dir,
            viewer_path=viewer_path,
            resolved_viewer_path=viewer_path,
            book_slug=book_slug,
            anchor=anchor,
        )
    active_book_slug = parse_active_runtime_markdown_viewer_path(viewer_path)
    if active_book_slug:
        anchor = viewer_path.split("#", 1)[1].strip() if "#" in viewer_path else ""
        settings = load_settings(root_dir)
        docs_viewer_path = f"/docs/ocp/{settings.ocp_version}/{settings.docs_language}/{active_book_slug}/index.html"
        if anchor:
            docs_viewer_path = f"{docs_viewer_path}#{anchor}"
        return _official_runtime_source_meta(
            root_dir=root_dir,
            viewer_path=viewer_path,
            resolved_viewer_path=docs_viewer_path,
            book_slug=active_book_slug,
            anchor=anchor,
        )
    entity_slug = parse_entity_hub_viewer_path(viewer_path)
    if entity_slug:
        entity = _entity_hubs().get(entity_slug)
        if entity is None:
            return None
        title = str(entity.get("title") or entity_slug).strip() or entity_slug
        return {
            "book_slug": entity_slug,
            "book_title": title,
            "anchor": "",
            "section": title,
            "section_path": [title],
            "section_path_label": title,
            "source_url": "",
            "viewer_path": viewer_path,
            "section_match_exact": True,
            "source_lane": "approved_wiki_runtime",
            "approval_state": "approved",
            "publication_state": "active",
            "parser_backend": "",
            "boundary_truth": "official_validated_runtime",
            "runtime_truth_label": "Validated Runtime Entity Hub",
            "boundary_badge": "Validated Runtime",
            **_core_pack_payload(),
        }
    figure_parsed = parse_figure_viewer_path(viewer_path)
    if figure_parsed is not None:
        slug, asset_name = figure_parsed
        asset = _figure_asset_by_name(slug, asset_name)
        if asset is None:
            return None
        settings = load_settings(root_dir)
        truth = official_runtime_truth_payload(settings=settings, manifest_entry=_manifest_entry_for_book(root_dir, slug))
        caption = str(asset.get("caption") or asset.get("alt") or asset_name).strip() or asset_name
        section_match = _figure_section_match(slug, asset_name) or {}
        section_path = [str(section_match.get("section_heading") or "").strip(), caption]
        section_path = [item for item in section_path if item]
        return {
            "book_slug": slug,
            "book_title": caption,
            "anchor": asset_name,
            "section": caption,
            "section_path": section_path,
            "section_path_label": " > ".join(section_path) if section_path else caption,
            "source_url": str(asset.get("asset_url") or "").strip(),
            "viewer_path": viewer_path,
            "section_match_exact": True,
            "source_lane": str(truth.get("source_lane") or ""),
            "approval_state": str(truth.get("approval_state") or ""),
            "publication_state": str(truth.get("publication_state") or "active"),
            "parser_backend": str(truth.get("parser_backend") or ""),
            "boundary_truth": str(truth.get("boundary_truth") or ""),
            "runtime_truth_label": "{} Figure".format(str(truth.get("boundary_badge") or "Runtime")),
            "boundary_badge": str(truth.get("boundary_badge") or ""),
            **_core_pack_payload(),
        }
    return None


def handle_source_meta(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    viewer_path = str((params.get("viewer_path") or [""])[0]).strip()
    if not viewer_path:
        handler._send_json({"error": "viewer_path가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    customer_pack_draft_id = customer_pack_draft_id_from_viewer_path(viewer_path)
    if customer_pack_draft_id and not _customer_pack_read_allowed(root_dir, customer_pack_draft_id):
        _send_customer_pack_read_blocked(handler)
        return
    payload = _viewer_source_meta(root_dir, viewer_path)
    if payload is None:
        handler._send_json({"error": "지원하지 않는 viewer_path입니다."}, HTTPStatus.BAD_REQUEST)
        return
    if customer_pack_draft_id:
        payload = sanitize_customer_pack_source_meta_payload(payload)
    handler._send_json(payload)


def handle_viewer_document(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    viewer_path = str((params.get("viewer_path") or [""])[0]).strip()
    page_mode = str((params.get("page_mode") or ["single"])[0]).strip().lower()
    if page_mode not in {"single", "multi"}:
        page_mode = "single"
    if not viewer_path:
        handler._send_json({"error": "viewer_path가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    viewer_path = _canonicalize_viewer_path(viewer_path)
    customer_pack_draft_id = customer_pack_draft_id_from_viewer_path(viewer_path)
    if customer_pack_draft_id and not _customer_pack_read_allowed(root_dir, customer_pack_draft_id):
        _send_customer_pack_read_blocked(handler)
        return
    html_text = _viewer_html_for_path(root_dir, viewer_path, page_mode=page_mode)
    if html_text is None:
        handler._send_json({"error": "viewer document를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(_build_viewer_document_payload(html_text, viewer_path))


def handle_runtime_figures(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    book_slug = str((params.get("book_slug") or [""])[0]).strip()
    limit_raw = str((params.get("limit") or ["3"])[0]).strip()
    if not book_slug:
        handler._send_json({"error": "book_slug가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    try:
        limit = max(1, min(12, int(limit_raw or "3")))
    except ValueError:
        limit = 3
    asset_path = root_dir / "data" / "wiki_relations" / "figure_assets.json"
    if not asset_path.exists():
        handler._send_json({"count": 0, "items": []})
        return
    payload = json.loads(asset_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    items = entries.get(book_slug) if isinstance(entries, dict) else []
    if not isinstance(items, list):
        items = []
    normalized: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "caption": str(item.get("caption") or item.get("alt") or "Figure"),
                "viewer_path": str(item.get("viewer_path") or "").strip(),
                "asset_url": str(item.get("asset_url") or "").strip(),
                "asset_kind": str(item.get("asset_kind") or "figure"),
                "diagram_type": str(item.get("diagram_type") or "").strip(),
                "section_hint": str(item.get("section_hint") or "").strip(),
            }
        )
    handler._send_json({"count": len(normalized), "items": normalized, "book_slug": book_slug})


__all__ = [
    "_build_viewer_document_payload",
    "_canonicalize_viewer_path",
    "_viewer_source_meta",
    "handle_runtime_figures",
    "handle_source_meta",
    "handle_viewer_document",
    "resolve_viewer_html",
]
