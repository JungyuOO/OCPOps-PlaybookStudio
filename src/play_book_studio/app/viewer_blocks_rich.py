import html
import json
import re
from typing import Any

from .viewer_blocks_text import (
    EVENT_HANDLER_ATTR_RE,
    MARKDOWN_TABLE_DIVIDER_RE,
    RAW_TABLE_HTML_RE,
    SCRIPT_TAG_RE,
    WIKI_ASSET_URL_RE,
    _looks_like_ascii_grid,
    _parse_bool_attr,
    _render_inline_html,
    _render_text_with_command_boxes,
    _should_suppress_low_signal_code_block,
    _split_table_row,
)

YAML_KEY_VALUE_RE = re.compile(r"^(?P<indent>\s*)(?P<dash>-\s+)?(?P<key>[A-Za-z0-9_.-]+:)(?P<spacing>\s*)(?P<value>.*)$")
YAML_COMMENT_RE = re.compile(r"^(?P<indent>\s*)(?P<comment>#.*)$")


def _render_note_card_html(*, variant: str, title: str, body_html: str) -> str:
    icon = {"warning": "!", "caution": "!", "important": "!", "tip": "i"}.get(variant, "i")
    return """
    <section class="note-card note-{variant}">
      <div class="note-heading">
        <span class="note-icon" aria-hidden="true">{icon}</span>
        <div class="note-title">{title}</div>
      </div>
      <div class="note-body">{body_html}</div>
    </section>
    """.format(
        variant=html.escape(variant, quote=True),
        icon=html.escape(icon),
        title=html.escape(title),
        body_html=body_html,
    ).strip()


def _render_code_block_html(
    code_text: str,
    *,
    language: str = "shell",
    copy_text: str = "",
    wrap_hint: bool = False,
    overflow_hint: str = "toggle",
    caption: str = "",
    preserve_layout: bool = False,
) -> str:
    if _should_suppress_low_signal_code_block(code_text, language=language):
        return ""
    copy_payload = html.escape(json.dumps(copy_text or code_text), quote=True)
    classes = ["code-block"]
    if len(code_text.splitlines()) >= 14:
        classes.append("is-collapsible")
    normalized_overflow_hint = (overflow_hint or "toggle").strip().lower() or "toggle"
    if preserve_layout:
        classes.append("preserve-layout")
        wrap_hint = False
        normalized_overflow_hint = "toggle"
    if normalized_overflow_hint == "scroll":
        classes.append("overflow-scroll")
        wrap_hint = False
    elif normalized_overflow_hint == "wrap":
        classes.append("overflow-wrap")
        wrap_hint = True
    else:
        classes.append("overflow-toggle")
    if wrap_hint:
        classes.append("is-wrapped")
    display_language = _display_code_language(code_text, language=language)
    caption_html = '<div class="code-caption">{}</div>'.format(html.escape(caption)) if caption.strip() else ""
    wrap_button_html = ""
    if normalized_overflow_hint == "toggle":
        wrap_button_html = """
          <button type="button" class="wrap-button icon-button" aria-pressed="{wrap_pressed}" onclick="toggleViewerCodeWrap(this)" data-label-default="줄바꿈" data-label-active="줄바꿈 해제" title="{wrap_title}" aria-label="{wrap_title}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 10 20 15 15 20"></polyline><path d="M4 4v7a4 4 0 0 0 4 4h12"></path></svg>
            <span class="sr-only action-label">{wrap_title}</span>
          </button>
        """.format(
            wrap_pressed="true" if wrap_hint else "false",
            wrap_title="줄바꿈 해제" if wrap_hint else "줄바꿈",
        )
    collapse_button_html = ""
    if "is-collapsible" in classes:
        collapse_button_html = """
      <div class="code-footer">
        <button type="button" class="collapse-button" aria-expanded="true" onclick="toggleViewerCodeCollapse(this)" data-label-collapsed="Show more" data-label-expanded="Show less">Show less</button>
      </div>
        """
    return """
    <section class="{classes}">
      {caption_html}
      <div class="code-header">
        <span class="code-label">{language}</span>
        <div class="code-actions">
          <button type="button" class="copy-button icon-button" data-copy="{copy_payload}" data-label-default="복사" data-label-active="복사됨" title="복사" aria-label="복사">
            <svg class="copy-icon-idle" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <svg class="copy-icon-success" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
            <span class="sr-only action-label">복사</span>
          </button>
          {wrap_button_html}
        </div>
      </div>
      <pre><code>{code}</code></pre>
      {collapse_button_html}
    </section>
    """.format(
        classes=" ".join(classes),
        caption_html=caption_html,
        language=html.escape(display_language),
        copy_payload=copy_payload,
        wrap_button_html=wrap_button_html,
        code=_render_highlighted_code_html(code_text, language=display_language, preserve_layout=preserve_layout),
        collapse_button_html=collapse_button_html,
    ).strip()


def _display_code_language(code_text: str, *, language: str) -> str:
    normalized = (language or "text").strip().lower() or "text"
    if normalized in {"shell", "text", "plain", "console"} and _looks_like_yaml_document(code_text):
        return "yaml"
    return normalized


def _looks_like_yaml_document(code_text: str) -> bool:
    lines = [line for line in str(code_text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    structured = sum(1 for line in lines if YAML_KEY_VALUE_RE.match(line) or YAML_COMMENT_RE.match(line))
    return structured >= max(3, len(lines) // 2)


def _render_highlighted_code_html(code_text: str, *, language: str, preserve_layout: bool) -> str:
    if preserve_layout:
        return html.escape(code_text)
    normalized = (language or "text").strip().lower()
    if normalized not in {"yaml", "yml"}:
        return html.escape(code_text)
    return "\n".join(_render_yaml_line_html(line) for line in code_text.splitlines())


def _render_yaml_line_html(line: str) -> str:
    comment_match = YAML_COMMENT_RE.match(line)
    if comment_match is not None:
        return "{indent}<span class=\"code-token code-comment\">{comment}</span>".format(
            indent=_render_code_indent_html(comment_match.group("indent")),
            comment=html.escape(comment_match.group("comment")),
        )
    key_match = YAML_KEY_VALUE_RE.match(line)
    if key_match is not None:
        value = key_match.group("value")
        dash = key_match.group("dash") or ""
        return "{indent}{dash}<span class=\"code-token code-key\">{key}</span>{spacing}{value}".format(
            indent=_render_code_indent_html(key_match.group("indent")),
            dash=f'<span class="code-token code-punctuation">{html.escape(dash)}</span>' if dash else "",
            key=html.escape(key_match.group("key")),
            spacing=_render_code_indent_html(key_match.group("spacing")),
            value=_render_yaml_value_html(value),
        )
    stripped = line.lstrip()
    indent = _render_code_indent_html(line[: len(line) - len(stripped)])
    if stripped.startswith("- "):
        return "{}<span class=\"code-token code-punctuation\">- </span>{}".format(indent, _render_yaml_value_html(stripped[2:]))
    return html.escape(line)


def _render_yaml_value_html(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if normalized.startswith('"') and normalized.endswith('"'):
        return '<span class="code-token code-string">{}</span>'.format(html.escape(value))
    if normalized.lower() in {"true", "false", "null", "yes", "no", "on", "off"}:
        return '<span class="code-token code-atom">{}</span>'.format(html.escape(value))
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:ms|s|m|h|d)?", normalized):
        return '<span class="code-token code-number">{}</span>'.format(html.escape(value))
    if re.fullmatch(r"\{\}|\[\]", normalized):
        return '<span class="code-token code-punctuation">{}</span>'.format(html.escape(value))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+", normalized):
        return '<span class="code-token code-number">{}</span>'.format(html.escape(value))
    return html.escape(value)


def _render_code_indent_html(indent: str) -> str:
    if not indent:
        return ""
    expanded = indent.replace("\t", "  ")
    return expanded.replace(" ", "&nbsp;")


def _sanitize_table_html(table_html: str) -> str:
    sanitized = SCRIPT_TAG_RE.sub("", str(table_html or ""))
    sanitized = EVENT_HANDLER_ATTR_RE.sub("", sanitized)
    return sanitized.strip()


def _render_table_block_html(
    table_text: str,
    *,
    caption: str = "",
    table_html: str = "",
    has_header: bool | None = None,
) -> str:
    caption_html = '<div class="table-caption">{}</div>'.format(html.escape(caption)) if caption.strip() else ""
    if str(table_html or "").strip():
        return """
        <div class="table-wrap">
          {caption_html}
          {table_html}
        </div>
        """.format(caption_html=caption_html, table_html=_sanitize_table_html(table_html)).strip()
    raw_table_match = RAW_TABLE_HTML_RE.search(str(table_text or ""))
    if raw_table_match is not None:
        return """
        <div class="table-wrap">
          {caption_html}
          {table_html}
        </div>
        """.format(caption_html=caption_html, table_html=_sanitize_table_html(raw_table_match.group(0))).strip()
    raw_lines = [row for row in table_text.splitlines() if row.strip()]
    rows = [_split_table_row(row) for row in raw_lines]
    if not rows:
        return ""
    headers = rows[0]
    body = rows[1:]
    if len(raw_lines) >= 2 and MARKDOWN_TABLE_DIVIDER_RE.match(raw_lines[1]):
        if has_header is False:
            headers = []
            body = [rows[0], *rows[2:]]
        else:
            headers = rows[0]
            body = rows[2:]
    elif has_header is False:
        headers = []
        body = rows
    if not body:
        body = [headers] if headers else rows
        headers = [] if headers else headers
    header_html = ""
    if headers:
        header_html = f"<thead><tr>{''.join(f'<th>{html.escape(cell)}</th>' for cell in headers)}</tr></thead>"
    body_rows = ["<tr>{}</tr>".format("".join(f"<td>{html.escape(cell)}</td>" for cell in row)) for row in body]
    return """
    <div class="table-wrap">
      {caption_html}
      <table>
        {header_html}
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
    """.format(caption_html=caption_html, header_html=header_html, rows="".join(body_rows)).strip()


def _render_figure_block_html(src: str, *, caption: str = "", alt: str = "", kind: str = "", diagram_type: str = "") -> str:
    safe_src = html.escape(src, quote=True)
    safe_alt = html.escape(alt or caption or "figure", quote=True)
    caption_html = f"<figcaption>{html.escape(caption)}</figcaption>" if caption.strip() else ""
    normalized_kind = (kind or "").strip().lower()
    normalized_diagram_type = (diagram_type or "").strip().lower()
    class_names = ["figure-block"]
    if normalized_kind == "diagram" or src.strip().lower().endswith(".svg"):
        class_names.append("diagram-block")
    eyebrow_html = ""
    if normalized_kind == "diagram":
        label = "Diagram" if not normalized_diagram_type else f"Diagram · {normalized_diagram_type.replace('_', ' ')}"
        eyebrow_html = f'<div class="figure-eyebrow">{html.escape(label)}</div>'
    href = src
    external_attrs = ' target="_blank" rel="noreferrer"'
    match = WIKI_ASSET_URL_RE.fullmatch(src.strip())
    if match is not None:
        href = "/wiki/figures/{slug}/{asset_name}/index.html".format(slug=match.group("slug"), asset_name=match.group("asset_name"))
        external_attrs = ""
    meta_bits = [str(kind or "").strip(), str(diagram_type or "").strip()]
    meta_html = ""
    if any(meta_bits):
        meta_html = '<div class="figure-meta">{}</div>'.format(
            "".join('<span class="figure-meta-pill">{}</span>'.format(html.escape(bit.replace("_", " "))) for bit in meta_bits if bit)
        )
    return """
    <figure class="{class_names}">
      {eyebrow_html}
      {meta_html}
      <a class="figure-link" href="{href}"{external_attrs}>
        <img src="{src}" alt="{alt}" loading="lazy" />
      </a>
      {caption_html}
    </figure>
    """.format(
        class_names=" ".join(class_names),
        eyebrow_html=eyebrow_html,
        meta_html=meta_html,
        href=html.escape(href, quote=True),
        external_attrs=external_attrs,
        src=safe_src,
        alt=safe_alt,
        caption_html=caption_html,
    ).strip()


def _render_playbook_block_html(block: dict[str, Any]) -> str:
    kind = str(block.get("kind") or "").strip()
    if kind == "paragraph":
        return _render_text_with_command_boxes(str(block.get("text") or "").strip())
    if kind == "prerequisite":
        items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
        return (
            """
        <section class="note-card note-note">
          <div class="note-title">사전 요구 사항</div>
          <ul class="list-block">{items}</ul>
        </section>
        """.format(items="".join(f"<li>{_render_inline_html(item)}</li>" for item in items)).strip()
            if items
            else ""
        )
    if kind == "procedure":
        steps = list(block.get("steps") or [])
        items: list[str] = []
        for step in steps:
            text = str(step.get("text") or "").strip()
            if not text:
                continue
            substeps = [str(item).strip() for item in (step.get("substeps") or []) if str(item).strip()]
            substep_html = '<ul class="substep-list">{}</ul>'.format("".join(f"<li>{_render_inline_html(item)}</li>" for item in substeps)) if substeps else ""
            items.append("<li>{}{}</li>".format(_render_text_with_command_boxes(text, step_mode=True), substep_html))
        return '<ol class="procedure-list">{}</ol>'.format("".join(items)) if items else ""
    if kind == "code":
        code_text = str(block.get("code") or "").strip()
        return _render_code_block_html(
            code_text,
            language=str(block.get("language") or "shell").strip() or "shell",
            copy_text=str(block.get("copy_text") or "").strip(),
            wrap_hint=bool(block.get("wrap_hint", True)),
            overflow_hint=str(block.get("overflow_hint") or "toggle").strip() or "toggle",
            caption=str(block.get("caption") or "").strip(),
            preserve_layout=_looks_like_ascii_grid(code_text),
        )
    if kind == "note":
        variant = str(block.get("variant") or "note").strip().lower()
        title = str(block.get("title") or "").strip()
        note_title = title or {"warning": "주의", "caution": "주의", "important": "중요", "tip": "팁"}.get(variant, "참고")
        return _render_note_card_html(
            variant=variant,
            title=note_title,
            body_html=_render_text_with_command_boxes(str(block.get("text") or "").strip()),
        ).strip()
    if kind == "table":
        if str(block.get("table_html") or "").strip():
            return _render_table_block_html("", caption=str(block.get("caption") or "").strip(), table_html=str(block.get("table_html") or "").strip())
        headers = [str(item).strip() for item in (block.get("headers") or [])]
        rows = [tuple(str(cell).strip() for cell in row) for row in (block.get("rows") or [])]
        structured_headers = block.get("header_cells")
        structured_rows = block.get("row_cells")
        if isinstance(structured_headers, list) or isinstance(structured_rows, list):
            table_html_parts: list[str] = ["<table>"]
            if isinstance(structured_headers, list) and structured_headers:
                table_html_parts.append("<thead><tr>")
                for cell in structured_headers:
                    if not isinstance(cell, dict):
                        continue
                    attrs = []
                    colspan = int(cell.get("colspan") or 1)
                    rowspan = int(cell.get("rowspan") or 1)
                    if colspan > 1:
                        attrs.append(f' colspan="{colspan}"')
                    if rowspan > 1:
                        attrs.append(f' rowspan="{rowspan}"')
                    table_html_parts.append("<th{attrs}>{text}</th>".format(attrs="".join(attrs), text=html.escape(str(cell.get("text") or "").strip())))
                table_html_parts.append("</tr></thead>")
            if isinstance(structured_rows, list) and structured_rows:
                table_html_parts.append("<tbody>")
                for row in structured_rows:
                    if not isinstance(row, list):
                        continue
                    table_html_parts.append("<tr>")
                    for cell in row:
                        if not isinstance(cell, dict):
                            continue
                        attrs = []
                        colspan = int(cell.get("colspan") or 1)
                        rowspan = int(cell.get("rowspan") or 1)
                        if colspan > 1:
                            attrs.append(f' colspan="{colspan}"')
                        if rowspan > 1:
                            attrs.append(f' rowspan="{rowspan}"')
                        table_html_parts.append("<td{attrs}>{text}</td>".format(attrs="".join(attrs), text=html.escape(str(cell.get("text") or "").strip())))
                    table_html_parts.append("</tr>")
                table_html_parts.append("</tbody>")
            table_html_parts.append("</table>")
            return _render_table_block_html("", caption=str(block.get("caption") or "").strip(), table_html="".join(table_html_parts))
        lines: list[str] = []
        if headers:
            lines.append(" | ".join(headers))
        lines.extend(" | ".join(row) for row in rows)
        return _render_table_block_html("\n".join(lines), caption=str(block.get("caption") or "").strip())
    if kind == "figure":
        return _render_figure_block_html(
            str(block.get("src") or "").strip(),
            caption=str(block.get("caption") or "").strip(),
            alt=str(block.get("alt") or "").strip(),
            kind=str(block.get("kind_label") or block.get("asset_kind") or "").strip(),
            diagram_type=str(block.get("diagram_type") or "").strip(),
        )
    return ""


__all__ = [
    "_render_code_block_html",
    "_render_figure_block_html",
    "_render_note_card_html",
    "_render_playbook_block_html",
    "_render_table_block_html",
]
