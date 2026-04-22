from __future__ import annotations

# PDF capture를 canonical section row로 바꾸는 helper 모음.

import re

from ..models import CustomerPackDraftRecord
from .pdf_helpers import (
    MARKDOWN_HEADING_RE,
    PAGE_MARKER_RE,
    WHITESPACE_RE,
    _clean_docling_section_body,
    _docling_section_level,
    _extract_outline_section_body,
    _find_pdf_outline_position,
    _infer_pdf_section_level,
    _looks_like_pdf_heading,
    _normalize_pdf_heading,
    _pdf_anchor,
    _prepare_pdf_page_text,
    _should_inline_docling_heading,
    _skip_docling_heading,
    _validate_pdf_rows,
)
from .pdf import PdfOutlineEntry


KO_SPACE_MISSING_RE = re.compile(
    r"[가-힣][가-힣]{5,}"  # 5+ consecutive Korean chars with no space = likely merged words
)


def _docling_korean_quality_ok(rows: list[dict[str, object]]) -> bool:
    """Return False if docling output looks like merged Korean words (no spaces)."""
    if not rows:
        return False
    merged_count = 0
    sample = rows[:min(20, len(rows))]
    for row in sample:
        text = str(row.get("text") or "")
        if KO_SPACE_MISSING_RE.search(text):
            merged_count += 1
    # If more than 30% of sampled rows have merged Korean, quality is poor
    return merged_count / max(len(sample), 1) < 0.30


def _build_pdf_rows(
    pages: list[str],
    record: CustomerPackDraftRecord,
    *,
    outline: list[PdfOutlineEntry] | None = None,
) -> list[dict[str, object]]:
    if outline:
        outline_rows = _build_pdf_rows_from_outline(pages, outline, record)
        if outline_rows:
            _validate_pdf_rows(outline_rows, page_count=len(pages))
            return outline_rows

    rows: list[dict[str, object]] = []
    book_slug = record.plan.book_slug
    viewer_base = f"/playbooks/customer-packs/{record.draft_id}/index.html"
    source_url = record.request.uri
    book_title = record.plan.title
    ordinal = 1

    for page_number, page_text in enumerate(pages, start=1):
        page_sections = _segment_pdf_page(page_text)
        if not page_sections:
            continue
        for section_index, (heading, body) in enumerate(page_sections, start=1):
            anchor_seed = heading if heading and not heading.startswith("Page ") else f"page-{page_number}-{section_index}"
            anchor = _pdf_anchor(anchor_seed, ordinal)
            section_path = [f"Page {page_number}"]
            if heading:
                section_path.append(heading)
            rows.append(
                {
                    "book_slug": book_slug,
                    "book_title": book_title,
                    "heading": heading or f"Page {page_number}",
                    "section_level": _infer_pdf_section_level(heading),
                    "section_path": section_path,
                    "anchor": anchor,
                    "source_url": source_url,
                    "viewer_path": f"{viewer_base}#{anchor}",
                    "text": body.strip(),
                }
            )
            ordinal += 1
    _validate_pdf_rows(rows, page_count=len(pages))
    return rows


def _build_pdf_rows_from_docling_markdown(
    markdown: str,
    record: CustomerPackDraftRecord,
) -> list[dict[str, object]]:
    sections = _segment_docling_markdown(markdown)
    if not sections:
        return []

    rows: list[dict[str, object]] = []
    stack: list[str] = []
    book_slug = record.plan.book_slug
    viewer_base = f"/playbooks/customer-packs/{record.draft_id}/index.html"
    source_url = record.request.uri
    book_title = record.plan.title

    for ordinal, (level, heading, body) in enumerate(sections, start=1):
        stack = stack[: level - 1]
        stack.append(heading)
        anchor = _pdf_anchor(heading, ordinal)
        rows.append(
            {
                "book_slug": book_slug,
                "book_title": book_title,
                "heading": heading,
                "section_level": level,
                "section_path": list(stack),
                "anchor": anchor,
                "source_url": source_url,
                "viewer_path": f"{viewer_base}#{anchor}",
                "text": body,
            }
        )

    _validate_pdf_rows(rows, page_count=max(len(rows), 1))
    return rows


def _build_pdf_rows_from_outline(
    pages: list[str],
    outline: list[PdfOutlineEntry],
    record: CustomerPackDraftRecord,
) -> list[dict[str, object]]:
    if not pages or not outline:
        return []

    prepared_pages = [_prepare_pdf_page_text(page) for page in pages]
    matched_positions: list[tuple[int, int, int]] = []
    cursor_page = 0
    cursor_offset = 0
    for entry in outline:
        matched = _find_pdf_outline_position(
            prepared_pages,
            entry.title,
            start_page=cursor_page,
            start_offset=cursor_offset,
        )
        if matched is None:
            matched = (cursor_page, cursor_offset, cursor_offset)
        matched_positions.append(matched)
        cursor_page, _, cursor_offset = matched

    rows: list[dict[str, object]] = []
    stack: list[str] = []
    book_slug = record.plan.book_slug
    viewer_base = f"/playbooks/customer-packs/{record.draft_id}/index.html"
    source_url = record.request.uri
    book_title = record.plan.title

    for ordinal, entry in enumerate(outline, start=1):
        start_page, start_offset, _ = matched_positions[ordinal - 1]
        if ordinal < len(matched_positions):
            end_page, end_offset, _ = matched_positions[ordinal]
        else:
            end_page, end_offset = len(prepared_pages) - 1, len(prepared_pages[-1]) if prepared_pages else 0
        body = _extract_outline_section_body(
            prepared_pages,
            start_page=start_page,
            start_offset=start_offset,
            end_page=end_page,
            end_offset=end_offset,
            current_title=entry.title,
        )
        if not body:
            continue
        level = max(entry.level, 1)
        stack = stack[: level - 1]
        stack.append(entry.title)
        anchor = _pdf_anchor(entry.title, ordinal)
        rows.append(
            {
                "book_slug": book_slug,
                "book_title": book_title,
                "heading": entry.title,
                "section_level": level,
                "section_path": list(stack),
                "anchor": anchor,
                "source_url": source_url,
                "viewer_path": f"{viewer_base}#{anchor}",
                "text": body,
            }
        )

    return rows


def _segment_pdf_page(page_text: str) -> list[tuple[str, str]]:
    prepared = _prepare_pdf_page_text(page_text)
    if not prepared:
        return []
    lines = [line.strip() for line in prepared.splitlines()]
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_body
        body = "\n\n".join(part for part in current_body if part.strip()).strip()
        if current_heading or body:
            heading = current_heading or "Page Summary"
            sections.append((heading, body or heading))
        current_heading = ""
        current_body = []

    for raw_line in lines:
        line = WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line:
            if current_body and current_body[-1]:
                current_body.append("")
            continue
        if PAGE_MARKER_RE.match(line):
            continue
        if _looks_like_pdf_heading(line):
            flush()
            current_heading = _normalize_pdf_heading(line)
            continue
        current_body.append(line)

    flush()
    return [(heading, body) for heading, body in sections if body.strip()]


def _segment_docling_markdown(markdown: str) -> list[tuple[int, str, str]]:
    lines = str(markdown or "").splitlines()
    sections: list[tuple[int, str, str]] = []
    current_heading = ""
    current_level = 0
    body_lines: list[str] = []
    parent_level = 0

    def flush() -> None:
        nonlocal current_heading, current_level, body_lines, parent_level
        heading = current_heading.strip()
        body = _clean_docling_section_body("\n".join(body_lines), heading=heading)
        if heading and body and not _skip_docling_heading(heading):
            sections.append((current_level or 1, heading, body))
            parent_level = current_level or 1
        current_heading = ""
        current_level = 0
        body_lines = []

    for raw_line in lines:
        stripped = raw_line.strip()
        match = MARKDOWN_HEADING_RE.match(stripped)
        if match:
            heading = match.group(2).strip()
            if current_heading and _should_inline_docling_heading(heading):
                if body_lines and body_lines[-1].strip():
                    body_lines.append("")
                body_lines.append(f"### {heading}")
                continue
            flush()
            raw_level = len(match.group(1))
            current_level = _docling_section_level(
                heading,
                raw_level=raw_level,
                parent_level=parent_level,
            )
            current_heading = heading
            continue
        body_lines.append(raw_line.rstrip())

    flush()
    return sections


