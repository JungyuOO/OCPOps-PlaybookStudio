from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_pod_lifecycle_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    is_intake_doc: bool,
    lowered_text: str,
    lowered_section: str,
) -> None:
    if not signals.pod_lifecycle_intent:
        return

    mentions_pod = (
        "pod" in lowered_text
        or "pod" in lowered_section
        or "파드" in hit.text
        or "파드" in hit.section
    )
    is_command_section = hit.section.strip().startswith("$ ")
    is_operational_pod_section = (
        "검사" in hit.section
        or "oc get pod" in lowered_text
        or "oc get pods" in lowered_text
        or "[code]" in lowered_text
    )
    if hit.book_slug == "architecture":
        hit.fused_score *= 1.28
    if hit.book_slug == "nodes":
        hit.fused_score *= 1.22
    if hit.book_slug in {"overview", "building_applications"}:
        hit.fused_score *= 1.08
    if mentions_pod:
        hit.fused_score *= 1.16
    else:
        hit.fused_score *= 0.42
    if (
        "라이프사이클" in hit.text
        or "라이프사이클" in hit.section
        or "phase" in lowered_text
        or "pending" in lowered_text
        or "running" in lowered_text
        or "succeeded" in lowered_text
        or "failed" in lowered_text
        or "unknown" in lowered_text
    ):
        hit.fused_score *= 1.18
    if "용어집" in hit.section or "glossary" in lowered_section or "개요" in hit.section or "overview" in lowered_section:
        hit.fused_score *= 1.16
    if (
        "pod는" in hit.text
        or "pod는 kubernetes" in lowered_text
        or "pod는 쿠버네티스" in hit.text
        or "pod status" in lowered_text
        or "pod phase" in lowered_text
        or "정의" in hit.section
    ):
        hit.fused_score *= 1.12
    if (
        "pod 이해" in hit.section
        or "pod 사용" in hit.section
        or hit.section.strip() == "Pod"
        or "pod 구성의 예" in hit.section
    ):
        hit.fused_score *= 1.24
    if hit.book_slug.endswith("_apis"):
        hit.fused_score *= 0.52
    if is_command_section:
        hit.fused_score *= 0.24
    if (
        "[code]" in lowered_text
        or "oc get pod" in lowered_text
        or "evicted" in lowered_text
        or "oomkilled" in lowered_text
    ) and "용어집" not in hit.section and "glossary" not in lowered_section:
        hit.fused_score *= 0.72
    if is_intake_doc and is_operational_pod_section and "pod 이해" not in hit.section:
        hit.fused_score *= 0.46
    if (
        "pod 제거 이해" in hit.section
        or "oom 종료 정책 이해" in hit.section
        or "evicted" in lowered_text
        or "oomkilled" in lowered_text
    ):
        hit.fused_score *= 0.54
    if (
        "fileintegritynodestatuses" in lowered_text
        or "설치 후 노드 상태 확인" in hit.section
        or "node status" in lowered_text
        or "nodestatuses" in lowered_text
        or "status.conditions" in lowered_text
        or "status.phase" in lowered_text
    ):
        hit.fused_score *= 0.46
    if hit.book_slug in {"security_and_compliance", "installation_overview"}:
        hit.fused_score *= 0.52
    if "machine" in lowered_section and "pod" not in lowered_text:
        hit.fused_score *= 0.66
