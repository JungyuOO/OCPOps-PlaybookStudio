from __future__ import annotations

# PDF outline 탐색과 section heading/anchor 판정을 담당하는 helper 모음.

import re


HEADING_PREFIX_RE = re.compile(r"^(?:#{1,6}\s+|\d+(?:\.\d+)*[\.\)]?\s+)")
HEADING_PUNCTUATION_RE = re.compile(r"[\.!\?]|니다$|합니다$|하십시오$|하세요$")
ANCHOR_SANITIZE_RE = re.compile(r"[^a-z0-9가-힣]+")


def _pdf_search_key(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = re.sub(r"\s+", "", lowered)
    lowered = re.sub(r"[^0-9a-z가-힣]+", "", lowered)
    return lowered


def _pdf_title_pattern(title: str) -> re.Pattern[str] | None:
    tokens = [
        re.escape(token)
        for token in re.findall(r"\d+|[A-Za-z]+|[가-힣]+", title)
        if token
    ]
    if not tokens:
        return None
    return re.compile(r"[\s().:/_-]*".join(tokens), re.IGNORECASE)


def _find_pdf_outline_position(
    pages: list[str],
    title: str,
    *,
    start_page: int,
    start_offset: int,
) -> tuple[int, int, int] | None:
    pattern = _pdf_title_pattern(title)
    if pattern is None:
        return None

    for index in range(start_page, len(pages)):
        haystack = pages[index]
        if not haystack.strip():
            continue
        offset = start_offset if index == start_page else 0
        match = pattern.search(haystack, pos=offset)
        if match:
            return index, match.start(), match.end()

    for index in range(0, start_page):
        haystack = pages[index]
        if not haystack.strip():
            continue
        match = pattern.search(haystack)
        if match:
            return index, match.start(), match.end()
    return None


def _extract_outline_section_body(
    pages: list[str],
    *,
    start_page: int,
    start_offset: int,
    end_page: int,
    end_offset: int,
    current_title: str,
) -> str:
    start_page = max(start_page, 0)
    end_page = min(max(end_page, start_page), len(pages) - 1)
    if start_page >= len(pages) or end_page < start_page:
        return ""

    current_pattern = _pdf_title_pattern(current_title)
    segment_pages: list[str] = []
    consumed_prefix = 0
    for index in range(start_page, end_page + 1):
        page_text = pages[index]
        if not page_text.strip():
            continue
        if index == start_page:
            if current_pattern:
                match = current_pattern.search(page_text, pos=start_offset)
                if match:
                    consumed_prefix = match.end()
                    page_text = page_text[match.end() :]
                else:
                    consumed_prefix = start_offset
                    page_text = page_text[start_offset:]
            else:
                consumed_prefix = start_offset
                page_text = page_text[start_offset:]
        if index == end_page:
            adjusted_limit = end_offset - consumed_prefix if end_page == start_page else end_offset
            limit = min(max(adjusted_limit, 0), len(page_text))
            page_text = page_text[:limit]
        segment_pages.append(page_text.strip())

    text = "\n\n".join(page for page in segment_pages if page.strip())
    text = _clean_outline_section_body(text, heading=current_title)
    return text.strip()


def _clean_outline_section_body(text: str, *, heading: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"(?:\d+\s*장(?:\s*장)?\s*\.\s*[가-힣A-Za-z0-9\s().:/_-]{8,}?\s+\d+)\s*$",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"(?i)^openShift container platform\s+\d+\.\d+\s+", "", cleaned)
    heading_pattern = _pdf_title_pattern(heading)
    if heading_pattern:
        cleaned = heading_pattern.sub("", cleaned, count=1).strip()
    cleaned = re.sub(r"\bPage Summary\b", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _looks_like_pdf_heading(line: str) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 96:
        return False
    if HEADING_PREFIX_RE.match(candidate) or re.match(
        r"(?:\d+\s*장\s*\.|\d+\.\d+(?:\.\d+)*\.|(?:표|그림)\s*\d+\.\d+\.|(?:중요|주의|참고|팁)\b)",
        candidate,
    ):
        return True
    if HEADING_PUNCTUATION_RE.search(candidate):
        return False
    words = candidate.split()
    if 2 <= len(words) <= 8 and candidate == candidate.title():
        return True
    if len(words) == 1:
        return len(candidate) >= 8 and not re.search(r"[,:;]", candidate)
    return 8 <= len(candidate) <= 42 and not re.search(r"[,:;]", candidate)


def _normalize_pdf_heading(line: str) -> str:
    stripped = line.strip()
    return re.sub(r"^#{1,6}\s*", "", stripped)


def _infer_pdf_section_level(heading: str) -> int:
    normalized = heading.strip()
    match = re.match(r"^(\d+(?:\.\d+)*)", normalized)
    if match:
        return match.group(1).count(".") + 1
    return 1


def _pdf_anchor(seed: str, ordinal: int) -> str:
    normalized = ANCHOR_SANITIZE_RE.sub("-", seed.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or f"pdf-section-{ordinal}"
