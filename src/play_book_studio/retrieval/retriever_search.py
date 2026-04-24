from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from play_book_studio.intake.artifact_bundle import iter_customer_pack_book_payload_paths
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary

from .bm25 import tokenize_text
from .intake_overlay import (
    customer_pack_row_from_section,
    filter_customer_pack_hits_by_selection,
    has_active_customer_pack_selection,
    load_selected_customer_pack_private_bm25_index,
    _runtime_eligible_selected_draft_ids,
    search_selected_customer_pack_private_vectors,
)
from .models import RetrievalHit
from .query import has_doc_locator_intent
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


def _compact_customer_pack_title_text(text: str) -> str:
    return _CUSTOMER_PACK_TITLE_TEXT_RE.sub("", (text or "").lower())


def _customer_pack_locator_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in tokenize_text(text)
        if len(token) >= 2 and token not in _CUSTOMER_PACK_TITLE_QUERY_STOPWORDS
    )


def _is_customer_pack_title_locator_query(query: str) -> bool:
    normalized = str(query or "").strip()
    if not normalized or not has_doc_locator_intent(normalized.lower()):
        return False
    locator_tokens = _customer_pack_locator_tokens(normalized)
    lowered = normalized.lower()
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
    if overlay_index is None and has_active_customer_pack_selection(context):
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
            "title_locator_query": title_locator_query,
            "private_overlay_ready": private_index is not None,
            "summary": _summarize_hit_list(bm25_hits),
        },
    )
    return {
        "core_hits": core_hits,
        "overlay_hits": overlay_hits,
        "title_locator_hits": title_locator_hits,
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
