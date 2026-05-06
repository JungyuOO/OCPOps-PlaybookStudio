import html
import re

from play_book_studio.canonical.command_split import split_inline_commands

NORMALIZED_BLOCK_RE = re.compile(
    r"(\[CODE(?:\s+[^\]]+)?\].*?\[/CODE\]|\[TABLE(?:\s+[^\]]+)?\].*?\[/TABLE\]|\[FIGURE(?:\s+[^\]]+)?\].*?\[/FIGURE\])",
    re.DOTALL,
)
FENCED_CODE_BLOCK_RE = re.compile(
    r"```(?P<language>[A-Za-z0-9_+\-]*)[ \t]*\n(?P<body>.*?\n?)```",
    re.DOTALL,
)
MARKDOWN_IMAGE_BLOCK_RE = re.compile(
    r"(?m)^(?:>\s*)?!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"(?P<title>[^\"]+)\")?\)\s*$"
)
MARKDOWN_TABLE_BLOCK_RE = re.compile(
    r"(?ms)(^|\n{2,})(?P<body>\|.*?\|\s*\n\|\s*[-:| ]+\|\s*(?:\n\|.*?\|\s*)+)(?=\n{2,}|\Z)"
)
WIKI_ASSET_URL_RE = re.compile(r"^/playbooks/wiki-assets/[^/]+/(?P<slug>[^/]+)/(?P<asset_name>[^/]+)$")
MARKER_ATTR_RE = re.compile(r'([a-z_]+)="((?:[^"\\]|\\.)*)"')
CODE_BLOCK_RE = re.compile(r"^\[CODE(?P<attrs>[^\]]*)\]\s*(?P<body>.*?)\s*\[/CODE\]$", re.DOTALL)
TABLE_BLOCK_RE = re.compile(r"^\[TABLE(?P<attrs>[^\]]*)\]\s*(?P<body>.*?)\s*\[/TABLE\]$", re.DOTALL)
FIGURE_BLOCK_RE = re.compile(r"^\[FIGURE(?P<attrs>[^\]]*)\]\s*(?P<body>.*?)\s*\[/FIGURE\]$", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]+\")?\)")
MARKDOWN_STRONG_RE = re.compile(r"(?<!\*)\*\*([^*\n][^*\n]*?)\*\*(?!\*)")
MARKDOWN_EM_RE = re.compile(r"(?<![\w_])_([^_\n][^_\n]*?)_(?![\w_])")
ORDERED_LIST_ITEM_RE = re.compile(r"^(?P<index>\d+)\.\s+(?P<body>.+)$", re.DOTALL)
SOURCE_VIEW_LEADING_NOISE_RE = re.compile(
    r"^\s*Red Hat OpenShift Documentation Team(?:\s+법적 공지)?(?:\s+초록)?\s*",
)
SOURCE_VIEW_TOC_RE = re.compile(r"^\s*목차\s*(?:\n\n|\n)?")
ASCII_GRID_BORDER_RE = re.compile(r"^\s*[+\-=:]{3,}\s*$")
ASCII_GRID_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
MARKDOWN_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
LOW_SIGNAL_SHELL_RE = re.compile(
    r"^(?:\.\.\.|(?:\$|#)?\s*(?:oc|kubectl))\s*$",
    re.IGNORECASE,
)
RAW_TABLE_HTML_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
EVENT_HANDLER_ATTR_RE = re.compile(r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*')", re.IGNORECASE)
READER_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=니다\.)\s+")
READER_BREAKWORD_RE = re.compile(
    r"\s+(?=(?:Procedure|Prerequisites|Warning|Caution|Note|주의|참고|사전 요구 사항|프로세스|다음 절차|다음 명령))"
)
READER_LABELED_ITEM_RE = re.compile(r"^(?P<label>[^:\n]{1,48}?):\s+(?P<body>.+)$")
READER_INTRO_AND_LABELED_ITEM_RE = re.compile(
    r"^(?P<intro>.+?:)\s+(?P<label>[^:\n]{1,48}?):\s+(?P<body>.+)$"
)


def _clean_source_view_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = SOURCE_VIEW_LEADING_NOISE_RE.sub("", cleaned, count=1).lstrip()
    cleaned = SOURCE_VIEW_TOC_RE.sub("", cleaned, count=1).lstrip()
    return cleaned


def _normalize_markdown_fenced_code_blocks(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        language = (match.group("language") or "").strip() or "shell"
        body = (match.group("body") or "").strip("\n")
        return f'[CODE language="{language}" wrap_hint="false"]\n{body}\n[/CODE]'

    return FENCED_CODE_BLOCK_RE.sub(_replace, text)


def _normalize_markdown_image_blocks(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        alt = (match.group("alt") or "").strip()
        src = (match.group("src") or "").strip()
        title = (match.group("title") or "").strip()
        caption = title or alt
        attrs = ' src="{src}" alt="{alt}"'.format(
            src=html.escape(src, quote=True),
            alt=html.escape(alt or caption, quote=True),
        )
        body = html.escape(caption)
        return f'[FIGURE{attrs}]\n{body}\n[/FIGURE]'

    return MARKDOWN_IMAGE_BLOCK_RE.sub(_replace, text)


def _normalize_markdown_table_blocks(text: str) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return str(text or "")
    normalized: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        current = lines[index]
        next_line = lines[index + 1] if index + 1 < total else ""
        if "|" in current and MARKDOWN_TABLE_DIVIDER_RE.match(next_line):
            block = [current, next_line]
            index += 2
            while index < total:
                candidate = lines[index]
                if candidate.strip() and "|" in candidate:
                    block.append(candidate)
                    index += 1
                    continue
                break
            normalized.append("[TABLE]")
            normalized.extend(block)
            normalized.append("[/TABLE]")
            continue
        normalized.append(current)
        index += 1
    trailing_newline = "\n" if str(text or "").endswith("\n") else ""
    return "\n".join(normalized) + trailing_newline


def _render_inline_html(text: str) -> str:
    fragments: list[str] = []
    last_index = 0
    matches: list[tuple[int, int, str, re.Match[str]]] = []
    matches.extend((match.start(), match.end(), "code", match) for match in INLINE_CODE_RE.finditer(text))
    matches.extend((match.start(), match.end(), "link", match) for match in MARKDOWN_LINK_RE.finditer(text))
    matches.extend((match.start(), match.end(), "strong", match) for match in MARKDOWN_STRONG_RE.finditer(text))
    matches.extend((match.start(), match.end(), "em", match) for match in MARKDOWN_EM_RE.finditer(text))
    matches.sort(key=lambda item: (item[0], item[1]))
    for start, end, kind, match in matches:
        if start < last_index:
            continue
        if start > last_index:
            fragments.append(html.escape(text[last_index:start]))
        if kind == "code":
            fragments.append(f"<code>{html.escape(match.group(1))}</code>")
        elif kind == "link":
            label = html.escape(match.group(1))
            href = html.escape(match.group(2), quote=True)
            external_attrs = ""
            if not href.startswith("#") and not href.startswith("/"):
                external_attrs = ' target="_blank" rel="noreferrer"'
            fragments.append(f'<a href="{href}"{external_attrs}>{label}</a>')
        elif kind == "strong":
            fragments.append(f"<strong>{html.escape(match.group(1))}</strong>")
        else:
            fragments.append(f"<em>{html.escape(match.group(1))}</em>")
        last_index = end
    if last_index < len(text):
        fragments.append(html.escape(text[last_index:]))
    return "".join(fragments)


def _render_text_with_command_boxes(text: str, *, step_mode: bool = False) -> str:
    from .viewer_blocks_rich import _render_code_block_html, _render_table_block_html

    if RAW_TABLE_HTML_RE.search(text):
        return _render_table_block_html(text)
    split = split_inline_commands(text)
    if split is None:
        escaped = _render_inline_html(text)
        return f'<div class="step-text">{escaped}</div>' if step_mode else f"<p>{escaped}</p>"
    fragments: list[str] = []
    if split.narrative_text:
        narrative_html = _render_inline_html(split.narrative_text)
        fragments.append(f'<div class="step-text">{narrative_html}</div>' if step_mode else f"<p>{narrative_html}</p>")
    for index, command in enumerate(split.commands):
        fragments.append(
            _render_code_block_html(
                command,
                language="shell",
                copy_text=command,
                wrap_hint=True,
                overflow_hint="toggle",
                caption=split.caption_text if index == 0 and not split.narrative_text else "",
                preserve_layout=_looks_like_ascii_grid(command),
            )
        )
    return "".join(fragments)


def _parse_marker_attrs(text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, value in MARKER_ATTR_RE.findall(text or ""):
        attrs[key.strip().lower()] = value.strip()
    return attrs


def _parse_bool_attr(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _looks_like_subheading(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 36:
        return False
    if re.search(r"(?:니다|합니다|하십시오|하세요|[\.\?\!])", stripped):
        return False
    return True


def _looks_like_ascii_grid(text: str) -> bool:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    border_rows = sum(1 for line in lines if ASCII_GRID_BORDER_RE.match(line))
    cell_rows = sum(1 for line in lines if ASCII_GRID_ROW_RE.match(line))
    return border_rows >= 2 and cell_rows >= 1


def _split_table_row(row: str) -> list[str]:
    stripped = str(row or "").strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _looks_like_markdown_table_block(text: str) -> bool:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return False
    if not MARKDOWN_TABLE_DIVIDER_RE.match(lines[1]):
        return False
    body_lines = lines[2:]
    return bool(body_lines) and all("|" in line for line in body_lines)


def _split_reader_display_paragraphs(text: str) -> list[str]:
    def _hard_wrap(value: str, *, limit: int = 160) -> list[str]:
        words = [word for word in str(value or "").split() if word]
        if not words:
            return []
        wrapped: list[str] = []
        bucket: list[str] = []
        bucket_len = 0
        for word in words:
            projected = bucket_len + len(word) + (1 if bucket else 0)
            if bucket and projected > limit:
                wrapped.append(" ".join(bucket).strip())
                bucket = [word]
                bucket_len = len(word)
                continue
            bucket.append(word)
            bucket_len = projected
        if bucket:
            wrapped.append(" ".join(bucket).strip())
        return wrapped

    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return []
    if READER_BREAKWORD_RE.search(cleaned):
        segmented: list[str] = []
        for piece in READER_BREAKWORD_RE.split(cleaned):
            piece = piece.strip()
            if not piece:
                continue
            segmented.extend(_hard_wrap(piece) if len(piece) > 260 else [piece])
        if len(segmented) > 1:
            return segmented
    if len(cleaned) <= 320:
        return [cleaned]
    sentences = [sentence.strip() for sentence in READER_SENTENCE_SPLIT_RE.split(cleaned) if sentence.strip()]
    if len(sentences) <= 1:
        return _hard_wrap(cleaned) or [cleaned]
    chunks: list[str] = []
    bucket: list[str] = []
    bucket_len = 0
    for sentence in sentences:
        projected = bucket_len + len(sentence) + (1 if bucket else 0)
        if bucket and (projected > 260 or len(bucket) >= 2):
            chunks.append(" ".join(bucket).strip())
            bucket = [sentence]
            bucket_len = len(sentence)
            continue
        bucket.append(sentence)
        bucket_len = projected
    if bucket:
        chunks.append(" ".join(bucket).strip())
    normalized_chunks: list[str] = []
    for chunk in chunks or [cleaned]:
        normalized_chunks.extend(_hard_wrap(chunk) if len(chunk) > 320 else [chunk])
    return normalized_chunks or [cleaned]


def _looks_like_source_attribution(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    if normalized.startswith("_") and normalized.endswith("_"):
        normalized = normalized[1:-1].strip()
    return normalized.lower().startswith("source:")


def _render_source_attribution_html(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if normalized.startswith("_") and normalized.endswith("_"):
        normalized = normalized[1:-1].strip()
    return '<p class="source-attribution">{}</p>'.format(_render_inline_html(normalized))


def _looks_like_reader_list_label(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or len(normalized) > 36 or normalized.count(" ") > 5:
        return False
    if any(token in normalized.lower() for token in ("http", "www.", "`", "_source")):
        return False
    if any(mark in normalized for mark in ".?![]{}<>"):
        return False
    return True


def _extract_labeled_reader_item(text: str) -> tuple[str | None, str, str] | None:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or _looks_like_source_attribution(normalized):
        return None
    for match in (READER_INTRO_AND_LABELED_ITEM_RE.match(normalized), READER_LABELED_ITEM_RE.match(normalized)):
        if match is None:
            continue
        label = " ".join(str(match.group("label") or "").split()).strip()
        body = " ".join(str(match.group("body") or "").split()).strip()
        if not _looks_like_reader_list_label(label) or not body:
            continue
        intro = match.groupdict().get("intro")
        intro_text = " ".join(str(intro or "").split()).strip() if intro else None
        return intro_text or None, label, body
    return None


def _looks_like_reader_list_intro(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or _looks_like_source_attribution(normalized):
        return False
    return normalized.endswith(":") or any(
        phrase in normalized
        for phrase in ("다음 목록", "다음 항목", "다음과 같은", "다음과 같습니다", "자세히 설명합니다", "사용 사례를 고려하십시오", "the following", "described below")
    )


def _looks_like_simple_reader_list_item(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or len(normalized) > 80:
        return False
    if normalized.endswith((".", "?", "!", ":", ";")):
        return False
    return len(normalized.split()) <= 6


def _render_reader_list_item(
    body_text: str,
    *,
    lead_label: str = "",
    continuation_texts: list[str] | None = None,
) -> str:
    primary_html = _render_inline_html(" ".join(str(body_text or "").split()).strip())
    lead_html = '<span class="reader-list-lead">{}</span> '.format(html.escape(f"{lead_label}:")) if lead_label.strip() else ""
    fragments = [f'<div class="reader-list-item-body">{lead_html}{primary_html}</div>']
    for continuation in continuation_texts or []:
        for paragraph in _split_reader_display_paragraphs(continuation):
            fragments.append(f"<p>{_render_inline_html(paragraph)}</p>")
    return '<li class="reader-list-item">{}</li>'.format("".join(fragments))


def _render_reader_list_html(items: list[str], *, labeled: bool = False) -> str:
    class_name = "reader-bullet-list reader-bullet-list-labeled" if labeled else "reader-bullet-list"
    return '<ul class="{}">{}</ul>'.format(class_name, "".join(items))


def _consume_labeled_reader_list(paragraph_queue: list[str], start_index: int) -> tuple[list[str], int] | None:
    intro_fragments: list[str] = []
    items: list[str] = []
    index = start_index
    saw_intro = False
    while index < len(paragraph_queue):
        current = paragraph_queue[index].strip()
        parsed = _extract_labeled_reader_item(current)
        if parsed is None:
            break
        intro_text, label, body = parsed
        if intro_text:
            if items:
                break
            intro_fragments.append(f'<p class="reader-intro">{_render_inline_html(intro_text)}</p>')
            saw_intro = True
        index += 1
        continuation_texts: list[str] = []
        while index < len(paragraph_queue):
            candidate = paragraph_queue[index].strip()
            if (
                not candidate
                or _looks_like_subheading(candidate)
                or _looks_like_source_attribution(candidate)
                or _looks_like_reader_list_intro(candidate)
                or _extract_labeled_reader_item(candidate) is not None
                or _looks_like_markdown_table_block(candidate)
                or RAW_TABLE_HTML_RE.search(candidate)
            ):
                break
            continuation_texts.append(candidate)
            index += 1
        items.append(_render_reader_list_item(body, lead_label=label, continuation_texts=continuation_texts))
    if len(items) >= 2 or (saw_intro and items):
        return intro_fragments + [_render_reader_list_html(items, labeled=True)], index
    return None


def _consume_simple_reader_list(paragraph_queue: list[str], start_index: int) -> tuple[list[str], int] | None:
    intro = paragraph_queue[start_index].strip()
    if not _looks_like_reader_list_intro(intro):
        return None
    index = start_index + 1
    items: list[str] = []
    while index < len(paragraph_queue):
        candidate = paragraph_queue[index].strip()
        if (
            not candidate
            or _looks_like_source_attribution(candidate)
            or _extract_labeled_reader_item(candidate) is not None
            or _looks_like_reader_list_intro(candidate)
            or _looks_like_markdown_table_block(candidate)
            or RAW_TABLE_HTML_RE.search(candidate)
        ):
            break
        if len(candidate) > 260 and items:
            break
        if _looks_like_subheading(candidate) and not _looks_like_simple_reader_list_item(candidate):
            break
        items.append(_render_reader_list_item(candidate))
        index += 1
    if len(items) >= 2:
        return [f'<p class="reader-intro">{_render_inline_html(intro)}</p>', _render_reader_list_html(items)], index
    return None


def _is_low_signal_ordered_item_body(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return True
    return re.fullmatch(r"\d+(?:[./:-]\d+)*", normalized) is not None


def _looks_like_structured_code_paragraph(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) < 120:
        return False
    colon_count = normalized.count(":")
    quote_count = normalized.count('"')
    if normalized.startswith("{"):
        return colon_count >= 4 and quote_count >= 8
    if normalized.startswith('"'):
        return colon_count >= 4 and quote_count >= 6
    return False


def _should_suppress_low_signal_code_block(code_text: str, *, language: str = "shell") -> bool:
    normalized = (code_text or "").strip()
    if not normalized:
        return True
    normalized_language = (language or "shell").strip().lower()
    if normalized_language not in {"shell", "shell-session", "bash", "sh", "console", "text"}:
        return False
    return LOW_SIGNAL_SHELL_RE.fullmatch(normalized) is not None


__all__ = [
    "_clean_source_view_text",
    "_consume_labeled_reader_list",
    "_consume_simple_reader_list",
    "_extract_labeled_reader_item",
    "_is_low_signal_ordered_item_body",
    "_looks_like_ascii_grid",
    "_looks_like_markdown_table_block",
    "_looks_like_simple_reader_list_item",
    "_looks_like_source_attribution",
    "_looks_like_structured_code_paragraph",
    "_looks_like_subheading",
    "_normalize_markdown_fenced_code_blocks",
    "_normalize_markdown_image_blocks",
    "_normalize_markdown_table_blocks",
    "_parse_bool_attr",
    "_parse_marker_attrs",
    "_render_inline_html",
    "_render_source_attribution_html",
    "_render_text_with_command_boxes",
    "_should_suppress_low_signal_code_block",
]
