from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from play_book_studio.intake.artifact_bundle import iter_customer_pack_book_payload_paths
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary

from .bm25 import BM25Index, tokenize_text
from .intake_overlay import (
    customer_pack_row_from_section,
    filter_customer_pack_hits_by_selection,
    has_active_customer_pack_selection,
    load_selected_customer_pack_private_bm25_index,
    _runtime_eligible_selected_draft_ids,
    search_selected_customer_pack_private_vectors,
)
from .models import RetrievalHit
from .query import has_doc_locator_intent, is_explainer_query
from .ranking import (
    rrf_merge_hit_lists as _rrf_merge_hit_lists,
    rrf_merge_named_hit_lists as _rrf_merge_named_hit_lists,
    summarize_hit_list as _summarize_hit_list,
)
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event
from .vector import hit_from_payload


_CUSTOMER_PACK_TITLE_QUERY_STOPWORDS = frozenset(
    {
        "찾아",
        "찾아줘",
        "찾아줄래",
        "보여줘",
        "열어줘",
        "알려줘",
        "문서",
        "자료",
        "파일",
        "ppt",
        "pptx",
        "deck",
        "slide",
        "slides",
        "슬라이드",
        "해줘",
        "줘",
    }
)
_CUSTOMER_PACK_TITLE_TEXT_RE = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)
_CUSTOMER_PACK_EXPLICIT_LOCATOR_RE = re.compile(
    r"(어디서|어디 있어|어디를|찾아|찾을|열어|보여|보고 싶|참고할|경로|위치|이동|들어가|"
    r"파일|ppt|pptx|slide|slides|슬라이드|문서\s*(?:목록|위치|경로)|자료\s*(?:목록|위치|경로))",
    re.IGNORECASE,
)
_OFFICIAL_TITLE_QUERY_STOPWORDS = frozenset(
    {
        "공식",
        "공식문서",
        "공식매뉴얼",
        "문서",
        "매뉴얼",
        "기준",
        "요약",
        "설명",
        "설명해줘",
        "알려줘",
        "대해",
        "관련",
        "에서",
        "ocp",
        "openshift",
        "container",
        "platform",
        "official",
        "docs",
        "doc",
        "manual",
        "manuals",
        "install",
        "installing",
        "installation",
        "using",
        "uses",
        "use",
        "build",
        "builds",
        "building",
        "migration",
    }
)
_OFFICIAL_RUNTIME_SOURCE_RE = re.compile(
    r"(공식\s*(?:문서|매뉴얼)|ocp\s*공식|openshift\s*공식|official\s*(?:docs?|manuals?))",
    re.IGNORECASE,
)
_CUSTOMER_PACK_EXPLICIT_QUERY_TOKENS = (
    "업로드 문서",
    "업로드한 문서",
    "업로드 자료",
    "업로드자료",
    "유저 업로드",
    "사용자 업로드",
    "고객 문서",
    "고객문서",
    "고객 자료",
    "고객자료",
    "고객 ppt",
    "고객ppt",
    "고객 운영북",
    "운영북",
    "ppt 자료",
    "ppt자료",
    "우리 문서",
    "our document",
    "customer pack",
    "customer-pack",
)
_CUSTOMER_PACK_BROAD_CONTEXT_TOKENS = (
    "자료",
    "문서",
    "운영",
    "설계",
    "ppt",
    "pptx",
    "ci/cd",
    "cicd",
    "운영북",
)
_OFFICIAL_RUNTIME_TOPIC_RE = re.compile(r"\b(?:ocp|openshift)\b", re.IGNORECASE)
_OFFICIAL_DECISIVE_TITLE_TOKENS = frozenset(
    {
        "buildconfig",
        "buildconfigs",
        "podnetworkconnectivitycheck",
    }
)


def _compact_customer_pack_title_text(text: str) -> str:
    return _CUSTOMER_PACK_TITLE_TEXT_RE.sub("", (text or "").lower())


def _customer_pack_locator_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in tokenize_text(text)
        if len(token) >= 2 and token not in _CUSTOMER_PACK_TITLE_QUERY_STOPWORDS
    )


def _official_runtime_manifest_path(retriever) -> Path:
    return retriever.settings.root_dir / "data" / "wiki_runtime_books" / "active_manifest.json"


def _official_runtime_title_fingerprint(manifest_path: Path) -> tuple[tuple[str, int], ...]:
    if not manifest_path.exists():
        return ()
    return ((str(manifest_path), manifest_path.stat().st_mtime_ns),)


def _official_title_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in tokenize_text(text):
        normalized = token.strip().lower()
        if len(normalized) < 2:
            continue
        if normalized in _OFFICIAL_TITLE_QUERY_STOPWORDS:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tuple(tokens)


def _official_title_candidates(entry: dict[str, object]) -> tuple[str, ...]:
    candidates: list[str] = []
    for raw in (
        entry.get("title"),
        entry.get("book_title"),
        entry.get("canonical_title"),
        entry.get("slug"),
    ):
        value = str(raw or "").strip()
        if value:
            candidates.append(value)
            if raw == entry.get("slug"):
                candidates.append(value.replace("_", " ").replace("-", " "))
    source_ref = str(entry.get("source_ref") or entry.get("source_url") or "").strip()
    if source_ref:
        stem = source_ref.rstrip("/").rsplit("/", maxsplit=1)[-1]
        if stem and stem != "index":
            candidates.append(stem.replace("_", " ").replace("-", " "))
        if "/html-single/" in source_ref:
            slug_part = source_ref.split("/html-single/", maxsplit=1)[-1].split("/", maxsplit=1)[0]
            if slug_part:
                candidates.append(slug_part)
                candidates.append(slug_part.replace("_", " ").replace("-", " "))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        compact = _compact_customer_pack_title_text(candidate)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(candidate)
    return tuple(deduped)


@lru_cache(maxsize=4)
def _official_runtime_title_catalog(
    manifest_path_str: str,
    fingerprint: tuple[tuple[str, int], ...],
) -> tuple[dict[str, object], ...]:
    del fingerprint
    path = Path(manifest_path_str)
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return ()
    catalog: list[dict[str, object]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        slug = str(raw_entry.get("slug") or "").strip()
        if not slug:
            continue
        candidates = _official_title_candidates(raw_entry)
        if not candidates:
            continue
        catalog.append(
            {
                "slug": slug,
                "title_candidates": candidates,
                "review_status": str(raw_entry.get("review_status") or "").strip(),
            }
        )
    return tuple(catalog)


def _mentions_official_runtime_sources(query: str) -> bool:
    return bool(_OFFICIAL_RUNTIME_SOURCE_RE.search(query or ""))


def _has_official_runtime_signal(query: str) -> bool:
    return _mentions_official_runtime_sources(query) or bool(_OFFICIAL_RUNTIME_TOPIC_RE.search(query or ""))


def _has_broad_customer_pack_signal(lowered_query: str) -> bool:
    return "고객" in lowered_query and any(
        token in lowered_query for token in _CUSTOMER_PACK_BROAD_CONTEXT_TOKENS
    )


def _is_customer_pack_explicit_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(token in lowered for token in _CUSTOMER_PACK_EXPLICIT_QUERY_TOKENS) or _has_broad_customer_pack_signal(
        lowered
    )


def _official_title_match_score(query: str, *, title_candidates: tuple[str, ...]) -> float:
    compact_query = _compact_customer_pack_title_text(query)
    if not compact_query:
        return 0.0
    query_tokens = set(_official_title_tokens(query))
    official_source_mentioned = _has_official_runtime_signal(query)
    best_score = 0.0
    for candidate in title_candidates:
        compact_candidate = _compact_customer_pack_title_text(candidate)
        if len(compact_candidate) >= 6 and compact_candidate in compact_query:
            best_score = max(best_score, 12.0 + min(len(compact_candidate), 120) / 100.0)
            continue
        if len(compact_query) >= 8 and compact_query in compact_candidate:
            best_score = max(best_score, 10.0 + min(len(compact_query), 120) / 100.0)
        title_tokens = set(_official_title_tokens(candidate))
        if not title_tokens or not query_tokens:
            continue
        overlap_tokens = query_tokens & title_tokens
        overlap = len(overlap_tokens)
        coverage = overlap / len(title_tokens)
        query_coverage = overlap / len(query_tokens)
        decisive_overlap = any(
            len(token) >= 7 and re.search(r"[a-z0-9]", token, re.IGNORECASE)
            for token in overlap_tokens
        )
        decisive_title_overlap = bool(overlap_tokens & _OFFICIAL_DECISIVE_TITLE_TOKENS)
        if overlap >= 2 and coverage >= 0.6:
            best_score = max(best_score, 7.5 + coverage + query_coverage)
        elif decisive_title_overlap and coverage >= 0.6:
            decisive_base = 15.0 if official_source_mentioned else 10.0
            best_score = max(best_score, decisive_base + coverage + query_coverage)
        elif official_source_mentioned and decisive_overlap:
            best_score = max(best_score, 14.0 + query_coverage)
        elif official_source_mentioned and overlap >= 3 and query_coverage >= 0.4:
            best_score = max(best_score, 6.5 + coverage + query_coverage)
    return best_score


def _book_rows_for_slug(retriever, slug: str) -> list[dict]:
    return [
        row
        for row in retriever.bm25_index.rows
        if str(row.get("book_slug") or "").strip() == slug
        and str(row.get("source_collection") or "core").strip() == "core"
        and str(row.get("section") or "").strip().lower() != "legal notice"
    ]


def _search_official_runtime_title_hits(
    retriever,
    *,
    query: str,
    top_k: int,
) -> list[RetrievalHit]:
    manifest_path = _official_runtime_manifest_path(retriever)
    fingerprint = _official_runtime_title_fingerprint(manifest_path)
    if not fingerprint:
        return []
    catalog = _official_runtime_title_catalog(str(manifest_path), fingerprint)
    scored_slugs: list[tuple[float, str]] = []
    for entry in catalog:
        title_score = _official_title_match_score(
            query,
            title_candidates=tuple(entry.get("title_candidates") or ()),
        )
        if title_score <= 0:
            continue
        scored_slugs.append((title_score, str(entry.get("slug") or "").strip()))
    if not scored_slugs:
        return []
    scored_slugs.sort(key=lambda item: (-item[0], item[1]))

    hits: list[RetrievalHit] = []
    per_book_limit = max(2, min(4, top_k))
    for title_score, slug in scored_slugs[: min(len(scored_slugs), 4)]:
        rows = _book_rows_for_slug(retriever, slug)
        if not rows:
            continue
        scoped_hits = BM25Index.from_rows(rows).search(query, top_k=per_book_limit)
        if not scoped_hits:
            scoped_hits = [hit_from_payload(rows[0], source="official_title_locator", score=title_score)]
        for rank, source_hit in enumerate(scoped_hits[:per_book_limit], start=1):
            hit = source_hit
            hit.source = "official_title_locator"
            scoped_score = min(float(source_hit.raw_score) / max(rank, 1), 2.0)
            hit.raw_score = float(title_score) + scoped_score
            hit.fused_score = hit.raw_score
            hit.component_scores = dict(hit.component_scores)
            hit.component_scores["official_title_score"] = float(title_score)
            hit.component_scores["official_title_rank"] = float(rank)
            hits.append(hit)
    hits.sort(
        key=lambda item: (
            -item.raw_score,
            item.book_slug,
            item.chunk_id,
        )
    )
    return hits[:top_k]


def _has_customer_pack_explicit_locator_signal(query: str) -> bool:
    return bool(_CUSTOMER_PACK_EXPLICIT_LOCATOR_RE.search(query or ""))


def _is_customer_pack_title_locator_query(query: str) -> bool:
    normalized = str(query or "").strip()
    if not normalized or not has_doc_locator_intent(normalized.lower()):
        return False
    locator_tokens = _customer_pack_locator_tokens(normalized)
    lowered = normalized.lower()
    has_explicit_locator = _has_customer_pack_explicit_locator_signal(normalized)
    navigation_locator = any(
        token in lowered
        for token in (
            "어디",
            "찾아",
            "찾을",
            "열어",
            "보여",
            "보고 싶",
            "경로",
            "위치",
            "이동",
            "들어가",
            "목록",
        )
    )
    if is_explainer_query(normalized) and not navigation_locator:
        return False
    if (
        not has_explicit_locator
        and "문서" in lowered
        and not any(
            token in lowered
            for token in ("설계서", "제안서", "ppt", "pptx", "slide", "슬라이드")
        )
    ):
        return False
    return len(locator_tokens) >= 3 or any(
        token in lowered
        for token in (
            "설계서",
            "제안서",
            "발표",
            "ppt",
            "pptx",
            "slide",
            "슬라이드",
        )
    )


def _customer_pack_title_candidates(payload: dict[str, object]) -> tuple[str, ...]:
    candidates: list[str] = []
    for raw in (
        payload.get("title"),
        payload.get("book_slug"),
        payload.get("canonical_title"),
        payload.get("asset_slug"),
    ):
        value = str(raw or "").strip()
        if value:
            candidates.append(value)
    source_uri = str(payload.get("source_uri") or "").strip()
    if source_uri:
        stem = Path(source_uri).stem.replace("_", " ").replace("-", " ").strip()
        if stem:
            candidates.append(stem)
    for section in (payload.get("sections") or [])[:3]:
        if not isinstance(section, dict):
            continue
        for raw in (
            section.get("heading"),
            section.get("section_path_label"),
        ):
            value = str(raw or "").strip()
            if value:
                candidates.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        compact = _compact_customer_pack_title_text(candidate)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(candidate)
    return tuple(deduped)


def _customer_pack_title_match_score(query: str, *, title_candidates: tuple[str, ...]) -> float:
    compact_query = _compact_customer_pack_title_text(query)
    if not compact_query:
        return 0.0
    query_tokens = set(_customer_pack_locator_tokens(query))
    best_score = 0.0
    for candidate in title_candidates:
        compact_candidate = _compact_customer_pack_title_text(candidate)
        if len(compact_candidate) >= 6 and compact_candidate in compact_query:
            best_score = max(best_score, 10.0 + min(len(compact_candidate), 120) / 100.0)
            continue
        if len(compact_query) >= 8 and compact_query in compact_candidate:
            best_score = max(best_score, 9.0 + min(len(compact_query), 120) / 100.0)
        title_tokens = set(_customer_pack_locator_tokens(candidate))
        if not title_tokens or not query_tokens:
            continue
        overlap = len(query_tokens & title_tokens)
        coverage = overlap / len(title_tokens)
        query_coverage = overlap / len(query_tokens)
        if overlap >= 3 and coverage >= 0.6:
            best_score = max(best_score, 6.0 + coverage + query_coverage)
        elif overlap >= 4 and query_coverage >= 0.5:
            best_score = max(best_score, 5.5 + coverage + query_coverage)
    return best_score


def _customer_pack_title_locator_fingerprint(books_dir: Path) -> tuple[tuple[str, int], ...]:
    if not books_dir.exists():
        return ()
    fingerprint: list[tuple[str, int]] = []
    for path in iter_customer_pack_book_payload_paths(books_dir):
        if "--" in path.stem:
            continue
        fingerprint.append((f"book:{path.name}", path.stat().st_mtime_ns))
        manifest_path = books_dir.parent / "corpus" / path.stem / "manifest.json"
        if manifest_path.exists():
            fingerprint.append((f"manifest:{path.stem}", manifest_path.stat().st_mtime_ns))
    return tuple(sorted(fingerprint))


def _select_customer_pack_title_locator_section(payload: dict[str, object]) -> dict[str, object] | None:
    sections = [
        dict(section)
        for section in (payload.get("sections") or [])
        if isinstance(section, dict)
    ]
    if not sections:
        return None
    title = str(payload.get("title") or payload.get("book_slug") or "").strip()
    compact_title = _compact_customer_pack_title_text(title)
    scored_sections: list[tuple[int, int, dict[str, object]]] = []
    for index, section in enumerate(sections):
        heading = str(section.get("heading") or section.get("section_path_label") or "").strip()
        score = 0
        compact_heading = _compact_customer_pack_title_text(heading)
        if compact_title and compact_heading and (
            compact_heading in compact_title or compact_title in compact_heading
        ):
            score += 4
        if index == 0:
            score += 2
        if str(section.get("semantic_role") or "").strip() in {"title", "overview", "summary"}:
            score += 1
        if str(section.get("viewer_path") or "").strip():
            score += 1
        if str(section.get("text") or "").strip():
            score += 1
        scored_sections.append((score, -index, section))
    scored_sections.sort(key=lambda item: (-item[0], item[1]))
    return scored_sections[0][2] if scored_sections else sections[0]


@lru_cache(maxsize=4)
def _customer_pack_title_locator_catalog(
    books_dir_str: str,
    fingerprint: tuple[tuple[str, int], ...],
) -> tuple[dict[str, object], ...]:
    del fingerprint
    books_dir = Path(books_dir_str)
    catalog: list[dict[str, object]] = []
    for path in iter_customer_pack_book_payload_paths(books_dir):
        if "--" in path.stem:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        manifest_path = books_dir.parent / "corpus" / path.stem / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        runtime_boundary = summarize_private_runtime_boundary(manifest_payload)
        if not bool(runtime_boundary.get("runtime_eligible")):
            continue
        promotion_gate = dict(manifest_payload.get("grade_gate") or {}).get("promotion_gate") or {}
        if not bool(
            manifest_payload.get("publish_ready")
            or promotion_gate.get("publish_ready")
        ):
            continue
        hydrated_payload = dict(payload)
        hydrated_payload["quality_status"] = str(
            payload.get("quality_status")
            or manifest_payload.get("quality_status")
            or "ready"
        )
        title_candidates = _customer_pack_title_candidates(hydrated_payload)
        section = _select_customer_pack_title_locator_section(hydrated_payload)
        if not title_candidates or section is None:
            continue
        row = customer_pack_row_from_section(hydrated_payload, section, draft_id=path.stem)
        title_prefix = [f"문서 제목: {title_candidates[0]}"]
        source_uri = str(hydrated_payload.get("source_uri") or "").strip()
        if source_uri:
            title_prefix.append(f"원본 파일: {Path(source_uri).name}")
        body = str(row.get("text") or "").strip()
        row["text"] = "\n".join(part for part in (*title_prefix, body) if part).strip()
        catalog.append(
            {
                "row": row,
                "title_candidates": title_candidates,
            }
        )
    return tuple(catalog)


def _search_customer_pack_title_locator_hits(
    retriever,
    *,
    query: str,
    top_k: int,
) -> list[RetrievalHit]:
    if not _is_customer_pack_title_locator_query(query):
        return []
    fingerprint = _customer_pack_title_locator_fingerprint(retriever.settings.customer_pack_books_dir)
    if not fingerprint:
        return []
    catalog = _customer_pack_title_locator_catalog(
        str(retriever.settings.customer_pack_books_dir),
        fingerprint,
    )
    scored_hits: list[tuple[float, RetrievalHit]] = []
    for entry in catalog:
        title_score = _customer_pack_title_match_score(
            query,
            title_candidates=tuple(entry.get("title_candidates") or ()),
        )
        if title_score <= 0:
            continue
        row = dict(entry.get("row") or {})
        hit = hit_from_payload(row, source="customer_pack_title_locator", score=title_score)
        hit.component_scores["customer_pack_title_score"] = float(title_score)
        scored_hits.append((title_score, hit))
    scored_hits.sort(
        key=lambda item: (
            -item[0],
            item[1].book_slug,
            item[1].chunk_id,
        )
    )
    return [hit for _, hit in scored_hits[:top_k]]


def _vector_subquery_runtime(
    *,
    query: str,
    runtime: dict[str, object],
) -> dict[str, object]:
    return {
        "query": query,
        "endpoint_used": str(runtime.get("endpoint_used", "")),
        "attempted_endpoints": [str(item) for item in (runtime.get("attempted_endpoints") or [])],
        "hit_count": int(runtime.get("hit_count", 0) or 0),
        "top_score": runtime.get("top_score"),
    }


def _aggregate_vector_runtime(subqueries: list[dict[str, object]]) -> dict[str, object]:
    endpoints_used = sorted(
        {
            str(item.get("endpoint_used", "")).strip()
            for item in subqueries
            if str(item.get("endpoint_used", "")).strip()
        }
    )
    return {
        "subquery_count": len(subqueries),
        "subqueries": subqueries,
        "endpoints_used": endpoints_used,
        "endpoint_used": endpoints_used[0] if len(endpoints_used) == 1 else "mixed" if endpoints_used else "",
        "empty_subqueries": sum(int(item.get("hit_count", 0) == 0) for item in subqueries),
    }


def search_bm25_candidates(
    retriever,
    *,
    context,
    rewritten_queries: list[str],
    effective_candidate_k: int,
    trace_callback,
    timings_ms: dict[str, float],
) -> dict[str, list[RetrievalHit]]:
    _emit_trace_event(
        trace_callback,
        step="bm25_search",
        label="키워드 검색 중",
        status="running",
    )
    bm25_started_at = time.perf_counter()
    bm25_hit_sets = [
        retriever.bm25_index.search(subquery, top_k=effective_candidate_k)
        for subquery in rewritten_queries
    ]
    core_hits = _rrf_merge_hit_lists(
        bm25_hit_sets,
        source_name="bm25",
        top_k=effective_candidate_k,
    )
    official_title_locator_hits = _search_official_runtime_title_hits(
        retriever,
        query=rewritten_queries[0] if rewritten_queries else "",
        top_k=effective_candidate_k,
    )
    if official_title_locator_hits:
        core_hits = _rrf_merge_named_hit_lists(
            {
                "bm25": core_hits,
                "official_title": official_title_locator_hits,
            },
            source_name="bm25",
            top_k=effective_candidate_k,
            weights={"bm25": 1.0, "official_title": 3.4},
        )
    overlay_bm25_hits: list[RetrievalHit] = []
    private_index = load_selected_customer_pack_private_bm25_index(
        retriever.settings,
        context=context,
    )
    overlay_index = None
    if private_index is not None:
        overlay_index = private_index
    title_locator_query = any(
        _is_customer_pack_title_locator_query(subquery)
        for subquery in rewritten_queries
    )
    if overlay_index is None and (
        has_active_customer_pack_selection(context)
        or any(_is_customer_pack_explicit_query(subquery) for subquery in rewritten_queries)
    ):
        overlay_index = retriever.customer_pack_overlay_index()
    eligible_selected = _runtime_eligible_selected_draft_ids(retriever.settings, context)
    if overlay_index is not None:
        overlay_hit_sets = [
            (
                overlay_index.search(subquery, top_k=effective_candidate_k)
                if private_index is not None
                else filter_customer_pack_hits_by_selection(
                    overlay_index.search(subquery, top_k=effective_candidate_k),
                    context=context,
                    allowed_draft_ids=eligible_selected,
                )
                if eligible_selected
                else overlay_index.search(subquery, top_k=effective_candidate_k)
            )
            for subquery in rewritten_queries
        ]
        overlay_bm25_hits = _rrf_merge_hit_lists(
            overlay_hit_sets,
            source_name="overlay_bm25",
            top_k=effective_candidate_k,
        )
    title_locator_hits = _search_customer_pack_title_locator_hits(
        retriever,
        query=rewritten_queries[0] if rewritten_queries else "",
        top_k=effective_candidate_k,
    )
    overlay_hits = (
        _rrf_merge_named_hit_lists(
            {
                "overlay_bm25": overlay_bm25_hits,
                "customer_pack_title": title_locator_hits,
            },
            source_name="overlay_bm25",
            top_k=effective_candidate_k,
            weights={"overlay_bm25": 1.35, "customer_pack_title": 2.8},
        )
        if overlay_bm25_hits or title_locator_hits
        else []
    )
    bm25_hits = (
        _rrf_merge_named_hit_lists(
            {
                "bm25": core_hits,
                "overlay_bm25": overlay_hits,
            },
            source_name="bm25",
            top_k=effective_candidate_k,
            weights={"bm25": 1.0, "overlay_bm25": 1.35},
        )
        if overlay_hits
        else core_hits
    )
    timings_ms["bm25_search"] = _duration_ms(bm25_started_at)
    _emit_trace_event(
        trace_callback,
        step="bm25_search",
        label="키워드 검색 완료",
        status="done",
        detail=f"후보 {len(bm25_hits)}개",
        duration_ms=timings_ms["bm25_search"],
        meta={
            "candidate_k": effective_candidate_k,
            "count": len(bm25_hits),
            "overlay_count": len(overlay_hits),
            "overlay_bm25_count": len(overlay_bm25_hits),
            "title_locator_count": len(title_locator_hits),
            "official_title_locator_count": len(official_title_locator_hits),
            "title_locator_query": title_locator_query,
            "private_overlay_ready": private_index is not None,
            "summary": _summarize_hit_list(bm25_hits),
        },
    )
    return {
        "core_hits": core_hits,
        "overlay_hits": overlay_hits,
        "title_locator_hits": title_locator_hits,
        "official_title_locator_hits": official_title_locator_hits,
        "hits": bm25_hits,
    }


def search_vector_candidates(
    retriever,
    *,
    context,
    rewritten_queries: list[str],
    effective_candidate_k: int,
    trace_callback,
    timings_ms: dict[str, float],
) -> dict[str, object]:
    _private_probe_hits, private_probe_runtime = search_selected_customer_pack_private_vectors(
        retriever.settings,
        context=context,
        query=rewritten_queries[0] if rewritten_queries else "",
        top_k=effective_candidate_k,
    )
    if retriever.vector_retriever is None and str(private_probe_runtime.get("status") or "") != "ready":
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 실패",
            status="error",
            detail="vector retriever is not configured",
        )
        raise RuntimeError("vector retriever is not configured")
    try:
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 중",
            status="running",
        )
        vector_started_at = time.perf_counter()
        vector_hit_sets: list[list[RetrievalHit]] = []
        vector_subqueries: list[dict[str, object]] = []
        for subquery in rewritten_queries:
            official_hits: list[RetrievalHit] = []
            runtime = {
                "endpoint_used": "",
                "attempted_endpoints": [],
                "hit_count": 0,
                "top_score": None,
            }
            if retriever.vector_retriever is not None:
                if hasattr(retriever.vector_retriever, "search_with_trace"):
                    official_hits, runtime = retriever.vector_retriever.search_with_trace(
                        subquery,
                        top_k=effective_candidate_k,
                    )
                else:
                    official_hits = retriever.vector_retriever.search(subquery, top_k=effective_candidate_k)
                    runtime = {
                        "endpoint_used": "",
                        "attempted_endpoints": [],
                        "hit_count": len(official_hits),
                        "top_score": float(official_hits[0].raw_score) if official_hits else None,
                    }
            private_hits, private_runtime = search_selected_customer_pack_private_vectors(
                retriever.settings,
                context=context,
                query=subquery,
                top_k=effective_candidate_k,
            )
            merged_hits = (
                _rrf_merge_named_hit_lists(
                    {
                        "vector": official_hits,
                        "private_vector": private_hits,
                    },
                    source_name="vector",
                    top_k=effective_candidate_k,
                    weights={"vector": 1.0, "private_vector": 1.15},
                )
                if official_hits and private_hits
                else (private_hits or official_hits)
            )
            vector_hit_sets.append(merged_hits)
            runtime_payload = _vector_subquery_runtime(query=subquery, runtime=runtime)
            runtime_payload["private_vector_status"] = str(private_runtime.get("status", ""))
            runtime_payload["private_hit_count"] = int(private_runtime.get("hit_count", 0) or 0)
            vector_subqueries.append(runtime_payload)
        vector_hits = _rrf_merge_hit_lists(
            vector_hit_sets,
            source_name="vector",
            top_k=effective_candidate_k,
        )
        vector_runtime = _aggregate_vector_runtime(vector_subqueries)
        timings_ms["vector_search"] = _duration_ms(vector_started_at)
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 완료",
            status="done",
            detail=f"후보 {len(vector_hits)}개",
            duration_ms=timings_ms["vector_search"],
            meta={
                "candidate_k": effective_candidate_k,
                "count": len(vector_hits),
                "endpoint_used": vector_runtime["endpoint_used"],
                "endpoints_used": vector_runtime["endpoints_used"],
                "empty_subqueries": vector_runtime["empty_subqueries"],
                "summary": _summarize_hit_list(vector_hits),
            },
        )
        return {
            "hits": vector_hits,
            "runtime": vector_runtime,
        }
    except Exception as exc:  # noqa: BLE001
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 실패",
            status="error",
            detail=str(exc),
        )
        raise RuntimeError(f"vector search failed: {exc}") from exc
