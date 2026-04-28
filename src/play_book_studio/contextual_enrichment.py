from __future__ import annotations

import re
from typing import Any


CONTEXTUAL_ENRICHMENT_VERSION = "contextual-retrieval-v1"
SPACE_RE = re.compile(r"\s+")
LINE_RE = re.compile(r"\r?\n+")


def _clean_text(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip())


def _list_strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    elif value:
        raw_items = [value]
    else:
        raw_items = []
    items: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _clean_text(raw)
        if not item or item.casefold() in seen:
            continue
        seen.add(item.casefold())
        items.append(item)
    return items


def contextual_heading_path(row: dict[str, Any]) -> list[str]:
    path = _list_strings(row.get("section_path"))
    for key in ("chapter", "section"):
        value = _clean_text(row.get(key))
        if value and value.casefold() not in {item.casefold() for item in path}:
            path.append(value)
    return path


def contextual_parent_title(row: dict[str, Any]) -> str:
    return _clean_text(row.get("book_title") or row.get("original_title") or row.get("book_slug"))


def _source_label(row: dict[str, Any]) -> str:
    lane = _clean_text(row.get("source_lane"))
    collection = _clean_text(row.get("source_collection"))
    source_type = _clean_text(row.get("source_type"))
    parts = [part for part in (lane, collection, source_type) if part]
    return " / ".join(parts)


def _first_body_excerpt(row: dict[str, Any], *, max_chars: int = 260) -> str:
    text = str(row.get("text") or "").strip()
    if not text:
        return ""
    parent_title = contextual_parent_title(row).casefold()
    heading_values = {item.casefold() for item in contextual_heading_path(row)}
    paragraphs = [part.strip() for part in LINE_RE.split(text) if part.strip()]
    for paragraph in paragraphs:
        normalized = _clean_text(paragraph)
        if not normalized:
            continue
        folded = normalized.casefold()
        if folded == parent_title or folded in heading_values:
            continue
        if normalized.startswith("[CODE") or normalized.startswith("[TABLE") or normalized.startswith("[FIGURE"):
            continue
        return normalized[:max_chars].rstrip()
    return _clean_text(text)[:max_chars].rstrip()


def build_contextual_prefix(row: dict[str, Any], *, max_chars: int = 900) -> str:
    parent = contextual_parent_title(row)
    path = contextual_heading_path(row)
    lines: list[str] = []
    if parent:
        lines.append(f"문서: {parent}")
    if path:
        lines.append(f"경로: {' > '.join(path)}")
    source = _source_label(row)
    if source:
        lines.append(f"출처: {source}")
    role = _clean_text(row.get("semantic_role") or row.get("chunk_type"))
    if role:
        lines.append(f"역할: {role}")
    commands = _list_strings(row.get("cli_commands"))[:4]
    if commands:
        lines.append(f"명령: {', '.join(commands)}")
    objects = _list_strings(row.get("k8s_objects"))[:4]
    if objects:
        lines.append(f"Kubernetes 객체: {', '.join(objects)}")
    operators = _list_strings(row.get("operator_names"))[:3]
    if operators:
        lines.append(f"Operator: {', '.join(operators)}")
    excerpt = _first_body_excerpt(row)
    if excerpt:
        lines.append(f"요약: {excerpt}")
    prefix = "\n".join(lines).strip()
    if len(prefix) <= max_chars:
        return prefix
    return prefix[:max_chars].rstrip()


def contextual_search_text(row: dict[str, Any]) -> str:
    prefix = str(row.get("contextual_prefix") or "").strip() or build_contextual_prefix(row)
    body = str(row.get("text") or "").strip()
    if not prefix:
        return body
    if not body:
        return prefix
    return f"{prefix}\n\n{body}"


def enrich_contextual_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    enriched["contextual_enrichment_version"] = str(
        enriched.get("contextual_enrichment_version") or CONTEXTUAL_ENRICHMENT_VERSION
    )
    enriched["contextual_parent_title"] = str(
        enriched.get("contextual_parent_title") or contextual_parent_title(enriched)
    )
    enriched["contextual_heading_path"] = _list_strings(
        enriched.get("contextual_heading_path") or contextual_heading_path(enriched)
    )
    enriched["contextual_prefix"] = str(
        enriched.get("contextual_prefix") or build_contextual_prefix(enriched)
    )
    return enriched


def has_contextual_enrichment(row: dict[str, Any]) -> bool:
    return (
        str(row.get("contextual_enrichment_version") or "") == CONTEXTUAL_ENRICHMENT_VERSION
        and bool(_clean_text(row.get("contextual_parent_title")))
        and bool(_list_strings(row.get("contextual_heading_path")))
        and bool(_clean_text(row.get("contextual_prefix")))
    )
