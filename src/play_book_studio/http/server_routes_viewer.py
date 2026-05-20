from __future__ import annotations

import base64
import html
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

from play_book_studio.http.customer_pack_read_boundary import (
    customer_pack_draft_id_from_viewer_path,
    sanitize_customer_pack_source_meta_payload,
)
from play_book_studio.http.course_api import course_viewer_html, course_viewer_source_meta
from play_book_studio.http.presenters import (
    _core_pack_payload,
    _customer_pack_meta_for_viewer_path,
    _humanize_book_slug,
    _manifest_entry_for_book,
    _resolve_normalized_row_for_viewer_path,
)
from play_book_studio.http.source_books import (
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
from play_book_studio.http.source_books_wiki_relations import _figure_assets, _figure_viewer_href
from play_book_studio.http.source_books_customer_pack import (
    internal_customer_pack_viewer_html as _internal_customer_pack_viewer_html,
)
from play_book_studio.http.viewer_paths import _viewer_path_to_local_html
from play_book_studio.http.viewers import _parse_viewer_path
from play_book_studio.http.viewer_blocks_rich import _render_code_block_html
from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.document_parsing import render_pdf_page_image_bytes
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
_UPLOAD_DOCUMENT_DIRECTORY_VIEWER_PATH_RE = re.compile(r"^/uploads/documents/[0-9a-fA-F-]{36}$")
_UPLOAD_DOCUMENT_VIEWER_PATH_RE = re.compile(r"^/uploads/documents/(?P<document_source_id>[0-9a-fA-F-]{36})(?:/index\.html)?$")


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
            or _UPLOAD_DOCUMENT_DIRECTORY_VIEWER_PATH_RE.fullmatch(normalized_path)
        )
    ):
        normalized_path = f"{normalized_path}/index.html"
    if normalized_path == path:
        return raw
    return urlunparse(parsed._replace(path=normalized_path))


def _owner_hash_from_handler(handler: Any) -> str:
    resolver = getattr(handler, "_session_owner", None)
    if not callable(resolver):
        return ""
    try:
        owner = resolver()
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(owner, "owner_hash", "") or "").strip()


def _markdownish_to_html(markdown: str, asset_sources: dict[str, dict[str, str]] | None = None) -> str:
    text = str(markdown or "").strip()
    if not text:
        return ""
    asset_sources = asset_sources or {}
    parts: list[str] = []
    in_code = False
    code_lines: list[str] = []
    code_language = "text"
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    table_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        body = "<br />".join(html.escape(line) for line in paragraph_lines if line.strip())
        if body:
            parts.append(f"<p>{body}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        parts.append("<ul>{}</ul>".format("".join(f"<li>{_render_basic_inline(item)}</li>" for item in list_items)))
        list_items.clear()

    def flush_code() -> None:
        nonlocal code_language
        if not code_lines:
            return
        raw_body = "\n".join(code_lines)
        parts.append(
            _render_code_block_html(
                raw_body,
                language=code_language or "text",
                copy_text=raw_body,
                wrap_hint=False,
                overflow_hint="toggle",
            )
        )
        code_lines.clear()
        code_language = "text"

    def flush_table() -> None:
        if not table_lines:
            return
        rendered = _render_markdown_table(table_lines)
        if rendered:
            parts.append(rendered)
        else:
            paragraph_lines.extend(table_lines)
        table_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if re.match(r"^<!--\s*(?:page|slide)\s*:\s*\d+\s*-->\s*$", line.strip(), re.IGNORECASE):
            continue
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_list()
                flush_paragraph()
                flush_table()
                fence = line.strip()
                language = fence[3:].strip().split(maxsplit=1)[0] if len(fence) > 3 else ""
                code_language = language or "text"
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_table()
            flush_list()
            flush_paragraph()
            continue
        if _is_markdown_table_line(line):
            flush_list()
            flush_paragraph()
            table_lines.append(line)
            continue
        flush_table()
        image_match = re.match(r"^!\[([^\]]*)]\(([^)]+)\)\s*$", line.strip())
        if image_match:
            flush_list()
            flush_paragraph()
            alt = image_match.group(1).strip()
            src_raw = image_match.group(2).strip()
            asset_id = src_raw.removeprefix("asset://") if src_raw.startswith("asset://") else ""
            asset_source = asset_sources.get(asset_id, {})
            src = asset_source.get("src") or src_raw
            caption = asset_source.get("caption") or alt
            if src.startswith(("data:image/", "http://", "https://", "/")):
                parts.append(
                    '<figure class="upload-asset-figure">'
                    f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt or caption, quote=True)}" loading="lazy" />'
                    + (f"<figcaption>{html.escape(caption)}</figcaption>" if caption else "")
                    + "</figure>"
                )
            else:
                parts.append(f"<p>{html.escape(alt or src_raw)}</p>")
            continue
        heading_match = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading_match:
            flush_list()
            flush_paragraph()
            level = min(len(heading_match.group(1)) + 1, 5)
            parts.append(f"<h{level}>{html.escape(heading_match.group(2).strip())}</h{level}>")
            continue
        bullet_match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line.strip())
        if bullet_match:
            flush_paragraph()
            list_items.append(bullet_match.group(1).strip())
            continue
        flush_list()
        paragraph_lines.append(line)
    flush_code()
    flush_table()
    flush_list()
    flush_paragraph()
    return "\n".join(parts)


def _html_id(value: object) -> str:
    normalized = re.sub(r"[\s#?&/\\<>\"']+", "-", str(value or "").strip()).strip("-")
    return normalized[:160]


def _is_markdown_table_line(line: str) -> bool:
    stripped = str(line or "").strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in stripped.split("|")]


def _is_markdown_table_separator(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _render_markdown_table(lines: list[str]) -> str:
    rows = [_split_markdown_table_row(line) for line in lines if _is_markdown_table_line(line)]
    rows = [row for row in rows if row]
    if len(rows) < 2:
        return ""
    has_header = len(rows) >= 2 and _is_markdown_table_separator(rows[1])
    header = rows[0] if has_header else []
    body = rows[2:] if has_header else rows
    width = max(len(row) for row in ([header] if header else []) + body)
    def pad(row: list[str]) -> list[str]:
        return row + [""] * (width - len(row))
    table_parts = ['<div class="upload-table-wrap"><table class="upload-table">']
    if header:
        table_parts.append("<thead><tr>")
        table_parts.extend(f"<th>{_render_basic_inline(cell)}</th>" for cell in pad(header))
        table_parts.append("</tr></thead>")
    table_parts.append("<tbody>")
    for row in body:
        table_parts.append("<tr>")
        table_parts.extend(f"<td>{_render_basic_inline(cell)}</td>" for cell in pad(row))
        table_parts.append("</tr>")
    table_parts.append("</tbody></table></div>")
    return "".join(table_parts)


def _render_basic_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def _normalize_title_text(text: str) -> str:
    return re.sub(r"[\s._\-]+", "", str(text or "").strip().lower())


def _looks_like_generated_upload_title(text: str) -> bool:
    compact = re.sub(r"[\s._\-()]+", "", str(text or "")).strip()
    if not compact:
        return True
    if re.fullmatch(r"\d{1,3}\d{2,4}", compact):
        return True
    if re.fullmatch(r"\d{1,3}\d{1,2}\d{1,2}", compact):
        return True
    return False


def _uploaded_document_title_from_markdown(markdown: str, current_title: str) -> str:
    current = str(current_title or "").strip()
    current_normalized = _normalize_title_text(current)
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("<!--"):
            continue
        heading_match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        candidate = heading_match.group(1).strip() if heading_match else line
        if re.fullmatch(r"(?i)page\s+\d+", candidate):
            continue
        if _normalize_title_text(candidate) == current_normalized:
            continue
        if _looks_like_generated_upload_title(candidate):
            continue
        if len(candidate) > 80:
            continue
        return candidate
    return current or "Uploaded document"


def _strip_uploaded_document_title(markdown: str, title: str) -> str:
    lines = str(markdown or "").splitlines()
    if not lines:
        return ""
    normalized_title = _normalize_title_text(title)
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return ""
    first = lines[index].strip()
    heading_match = re.match(r"^#{1,2}\s+(.+?)\s*$", first)
    if heading_match and _normalize_title_text(heading_match.group(1)) == normalized_title:
        del lines[index]
    return "\n".join(lines).strip()


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _short_viewer_text(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _asset_data_url(content: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type or 'application/octet-stream'};base64,{encoded}"


def _pdf_asset_bytes(source_path: Path, metadata: dict[str, Any]) -> bytes:
    rendered_pdf_page = _metadata_int(metadata.get("rendered_pdf_page"))
    if rendered_pdf_page:
        return render_pdf_page_image_bytes(
            source_path,
            page_number=rendered_pdf_page,
            scale=_metadata_float(metadata.get("rendered_pdf_scale"), default=2.0),
        )

    pdf_xref = str(metadata.get("pdf_xref") or "").strip()
    if not pdf_xref:
        return b""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(source_path))
        try:
            payload = doc.extract_image(int(pdf_xref))
            return bytes(payload.get("image") or b"")
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return b""


def _metadata_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _metadata_float(value: Any, *, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _uploaded_document_asset_sources(root_dir: Path, document: dict[str, Any], asset_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    settings = load_settings(root_dir)
    storage_root = settings.object_storage_dir.resolve()
    source_path = (settings.object_storage_dir / str(document.get("storage_key") or "")).resolve()
    result: dict[str, dict[str, str]] = {}
    for row in asset_rows:
        asset_id = str(row.get("asset_id") or "").strip()
        if not asset_id:
            continue
        metadata = _json_dict(row.get("metadata"))
        content = b""
        storage_key = str(row.get("storage_key") or "").strip()
        if storage_key:
            try:
                asset_path = (settings.object_storage_dir / storage_key).resolve()
                if storage_root in asset_path.parents and asset_path.is_file():
                    content = asset_path.read_bytes()
            except OSError:
                content = b""
        if not content and source_path.exists() and str(metadata.get("pdf_xref") or "").strip():
            content = _pdf_asset_bytes(source_path, metadata)
        if not content:
            continue
        filename = str(metadata.get("filename") or storage_key or asset_id).strip()
        result[asset_id] = {
            "src": _asset_data_url(content, str(row.get("mime_type") or "image/png")),
            "caption": filename,
        }
        parser_asset_id = str(metadata.get("parser_asset_id") or "").strip()
        if parser_asset_id:
            result[parser_asset_id] = result[asset_id]
    return result


def _course_asset_viewer_src(asset_path: str) -> str:
    normalized = str(asset_path or "").strip().replace("\\", "/")
    if not normalized.startswith("data/course_pbs/assets/"):
        return ""
    if not re.search(r"\.(?:png|jpe?g|webp|gif)$", normalized, re.IGNORECASE):
        return ""
    return f"/api/v1/course/assets?path={quote(normalized, safe='/._-()')}"


def _uploaded_document_course_asset_figures_html(chunk: dict[str, Any]) -> str:
    metadata = _json_dict(chunk.get("metadata"))
    attachments = metadata.get("image_attachments")
    if not isinstance(attachments, list):
        return ""

    candidates = [
        attachment
        for attachment in attachments
        if isinstance(attachment, dict) and not bool(attachment.get("exclude_from_default"))
    ]
    candidates.sort(
        key=lambda item: (
            not bool(item.get("is_default_visible", True)),
            int(item.get("default_visible_order") or item.get("image_rank_order") or 9999),
            str(item.get("asset_id") or item.get("attachment_id") or ""),
        )
    )

    figures: list[str] = []
    seen_paths: set[str] = set()
    for attachment in candidates[:6]:
        asset_path = str(attachment.get("asset_path") or "").strip()
        src = _course_asset_viewer_src(asset_path)
        if not src or src in seen_paths:
            continue
        seen_paths.add(src)
        caption = _short_viewer_text(
            attachment.get("visual_summary")
            or attachment.get("caption_text")
            or attachment.get("ocr_text")
            or attachment.get("instructional_role")
            or "",
            limit=220,
        )
        slide_no = int(attachment.get("slide_no") or 0)
        role = str(attachment.get("instructional_role") or "").strip().replace("_", " ")
        caption_parts = [part for part in [f"Slide {slide_no}" if slide_no else "", role, caption] if part]
        caption_text = " - ".join(caption_parts)
        alt_text = caption or caption_text or "고객문서 이미지"
        figures.append(
            '<figure class="upload-asset-figure upload-course-asset-figure">'
            f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt_text, quote=True)}" loading="lazy" />'
            + (f"<figcaption>{html.escape(caption_text)}</figcaption>" if caption_text else "")
            + "</figure>"
        )
    return "\n".join(figures)


def _uploaded_document_viewer_html(root_dir: Path, viewer_path: str, *, owner_user_id: str = "") -> str | None:
    canonical_viewer_path = _canonicalize_viewer_path(viewer_path)
    match = _UPLOAD_DOCUMENT_VIEWER_PATH_RE.fullmatch(urlparse(canonical_viewer_path).path)
    if not match:
        return None
    document_source_id = match.group("document_source_id")
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return None

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ds.id::text AS document_source_id,
                    ds.filename,
                    ds.storage_key,
                    ds.owner_user_id,
                    ds.visibility,
                    ds.byte_size,
                    pd.id::text AS parsed_document_id,
                    COALESCE(NULLIF(pd.title, ''), ds.filename) AS title,
                    pd.markdown,
                    pd.parser_name,
                    pd.parser_version,
                    pd.metadata AS parsed_metadata,
                    pd.warnings AS parsed_warnings,
                    ds.created_at
                FROM document_sources ds
                LEFT JOIN LATERAL (
                    SELECT parsed_documents.*
                    FROM parsed_documents
                    WHERE parsed_documents.document_source_id = ds.id
                    ORDER BY parsed_documents.created_at DESC
                    LIMIT 1
                ) pd ON TRUE
                WHERE ds.id = %s::uuid
                  AND (
                    ds.visibility IN ('workspace_shared', 'global_shared')
                    OR COALESCE(ds.owner_user_id, '') = %s
                  )
                LIMIT 1
                """,
                (document_source_id, owner_user_id),
            )
            document = cursor.fetchone()
            if not document or not document.get("parsed_document_id"):
                return None
            cursor.execute(
                """
                SELECT
                    id::text AS chunk_id,
                    COALESCE(source_anchor, '') AS source_anchor,
                    COALESCE(chunk_key, '') AS chunk_key,
                    ordinal,
                    heading_title,
                    section_path,
                    markdown,
                    token_count,
                    page_start,
                    page_end,
                    asset_ids,
                    metadata
                FROM document_chunks
                WHERE parsed_document_id = %s::uuid
                  AND navigation_only = false
                ORDER BY ordinal ASC
                LIMIT 400
                """,
                (document["parsed_document_id"],),
            )
            chunks = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    count(*)::int AS block_count,
                    count(*) FILTER (WHERE block_type = 'heading')::int AS heading_count,
                    count(*) FILTER (WHERE block_type = 'table')::int AS table_count,
                    count(*) FILTER (WHERE block_type = 'code')::int AS code_count,
                    count(*) FILTER (WHERE block_type = 'image')::int AS image_count,
                    count(DISTINCT page_number) FILTER (WHERE page_number IS NOT NULL)::int AS page_count
                FROM document_blocks
                WHERE parsed_document_id = %s::uuid
                """,
                (document["parsed_document_id"],),
            )
            block_metrics = cursor.fetchone() or {}
            cursor.execute(
                """
                SELECT
                    id::text AS asset_id,
                    mime_type,
                    storage_key,
                    page_number,
                    ocr_text,
                    qwen_description,
                    metadata
                FROM document_assets
                WHERE parsed_document_id = %s::uuid
                ORDER BY page_number NULLS LAST, created_at ASC
                LIMIT 80
                """,
                (document["parsed_document_id"],),
            )
            asset_rows = cursor.fetchall()

    stored_title = str(document.get("title") or document.get("filename") or "Uploaded document")
    raw_markdown = str(document.get("markdown") or "")
    title = (
        _uploaded_document_title_from_markdown(raw_markdown, stored_title)
        if _looks_like_generated_upload_title(stored_title)
        else stored_title
    )
    filename = str(document.get("filename") or title)
    total_tokens = sum(int(row.get("token_count") or 0) for row in chunks)
    parsed_markdown = _strip_uploaded_document_title(raw_markdown, stored_title)
    parsed_markdown = _strip_uploaded_document_title(parsed_markdown, title)
    parsed_metadata = _json_dict(document.get("parsed_metadata"))
    parsed_warnings = [str(item) for item in _json_list(document.get("parsed_warnings")) if str(item).strip()]
    asset_sources = _uploaded_document_asset_sources(root_dir, document, asset_rows)
    block_count = int(block_metrics.get("block_count") or 0)
    page_count = int(block_metrics.get("page_count") or 0)
    quality_notes: list[str] = []
    if not parsed_markdown.strip():
        quality_notes.append("파싱된 본문이 비어 있습니다. 원본 파일 변환 결과를 확인해야 합니다.")
    if total_tokens < 250 and int(document.get("byte_size") or 0) > 100_000:
        quality_notes.append("파일 크기에 비해 추출된 텍스트가 적습니다. 스캔 PDF/이미지 PDF이거나 텍스트 추출이 제한되었을 수 있습니다.")
    if parsed_warnings:
        quality_notes.extend(parsed_warnings)
    document_body_html = _markdownish_to_html(parsed_markdown, asset_sources=asset_sources)
    if chunks:
        chunk_sections: list[str] = []
        used_anchor_ids: set[str] = set()
        for index, row in enumerate(chunks, start=1):
            chunk_id = _html_id(row.get("chunk_id"))
            source_anchor = _html_id(row.get("source_anchor"))
            chunk_key = _html_id(row.get("chunk_key"))
            section_id = next(
                (
                    candidate
                    for candidate in [chunk_id, source_anchor, chunk_key]
                    if candidate and candidate not in used_anchor_ids
                ),
                f"upload-chunk-{index}",
            )
            used_anchor_ids.add(section_id)
            alias_parts = []
            for alias in [source_anchor, chunk_key]:
                if alias and alias != section_id and alias not in used_anchor_ids:
                    alias_parts.append(f'<span id="{html.escape(alias, quote=True)}" class="upload-anchor-alias"></span>')
                    used_anchor_ids.add(alias)
            chunk_markdown = _strip_uploaded_document_title(str(row.get("markdown") or ""), title)
            chunk_markdown = _strip_uploaded_document_title(chunk_markdown, stored_title)
            chunk_html = _markdownish_to_html(chunk_markdown, asset_sources=asset_sources)
            chunk_asset_html = _uploaded_document_course_asset_figures_html(row)
            chunk_sections.append(
                f'<section id="{html.escape(section_id, quote=True)}" class="upload-chunk-section">'
                + "".join(alias_parts)
                + chunk_html
                + chunk_asset_html
                + "</section>"
            )
        document_body_html = "\n".join(chunk_sections)
    body_parts = [
        "<!doctype html>",
        '<html lang="ko">',
        "<head>",
        '<meta charset="utf-8" />',
        f"<title>{html.escape(title)}</title>",
        "<style>",
        """
        body {
          margin: 0;
          background: #08111f;
          color: #e5f3ff;
          font-family: Inter, Pretendard, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .upload-reader {
          max-width: 1120px;
          margin: 0 auto;
          padding: 42px 44px 64px;
        }
        .upload-reader .eyebrow {
          color: #00d1ff;
          font-size: 0.78rem;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .upload-reader h1 {
          margin: 10px 0 8px;
          font-size: clamp(2rem, 4vw, 3.4rem);
          line-height: 1.05;
        }
        .upload-reader .summary {
          color: #93a4b8;
          margin: 0 0 24px;
        }
        .upload-reader .meta {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 24px;
        }
        .upload-reader .meta span {
          border: 1px solid rgba(0, 209, 255, 0.22);
          border-radius: 999px;
          padding: 6px 10px;
          background: rgba(0, 209, 255, 0.08);
          color: #c7e8f5;
          font-size: 0.78rem;
          font-weight: 700;
        }
        .upload-reader .document-panel,
        .upload-reader .diagnostic-panel {
          border: 1px solid rgba(148, 163, 184, 0.18);
          border-radius: 18px;
          background: rgba(15, 23, 42, 0.78);
          padding: 22px 24px;
          margin: 14px 0;
          box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
        }
        .upload-reader .document-panel h2,
        .upload-reader .diagnostic-panel h2 {
          margin: 0 0 10px;
          font-size: 1.22rem;
        }
        .upload-reader .document-body {
          display: grid;
          gap: 14px;
        }
        .upload-reader .upload-chunk-section {
          position: relative;
          scroll-margin-top: 24px;
        }
        .upload-reader .upload-chunk-section:target {
          border-radius: 12px;
          background: linear-gradient(90deg, rgba(125, 211, 252, 0.12), rgba(125, 211, 252, 0));
        }
        .upload-reader .upload-anchor-alias {
          position: relative;
          top: -24px;
          display: block;
          height: 0;
          overflow: hidden;
        }
        .upload-reader .document-body h2,
        .upload-reader .document-body h3,
        .upload-reader .document-body h4,
        .upload-reader .document-body h5 {
          margin: 24px 0 6px;
          color: #f8fbff;
          line-height: 1.35;
        }
        .upload-reader .document-body h2:first-child,
        .upload-reader .document-body h3:first-child {
          margin-top: 0;
        }
        .upload-reader .document-body ul {
          margin: 0;
          padding-left: 1.25rem;
          color: #d6e4f0;
          line-height: 1.8;
        }
        .upload-reader .upload-table-wrap {
          overflow-x: auto;
          margin: 12px 0;
          border: 1px solid rgba(148, 163, 184, 0.22);
          border-radius: 12px;
          background: rgba(2, 6, 23, 0.28);
        }
        .upload-reader .upload-table {
          width: 100%;
          border-collapse: collapse;
          min-width: 640px;
          color: #d6e4f0;
          font-size: 0.95rem;
          line-height: 1.55;
        }
        .upload-reader .upload-table th,
        .upload-reader .upload-table td {
          border-bottom: 1px solid rgba(148, 163, 184, 0.18);
          border-right: 1px solid rgba(148, 163, 184, 0.14);
          padding: 10px 12px;
          text-align: left;
          vertical-align: top;
        }
        .upload-reader .upload-table th {
          color: #f8fbff;
          background: rgba(14, 165, 233, 0.12);
          font-weight: 800;
        }
        .upload-reader .upload-table tr:last-child td {
          border-bottom: 0;
        }
        .upload-reader .upload-table th:last-child,
        .upload-reader .upload-table td:last-child {
          border-right: 0;
        }
        .upload-reader .upload-asset-figure {
          margin: 18px 0;
          border: 1px solid rgba(125, 211, 252, 0.18);
          border-radius: 14px;
          overflow: hidden;
          background: rgba(2, 6, 23, 0.42);
        }
        .upload-reader .upload-asset-figure img {
          display: block;
          width: 100%;
          height: auto;
          background: #f8fafc;
        }
        .upload-reader .upload-asset-figure figcaption {
          padding: 10px 12px;
          color: #334155;
          font-size: 0.86rem;
          line-height: 1.55;
          border-top: 1px solid rgba(148, 163, 184, 0.22);
          background: #f8fafc;
        }
        .upload-reader .quality-notes {
          display: grid;
          gap: 8px;
          margin: 20px 0;
        }
        .upload-reader .quality-note {
          border: 1px solid rgba(245, 158, 11, 0.28);
          border-radius: 12px;
          padding: 10px 12px;
          background: rgba(245, 158, 11, 0.1);
          color: #f8d78d;
          font-size: 0.9rem;
          line-height: 1.5;
        }
        .upload-reader details summary {
          cursor: pointer;
          color: #7dd3fc;
          font-weight: 800;
          margin-bottom: 12px;
        }
        .upload-reader .chunk-diagnostic {
          border-top: 1px solid rgba(148, 163, 184, 0.16);
          padding-top: 14px;
          margin-top: 14px;
        }
        .upload-reader .chunk-meta {
          color: #7dd3fc;
          font-size: 0.75rem;
          margin-bottom: 14px;
        }
        .upload-reader p {
          color: #d6e4f0;
          line-height: 1.78;
        }
        .upload-reader pre {
          overflow: auto;
          border-radius: 12px;
          border: 1px solid rgba(255,255,255,0.1);
          background: #020617;
          padding: 16px;
          color: #e2e8f0;
        }
        .upload-reader code {
          font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
          border-radius: 5px;
          padding: 0.12rem 0.3rem;
          background: rgba(125, 211, 252, 0.12);
        }
        .upload-reader .code-block {
          margin: 14px 0;
          overflow: hidden;
          border: 1px solid rgba(148, 163, 184, 0.18);
          border-radius: 12px;
          background: rgba(2, 6, 23, 0.88);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }
        .upload-reader .code-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 11px 13px;
          border-bottom: 1px solid rgba(148, 163, 184, 0.12);
          background: rgba(15, 23, 42, 0.62);
        }
        .upload-reader .code-label {
          color: #94a3b8;
          font-size: 0.72rem;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .upload-reader .code-actions {
          display: inline-flex;
          align-items: center;
          gap: 8px;
        }
        .upload-reader .icon-button {
          display: inline-grid;
          place-items: center;
          width: 30px;
          height: 30px;
          border: 1px solid rgba(148, 163, 184, 0.12);
          border-radius: 7px;
          padding: 0;
          background: rgba(255, 255, 255, 0.04);
          color: rgba(226, 232, 240, 0.78);
          cursor: pointer;
          transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
        }
        .upload-reader .icon-button:hover,
        .upload-reader .icon-button[aria-pressed="true"] {
          border-color: rgba(0, 209, 255, 0.28);
          background: rgba(0, 209, 255, 0.12);
          color: #f8fbff;
        }
        .upload-reader .sr-only,
        .upload-reader .icon-button .action-label {
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border: 0;
        }
        .upload-reader .code-block pre {
          margin: 0;
          overflow-x: auto;
          border: 0;
          border-radius: 0;
          background: transparent;
          padding: 16px 18px;
          color: #e2e8f0;
          font-size: 0.9rem;
          line-height: 1.65;
          white-space: pre;
          tab-size: 2;
        }
        .upload-reader .code-block code {
          display: block;
          border: 0;
          border-radius: 0;
          background: transparent;
          padding: 0;
          color: inherit;
          white-space: inherit;
        }
        .upload-reader .code-block.overflow-toggle.is-wrapped pre,
        .upload-reader .code-block.overflow-wrap pre {
          overflow-x: hidden;
          white-space: pre-wrap;
          overflow-wrap: break-word;
          word-break: normal;
        }
        .upload-reader .copy-button.is-copied {
          border-color: rgba(134, 239, 172, 0.45);
          background: rgba(22, 163, 74, 0.14);
          color: #bbf7d0;
        }
        .upload-reader .copy-button .copy-icon-success {
          display: none;
        }
        .upload-reader .copy-button.is-copied .copy-icon-idle {
          display: none;
        }
        .upload-reader .copy-button.is-copied .copy-icon-success {
          display: block;
        }
        .upload-reader .code-footer {
          display: flex;
          justify-content: center;
          padding: 10px 16px 14px;
          border-top: 1px solid rgba(148, 163, 184, 0.12);
          background: rgba(15, 23, 42, 0.62);
        }
        .upload-reader .collapse-button {
          border: 0;
          background: transparent;
          color: #cbd5e1;
          font-size: 0.82rem;
          font-weight: 700;
          cursor: pointer;
        }
        .upload-reader .collapse-button:hover,
        .upload-reader .collapse-button.is-collapsed {
          color: #7dd3fc;
        }
        .upload-reader .code-block.is-collapsible pre {
          position: relative;
        }
        .upload-reader .code-block.is-collapsible.is-collapsed pre {
          max-height: 14rem;
          overflow: auto;
          scrollbar-width: thin;
        }
        .upload-reader .code-block.is-collapsible.is-collapsed pre::after {
          content: "";
          position: absolute;
          inset: auto 0 0 0;
          height: 4.5rem;
          background: linear-gradient(to bottom, rgba(2, 6, 23, 0), rgba(2, 6, 23, 0.98));
          pointer-events: none;
        }
        .upload-reader .code-token.code-key {
          color: #93c5fd;
        }
        .upload-reader .code-token.code-string {
          color: #86efac;
        }
        .upload-reader .code-token.code-number {
          color: #c4b5fd;
        }
        .upload-reader .code-token.code-atom {
          color: #fbbf24;
        }
        .upload-reader .code-token.code-comment {
          color: #64748b;
        }
        .upload-reader .code-token.code-punctuation {
          color: #e2e8f0;
        }
        .upload-reader,
        .upload-reader * {
          box-sizing: border-box;
        }
        .upload-reader {
          width: 100%;
          max-width: 100%;
          padding: 10px 8px 44px;
          overflow-x: hidden;
        }
        .upload-reader h1 {
          font-size: clamp(1.8rem, 4vw, 2.45rem);
          overflow-wrap: anywhere;
        }
        .upload-reader .summary,
        .upload-reader p,
        .upload-reader li,
        .upload-reader td,
        .upload-reader h2,
        .upload-reader h3,
        .upload-reader h4,
        .upload-reader h5 {
          overflow-wrap: anywhere;
          word-break: normal;
        }
        .upload-reader .document-panel,
        .upload-reader .diagnostic-panel {
          max-width: 100%;
          min-width: 0;
          padding: 12px;
          box-shadow: none;
        }
        .upload-reader .document-body > *,
        .upload-reader .code-block,
        .upload-reader pre,
        .upload-reader .upload-table-wrap {
          max-width: 100%;
          min-width: 0;
        }
        .upload-reader .upload-asset-figure {
          max-width: 100%;
          background: #ffffff;
        }
        .upload-reader .upload-asset-figure img {
          width: auto;
          max-width: 100%;
          max-height: min(52vh, 360px);
          object-fit: contain;
          margin: 0 auto;
        }
        .upload-reader .upload-table {
          min-width: 0 !important;
          table-layout: fixed;
        }
        .upload-reader .upload-table th,
        .upload-reader .upload-table td {
          overflow-wrap: anywhere;
        }
        .upload-reader .code-block {
          background: #0f172a !important;
          box-shadow: none;
        }
        .upload-reader .code-header,
        .upload-reader .code-footer {
          background: #111827 !important;
          border-color: rgba(148, 163, 184, 0.18) !important;
        }
        .upload-reader .code-label,
        .upload-reader .collapse-button {
          color: #cbd5e1;
        }
        .upload-reader .code-block pre,
        .upload-reader .code-block code,
        .upload-reader pre,
        .upload-reader pre code {
          background: #0f172a !important;
          color: #dbeafe !important;
          font-size: 0.82rem;
          line-height: 1.58;
        }
        .upload-reader .code-token.code-key {
          color: #7dd3fc !important;
        }
        .upload-reader .code-token.code-string {
          color: #86efac !important;
        }
        .upload-reader .code-token.code-number {
          color: #c4b5fd !important;
        }
        .upload-reader .code-token.code-atom {
          color: #fbbf24 !important;
        }
        .upload-reader .code-token.code-comment {
          color: #cbd5e1 !important;
        }
        .upload-reader .code-token.code-punctuation {
          color: #e2e8f0 !important;
        }
        .upload-reader .code-block.is-collapsible.is-collapsed pre::after {
          content: none !important;
          display: none !important;
        }
        """,
        "</style>",
        "</head>",
        '<body class="is-embedded upload-reader-document">',
        '<main class="upload-reader">',
        '<div class="eyebrow">User Upload Document</div>',
        f"<h1>{html.escape(title)}</h1>",
        f'<p class="summary">{html.escape(filename)}에서 추출해 정리한 문서 본문입니다. 인용 번호를 누르면 관련 위치로 이동합니다.</p>',
        '<div class="meta">',
        f"<span>{block_count:,} blocks</span>",
        f"<span>{len(chunks)} chunks</span>",
        f"<span>{total_tokens:,} tokens</span>",
        f"<span>{page_count:,} pages</span>",
        f"<span>{html.escape(str(document.get('parser_name') or 'parser'))}</span>",
        f"<span>{html.escape(str(document.get('visibility') or 'private_user'))}</span>",
        "</div>",
        '<section class="document-panel">',
        "<h2>문서 본문</h2>",
        '<div class="document-body">',
        document_body_html or "<p>표시할 문서 본문이 없습니다.</p>",
        "</div>",
        "</section>",
    ]
    if quality_notes:
        body_parts.extend(['<div class="quality-notes">'])
        for note in quality_notes:
            body_parts.append(f'<div class="quality-note">{html.escape(note)}</div>')
        body_parts.append("</div>")
    body_parts.extend(
        [
            '<section class="diagnostic-panel">',
            "<h2>검색 인덱스 기록</h2>",
            "<p>아래 항목은 챗봇 검색에 사용된 내부 색인 단위입니다.</p>",
            "<details>",
            "<summary>청크 목록 열기</summary>",
        ]
    )
    for index, row in enumerate(chunks, start=1):
        heading = str(row.get("heading_title") or "").strip()
        section_path = row.get("section_path") or []
        if isinstance(section_path, list):
            section_label = " > ".join(str(item) for item in section_path if str(item).strip())
        else:
            section_label = ""
        title_text = heading or section_label or f"Chunk {index}"
        page_bits = []
        if row.get("page_start"):
            page_bits.append(f"p.{row.get('page_start')}")
        if row.get("page_end") and row.get("page_end") != row.get("page_start"):
            page_bits.append(f"-{row.get('page_end')}")
        meta = " · ".join(
            item
            for item in [
                f"#{index}",
                f"{int(row.get('token_count') or 0):,} tokens",
                "".join(page_bits),
                section_label,
            ]
            if item
        )
        body_parts.extend(
            [
                '<section class="chunk-diagnostic">',
                f"<h2>{html.escape(title_text)}</h2>",
                f'<div class="chunk-meta">{html.escape(meta)}</div>',
                _markdownish_to_html(str(row.get("markdown") or "")) or "<p>내용이 비어 있습니다.</p>",
                "</section>",
            ]
        )
    body_parts.extend(
        [
            "</details>",
            "</section>",
            "</main>",
            """
            <script>
            function uploadViewerCodeText(button) {
              if (button.dataset.copy) return JSON.parse(button.dataset.copy || '""');
              const block = button.closest(".code-block");
              const code = block ? block.querySelector("code") : null;
              return code ? (code.textContent || "") : "";
            }
            async function copyViewerCode(button) {
              const label = button.dataset.labelDefault || "복사";
              try {
                const text = uploadViewerCodeText(button);
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  await navigator.clipboard.writeText(text);
                }
                button.classList.add("is-copied");
                button.setAttribute("title", button.dataset.labelActive || "복사됨");
                button.setAttribute("aria-label", button.dataset.labelActive || "복사됨");
                window.setTimeout(function () {
                  button.classList.remove("is-copied");
                  button.setAttribute("title", label);
                  button.setAttribute("aria-label", label);
                }, 1400);
              } catch (error) {
                button.setAttribute("title", "실패");
                button.setAttribute("aria-label", "실패");
                window.setTimeout(function () {
                  button.setAttribute("title", label);
                  button.setAttribute("aria-label", label);
                }, 1400);
              }
            }
            function toggleViewerCodeWrap(button) {
              const block = button.closest(".code-block");
              if (!block) return;
              block.classList.toggle("is-wrapped");
              const wrapped = block.classList.contains("is-wrapped");
              const label = wrapped
                ? (button.dataset.labelActive || "줄바꿈 해제")
                : (button.dataset.labelDefault || "줄바꿈");
              button.setAttribute("aria-pressed", wrapped ? "true" : "false");
              button.setAttribute("title", label);
              button.setAttribute("aria-label", label);
            }
            function toggleViewerCodeCollapse(button) {
              const block = button.closest(".code-block");
              if (!block) return;
              block.classList.toggle("is-collapsed");
              const collapsed = block.classList.contains("is-collapsed");
              button.classList.toggle("is-collapsed", collapsed);
              button.setAttribute("aria-expanded", collapsed ? "false" : "true");
              button.textContent = collapsed
                ? (button.dataset.labelCollapsed || "전체 보기")
                : (button.dataset.labelExpanded || "접기");
            }
            </script>
            """,
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(body_parts)


def _uploaded_document_source_meta(root_dir: Path, viewer_path: str, *, owner_user_id: str = "") -> dict[str, Any] | None:
    canonical_viewer_path = _canonicalize_viewer_path(viewer_path)
    match = _UPLOAD_DOCUMENT_VIEWER_PATH_RE.fullmatch(urlparse(canonical_viewer_path).path)
    if not match:
        return None
    document_source_id = match.group("document_source_id")
    anchor = urlparse(canonical_viewer_path).fragment.strip()
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return None

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ds.id::text AS document_source_id,
                    ds.filename,
                    ds.storage_key,
                    ds.owner_user_id,
                    ds.visibility,
                    ds.source_scope,
                    ds.metadata AS source_metadata,
                    pd.id::text AS parsed_document_id,
                    COALESCE(NULLIF(pd.title, ''), ds.filename) AS title,
                    pd.parser_name,
                    pd.metadata AS parsed_metadata,
                    COALESCE(dc.id::text, '') AS chunk_id,
                    COALESCE(dc.heading_title, '') AS heading_title,
                    COALESCE(dc.source_anchor, '') AS source_anchor,
                    COALESCE(dc.section_path, '[]'::jsonb) AS chunk_section_path
                FROM document_sources ds
                LEFT JOIN LATERAL (
                    SELECT parsed_documents.*
                    FROM parsed_documents
                    WHERE parsed_documents.document_source_id = ds.id
                    ORDER BY parsed_documents.created_at DESC
                    LIMIT 1
                ) pd ON TRUE
                LEFT JOIN LATERAL (
                    SELECT document_chunks.*
                    FROM document_chunks
                    WHERE document_chunks.parsed_document_id = pd.id
                      AND (%s = '' OR document_chunks.id::text = %s OR document_chunks.source_anchor = %s OR document_chunks.chunk_key = %s)
                    ORDER BY
                        CASE
                            WHEN document_chunks.id::text = %s THEN 0
                            WHEN document_chunks.source_anchor = %s OR document_chunks.chunk_key = %s THEN 1
                            ELSE 2
                        END,
                        document_chunks.ordinal ASC
                    LIMIT 1
                ) dc ON TRUE
                WHERE ds.id = %s::uuid
                  AND (
                    ds.visibility IN ('workspace_shared', 'global_shared')
                    OR COALESCE(ds.owner_user_id, '') = %s
                  )
                LIMIT 1
                """,
                (anchor, anchor, anchor, anchor, anchor, anchor, anchor, document_source_id, owner_user_id),
            )
            row = cursor.fetchone()
    if not row:
        return None

    title = str(row.get("title") or row.get("filename") or "Uploaded document").strip()
    section_path = [
        str(item).strip()
        for item in _json_list(row.get("chunk_section_path"))
        if str(item).strip()
    ]
    section = str(row.get("heading_title") or "").strip() or (section_path[-1] if section_path else title)
    source_scope = str(row.get("source_scope") or "user_upload").strip() or "user_upload"
    resolved_anchor = str(row.get("chunk_id") or row.get("source_anchor") or anchor or "").strip()
    parsed_viewer_path = urlparse(canonical_viewer_path)
    resolved_viewer_path = urlunparse(parsed_viewer_path._replace(fragment=resolved_anchor))
    return {
        "book_slug": "uploaded-documents",
        "book_title": title,
        "anchor": resolved_anchor,
        "section": section,
        "section_path": section_path or [title],
        "section_path_label": " > ".join(section_path) if section_path else section,
        "source_url": str(row.get("storage_key") or "").strip(),
        "viewer_path": resolved_viewer_path,
        "section_match_exact": bool(anchor and row.get("chunk_id")),
        "source_collection": "uploads",
        "pack_label": "User Upload",
        "source_lane": source_scope,
        "approval_state": "private",
        "publication_state": "uploaded",
        "parser_backend": str(row.get("parser_name") or ""),
        "boundary_truth": "private_user_upload_runtime",
        "runtime_truth_label": "User Upload Document",
        "boundary_badge": "User Upload",
    }


def _viewer_html_for_path(
    root_dir: Path,
    viewer_path: str,
    *,
    page_mode: str = "single",
    owner_user_id: str = "",
) -> str | None:
    viewer_path = _canonicalize_viewer_path(viewer_path)
    internal_html = (
        _uploaded_document_viewer_html(root_dir, viewer_path, owner_user_id=owner_user_id)
        or course_viewer_html(root_dir, viewer_path)
        or
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


def resolve_viewer_html(
    root_dir: Path,
    viewer_path: str,
    *,
    page_mode: str = "single",
    owner_user_id: str = "",
) -> str | None:
    viewer_path = _canonicalize_viewer_path(viewer_path)
    customer_pack_draft_id = customer_pack_draft_id_from_viewer_path(viewer_path)
    if customer_pack_draft_id and not _customer_pack_read_allowed(root_dir, customer_pack_draft_id):
        return None
    return _viewer_html_for_path(root_dir, viewer_path, page_mode=page_mode, owner_user_id=owner_user_id)


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
    uploaded_meta = _uploaded_document_source_meta(root_dir, viewer_path)
    if uploaded_meta is not None:
        return uploaded_meta
    customer_pack_meta = _customer_pack_meta_for_viewer_path(root_dir, viewer_path)
    if customer_pack_meta is not None:
        return customer_pack_meta
    course_meta = course_viewer_source_meta(root_dir, viewer_path)
    if course_meta is not None:
        return course_meta
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
    uploaded_payload = _uploaded_document_source_meta(root_dir, viewer_path, owner_user_id=_owner_hash_from_handler(handler))
    if uploaded_payload is not None:
        handler._send_json(uploaded_payload)
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
    html_text = _uploaded_document_viewer_html(root_dir, viewer_path, owner_user_id=_owner_hash_from_handler(handler))
    if html_text is None:
        html_text = _viewer_html_for_path(
            root_dir,
            viewer_path,
            page_mode=page_mode,
            owner_user_id=_owner_hash_from_handler(handler),
        )
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
    items = _figure_assets().get(book_slug, [])
    if not isinstance(items, list):
        items = []
    normalized: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "caption": str(item.get("caption") or item.get("alt") or "Figure"),
                "viewer_path": _figure_viewer_href(book_slug, item),
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
