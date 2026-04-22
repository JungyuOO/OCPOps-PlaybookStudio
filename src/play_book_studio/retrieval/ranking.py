"""retrieval 후보 병합과 점수 요약을 담당하는 helper 모듈이다.

`retriever.py` 본체에서는 검색 orchestration만 남기고, RRF merge와 trace summary는 이 파일로 분리한다.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .models import RetrievalHit


NOISE_SECTION_RE = re.compile(r"^Legal Notice$", re.IGNORECASE)
STRUCTURED_KEY_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+(?:=[a-z0-9_.-]+)?", re.IGNORECASE)


def is_noise_hit(hit: RetrievalHit) -> bool:
    return bool(NOISE_SECTION_RE.match(hit.section.strip()))


def round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def extract_structured_query_terms(text: str) -> tuple[str, ...]:
    terms = []
    seen: set[str] = set()
    for match in STRUCTURED_KEY_RE.finditer((text or "").lower()):
        term = match.group(0).strip()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return tuple(terms)


def summarize_hit(hit: RetrievalHit, *, score_key: str = "raw_score") -> dict[str, Any]:
    summary = {
        "chunk_id": hit.chunk_id,
        "book_slug": hit.book_slug,
        "section": hit.section,
        "score": round_score(getattr(hit, score_key, 0.0)),
    }
    for key in ("bm25_score", "bm25_rank", "vector_score", "vector_rank"):
        if key in hit.component_scores:
            summary[key] = round_score(hit.component_scores[key])
    for key in ("pre_rerank_fused_score", "reranker_score"):
        if key in hit.component_scores:
            summary[key] = round_score(hit.component_scores[key])
    return summary


def summarize_hit_list(
    hits: list[RetrievalHit],
    *,
    score_key: str = "raw_score",
    limit: int = 3,
) -> dict[str, Any]:
    top_hits = [summarize_hit(hit, score_key=score_key) for hit in hits[:limit]]
    return {
        "count": len(hits),
        "top_score": round_score(getattr(hits[0], score_key, 0.0)) if hits else None,
        "top_hits": top_hits,
    }


def rrf_merge_hit_lists(
    hit_lists: list[list[RetrievalHit]],
    *,
    source_name: str,
    top_k: int,
    rrf_k: int = 60,
) -> list[RetrievalHit]:
    if not hit_lists:
        return []

    merged_by_id: dict[str, RetrievalHit] = {}
    for hits in hit_lists:
        for rank, hit in enumerate(hits, start=1):
            if is_noise_hit(hit):
                continue
            if hit.chunk_id not in merged_by_id:
                merged = copy.deepcopy(hit)
                merged.source = source_name
                merged.raw_score = 0.0
                merged.fused_score = 0.0
                merged.component_scores = {}
                merged_by_id[hit.chunk_id] = merged
            merged_hit = merged_by_id[hit.chunk_id]
            merged_hit.raw_score += 1.0 / (rrf_k + rank)

    merged_hits = list(merged_by_id.values())
    merged_hits.sort(
        key=lambda item: (
            -item.raw_score,
            item.book_slug,
            item.chunk_id,
        )
    )
    return merged_hits[:top_k]


def rrf_merge_named_hit_lists(
    hit_lists_by_source: dict[str, list[RetrievalHit]],
    *,
    source_name: str,
    top_k: int,
    rrf_k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[RetrievalHit]:
    if not hit_lists_by_source:
        return []

    weights = weights or {}
    merged_by_id: dict[str, RetrievalHit] = {}
    for current_source, hits in hit_lists_by_source.items():
        weight = float(weights.get(current_source, 1.0) or 1.0)
        for rank, hit in enumerate(hits, start=1):
            if is_noise_hit(hit):
                continue
            if hit.chunk_id not in merged_by_id:
                merged = copy.deepcopy(hit)
                merged.source = source_name
                merged.raw_score = 0.0
                merged.fused_score = 0.0
                merged.component_scores = {}
                merged_by_id[hit.chunk_id] = merged
            merged_hit = merged_by_id[hit.chunk_id]
            merged_hit.raw_score += weight / (rrf_k + rank)
            merged_hit.component_scores[f"{current_source}_score"] = float(hit.raw_score)
            merged_hit.component_scores[f"{current_source}_rank"] = float(rank)

    merged_hits = list(merged_by_id.values())
    merged_hits.sort(
        key=lambda item: (
            -item.raw_score,
            item.book_slug,
            item.chunk_id,
        )
    )
    return merged_hits[:top_k]
