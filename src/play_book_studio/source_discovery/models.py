from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast


SOURCE_DISCOVERY_PLAN_SCHEMA = "source_discovery_plan_v1"

SOURCE_LANE_OFFICIAL_MANUAL = "official_manual"
SOURCE_LANE_OFFICIAL_SOURCE_REPO = "official_source_repo"
SOURCE_LANE_OFFICIAL_ISSUE_PR = "official_issue_pr"
SOURCE_LANE_COMMUNITY_TROUBLESHOOTING = "community_troubleshooting"
SOURCE_LANE_VENDOR_KB = "vendor_kb"
SOURCE_LANE_UNSAFE_UNVERIFIED = "unsafe_unverified"

SourceLane = Literal[
    "official_manual",
    "official_source_repo",
    "official_issue_pr",
    "community_troubleshooting",
    "vendor_kb",
    "unsafe_unverified",
]

NEED_OFFICIAL_MANUAL_GAP = "official_manual_gap"
NEED_SOURCE_CODE_REFERENCE = "source_code_or_config_reference"
NEED_KNOWN_ISSUE = "known_issue_or_bug"
NEED_COMMUNITY_TROUBLESHOOTING = "community_troubleshooting"
NEED_VENDOR_KB = "vendor_kb"
NEED_UNKNOWN = "unknown"

NeedType = Literal[
    "official_manual_gap",
    "source_code_or_config_reference",
    "known_issue_or_bug",
    "community_troubleshooting",
    "vendor_kb",
    "unknown",
]

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

RiskLevel = Literal["low", "medium", "high"]

GOLD_ALLOWED_AFTER_VALIDATION = "gold_allowed_after_validation"
GOLD_REQUIRES_OFFICIAL_CROSS_CHECK = "requires_official_cross_check"
GOLD_BRONZE_ONLY = "bronze_only"
GOLD_NOT_ELIGIBLE = "not_gold_eligible"

GoldPolicy = Literal[
    "gold_allowed_after_validation",
    "requires_official_cross_check",
    "bronze_only",
    "not_gold_eligible",
]

SUPPORTED_SOURCE_LANES: tuple[SourceLane, ...] = (
    SOURCE_LANE_OFFICIAL_MANUAL,
    SOURCE_LANE_OFFICIAL_SOURCE_REPO,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_VENDOR_KB,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
)

SUPPORTED_NEED_TYPES: tuple[NeedType, ...] = (
    NEED_OFFICIAL_MANUAL_GAP,
    NEED_SOURCE_CODE_REFERENCE,
    NEED_KNOWN_ISSUE,
    NEED_COMMUNITY_TROUBLESHOOTING,
    NEED_VENDOR_KB,
    NEED_UNKNOWN,
)

SUPPORTED_RISK_LEVELS: tuple[RiskLevel, ...] = (RISK_LOW, RISK_MEDIUM, RISK_HIGH)

SUPPORTED_GOLD_POLICIES: tuple[GoldPolicy, ...] = (
    GOLD_ALLOWED_AFTER_VALIDATION,
    GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
    GOLD_BRONZE_ONLY,
    GOLD_NOT_ELIGIBLE,
)

REVIEW_REQUIRED_LANES = frozenset(
    {
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
        SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
        SOURCE_LANE_VENDOR_KB,
        SOURCE_LANE_UNSAFE_UNVERIFIED,
    }
)
NON_GOLD_DIRECT_LANES = frozenset(
    {
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
        SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
        SOURCE_LANE_VENDOR_KB,
        SOURCE_LANE_UNSAFE_UNVERIFIED,
    }
)

_RISK_RANK: dict[RiskLevel, int] = {
    RISK_LOW: 0,
    RISK_MEDIUM: 1,
    RISK_HIGH: 2,
}

_LANE_POLICIES: dict[SourceLane, dict[str, object]] = {
    SOURCE_LANE_OFFICIAL_MANUAL: {
        "label": "Official manual",
        "trust_level": "authoritative",
        "default_gold_policy": GOLD_ALLOWED_AFTER_VALIDATION,
        "requires_human_review": False,
    },
    SOURCE_LANE_OFFICIAL_SOURCE_REPO: {
        "label": "Official source repository",
        "trust_level": "authoritative",
        "default_gold_policy": GOLD_ALLOWED_AFTER_VALIDATION,
        "requires_human_review": False,
    },
    SOURCE_LANE_OFFICIAL_ISSUE_PR: {
        "label": "Official issue or pull request",
        "trust_level": "official-but-unstable",
        "default_gold_policy": GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
        "requires_human_review": True,
    },
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING: {
        "label": "Community troubleshooting",
        "trust_level": "community",
        "default_gold_policy": GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
        "requires_human_review": True,
    },
    SOURCE_LANE_VENDOR_KB: {
        "label": "Vendor knowledge base",
        "trust_level": "vendor",
        "default_gold_policy": GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
        "requires_human_review": True,
    },
    SOURCE_LANE_UNSAFE_UNVERIFIED: {
        "label": "Unsafe or unverified",
        "trust_level": "untrusted",
        "default_gold_policy": GOLD_NOT_ELIGIBLE,
        "requires_human_review": True,
    },
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _unique_clean(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values: tuple[Any, ...] = (values,)
    else:
        try:
            raw_values = tuple(values)
        except TypeError:
            raw_values = (values,)

    seen: set[str] = set()
    cleaned: list[str] = []
    for value in raw_values:
        item = _clean_text(value)
        if item and item not in seen:
            seen.add(item)
            cleaned.append(item)
    return tuple(cleaned)


def _validate_choice(value: str, supported: tuple[str, ...], field_name: str) -> str:
    if value not in supported:
        supported_label = ", ".join(supported)
        raise ValueError(f"{field_name} must be one of: {supported_label}")
    return value


def _normalize_lane(value: Any) -> SourceLane:
    return cast(SourceLane, _validate_choice(_clean_text(value), cast(tuple[str, ...], SUPPORTED_SOURCE_LANES), "lane"))


def _normalize_need_type(value: Any) -> NeedType:
    cleaned = _clean_text(value) or NEED_UNKNOWN
    return cast(NeedType, _validate_choice(cleaned, cast(tuple[str, ...], SUPPORTED_NEED_TYPES), "need_type"))


def _normalize_risk(value: Any) -> RiskLevel:
    cleaned = _clean_text(value) or RISK_LOW
    return cast(RiskLevel, _validate_choice(cleaned, cast(tuple[str, ...], SUPPORTED_RISK_LEVELS), "risk_level"))


def _normalize_gold_policy(value: Any) -> GoldPolicy:
    cleaned = _clean_text(value) or GOLD_ALLOWED_AFTER_VALIDATION
    return cast(GoldPolicy, _validate_choice(cleaned, cast(tuple[str, ...], SUPPORTED_GOLD_POLICIES), "gold_policy"))


def _max_risk(current: RiskLevel, minimum: RiskLevel) -> RiskLevel:
    if _RISK_RANK[current] >= _RISK_RANK[minimum]:
        return current
    return minimum


def _policy_for_lanes(
    lanes: tuple[SourceLane, ...],
    requested_policy: GoldPolicy,
    requested_risk: RiskLevel,
    requested_review: bool,
) -> tuple[GoldPolicy, RiskLevel, bool]:
    lane_set = set(lanes)
    policy = requested_policy
    risk = requested_risk
    requires_review = requested_review or bool(lane_set & REVIEW_REQUIRED_LANES)

    if SOURCE_LANE_UNSAFE_UNVERIFIED in lane_set:
        return GOLD_NOT_ELIGIBLE, RISK_HIGH, True

    if lane_set & NON_GOLD_DIRECT_LANES:
        if policy == GOLD_ALLOWED_AFTER_VALIDATION:
            policy = GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
        risk = _max_risk(risk, RISK_MEDIUM)

    return policy, risk, requires_review


def source_lane_policy(lane: str) -> dict[str, object]:
    normalized = _normalize_lane(lane)
    policy = dict(_LANE_POLICIES[normalized])
    policy["lane"] = normalized
    return policy


@dataclass(frozen=True, slots=True)
class SourceDiscoverySearchQuery:
    query: str
    lane: SourceLane
    purpose: str = ""
    expected_evidence: str = ""

    def __post_init__(self) -> None:
        query = _clean_text(self.query)
        if not query:
            raise ValueError("search query is required")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "lane", _normalize_lane(self.lane))
        object.__setattr__(self, "purpose", _clean_text(self.purpose))
        object.__setattr__(self, "expected_evidence", _clean_text(self.expected_evidence))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceDiscoverySearchQuery:
        if not isinstance(payload, dict):
            raise TypeError("search query payload must be a dict")
        return cls(
            query=str(payload.get("query") or ""),
            lane=cast(SourceLane, payload.get("lane") or SOURCE_LANE_OFFICIAL_MANUAL),
            purpose=str(payload.get("purpose") or ""),
            expected_evidence=str(payload.get("expected_evidence") or ""),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "lane": self.lane,
            "purpose": self.purpose,
            "expected_evidence": self.expected_evidence,
        }


@dataclass(frozen=True, slots=True)
class SourceDiscoveryPlan:
    question: str
    search_queries: tuple[SourceDiscoverySearchQuery, ...]
    source_request_id: str = ""
    failed_answer: str = ""
    response_kind: str = ""
    need_type: NeedType = NEED_UNKNOWN
    reason: str = ""
    allowed_lanes: tuple[SourceLane, ...] = (SOURCE_LANE_OFFICIAL_MANUAL,)
    risk_level: RiskLevel = RISK_LOW
    gold_policy: GoldPolicy = GOLD_ALLOWED_AFTER_VALIDATION
    requires_human_review: bool = False
    evidence: tuple[str, ...] = ()
    schema: str = SOURCE_DISCOVERY_PLAN_SCHEMA

    def __post_init__(self) -> None:
        schema = _clean_text(self.schema) or SOURCE_DISCOVERY_PLAN_SCHEMA
        if schema != SOURCE_DISCOVERY_PLAN_SCHEMA:
            raise ValueError(f"unsupported source discovery schema: {schema}")
        object.__setattr__(self, "schema", schema)

        question = _clean_text(self.question)
        if not question:
            raise ValueError("question is required")
        object.__setattr__(self, "question", question)
        object.__setattr__(self, "source_request_id", _clean_text(self.source_request_id))
        object.__setattr__(self, "failed_answer", _clean_text(self.failed_answer))
        object.__setattr__(self, "response_kind", _clean_text(self.response_kind))
        object.__setattr__(self, "need_type", _normalize_need_type(self.need_type))
        object.__setattr__(self, "reason", _clean_text(self.reason))
        object.__setattr__(self, "evidence", _unique_clean(self.evidence))

        normalized_queries: list[SourceDiscoverySearchQuery] = []
        seen_queries: set[tuple[str, SourceLane]] = set()
        for item in self.search_queries:
            query = item if isinstance(item, SourceDiscoverySearchQuery) else SourceDiscoverySearchQuery.from_dict(cast(dict[str, Any], item))
            query_key = (query.query.casefold(), query.lane)
            if query_key in seen_queries:
                continue
            seen_queries.add(query_key)
            normalized_queries.append(query)
        if not normalized_queries:
            raise ValueError("at least one search query is required")
        object.__setattr__(self, "search_queries", tuple(normalized_queries))

        lanes_from_payload = tuple(_normalize_lane(lane) for lane in self.allowed_lanes)
        lanes_from_queries = tuple(query.lane for query in normalized_queries)
        allowed_lanes = cast(tuple[SourceLane, ...], _unique_clean((*lanes_from_payload, *lanes_from_queries)))
        object.__setattr__(self, "allowed_lanes", allowed_lanes)

        requested_policy = _normalize_gold_policy(self.gold_policy)
        requested_risk = _normalize_risk(self.risk_level)
        policy, risk, requires_review = _policy_for_lanes(
            allowed_lanes,
            requested_policy,
            requested_risk,
            bool(self.requires_human_review),
        )
        object.__setattr__(self, "gold_policy", policy)
        object.__setattr__(self, "risk_level", risk)
        object.__setattr__(self, "requires_human_review", requires_review)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceDiscoveryPlan:
        if not isinstance(payload, dict):
            raise TypeError("source discovery plan payload must be a dict")
        queries_payload = payload.get("search_queries") or []
        queries = tuple(
            item if isinstance(item, SourceDiscoverySearchQuery) else SourceDiscoverySearchQuery.from_dict(cast(dict[str, Any], item))
            for item in queries_payload
        )
        return cls(
            schema=str(payload.get("schema") or SOURCE_DISCOVERY_PLAN_SCHEMA),
            source_request_id=str(payload.get("source_request_id") or ""),
            question=str(payload.get("question") or ""),
            failed_answer=str(payload.get("failed_answer") or ""),
            response_kind=str(payload.get("response_kind") or ""),
            need_type=cast(NeedType, payload.get("need_type") or NEED_UNKNOWN),
            reason=str(payload.get("reason") or ""),
            allowed_lanes=cast(tuple[SourceLane, ...], tuple(payload.get("allowed_lanes") or ())),
            search_queries=queries,
            risk_level=cast(RiskLevel, payload.get("risk_level") or RISK_LOW),
            gold_policy=cast(GoldPolicy, payload.get("gold_policy") or GOLD_ALLOWED_AFTER_VALIDATION),
            requires_human_review=bool(payload.get("requires_human_review", False)),
            evidence=tuple(str(item) for item in (payload.get("evidence") or ())),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_request_id": self.source_request_id,
            "question": self.question,
            "failed_answer": self.failed_answer,
            "response_kind": self.response_kind,
            "need_type": self.need_type,
            "reason": self.reason,
            "allowed_lanes": list(self.allowed_lanes),
            "search_queries": [query.to_dict() for query in self.search_queries],
            "risk_level": self.risk_level,
            "gold_policy": self.gold_policy,
            "requires_human_review": self.requires_human_review,
            "evidence": list(self.evidence),
            "lane_policies": [source_lane_policy(lane) for lane in self.allowed_lanes],
        }


def _default_purpose(lane: SourceLane) -> str:
    if lane == SOURCE_LANE_OFFICIAL_MANUAL:
        return "Find authoritative product documentation that can become a Gold candidate after translation and review."
    if lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
        return "Find implementation, configuration, or source-level evidence from an official repository."
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        return "Find upstream issue or pull request context for unstable behavior or known bugs."
    if lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
        return "Find community troubleshooting clues that must be cross-checked before promotion."
    if lane == SOURCE_LANE_VENDOR_KB:
        return "Find vendor troubleshooting notes that must be cross-checked before promotion."
    return "Collect unverified context for human review only."


def _default_evidence(lane: SourceLane) -> str:
    if lane == SOURCE_LANE_OFFICIAL_MANUAL:
        return "official document URL, product/version, section title"
    if lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
        return "repository, branch/tag, file path, commit or release reference"
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        return "repository, issue/PR number, status, maintainer signal"
    if lane == SOURCE_LANE_COMMUNITY_TROUBLESHOOTING:
        return "thread URL, environment, accepted answer or reproduced fix"
    if lane == SOURCE_LANE_VENDOR_KB:
        return "vendor article URL, affected version, publication/update date"
    return "source URL and explicit reason it cannot be trusted"


def _default_need_type(lanes: tuple[SourceLane, ...]) -> NeedType:
    if SOURCE_LANE_OFFICIAL_SOURCE_REPO in lanes:
        return NEED_SOURCE_CODE_REFERENCE
    if SOURCE_LANE_OFFICIAL_ISSUE_PR in lanes:
        return NEED_KNOWN_ISSUE
    if SOURCE_LANE_COMMUNITY_TROUBLESHOOTING in lanes:
        return NEED_COMMUNITY_TROUBLESHOOTING
    if SOURCE_LANE_VENDOR_KB in lanes:
        return NEED_VENDOR_KB
    if SOURCE_LANE_OFFICIAL_MANUAL in lanes:
        return NEED_OFFICIAL_MANUAL_GAP
    return NEED_UNKNOWN


def build_source_discovery_plan(
    *,
    question: str,
    failed_answer: str = "",
    response_kind: str = "",
    source_request_id: str = "",
    lanes: tuple[SourceLane, ...] | None = None,
    reason: str = "",
) -> SourceDiscoveryPlan:
    normalized_question = _clean_text(question)
    normalized_lanes = lanes or (
        SOURCE_LANE_OFFICIAL_MANUAL,
        SOURCE_LANE_OFFICIAL_SOURCE_REPO,
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
    )
    allowed_lanes = cast(tuple[SourceLane, ...], tuple(_normalize_lane(lane) for lane in normalized_lanes))
    queries = tuple(
        SourceDiscoverySearchQuery(
            query=normalized_question,
            lane=lane,
            purpose=_default_purpose(lane),
            expected_evidence=_default_evidence(lane),
        )
        for lane in allowed_lanes
    )
    return SourceDiscoveryPlan(
        source_request_id=source_request_id,
        question=normalized_question,
        failed_answer=failed_answer,
        response_kind=response_kind,
        need_type=_default_need_type(allowed_lanes),
        reason=reason or "The previous answer needs additional source evidence before it can be trusted.",
        allowed_lanes=allowed_lanes,
        search_queries=queries,
    )
