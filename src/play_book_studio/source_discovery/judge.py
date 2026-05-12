from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.source_discovery.models import (
    GOLD_NOT_ELIGIBLE,
    GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_OFFICIAL_MANUAL,
    SOURCE_LANE_OFFICIAL_SOURCE_REPO,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
    SOURCE_LANE_VENDOR_KB,
)


SOURCE_DISCOVERY_JUDGE_SCHEMA = "source_discovery_judge_report_v1"
JUDGE_VERDICT_PASS = "pass"
JUDGE_VERDICT_NEEDS_REVIEW = "needs_review"
JUDGE_VERDICT_NEEDS_REPLAY = "needs_replay"
JUDGE_VERDICT_FAIL = "fail"

AUTHORITATIVE_LANES = frozenset({SOURCE_LANE_OFFICIAL_MANUAL, SOURCE_LANE_OFFICIAL_SOURCE_REPO})
REVIEW_REQUIRED_LANES = frozenset(
    {
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
        SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
        SOURCE_LANE_VENDOR_KB,
        SOURCE_LANE_UNSAFE_UNVERIFIED,
    }
)
AUTHORITATIVE_RUNTIME_TRUTHS = frozenset({"official_gold_playbook_runtime", "official_validated_runtime"})
REVIEW_REQUIRED_RUNTIME_TRUTHS = frozenset({"official_candidate_runtime"})
AUTHORITATIVE_SOURCE_LANE_ALIASES = frozenset({"official", "official_ko", "official_docs", "official_manual_ko"})

_CITATION_MARKER_RE = re.compile(r"\[\d+\]")
_ACTION_SEVERITY_INFO = "info"
_ACTION_SEVERITY_WARNING = "warning"
_ACTION_SEVERITY_CRITICAL = "critical"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    rows: list[str] = []
    for value in values:
        item = _clean_text(value)
        if item:
            rows.append(item)
    return rows


def _dict_rows(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, dict)]


def _record_key(record: dict[str, Any]) -> str:
    candidate_id = _clean_text(record.get("candidate_id"))
    if candidate_id:
        return f"id:{candidate_id}"
    return "|".join(
        [
            _lane_from_record(record),
            _clean_text(record.get("provider")),
            _clean_text(record.get("query") or record.get("source_request_query")),
            _clean_text(record.get("source_url") or record.get("html_url")),
            _clean_text(record.get("source_ref")),
            _record_title(record),
        ]
    )


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for record in records:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        rows.append(record)
    return rows


def _lane_from_record(record: dict[str, Any]) -> str:
    for key in ("lane", "source_lane"):
        value = _clean_text(record.get(key))
        if value:
            if value in AUTHORITATIVE_LANES or value in REVIEW_REQUIRED_LANES:
                return value
            if value in AUTHORITATIVE_SOURCE_LANE_ALIASES:
                return SOURCE_LANE_OFFICIAL_MANUAL
            return value
    boundary_truth = _clean_text(record.get("boundary_truth"))
    if boundary_truth in AUTHORITATIVE_RUNTIME_TRUTHS:
        return SOURCE_LANE_OFFICIAL_MANUAL
    if boundary_truth in REVIEW_REQUIRED_RUNTIME_TRUTHS:
        return SOURCE_LANE_OFFICIAL_ISSUE_PR
    if boundary_truth == "private_customer_pack_runtime":
        return SOURCE_LANE_VENDOR_KB
    source_basis = _clean_text(record.get("source_basis") or record.get("current_source_basis"))
    if source_basis in {"official_homepage", "official_repo"}:
        return SOURCE_LANE_OFFICIAL_MANUAL if source_basis == "official_homepage" else SOURCE_LANE_OFFICIAL_SOURCE_REPO
    trust_level = _clean_text(record.get("trust_level"))
    if trust_level == "authoritative":
        return SOURCE_LANE_OFFICIAL_MANUAL
    label_blob = " ".join(
        _clean_text(record.get(key))
        for key in ("source_collection", "source_label", "book_slug", "book_title", "provider")
    ).lower()
    if "community" in label_blob:
        return SOURCE_LANE_COMMUNITY_TROUBLESHOOTING
    if "vendor" in label_blob or "solution" in label_blob or "knowledge" in label_blob:
        return SOURCE_LANE_VENDOR_KB
    if "issue" in label_blob or "pull" in label_blob or "github_issues" in label_blob:
        return SOURCE_LANE_OFFICIAL_ISSUE_PR
    if "official" in label_blob or "openshift_docs" in label_blob or "official_docs" in label_blob:
        return SOURCE_LANE_OFFICIAL_MANUAL
    return ""


def _is_authoritative(record: dict[str, Any]) -> bool:
    lane = _lane_from_record(record)
    if lane in REVIEW_REQUIRED_LANES:
        return False
    if lane in AUTHORITATIVE_LANES:
        return True
    if _clean_text(record.get("trust_level")) == "authoritative":
        return True
    basis = _clean_text(record.get("source_basis") or record.get("current_source_basis"))
    return basis in {"official_homepage", "official_repo"}


def _record_title(record: dict[str, Any]) -> str:
    return (
        _clean_text(record.get("title"))
        or _clean_text(record.get("source_label"))
        or _clean_text(record.get("book_title"))
        or _clean_text(record.get("book_slug"))
        or _clean_text(record.get("source_ref"))
        or _clean_text(record.get("source_url"))
        or "source"
    )


def _record_is_citation_eligible(record: dict[str, Any]) -> bool:
    if "citation_eligible" in record:
        return bool(record.get("citation_eligible"))
    return _is_authoritative(record)


def _record_blocks_gold(record: dict[str, Any]) -> bool:
    blockers = _clean_list(record.get("promotion_blockers") or [])
    if blockers:
        return True
    if _clean_text(record.get("gold_policy")) in {GOLD_NOT_ELIGIBLE, GOLD_REQUIRES_OFFICIAL_CROSS_CHECK}:
        return True
    if "can_promote_to_gold" in record and not bool(record.get("can_promote_to_gold")):
        return True
    return _lane_from_record(record) in REVIEW_REQUIRED_LANES


def _answer_delta(before_answer: str, after_answer: str, citation_count: int) -> dict[str, Any]:
    before_len = len(before_answer)
    after_len = len(after_answer)
    after_has_citation_marker = bool(_CITATION_MARKER_RE.search(after_answer))
    if not after_answer:
        verdict = JUDGE_VERDICT_NEEDS_REPLAY
    elif not before_answer:
        verdict = JUDGE_VERDICT_NEEDS_REVIEW
    elif after_len >= max(before_len, 1) and (citation_count > 0 or after_has_citation_marker):
        verdict = JUDGE_VERDICT_PASS
    else:
        verdict = JUDGE_VERDICT_NEEDS_REVIEW
    return {
        "before_answer_present": bool(before_answer),
        "after_answer_present": bool(after_answer),
        "before_length": before_len,
        "after_length": after_len,
        "after_has_citation_marker": after_has_citation_marker,
        "improvement_signal": after_len > before_len and (citation_count > 0 or after_has_citation_marker),
        "verdict": verdict,
    }


def _judge_id_payload(question: str, before_answer: str, after_answer: str, source_titles: list[str]) -> dict[str, Any]:
    return {
        "question": question,
        "before_answer": before_answer[:500],
        "after_answer": after_answer[:500],
        "source_titles": source_titles[:20],
    }


def source_discovery_judge_id(question: str, before_answer: str, after_answer: str, source_titles: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            _judge_id_payload(question, before_answer, after_answer, source_titles),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]


def _action(
    *,
    action_id: str,
    label: str,
    description: str,
    severity: str,
    query: str,
    lane: str = "",
) -> dict[str, str]:
    row = {
        "action_id": action_id,
        "label": label,
        "description": description,
        "severity": severity,
        "query": query,
    }
    if lane:
        row["lane"] = lane
    return row


def _dedupe_actions(actions: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, str]] = []
    for action in actions:
        key = (
            _clean_text(action.get("action_id")),
            _clean_text(action.get("lane")),
            _clean_text(action.get("query")),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(action)
    return rows


def _build_next_actions(
    *,
    question: str,
    overall_verdict: str,
    remaining_gap: list[str],
    review_required_lanes: list[str],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []

    if overall_verdict == JUDGE_VERDICT_PASS:
        actions.append(
            _action(
                action_id="record_answerable_case",
                label="답변 가능 케이스로 기록",
                description="공식 근거와 RAG 재답변이 통과했으므로 같은 질문 유형을 Gold/운영 위키 개선 후보로 남깁니다.",
                severity=_ACTION_SEVERITY_INFO,
                query=question,
            )
        )
        return actions

    if "after_answer_replay_required" in remaining_gap:
        actions.append(
            _action(
                action_id="rerun_rag_replay",
                label="RAG 재답변 다시 실행",
                description="새 근거를 넣은 뒤 실제 챗봇 답변이 만들어졌는지 다시 확인합니다.",
                severity=_ACTION_SEVERITY_WARNING,
                query=question,
            )
        )

    if any(
        gap in remaining_gap
        for gap in ("official_cross_check_missing", "official_cross_check_unproven", "official_citation_missing", "community_only_risk")
    ):
        actions.append(
            _action(
                action_id="search_official_manual",
                label="공식 매뉴얼 근거 찾기",
                description="커뮤니티/후보 자료만으로는 Gold 승격이나 최종 답변 인용을 통과시킬 수 없습니다.",
                severity=_ACTION_SEVERITY_WARNING,
                query=question,
                lane=SOURCE_LANE_OFFICIAL_MANUAL,
            )
        )
        actions.append(
            _action(
                action_id="search_official_source_repo",
                label="공식 소스 레포 근거 찾기",
                description="공식 문서가 부족하면 OpenShift 공식 레포/코드 근거로 교차검증 후보를 확보합니다.",
                severity=_ACTION_SEVERITY_INFO,
                query=question,
                lane=SOURCE_LANE_OFFICIAL_SOURCE_REPO,
            )
        )

    if "review_required_sources_pending" in remaining_gap:
        lanes = review_required_lanes or [""]
        for lane in lanes:
            actions.append(
                _action(
                    action_id="verify_bronze_queue",
                    label="Bronze 후보 검증",
                    description="검증 대기 source candidate를 공식 근거와 대조하고 인용 허용 여부를 결정합니다.",
                    severity=_ACTION_SEVERITY_WARNING,
                    query=question,
                    lane=lane,
                )
            )

    if "non_eligible_source_cited" in remaining_gap:
        actions.append(
            _action(
                action_id="replace_non_eligible_citations",
                label="비인용 근거 교체",
                description="Issue/PR, 커뮤니티, 후보 runtime 등 citation blocked 근거가 답변 인용에 들어갔습니다.",
                severity=_ACTION_SEVERITY_CRITICAL,
                query=question,
            )
        )

    if "unsafe_source_cited" in remaining_gap:
        actions.append(
            _action(
                action_id="remove_unsafe_citation",
                label="위험 출처 제거",
                description="출처 불명 또는 사용 금지 자료가 인용되었습니다. 답변 근거에서 제거해야 합니다.",
                severity=_ACTION_SEVERITY_CRITICAL,
                query=question,
                lane=SOURCE_LANE_UNSAFE_UNVERIFIED,
            )
        )

    if not actions:
        actions.append(
            _action(
                action_id="manual_judge_review",
                label="Judge 결과 수동 검토",
                description="자동 규칙으로 다음 행동을 확정하지 못했습니다. 답변, citation, source candidate를 직접 확인합니다.",
                severity=_ACTION_SEVERITY_WARNING,
                query=question,
            )
        )

    return _dedupe_actions(actions)


def build_source_discovery_judge_report(
    payload: dict[str, Any],
    *,
    verification_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    question = _clean_text(payload.get("question") or payload.get("query"))
    if not question:
        raise ValueError("question이 필요합니다.")

    before_answer = _clean_text(payload.get("before_answer"))
    after_answer = _clean_text(payload.get("after_answer"))
    citations = _dedupe_records(_dict_rows(payload.get("citations")))
    source_candidates = _dedupe_records(_dict_rows(payload.get("source_candidates")))
    queue_records = _dict_rows(payload.get("verification_records"))
    if verification_records:
        queue_records.extend(_dict_rows(verification_records))
    queue_records = _dedupe_records(queue_records)

    official_citations = [item for item in citations if _is_authoritative(item)]
    non_eligible_citations = [item for item in citations if not _record_is_citation_eligible(item)]
    unsafe_citations = [item for item in citations if _lane_from_record(item) == SOURCE_LANE_UNSAFE_UNVERIFIED]
    official_candidates = [item for item in source_candidates if _is_authoritative(item)]
    review_required_candidates = [
        item for item in [*source_candidates, *queue_records]
        if _lane_from_record(item) in REVIEW_REQUIRED_LANES or _record_blocks_gold(item)
    ]
    blocked_candidates = [
        item for item in [*source_candidates, *queue_records]
        if _lane_from_record(item) == SOURCE_LANE_UNSAFE_UNVERIFIED
        or _clean_text(item.get("gold_policy")) == GOLD_NOT_ELIGIBLE
        or "not_gold_eligible" in _clean_list(item.get("promotion_blockers") or [])
    ]
    claimed_official_cross_check = bool(payload.get("official_cross_check"))
    official_cross_check = bool(official_citations or official_candidates)
    community_or_vendor_records = [
        item for item in [*citations, *source_candidates, *queue_records]
        if _lane_from_record(item) in {SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, SOURCE_LANE_VENDOR_KB}
    ]
    community_only_risk = bool(community_or_vendor_records) and not official_cross_check
    citation_count = len(citations)
    citation_coverage_verdict = (
        JUDGE_VERDICT_PASS
        if official_citations
        else JUDGE_VERDICT_NEEDS_REPLAY
        if not after_answer
        else JUDGE_VERDICT_NEEDS_REVIEW
    )
    answer_delta = _answer_delta(before_answer, after_answer, citation_count)

    remaining_gap: list[str] = []
    if answer_delta["verdict"] == JUDGE_VERDICT_NEEDS_REPLAY:
        remaining_gap.append("after_answer_replay_required")
    if not official_cross_check:
        remaining_gap.append("official_cross_check_missing")
    if claimed_official_cross_check and not official_cross_check:
        remaining_gap.append("official_cross_check_unproven")
    if not official_citations and after_answer:
        remaining_gap.append("official_citation_missing")
    if review_required_candidates:
        remaining_gap.append("review_required_sources_pending")
    if community_only_risk:
        remaining_gap.append("community_only_risk")
    if non_eligible_citations:
        remaining_gap.append("non_eligible_source_cited")
    if unsafe_citations:
        remaining_gap.append("unsafe_source_cited")

    if unsafe_citations or non_eligible_citations:
        source_trust_verdict = JUDGE_VERDICT_FAIL
    elif community_only_risk or review_required_candidates:
        source_trust_verdict = JUDGE_VERDICT_NEEDS_REVIEW
    else:
        source_trust_verdict = JUDGE_VERDICT_PASS

    if source_trust_verdict == JUDGE_VERDICT_FAIL:
        overall_verdict = JUDGE_VERDICT_FAIL
    elif answer_delta["verdict"] == JUDGE_VERDICT_NEEDS_REPLAY:
        overall_verdict = JUDGE_VERDICT_NEEDS_REPLAY
    elif source_trust_verdict == JUDGE_VERDICT_PASS and citation_coverage_verdict == JUDGE_VERDICT_PASS:
        overall_verdict = JUDGE_VERDICT_PASS
    else:
        overall_verdict = JUDGE_VERDICT_NEEDS_REVIEW

    source_titles = [_record_title(item) for item in [*citations, *source_candidates, *queue_records]]
    review_required_lanes = sorted(
        {
            lane
            for lane in (_lane_from_record(item) for item in review_required_candidates)
            if lane
        }
    )
    next_actions = _build_next_actions(
        question=question,
        overall_verdict=overall_verdict,
        remaining_gap=remaining_gap,
        review_required_lanes=review_required_lanes,
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": SOURCE_DISCOVERY_JUDGE_SCHEMA,
        "judge_id": source_discovery_judge_id(question, before_answer, after_answer, source_titles),
        "created_at": now,
        "question": question,
        "before_answer": before_answer,
        "after_answer": after_answer,
        "overall_verdict": overall_verdict,
        "pass_fail": "pass" if overall_verdict == JUDGE_VERDICT_PASS else "fail" if overall_verdict == JUDGE_VERDICT_FAIL else "pending",
        "answer_delta": answer_delta,
        "citation_coverage": {
            "verdict": citation_coverage_verdict,
            "citation_count": citation_count,
            "official_citation_count": len(official_citations),
            "citation_eligible_count": sum(1 for item in citations if _record_is_citation_eligible(item)),
            "non_eligible_citation_count": len(non_eligible_citations),
            "has_citation_markers": bool(_CITATION_MARKER_RE.search(after_answer)),
        },
        "source_trust": {
            "verdict": source_trust_verdict,
            "official_cross_check": official_cross_check,
            "claimed_official_cross_check": claimed_official_cross_check,
            "community_only_risk": community_only_risk,
            "needs_verification_count": len(review_required_candidates),
            "blocked_candidate_count": len(blocked_candidates),
            "unsafe_citation_count": len(unsafe_citations),
            "review_required_lanes": review_required_lanes,
        },
        "remaining_gap": remaining_gap,
        "next_actions": next_actions,
        "evidence": {
            "citations": citations,
            "source_candidates": source_candidates,
            "verification_records": queue_records,
        },
    }


def _judge_report_path(root_dir: Path) -> Path:
    return load_settings(root_dir).artifacts_dir / "source_discovery" / "judge_reports.jsonl"


def save_source_discovery_judge_report(root_dir: Path, payload: dict[str, Any], *, verification_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    report = build_source_discovery_judge_report(payload, verification_records=verification_records)
    path = _judge_report_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")
    return {**report, "path": str(path)}


def list_source_discovery_judge_reports(root_dir: Path, *, limit: int = 20) -> dict[str, Any]:
    path = _judge_report_path(root_dir)
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and _clean_text(payload.get("schema")) == SOURCE_DISCOVERY_JUDGE_SCHEMA:
                rows.append(payload)
    items = sorted(rows, key=lambda item: _clean_text(item.get("created_at")), reverse=True)[: max(1, min(100, limit))]
    return {
        "schema": SOURCE_DISCOVERY_JUDGE_SCHEMA,
        "count": len(items),
        "items": items,
        "path": str(path),
    }
