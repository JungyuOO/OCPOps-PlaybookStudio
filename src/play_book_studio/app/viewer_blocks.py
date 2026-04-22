# 플레이북 문서의 section body를 HTML 블록으로 렌더링한다.
import html
import re
from typing import Any

from .viewer_blocks_rich import (
    _render_code_block_html,
    _render_figure_block_html,
    _render_note_card_html,
    _render_playbook_block_html,
    _render_table_block_html,
)
from .viewer_blocks_text import (
    CODE_BLOCK_RE,
    FIGURE_BLOCK_RE,
    NORMALIZED_BLOCK_RE,
    ORDERED_LIST_ITEM_RE,
    RAW_TABLE_HTML_RE,
    TABLE_BLOCK_RE,
    _clean_source_view_text,
    _consume_labeled_reader_list,
    _consume_simple_reader_list,
    _extract_labeled_reader_item,
    _is_low_signal_ordered_item_body,
    _looks_like_ascii_grid,
    _looks_like_markdown_table_block,
    _looks_like_source_attribution,
    _looks_like_structured_code_paragraph,
    _looks_like_subheading,
    _normalize_markdown_fenced_code_blocks,
    _normalize_markdown_image_blocks,
    _normalize_markdown_table_blocks,
    _parse_bool_attr,
    _parse_marker_attrs,
    _render_inline_html,
    _render_source_attribution_html,
    _render_text_with_command_boxes,
    _split_reader_display_paragraphs,
)

UNORDERED_LIST_ITEM_RE = re.compile(r"^(?:[*+-])\s+(?P<body>.+)$", re.DOTALL)
ADMONITION_VARIANTS = {
    "중요": "important",
    "important": "important",
    "주의": "warning",
    "warning": "warning",
    "caution": "caution",
    "참고": "note",
    "note": "note",
    "팁": "tip",
    "tip": "tip",
}


def _render_normalized_section_html(text: str) -> str:
    blocks: list[str] = []
    normalized = _normalize_markdown_table_blocks(
        _normalize_markdown_image_blocks(
            _normalize_markdown_fenced_code_blocks(_clean_source_view_text(text))
        )
    )
    paragraph_queue: list[str] = []

    def flush_paragraph_queue() -> None:
        nonlocal paragraph_queue
        if not paragraph_queue:
            return
        index = 0
        while index < len(paragraph_queue):
            current = paragraph_queue[index]
            admonition_block = _consume_admonition_block(paragraph_queue, index)
            if admonition_block is not None:
                blocks.append(admonition_block[0])
                index = admonition_block[1]
                continue
            labeled_list = _consume_labeled_reader_list(paragraph_queue, index)
            if labeled_list is not None:
                fragments, next_index = labeled_list
                blocks.extend(fragments)
                index = next_index
                continue
            if _looks_like_reader_list_intro_bridge(current, paragraph_queue, index):
                fragments, next_index = _consume_labeled_reader_list(paragraph_queue, index + 1) or ([], index + 1)
                blocks.append(f'<p class="reader-intro">{_render_inline_html(" ".join(current.split()).strip())}</p>')
                blocks.extend(fragments)
                index = next_index
                continue
            simple_list = _consume_simple_reader_list(paragraph_queue, index)
            if simple_list is not None:
                fragments, next_index = simple_list
                blocks.extend(fragments)
                index = next_index
                continue
            markdown_list = _consume_markdown_bullet_list(paragraph_queue, index)
            if markdown_list is not None:
                fragments, next_index = markdown_list
                blocks.extend(fragments)
                index = next_index
                continue
            ordered_match = ORDERED_LIST_ITEM_RE.match(current)
            if not ordered_match:
                blocks.extend(_render_normal_paragraph(current))
                index += 1
                continue
            start = int(ordered_match.group("index"))
            items: list[str] = []
            while index < len(paragraph_queue):
                item_match = ORDERED_LIST_ITEM_RE.match(paragraph_queue[index])
                if not item_match:
                    break
                item_body = item_match.group("body").strip()
                index += 1
                if _is_low_signal_ordered_item_body(item_body):
                    continue
                item_body_parts = [_render_inline_html(item_body)]
                while index < len(paragraph_queue):
                    continuation = paragraph_queue[index]
                    if ORDERED_LIST_ITEM_RE.match(continuation) or _looks_like_subheading(continuation):
                        break
                    item_body_parts.extend(
                        "<p>{}</p>".format(_render_inline_html(paragraph))
                        for paragraph in _split_reader_display_paragraphs(continuation)
                    )
                    index += 1
                items.append("<li>{}</li>".format("".join(item_body_parts)))
            if items:
                blocks.append('<ol class="normalized-ordered-list" start="{}">{}</ol>'.format(start, "".join(items)))
        paragraph_queue = []

    for part in NORMALIZED_BLOCK_RE.split(normalized):
        if not part or not part.strip():
            continue
        stripped = part.strip()
        code_match = CODE_BLOCK_RE.match(stripped)
        if code_match:
            flush_paragraph_queue()
            attrs = _parse_marker_attrs(code_match.group("attrs"))
            code_text = code_match.group("body").strip("\n")
            blocks.append(
                _render_code_block_html(
                    code_text,
                    language=str(attrs.get("language") or "shell").strip() or "shell",
                    copy_text=code_text,
                    wrap_hint=_parse_bool_attr(attrs.get("wrap_hint"), False),
                    overflow_hint=str(attrs.get("overflow_hint") or "toggle").strip() or "toggle",
                    caption=str(attrs.get("caption") or "").strip(),
                    preserve_layout=_looks_like_ascii_grid(code_text),
                )
            )
            continue
        table_match = TABLE_BLOCK_RE.match(stripped)
        if table_match:
            flush_paragraph_queue()
            attrs = _parse_marker_attrs(table_match.group("attrs"))
            has_header_attr = attrs.get("header")
            blocks.append(
                _render_table_block_html(
                    table_match.group("body").strip("\n"),
                    caption=str(attrs.get("caption") or "").strip(),
                    has_header=_parse_bool_attr(has_header_attr, True) if has_header_attr is not None else None,
                )
            )
            continue
        figure_match = FIGURE_BLOCK_RE.match(stripped)
        if figure_match:
            flush_paragraph_queue()
            attrs = _parse_marker_attrs(figure_match.group("attrs"))
            blocks.append(
                _render_figure_block_html(
                    str(attrs.get("src") or "").strip(),
                    caption=html.unescape(figure_match.group("body").strip()),
                    alt=str(attrs.get("alt") or "").strip(),
                    kind=str(attrs.get("kind") or "").strip(),
                    diagram_type=str(attrs.get("diagram_type") or "").strip(),
                )
            )
            continue
        for paragraph in re.split(r"\n\s*\n+", stripped):
            if _looks_like_markdown_table_block(paragraph):
                flush_paragraph_queue()
                blocks.append(_render_table_block_html(paragraph))
                continue
            preserved_lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if len(preserved_lines) > 1 and (
                _looks_like_admonition_title(preserved_lines[0])
                or any(UNORDERED_LIST_ITEM_RE.match(line) for line in preserved_lines)
            ):
                paragraph_queue.extend(preserved_lines)
                continue
            cleaned = re.sub(r"\s*\n\s*", " ", paragraph).strip()
            if cleaned:
                paragraph_queue.append(cleaned)
    flush_paragraph_queue()
    return "\n".join(blocks)


def _looks_like_reader_list_intro_bridge(paragraph_queue_item: str, paragraph_queue: list[str], index: int) -> bool:
    return (
        index + 1 < len(paragraph_queue)
        and _extract_labeled_reader_item(paragraph_queue[index + 1]) is not None
        and any(phrase in " ".join(paragraph_queue_item.split()).strip() or paragraph_queue_item.endswith(":") for phrase in ("다음 목록", "다음 항목", "다음과 같은", "자세히 설명합니다", "사용 사례를 고려하십시오", "the following", "described below", ":"))
    )


def _render_normal_paragraph(current: str) -> list[str]:
    if RAW_TABLE_HTML_RE.search(current):
        return [_render_table_block_html(current)]
    if _looks_like_source_attribution(current):
        return [_render_source_attribution_html(current)]
    if _looks_like_subheading(current):
        return [f"<h3>{html.escape(current)}</h3>"]
    if _looks_like_structured_code_paragraph(current):
        return [_render_code_block_html(current, language="json", copy_text=current, wrap_hint=False, overflow_hint="toggle")]
    return [_render_text_with_command_boxes(paragraph) for paragraph in _split_reader_display_paragraphs(current)]


def _looks_like_admonition_title(text: str) -> bool:
    return " ".join(str(text or "").split()).strip().lower() in ADMONITION_VARIANTS


def _admonition_variant(text: str) -> str:
    return ADMONITION_VARIANTS.get(" ".join(str(text or "").split()).strip().lower(), "note")


def _consume_markdown_bullet_list(paragraph_queue: list[str], start_index: int) -> tuple[list[str], int] | None:
    current = paragraph_queue[start_index].strip()
    if UNORDERED_LIST_ITEM_RE.match(current) is None:
        return None
    items: list[str] = []
    index = start_index
    while index < len(paragraph_queue):
        candidate = paragraph_queue[index].strip()
        match = UNORDERED_LIST_ITEM_RE.match(candidate)
        if match is None:
            break
        items.append(f"<li>{_render_inline_html(' '.join(match.group('body').split()).strip())}</li>")
        index += 1
    return (['<ul class="reader-bullet-list">{}</ul>'.format("".join(items))], index) if items else None


def _render_note_body_fragment(text: str) -> list[str]:
    if RAW_TABLE_HTML_RE.search(text):
        return [_render_table_block_html(text)]
    if _looks_like_structured_code_paragraph(text):
        return [_render_code_block_html(text, language="json", copy_text=text, wrap_hint=False, overflow_hint="toggle")]
    return [_render_text_with_command_boxes(paragraph) for paragraph in _split_reader_display_paragraphs(text)]


def _consume_admonition_block(paragraph_queue: list[str], start_index: int) -> tuple[str, int] | None:
    title = paragraph_queue[start_index].strip()
    if not _looks_like_admonition_title(title):
        return None
    variant = _admonition_variant(title)
    body_fragments: list[str] = []
    index = start_index + 1
    while index < len(paragraph_queue):
        current = paragraph_queue[index].strip()
        if not current or _looks_like_source_attribution(current) or _looks_like_admonition_title(current):
            break
        if _looks_like_markdown_table_block(current):
            body_fragments.append(_render_table_block_html(current))
            index += 1
            continue
        labeled_list = _consume_labeled_reader_list(paragraph_queue, index)
        if labeled_list is not None:
            fragments, next_index = labeled_list
            body_fragments.extend(fragments)
            index = next_index
            continue
        simple_list = _consume_simple_reader_list(paragraph_queue, index)
        if simple_list is not None:
            fragments, next_index = simple_list
            body_fragments.extend(fragments)
            index = next_index
            continue
        markdown_list = _consume_markdown_bullet_list(paragraph_queue, index)
        if markdown_list is not None:
            fragments, next_index = markdown_list
            body_fragments.extend(fragments)
            index = next_index
            continue
        if _looks_like_subheading(current) and body_fragments:
            break
        body_fragments.extend(_render_note_body_fragment(current))
        index += 1
    if not body_fragments:
        return None
    return _render_note_card_html(variant=variant, title=title, body_html="".join(body_fragments)), index


__all__ = [
    "_clean_source_view_text",
    "_render_normalized_section_html",
    "_render_playbook_block_html",
]
