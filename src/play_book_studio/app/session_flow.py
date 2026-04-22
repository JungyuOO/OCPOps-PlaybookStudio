# 채팅 세션 문맥, follow-up, 추천 질문 규칙을 담당한다.
from __future__ import annotations

import re
from typing import Any

from play_book_studio.answering.models import AnswerResult
from play_book_studio.app.next_play_planner import build_next_play_plan
from play_book_studio.app.sessions import ChatSession, RUNTIME_CHAT_MODE
from play_book_studio.config.packs import default_core_pack
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.text_utils import strip_section_prefix
from play_book_studio.retrieval.query import (
    ARCHITECTURE_RE,
    ETCD_RE,
    MCO_RE,
    OCP_RE,
    OPENSHIFT_RE,
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_logging_ambiguity,
    has_deployment_scaling_intent,
    has_doc_locator_intent,
    has_follow_up_reference,
    has_operator_concept_intent,
    has_openshift_kubernetes_compare_intent,
    has_pod_lifecycle_concept_intent,
    has_pod_pending_troubleshooting_intent,
    has_rbac_intent,
    has_route_ingress_compare_intent,
    has_update_doc_locator_ambiguity,
    is_generic_intro_query,
)

DEFAULT_CORE_VERSION = default_core_pack().version
GENERIC_CITATION_TOPICS = {
    "additional resources",
    "informational resources",
    "legal notice",
    "legal notice abstract",
    "abstract",
    "추가 리소스",
    "법적 공지",
    "법적 공지 초록",
    "초록",
}


def _is_generic_citation_topic(topic: str) -> bool:
    normalized = strip_section_prefix(topic or "").strip().lower()
    return normalized in GENERIC_CITATION_TOPICS

def context_with_request_overrides(
    previous: SessionContext | None,
    *,
    payload: dict[str, Any],
    mode: str,
    default_ocp_version: str = DEFAULT_CORE_VERSION,
) -> SessionContext:
    del mode
    context = SessionContext.from_dict(previous.to_dict() if previous else None)
    context.mode = RUNTIME_CHAT_MODE
    requested_user_id = str(payload.get("user_id") or "").strip()
    if requested_user_id:
        context.user_id = requested_user_id
    requested_version = str(payload.get("ocp_version") or "").strip()
    if requested_version:
        context.ocp_version = requested_version
    elif not context.ocp_version:
        context.ocp_version = default_ocp_version

    selected_draft_ids = payload.get("selected_draft_ids")
    if isinstance(selected_draft_ids, list):
        context.selected_draft_ids = [
            str(item).strip()
            for item in selected_draft_ids
            if str(item).strip()
        ]
    context.restrict_uploaded_sources = bool(payload.get("restrict_uploaded_sources", True))
    return context

def is_task_topic(topic: str) -> bool:
    normalized = (topic or "").strip()
    if not normalized:
        return False
    return normalized in {
        "Deployment 스케일링",
        "etcd 백업/복원",
        "RBAC",
        "Operator",
        "Machine Config Operator",
        "OpenShift 아키텍처",
        "Route와 Ingress 비교",
    }

def infer_explicit_topic(query: str) -> str | None:
    normalized = (query or "").strip()
    if not normalized:
        return None
    if has_deployment_scaling_intent(normalized):
        return "Deployment 스케일링"
    if has_route_ingress_compare_intent(normalized):
        return "Route와 Ingress 비교"
    if has_operator_concept_intent(normalized):
        return "Operator"
    if ETCD_RE.search(normalized):
        if has_backup_restore_intent(normalized):
            return "etcd 백업/복원"
        return "etcd"
    if MCO_RE.search(normalized):
        return "Machine Config Operator"
    if has_rbac_intent(normalized):
        return "RBAC"
    if OPENSHIFT_RE.search(normalized) or OCP_RE.search(normalized):
        if ARCHITECTURE_RE.search(normalized):
            return "OpenShift 아키텍처"
        if is_generic_intro_query(normalized):
            return "OpenShift"
        return None
    return None

def infer_open_entities(topic: str) -> list[str]:
    normalized = (topic or "").lower()
    if "deployment" in normalized and "스케일" in normalized:
        return ["Deployment", "replicas"]
    if "etcd" in normalized:
        return ["etcd"]
    if normalized == "operator":
        return ["Operator"]
    if "machine config operator" in normalized or "mco" in normalized:
        return ["Machine Config Operator"]
    if "rbac" in normalized:
        return ["RBAC"]
    if "route와 ingress 비교" in normalized:
        return ["OpenShift", "Route", "Ingress"]
    if "openshift" in normalized:
        return ["OpenShift"]
    return []

def derive_next_context(
    previous: SessionContext | None,
    *,
    query: str,
    mode: str,
    result: AnswerResult,
    default_ocp_version: str = DEFAULT_CORE_VERSION,
) -> SessionContext:
    # 멀티턴 채팅에서 세션과 follow-up 맥락을 이어 주는 helper.
    del mode
    next_context = SessionContext.from_dict(previous.to_dict() if previous else None)
    next_context.mode = RUNTIME_CHAT_MODE
    next_context.ocp_version = next_context.ocp_version or default_ocp_version
    normalized_query = (query or "").strip()
    follow_up_reference = has_follow_up_reference(normalized_query)
    prior_goal = (next_context.user_goal or "").strip()
    prior_unresolved = (next_context.unresolved_question or "").strip()

    if result.response_kind in {"smalltalk", "meta", "guide"}:
        return next_context
    if result.response_kind in {"clarification", "no_answer"}:
        if normalized_query and not follow_up_reference:
            next_context.user_goal = normalized_query
        elif not prior_goal and prior_unresolved:
            next_context.user_goal = prior_unresolved
        next_context.unresolved_question = query
        return next_context

    explicit_topic = infer_explicit_topic(query)
    if normalized_query:
        if follow_up_reference:
            next_context.user_goal = prior_goal or prior_unresolved or normalized_query
        else:
            next_context.user_goal = normalized_query
    if explicit_topic:
        next_context.current_topic = explicit_topic
        next_context.open_entities = infer_open_entities(explicit_topic)
        next_context.unresolved_question = None if result.citations else query
    elif result.citations:
        primary = result.citations[0]
        if not (follow_up_reference and is_task_topic(next_context.current_topic or "")):
            primary_topic = strip_section_prefix(primary.section) or next_context.current_topic
            if not _is_generic_citation_topic(primary_topic or ""):
                next_context.current_topic = primary_topic
                next_context.open_entities = infer_open_entities(primary_topic or "")
        next_context.unresolved_question = None
    else:
        next_context.unresolved_question = query
    return next_context

def dedupe_suggestions(candidates: list[str], *, query: str, limit: int = 3) -> list[str]:
    normalized_query = (query or "").strip().lower()
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        cleaned = (candidate or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered == normalized_query or lowered in seen:
            continue
        seen.add(lowered)
        unique.append(cleaned)
        if len(unique) >= limit:
            break
    return unique

def _suggestion_subject(
    *,
    query: str,
    topic: str,
    primary: Any | None,
) -> str:
    normalized = (query or "").strip()
    lowered = normalized.lower()
    if has_route_ingress_compare_intent(normalized):
        return "Route와 Ingress"
    if ETCD_RE.search(normalized):
        return "etcd"
    if MCO_RE.search(normalized):
        return "Machine Config Operator"
    if "operator" in lowered:
        return "Operator"
    if topic:
        stripped_topic = strip_section_prefix(topic)
        if stripped_topic:
            return stripped_topic
    if primary is not None:
        section = strip_section_prefix(getattr(primary, "section", ""))
        if section:
            return section
    explicit = infer_explicit_topic(normalized)
    if explicit:
        return explicit
    return ""

def _contextualize_follow_up(candidate: str, *, subject: str) -> str:
    cleaned = (candidate or "").strip()
    if not cleaned or not subject:
        return cleaned
    replacements = {
        "실행 예시도 같이 보여줘": f"{subject} 관련 실행 예시도 같이 보여줘",
        "주의사항도 함께 정리해줘": f"{subject} 관련 주의사항도 함께 정리해줘",
        "운영 중 주의사항도 함께 정리해줘": f"{subject} 운영 시 주의사항도 함께 정리해줘",
        "상태 확인 방법도 같이 알려줘": f"{subject} 상태 확인 방법도 같이 알려줘",
        "실무에서 언제 쓰는지 알려줘": f"{subject}를 실무에서 언제 쓰는지 알려줘",
        "초보자 기준으로 단계별로 설명해줘": f"{subject}를 초보자 기준으로 단계별로 설명해줘",
        "실무에서 왜 중요한지도 설명해줘": f"{subject}가 실무에서 왜 중요한지도 설명해줘",
    }
    return replacements.get(cleaned, cleaned)

def fallback_follow_up_questions(*, query: str) -> list[str]:
    if (
        is_generic_intro_query(query)
        or has_openshift_kubernetes_compare_intent(query)
        or has_pod_lifecycle_concept_intent(query)
        or has_pod_pending_troubleshooting_intent(query)
    ):
        return [
            "초보자 기준으로 단계별로 설명해줘",
            "실무에서 언제 쓰는지 알려줘",
            "실무에서 왜 중요한지도 설명해줘",
        ]
    return [
        "실행 예시도 같이 보여줘",
        "주의사항도 함께 정리해줘",
        "상태 확인 방법도 같이 알려줘",
    ]

def fallback_no_answer_questions(*, query: str, topic: str = "") -> list[str]:
    lowered = (query or "").lower()
    if "networkpolicy" in lowered:
        return [
            "NetworkPolicy 기본 구조를 예시와 함께 설명해줘",
            "특정 namespace 에서 Pod 간 통신만 허용하는 예시를 보여줘",
            "NetworkPolicy 적용 후 통신 확인 방법도 알려줘",
        ]
    subject = _suggestion_subject(query=query, topic=topic, primary=None)
    return dedupe_suggestions(
        [
            _contextualize_follow_up("초보자 기준으로 단계별로 설명해줘", subject=subject),
            _contextualize_follow_up("실행 예시도 같이 보여줘", subject=subject),
            _contextualize_follow_up("상태 확인 방법도 같이 알려줘", subject=subject),
        ],
        query=query,
        limit=3,
    )

_SUGGESTION_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_-]+")
_BAD_SUGGESTION_PATTERNS = (
    "지원 요청",
    "추가 리소스",
    "확인된 문제",
    "release notes",
    "릴리스",
    "card copy",
    "퀵 스타트",
    "workspace",
    "--cache-dir",
    "--workspace",
    "플래그 정보",
    "oc-mirror",
)

def _tokenize_suggestion_text(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in _SUGGESTION_TOKEN_RE.findall(str(part or "").lower()):
            normalized = token.strip("-_ ")
            if len(normalized) >= 2:
                tokens.add(normalized)
    return tokens

def _is_bad_suggestion_section(section: str) -> bool:
    lowered = str(section or "").strip().lower()
    if not lowered:
        return True
    return any(pattern in lowered for pattern in _BAD_SUGGESTION_PATTERNS)

def _suggestions_from_retrieval_hits(result: AnswerResult) -> list[str]:
    retrieval_trace = result.retrieval_trace or {}
    metrics = retrieval_trace.get("metrics") or {}
    query_tokens = _tokenize_suggestion_text(result.query or "", result.rewritten_query or "")
    candidate_groups: list[list[dict[str, Any]]] = []
    for metric_key in ("vector", "hybrid", "bm25"):
        payload = metrics.get(metric_key) or {}
        top_hits = payload.get("top_hits") if isinstance(payload, dict) else []
        if isinstance(top_hits, list):
            candidate_groups.append(top_hits)
    suggestions: list[str] = []
    seen: set[str] = set()
    for top_hits in candidate_groups:
        for item in top_hits:
            if not isinstance(item, dict):
                continue
            section = str(item.get("section") or "").strip()
            book_slug = str(item.get("book_slug") or "").strip()
            if (
                not section
                or not any("\uac00" <= char <= "\ud7a3" for char in section)
                or _is_bad_suggestion_section(section)
            ):
                continue
            section_tokens = _tokenize_suggestion_text(section, book_slug)
            if query_tokens and not (query_tokens & section_tokens):
                continue
            suggestion = f"{section} 기준으로 설명해줘"
            if suggestion in seen:
                continue
            seen.add(suggestion)
            suggestions.append(suggestion)
            if len(suggestions) >= 3:
                return suggestions
    return suggestions

def suggest_follow_up_questions(*, session: ChatSession, result: AnswerResult) -> list[str]:
    query = (result.query or "").strip()
    normalized = query.lower()
    topic = (session.context.current_topic or "").strip()
    primary = result.citations[0] if result.citations else None
    book_slug = (primary.book_slug if primary else "").lower()
    section = (primary.section if primary else "").lower()

    if result.response_kind == "smalltalk":
        return [
            "오픈시프트가 뭐야?",
            "특정 namespace에 admin 권한 주는 법 알려줘",
            "프로젝트가 Terminating에서 안 지워질 때 어떻게 해?",
        ]
    if result.response_kind == "no_answer":
        retrieval_backed = _suggestions_from_retrieval_hits(result)
        if retrieval_backed:
            return retrieval_backed
        return fallback_no_answer_questions(query=query, topic=topic)
    if result.response_kind == "clarification":
        subject = _suggestion_subject(query=query, topic=topic, primary=primary)
        return dedupe_suggestions(
            [
                _contextualize_follow_up("실행 예시도 같이 보여줘", subject=subject),
                _contextualize_follow_up("상태 확인 방법도 같이 알려줘", subject=subject),
                _contextualize_follow_up("주의사항도 함께 정리해줘", subject=subject),
            ],
            query=query,
            limit=3,
        )
    if (
        result.response_kind != "rag"
        or not result.citations
        or not result.cited_indices
        or result.warnings
    ):
        return []

    play_plan = build_next_play_plan(session_topic=topic, result=result)
    plan_candidates = play_plan.as_list() if play_plan is not None else []

    candidates: list[str] = []

    if has_rbac_intent(query) or topic == "RBAC" or book_slug == "authentication_and_authorization":
        lowered_query = query.lower()
        if "rolebinding" in lowered_query or "yaml" in lowered_query or "manifest" in lowered_query or "예시" in query:
            candidates = [
                "권한이 제대로 들어갔는지 확인하는 명령도 알려줘",
                "권한이 너무 넓게 들어갔을 때 회수하는 방법도 알려줘",
                "edit 나 view 권한을 줄 때는 어떻게 달라?",
            ]
        elif "회수" in query or "제거" in query or "삭제" in query or "해제" in query:
            candidates = [
                "RoleBinding YAML 예시도 보여줘",
                "권한이 제대로 들어갔는지 확인하는 명령도 알려줘",
                "edit 나 view 권한을 줄 때는 어떻게 달라?",
            ]
        elif "확인" in query or "검증" in query or "잘 들어갔" in query:
            candidates = [
                "RoleBinding YAML 예시도 보여줘",
                "권한이 너무 넓게 들어갔을 때 회수하는 방법도 알려줘",
                "edit 나 view 권한을 줄 때는 어떻게 달라?",
            ]
        else:
            candidates = [
                "RoleBinding YAML 예시도 보여줘",
                "권한이 제대로 들어갔는지 확인하는 명령도 알려줘",
                "권한이 너무 넓게 들어갔을 때 회수하는 방법도 알려줘",
                "edit 나 view 권한을 줄 때는 어떻게 달라?",
            ]
    elif "terminating" in normalized or "finalizer" in normalized or "삭제" in query:
        candidates = [
            "걸려 있는 리소스 찾는 명령도 알려줘",
            "finalizers를 안전하게 제거하는 절차를 알려줘",
            "강제 삭제 전에 확인할 점은 뭐야?",
            "namespace 이벤트를 먼저 확인하는 방법도 알려줘",
        ]
    elif has_certificate_monitor_intent(query) or "인증서" in query:
        candidates = [
            "만료 전에 자동 점검하는 방법도 알려줘",
            "인증서 갱신 절차도 같이 알려줘",
            "어떤 인증서를 우선 확인해야 하는지 정리해줘",
        ]
    elif ETCD_RE.search(query) or "etcd" in topic.lower() or book_slug == "etcd":
        if has_backup_restore_intent(query) or "백업" in topic or "복원" in topic:
            candidates = [
                "etcd 허브에서 같이 봐야 할 관련 문서도 보여줘",
                "복원 후 Machine Configuration은 왜 같이 봐야 해?",
                "백업 후 Monitoring에서 어떤 신호를 확인해야 해?",
            ]
        else:
            candidates = [
                "etcd 허브에서 바로 가야 할 운영 문서를 보여줘",
                "etcd 백업은 어떻게 해?",
                "etcd 복원 후 어떤 문서로 이어서 확인해야 해?",
                "장애가 나면 어떤 신호를 먼저 봐야 해?",
            ]
    elif MCO_RE.search(query) or "machine config" in topic.lower() or book_slug in {
        "machine_configuration",
        "operators",
    }:
        candidates = [
            "Machine Config Operator 허브에서 같이 봐야 할 문서를 보여줘",
            "MachineConfigPool 상태는 어떻게 확인해?",
            "노드 설정 변경 뒤 Monitoring에서는 뭘 봐야 해?",
        ]
    elif "monitoring" in normalized or "prometheus" in normalized or "alert" in normalized or book_slug in {
        "monitoring",
        "monitoring_alerts_admin",
        "monitoring_metrics_admin",
        "monitoring_troubleshooting",
    }:
        candidates = [
            "Prometheus 허브에서 같이 봐야 할 운영 문서를 보여줘",
            "경보를 본 다음 어떤 메트릭 문서로 이어가야 해?",
            "Monitoring 장애를 볼 때 Machine Configuration도 같이 봐야 해?",
        ]
    elif has_openshift_kubernetes_compare_intent(query):
        candidates = [
            "OpenShift에서 추가되는 운영 기능은 뭐야?",
            "쿠버네티스 대신 OpenShift를 쓰는 이유는?",
            "Operator가 왜 중요한지도 설명해줘",
        ]
    elif is_generic_intro_query(query) or topic.startswith("OpenShift") or book_slug in {
        "architecture",
        "overview",
    }:
        candidates = [
            "쿠버네티스와 차이도 설명해줘",
            "Operator가 뭐야?",
            "OpenShift 아키텍처를 처음 설명해줘",
            "실무에서 주로 어떤 기능을 쓰는지도 알려줘",
        ]
    elif has_doc_locator_intent(query):
        candidates = [
            "핵심만 먼저 요약해줘",
            "실행 예시도 같이 보여줘",
            "주의사항도 함께 정리해줘",
        ]

    if not candidates and "operator" in section:
        candidates = [
            "Operator가 왜 필요한지 설명해줘",
            "설치 후 상태는 어떻게 확인해?",
            "문제가 나면 어디부터 봐야 해?",
        ]

    if not candidates and "backup" in section:
        candidates = [
            "복원 후 이어서 봐야 할 문서도 알려줘",
            "백업 파일 확인 방법도 알려줘",
            "운영 중 어떤 허브로 이어지는지 정리해줘",
        ]

    subject = _suggestion_subject(query=query, topic=topic, primary=primary)
    source_candidates = plan_candidates + candidates
    if not source_candidates:
        source_candidates = fallback_follow_up_questions(query=query)
    else:
        source_candidates += fallback_follow_up_questions(query=query)
    contextualized = [
        _contextualize_follow_up(candidate, subject=subject)
        for candidate in source_candidates
    ]
    merged = dedupe_suggestions(contextualized, query=query)
    return merged[:3]

__all__ = ["context_with_request_overrides", "dedupe_suggestions", "derive_next_context", "fallback_follow_up_questions", "infer_explicit_topic", "infer_open_entities", "is_task_topic", "suggest_follow_up_questions"]
