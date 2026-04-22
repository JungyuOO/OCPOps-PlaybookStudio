from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_pod_troubleshooting_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    lowered_text: str,
    lowered_section: str,
) -> None:
    if signals.pod_pending_intent:
        if hit.book_slug == "support":
            hit.fused_score *= 1.14
        if hit.book_slug == "nodes":
            hit.fused_score *= 1.12
        if (
            "pod 문제 조사" in hit.text
            or "pod 오류 상태" in hit.text
            or "pod 상태 검토" in hit.text
            or "failedscheduling" in lowered_text
            or "insufficient cpu" in lowered_text
            or "insufficient memory" in lowered_text
            or "node affinity" in lowered_text
            or "taint" in lowered_text
            or "toleration" in lowered_text
        ):
            hit.fused_score *= 1.28
        if hit.book_slug == "nodes" and "failedscheduling" in lowered_text:
            hit.fused_score *= 1.22
        if "설치 문제 해결" in hit.text:
            hit.fused_score *= 0.64
            if "etcd" in lowered_section or "operator" in lowered_text:
                hit.fused_score *= 0.7

    if signals.crash_loop_intent:
        is_app_diag = (
            "애플리케이션 오류 조사" in hit.section
            or "애플리케이션 진단 데이터 수집" in hit.section
            or "oc describe pod/" in lowered_text
            or "oc logs -f pod/" in lowered_text
            or "애플리케이션 pod와 관련된 이벤트" in hit.text
        )
        is_event_diagnostic = (
            "이벤트 목록" in hit.section
            or ("이벤트" in hit.section and "backoff" in lowered_text)
            or "back-off restarting failed container" in lowered_text
        )
        is_probe_diagnostic = (
            "상태 점검 이해" in hit.section
            or "상태 점검 구성" in hit.section
            or "livenessprobe" in lowered_text
            or "readinessprobe" in lowered_text
        )
        is_oom_diagnostic = (
            "oom 종료 정책" in hit.section
            or "oomkilled" in lowered_text
            or "restartcount" in lowered_text
            or "exitcode: 137" in lowered_text
        )
        is_operator_image_pull_only = (
            (
                "imagepullbackoff" in lowered_text
                or "errimagepull" in lowered_text
                or "back-off pulling image" in lowered_text
            )
            and "crashloopbackoff" not in lowered_text
            and "restartcount" not in lowered_text
            and "oomkilled" not in lowered_text
            and "livenessprobe" not in lowered_text
            and "readinessprobe" not in lowered_text
            and "애플리케이션" not in hit.text
        )
        if hit.book_slug in {"support", "validation_and_troubleshooting"}:
            hit.fused_score *= 1.22
        if hit.book_slug == "nodes":
            hit.fused_score *= 1.08
        if hit.book_slug == "building_applications":
            hit.fused_score *= 1.16
        if is_app_diag:
            hit.fused_score *= 1.42
        if (
            "pod 오류 상태 이해" in hit.section
            or "backoff" in lowered_text
            or "back-off restarting failed container" in lowered_text
            or "imagepullbackoff" in lowered_text
            or "errimagepull" in lowered_text
        ):
            hit.fused_score *= 1.18
        if is_event_diagnostic:
            hit.fused_score *= 1.24
        if is_probe_diagnostic:
            hit.fused_score *= 1.22
        if (
            "crashloopbackoff" in lowered_text
            or "pod 오류 상태" in hit.text
            or "애플리케이션 오류 조사" in hit.text
            or "oomkilled" in lowered_text
            or "imagepullbackoff" in lowered_text
            or "errimagepull" in lowered_text
            or "back-off restarting failed container" in lowered_text
            or "restartcount" in lowered_text
            or "livenessprobe" in lowered_text
            or "readinessprobe" in lowered_text
        ):
            hit.fused_score *= 1.18
        if hit.book_slug == "nodes" and is_oom_diagnostic:
            hit.fused_score *= 1.08
        if is_operator_image_pull_only:
            hit.fused_score *= 0.32
        if (
            "로그 수준 이해" in hit.section
            or "open vswitch" in lowered_text
            or "ovs" in lowered_section
            or "compliance operator" in lowered_text
            or "카탈로그 소스" in hit.text
            or "openshift-marketplace" in lowered_text
            or "example-catalog" in lowered_text
            or "marketplace-operator" in lowered_text
            or "인덱스 이미지" in hit.text
            or "catalog source" in lowered_text
            or "kernel module management operator" in lowered_text
            or "ovnkube-node" in lowered_text
            or ("etcd pod" in lowered_text and "애플리케이션" not in hit.text)
        ):
            hit.fused_score *= 0.54
        if (
            "operator 문제 해결" in hit.section
            or "카탈로그 소스 상태 보기" in hit.section
            or "실패한 서브스크립션 새로 고침" in hit.section
        ) and not is_app_diag and not is_oom_diagnostic:
            hit.fused_score *= 0.34
        if hit.book_slug.endswith("_apis"):
            hit.fused_score *= 0.58
        if hit.book_slug == "monitoring_apis":
            hit.fused_score *= 0.52
        if hit.book_slug == "security_and_compliance" and "oomkilled" not in lowered_text:
            hit.fused_score *= 0.62
        if hit.book_slug == "support" and "operator 문제 해결" in hit.text and "애플리케이션" not in hit.text:
            hit.fused_score *= 0.66
