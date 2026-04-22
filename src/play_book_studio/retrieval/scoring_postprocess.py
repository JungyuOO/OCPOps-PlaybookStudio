# fusion 결과의 정렬과 다양성 제한을 후처리한다.
from __future__ import annotations

from collections import Counter

from .models import RetrievalHit
from .query import contains_hangul
from .scoring_signals import ScoreSignals


def sort_and_diversify_hits(
    hits: list[RetrievalHit],
    *,
    top_k: int,
    signals: ScoreSignals,
) -> list[RetrievalHit]:
    hits.sort(
        key=lambda item: (
            -item.fused_score,
            -int(contains_hangul(item.text)),
            item.book_slug,
            item.chunk_id,
        )
    )
    if signals.pod_lifecycle_intent or signals.operator_concept_intent or signals.mco_concept_intent:
        diversified_hits: list[RetrievalHit] = []
        per_book_counts: Counter[str] = Counter()
        seen_intake_sections: set[tuple[str, str]] = set()
        for hit in hits:
            normalized_section = hit.section.strip().lower()
            if hit.viewer_path.startswith("/playbooks/customer-packs/"):
                section_key = (hit.book_slug, normalized_section)
                if section_key in seen_intake_sections:
                    continue
                seen_intake_sections.add(section_key)
            if per_book_counts[hit.book_slug] >= 2:
                continue
            diversified_hits.append(hit)
            per_book_counts[hit.book_slug] += 1
        hits = diversified_hits
    return hits[:top_k]

