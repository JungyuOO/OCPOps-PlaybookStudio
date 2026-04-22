from __future__ import annotations

# PDF 페이지 전처리와 docling 본문 클린업을 담당하는 helper 모음.

import re


WHITESPACE_RE = re.compile(r"\s+")
PAGE_MARKER_RE = re.compile(r"^(?:page|페이지)\s+\d+$", re.IGNORECASE)
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
PDF_STRUCTURE_BREAK_RE = re.compile(
    r"(?=(?:\d+\s*장\s*\.|\d+\.\d+(?:\.\d+)*\.|(?:표|그림)\s*\d+\.\d+\.|(?:중요|주의|참고|팁)\b))"
)
PDF_STRUCTURAL_MARKER_RE = re.compile(
    r"(?:\d+\s*장\s*\.|\d+\.\d+(?:\.\d+)*\.|(?:표|그림)\s*\d+\.\d+\.|(?:중요|주의|참고|팁)\b)"
)
PDF_FRONT_MATTER_TITLE_RE = re.compile(
    r"OpenShift Container Platform\s+\d+\.\d+.*?(?:Last Updated:\s*\d{4}-\d{2}-\d{2})?",
    re.IGNORECASE,
)
PDF_TOC_DOT_LEADER_RE = re.compile(r"(?:\.\s*){12,}")
PDF_TRAILING_PAGE_NUMBER_RE = re.compile(r"\s+\d+\s*$")
PDF_TRAILING_CHAPTER_FOOTER_RE = re.compile(
    r"(?:\d+\s*장(?:\s*장)?\s*\.\s*[가-힣A-Za-z0-9\s().:/_-]{8,}?\s+\d+)\s*$"
)
PDF_SKIP_PAGE_RE = re.compile(
    r"^(?:OpenShift Container Platform\s+\d+\.\d+.*|Last Updated:\s*\d{4}-\d{2}-\d{2}|Table of Contents.*|Legal Notice.*)?$",
    re.IGNORECASE,
)
DOCLING_SKIP_HEADINGS = {"legal notice", "table of contents"}
DOCLING_INLINE_HEADINGS = {
    "abstract",
    "사전 요구 사항",
    "프로세스",
    "추가 리소스",
    "중요",
    "참고",
    "작은 정보",
    "출력 예",
    "사용 예",
    "출력",
    "예",
    "spec:",
}
DOCLING_INLINE_HEADINGS_LOWER = {item.lower() for item in DOCLING_INLINE_HEADINGS}


def _skip_docling_heading(heading: str) -> bool:
    normalized = heading.strip().lower()
    if normalized in DOCLING_SKIP_HEADINGS:
        return True
    if normalized.startswith("openshift container platform "):
        return True
    return False


def _should_inline_docling_heading(heading: str) -> bool:
    normalized = heading.strip().lower()
    return normalized in DOCLING_INLINE_HEADINGS_LOWER


def _docling_section_level(heading: str, *, raw_level: int, parent_level: int) -> int:
    normalized = heading.strip()
    chapter_match = re.match(r"^\d+\s*장\b", normalized)
    if chapter_match:
        return 1
    section_match = re.match(r"^(\d+(?:\.\d+)+)", normalized)
    if section_match:
        return section_match.group(1).count(".") + 1
    if re.match(r"^(?:표|그림)\s*\d+\.\d+", normalized):
        return max(parent_level + 1, 2)
    return max(parent_level + 1, max(raw_level - 1, 1))


def _clean_docling_section_body(text: str, *, heading: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    kept_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            kept_lines.append("")
            continue
        if line == "<!-- image -->":
            continue
        if line in {"OpenShift Container Platform 시작하기"}:
            continue
        if re.fullmatch(r"OpenShift Container Platform \d+\.\d+", line):
            continue
        if line == ".":
            continue
        if lower.startswith("copyright ©"):
            continue
        if _is_docling_dot_leader_line(line):
            continue
        if _is_docling_table_separator_line(line):
            continue
        kept_lines.append(raw_line)

    cleaned = "\n".join(kept_lines).strip()
    cleaned = _strip_leading_heading_line(cleaned, heading)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _strip_leading_heading_line(text: str, heading: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or not heading.strip():
        return cleaned
    lines = cleaned.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    first = lines[0].strip()
    if first == heading.strip():
        return "\n".join(lines[1:]).strip()
    first_key = _pdf_search_key(first)
    heading_key = _pdf_search_key(heading)
    if first_key and heading_key and first_key == heading_key:
        return "\n".join(lines[1:]).strip()
    return cleaned


def _is_docling_dot_leader_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    dot_count = stripped.count(".")
    if dot_count < 12:
        return False
    other = re.sub(r"[.\s|]", "", stripped)
    return other == ""


def _is_docling_table_separator_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    inner = stripped.strip("|").replace("-", "").replace(":", "").replace(" ", "")
    return inner == ""


def _validate_pdf_rows(rows: list[dict[str, object]], *, page_count: int) -> None:
    if not rows:
        return
    short_rows = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if len(text) <= 18:
            short_rows += 1
    if len(rows) > max(400, page_count * 12) and short_rows / max(len(rows), 1) >= 0.55:
        raise ValueError(
            "PDF section normalization 품질이 낮습니다. "
            "줄 단위 텍스트가 과도하게 쪼개져 study view로 쓰기 어렵습니다. "
            "더 나은 PDF 추출기나 OCR 전처리가 필요합니다."
        )


def _prepare_pdf_page_text(page_text: str) -> str:
    normalized = (page_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    if _should_skip_pdf_page(normalized):
        return ""
    normalized = re.sub(r"\n\s*\n+", "\u2029", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" ?\n ?", " ", normalized)
    normalized = normalized.replace("\u2029", "\n\n")
    normalized = PDF_TOC_DOT_LEADER_RE.sub(" ", normalized)
    normalized = PDF_TRAILING_PAGE_NUMBER_RE.sub("", normalized).strip()
    normalized = PDF_TRAILING_CHAPTER_FOOTER_RE.sub("", normalized).strip()

    marker_match = PDF_STRUCTURAL_MARKER_RE.search(normalized)
    if marker_match and marker_match.start() > 0:
        prefix = normalized[:marker_match.start()].strip()
        if prefix and PDF_FRONT_MATTER_TITLE_RE.search(prefix):
            normalized = normalized[marker_match.start() :].strip()

    if (
        normalized.lower().startswith("table of contents")
        or normalized.startswith("목차")
    ) and len(PDF_STRUCTURAL_MARKER_RE.findall(normalized)) >= 6:
        return ""

    if not PDF_STRUCTURAL_MARKER_RE.search(normalized):
        if PDF_SKIP_PAGE_RE.match(normalized):
            return ""
        if PDF_FRONT_MATTER_TITLE_RE.search(normalized) and len(normalized) < 260:
            return ""

    normalized = PDF_STRUCTURE_BREAK_RE.sub("\n\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def _should_skip_pdf_page(normalized: str) -> bool:
    compact = re.sub(r"\s+", " ", normalized).strip()
    lowered = compact.lower()
    if not compact:
        return True
    if PDF_STRUCTURAL_MARKER_RE.search(compact):
        return False
    if lowered.startswith("legal notice") or "copyright ©" in lowered:
        return True
    if compact.startswith("목차") or lowered.startswith("table of contents"):
        return True
    if compact.count(".") >= 200 and ("table of contents" in lowered or compact.count("1.") >= 2):
        return True
    if PDF_SKIP_PAGE_RE.match(compact) and len(compact) < 260:
        return True
    return False


def _pdf_search_key(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = re.sub(r"\s+", "", lowered)
    lowered = re.sub(r"[^0-9a-z가-힣]+", "", lowered)
    return lowered
