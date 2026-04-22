# retrieval 질문 전처리에 공통으로 쓰는 텍스트 helper 모음이다.
# 공백 정리, 중복 제거, 토큰 수 계산처럼 여러 규칙이 함께 쓰는 최소 기반을 여기에 둔다.
from __future__ import annotations

import re


HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
SPACE_RE = re.compile(r"\s+")
SECTION_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s*")


def contains_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text or ""))


def collapse_spaces(text: str) -> str:
    return SPACE_RE.sub(" ", (text or "")).strip()


def strip_section_prefix(text: str) -> str:
    collapsed = collapse_spaces(text)
    if not collapsed:
        return ""
    last_segment = collapsed.split(">")[-1].strip()
    cleaned = SECTION_PREFIX_RE.sub("", last_segment).strip()
    return cleaned or last_segment


def append_terms(base_query: str, terms: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []

    for token in collapse_spaces(base_query).split():
        lowered = token.lower()
        if lowered not in seen:
            seen.add(lowered)
            ordered.append(token)

    for term in terms:
        for token in collapse_spaces(term).split():
            lowered = token.lower()
            if lowered not in seen:
                seen.add(lowered)
                ordered.append(token)

    return " ".join(ordered).strip()


def dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        cleaned = collapse_spaces(query)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(cleaned)
    return unique


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))
