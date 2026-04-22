# hybrid retrieval의 fusion/scoring facade.
from __future__ import annotations

import copy

from .models import RetrievalHit, SessionContext
from .ranking import is_noise_hit as _is_noise_hit
from .scoring_adjustments import apply_hit_adjustments
from .scoring_postprocess import sort_and_diversify_hits
from .scoring_signals import build_score_signals


def fuse_ranked_hits(
    query: str,
    ranked_lists: dict[str, list[RetrievalHit]],
    *,
    context: SessionContext | None = None,
    top_k: int,
    rrf_k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[RetrievalHit]:
    weights = weights or {"bm25": 1.0, "vector": 1.0}
    context = context or SessionContext()
    signals = build_score_signals(query, context=context)

    fused_by_id: dict[str, RetrievalHit] = {}
    book_sources: dict[str, set[str]] = {}
    for source_name, hits in ranked_lists.items():
        weight = weights.get(source_name, 1.0)
        for rank, hit in enumerate(hits, start=1):
            if _is_noise_hit(hit):
                continue
            if rank <= 10:
                book_sources.setdefault(hit.book_slug, set()).add(source_name)
            if hit.chunk_id not in fused_by_id:
                fused_hit = copy.deepcopy(hit)
                fused_hit.source = "hybrid"
                fused_hit.fused_score = 0.0
                fused_hit.component_scores = {}
                fused_by_id[hit.chunk_id] = fused_hit
            fused = fused_by_id[hit.chunk_id]
            fused.component_scores[f"{source_name}_score"] = float(hit.raw_score)
            fused.component_scores[f"{source_name}_rank"] = float(rank)
            fused.fused_score += weight / (rrf_k + rank)

    fused_hits = list(fused_by_id.values())
    for hit in fused_hits:
        apply_hit_adjustments(
            hit,
            signals=signals,
            book_source_count=len(book_sources.get(hit.book_slug, set())),
        )

    return sort_and_diversify_hits(fused_hits, top_k=top_k, signals=signals)
