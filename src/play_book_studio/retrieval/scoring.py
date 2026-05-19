"""Minimal fusion facade retained for compatibility tests."""
from __future__ import annotations

import copy

from .models import RetrievalHit, SessionContext
from .ranking import is_noise_hit as _is_noise_hit


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
    fused_by_id: dict[str, RetrievalHit] = {}
    for source_name, hits in ranked_lists.items():
        weight = weights.get(source_name, 1.0)
        for rank, hit in enumerate(hits, start=1):
            if _is_noise_hit(hit):
                continue
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

    return sorted(
        fused_by_id.values(),
        key=lambda hit: (-hit.fused_score, -hit.raw_score, hit.book_slug, hit.chunk_id),
    )[:top_k]
