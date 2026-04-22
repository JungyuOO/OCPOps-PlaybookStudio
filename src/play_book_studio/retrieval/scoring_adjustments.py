# hit 하나에 적용할 fusion 점수 조정 규칙을 조립한다.
from __future__ import annotations

from .models import RetrievalHit
from .query import contains_hangul
from .scoring_adjustments_core import apply_core_adjustments
from .scoring_adjustments_runtime import apply_runtime_adjustments
from .scoring_signals import ScoreSignals
from play_book_studio.config.corpus_policy import is_reference_heavy_book_slug


def apply_hit_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    book_source_count: int,
) -> None:
    is_intake_doc = hit.viewer_path.startswith("/playbooks/customer-packs/")
    lowered_text = hit.text.lower()

    if book_source_count >= 2:
        hit.fused_score *= 1.1
    elif (
        contains_hangul(signals.query)
        and "vector_score" in hit.component_scores
        and "bm25_score" not in hit.component_scores
    ):
        hit.fused_score *= 0.95

    # intake overlay는 현재 기본 retrieval 경로에서 비활성화했다.
    # overlay 점수 우대는 opt-in 경로가 다시 살아날 때만 되돌린다.

    if contains_hangul(signals.query):
        if contains_hangul(hit.text):
            hit.fused_score *= 1.05
        else:
            hit.fused_score *= 0.85

    if is_reference_heavy_book_slug(hit.book_slug):
        if signals.concept_like_intent and not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.34
        elif not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.82

    apply_core_adjustments(hit, signals=signals)

    if hit.book_slug in signals.book_boosts:
        hit.fused_score *= signals.book_boosts[hit.book_slug]
    if hit.book_slug in signals.book_penalties:
        hit.fused_score *= signals.book_penalties[hit.book_slug]

    apply_runtime_adjustments(
        hit,
        signals=signals,
        is_intake_doc=is_intake_doc,
    )

    hit.raw_score = hit.fused_score

