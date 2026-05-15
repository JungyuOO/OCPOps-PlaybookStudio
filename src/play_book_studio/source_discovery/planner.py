from __future__ import annotations

import re
from typing import Any, cast

from play_book_studio.source_discovery.models import (
    GOLD_ALLOWED_AFTER_VALIDATION,
    GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
    NEED_COMMUNITY_TROUBLESHOOTING,
    NEED_KNOWN_ISSUE,
    NEED_OFFICIAL_MANUAL_GAP,
    NEED_SOURCE_CODE_REFERENCE,
    NEED_VENDOR_KB,
    RISK_LOW,
    RISK_MEDIUM,
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_OFFICIAL_MANUAL,
    SOURCE_LANE_OFFICIAL_SOURCE_REPO,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
    SOURCE_LANE_VENDOR_KB,
    SourceDiscoveryPlan,
    SourceDiscoverySearchQuery,
    SourceLane,
)


SOURCE_DISCOVERY_PLANNER_MODE = "deterministic_contract_v1"

_ASCII_SIGNAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,}")

_TROUBLESHOOTING_TERMS = (
    "장애",
    "에러",
    "오류",
    "실패",
    "복구",
    "로그",
    "원인",
    "crashloopbackoff",
    "imagepullbackoff",
    "pending",
    "timeout",
    "failed",
    "failure",
    "error",
    "exception",
    "troubleshoot",
    "debug",
    "recover",
)
_SOURCE_REPO_TERMS = (
    "소스",
    "코드",
    "설정",
    "config",
    "yaml",
    "manifest",
    "operator",
    "controller",
    "repository",
    "source",
)
_KNOWN_ISSUE_TERMS = (
    "bug",
    "버그",
    "known issue",
    "regression",
    "이슈",
    "pr",
    "pull request",
)
_VENDOR_TERMS = (
    "support",
    "지원",
    "case",
    "kb",
    "knowledgebase",
    "red hat solution",
    "vendor",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "include", "included"}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def _provider_signal_query(question: str) -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _ASCII_SIGNAL_RE.findall(question):
        normalized = token.strip(".,:;")
        if not normalized or normalized.lower() in {"the", "and", "for", "with", "from"}:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(normalized)
    if not tokens:
        return _clean_text(question)
    if not any(token.lower() == "openshift" for token in tokens):
        tokens.insert(0, "OpenShift")
    return " ".join(tokens[:6])


def _question_from_payload(payload: dict[str, Any]) -> str:
    return _clean_text(
        payload.get("question")
        or payload.get("query")
        or payload.get("repository_query")
        or payload.get("source_request_query")
        or ""
    )


def _source_mode(payload: dict[str, Any]) -> str:
    return _clean_text(payload.get("source_mode") or payload.get("mode") or "guided").lower()


def _lanes_from_payload(payload: dict[str, Any], *, question: str, failed_answer: str) -> tuple[SourceLane, ...]:
    source_mode = _source_mode(payload)
    combined_text = " ".join([question, failed_answer, _clean_text(payload.get("failure_reason") or "")])
    has_trouble_signal = _contains_any(combined_text, _TROUBLESHOOTING_TERMS)
    wants_source_repo = _contains_any(combined_text, _SOURCE_REPO_TERMS)
    wants_issue = _contains_any(combined_text, _KNOWN_ISSUE_TERMS) or has_trouble_signal
    wants_vendor = _contains_any(combined_text, _VENDOR_TERMS)
    official_only = source_mode in {"official_only", "official", "manual_only"}
    include_community = (
        _truthy(payload.get("include_community"))
        or source_mode in {"include_community", "perplexity", "wide", "web"}
        or has_trouble_signal
    )
    allow_unverified = _truthy(payload.get("allow_unverified")) or source_mode in {"unsafe_unverified", "unverified"}

    lanes: list[SourceLane] = [SOURCE_LANE_OFFICIAL_MANUAL]
    if wants_source_repo or not official_only:
        lanes.append(SOURCE_LANE_OFFICIAL_SOURCE_REPO)
    if not official_only and wants_issue:
        lanes.append(SOURCE_LANE_OFFICIAL_ISSUE_PR)
    if not official_only and include_community:
        lanes.append(SOURCE_LANE_COMMUNITY_TROUBLESHOOTING)
        if wants_vendor or has_trouble_signal or include_community:
            lanes.append(SOURCE_LANE_VENDOR_KB)
    if not official_only and allow_unverified:
        lanes.append(SOURCE_LANE_UNSAFE_UNVERIFIED)

    seen: set[SourceLane] = set()
    ordered: list[SourceLane] = []
    for lane in lanes:
        if lane in seen:
            continue
        seen.add(lane)
        ordered.append(lane)
    return tuple(ordered)


def _need_type_for_payload(payload: dict[str, Any], *, question: str, failed_answer: str, lanes: tuple[SourceLane, ...]) -> str:
    explicit = _clean_text(payload.get("need_type") or "")
    if explicit:
        return explicit
    combined_text = " ".join([question, failed_answer, _clean_text(payload.get("failure_reason") or "")])
    if SOURCE_LANE_COMMUNITY_TROUBLESHOOTING in lanes:
        return NEED_COMMUNITY_TROUBLESHOOTING
    if SOURCE_LANE_VENDOR_KB in lanes:
        return NEED_VENDOR_KB
    if _contains_any(combined_text, _KNOWN_ISSUE_TERMS) or SOURCE_LANE_OFFICIAL_ISSUE_PR in lanes:
        return NEED_KNOWN_ISSUE
    if _contains_any(combined_text, _SOURCE_REPO_TERMS):
        return NEED_SOURCE_CODE_REFERENCE
    return NEED_OFFICIAL_MANUAL_GAP


def _query_for_lane(question: str, lane: SourceLane) -> str:
    if lane == SOURCE_LANE_OFFICIAL_MANUAL:
        return question
    if lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
        return "openshift-docs"
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        return _provider_signal_query(question)
    if lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
        return f"{_provider_signal_query(question)} troubleshooting"
    if lane == SOURCE_LANE_VENDOR_KB:
        return f"{_provider_signal_query(question)} Red Hat knowledgebase solution"
    return f"{question} unverified source review"


def _purpose_for_lane(lane: SourceLane) -> str:
    if lane == SOURCE_LANE_OFFICIAL_MANUAL:
        return "공식 매뉴얼에서 Gold 후보가 될 수 있는 원천 근거를 찾는다."
    if lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
        return "공식 소스/문서 레포에서 구현, 설정, 원문 AsciiDoc 근거를 찾는다."
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        return "공식 조직의 issue/PR에서 알려진 문제, 변경 이력, maintainer signal을 찾는다."
    if lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
        return "커뮤니티 장애 사례에서 단서를 찾되 공식 근거와 교차 검증한다."
    if lane == SOURCE_LANE_VENDOR_KB:
        return "벤더 KB에서 운영 장애 단서를 찾되 공식 절차와 교차 검증한다."
    return "출처 불명 자료는 참고만 하고 승격 대상에서 제외한다."


def _expected_evidence_for_lane(lane: SourceLane) -> str:
    if lane == SOURCE_LANE_OFFICIAL_MANUAL:
        return "공식 문서 URL, 제품 버전, 섹션 제목"
    if lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
        return "공식 repo, branch/tag, 파일 경로, commit 또는 release 기준"
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        return "repo, issue/PR 번호, 상태, maintainer 답변 또는 merge 여부"
    if lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
        return "글 URL, 환경 조건, 재현 가능한 로그/명령, 공식 근거와의 교차 검증 결과"
    if lane == SOURCE_LANE_VENDOR_KB:
        return "벤더 문서 URL, 적용 버전, 게시/수정일, 공식 절차와의 충돌 여부"
    return "URL, 출처 불명 사유, 사용 금지 또는 참고 전용 표시"


def _reason_for_payload(payload: dict[str, Any], *, lanes: tuple[SourceLane, ...]) -> str:
    explicit = _clean_text(payload.get("reason") or "")
    if explicit:
        return explicit
    if SOURCE_LANE_COMMUNITY_TROUBLESHOOTING in lanes:
        return "답변 품질을 높이려면 공식 문서뿐 아니라 실제 장애/운영 사례 단서가 필요하다."
    if SOURCE_LANE_OFFICIAL_ISSUE_PR in lanes:
        return "공식 문서만으로 부족할 수 있어 알려진 이슈나 변경 이력 확인이 필요하다."
    if SOURCE_LANE_OFFICIAL_SOURCE_REPO in lanes:
        return "공식 문서 후보와 원천 레포 근거를 함께 확인해야 한다."
    return "공식 매뉴얼 후보를 찾아 Library/Gold corpus 보강 여부를 판단한다."


def _next_actions(plan: SourceDiscoveryPlan) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for query in plan.search_queries:
        if query.lane == SOURCE_LANE_OFFICIAL_MANUAL:
            actions.append({"lane": query.lane, "action": "search_official_catalog", "query": query.query})
        elif query.lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
            actions.append({"lane": query.lane, "action": "search_github_repositories", "query": query.query})
        elif query.lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
            actions.append({"lane": query.lane, "action": "search_github_issues_prs", "query": query.query})
        elif query.lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
            actions.append({"lane": query.lane, "action": "search_community_troubleshooting", "query": query.query})
        elif query.lane == SOURCE_LANE_VENDOR_KB:
            actions.append({"lane": query.lane, "action": "search_vendor_kb", "query": query.query})
        else:
            actions.append({"lane": query.lane, "action": "hold_for_manual_review", "query": query.query})
    return actions


def build_source_discovery_plan_from_payload(payload: dict[str, Any]) -> SourceDiscoveryPlan:
    question = _question_from_payload(payload)
    if not question:
        raise ValueError("question 또는 query가 필요합니다.")
    failed_answer = _clean_text(payload.get("failed_answer") or payload.get("answer") or "")
    response_kind = _clean_text(payload.get("response_kind") or "")
    lanes = _lanes_from_payload(payload, question=question, failed_answer=failed_answer)
    search_queries = tuple(
        SourceDiscoverySearchQuery(
            query=_query_for_lane(question, lane),
            lane=lane,
            purpose=_purpose_for_lane(lane),
            expected_evidence=_expected_evidence_for_lane(lane),
        )
        for lane in lanes
    )
    return SourceDiscoveryPlan(
        source_request_id=_clean_text(payload.get("source_request_id") or payload.get("request_id") or ""),
        question=question,
        failed_answer=failed_answer,
        response_kind=response_kind,
        need_type=cast(Any, _need_type_for_payload(payload, question=question, failed_answer=failed_answer, lanes=lanes)),
        reason=_reason_for_payload(payload, lanes=lanes),
        allowed_lanes=lanes,
        search_queries=search_queries,
        risk_level=RISK_MEDIUM if len(lanes) > 2 else RISK_LOW,
        gold_policy=GOLD_REQUIRES_OFFICIAL_CROSS_CHECK if len(lanes) > 2 else GOLD_ALLOWED_AFTER_VALIDATION,
        requires_human_review=len(lanes) > 2,
        evidence=tuple(str(item) for item in (payload.get("evidence") or ()) if str(item).strip())
        if isinstance(payload.get("evidence"), list)
        else (),
    )


def build_source_discovery_plan_response(payload: dict[str, Any]) -> dict[str, Any]:
    plan = build_source_discovery_plan_from_payload(payload)
    return {
        "success": True,
        "planner_mode": SOURCE_DISCOVERY_PLANNER_MODE,
        "llm_planner_enabled": False,
        "plan": plan.to_dict(),
        "next_actions": _next_actions(plan),
        "notes": [
            "현재 planner는 deterministic contract 모드입니다.",
            "LLM planner는 이 API 계약 위에 후속 단계로 연결합니다.",
        ],
    }
