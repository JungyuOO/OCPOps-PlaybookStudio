from __future__ import annotations

# 개념/문서 탐색 계열의 core 점수 규칙.

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_discovery_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    lowered_text = hit.text.lower()
    lowered_section = hit.section.lower()

    if signals.generic_intro_intent:
        if hit.book_slug == "architecture":
            hit.fused_score *= 1.22
            if "아키텍처 개요" in hit.section or "architecture overview" in lowered_section:
                hit.fused_score *= 1.18
            if hit.section.startswith("1장. 아키텍처 개요"):
                hit.fused_score *= 1.16
            if "정의" in hit.section or "소개" in hit.section:
                hit.fused_score *= 1.1
            if "라이프사이클" in hit.section or "lifecycle" in lowered_section:
                hit.fused_score *= 0.58
            if "기타 주요 기능" in hit.section:
                hit.fused_score *= 0.62
            if "용어집" in hit.section or "glossary" in lowered_section:
                hit.fused_score *= 0.74
        elif hit.book_slug == "overview":
            hit.fused_score *= 1.16
        elif hit.book_slug.endswith("_overview"):
            hit.fused_score *= 0.84
        elif hit.book_slug in {"api_overview", "networking_overview", "project_apis"}:
            hit.fused_score *= 0.88

    if signals.compare_intent:
        if hit.book_slug in {"architecture", "overview", "security_and_compliance"}:
            hit.fused_score *= 1.08
        if "유사점 및 차이점" in hit.section or "difference" in lowered_section or "comparison" in lowered_section:
            hit.fused_score *= 1.16
        if "쿠버네티스" in hit.text or "kubernetes" in lowered_text:
            hit.fused_score *= 1.08
        if hit.book_slug in {"tutorials", "support", "cli_tools"}:
            hit.fused_score *= 0.75

    if signals.update_doc_locator_intent:
        is_update_guide = hit.book_slug == "updating_clusters"
        is_release_notes = hit.book_slug == "release_notes"
        if is_update_guide:
            hit.fused_score *= 1.34
        elif is_release_notes:
            hit.fused_score *= 1.18
        elif hit.book_slug == "overview":
            hit.fused_score *= 1.05
        elif hit.book_slug == "cli_tools":
            hit.fused_score *= 0.42
        if (
            "업데이트" in hit.section
            or "업그레이드" in hit.section
            or "업데이트" in hit.text
            or "업그레이드" in hit.text
            or "update" in lowered_section
            or "upgrade" in lowered_section
        ):
            hit.fused_score *= 1.1
        if "릴리스 노트" in hit.section or "release notes" in lowered_section or "release notes" in lowered_text:
            hit.fused_score *= 1.08
        if "oc explain" in lowered_text or "리소스에 대한 문서 가져오기" in hit.section or "resource document" in lowered_text:
            hit.fused_score *= 0.22
        if hit.book_slug.endswith("_apis"):
            hit.fused_score *= 0.46

    if signals.doc_locator_intent and hit.book_slug.endswith("_apis"):
        hit.fused_score *= 0.82
