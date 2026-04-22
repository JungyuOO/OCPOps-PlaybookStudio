from __future__ import annotations

# operator/MCO 계열의 core 점수 규칙.

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_operator_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    lowered_text = hit.text.lower()
    lowered_section = hit.section.lower()
    context_text = signals.context_text

    if signals.operator_concept_intent:
        if hit.book_slug == "extensions":
            hit.fused_score *= 1.24
        elif hit.book_slug == "overview":
            hit.fused_score *= 1.16
        elif hit.book_slug == "architecture":
            hit.fused_score *= 1.08
        elif hit.book_slug == "installation_overview":
            hit.fused_score *= 0.52
        if (
            "operator" in lowered_section
            and (
                "개요" in hit.section
                or "overview" in lowered_section
                or "용어집" in hit.section
                or "glossary" in lowered_section
            )
        ):
            hit.fused_score *= 1.18
        if "operator는" in hit.text or "운영 지식" in hit.text:
            hit.fused_score *= 1.08
        if (
            "operator controller" in lowered_section
            or "olm v1 구성 요소 개요" in hit.section
            or ("controller" in lowered_section and "operator" in lowered_section)
        ):
            hit.fused_score *= 0.82
        if "정의" in hit.section or "purpose" in lowered_section or "목적" in hit.section:
            hit.fused_score *= 1.08
        if (
            hit.book_slug in {"support", "web_console", "release_notes", "edge_computing"}
            or "문제 해결" in hit.section
            or "troubleshooting" in lowered_section
        ):
            hit.fused_score *= 0.55
        if "machine config operator" in context_text:
            if hit.book_slug == "machine_management":
                hit.fused_score *= 1.18
            if hit.book_slug == "postinstallation_configuration":
                hit.fused_score *= 1.1
            if hit.book_slug in {"hosted_control_planes", "installation_overview"}:
                hit.fused_score *= 0.42
        if "console." in lowered_text or "api" in lowered_section:
            hit.fused_score *= 0.78

    if signals.mco_concept_intent:
        if hit.book_slug == "machine_configuration":
            hit.fused_score *= 1.36
        elif hit.book_slug == "operators":
            hit.fused_score *= 1.12
        if hit.book_slug == "architecture":
            hit.fused_score *= 1.2
        elif hit.book_slug == "overview":
            hit.fused_score *= 1.16
        elif hit.book_slug == "machine_management":
            hit.fused_score *= 1.14
        elif hit.book_slug == "postinstallation_configuration":
            hit.fused_score *= 1.12
        elif hit.book_slug == "images":
            hit.fused_score *= 1.08
        if "machine config operator" in lowered_text or "machine config operator" in lowered_section:
            hit.fused_score *= 1.22
        if (
            "about the machine config operator" in lowered_section
            or "machine config operator 정보" in hit.section
            or "머신 구성 운영 개요" in hit.section
        ):
            hit.fused_score *= 1.28
        if "machine config daemon" in lowered_text or "machineconfigdaemon" in lowered_text:
            hit.fused_score *= 1.08
        if "machine config pool" in lowered_text or "mcp" in hit.text:
            hit.fused_score *= 1.08
        if (
            "노드" in hit.text
            or "RHCOS" in hit.text
            or "kubelet" in hit.text
            or "CRI-O" in hit.text
            or "ignition" in lowered_text
        ):
            hit.fused_score *= 1.1
        if "용어집" in hit.section or "glossary" in lowered_section:
            hit.fused_score *= 1.14
            if hit.book_slug in {"overview", "architecture", "updating_clusters"}:
                hit.fused_score *= 0.68
        if "일반 용어" in hit.section and hit.book_slug == "updating_clusters":
            hit.fused_score *= 0.54
        if (
            hit.book_slug in {"support", "release_notes", "edge_computing", "security_and_compliance"}
            or "비활성화" in hit.section
            or "자동으로 재부팅되지 않도록" in hit.section
            or "bug" in lowered_section
            or "troubleshooting" in lowered_section
        ):
            hit.fused_score *= 0.48
        if hit.book_slug in {"hosted_control_planes", "installation_overview"}:
            hit.fused_score *= 0.42
        if hit.book_slug == "updating_clusters":
            hit.fused_score *= 0.52
        if hit.book_slug == "windows_container_support_for_openshift":
            hit.fused_score *= 0.38
    elif "machine config operator" in context_text:
        pause_control_signal = (
            "자동으로 재부팅되지 않도록" in context_text
            or "spec.paused" in context_text.lower()
            or "자동으로 재부팅되지 않도록" in signals.query
            or "spec.paused" in signals.query.lower()
        )
        doc_locator_signal = signals.doc_locator_intent
        if hit.book_slug == "machine_management":
            hit.fused_score *= 1.16
        if doc_locator_signal and hit.book_slug == "machine_configuration":
            hit.fused_score *= 1.36
        if doc_locator_signal and hit.book_slug == "operators":
            hit.fused_score *= 1.24
        if hit.book_slug == "postinstallation_configuration":
            hit.fused_score *= 1.14
        if hit.book_slug == "architecture":
            hit.fused_score *= 1.12
        if hit.book_slug == "overview":
            hit.fused_score *= 1.06
        if hit.book_slug == "nodes":
            hit.fused_score *= 1.1
        if hit.book_slug == "support":
            if doc_locator_signal:
                hit.fused_score *= 1.22 if pause_control_signal else 1.04
            else:
                hit.fused_score *= 1.28 if pause_control_signal else 0.78
        if hit.book_slug == "cli_tools":
            hit.fused_score *= 0.62
        if signals.machine_config_reboot_intent:
            if hit.book_slug == "updating_clusters":
                hit.fused_score *= 1.34
            if hit.book_slug == "nodes":
                hit.fused_score *= 1.08
        if (
            "자동으로 재부팅되지 않도록" in lowered_text
            or "자동으로 재부팅되지 않도록" in lowered_section
            or "spec.paused" in lowered_text
            or "spec.paused" in lowered_section
        ):
            hit.fused_score *= 1.26
        if "machineconfigpool" in lowered_text or "machine config pool" in lowered_text:
            hit.fused_score *= 1.12
        if hit.book_slug in {"specialized_hardware_and_driver_enablement", "network_security", "hosted_control_planes"}:
            hit.fused_score *= 0.24
        if hit.book_slug == "installation_overview":
            hit.fused_score *= 0.42
        if doc_locator_signal and hit.book_slug in {"release_notes", "advanced_networking", "networking_overview"}:
            hit.fused_score *= 0.42
        if hit.book_slug == "updating_clusters":
            if signals.machine_config_reboot_intent:
                hit.fused_score *= 0.86
            elif doc_locator_signal:
                hit.fused_score *= 1.08
            else:
                hit.fused_score *= 0.56
