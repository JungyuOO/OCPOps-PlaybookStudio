# ingestion 산출물의 제목/본문/경로 품질을 검사해서 data quality 리포트를 만든다.
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import re

from bs4 import BeautifulSoup

from .audit_rules import CJK_IDEOGRAPH_RE, HANGUL_JAMO_RE, HANGUL_SYLLABLE_RE, looks_like_mojibake_title
from .manifest import read_manifest, runtime_catalog_entries
from .validation import read_jsonl


LATIN_HEADING_RE = re.compile(r"[A-Za-z]")
HEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:chapter\s+\d+\.?\s*|(?:\d+|[A-Za-z])(?:\.\d+)*\.?\s*)",
    re.IGNORECASE,
)
COMMAND_HEADING_RE = re.compile(
    r"^(?:oc|kubectl)\s+[A-Za-z0-9._:/-]+(?:\s+[A-Za-z0-9._:/-]+)*$",
    re.IGNORECASE,
)
EXTENSION_POINT_HEADING_RE = re.compile(
    r"^[A-Za-z0-9_-]+(?:[./][A-Za-z0-9_-]+)+(?:/[A-Za-z0-9_-]+)*$"
)


def _read_html_heading(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    heading = soup.select_one("main#main-content article h1") or soup.select_one("article h1")
    if heading is not None:
        return " ".join(heading.get_text(" ", strip=True).split())
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return " ".join(title.split())


def _viewer_path_matches_slug(viewer_path: str, slug: str, *, settings) -> bool:
    template = getattr(settings, "viewer_path_template", "/docs/ocp/{version}/{lang}/{slug}/index.html")
    version = getattr(settings, "ocp_version", "4.20")
    language = getattr(settings, "docs_language", "ko")
    return viewer_path == template.format(version=version, lang=language, slug=slug)


def _source_url_matches_slug(source_url: str, slug: str, *, settings) -> bool:
    template = getattr(
        settings,
        "book_url_template",
        "https://docs.redhat.com/{lang}/documentation/openshift_container_platform/{version}/html-single/{slug}/index",
    )
    version = getattr(settings, "ocp_version", "4.20")
    language = getattr(settings, "docs_language", "ko")
    return source_url == template.format(version=version, lang=language, slug=slug)


def _normalized_heading_for_language_audit(heading: str) -> str:
    stripped = HEADING_NUMBER_PREFIX_RE.sub("", heading or "").strip()
    return " ".join(stripped.split())


def _heading_counts_as_english_for_audit(heading: str) -> bool:
    normalized = _normalized_heading_for_language_audit(heading)
    if not normalized:
        return False
    if not LATIN_HEADING_RE.search(normalized) or HANGUL_SYLLABLE_RE.search(normalized):
        return False
    if COMMAND_HEADING_RE.match(normalized):
        return False
    if EXTENSION_POINT_HEADING_RE.match(normalized):
        return False
    return True


def _audit_comparison_title(
    *,
    display_title: str,
    original_title: str,
    source_type: str,
    source_lane: str,
) -> str:
    if source_type == "manual_synthesis" or source_lane == "applied_playbook":
        return display_title
    return display_title


def _should_audit_normalized_title_against_raw_html(*, source_type: str, source_lane: str) -> bool:
    return not (source_type == "manual_synthesis" or source_lane == "applied_playbook")


def _chunk_text_quality(rows: list[dict]) -> dict[str, object]:
    total_rows = len(rows)
    hangul_rows = 0
    suspicious_rows = 0
    suspicious_examples: list[dict[str, str]] = []
    per_book_totals: Counter[str] = Counter()
    per_book_suspicious: Counter[str] = Counter()

    for row in rows:
        text = str(row.get("text", ""))
        book_slug = str(row.get("book_slug", ""))
        per_book_totals[book_slug] += 1
        if HANGUL_SYLLABLE_RE.search(text):
            hangul_rows += 1
        suspicious_score = (
            len(HANGUL_JAMO_RE.findall(text))
            + len(CJK_IDEOGRAPH_RE.findall(text))
            + text.count("�") * 3
        )
        if suspicious_score >= 4:
            suspicious_rows += 1
            per_book_suspicious[book_slug] += 1
            if len(suspicious_examples) < 5:
                suspicious_examples.append(
                    {
                        "book_slug": book_slug,
                        "section": str(row.get("section", "")),
                        "text_preview": text[:200],
                    }
                )

    suspicious_books: list[dict[str, object]] = []
    for book_slug, total in per_book_totals.items():
        suspicious = per_book_suspicious.get(book_slug, 0)
        if suspicious == 0:
            continue
        suspicious_books.append(
            {
                "book_slug": book_slug,
                "suspicious_chunk_count": suspicious,
                "chunk_count": total,
                "suspicious_ratio": round(suspicious / total, 4),
            }
        )
    suspicious_books.sort(key=lambda item: (-float(item["suspicious_ratio"]), item["book_slug"]))

    return {
        "chunk_count": total_rows,
        "hangul_chunk_ratio": round(hangul_rows / max(total_rows, 1), 4),
        "suspicious_chunk_count": suspicious_rows,
        "suspicious_chunk_ratio": round(suspicious_rows / max(total_rows, 1), 4),
        "suspicious_books": suspicious_books[:20],
        "suspicious_examples": suspicious_examples,
    }


def _playbook_book_paths_from_dirs(book_dirs: tuple[Path, ...]) -> tuple[Path, ...]:
    paths: dict[str, Path] = {}
    for directory in book_dirs:
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            paths.setdefault(path.name, path)
    return tuple(paths[name] for name in sorted(paths))


def _playbook_book_paths(settings) -> tuple[Path, ...]:
    candidate_dirs = tuple(
        Path(path)
        for path in (
            getattr(settings, "playbook_book_dirs", None)
            or (getattr(settings, "playbook_books_dir", None),)
        )
        if path
    )
    return _playbook_book_paths_from_dirs(candidate_dirs)


def _reader_grade_heading_gate_exempt(*, source_type: str, source_lane: str) -> bool:
    return source_type == "manual_synthesis" or source_lane == "applied_playbook"


def _build_playbook_reader_grade_audit_from_paths(paths: tuple[Path, ...]) -> dict[str, object]:
    per_book: list[dict[str, object]] = []
    failing_books: list[dict[str, object]] = []
    warning_books: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        book_slug = str(payload.get("book_slug") or path.stem)
        title = str(payload.get("title") or book_slug)
        translation_status = str(payload.get("translation_status") or "")
        source_metadata = dict(payload.get("source_metadata") or {})
        source_type = str(source_metadata.get("source_type") or "").strip()
        source_lane = str(source_metadata.get("source_lane") or "").strip()
        sections = [dict(section) for section in (payload.get("sections") or []) if isinstance(section, dict)]
        section_count = len(sections)
        unknown_count = 0
        procedure_count = 0
        known_semantic_role_count = 0
        english_heading_count = 0
        code_block_count = 0
        for section in sections:
            semantic_role = str(section.get("semantic_role") or "unknown").strip() or "unknown"
            if semantic_role == "unknown":
                unknown_count += 1
            else:
                known_semantic_role_count += 1
            if semantic_role == "procedure":
                procedure_count += 1
            heading = str(section.get("heading") or "").strip()
            if _heading_counts_as_english_for_audit(heading):
                english_heading_count += 1
            for block in section.get("blocks") or []:
                if isinstance(block, dict) and str(block.get("kind") or "").strip() == "code":
                    code_block_count += 1
        unknown_section_share = round(unknown_count / max(section_count, 1), 4)
        procedure_section_share = round(procedure_count / max(section_count, 1), 4)
        english_heading_ratio = round(english_heading_count / max(section_count, 1), 4)
        semantic_role_coverage_ok = known_semantic_role_count > 0 and unknown_section_share <= 0.5
        heading_language_warning = translation_status == "approved_ko" and english_heading_ratio > 0.5
        heading_gate_exempt = _reader_grade_heading_gate_exempt(
            source_type=source_type,
            source_lane=source_lane,
        )
        heading_language_ok = not heading_language_warning or heading_gate_exempt
        row = {
            "book_slug": book_slug,
            "title": title,
            "translation_status": translation_status,
            "source_type": source_type,
            "source_lane": source_lane,
            "section_count": section_count,
            "known_semantic_role_count": known_semantic_role_count,
            "unknown_section_share": unknown_section_share,
            "procedure_section_share": procedure_section_share,
            "english_heading_ratio": english_heading_ratio,
            "code_block_count": code_block_count,
            "semantic_role_coverage_ok": semantic_role_coverage_ok,
            "heading_language_ok": heading_language_ok,
            "heading_language_warning": heading_language_warning,
            "heading_gate_exempt": heading_gate_exempt,
        }
        per_book.append(row)
        if not semantic_role_coverage_ok or not heading_language_ok:
            failing_books.append(row)
        elif heading_language_warning:
            warning_books.append(row)
    return {
        "book_count": len(per_book),
        "failing_book_count": len(failing_books),
        "warning_book_count": len(warning_books),
        "failing_books": sorted(
            failing_books,
            key=lambda item: (
                item["semantic_role_coverage_ok"],
                item["heading_language_ok"],
                -float(item["unknown_section_share"]),
                -float(item["english_heading_ratio"]),
                item["book_slug"],
            ),
        )[:20],
        "warning_books": sorted(
            warning_books,
            key=lambda item: (
                -float(item["english_heading_ratio"]),
                item["book_slug"],
            ),
        )[:20],
        "worst_books": sorted(
            per_book,
            key=lambda item: (
                item["semantic_role_coverage_ok"],
                item["heading_language_ok"],
                -float(item["unknown_section_share"]),
                -float(item["english_heading_ratio"]),
                item["book_slug"],
            ),
        )[:20],
        "checks": {
            "playbook_semantic_roles_valid": all(
                bool(item["semantic_role_coverage_ok"]) for item in per_book
            ),
            "playbook_korean_headings_valid": all(
                bool(item["heading_language_ok"]) for item in per_book
            ),
        },
    }


def build_playbook_reader_grade_audit_for_dirs(book_dirs: tuple[Path, ...]) -> dict[str, object]:
    return _build_playbook_reader_grade_audit_from_paths(
        _playbook_book_paths_from_dirs(tuple(Path(path) for path in book_dirs))
    )


def build_playbook_reader_grade_audit(settings) -> dict[str, object]:
    return _build_playbook_reader_grade_audit_from_paths(_playbook_book_paths(settings))


def playbook_reader_grade_failures(settings) -> dict[str, dict[str, object]]:
    audit = build_playbook_reader_grade_audit(settings)
    return {
        str(item.get("book_slug", "")).strip(): dict(item)
        for item in audit.get("failing_books", [])
        if str(item.get("book_slug", "")).strip()
    }


def build_data_quality_report(settings) -> dict[str, object]:
    manifest = runtime_catalog_entries(read_manifest(settings.source_catalog_path), settings)
    normalized_docs = read_jsonl(settings.normalized_docs_path)
    chunks = read_jsonl(settings.chunks_path)
    bm25_rows = read_jsonl(settings.bm25_corpus_path)
    preprocessing_log = json.loads(settings.preprocessing_log_path.read_text(encoding="utf-8"))

    normalized_titles: dict[str, str] = {}
    normalized_original_titles: dict[str, str] = {}
    normalized_source_types: dict[str, str] = {}
    normalized_source_lanes: dict[str, str] = {}
    for row in normalized_docs:
        slug = str(row["book_slug"])
        normalized_titles.setdefault(slug, str(row["book_title"]))
        normalized_original_titles.setdefault(slug, str(row.get("original_title", "")))
        normalized_source_types.setdefault(slug, str(row.get("source_type", "")))
        normalized_source_lanes.setdefault(slug, str(row.get("source_lane", "")))

    chunk_titles: dict[str, str] = {}
    chunk_original_titles: dict[str, str] = {}
    chunk_source_types: dict[str, str] = {}
    chunk_source_lanes: dict[str, str] = {}
    for row in chunks:
        slug = str(row["book_slug"])
        chunk_titles.setdefault(slug, str(row["book_title"]))
        chunk_original_titles.setdefault(slug, str(row.get("original_title", "")))
        chunk_source_types.setdefault(slug, str(row.get("source_type", "")))
        chunk_source_lanes.setdefault(slug, str(row.get("source_lane", "")))

    preprocessing_titles = {
        str(item.get("book_slug")): str(item.get("title", ""))
        for item in preprocessing_log.get("per_book_stats", [])
        if item.get("book_slug")
    }

    raw_html_titles: dict[str, str] = {}
    for entry in manifest:
        html_path = settings.raw_html_dir / f"{entry.book_slug}.html"
        if html_path.exists():
            raw_html_titles[entry.book_slug] = _read_html_heading(html_path)

    per_book: list[dict[str, object]] = []
    manifest_mojibake = 0
    preprocessing_mojibake = 0
    normalized_mojibake = 0
    chunk_mojibake = 0
    raw_html_mojibake = 0
    manifest_raw_mismatch = 0
    normalized_raw_mismatch = 0
    chunk_raw_mismatch = 0
    bad_viewer_paths = 0
    bad_source_urls = 0

    for entry in manifest:
        slug = entry.book_slug
        manifest_title = entry.title
        preprocessing_title = preprocessing_titles.get(slug, "")
        normalized_title = normalized_titles.get(slug, "")
        chunk_title = chunk_titles.get(slug, "")
        raw_html_title = raw_html_titles.get(slug, "")
        normalized_audit_title = _audit_comparison_title(
            display_title=normalized_title,
            original_title=normalized_original_titles.get(slug, ""),
            source_type=normalized_source_types.get(slug, ""),
            source_lane=normalized_source_lanes.get(slug, ""),
        )
        chunk_audit_title = _audit_comparison_title(
            display_title=chunk_title,
            original_title=chunk_original_titles.get(slug, ""),
            source_type=chunk_source_types.get(slug, ""),
            source_lane=chunk_source_lanes.get(slug, ""),
        )

        manifest_flag = looks_like_mojibake_title(manifest_title)
        preprocessing_flag = looks_like_mojibake_title(preprocessing_title)
        normalized_flag = looks_like_mojibake_title(normalized_title)
        chunk_flag = looks_like_mojibake_title(chunk_title)
        raw_html_flag = looks_like_mojibake_title(raw_html_title)

        manifest_mojibake += int(manifest_flag)
        preprocessing_mojibake += int(preprocessing_flag)
        normalized_mojibake += int(normalized_flag)
        chunk_mojibake += int(chunk_flag)
        raw_html_mojibake += int(raw_html_flag)

        manifest_match = bool(raw_html_title) and manifest_title == raw_html_title
        normalized_match = (
            not raw_html_title
            or not normalized_title
            or not _should_audit_normalized_title_against_raw_html(
                source_type=normalized_source_types.get(slug, ""),
                source_lane=normalized_source_lanes.get(slug, ""),
            )
            or normalized_audit_title == raw_html_title
        )
        chunk_match = (
            not raw_html_title
            or not chunk_title
            or not _should_audit_normalized_title_against_raw_html(
                source_type=chunk_source_types.get(slug, ""),
                source_lane=chunk_source_lanes.get(slug, ""),
            )
            or chunk_audit_title == raw_html_title
        )

        manifest_raw_mismatch += int(bool(raw_html_title) and not manifest_match)
        normalized_raw_mismatch += int(
            bool(raw_html_title)
            and bool(normalized_title)
            and _should_audit_normalized_title_against_raw_html(
                source_type=normalized_source_types.get(slug, ""),
                source_lane=normalized_source_lanes.get(slug, ""),
            )
            and not normalized_match
        )
        chunk_raw_mismatch += int(
            bool(raw_html_title)
            and bool(chunk_title)
            and _should_audit_normalized_title_against_raw_html(
                source_type=chunk_source_types.get(slug, ""),
                source_lane=chunk_source_lanes.get(slug, ""),
            )
            and not chunk_match
        )

        viewer_ok = _viewer_path_matches_slug(entry.viewer_path, slug, settings=settings)
        source_ok = _source_url_matches_slug(entry.source_url, slug, settings=settings)
        bad_viewer_paths += int(not viewer_ok)
        bad_source_urls += int(not source_ok)

        if any(
            (
                manifest_flag,
                preprocessing_flag,
                normalized_flag,
                chunk_flag,
                raw_html_flag,
                not viewer_ok,
                not source_ok,
                bool(raw_html_title) and not manifest_match,
                bool(raw_html_title)
                and bool(normalized_title)
                and _should_audit_normalized_title_against_raw_html(
                    source_type=normalized_source_types.get(slug, ""),
                    source_lane=normalized_source_lanes.get(slug, ""),
                )
                and not normalized_match,
                bool(raw_html_title) and bool(chunk_title) and not chunk_match,
            )
        ):
            per_book.append(
                {
                    "book_slug": slug,
                    "manifest_title": manifest_title,
                    "preprocessing_title": preprocessing_title,
                    "normalized_title": normalized_title,
                    "normalized_audit_title": normalized_audit_title,
                    "chunk_title": chunk_title,
                    "chunk_audit_title": chunk_audit_title,
                    "raw_html_title": raw_html_title,
                    "manifest_title_mojibake": manifest_flag,
                    "preprocessing_title_mojibake": preprocessing_flag,
                    "normalized_title_mojibake": normalized_flag,
                    "chunk_title_mojibake": chunk_flag,
                    "raw_html_title_mojibake": raw_html_flag,
                    "manifest_matches_raw_html": manifest_match,
                    "normalized_matches_raw_html": normalized_match,
                    "chunk_matches_raw_html": chunk_match,
                    "viewer_path_ok": viewer_ok,
                    "source_url_ok": source_ok,
                }
            )

    text_audit = _chunk_text_quality(chunks)
    playbook_reader_audit = build_playbook_reader_grade_audit(settings)

    return {
        "artifact_scope": {
            "manifest_count": len(manifest),
            "normalized_doc_count": len(normalized_docs),
            "chunk_count": len(chunks),
            "bm25_row_count": len(bm25_rows),
            "raw_html_count": len(raw_html_titles),
        },
        "title_audit": {
            "manifest_mojibake_count": manifest_mojibake,
            "preprocessing_log_mojibake_count": preprocessing_mojibake,
            "normalized_title_mojibake_count": normalized_mojibake,
            "chunk_title_mojibake_count": chunk_mojibake,
            "raw_html_title_mojibake_count": raw_html_mojibake,
            "manifest_raw_html_mismatch_count": manifest_raw_mismatch,
            "normalized_raw_html_mismatch_count": normalized_raw_mismatch,
            "chunk_raw_html_mismatch_count": chunk_raw_mismatch,
        },
        "path_audit": {
            "bad_viewer_path_count": bad_viewer_paths,
            "bad_source_url_count": bad_source_urls,
        },
        "text_audit": text_audit,
        "manualbook_audit": playbook_reader_audit,
        "sample_issues": per_book[:25],
        "checks": {
            "raw_html_titles_clean": raw_html_mojibake == 0,
            "normalized_titles_clean": normalized_mojibake == 0,
            "chunk_titles_clean": chunk_mojibake == 0,
            "manifest_titles_clean": manifest_mojibake == 0,
            "preprocessing_titles_clean": preprocessing_mojibake == 0,
            "normalized_titles_align_with_raw_html": normalized_raw_mismatch == 0,
            "chunk_titles_align_with_raw_html": chunk_raw_mismatch == 0,
            "viewer_paths_valid": bad_viewer_paths == 0,
            "source_urls_valid": bad_source_urls == 0,
            "chunk_text_suspicious_ratio_below_1pct": text_audit["suspicious_chunk_ratio"] < 0.01,
            "playbook_semantic_roles_valid": playbook_reader_audit["checks"]["playbook_semantic_roles_valid"],
            "playbook_korean_headings_valid": playbook_reader_audit["checks"]["playbook_korean_headings_valid"],
        },
    }
