# ingestion audit에서 공통으로 쓰는 언어/제목/승인 판정 규칙 모음이다.
from __future__ import annotations

import re

from .models import (
    CITATION_ELIGIBLE_STATUSES,
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_BLOCKED,
    CONTENT_STATUS_EN_ONLY,
    CONTENT_STATUS_MIXED,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    SourceManifestEntry,
)


HANGUL_SYLLABLE_RE = re.compile(r"[가-힣]")
HANGUL_JAMO_RE = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]")
CJK_IDEOGRAPH_RE = re.compile(r"[\u4e00-\u9fff]")
SUSPICIOUS_TITLE_CHAR_RE = re.compile(r"[�]|[ㄱ-ㅎㅏ-ㅣ]|[\u4e00-\u9fff]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
LANGUAGE_FALLBACK_RE = re.compile(
    r"This content is not available in (the )?selected language|"
    r"이 콘텐츠는 선택한 언어로 제공되지 않습니다",
    re.IGNORECASE,
)
CONTENT_STATUS_SORT_ORDER = {
    CONTENT_STATUS_APPROVED_KO: 0,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT: 1,
    CONTENT_STATUS_MIXED: 2,
    CONTENT_STATUS_EN_ONLY: 3,
    CONTENT_STATUS_BLOCKED: 4,
}


def looks_like_mojibake_title(text: str) -> bool:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return False
    if SUSPICIOUS_TITLE_CHAR_RE.search(cleaned):
        return True
    question_marks = cleaned.count("?")
    return question_marks >= 2


def hangul_ratio(texts: list[str]) -> float:
    if not texts:
        return 0.0
    hangul = sum(int(bool(HANGUL_SYLLABLE_RE.search(text or ""))) for text in texts)
    return round(hangul / len(texts), 4)


def is_english_like_title(text: str) -> bool:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return False
    return bool(LATIN_LETTER_RE.search(cleaned)) and not bool(HANGUL_SYLLABLE_RE.search(cleaned))


def body_language_guess(*, hangul_chunk_ratio: float, fallback_detected: bool) -> str:
    if fallback_detected or hangul_chunk_ratio < 0.05:
        return "en_only"
    if hangul_chunk_ratio < 0.85:
        return "mixed"
    return "ko"


def classify_content_status(
    *,
    section_count: int,
    chunk_count: int,
    hangul_section_ratio: float,
    hangul_chunk_ratio: float,
    title_english_like: bool,
    fallback_detected: bool,
) -> tuple[str, str]:
    if fallback_detected:
        return CONTENT_STATUS_EN_ONLY, "vendor page reports selected-language fallback"
    if section_count == 0 or chunk_count == 0:
        return CONTENT_STATUS_BLOCKED, "missing normalized sections or chunks"
    if hangul_chunk_ratio < 0.05:
        return CONTENT_STATUS_EN_ONLY, "chunk text is effectively non-Korean"
    if hangul_chunk_ratio < 0.85 or hangul_section_ratio < 0.85:
        return CONTENT_STATUS_MIXED, "book mixes Korean and non-Korean body text"
    if title_english_like:
        return CONTENT_STATUS_MIXED, "book title is English-like even though body is mostly Korean"
    return CONTENT_STATUS_APPROVED_KO, ""


def resolve_final_content_status(
    entry: SourceManifestEntry,
    *,
    auto_status: str,
    auto_reason: str,
    allow_manual_synthesis_override: bool = True,
) -> tuple[str, bool, str, str]:
    manual_status = (entry.content_status or "").strip()
    if (
        allow_manual_synthesis_override
        and
        manual_status == CONTENT_STATUS_APPROVED_KO
        and entry.approval_status == "approved"
        and entry.source_type == "manual_synthesis"
        and auto_status in {CONTENT_STATUS_APPROVED_KO, CONTENT_STATUS_BLOCKED}
    ):
        return (
            CONTENT_STATUS_APPROVED_KO,
            True,
            "",
            "approved",
        )
    if manual_status == CONTENT_STATUS_TRANSLATED_KO_DRAFT:
        return (
            CONTENT_STATUS_TRANSLATED_KO_DRAFT,
            False,
            "translated Korean draft requires review before citation",
            "needs_review",
        )
    citation_eligible = auto_status in CITATION_ELIGIBLE_STATUSES
    approval_status = "approved" if citation_eligible else "needs_review"
    return auto_status, citation_eligible, auto_reason, approval_status
