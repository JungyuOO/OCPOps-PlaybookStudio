from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.source_discovery.models import (
    GOLD_NOT_ELIGIBLE,
    GOLD_REQUIRES_OFFICIAL_CROSS_CHECK,
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
    SOURCE_LANE_VENDOR_KB,
    source_lane_policy,
)


SOURCE_DISCOVERY_VERIFICATION_SCHEMA = "source_discovery_verification_queue_v1"
VERIFICATION_STATUS_NEEDS_REVIEW = "needs_verification"
VERIFICATION_GRADE_BRONZE = "bronze"
REVIEW_REQUIRED_SOURCE_LANES = frozenset(
    {
        SOURCE_LANE_OFFICIAL_ISSUE_PR,
        SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
        SOURCE_LANE_VENDOR_KB,
        SOURCE_LANE_UNSAFE_UNVERIFIED,
    }
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _candidate_text(candidate: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_text(candidate.get(key))
        if value:
            return value
    return ""


def _candidate_source_url(candidate: dict[str, Any]) -> str:
    direct = _candidate_text(candidate, ("html_url", "source_url", "url", "href", "viewer_path"))
    if direct:
        return direct
    source_options = candidate.get("source_options")
    if isinstance(source_options, list):
        for option in source_options:
            if not isinstance(option, dict):
                continue
            href = _clean_text(option.get("href"))
            if href:
                return href
    return ""


def _candidate_title(candidate: dict[str, Any], *, lane: str, query: str) -> str:
    return (
        _candidate_text(candidate, ("title", "full_name", "book_slug", "name"))
        or query
        or str(source_lane_policy(lane).get("label") or lane)
    )


def _candidate_ref(candidate: dict[str, Any], *, source_url: str) -> str:
    repository = _candidate_text(candidate, ("repository_full_name", "full_name", "source_repo"))
    number = _candidate_text(candidate, ("number",))
    if repository and number:
        return f"{repository}#{number}"
    if repository:
        return repository
    return source_url


def _verification_queue_path(root_dir: Path) -> Path:
    return load_settings(root_dir).artifacts_dir / "source_discovery" / "verification_queue.jsonl"


def _candidate_id_payload(
    *,
    lane: str,
    provider: str,
    source_url: str,
    source_ref: str,
    title: str,
    query: str,
) -> dict[str, str]:
    return {
        "lane": lane,
        "provider": provider,
        "source_url": source_url,
        "source_ref": source_ref,
        "title": title,
        "query": query,
    }


def source_discovery_candidate_id(
    *,
    lane: str,
    provider: str,
    source_url: str,
    source_ref: str,
    title: str,
    query: str,
) -> str:
    payload = _candidate_id_payload(
        lane=lane,
        provider=provider,
        source_url=source_url,
        source_ref=source_ref,
        title=title,
        query=query,
    )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def required_verification_checks(lane: str) -> list[dict[str, str]]:
    if lane == SOURCE_LANE_UNSAFE_UNVERIFIED:
        return [
            {
                "id": "reject_or_reclassify",
                "label": "출처 검증 또는 폐기",
                "description": "출처가 확인되지 않으면 자동 승격하지 않고 폐기하거나 다른 lane으로 재분류합니다.",
            },
            {
                "id": "security_review",
                "label": "보안/운영 위험 검토",
                "description": "명령어, 스크립트, 설정 변경이 포함되면 운영 위험을 별도로 검토합니다.",
            },
        ]
    checks = [
        {
            "id": "official_cross_check",
            "label": "공식 근거 교차 검증",
            "description": "공식 문서, 공식 레포, 공식 issue/PR 중 하나 이상의 근거와 맞는지 확인합니다.",
        },
        {
            "id": "ocp_version_scope",
            "label": "OCP 버전 범위 확인",
            "description": "현재 대상 OCP 버전에 적용되는 내용인지 확인합니다.",
        },
        {
            "id": "korean_normalization",
            "label": "한글 요약/정규화",
            "description": "Library/Gold 후보로 쓰기 전에 한국어 설명과 근거 메타데이터를 정리합니다.",
        },
    ]
    if lane in {SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, SOURCE_LANE_VENDOR_KB}:
        checks.append(
            {
                "id": "reproduction_or_support_signal",
                "label": "재현 또는 지원 근거",
                "description": "로그, 환경 조건, accepted answer, 벤더 solution 등 재현 가능한 근거를 확인합니다.",
            }
        )
    if lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
        checks.append(
            {
                "id": "maintainer_signal",
                "label": "Maintainer signal",
                "description": "maintainer 답변, merge 여부, close 사유처럼 공식 프로젝트 신호를 확인합니다.",
            }
        )
    return checks


def promotion_blockers(lane: str) -> list[str]:
    if lane == SOURCE_LANE_UNSAFE_UNVERIFIED:
        return ["not_gold_eligible", "source_unverified", "security_review_required"]
    return [
        "official_cross_check_missing",
        "ocp_version_scope_unverified",
        "korean_normalization_missing",
        "human_review_required",
    ]


@dataclass(frozen=True, slots=True)
class SourceDiscoveryVerificationRecord:
    candidate_id: str
    lane: str
    provider: str
    title: str
    source_url: str
    source_ref: str
    query: str
    source_request_query: str = ""
    candidate_kind: str = ""
    trust_level: str = ""
    grade: str = VERIFICATION_GRADE_BRONZE
    verification_status: str = VERIFICATION_STATUS_NEEDS_REVIEW
    gold_policy: str = GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    citation_eligible: bool = False
    can_promote_to_gold: bool = False
    requires_human_review: bool = True
    required_checks: tuple[dict[str, str], ...] = field(default_factory=tuple)
    promotion_blockers: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""
    raw_candidate: dict[str, Any] = field(default_factory=dict)
    schema: str = SOURCE_DISCOVERY_VERIFICATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_id": self.candidate_id,
            "lane": self.lane,
            "provider": self.provider,
            "title": self.title,
            "source_url": self.source_url,
            "source_ref": self.source_ref,
            "query": self.query,
            "source_request_query": self.source_request_query,
            "candidate_kind": self.candidate_kind,
            "trust_level": self.trust_level,
            "grade": self.grade,
            "verification_status": self.verification_status,
            "gold_policy": self.gold_policy,
            "citation_eligible": self.citation_eligible,
            "can_promote_to_gold": self.can_promote_to_gold,
            "requires_human_review": self.requires_human_review,
            "required_checks": list(self.required_checks),
            "promotion_blockers": list(self.promotion_blockers),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "raw_candidate": dict(self.raw_candidate),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceDiscoveryVerificationRecord:
        lane = _clean_text(payload.get("lane"))
        is_review_required_lane = lane in REVIEW_REQUIRED_SOURCE_LANES
        default_gold_policy = (
            GOLD_NOT_ELIGIBLE
            if lane == SOURCE_LANE_UNSAFE_UNVERIFIED
            else GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
        )
        required_checks = tuple(
            dict(item)
            for item in (payload.get("required_checks") or [])
            if isinstance(item, dict)
        )
        blockers = tuple(
            _clean_text(item)
            for item in (payload.get("promotion_blockers") or [])
            if _clean_text(item)
        )
        raw_candidate = payload.get("raw_candidate") or {}
        return cls(
            candidate_id=_clean_text(payload.get("candidate_id")),
            lane=lane,
            provider=_clean_text(payload.get("provider")),
            title=_clean_text(payload.get("title")),
            source_url=_clean_text(payload.get("source_url")),
            source_ref=_clean_text(payload.get("source_ref")),
            query=_clean_text(payload.get("query")),
            source_request_query=_clean_text(payload.get("source_request_query")),
            candidate_kind=_clean_text(payload.get("candidate_kind")),
            trust_level=_clean_text(payload.get("trust_level")),
            grade=VERIFICATION_GRADE_BRONZE if is_review_required_lane else _clean_text(payload.get("grade")) or VERIFICATION_GRADE_BRONZE,
            verification_status=(
                VERIFICATION_STATUS_NEEDS_REVIEW
                if is_review_required_lane
                else _clean_text(payload.get("verification_status")) or VERIFICATION_STATUS_NEEDS_REVIEW
            ),
            gold_policy=default_gold_policy if is_review_required_lane else _clean_text(payload.get("gold_policy")) or default_gold_policy,
            citation_eligible=False if is_review_required_lane else bool(payload.get("citation_eligible", False)),
            can_promote_to_gold=False if is_review_required_lane else bool(payload.get("can_promote_to_gold", False)),
            requires_human_review=True if is_review_required_lane else bool(payload.get("requires_human_review", True)),
            required_checks=required_checks or (tuple(required_verification_checks(lane)) if is_review_required_lane else ()),
            promotion_blockers=blockers or (tuple(promotion_blockers(lane)) if is_review_required_lane else ()),
            created_at=_clean_text(payload.get("created_at")),
            updated_at=_clean_text(payload.get("updated_at")),
            raw_candidate=dict(raw_candidate) if isinstance(raw_candidate, dict) else {},
        )


def build_verification_record(payload: dict[str, Any]) -> SourceDiscoveryVerificationRecord:
    lane = _clean_text(payload.get("lane"))
    if lane not in REVIEW_REQUIRED_SOURCE_LANES:
        supported = ", ".join(sorted(REVIEW_REQUIRED_SOURCE_LANES))
        raise ValueError(f"lane은 Bronze 검증 대상이어야 합니다: {supported}")
    provider = _clean_text(payload.get("provider")) or "manual"
    query = _clean_text(payload.get("query"))
    candidate_payload = payload.get("candidate") or {}
    if not isinstance(candidate_payload, dict):
        raise ValueError("candidate는 객체여야 합니다.")
    candidate = dict(candidate_payload)
    title = _candidate_title(candidate, lane=lane, query=query)
    source_url = _candidate_source_url(candidate)
    source_ref = _candidate_ref(candidate, source_url=source_url)
    policy = source_lane_policy(lane)
    gold_policy = GOLD_NOT_ELIGIBLE if lane == SOURCE_LANE_UNSAFE_UNVERIFIED else GOLD_REQUIRES_OFFICIAL_CROSS_CHECK
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    candidate_id = source_discovery_candidate_id(
        lane=lane,
        provider=provider,
        source_url=source_url,
        source_ref=source_ref,
        title=title,
        query=query,
    )
    return SourceDiscoveryVerificationRecord(
        candidate_id=candidate_id,
        lane=lane,
        provider=provider,
        title=title,
        source_url=source_url,
        source_ref=source_ref,
        query=query,
        source_request_query=_clean_text(payload.get("source_request_query")),
        candidate_kind=_candidate_text(candidate, ("kind", "status", "type")) or lane,
        trust_level=_clean_text(policy.get("trust_level")),
        gold_policy=gold_policy,
        required_checks=tuple(required_verification_checks(lane)),
        promotion_blockers=tuple(promotion_blockers(lane)),
        created_at=now,
        updated_at=now,
        raw_candidate=candidate,
    )


def _read_verification_records(path: Path) -> list[SourceDiscoveryVerificationRecord]:
    if not path.exists():
        return []
    rows: list[SourceDiscoveryVerificationRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if _clean_text(payload.get("schema")) != SOURCE_DISCOVERY_VERIFICATION_SCHEMA:
            continue
        record = SourceDiscoveryVerificationRecord.from_dict(payload)
        if record.candidate_id:
            rows.append(record)
    return rows


def list_verification_queue(root_dir: Path, *, limit: int = 50) -> dict[str, Any]:
    path = _verification_queue_path(root_dir)
    deduped: dict[str, SourceDiscoveryVerificationRecord] = {}
    for record in _read_verification_records(path):
        deduped[record.candidate_id] = record
    items = sorted(
        deduped.values(),
        key=lambda item: item.updated_at or item.created_at,
        reverse=True,
    )[: max(1, min(200, limit))]
    return {
        "schema": SOURCE_DISCOVERY_VERIFICATION_SCHEMA,
        "count": len(items),
        "items": [item.to_dict() for item in items],
        "path": str(path),
    }


def save_verification_candidate(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = _verification_queue_path(root_dir)
    record = build_verification_record(payload)
    existing = {
        item.candidate_id: item
        for item in _read_verification_records(path)
    }
    if record.candidate_id in existing:
        return {
            "saved": False,
            "deduplicated": True,
            "item": existing[record.candidate_id].to_dict(),
            **list_verification_queue(root_dir),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return {
        "saved": True,
        "deduplicated": False,
        "item": record.to_dict(),
        **list_verification_queue(root_dir),
    }


__all__ = [
    "REVIEW_REQUIRED_SOURCE_LANES",
    "SOURCE_DISCOVERY_VERIFICATION_SCHEMA",
    "SourceDiscoveryVerificationRecord",
    "build_verification_record",
    "list_verification_queue",
    "required_verification_checks",
    "save_verification_candidate",
]
