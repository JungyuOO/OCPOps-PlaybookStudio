from __future__ import annotations

from dataclasses import dataclass

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.retrieval.text_utils import strip_section_prefix
from play_book_studio.retrieval.query import (
    ETCD_RE,
    MCO_RE,
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_deployment_scaling_intent,
    has_doc_locator_intent,
    has_openshift_kubernetes_compare_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
    has_rbac_intent,
    has_route_ingress_compare_intent,
    is_generic_intro_query,
)


@dataclass(slots=True)
class NextPlayPlan:
    next_action: str
    verification: str
    next_branch: str

    def as_list(self) -> list[str]:
        return [self.next_action, self.verification, self.next_branch]


def _subject_from(result: AnswerResult, citation: Citation | None, topic: str) -> str:
    query = (result.query or "").strip()
    lowered = query.lower()
    if _has_buildconfig_intent(query, citation):
        return "BuildConfig"
    if has_route_ingress_compare_intent(query):
        return "Route와 Ingress"
    if "router" in lowered or "라우터" in lowered:
        return "Router"
    if "ci/cd" in lowered or "cicd" in lowered:
        return "CI/CD 운영 구조"
    if ETCD_RE.search(query) or "etcd" in topic.lower():
        return "etcd"
    if MCO_RE.search(query) or "machine config operator" in topic.lower():
        return "Machine Config Operator"
    if "operator" in lowered:
        return "Operator"
    if topic.strip():
        return strip_section_prefix(topic.strip())
    if citation is not None:
        if citation.operator_names:
            return citation.operator_names[0]
        if citation.section:
            return strip_section_prefix(citation.section)
    return "이 작업"


def _has_buildconfig_intent(query: str, citation: Citation | None = None) -> bool:
    haystack = " ".join(
        [
            str(query or ""),
            str(getattr(citation, "book_slug", "") or ""),
            str(getattr(citation, "section", "") or ""),
        ]
    ).lower()
    return "buildconfig" in haystack or "build config" in haystack


def _is_customer_citation(citation: Citation) -> bool:
    source_collection = str(citation.source_collection or "").strip().lower()
    viewer_path = str(citation.viewer_path or "").strip()
    return source_collection == "uploaded" or viewer_path.startswith("/playbooks/customer-packs/")


def _has_customer_runtime(result: AnswerResult) -> bool:
    return any(_is_customer_citation(citation) for citation in result.citations)


def _has_official_runtime(result: AnswerResult) -> bool:
    return any(not _is_customer_citation(citation) for citation in result.citations)


def _is_customer_context_query(query: str) -> bool:
    normalized = str(query or "")
    lowered = normalized.lower()
    return any(
        token in lowered
        for token in (
            "customer",
            "uploaded",
            "user upload",
        )
    ) or any(
        token in normalized
        for token in (
            "고객 문서",
            "고객문서",
            "고객 자료",
            "고객자료",
            "고객 PPT",
            "고객 운영북",
            "운영북",
            "업로드 문서",
            "업로드자료",
            "사용자 업로드",
        )
    )


def _customer_subject(result: AnswerResult, fallback_subject: str) -> str:
    query = str(result.query or "")
    lowered = query.lower()
    if "ci/cd" in lowered or "cicd" in lowered:
        return "고객 CI/CD 운영 구조"
    if "교육" in query or "신규 운영자" in query:
        return "신규 운영자 교육 코스"
    if "아키텍처" in query or "architecture" in lowered:
        return "고객 목표 아키텍처"
    for citation in result.citations:
        if not _is_customer_citation(citation):
            continue
        section = strip_section_prefix(citation.section)
        if section:
            return f"고객 {section}"
    return f"고객 {fallback_subject}" if fallback_subject and not fallback_subject.startswith("고객") else fallback_subject


def _official_subject(result: AnswerResult, fallback_subject: str) -> str:
    query = str(result.query or "")
    lowered = query.lower()
    if _has_buildconfig_intent(query, result.citations[0] if result.citations else None):
        return "BuildConfig 공식문서"
    if "router" in lowered or "라우터" in lowered:
        return "Router 공식문서"
    if "아키텍처" in query or "architecture" in lowered or "구성" in query:
        return "OCP 구성 공식문서"
    for citation in result.citations:
        if _is_customer_citation(citation):
            continue
        section = strip_section_prefix(citation.section)
        if section:
            return section
    return fallback_subject or "공식문서"


def _is_training_query(query: str) -> bool:
    return any(token in str(query or "") for token in ("교육", "학습", "신규 운영자", "온보딩", "커리큘럼"))


def _is_blended_runtime_query(result: AnswerResult) -> bool:
    query = str(result.query or "")
    lowered = query.lower()
    has_bridge_word = any(token in query for token in ("같이", "함께", "대조", "비교")) or any(
        token in lowered for token in ("together", "alongside", "compare")
    )
    return _has_customer_runtime(result) and _has_official_runtime(result) and (
        has_bridge_word or _is_customer_context_query(query)
    )


def _has_verification_intent(query: str) -> bool:
    normalized = str(query or "").lower()
    return any(token in str(query or "") for token in ("검증", "확인", "상태", "증거", "산출물")) or any(
        token in normalized
        for token in (
            "verify",
            "verification",
            "validate",
            "status",
            "evidence",
        )
    )


def _verification_question(subject: str, citation: Citation | None) -> str:
    if citation is not None and citation.verification_hints:
        hint = citation.verification_hints[0].strip()
        if hint:
            return f"{subject} 적용 후 검증 포인트를 기준으로 다시 정리해줘"
    return f"{subject} 적용 후 검증 방법도 알려줘"


def _branch_question(subject: str, citation: Citation | None) -> str:
    if citation is not None and (citation.error_strings or citation.chunk_type == "troubleshooting"):
        return f"{subject} 진행 중 문제가 나면 어떤 오류나 이벤트부터 봐야 해?"
    return f"{subject} 진행 중 막히면 다음에는 어디부터 확인해야 해?"


def _procedure_plan(subject: str, citation: Citation | None) -> NextPlayPlan:
    next_action = f"{subject} 실행 절차를 순서대로 다시 보여줘"
    if citation is not None and citation.cli_commands:
        next_action = f"{subject} 실행 명령만 추려서 다시 보여줘"
    return NextPlayPlan(
        next_action=next_action,
        verification=_verification_question(subject, citation),
        next_branch=_branch_question(subject, citation),
    )


def build_next_play_plan(
    *,
    session_topic: str,
    result: AnswerResult,
) -> NextPlayPlan | None:
    if result.response_kind != "rag" or not result.citations or not result.cited_indices or result.warnings:
        return None

    query = (result.query or "").strip()
    topic = (session_topic or "").strip()
    citation = result.citations[0] if result.citations else None
    subject = _subject_from(result, citation, topic)
    customer_context = _has_customer_runtime(result) or _is_customer_context_query(query)

    if _is_blended_runtime_query(result):
        customer_subject = _customer_subject(result, subject)
        official_subject = _official_subject(result, subject)
        if _is_training_query(query):
            return NextPlayPlan(
                next_action=f"{customer_subject}를 오전/오후 실습 순서로 다시 짜줘",
                verification="교육 후 운영자가 확인해야 할 산출물과 체크포인트를 표로 정리해줘",
                next_branch=f"{official_subject}와 고객 운영북 기준이 다른 부분을 따로 표시해줘",
            )
        return NextPlayPlan(
            next_action=f"{customer_subject}와 {official_subject}를 나란히 비교해서 체크리스트로 만들어줘",
            verification=f"{customer_subject} 기준으로 실제 운영 확인 명령과 증거를 어떻게 남길지 알려줘",
            next_branch=f"{official_subject}와 고객 운영북이 다를 때 우선순위 판단 기준을 알려줘",
        )

    if customer_context:
        customer_subject = _customer_subject(result, subject)
        if _is_training_query(query):
            return NextPlayPlan(
                next_action=f"{customer_subject}를 초급/중급/실습 순서로 다시 구성해줘",
                verification="교육 완료 여부를 확인할 체크리스트와 산출물을 알려줘",
                next_branch="운영자가 막히기 쉬운 구간과 보강 문서를 알려줘",
            )
        if "ci/cd" in query.lower() or "cicd" in query.lower():
            return NextPlayPlan(
                next_action=f"{customer_subject}를 빌드-배포-검증 흐름으로 다시 정리해줘",
                verification="고객 CI/CD 운영에서 실제로 확인해야 할 로그와 산출물을 알려줘",
                next_branch="고객 CI/CD 장애가 나면 공식 BuildConfig 문서와 어디를 대조해야 해?",
            )
        return NextPlayPlan(
            next_action=f"{customer_subject} 기준으로 바로 실행할 운영 체크리스트를 만들어줘",
            verification=f"{customer_subject} 적용 후 확인해야 할 증거와 산출물을 알려줘",
            next_branch="고객 운영북과 공식문서가 다를 때 어떤 기준으로 판단해야 해?",
        )

    if _has_buildconfig_intent(query, citation):
        verification = "BuildConfig 적용 후 build와 pod 상태를 검증하는 순서를 알려줘"
        if _has_verification_intent(query):
            verification = "BuildConfig 적용 후 oc describe bc와 oc get builds 결과를 검증 증거로 어떻게 남겨야 해?"
            if "oc describe bc" in query.lower() or "검증 증거" in query:
                verification = "BuildConfig 검증 결과에서 build 이벤트와 로그 확인 기준을 알려줘"
        return NextPlayPlan(
            next_action="BuildConfig 상태 확인 명령만 모아서 다시 보여줘",
            verification=verification,
            next_branch="BuildConfig 빌드가 실패하면 이벤트와 로그를 어디부터 봐야 해?",
        )

    if has_rbac_intent(query) or topic == "RBAC":
        return NextPlayPlan(
            next_action="같은 권한을 RoleBinding YAML로 적용하는 예시도 보여줘",
            verification="권한이 제대로 들어갔는지 확인하는 명령도 알려줘",
            next_branch="권한이 너무 넓게 들어갔을 때 회수하는 방법도 알려줘",
        )
    if has_project_terminating_intent(query) or has_project_finalizer_intent(query):
        return NextPlayPlan(
            next_action="걸려 있는 리소스를 찾는 절차를 알려줘",
            verification="삭제 진행 상태를 확인하는 방법도 알려줘",
            next_branch="finalizer 제거 전에 확인해야 할 위험 요소도 알려줘",
        )
    if has_certificate_monitor_intent(query):
        return NextPlayPlan(
            next_action="인증서 상태를 점검하는 명령을 다시 정리해줘",
            verification="만료 임박 여부를 확인하는 기준도 알려줘",
            next_branch="갱신이나 점검이 실패하면 어디부터 봐야 하는지 알려줘",
        )
    if ETCD_RE.search(query) or "etcd" in topic.lower():
        if has_backup_restore_intent(query) or "백업" in topic or "복원" in topic:
            return NextPlayPlan(
                next_action="etcd 허브에서 같이 봐야 할 운영 문서를 보여줘",
                verification="복원 후 Machine Configuration은 왜 같이 봐야 하는지 알려줘",
                next_branch="백업 후 Monitoring에서는 어떤 신호를 먼저 확인해야 해?",
            )
        return NextPlayPlan(
            next_action="etcd 허브에서 바로 가야 할 관련 문서를 보여줘",
            verification="etcd 상태를 확인한 다음 어떤 북으로 이어가야 해?",
            next_branch="장애가 나면 Monitoring이나 Backup and Restore 중 어디부터 보는 게 맞아?",
        )
    if MCO_RE.search(query) or "machine config operator" in topic.lower():
        return NextPlayPlan(
            next_action="Machine Config Operator 허브에서 같이 봐야 할 문서를 보여줘",
            verification="MCP 확인 다음에 Monitoring에서는 뭘 봐야 하는지 알려줘",
            next_branch="MCO가 Degraded면 어떤 관련 북으로 이동해야 하는지 알려줘",
        )
    if has_deployment_scaling_intent(query):
        return NextPlayPlan(
            next_action="deployment replicas를 바로 변경하는 명령 예시를 보여줘",
            verification="적용 후 replicas가 바뀌었는지 확인하는 명령도 알려줘",
            next_branch="스케일이 반영되지 않으면 어디부터 확인해야 해?",
        )
    if has_route_ingress_compare_intent(query):
        return NextPlayPlan(
            next_action="OpenShift에서 Route를 실제로 만드는 예시를 보여줘",
            verification="노출이 정상인지 확인하는 명령과 체크포인트를 알려줘",
            next_branch="접속이 안 되거나 503이면 어디부터 봐야 하는지 알려줘",
        )
    if has_openshift_kubernetes_compare_intent(query) or is_generic_intro_query(query):
        return NextPlayPlan(
            next_action="운영 입문 기준으로 먼저 봐야 할 플레이북 3개를 알려줘",
            verification="기본 상태 확인 뒤 어떤 허브로 들어가야 하는지 알려줘",
            next_branch="문제가 생기면 위키 안에서 어떤 순서로 이동해야 하는지 알려줘",
        )
    if has_doc_locator_intent(query):
        return NextPlayPlan(
            next_action="이 문서 기준으로 바로 실행할 절차만 추려줘",
            verification="실행 후 검증 포인트도 같이 정리해줘",
            next_branch="실패 시 다음 분기까지 같이 정리해줘",
        )
    if citation is not None and citation.chunk_type in {"procedure", "command", "troubleshooting"}:
        return _procedure_plan(subject, citation)
    if citation is not None and citation.operator_names:
        operator_subject = citation.operator_names[0].strip() or subject
        return NextPlayPlan(
            next_action=f"{operator_subject} 설치나 적용 다음에 무엇을 확인해야 해?",
            verification=f"{operator_subject} 정상 동작 여부를 어디서 확인해?",
            next_branch=f"{operator_subject} 관련 문제가 나면 어디부터 봐야 해?",
        )
    return NextPlayPlan(
        next_action=f"{subject} 관련 다음 작업을 이어서 알려줘",
        verification=_verification_question(subject, citation),
        next_branch=_branch_question(subject, citation),
    )
