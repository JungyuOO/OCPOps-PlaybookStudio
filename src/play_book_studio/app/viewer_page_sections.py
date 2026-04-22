import json
import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from play_book_studio.app.viewer_blocks import (
    _clean_source_view_text,
    _render_normal_paragraph,
    _render_normalized_section_html,
    _render_playbook_block_html,
)
from play_book_studio.app.viewer_blocks_text import _render_inline_html
from play_book_studio.app.viewer_blocks_rich import _render_figure_block_html
from play_book_studio.app.viewer_blocks_text import _extract_labeled_reader_item, _split_reader_display_paragraphs
from play_book_studio.app.source_books_wiki_relations import _figure_asset_by_name

HEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:chapter\s+\d+\.?\s*|\d+\s*장\.?\s*|(?:\d+|[A-Za-z])(?:\.\d+)*\.?\s+)",
    re.IGNORECASE,
)
KOREAN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}")
LINK_PUNCTUATION_RE = re.compile(r"^(?P<body>.*?)(?P<tail>[.。]?)$")
ADDITIONAL_RESOURCES_LABELS = {"추가 리소스", "additional resources"}
KOREAN_SUFFIXES = (
    "하도록",
    "하십시오",
    "합니다",
    "됩니다",
    "됩니다",
    "사용",
    "구성",
    "관리",
    "삭제",
    "업데이트",
    "설치",
    "확인",
    "생성",
    "등록",
    "지원",
    "보기",
    "정보",
    "예",
)
KOREAN_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "으로",
    "와",
    "과",
    "를",
    "을",
    "은",
    "는",
    "이",
    "가",
    "에",
)
ADOC_ID_RE = re.compile(r'^\[id="(?P<id>[^"]+)"\]$')
ADOC_BULLET_RE = re.compile(r"^(?P<depth>\*+)\s+(?P<body>.+)$")
ADOC_LINK_RE = re.compile(r"link:(?P<href>\S+?)\[(?P<label>[^\]]+)\]")
ADOC_XREF_RE = re.compile(r"xref:(?P<target>[^\[]+)\[(?P<label>[^\]]+)\]")
ADOC_IMAGE_RE = re.compile(r"image::(?P<asset_ref>[^\[]+)\[(?P<caption>[^\]]*)\]")


def _display_heading(text: str) -> str:
    raw = " ".join(str(text or "").split()).strip()
    if not raw:
        return ""
    cleaned = HEADING_NUMBER_PREFIX_RE.sub("", raw).strip()
    return cleaned or raw


def _normalize_link_token(token: str) -> str:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return ""
    if normalized == "operators":
        normalized = "operator"
    if normalized == "clusters":
        normalized = "cluster"
    for suffix in KOREAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            normalized = normalized[: -len(suffix)]
            break
    for particle in KOREAN_PARTICLES:
        if normalized.endswith(particle) and len(normalized) > len(particle) + 1:
            normalized = normalized[: -len(particle)]
            break
    return normalized


def _link_match_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in KOREAN_TOKEN_RE.findall(_display_heading(text)):
        normalized = _normalize_link_token(token)
        if normalized and normalized not in {"red", "hat", "대한", "다음", "경우"}:
            tokens.append(normalized)
    return tuple(tokens)


def _build_section_link_candidates(
    sections: list[dict[str, Any]],
    *,
    book_slug: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in sections:
        anchor = str(row.get("anchor") or "").strip()
        heading = _display_heading(str(row.get("heading") or ""))
        if not anchor or not heading:
            continue
        href = f"/playbooks/wiki-runtime/active/{book_slug}/index.html#{anchor}" if book_slug else f"#{anchor}"
        candidates.append(
            {
                "anchor": anchor,
                "heading": heading,
                "heading_tokens": _link_match_tokens(heading),
                "anchor_tokens": _link_match_tokens(anchor.replace("_", " ").replace("-", " ")),
                "href": href,
            }
        )
    return candidates


def _runtime_href_from_docs_href(href: str) -> str:
    normalized = str(href or "").strip()
    match = re.match(r"^/docs/ocp/[^/]+/[^/]+/(?P<slug>[^/]+)/index\.html(?:#(?P<anchor>.*))?$", normalized)
    if match is None:
        return normalized
    slug = str(match.group("slug") or "").strip()
    anchor = str(match.group("anchor") or "").strip()
    rewritten = f"/playbooks/wiki-runtime/active/{slug}/index.html"
    return f"{rewritten}#{anchor}" if anchor else rewritten


@lru_cache(maxsize=1)
def _playbook_anchor_index(root_dir_str: str) -> dict[str, str]:
    root_dir = Path(root_dir_str)
    playbook_dir = root_dir / "data" / "gold_manualbook_ko" / "playbooks"
    index: dict[str, str] = {}
    if not playbook_dir.exists():
        return index
    for path in playbook_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        anchor_map = payload.get("anchor_map")
        if not isinstance(anchor_map, dict):
            continue
        for anchor, href in anchor_map.items():
            normalized_anchor = str(anchor or "").strip()
            normalized_href = str(href or "").strip()
            if normalized_anchor and normalized_href and normalized_anchor not in index:
                index[normalized_anchor] = _runtime_href_from_docs_href(normalized_href)
    return index


def _source_anchor_variants(anchor: str) -> tuple[str, ...]:
    normalized = str(anchor or "").strip()
    if not normalized:
        return ()
    variants = [normalized]
    if "_" in normalized:
        variants.append(f'{normalized.rsplit("_", 1)[0]}_{{context}}')
    return tuple(dict.fromkeys(variants))


@lru_cache(maxsize=1)
def _source_anchor_file_index(root_dir_str: str) -> dict[str, str]:
    repo_root = Path(root_dir_str) / "tmp_source" / "openshift-docs-enterprise-4.20"
    index: dict[str, str] = {}
    if not repo_root.exists():
        return index
    for path in repo_root.rglob("*.adoc"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for raw_line in lines:
            match = ADOC_ID_RE.match(raw_line.strip())
            if match is None:
                continue
            anchor_id = str(match.group("id") or "").strip()
            if anchor_id and anchor_id not in index:
                index[anchor_id] = str(path)
    return index


@lru_cache(maxsize=256)
def _source_file_lines(file_path_str: str) -> tuple[str, ...]:
    try:
        return tuple(Path(file_path_str).read_text(encoding="utf-8").splitlines())
    except Exception:  # noqa: BLE001
        return ()


@lru_cache(maxsize=128)
def _source_section_lines(root_dir_str: str, anchor: str) -> tuple[str, ...]:
    anchor_variants = _source_anchor_variants(anchor)
    if not anchor_variants:
        return ()
    anchor_file_index = _source_anchor_file_index(root_dir_str)
    for anchor_variant in anchor_variants:
        file_path_str = anchor_file_index.get(anchor_variant)
        if not file_path_str:
            continue
        lines = _source_file_lines(file_path_str)
        if not lines:
            continue
        for index, line in enumerate(lines):
            match = ADOC_ID_RE.match(line.strip())
            if match is None or str(match.group("id") or "").strip() != anchor_variant:
                continue
            collected: list[str] = []
            for candidate in lines[index + 1:]:
                if ADOC_ID_RE.match(candidate.strip()):
                    break
                collected.append(candidate.rstrip())
            return tuple(collected)
    return ()


def _source_overlay_href(root_dir: Path, raw_target: str) -> str:
    normalized = str(raw_target or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("http://") or normalized.startswith("https://") or normalized.startswith("/"):
        return normalized
    target_anchor = normalized.split("#", 1)[1].strip() if "#" in normalized else ""
    if target_anchor:
        anchor_index = _playbook_anchor_index(str(root_dir))
        href = anchor_index.get(target_anchor)
        if href:
            return href
    return ""


def _parse_source_bullet_href(root_dir: Path, bullet_text: str) -> str:
    link_match = ADOC_LINK_RE.search(bullet_text)
    if link_match is not None:
        return str(link_match.group("href") or "").strip()
    xref_match = ADOC_XREF_RE.search(bullet_text)
    if xref_match is None:
        return ""
    return _source_overlay_href(root_dir, str(xref_match.group("target") or "").strip())


def _source_section_overlay(root_dir: Path | None, anchor: str) -> dict[str, Any]:
    if root_dir is None:
        return {}
    lines = list(_source_section_lines(str(root_dir), anchor))
    if not lines:
        return {}
    overlay: dict[str, Any] = {"items": [], "additional_resources": [], "figure": {}}
    resource_mode = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == '[role="_additional-resources"]' or stripped.lower() == '.additional resources':
            resource_mode = True
            continue
        image_match = ADOC_IMAGE_RE.search(stripped)
        if image_match is not None:
            overlay["figure"] = {
                "asset_ref": str(image_match.group("asset_ref") or "").strip(),
                "caption": str(image_match.group("caption") or "").strip(),
            }
            continue
        bullet_match = ADOC_BULLET_RE.match(stripped)
        if bullet_match is None:
            continue
        href = _parse_source_bullet_href(root_dir, bullet_match.group("body"))
        target_list = overlay["additional_resources"] if resource_mode else overlay["items"]
        target_list.append({"href": href})
    return overlay


def _render_source_overlay_labeled_items(paragraphs: list[str], source_items: list[dict[str, str]]) -> str | None:
    items: list[str] = []
    index = 0
    source_index = 0
    while index < len(paragraphs):
        parsed = _extract_labeled_reader_item(paragraphs[index])
        if parsed is None:
            break
        _, label, body = parsed
        continuation_texts: list[str] = []
        index += 1
        while index < len(paragraphs) and _extract_labeled_reader_item(paragraphs[index]) is None:
            candidate = paragraphs[index]
            if candidate in ADDITIONAL_RESOURCES_LABELS:
                break
            continuation_texts.append(candidate)
            index += 1
        href = str(source_items[source_index].get("href") or "").strip() if source_index < len(source_items) else ""
        body_html = '<a href="{href}">{label}</a>'.format(
            href=html.escape(href, quote=True),
            label=_render_inline_html(body),
        ) if href else _render_inline_html(body)
        fragments = [
            '<div class="reader-list-item-body"><span class="reader-list-lead">{lead}</span> {body}</div>'.format(
                lead=html.escape(f"{label}:"),
                body=body_html,
            )
        ]
        for continuation in continuation_texts:
            for paragraph in _split_reader_display_paragraphs(continuation):
                fragments.append(f"<p>{_render_inline_html(paragraph)}</p>")
        items.append('<li class="reader-list-item">{}</li>'.format("".join(fragments)))
        source_index += 1
    return '<ul class="reader-bullet-list reader-bullet-list-labeled">{}</ul>'.format("".join(items)) if items else None


def _render_source_overlay_simple_items(items: list[str], source_items: list[dict[str, str]]) -> str | None:
    if not items:
        return None
    rendered: list[str] = []
    for index, item in enumerate(items):
        href = str(source_items[index].get("href") or "").strip() if index < len(source_items) else ""
        rendered.append(
            _render_link_list_item(
                item,
                candidate={"href": href} if href else None,
            )
        )
    return '<ul class="reader-bullet-list reader-bullet-list-linked">{}</ul>'.format("".join(rendered))


def _needs_source_overlay(paragraphs: list[str]) -> bool:
    for paragraph in paragraphs:
        text = " ".join(str(paragraph or "").split()).strip()
        if not text:
            continue
        if text in ADDITIONAL_RESOURCES_LABELS:
            return True
        if text.startswith("그림 "):
            return True
        if _extract_labeled_reader_item(text) is not None:
            return True
    return False


def _match_figure_overlay(paragraph: str, *, book_slug: str, root_dir: Path | None, overlay_figure: dict[str, Any]) -> str:
    asset_ref = str(overlay_figure.get("asset_ref") or "").strip()
    if not asset_ref:
        return ""
    asset = _figure_asset_by_name(book_slug, asset_ref)
    if asset is None:
        return ""
    return _render_figure_block_html(
        str(asset.get("asset_url") or "").strip(),
        caption=" ".join(str(paragraph or "").split()).strip(),
        alt=str(asset.get("alt") or asset.get("caption") or "").strip(),
        kind=str(asset.get("asset_kind") or "").strip(),
        diagram_type=str(asset.get("diagram_type") or "").strip(),
    )


def _match_section_link_candidate(
    text: str,
    *,
    link_candidates: list[dict[str, Any]],
    current_anchor: str,
) -> dict[str, Any] | None:
    query = " ".join(str(text or "").split()).strip()
    if not query:
        return None
    query_tokens = set(_link_match_tokens(query))
    if not query_tokens:
        return None
    query_normalized = " ".join(query_tokens)
    best_candidate: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in link_candidates:
        if str(candidate.get("anchor") or "") == current_anchor:
            continue
        heading_tokens = set(candidate.get("heading_tokens") or [])
        anchor_tokens = set(candidate.get("anchor_tokens") or [])
        comparison_tokens = heading_tokens | anchor_tokens
        if not comparison_tokens:
            continue
        shared_tokens = query_tokens & comparison_tokens
        if not shared_tokens:
            continue
        query_coverage = len(shared_tokens) / max(len(query_tokens), 1)
        candidate_coverage = len(shared_tokens) / max(len(comparison_tokens), 1)
        score = query_coverage * 0.65 + candidate_coverage * 0.35
        if heading_tokens and heading_tokens.issubset(query_tokens):
            score += 0.15
        if query_tokens.issubset(heading_tokens):
            score += 0.1
        if anchor_tokens and query_tokens.issubset(anchor_tokens):
            score += 0.08
        if score > best_score:
            best_candidate = candidate
            best_score = score
    return best_candidate if best_candidate is not None and best_score >= 0.52 else None


def _render_link_list_item(text: str, *, candidate: dict[str, Any] | None = None) -> str:
    match = LINK_PUNCTUATION_RE.match(" ".join(str(text or "").split()).strip())
    body = str(match.group("body") if match is not None else text).strip()
    tail = str(match.group("tail") if match is not None else "").strip()
    if candidate is None:
        return "<li>{}{}</li>".format(_render_inline_html(body), html.escape(tail))
    return '<li><a href="{href}">{label}</a>{tail}</li>'.format(
        href=html.escape(str(candidate.get("href") or ""), quote=True),
        label=_render_inline_html(body),
        tail=html.escape(tail),
    )


def _render_additional_resources_card(
    items: list[str],
    *,
    link_candidates: list[dict[str, Any]],
    current_anchor: str,
    source_items: list[dict[str, str]] | None = None,
) -> str:
    rendered_parts: list[str] = []
    for index, item in enumerate(items):
        if not str(item).strip():
            continue
        source_href = ""
        if source_items and index < len(source_items):
            source_href = str(source_items[index].get("href") or "").strip()
        candidate = {"href": source_href} if source_href else _match_section_link_candidate(item, link_candidates=link_candidates, current_anchor=current_anchor)
        rendered_parts.append(_render_link_list_item(item, candidate=candidate))
    rendered_items = "".join(rendered_parts)
    if not rendered_items:
        return ""
    return """
    <aside class="additional-resources-card">
      <p class="additional-resources-title"><strong>추가 리소스</strong></p>
      <ul class="reader-bullet-list additional-resources-list">{items}</ul>
    </aside>
    """.format(items=rendered_items).strip()


def _render_paragraph_only_playbook_section_html(
    row: dict[str, Any],
    *,
    link_candidates: list[dict[str, Any]],
    root_dir: Path | None = None,
    book_slug: str = "",
) -> str:
    paragraphs = [
        " ".join(str(block.get("text") or "").split()).strip()
        for block in (row.get("blocks") or [])
        if isinstance(block, dict) and str(block.get("text") or "").strip()
    ]
    if not paragraphs:
        return ""
    current_anchor = str(row.get("anchor") or "").strip()
    source_overlay = _source_section_overlay(root_dir, current_anchor) if _needs_source_overlay(paragraphs) else {}
    source_items = list(source_overlay.get("items") or [])
    source_resources = list(source_overlay.get("additional_resources") or [])
    source_figure = source_overlay.get("figure") if isinstance(source_overlay.get("figure"), dict) else {}
    fragments: list[str] = []
    task_items: list[str] = []
    index = 0

    def flush_task_items() -> None:
        nonlocal task_items
        if not task_items:
            return
        source_html = _render_source_overlay_simple_items(task_items, source_items) if source_items else None
        if source_html is not None:
            fragments.append(source_html)
        else:
            rendered = []
            for item in task_items:
                candidate = _match_section_link_candidate(item, link_candidates=link_candidates, current_anchor=current_anchor)
                rendered.append(_render_link_list_item(item, candidate=candidate))
            fragments.append('<ul class="reader-bullet-list reader-bullet-list-linked">{}</ul>'.format("".join(rendered)))
        task_items = []

    while index < len(paragraphs):
        current = paragraphs[index]
        if source_items and _extract_labeled_reader_item(current) is not None:
            flush_task_items()
            labeled_html = _render_source_overlay_labeled_items(paragraphs[index:], source_items)
            if labeled_html is not None:
                fragments.append(labeled_html)
                while index < len(paragraphs):
                    candidate = paragraphs[index]
                    if candidate in ADDITIONAL_RESOURCES_LABELS:
                        break
                    index += 1
                continue
        if current.startswith("그림 ") and source_figure:
            flush_task_items()
            figure_html = _match_figure_overlay(current, book_slug=book_slug, root_dir=root_dir, overlay_figure=source_figure)
            if figure_html:
                fragments.append(figure_html)
                index += 1
                continue
        if current in ADDITIONAL_RESOURCES_LABELS:
            flush_task_items()
            resource_items: list[str] = []
            index += 1
            while index < len(paragraphs):
                resource_items.append(paragraphs[index])
                index += 1
            resource_html = _render_additional_resources_card(
                resource_items,
                link_candidates=link_candidates,
                current_anchor=current_anchor,
                source_items=source_resources,
            )
            if resource_html:
                fragments.append(resource_html)
            break
        candidate = _match_section_link_candidate(current, link_candidates=link_candidates, current_anchor=current_anchor)
        if candidate is not None and len(current) <= 96:
            task_items.append(current)
            index += 1
            continue
        flush_task_items()
        fragments.extend(_render_normal_paragraph(current))
        index += 1
    flush_task_items()
    return "\n".join(fragment for fragment in fragments if fragment)


def _render_page_overlay_toolbar(
    *,
    target_kind: str,
    target_ref: str,
    title: str,
    book_slug: str = "",
    anchor: str = "",
    asset_name: str = "",
    entity_slug: str = "",
    viewer_path: str = "",
) -> str:
    return """
    <div class="overlay-page-target" hidden data-page-root="true" data-target-kind="{target_kind}" data-target-ref="{target_ref}" data-target-title="{title}" data-book-slug="{book_slug}" data-anchor="{anchor}" data-asset-name="{asset_name}" data-entity-slug="{entity_slug}" data-viewer-path="{viewer_path}"></div>
    """.format(
        target_kind=html.escape(target_kind, quote=True),
        target_ref=html.escape(target_ref, quote=True),
        title=html.escape(title, quote=True),
        book_slug=html.escape(book_slug, quote=True),
        anchor=html.escape(anchor, quote=True),
        asset_name=html.escape(asset_name, quote=True),
        entity_slug=html.escape(entity_slug, quote=True),
        viewer_path=html.escape(viewer_path, quote=True),
    ).strip()


def _build_study_section_cards(
    sections: list[dict[str, Any]],
    *,
    book_slug: str = "",
    target_anchor: str = "",
    embedded: bool = False,
    root_dir: Path | None = None,
) -> list[str]:
    cards: list[str] = []
    link_candidates = _build_section_link_candidates(sections, book_slug=book_slug)
    for row in sections:
        anchor = str(row.get("anchor") or "")
        heading = str(row.get("heading") or "")
        display_heading = _display_heading(heading)
        section_path = [
            _display_heading(str(item))
            for item in (row.get("section_path") or row.get("path") or [])
            if str(item).strip()
        ]
        level = max(1, int(row.get("level") or row.get("section_level") or len(section_path) or 1))
        breadcrumb = " > ".join(item for item in section_path if item) if section_path else display_heading
        section_text = _clean_source_view_text(str(row.get("text") or ""))
        is_target = bool(target_anchor) and anchor == target_anchor
        blocks = [dict(block) for block in (row.get("blocks") or []) if isinstance(block, dict)]
        paragraph_only_blocks = blocks and all(
            str(block.get("kind") or "").strip() == "paragraph"
            for block in blocks
        )
        rendered_body = (
            _render_paragraph_only_playbook_section_html(row, link_candidates=link_candidates, root_dir=root_dir, book_slug=book_slug)
            if paragraph_only_blocks
            else (
                "\n".join(
                    fragment for fragment in (_render_playbook_block_html(block) for block in blocks) if fragment
                )
                if blocks
                else _render_normalized_section_html(section_text)
            )
        )
        if embedded:
            cards.append(
                """
                <section id="{anchor}" class="embedded-section{target_class}">
                  <div class="section-header">
                    <div class="section-meta">{breadcrumb}</div>
                    <h2>{heading}</h2>
                  </div>
                  <div class="section-body">{text}</div>
                </section>
                """.format(
                    anchor=html.escape(anchor, quote=True),
                    target_class=" is-target" if is_target else "",
                    breadcrumb=html.escape(breadcrumb),
                    heading=html.escape(display_heading),
                    text=rendered_body,
                ).strip()
            )
            continue
        cards.append(
            """
            <section id="{anchor}" class="section-card section-level-{level}{target_class}" data-semantic-role="{semantic_role}" data-section-level="{level}">
              <div class="section-header">
                <div class="section-meta">{breadcrumb}</div>
                <h2>{heading}</h2>
              </div>
              <div class="section-body">{text}</div>
            </section>
            """.format(
                anchor=html.escape(anchor, quote=True),
                level=level,
                target_class=" is-target" if is_target else "",
                semantic_role=html.escape(str(row.get("semantic_role") or "").strip(), quote=True),
                breadcrumb=html.escape(breadcrumb),
                heading=html.escape(display_heading),
                text=rendered_body,
            ).strip()
        )
    return cards


def _build_section_outline(sections: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, str]]:
    outline: list[dict[str, str]] = []
    for row in sections:
        anchor = str(row.get("anchor") or "").strip()
        heading = _display_heading(str(row.get("heading") or ""))
        if not anchor or not heading:
            continue
        path = [
            _display_heading(str(item))
            for item in (row.get("section_path") or row.get("path") or [])
            if str(item).strip()
        ]
        outline.append(
            {
                "anchor": anchor,
                "heading": heading,
                "path": " > ".join(item for item in path if item) or heading,
            }
        )
        if len(outline) >= limit:
            break
    return outline


def _build_section_metrics(sections: list[dict[str, Any]]) -> list[str]:
    semantic_counts: dict[str, int] = {}
    figure_count = 0
    code_count = 0
    table_count = 0
    for row in sections:
        semantic_role = str(row.get("semantic_role") or "").strip().lower()
        if semantic_role:
            semantic_counts[semantic_role] = semantic_counts.get(semantic_role, 0) + 1
        for block in row.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("kind") or "").strip().lower()
            if kind == "figure":
                figure_count += 1
            elif kind == "code":
                code_count += 1
            elif kind == "table":
                table_count += 1
    metrics = [f"섹션 {len(sections)}"]
    if semantic_counts.get("procedure"):
        metrics.append(f"절차 {semantic_counts['procedure']}")
    if semantic_counts.get("reference"):
        metrics.append(f"참조 {semantic_counts['reference']}")
    if figure_count:
        metrics.append(f"figure {figure_count}")
    if table_count:
        metrics.append(f"table {table_count}")
    if code_count:
        metrics.append(f"code {code_count}")
    return metrics[:5]


__all__ = [
    "_build_section_metrics",
    "_build_section_outline",
    "_build_study_section_cards",
    "_display_heading",
    "_render_page_overlay_toolbar",
]
