from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .source_books_wiki_relations import (
    _book_related_sections,
    _candidate_relations,
    _chat_link_truth_payload,
    _chat_navigation_aliases,
    _contains_hangul,
    _is_final_runtime_href,
    _link_book_slug,
    _prefer_korean_book_links,
    _rewrite_book_href,
    _wiki_relation_items,
)
from .source_books_viewer_resolver import (
    ACTIVE_RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE,
    ENTITY_HUB_VIEWER_PATH_RE,
    FIGURE_VIEWER_PATH_RE,
    MARKDOWN_VIEWER_PATH_RE,
    RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE,
)
from .wiki_user_overlay import build_wiki_overlay_signal_payload


_OVERLAY_SIGNAL_CACHE_TTL_SECONDS = 30.0
_OVERLAY_SIGNAL_CACHE_LOCK = threading.Lock()
_OVERLAY_SIGNAL_CACHE: dict[tuple[str, str], tuple[float, dict[str, int], dict[str, int]]] = {}


def _overlay_recent_target_scores(
    root_dir: Path,
    *,
    user_id: str | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return {}, {}
    cache_key = (str(root_dir.resolve()), normalized_user_id)
    now = time.monotonic()
    with _OVERLAY_SIGNAL_CACHE_LOCK:
        cached = _OVERLAY_SIGNAL_CACHE.get(cache_key)
        if cached is not None:
            cached_at, href_scores, ref_scores = cached
            if now - cached_at <= _OVERLAY_SIGNAL_CACHE_TTL_SECONDS:
                return dict(href_scores), dict(ref_scores)
    try:
        payload = build_wiki_overlay_signal_payload(root_dir, user_id=normalized_user_id)
    except Exception:  # noqa: BLE001
        return {}, {}
    user_focus = payload.get("user_focus") if isinstance(payload, dict) else None
    recent_targets = user_focus.get("recent_targets") if isinstance(user_focus, dict) else None
    if not isinstance(recent_targets, list):
        return {}, {}
    href_scores: dict[str, int] = {}
    ref_scores: dict[str, int] = {}
    for index, item in enumerate(recent_targets[:12]):
        if not isinstance(item, dict):
            continue
        base_score = max(10, 80 - index * 6)
        href = _rewrite_book_href(root_dir, str(item.get("href") or "").strip())
        target_ref = str(item.get("target_ref") or "").strip()
        if href:
            href_scores[href] = max(href_scores.get(href, 0), base_score)
        if target_ref:
            ref_scores[target_ref] = max(ref_scores.get(target_ref, 0), base_score)
    with _OVERLAY_SIGNAL_CACHE_LOCK:
        _OVERLAY_SIGNAL_CACHE[cache_key] = (now, dict(href_scores), dict(ref_scores))
        if len(_OVERLAY_SIGNAL_CACHE) > 64:
            stale_keys = [
                key
                for key, (cached_at, _, _) in _OVERLAY_SIGNAL_CACHE.items()
                if now - cached_at > _OVERLAY_SIGNAL_CACHE_TTL_SECONDS
            ]
            for stale_key in stale_keys:
                _OVERLAY_SIGNAL_CACHE.pop(stale_key, None)
    return href_scores, ref_scores


def _link_target_ref(kind: str, href: str) -> str:
    normalized_kind = str(kind or "").strip()
    normalized_href = str(href or "").strip()
    parsed = urlparse(normalized_href)
    request_path = parsed.path.strip()
    entity_match = ENTITY_HUB_VIEWER_PATH_RE.match(request_path)
    if entity_match:
        return f"entity:{entity_match.group(1)}"
    figure_match = FIGURE_VIEWER_PATH_RE.match(request_path)
    if figure_match:
        return f"figure:{figure_match.group(1)}:{figure_match.group(2)}"
    active_book_match = ACTIVE_RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE.match(request_path)
    if active_book_match:
        slug = active_book_match.group(1)
        if normalized_kind == "section":
            anchor = parsed.fragment.strip()
            if anchor:
                return f"section:{slug}#{anchor}"
        return f"book:{slug}"
    runtime_book_match = RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE.match(request_path)
    if runtime_book_match:
        slug = runtime_book_match.group(2)
        if normalized_kind == "section":
            anchor = parsed.fragment.strip()
            if anchor:
                return f"section:{slug}#{anchor}"
        return f"book:{slug}"
    gold_book_match = MARKDOWN_VIEWER_PATH_RE.match(request_path)
    if gold_book_match:
        slug = gold_book_match.group(1)
        if normalized_kind == "section":
            anchor = parsed.fragment.strip()
            if anchor:
                return f"section:{slug}#{anchor}"
        return f"book:{slug}"
    return ""


def build_chat_navigation_links(
    root_dir: Path,
    citations: list[dict[str, Any]] | list[Any],
    *,
    user_id: str | None = None,
) -> list[dict[str, str]]:
    direct_links: list[dict[str, str]] = []
    direct_seen: set[str] = set()
    direct_slug_seen: set[str] = set()
    href_scores, ref_scores = _overlay_recent_target_scores(root_dir, user_id=user_id)
    direct_counts: dict[str, int] = {}
    rewritten_href_cache: dict[str, str] = {}
    truth_payload_cache: dict[tuple[str, str], dict[str, str]] = {}

    def _rewrite_cached(href: str) -> str:
        normalized_href = str(href or "").strip()
        if normalized_href not in rewritten_href_cache:
            rewritten_href_cache[normalized_href] = _rewrite_book_href(root_dir, normalized_href)
        return rewritten_href_cache[normalized_href]

    def _truth_payload_cached(href: str, kind: str) -> dict[str, str]:
        cache_key = (str(href or "").strip(), str(kind or "").strip())
        if cache_key not in truth_payload_cache:
            truth_payload_cache[cache_key] = _chat_link_truth_payload(
                root_dir,
                cache_key[0],
                cache_key[1],
            )
        return truth_payload_cache[cache_key]

    for citation in citations:
        if not isinstance(citation, dict):
            continue
        href = _rewrite_cached(str(citation.get("href") or "").strip())
        if not _is_final_runtime_href(href):
            continue
        book_slug = str(citation.get("book_slug") or _link_book_slug(href)).strip()
        if not book_slug:
            continue
        direct_counts[href] = direct_counts.get(href, 0) + 1
        if href in direct_seen or book_slug in direct_slug_seen:
            continue
        book_title = str(citation.get("book_title") or "").strip()
        source_label = str(citation.get("source_label") or "").strip()
        section_label = str(citation.get("section_path_label") or citation.get("section") or "").strip()
        label = book_title or source_label.split(" · ", 1)[0].strip() or book_slug.replace("_", " ").title()
        summary = section_label or source_label
        if not label:
            continue
        direct_seen.add(href)
        direct_slug_seen.add(book_slug)
        direct_links.append(
            {
                "label": label,
                "href": href,
                "kind": "book",
                "summary": summary,
                **_truth_payload_cached(href, "book"),
            }
        )

    if direct_links:
        ranked_direct_links = sorted(
            direct_links,
            key=lambda item: (
                -max(
                    direct_counts.get(str(item.get("href") or "").strip(), 0) * 100,
                    href_scores.get(str(item.get("href") or "").strip(), 0),
                    ref_scores.get(
                        _link_target_ref(
                            str(item.get("kind") or "").strip(),
                            str(item.get("href") or "").strip(),
                        ),
                        0,
                    ),
                ),
                0 if _contains_hangul(str(item.get("label") or "")) else 1,
                str(item.get("label") or ""),
            ),
        )
        return ranked_direct_links[:2]

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    slug_seen: set[str] = set()
    semantic_seen: set[str] = set()
    alias_map = _chat_navigation_aliases()
    relation_map = _candidate_relations()

    def duplicate_semantic(label: str, kind: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(label or "").strip().lower())
        if not normalized:
            return False
        keys = {normalized, f"{kind}:{normalized}"}
        if any(key in semantic_seen for key in keys):
            return True
        semantic_seen.update(keys)
        return False

    for citation in citations:
        if not isinstance(citation, dict):
            continue
        slug = str(citation.get("book_slug") or "").strip()
        if slug and slug in alias_map:
            for item in alias_map.get(slug, []):
                kind = str(item.get("kind") or "book")
                if kind != "book":
                    continue
                href = str(item.get("href") or "").strip()
                label = str(item.get("label") or "").strip()
                rewritten_href = _rewrite_cached(href)
                book_slug = _link_book_slug(rewritten_href)
                if (
                    not href
                    or not label
                    or not _is_final_runtime_href(rewritten_href)
                    or rewritten_href in seen
                    or (book_slug and book_slug in slug_seen)
                    or duplicate_semantic(label, kind)
                ):
                    continue
                seen.add(rewritten_href)
                if book_slug:
                    slug_seen.add(book_slug)
                links.append(
                    {
                        "label": label,
                        "href": rewritten_href,
                        "kind": kind,
                        **_truth_payload_cached(rewritten_href, kind),
                    }
                )
        relation = relation_map.get(slug) if slug else None
        if relation is None and not slug:
            continue
        if relation is None:
            excerpt = str(citation.get("excerpt") or "")
            section = str(citation.get("section") or "")
            haystack = f"{slug} {section} {excerpt}".lower()
            if "etcd" in haystack:
                relation = relation_map.get("backup_and_restore")
            elif "machine config" in haystack or "mco" in haystack:
                relation = relation_map.get("machine_configuration")
            elif "prometheus" in haystack or "alert" in haystack or "monitoring" in haystack:
                relation = relation_map.get("monitoring_troubleshooting")
        if relation is None:
            continue
        for item in _wiki_relation_items(relation, "related_docs")[:2]:
            href = str(item.get("href") or "").strip()
            label = str(item.get("label") or "").strip()
            rewritten_href = _rewrite_cached(href)
            book_slug = _link_book_slug(rewritten_href)
            if (
                not href
                or not label
                or not _is_final_runtime_href(rewritten_href)
                or rewritten_href in seen
                or (book_slug and book_slug in slug_seen)
                or duplicate_semantic(label, "book")
            ):
                continue
            seen.add(rewritten_href)
            if book_slug:
                slug_seen.add(book_slug)
            links.append(
                {
                    "label": label,
                    "href": rewritten_href,
                    "kind": "book",
                    **_truth_payload_cached(rewritten_href, "book"),
                }
            )
        if len(links) >= 2:
            break
    links = _prefer_korean_book_links(links)
    ranked_links = sorted(
        links,
        key=lambda item: (
            -max(
                href_scores.get(str(item.get("href") or "").strip(), 0),
                ref_scores.get(
                    _link_target_ref(
                        str(item.get("kind") or "").strip(),
                        str(item.get("href") or "").strip(),
                    ),
                    0,
                ),
            ),
            0 if _contains_hangul(str(item.get("label") or "")) else 1,
            str(item.get("label") or ""),
        ),
    )
    return ranked_links[:2]


_SECTION_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_-]+")


def _tokenize_section_text(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in _SECTION_TOKEN_RE.findall(str(part or "").lower()):
            normalized = token.strip("-_ ")
            if len(normalized) >= 2:
                tokens.add(normalized)
    return tokens


def _section_link_score(item: dict[str, Any], citation: dict[str, Any]) -> int:
    score = 0
    item_href = str(item.get("href") or "").strip()
    item_label = str(item.get("label") or "").strip()
    item_summary = str(item.get("summary") or "").strip()
    citation_href = str(citation.get("href") or "").strip()
    citation_section = str(citation.get("section") or "").strip()
    citation_excerpt = str(citation.get("excerpt") or "").strip()
    citation_source_label = str(citation.get("source_label") or "").strip()

    if citation_href and item_href == citation_href:
        score += 1000
    if citation_section and item_label:
        lowered_section = citation_section.lower()
        lowered_label = item_label.lower()
        if lowered_section == lowered_label:
            score += 300
        elif lowered_section in lowered_label or lowered_label in lowered_section:
            score += 120

    citation_tokens = _tokenize_section_text(citation_section, citation_excerpt, citation_source_label)
    item_tokens = _tokenize_section_text(item_label, item_summary)
    overlap = citation_tokens & item_tokens
    score += len(overlap) * 15

    if citation_excerpt and item_summary:
        lowered_excerpt = citation_excerpt.lower()
        lowered_summary = item_summary.lower()
        if lowered_summary and lowered_summary in lowered_excerpt:
            score += 40
        elif lowered_excerpt and lowered_excerpt[:80] in lowered_summary:
            score += 20

    return score


def build_chat_section_links(
    root_dir: Path,
    citations: list[dict[str, Any]] | list[Any],
    *,
    user_id: str | None = None,
) -> list[dict[str, str]]:
    candidates: dict[str, dict[str, Any]] = {}
    label_seen: set[str] = set()
    slug_seen: set[str] = set()
    href_scores, ref_scores = _overlay_recent_target_scores(root_dir, user_id=user_id)
    direct_candidate_count = 0
    rewritten_href_cache: dict[str, str] = {}
    related_sections_cache: dict[str, list[dict[str, Any]]] = {}

    def _rewrite_cached(href: str) -> str:
        normalized_href = str(href or "").strip()
        if normalized_href not in rewritten_href_cache:
            rewritten_href_cache[normalized_href] = _rewrite_book_href(root_dir, normalized_href)
        return rewritten_href_cache[normalized_href]

    def _related_sections_cached(slug: str) -> list[dict[str, Any]]:
        normalized_slug = str(slug or "").strip()
        if normalized_slug not in related_sections_cache:
            related_sections_cache[normalized_slug] = list(_book_related_sections(normalized_slug))
        return related_sections_cache[normalized_slug]

    for citation in citations:
        if not isinstance(citation, dict):
            continue
        slug = str(citation.get("book_slug") or "").strip()
        if not slug:
            continue
        citation_href = str(citation.get("href") or "").strip()
        citation_section = str(citation.get("section") or "").strip()
        if citation_href and citation_section:
            rewritten_citation_href = _rewrite_cached(citation_href)
            if _is_final_runtime_href(rewritten_citation_href) and _contains_hangul(citation_section):
                direct_candidate = {
                    "label": citation_section,
                    "href": rewritten_citation_href,
                    "kind": "section",
                    "summary": str(citation.get("source_label") or "").strip(),
                }
                candidates[rewritten_citation_href] = {
                    **direct_candidate,
                    "_score": max(int(candidates.get(rewritten_citation_href, {}).get("_score", 0)), 1500),
                }
                direct_candidate_count += 1
        if direct_candidate_count > 0:
            continue
        for item in _related_sections_cached(slug):
            href = str(item.get("href") or "").strip()
            label = str(item.get("label") or "").strip()
            if not href or not label:
                continue
            score = _section_link_score(item, citation)
            current = candidates.get(href)
            rewritten_href = _rewrite_cached(href)
            if not _is_final_runtime_href(rewritten_href) or not _contains_hangul(label):
                continue
            if current is None or score > int(current.get("_score", 0)):
                candidates[href] = {
                    "label": label,
                    "href": rewritten_href,
                    "kind": "section",
                    "summary": str(item.get("summary") or "").strip(),
                    "_score": score,
                }
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -max(
                int(item.get("_score", 0)),
                href_scores.get(str(item.get("href") or "").strip(), 0),
                ref_scores.get(
                    _link_target_ref(
                        "section",
                        str(item.get("href") or "").strip(),
                    ),
                    0,
                ),
            ),
            str(item.get("label") or ""),
        ),
    )
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in ranked:
        href = str(item.get("href") or "").strip()
        label = str(item.get("label") or "").strip()
        normalized_label = re.sub(r"\s+", " ", label.lower())
        book_slug = _link_book_slug(href)
        if (
            not href
            or href in seen
            or (normalized_label and normalized_label in label_seen)
            or (book_slug and book_slug in slug_seen)
        ):
            continue
        seen.add(href)
        if normalized_label:
            label_seen.add(normalized_label)
        if book_slug:
            slug_seen.add(book_slug)
        links.append(
            {
                "label": label,
                "href": href,
                "kind": "section",
                "summary": str(item.get("summary") or "").strip(),
            }
        )
        if len(links) >= 2:
            break
    return links


__all__ = [
    "build_chat_navigation_links",
    "build_chat_section_links",
]
