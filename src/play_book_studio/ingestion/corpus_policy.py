# OCP 코퍼스의 보강 우선순위와 gap lane 분류 규칙을 모아 둔 파일이다.
# retrieval miss를 "나중에 보자"로 흘리지 않고, 다음 수집/번역/검토 순서를 고정할 때 쓴다.
from __future__ import annotations

TRANSLATION_FIRST_SLUGS = (
    "backup_and_restore",
    "installing_on_any_platform",
    "machine_configuration",
    "monitoring",
)

MANUAL_REVIEW_FIRST_SLUGS = (
    "etcd",
    "operators",
)

LANE_APPROVED = "approved"
LANE_TRANSLATION_FIRST = "translation_first"
LANE_MANUAL_REVIEW_FIRST = "manual_review_first"
LANE_REVIEW = "review"
LANE_WATCH = "watch"


def classify_gap_lane(
    *,
    book_slug: str,
    high_value: bool,
    content_status: str,
    fallback_detected: bool,
) -> tuple[str, int, str]:
    if not high_value:
        return LANE_WATCH, 99, "not a high-value coverage gap"

    if content_status == "approved_ko":
        return LANE_APPROVED, 0, "already approved for runtime citation"

    if book_slug in TRANSLATION_FIRST_SLUGS or fallback_detected:
        return LANE_TRANSLATION_FIRST, 1, "preferred next step is Korean translation or source substitution"

    if book_slug in MANUAL_REVIEW_FIRST_SLUGS:
        return LANE_MANUAL_REVIEW_FIRST, 2, "preferred next step is manual source review or curated internal summary"

    if content_status in {"blocked", "mixed", "translated_ko_draft"}:
        return LANE_REVIEW, 3, "needs manual review before corpus admission"

    return LANE_WATCH, 4, "track as backlog but not the first corpus expansion target"
