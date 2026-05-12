from __future__ import annotations

from http import HTTPStatus

import pytest

from play_book_studio.http import repository_registry, server_routes_ops
from play_book_studio.http.server_support import _build_chat_payload
from play_book_studio.http.sessions import ChatSession
from play_book_studio.http.server_routes_ops import (
    handle_repository_source_discovery_judge_save,
    handle_repository_source_discovery_judge_replay,
    handle_repository_source_discovery_plan,
    handle_repository_source_discovery_verification_save,
)
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.source_discovery import (
    GOLD_ALLOWED_AFTER_VALIDATION,
    GOLD_NOT_ELIGIBLE,
    GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
    SOURCE_DISCOVERY_JUDGE_SCHEMA,
    SOURCE_DISCOVERY_PLAN_SCHEMA,
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_OFFICIAL_MANUAL,
    SOURCE_LANE_OFFICIAL_SOURCE_REPO,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
    SOURCE_LANE_VENDOR_KB,
    SourceDiscoveryPlan,
    SourceDiscoverySearchQuery,
    SourceDiscoveryVerificationRecord,
    build_source_discovery_judge_report,
    build_source_discovery_plan_response,
    build_source_discovery_plan,
    build_verification_record,
    list_source_discovery_judge_reports,
    list_verification_queue,
    save_source_discovery_judge_report,
    save_verification_candidate,
    source_lane_policy,
)


def test_source_discovery_plan_round_trips_with_policy_metadata() -> None:
    plan = build_source_discovery_plan(
        source_request_id="sr-1",
        question="호스팅 컨트롤 플레인 장애 사례를 설명해줘",
        failed_answer="근거가 부족합니다.",
        response_kind="no_answer",
    )

    restored = SourceDiscoveryPlan.from_dict(plan.to_dict())
    payload = restored.to_dict()

    assert payload["schema"] == SOURCE_DISCOVERY_PLAN_SCHEMA
    assert restored.source_request_id == "sr-1"
    assert restored.question == "호스팅 컨트롤 플레인 장애 사례를 설명해줘"
    assert restored.allowed_lanes == (
        SOURCE_LANE_OFFICIAL_MANUAL,
        SOURCE_LANE_OFFICIAL_SOURCE_REPO,
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
    )
    assert restored.gold_policy == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert restored.requires_human_review is True
    assert len(payload["lane_policies"]) == 3


def test_community_or_vendor_lanes_cannot_be_gold_directly() -> None:
    plan = SourceDiscoveryPlan(
        question="etcd quorum lost 복구 방법",
        allowed_lanes=(SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, SOURCE_LANE_VENDOR_KB),
        search_queries=(
            SourceDiscoverySearchQuery(
                query="etcd quorum lost recovery openshift",
                lane=SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
            ),
        ),
        gold_policy=GOLD_ALLOWED_AFTER_VALIDATION,
    )

    assert plan.gold_policy == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert plan.risk_level == "medium"
    assert plan.requires_human_review is True


def test_unsafe_lane_is_never_gold_eligible() -> None:
    plan = SourceDiscoveryPlan(
        question="출처 불명 스크립트를 실행해도 되는지 확인",
        allowed_lanes=(SOURCE_LANE_UNSAFE_UNVERIFIED,),
        search_queries=(
            SourceDiscoverySearchQuery(
                query="random openshift fix script",
                lane=SOURCE_LANE_UNSAFE_UNVERIFIED,
            ),
        ),
        gold_policy=GOLD_ALLOWED_AFTER_VALIDATION,
        risk_level="low",
        requires_human_review=False,
    )

    assert plan.gold_policy == GOLD_NOT_ELIGIBLE
    assert plan.risk_level == "high"
    assert plan.requires_human_review is True


def test_plan_deduplicates_queries_and_lanes() -> None:
    plan = SourceDiscoveryPlan(
        question="router certificate rotation",
        allowed_lanes=(SOURCE_LANE_OFFICIAL_MANUAL, SOURCE_LANE_OFFICIAL_MANUAL),
        search_queries=(
            SourceDiscoverySearchQuery(
                query="router certificate rotation",
                lane=SOURCE_LANE_OFFICIAL_MANUAL,
            ),
            SourceDiscoverySearchQuery(
                query="router certificate rotation",
                lane=SOURCE_LANE_OFFICIAL_MANUAL,
            ),
            SourceDiscoverySearchQuery(
                query="router certificate rotation",
                lane=SOURCE_LANE_OFFICIAL_SOURCE_REPO,
            ),
        ),
    )

    assert plan.allowed_lanes == (SOURCE_LANE_OFFICIAL_MANUAL, SOURCE_LANE_OFFICIAL_SOURCE_REPO)
    assert len(plan.search_queries) == 2


def test_source_lane_policy_rejects_unknown_lane() -> None:
    with pytest.raises(ValueError):
        source_lane_policy("blog_random")


def test_source_discovery_planner_api_opens_troubleshooting_lanes() -> None:
    response = build_source_discovery_plan_response(
        {
            "query": "OpenShift CrashLoopBackOff 원인과 복구 방법",
            "failed_answer": "근거가 부족합니다.",
            "response_kind": "no_answer",
        }
    )

    plan = response["plan"]

    assert response["success"] is True
    assert response["planner_mode"] == "deterministic_contract_v1"
    assert response["llm_planner_enabled"] is False
    assert SOURCE_LANE_OFFICIAL_ISSUE_PR in plan["allowed_lanes"]
    assert SOURCE_LANE_COMMUNITY_TROUBLESHOOTING in plan["allowed_lanes"]
    assert SOURCE_LANE_VENDOR_KB in plan["allowed_lanes"]
    assert plan["gold_policy"] == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert plan["requires_human_review"] is True
    assert any(action["action"] == "search_community_troubleshooting" for action in response["next_actions"])


def test_source_discovery_planner_wide_mode_shows_pending_external_lanes() -> None:
    response = build_source_discovery_plan_response(
        {
            "query": "호스팅 컨트롤 플레인 아키텍처",
            "include_community": True,
        }
    )

    plan = response["plan"]

    assert SOURCE_LANE_COMMUNITY_TROUBLESHOOTING in plan["allowed_lanes"]
    assert SOURCE_LANE_VENDOR_KB in plan["allowed_lanes"]
    assert plan["gold_policy"] == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert plan["requires_human_review"] is True


def test_source_discovery_planner_api_respects_official_only_mode() -> None:
    response = build_source_discovery_plan_response(
        {
            "query": "호스팅 컨트롤 플레인 아키텍처",
            "mode": "official_only",
        }
    )

    plan = response["plan"]

    assert plan["allowed_lanes"] == [SOURCE_LANE_OFFICIAL_MANUAL]
    assert plan["gold_policy"] == GOLD_ALLOWED_AFTER_VALIDATION
    assert plan["requires_human_review"] is False


class _CaptureHandler:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}
        self.status: HTTPStatus = HTTPStatus.OK

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.payload = payload
        self.status = status


def test_source_discovery_plan_handler_returns_bad_request_for_empty_query(tmp_path) -> None:
    handler = _CaptureHandler()

    handle_repository_source_discovery_plan(handler, {"query": "   "}, root_dir=tmp_path)

    assert handler.status == HTTPStatus.BAD_REQUEST
    assert "question" in str(handler.payload["error"])


def test_no_answer_payload_exposes_repository_acquisition(tmp_path) -> None:
    session = ChatSession(session_id="source-request-session")
    result = AnswerResult(
        query="OpenShift 4.21 호스팅 컨트롤 플레인 아키텍처를 요약해줘",
        mode="chat",
        answer="현재 코퍼스 기준으로는 답변할 근거가 부족합니다.",
        rewritten_query="OpenShift 4.21 호스팅 컨트롤 플레인 아키텍처",
        citations=[],
        response_kind="no_answer",
        warnings=["out_of_corpus"],
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)

    assert payload["response_kind"] == "no_answer"
    assert payload["acquisition"]["kind"] == "repository_search"
    assert payload["acquisition"]["confirm_label"] == "자료 보강 요청"
    assert payload["acquisition"]["repository_query"] == result.rewritten_query


def test_source_discovery_search_splits_results_by_lane(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        server_routes_ops,
        "_search_official_source_candidates",
        lambda _root_dir, *, query, limit=8: [
            {
                "book_slug": "troubleshooting",
                "title": "Troubleshooting",
                "viewer_path": "/docs/troubleshooting/index.html",
                "match_score": 88,
            }
        ],
    )
    monkeypatch.setattr(
        server_routes_ops,
        "_search_github_repositories",
        lambda _root_dir, *, query, limit=8: {
            "auth_mode": "token",
            "rewritten_query": "openshift-docs archived:false",
            "results": [{"full_name": "openshift/openshift-docs", "html_url": "https://github.com/openshift/openshift-docs"}],
        },
    )
    monkeypatch.setattr(
        server_routes_ops,
        "_search_github_issues_prs",
        lambda _root_dir, *, query, limit=8, official_scope=True: {
            "auth_mode": "token",
            "rewritten_query": "CrashLoopBackOff org:openshift",
            "results": [{"title": "CrashLoopBackOff known issue", "html_url": "https://github.com/openshift/origin/issues/1"}],
        },
    )

    response = server_routes_ops._build_repository_source_discovery_search(
        tmp_path,
        {
            "query": "OpenShift CrashLoopBackOff 원인과 복구 방법",
            "failed_answer": "근거가 부족합니다.",
            "limit": 3,
        },
    )

    lanes = {row["lane"]: row for row in response["lane_results"]}

    assert response["success"] is True
    assert response["auth_mode"] == "token"
    assert response["totals"]["official_candidates"] == 1
    assert response["totals"]["github_repositories"] == 1
    assert response["totals"]["github_issues_prs"] == 1
    assert lanes[SOURCE_LANE_OFFICIAL_MANUAL]["provider"] == "official_catalog"
    assert lanes[SOURCE_LANE_OFFICIAL_SOURCE_REPO]["provider"] == "github_repositories"
    assert lanes[SOURCE_LANE_OFFICIAL_SOURCE_REPO]["trust_note"] == "openshift GitHub org 소속 repo만 official source로 표시합니다."
    assert lanes[SOURCE_LANE_OFFICIAL_ISSUE_PR]["provider"] == "github_issues_prs"
    assert lanes[SOURCE_LANE_COMMUNITY_TROUBLESHOOTING]["status"] == "not_configured"
    assert "외부 web/provider" in lanes[SOURCE_LANE_COMMUNITY_TROUBLESHOOTING]["message"]
    assert lanes[SOURCE_LANE_VENDOR_KB]["status"] == "not_configured"
    assert "외부 web/provider" in lanes[SOURCE_LANE_VENDOR_KB]["message"]


def test_source_discovery_search_filters_unofficial_repositories_from_official_lane(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        server_routes_ops,
        "_search_official_source_candidates",
        lambda _root_dir, *, query, limit=8: [],
    )
    monkeypatch.setattr(
        server_routes_ops,
        "_search_github_repositories",
        lambda _root_dir, *, query, limit=8: {
            "auth_mode": "public",
            "rewritten_query": "hosted control plane openshift",
            "results": [
                {
                    "full_name": "openshift/openshift-docs",
                    "owner_login": "openshift",
                    "html_url": "https://github.com/openshift/openshift-docs",
                },
                {
                    "full_name": "example-user/openshift-demo",
                    "owner_login": "example-user",
                    "html_url": "https://github.com/example-user/openshift-demo",
                },
            ],
        },
    )
    monkeypatch.setattr(
        server_routes_ops,
        "_search_github_issues_prs",
        lambda _root_dir, *, query, limit=8, official_scope=True: {
            "auth_mode": "public",
            "rewritten_query": query,
            "results": [],
        },
    )

    response = server_routes_ops._build_repository_source_discovery_search(
        tmp_path,
        {
            "query": "OpenShift hosted control plane source repo",
            "limit": 5,
        },
    )
    lanes = {row["lane"]: row for row in response["lane_results"]}
    repo_lane = lanes[SOURCE_LANE_OFFICIAL_SOURCE_REPO]

    assert response["totals"]["github_repositories"] == 1
    assert repo_lane["count"] == 1
    assert repo_lane["filtered_count"] == 1
    assert repo_lane["items"][0]["full_name"] == "openshift/openshift-docs"
    assert repo_lane["items"][0]["source_trust_label"] == "official_org"
    assert "비공식/데모 repo 1건" in repo_lane["message"]


class _GithubResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "items": [
                {
                    "id": 10,
                    "number": 7,
                    "title": "CrashLoopBackOff known issue",
                    "html_url": "https://github.com/openshift/origin/issues/7",
                    "state": "open",
                    "repository_url": "https://api.github.com/repos/openshift/origin",
                    "user": {"login": "maintainer"},
                    "labels": [{"name": "bug"}],
                    "comments": 3,
                    "updated_at": "2026-05-12T00:00:00Z",
                    "created_at": "2026-05-11T00:00:00Z",
                    "score": 12.5,
                },
                {
                    "id": 11,
                    "number": 8,
                    "title": "Fix operator rollout",
                    "html_url": "https://github.com/openshift/origin/pull/8",
                    "state": "closed",
                    "repository_url": "https://api.github.com/repos/openshift/origin",
                    "user": {"login": "maintainer"},
                    "labels": [],
                    "comments": 1,
                    "pull_request": {"url": "https://api.github.com/repos/openshift/origin/pulls/8"},
                    "updated_at": "2026-05-12T01:00:00Z",
                    "created_at": "2026-05-11T01:00:00Z",
                    "score": 8.0,
                },
            ]
        }


def test_github_issues_prs_provider_normalizes_issue_and_pr(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, *, headers: dict[str, str], params: dict[str, object], timeout: int) -> _GithubResponse:
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _GithubResponse()

    monkeypatch.setattr(repository_registry.requests, "get", fake_get)

    response = repository_registry.search_github_issues_prs(
        tmp_path,
        query="CrashLoopBackOff 복구",
        limit=2,
        official_scope=True,
    )

    assert captured["url"] == "https://api.github.com/search/issues"
    assert "org:openshift" in str(captured["params"]["q"])
    assert response["auth_mode"] == "public"
    assert response["count"] == 2
    assert response["results"][0]["repository_full_name"] == "openshift/origin"
    assert response["results"][0]["kind"] == "issue"
    assert response["results"][1]["kind"] == "pull_request"


def test_verification_record_for_community_is_bronze_and_not_citation_eligible() -> None:
    record = build_verification_record(
        {
            "lane": SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
            "provider": "external_search_pending",
            "query": "OpenShift CrashLoopBackOff troubleshooting",
            "source_request_query": "CrashLoopBackOff 원인",
            "candidate": {
                "title": "Community CrashLoopBackOff fix",
                "html_url": "https://example.com/crashloopbackoff",
                "kind": "blog",
            },
        }
    )

    payload = record.to_dict()

    assert payload["grade"] == "bronze"
    assert payload["verification_status"] == "needs_verification"
    assert payload["gold_policy"] == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert payload["citation_eligible"] is False
    assert payload["can_promote_to_gold"] is False
    assert "official_cross_check_missing" in payload["promotion_blockers"]
    assert any(check["id"] == "korean_normalization" for check in payload["required_checks"])


def test_verification_record_for_unsafe_is_not_gold_eligible() -> None:
    record = build_verification_record(
        {
            "lane": SOURCE_LANE_UNSAFE_UNVERIFIED,
            "provider": "manual_review",
            "query": "random fix script",
            "candidate": {"title": "Unknown script"},
        }
    )

    payload = record.to_dict()

    assert payload["gold_policy"] == GOLD_NOT_ELIGIBLE
    assert "not_gold_eligible" in payload["promotion_blockers"]
    assert payload["citation_eligible"] is False


@pytest.mark.parametrize(
    ("lane", "provider"),
    [
        (SOURCE_LANE_OFFICIAL_ISSUE_PR, "github_issues_prs"),
        (SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, "external_search_pending"),
        (SOURCE_LANE_VENDOR_KB, "external_search_pending"),
        (SOURCE_LANE_UNSAFE_UNVERIFIED, "manual_review"),
    ],
)
def test_verification_queue_accepts_review_required_lanes(tmp_path, lane: str, provider: str) -> None:
    response = save_verification_candidate(
        tmp_path,
        {
            "lane": lane,
            "provider": provider,
            "query": "OpenShift CrashLoopBackOff",
            "candidate": {
                "title": f"{lane} candidate",
                "html_url": f"https://example.com/{lane}",
                "kind": "issue",
            },
        },
    )

    item = response["item"]

    assert response["saved"] is True
    assert item["grade"] == "bronze"
    assert item["verification_status"] == "needs_verification"
    assert item["citation_eligible"] is False
    assert item["can_promote_to_gold"] is False
    assert item["requires_human_review"] is True


def test_verification_queue_save_deduplicates_candidates(tmp_path) -> None:
    request_payload = {
        "lane": SOURCE_LANE_OFFICIAL_ISSUE_PR,
        "provider": "github_issues_prs",
        "query": "OpenShift CrashLoopBackOff",
        "candidate": {
            "title": "CrashLoopBackOff known issue",
            "html_url": "https://github.com/openshift/origin/issues/7",
            "repository_full_name": "openshift/origin",
            "number": 7,
            "kind": "issue",
        },
    }

    first = save_verification_candidate(tmp_path, request_payload)
    second = save_verification_candidate(tmp_path, request_payload)
    queue = list_verification_queue(tmp_path)

    assert first["saved"] is True
    assert second["saved"] is False
    assert second["deduplicated"] is True
    assert queue["count"] == 1
    assert queue["items"][0]["grade"] == "bronze"
    assert queue["items"][0]["source_ref"] == "openshift/origin#7"


def test_verification_queue_rejects_authoritative_lane(tmp_path) -> None:
    with pytest.raises(ValueError):
        save_verification_candidate(
            tmp_path,
            {
                "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                "provider": "official_catalog",
                "query": "official docs",
                "candidate": {"title": "Official docs"},
            },
        )
    with pytest.raises(ValueError):
        save_verification_candidate(
            tmp_path,
            {
                "lane": SOURCE_LANE_OFFICIAL_SOURCE_REPO,
                "provider": "github_repositories",
                "query": "official source",
                "candidate": {"title": "Official source repo"},
            },
        )


def test_verification_record_rehardens_persisted_review_gate() -> None:
    restored = SourceDiscoveryVerificationRecord.from_dict(
        {
            "schema": "source_discovery_verification_queue_v1",
            "candidate_id": "unsafe-row",
            "lane": SOURCE_LANE_VENDOR_KB,
            "provider": "external_search_pending",
            "title": "Bad persisted row",
            "query": "OpenShift support",
            "grade": "gold",
            "verification_status": "approved",
            "gold_policy": GOLD_ALLOWED_AFTER_VALIDATION,
            "citation_eligible": True,
            "can_promote_to_gold": True,
            "requires_human_review": False,
        }
    ).to_dict()

    assert restored["grade"] == "bronze"
    assert restored["verification_status"] == "needs_verification"
    assert restored["gold_policy"] == GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    assert restored["citation_eligible"] is False
    assert restored["can_promote_to_gold"] is False
    assert restored["requires_human_review"] is True
    assert "official_cross_check_missing" in restored["promotion_blockers"]


def test_verification_queue_rejects_non_object_candidate(tmp_path) -> None:
    with pytest.raises(ValueError, match="candidate"):
        save_verification_candidate(
            tmp_path,
            {
                "lane": SOURCE_LANE_VENDOR_KB,
                "provider": "external_search_pending",
                "query": "OpenShift support",
                "candidate": ["not", "an", "object"],
            },
        )


def test_verification_save_handler_returns_created(tmp_path) -> None:
    handler = _CaptureHandler()

    handle_repository_source_discovery_verification_save(
        handler,
        {
            "lane": SOURCE_LANE_VENDOR_KB,
            "provider": "external_search_pending",
            "query": "OpenShift CrashLoopBackOff Red Hat solution",
            "candidate": {
                "title": "Red Hat solution needed",
                "html_url": "https://access.redhat.com/solutions/example",
            },
        },
        root_dir=tmp_path,
    )

    assert handler.status == HTTPStatus.CREATED
    assert handler.payload["saved"] is True
    assert handler.payload["item"]["grade"] == "bronze"


def test_source_discovery_judge_passes_official_citation_cross_check() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "router certificate rotation",
            "before_answer": "근거가 부족합니다.",
            "after_answer": "공식 문서 기준으로 router certificate rotation 절차를 확인했습니다 [1].",
            "citations": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                    "title": "OpenShift router certificate docs",
                    "citation_eligible": True,
                }
            ],
            "source_candidates": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_SOURCE_REPO,
                    "title": "openshift/router source",
                    "trust_level": "authoritative",
                }
            ],
        }
    )

    assert report["schema"] == SOURCE_DISCOVERY_JUDGE_SCHEMA
    assert report["overall_verdict"] == "pass"
    assert report["pass_fail"] == "pass"
    assert report["source_trust"]["official_cross_check"] is True
    assert report["citation_coverage"]["official_citation_count"] == 1
    assert report["remaining_gap"] == []
    assert report["next_actions"] == [
        {
            "action_id": "record_answerable_case",
            "label": "답변 가능 케이스로 기록",
            "description": "공식 근거와 RAG 재답변이 통과했으므로 같은 질문 유형을 Gold/운영 위키 개선 후보로 남깁니다.",
            "severity": "info",
            "query": "router certificate rotation",
        }
    ]


def test_source_discovery_judge_treats_official_runtime_boundary_as_authoritative() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "hosted control plane",
            "before_answer": "답변 실패",
            "after_answer": "공식 런타임 문서 기준으로 답했습니다 [1].",
            "citations": [
                {
                    "boundary_truth": "official_validated_runtime",
                    "runtime_truth_label": "Official Runtime",
                    "book_title": "Hosted control planes",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "pass"
    assert report["source_trust"]["official_cross_check"] is True
    assert report["citation_coverage"]["official_citation_count"] == 1


def test_source_discovery_judge_treats_gold_playbook_citation_as_authoritative() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "hosted control plane",
            "before_answer": "답변 실패",
            "after_answer": "Gold Playbook 기준으로 답했습니다 [1].",
            "citations": [
                {
                    "source_lane": "official_ko",
                    "boundary_truth": "official_gold_playbook_runtime",
                    "runtime_truth_label": "OpenShift 4.20 Gold Playbook",
                    "book_title": "아키텍처",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "pass"
    assert report["source_trust"]["official_cross_check"] is True
    assert report["citation_coverage"]["official_citation_count"] == 1


def test_source_discovery_judge_flags_community_only_risk() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "CrashLoopBackOff 복구",
            "before_answer": "답변 실패",
            "after_answer": "커뮤니티 사례를 찾았지만 공식 교차검증은 아직 필요합니다.",
            "source_candidates": [
                {
                    "lane": SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
                    "title": "Community CrashLoopBackOff fix",
                    "citation_eligible": False,
                    "gold_policy": GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
                }
            ],
        }
    )

    assert report["overall_verdict"] == "needs_review"
    assert report["pass_fail"] == "pending"
    assert report["source_trust"]["community_only_risk"] is True
    assert "official_cross_check_missing" in report["remaining_gap"]
    assert "community_only_risk" in report["remaining_gap"]
    assert {action["action_id"] for action in report["next_actions"]} >= {
        "search_official_manual",
        "search_official_source_repo",
        "verify_bronze_queue",
    }
    assert any(action.get("lane") == SOURCE_LANE_OFFICIAL_MANUAL for action in report["next_actions"])


def test_source_discovery_judge_fails_when_non_eligible_source_is_cited_with_official_citation() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "CrashLoopBackOff 복구",
            "before_answer": "답변 실패",
            "after_answer": "공식 문서와 커뮤니티 글을 함께 인용했습니다 [1] [2].",
            "citations": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                    "title": "Official troubleshooting docs",
                    "citation_eligible": True,
                },
                {
                    "lane": SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
                    "title": "Community-only fix",
                    "citation_eligible": False,
                },
            ],
        }
    )

    assert report["overall_verdict"] == "fail"
    assert report["pass_fail"] == "fail"
    assert report["source_trust"]["verdict"] == "fail"
    assert "non_eligible_source_cited" in report["remaining_gap"]
    assert any(action["action_id"] == "replace_non_eligible_citations" for action in report["next_actions"])


def test_source_discovery_judge_does_not_treat_official_issue_pr_as_authoritative() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "CrashLoopBackOff known bug",
            "before_answer": "답변 실패",
            "after_answer": "공식 Issue를 근거로 보류 판단했습니다 [1].",
            "citations": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_ISSUE_PR,
                    "title": "Official issue",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "fail"
    assert report["source_trust"]["official_cross_check"] is False
    assert "non_eligible_source_cited" in report["remaining_gap"]


def test_source_discovery_judge_does_not_allow_authoritative_trust_override_for_review_lanes() -> None:
    for lane in (SOURCE_LANE_OFFICIAL_ISSUE_PR, SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, SOURCE_LANE_VENDOR_KB):
        report = build_source_discovery_judge_report(
            {
                "question": f"{lane} citation",
                "before_answer": "답변 실패",
                "after_answer": "검토 필요 근거를 인용했습니다 [1].",
                "citations": [
                    {
                        "lane": lane,
                        "title": "Review required source",
                        "trust_level": "authoritative",
                    }
                ],
            }
        )

        assert report["overall_verdict"] == "fail"
        assert report["source_trust"]["official_cross_check"] is False
        assert "non_eligible_source_cited" in report["remaining_gap"]
        assert any(action["action_id"] == "replace_non_eligible_citations" for action in report["next_actions"])


def test_source_discovery_judge_does_not_treat_candidate_runtime_as_authoritative() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "candidate runtime docs",
            "before_answer": "답변 실패",
            "after_answer": "후보 runtime 문서만 인용했습니다 [1].",
            "citations": [
                {
                    "boundary_truth": "official_candidate_runtime",
                    "runtime_truth_label": "Official Candidate Runtime",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "fail"
    assert report["source_trust"]["official_cross_check"] is False
    assert "non_eligible_source_cited" in report["remaining_gap"]


def test_source_discovery_judge_does_not_allow_authoritative_trust_override_for_candidate_runtime() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "candidate runtime docs",
            "before_answer": "답변 실패",
            "after_answer": "후보 runtime 문서에 authoritative 표시가 붙었습니다 [1].",
            "citations": [
                {
                    "boundary_truth": "official_candidate_runtime",
                    "runtime_truth_label": "Official Candidate Runtime",
                    "trust_level": "authoritative",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "fail"
    assert report["source_trust"]["official_cross_check"] is False
    assert "non_eligible_source_cited" in report["remaining_gap"]


def test_source_discovery_judge_requires_answer_replay_before_pass() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "etcd quorum lost",
            "before_answer": "답변 실패",
            "after_answer": "",
            "citations": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                    "title": "Official etcd docs",
                    "citation_eligible": True,
                }
            ],
        }
    )

    assert report["overall_verdict"] == "needs_replay"
    assert report["pass_fail"] == "pending"
    assert "after_answer_replay_required" in report["remaining_gap"]
    assert any(action["action_id"] == "rerun_rag_replay" for action in report["next_actions"])


def test_source_discovery_judge_recommends_removing_unsafe_citations() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "random fix script",
            "before_answer": "답변 실패",
            "after_answer": "출처 불명 스크립트를 인용했습니다 [1].",
            "citations": [
                {
                    "lane": SOURCE_LANE_UNSAFE_UNVERIFIED,
                    "title": "Unknown script",
                }
            ],
        }
    )

    assert report["overall_verdict"] == "fail"
    assert "unsafe_source_cited" in report["remaining_gap"]
    assert any(action["action_id"] == "remove_unsafe_citation" for action in report["next_actions"])


def test_source_discovery_judge_persists_latest_report(tmp_path) -> None:
    first = save_source_discovery_judge_report(
        tmp_path,
        {
            "question": "first question",
            "before_answer": "답변 실패",
            "after_answer": "공식 문서로 보강했습니다 [1].",
            "citations": [{"lane": SOURCE_LANE_OFFICIAL_MANUAL, "title": "Official docs"}],
        },
    )
    second = save_source_discovery_judge_report(
        tmp_path,
        {
            "question": "second question",
            "before_answer": "답변 실패",
            "after_answer": "공식 문서로 다시 보강했습니다 [1].",
            "citations": [{"lane": SOURCE_LANE_OFFICIAL_MANUAL, "title": "Official docs"}],
        },
    )

    listing = list_source_discovery_judge_reports(tmp_path, limit=1)

    assert first["path"] == second["path"]
    assert listing["schema"] == SOURCE_DISCOVERY_JUDGE_SCHEMA
    assert listing["count"] == 1
    assert listing["items"][0]["question"] == "second question"


def test_source_discovery_judge_handler_includes_verification_queue(tmp_path) -> None:
    save_verification_candidate(
        tmp_path,
        {
            "lane": SOURCE_LANE_VENDOR_KB,
            "provider": "external_search_pending",
            "query": "OpenShift support solution",
            "candidate": {
                "title": "Vendor solution",
                "html_url": "https://access.redhat.com/solutions/example",
            },
        },
    )
    handler = _CaptureHandler()

    handle_repository_source_discovery_judge_save(
        handler,
        {
            "question": "OpenShift support solution",
            "before_answer": "답변 실패",
            "after_answer": "공식 교차검증 전까지는 보류합니다.",
            "source_candidates": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                    "title": "Official support docs",
                    "trust_level": "authoritative",
                }
            ],
        },
        root_dir=tmp_path,
    )

    assert handler.status == HTTPStatus.CREATED
    assert handler.payload["schema"] == SOURCE_DISCOVERY_JUDGE_SCHEMA
    assert handler.payload["source_trust"]["official_cross_check"] is True
    assert handler.payload["source_trust"]["needs_verification_count"] == 1
    assert "review_required_sources_pending" in handler.payload["remaining_gap"]


def test_source_discovery_judge_does_not_trust_client_cross_check_without_evidence() -> None:
    report = build_source_discovery_judge_report(
        {
            "question": "CrashLoopBackOff 복구",
            "before_answer": "답변 실패",
            "after_answer": "커뮤니티 사례만 확인했습니다.",
            "official_cross_check": True,
            "source_candidates": [
                {
                    "lane": SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
                    "title": "Community-only fix",
                    "citation_eligible": False,
                }
            ],
        }
    )

    assert report["source_trust"]["claimed_official_cross_check"] is True
    assert report["source_trust"]["official_cross_check"] is False
    assert report["source_trust"]["community_only_risk"] is True
    assert "official_cross_check_unproven" in report["remaining_gap"]


def test_source_discovery_judge_handler_does_not_mix_unrelated_queue(tmp_path) -> None:
    save_verification_candidate(
        tmp_path,
        {
            "lane": SOURCE_LANE_VENDOR_KB,
            "provider": "external_search_pending",
            "query": "unrelated support question",
            "source_request_query": "unrelated support question",
            "candidate": {
                "title": "Unrelated vendor solution",
                "html_url": "https://access.redhat.com/solutions/unrelated",
            },
        },
    )
    handler = _CaptureHandler()

    handle_repository_source_discovery_judge_save(
        handler,
        {
            "question": "router certificate rotation",
            "before_answer": "답변 실패",
            "after_answer": "공식 문서로 보강했습니다 [1].",
            "citations": [{"lane": SOURCE_LANE_OFFICIAL_MANUAL, "title": "Official docs"}],
        },
        root_dir=tmp_path,
    )

    assert handler.status == HTTPStatus.CREATED
    assert handler.payload["source_trust"]["needs_verification_count"] == 0
    assert "review_required_sources_pending" not in handler.payload["remaining_gap"]


def test_source_discovery_judge_handler_deduplicates_payload_and_queue(tmp_path) -> None:
    saved = save_verification_candidate(
        tmp_path,
        {
            "lane": SOURCE_LANE_VENDOR_KB,
            "provider": "external_search_pending",
            "query": "router certificate rotation",
            "source_request_query": "router certificate rotation",
            "candidate": {
                "title": "Vendor router certificate note",
                "html_url": "https://access.redhat.com/solutions/router-certificate",
            },
        },
    )
    handler = _CaptureHandler()

    handle_repository_source_discovery_judge_save(
        handler,
        {
            "question": "router certificate rotation",
            "before_answer": "답변 실패",
            "after_answer": "공식 교차검증 전까지 벤더 KB는 보류합니다.",
            "verification_records": [saved["item"]],
            "source_candidates": [
                {
                    "lane": SOURCE_LANE_OFFICIAL_MANUAL,
                    "title": "Official router certificate docs",
                }
            ],
        },
        root_dir=tmp_path,
    )

    assert handler.status == HTTPStatus.CREATED
    assert handler.payload["source_trust"]["needs_verification_count"] == 1
    assert len(handler.payload["evidence"]["verification_records"]) == 1


class _FakeReplaySettings:
    ocp_version = "4.20"


class _FakeReplayAnswerer:
    settings = _FakeReplaySettings()

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def answer(self, query: str, **kwargs: object) -> AnswerResult:
        self.calls.append({"query": query, **kwargs})
        return AnswerResult(
            query=query,
            mode=str(kwargs.get("mode") or "chat"),
            answer="공식 문서 기준으로 재답변했습니다 [1].",
            rewritten_query=query,
            citations=[
                Citation(
                    index=1,
                    chunk_id="chunk-1",
                    book_slug="hosted_control_planes",
                    section="Overview",
                    anchor="overview",
                    source_url="https://docs.redhat.com/openshift/hosted-control-planes",
                    viewer_path="/docs/ocp/4.20/hosted_control_planes/index.html",
                    excerpt="Hosted control planes official excerpt",
                )
            ],
            cited_indices=[1],
        )


def test_source_discovery_judge_replay_handler_runs_answerer_and_saves_judge_report(tmp_path) -> None:
    handler = _CaptureHandler()
    answerer = _FakeReplayAnswerer()

    def fake_build_chat_payload(**kwargs: object) -> dict[str, object]:
        result = kwargs["result"]
        assert isinstance(result, AnswerResult)
        return {
            "session_id": "source-judge-replay-test",
            "answer": result.answer,
            "response_kind": result.response_kind,
            "warnings": [],
            "citations": [
                {
                    **citation.to_dict(),
                    "boundary_truth": "official_validated_runtime",
                    "runtime_truth_label": "Official Runtime",
                }
                for citation in result.citations
            ],
            "suggested_queries": [],
            "related_links": [],
            "related_sections": [],
        }

    handle_repository_source_discovery_judge_replay(
        handler,
        {
            "question": "hosted control plane 설명",
            "before_answer": "답변 실패",
            "include_verification_queue": False,
        },
        root_dir=tmp_path,
        current_answerer=lambda: answerer,
        context_with_request_overrides=lambda context, **_: context,
        build_chat_payload=fake_build_chat_payload,
        owner_user_id="tester",
    )

    assert handler.status == HTTPStatus.CREATED
    assert handler.payload["schema"] == "source_discovery_judge_replay_v1"
    assert handler.payload["replay"]["answer"] == "공식 문서 기준으로 재답변했습니다 [1]."
    assert handler.payload["judge_report"]["after_answer"] == "공식 문서 기준으로 재답변했습니다 [1]."
    assert handler.payload["judge_report"]["overall_verdict"] == "pass"
    assert handler.payload["judge_report"]["source_trust"]["official_cross_check"] is True
    assert answerer.calls[0]["query"] == "hosted control plane 설명"
