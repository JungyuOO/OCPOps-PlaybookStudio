"""bucket builders for the data control room payload."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from play_book_studio.config.settings import load_settings
from play_book_studio.db.official_documents import load_official_manifest_entries
from play_book_studio.runtime_catalog_registry import official_runtime_books
from play_book_studio.wiki_gold_builder import gold_build_contract_from_blockers

from .runtime_truth import official_runtime_grade, official_runtime_truth_payload
from .wiki_user_overlay import build_wiki_overlay_signal_payload

LATEST_RUNTIME_BRONZE_SOURCE_TYPES = frozenset(
    {
        "topic_playbook",
        "operation_playbook",
        "troubleshooting_playbook",
        "policy_overlay_book",
        "synthesized_playbook",
    }
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SPACE_RE = re.compile(r"\s+")
_HTML_HEADING_RE = re.compile(r"<h[1-6]\b", re.IGNORECASE)


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_read_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _raw_html_meta_path(root: Path, slug: str) -> Path:
    return root / "data" / "bronze" / "raw_html" / f"{slug}.meta.json"


def _first_nonempty(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _normalize_repo_relative_path(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return ""
    suffix = Path(normalized).suffix.lower()
    if suffix:
        return normalized
    return f"{normalized.rstrip('/')}/index.adoc"


def _repo_blob_href(*, repo_url: str, branch: str, relative_path: str) -> str:
    repo = str(repo_url or "").strip().rstrip("/")
    path = _normalize_repo_relative_path(relative_path)
    if not repo or not path:
        return ""
    branch_name = str(branch or "").strip() or "main"
    return f"{repo}/blob/{branch_name}/{path}"


def _official_docs_source_payload(root: Path, *, slug: str, entry: dict[str, Any], settings) -> dict[str, Any]:
    bronze_meta = _safe_read_json(_raw_html_meta_path(root, slug))
    current_source_url = _first_nonempty(entry.get("source_url"))
    fallback_source_url = _first_nonempty(entry.get("fallback_source_url"), bronze_meta.get("fallback_source_url"))
    homepage_url = _first_nonempty(
        current_source_url if "docs.redhat.com" in current_source_url else "",
        fallback_source_url if "docs.redhat.com" in fallback_source_url else "",
        bronze_meta.get("source_url"),
        bronze_meta.get("resolved_source_url"),
        settings.book_url_template.format(slug=slug),
    )
    repo_relative_path = _first_nonempty(
        entry.get("source_relative_path"),
        *(entry.get("source_relative_paths") or []),
        bronze_meta.get("source_relative_path"),
        *(bronze_meta.get("source_relative_paths") or []),
    )
    repo_url = _first_nonempty(entry.get("source_repo"), bronze_meta.get("source_repo"))
    repo_branch = _first_nonempty(entry.get("source_branch"), bronze_meta.get("source_branch"), f"enterprise-{settings.ocp_version}")
    repo_href = _first_nonempty(
        current_source_url if "github.com" in current_source_url else "",
        _repo_blob_href(repo_url=repo_url, branch=repo_branch, relative_path=repo_relative_path),
    )
    primary_input_kind = _first_nonempty(entry.get("primary_input_kind"), bronze_meta.get("primary_input_kind"))
    current_basis = "unknown"
    if "github.com" in current_source_url or primary_input_kind == "source_repo":
        current_basis = "official_repo"
    elif "docs.redhat.com" in current_source_url or primary_input_kind == "html_single":
        current_basis = "official_homepage"
    elif repo_href and not homepage_url:
        current_basis = "official_repo"
    elif homepage_url and not repo_href:
        current_basis = "official_homepage"
    basis_label = {
        "official_homepage": "공식 홈페이지 기준",
        "official_repo": "공식 레포 기준",
    }.get(current_basis, "원천 기준 미기록")
    return {
        "current_source_basis": current_basis,
        "current_source_label": basis_label,
        "source_options": [
            {
                "key": "official_homepage",
                "label": "공식 홈페이지",
                "href": homepage_url,
                "availability": "available" if homepage_url else "missing",
                "note": "공식 KO published surface · 번역 없이 바로 reader-grade 기준선" if homepage_url else "공식 홈페이지 surface 미확인",
                "is_current": current_basis == "official_homepage",
            },
            {
                "key": "official_repo",
                "label": "공식 레포",
                "href": repo_href,
                "availability": "available" if repo_href else "missing",
                "note": "공식 AsciiDoc 원천 · 한국어 surface에서는 번역이 포함될 수 있음" if repo_href else "repo binding 미확정",
                "is_current": current_basis == "official_repo",
            },
        ],
    }


def _markdown_heading_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        normalized = line.strip()
        if normalized.startswith("## "):
            count += 1
    return count


def _markdown_code_block_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    fence_count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("```"))
    return fence_count // 2


def _build_gold_candidate_book_bucket(root: Path) -> dict[str, Any]:
    manifest_path = root / "data" / "gold_candidate_books" / "full_rebuild_manifest.json"
    return {
        "selected_dir": "",
        "books": [],
        "manifest_path": str(manifest_path.resolve()),
        "surface_policy": "hidden_from_latest_only_surface",
    }


def _translation_runtime_blocked_slugs(translation_lane_report: dict[str, Any]) -> set[str]:
    active_queue = (
        translation_lane_report.get("active_queue")
        if isinstance(translation_lane_report.get("active_queue"), list)
        else []
    )
    blocked: set[str] = set()
    for row in active_queue:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("book_slug") or "").strip()
        lane = row.get("translation_lane") if isinstance(row.get("translation_lane"), dict) else {}
        if not slug:
            continue
        if lane and not bool(lane.get("runtime_eligible")):
            blocked.add(slug)
    return blocked


def _latest_runtime_grade(entry: dict[str, Any]) -> str:
    return official_runtime_grade(entry)


def _latest_runtime_review_status(entry: dict[str, Any], *, grade: str) -> str:
    if grade == "Gold":
        return "active_runtime"
    if grade == "Bronze":
        return "derived_runtime_output"
    return "latest_pipeline_output"


def _operational_viewer_book_slug(viewer_path: str) -> str:
    from play_book_studio.http.source_books_viewer_resolver import parse_active_runtime_markdown_viewer_path
    from play_book_studio.http.viewer_paths import _parse_viewer_path

    parsed = _parse_viewer_path(viewer_path)
    if parsed is not None:
        return str(parsed[0] or "").strip()
    return str(parse_active_runtime_markdown_viewer_path(viewer_path) or "").strip()


def _local_runtime_artifact_exists(root: Path, viewer_path: str, book_slug: str) -> bool:
    from play_book_studio.http.source_books_viewer_resolver import (
        _load_normalized_book_sections,
        _load_playbook_book,
    )
    from play_book_studio.http.source_books_wiki_relations import _active_runtime_markdown_path
    from play_book_studio.http.viewer_paths import _viewer_path_to_local_html

    local_html = _viewer_path_to_local_html(root, viewer_path)
    if local_html is not None:
        return True
    playbook_book = _load_playbook_book(root, book_slug)
    if isinstance(playbook_book, dict) and playbook_book.get("sections"):
        return True
    if _load_normalized_book_sections(root, book_slug):
        return True
    markdown_path = _active_runtime_markdown_path(root, book_slug)
    return bool(markdown_path and markdown_path.exists() and markdown_path.is_file() and _markdown_heading_count(markdown_path) > 0)


def _manifest_runtime_slugs_with_chunks(entries: list[dict[str, Any]]) -> set[str]:
    slugs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("book_slug") or "").strip()
        chunk_count = _safe_int(entry.get("chunk_count") or entry.get("section_count"))
        if slug and chunk_count > 0:
            slugs.add(slug)
    return slugs


def _operational_wiki_gate_context(root: Path, settings, *, approved_manifest_entries: list[dict[str, Any]]) -> dict[str, Any]:
    database_url = str(settings.database_url or "").strip()
    return {
        "root": root,
        "database_url": database_url,
        "database_runtime_slugs": _manifest_runtime_slugs_with_chunks(approved_manifest_entries) if database_url else None,
    }


def _operational_wiki_block_reason(
    gate_context: dict[str, Any],
    *,
    expected_slug: str,
    viewer_path: str,
    section_count: int,
    chunk_count: int,
) -> str:
    if not str(viewer_path or "").strip():
        return "runtime_not_readable::missing_viewer_path"
    if section_count <= 0:
        return "runtime_not_readable::zero_sections"
    if chunk_count <= 0:
        return "runtime_not_readable::zero_chunks"
    book_slug = _operational_viewer_book_slug(viewer_path)
    if not book_slug:
        return "runtime_not_readable::unknown_viewer_route"
    normalized_expected_slug = str(expected_slug or "").strip()
    if normalized_expected_slug and book_slug != normalized_expected_slug:
        return "runtime_not_readable::viewer_slug_mismatch"
    database_url = str(gate_context.get("database_url") or "").strip()
    if database_url:
        database_runtime_slugs = gate_context.get("database_runtime_slugs")
        if database_runtime_slugs is None:
            return "runtime_not_readable::artifact_index_unavailable"
        if book_slug not in database_runtime_slugs:
            return "runtime_not_readable::missing_runtime_artifact"
        return ""
    root = gate_context.get("root")
    if not isinstance(root, Path) or not _local_runtime_artifact_exists(root, viewer_path, book_slug):
        return "runtime_not_readable::missing_runtime_artifact"
    return ""


def _html_visible_text(html_text: str) -> str:
    without_tags = _HTML_TAG_RE.sub(" ", str(html_text or ""))
    return _HTML_SPACE_RE.sub(" ", without_tags).strip()


def _viewer_document_smoke(root: Path, viewer_path: str, *, expected_title: str = "") -> dict[str, Any]:
    if not str(viewer_path or "").strip():
        return {
            "viewer_smoke_status": "fail",
            "viewer_smoke_reason": "missing_viewer_path",
            "viewer_smoke_path": "",
            "viewer_smoke_body_length": 0,
            "viewer_smoke_heading_count": 0,
            "viewer_smoke_title_present": False,
        }
    try:
        from play_book_studio.http.server_routes_viewer import (
            _build_viewer_document_payload,
            _canonicalize_viewer_path,
            _viewer_html_for_path,
        )

        resolved_viewer_path = _canonicalize_viewer_path(viewer_path)
        # Smoke the same viewer route with a single-section render so the gate stays fast.
        html_text = _viewer_html_for_path(root, resolved_viewer_path, page_mode="multi")
        if html_text is None:
            return {
                "viewer_smoke_status": "fail",
                "viewer_smoke_reason": "viewer_404",
                "viewer_smoke_path": resolved_viewer_path,
                "viewer_smoke_body_length": 0,
                "viewer_smoke_heading_count": 0,
                "viewer_smoke_title_present": False,
            }
        payload = _build_viewer_document_payload(html_text, resolved_viewer_path)
        body_html = str(payload.get("html") or "")
        body_text = _html_visible_text(body_html)
        heading_count = len(_HTML_HEADING_RE.findall(body_html))
        title = str(expected_title or "").strip()
        title_present = bool(title and title in body_text)
        result = {
            "viewer_smoke_status": "pass",
            "viewer_smoke_reason": "",
            "viewer_smoke_path": str(payload.get("viewer_path") or resolved_viewer_path),
            "viewer_smoke_body_length": len(body_text),
            "viewer_smoke_heading_count": heading_count,
            "viewer_smoke_title_present": title_present,
        }
        if not body_text:
            result["viewer_smoke_status"] = "fail"
            result["viewer_smoke_reason"] = "viewer_empty_body"
        elif heading_count <= 0:
            result["viewer_smoke_status"] = "fail"
            result["viewer_smoke_reason"] = "viewer_no_sections"
        elif title and not title_present:
            result["viewer_smoke_warning"] = "viewer_title_not_matched"
        return result
    except Exception as exc:  # noqa: BLE001
        return {
            "viewer_smoke_status": "fail",
            "viewer_smoke_reason": "viewer_exception",
            "viewer_smoke_error": str(exc),
            "viewer_smoke_path": str(viewer_path or "").strip(),
            "viewer_smoke_body_length": 0,
            "viewer_smoke_heading_count": 0,
            "viewer_smoke_title_present": False,
        }


def _viewer_smoke_block_reason(smoke: dict[str, Any]) -> str:
    if str(smoke.get("viewer_smoke_status") or "").strip() != "fail":
        return ""
    reason = str(smoke.get("viewer_smoke_reason") or "viewer_smoke_failed").strip()
    return f"runtime_not_readable::{reason}"


def _language_gate_payload(entry: dict[str, Any]) -> dict[str, Any]:
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    content_status = _first_nonempty(entry.get("content_status"), metadata.get("content_status"))
    body_language = _first_nonempty(entry.get("body_language_guess"), metadata.get("body_language_guess"))
    language_quality = _first_nonempty(entry.get("language_quality"), metadata.get("language_quality"), body_language)
    hangul_ratio = _safe_float(entry.get("hangul_chunk_ratio"))
    if hangul_ratio is None:
        hangul_ratio = _safe_float(metadata.get("hangul_chunk_ratio"))
    latin_only_ratio = _safe_float(entry.get("latin_only_chunk_ratio"))
    if latin_only_ratio is None:
        latin_only_ratio = _safe_float(metadata.get("latin_only_chunk_ratio"))
    hangul_count = _safe_int(entry.get("hangul_chunk_count") if "hangul_chunk_count" in entry else metadata.get("hangul_chunk_count"))
    latin_count = _safe_int(entry.get("latin_chunk_count") if "latin_chunk_count" in entry else metadata.get("latin_chunk_count"))
    latin_only_count = _safe_int(
        entry.get("latin_only_chunk_count") if "latin_only_chunk_count" in entry else metadata.get("latin_only_chunk_count")
    )
    chunk_count = _safe_int(entry.get("chunk_count") or metadata.get("chunk_count"))
    gate_status = "unknown"
    gate_reason = ""
    normalized_content_status = content_status.lower()
    normalized_body_language = body_language.lower()
    normalized_language_quality = language_quality.lower()
    if (
        normalized_content_status == "en_only"
        or normalized_body_language == "en_only"
        or normalized_language_quality == "en_only"
        or (hangul_ratio is not None and chunk_count > 0 and hangul_ratio < 0.05)
    ):
        gate_status = "fail"
        gate_reason = "non_ko_content"
        language_quality = language_quality or "en_only"
    elif (
        normalized_content_status in {"mixed", "translated_ko_draft"}
        or normalized_body_language == "mixed"
        or normalized_language_quality == "mixed"
        or (hangul_ratio is not None and chunk_count > 0 and hangul_ratio < 0.85)
    ):
        gate_status = "warning"
        gate_reason = "mixed_ko_content"
        language_quality = language_quality or "mixed"
    elif hangul_ratio is not None:
        gate_status = "pass"
        language_quality = language_quality or "ko"
    return {
        "language_gate_status": gate_status,
        "language_gate_reason": gate_reason,
        "language_quality": language_quality,
        "body_language_guess": body_language,
        "content_status": content_status,
        "hangul_chunk_ratio": hangul_ratio,
        "latin_only_chunk_ratio": latin_only_ratio,
        "hangul_chunk_count": hangul_count,
        "latin_chunk_count": latin_count,
        "latin_only_chunk_count": latin_only_count,
    }


def _language_gate_block_reason(language_gate: dict[str, Any]) -> str:
    if str(language_gate.get("language_gate_status") or "").strip() != "fail":
        return ""
    reason = str(language_gate.get("language_gate_reason") or "language_quality_failed").strip()
    return f"runtime_not_readable::{reason}"


_LANGUAGE_EVIDENCE_KEYS = (
    "grade",
    "source_url",
    "source_candidate_path",
    "source_lane",
    "source_type",
    "body_language_guess",
    "language_quality",
    "content_status",
    "hangul_chunk_ratio",
    "latin_only_chunk_ratio",
    "hangul_chunk_count",
    "latin_chunk_count",
    "latin_only_chunk_count",
    "chunk_count",
)


def _merge_manifest_language_evidence(entry: dict[str, Any], manifest_entry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(manifest_entry, dict) or not manifest_entry:
        return entry
    merged = dict(entry)
    entry_metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    manifest_metadata = manifest_entry.get("metadata") if isinstance(manifest_entry.get("metadata"), dict) else {}
    merged["metadata"] = {**manifest_metadata, **entry_metadata}
    for key in _LANGUAGE_EVIDENCE_KEYS:
        current = merged.get(key)
        if current not in ("", None):
            continue
        if key in manifest_entry:
            merged[key] = manifest_entry.get(key)
        elif key in manifest_metadata:
            merged[key] = manifest_metadata.get(key)
    return merged


def _skipped_viewer_smoke(reason: str, viewer_path: str) -> dict[str, Any]:
    return {
        "viewer_smoke_status": "skipped",
        "viewer_smoke_reason": str(reason or "").replace("runtime_not_readable::", ""),
        "viewer_smoke_path": str(viewer_path or "").strip(),
        "viewer_smoke_body_length": 0,
        "viewer_smoke_heading_count": 0,
        "viewer_smoke_title_present": False,
    }


def _gold_recovery_group(reason: str) -> str:
    normalized = str(reason or "").replace("runtime_not_readable::", "").strip()
    if normalized in {"zero_sections", "zero_chunks", "missing_runtime_artifact", "missing_viewer_path"}:
        return "materialization"
    if normalized in {"non_ko_content", "mixed_ko_content", "language_quality_failed"}:
        return "language_quality"
    if normalized in {"language_gate_missing", "missing_source_provenance", "missing_source_lane"}:
        return "certification_evidence"
    if normalized.startswith("viewer_") or normalized in {"viewer_slug_mismatch", "unknown_viewer_route"}:
        return "viewer"
    return "runtime_gate"


def _gold_recovery_action(reason: str) -> str:
    normalized = str(reason or "").replace("runtime_not_readable::", "").strip()
    if normalized == "zero_sections":
        return "문서 파싱/section materialize 재실행 필요"
    if normalized == "zero_chunks":
        return "chunk materialize 및 색인 입력 재생성 필요"
    if normalized in {"missing_viewer_path", "missing_runtime_artifact"}:
        return "reader/viewer 산출물 경로와 런타임 artifact 재생성 필요"
    if normalized == "viewer_slug_mismatch":
        return "viewer path와 book_slug 매핑 수정 필요"
    if normalized == "unknown_viewer_route":
        return "viewer route 등록 또는 canonical path 정리 필요"
    if normalized.startswith("viewer_"):
        return "reader smoke 실패 원인 수정 후 재검증 필요"
    if normalized == "non_ko_content":
        return "한글화/검수 재실행 후 approved_ko 승급 필요"
    if normalized == "mixed_ko_content":
        return "혼합 언어 구간 검수 후 한국어 품질 재판정 필요"
    if normalized == "language_gate_missing":
        return "한국어 품질 gate evidence 생성 후 재검증 필요"
    if normalized == "missing_source_provenance":
        return "공식 source URL 또는 source artifact provenance 연결 필요"
    if normalized == "missing_source_lane":
        return "source lane/source type 메타데이터 복구 필요"
    return "Gold 계약 blocker 해소 후 재검증 필요"


def _gold_recovery_blocking_check(reason: str) -> str:
    normalized = str(reason or "").replace("runtime_not_readable::", "").strip()
    if normalized in {"zero_sections", "zero_chunks"}:
        return "section_count > 0, chunk_count > 0, viewer_smoke_status=pass"
    if normalized in {"missing_viewer_path", "missing_runtime_artifact", "viewer_slug_mismatch", "unknown_viewer_route"}:
        return "viewer_path exists, runtime artifact exists, reader smoke opens the document"
    if normalized == "non_ko_content":
        return "language_gate_status=pass and body_language_guess=ko"
    if normalized == "mixed_ko_content":
        return "mixed chunks reviewed, Korean ratio accepted, language_gate_status=pass"
    if normalized == "language_gate_missing":
        return "language gate evidence exists for the book"
    if normalized == "missing_source_provenance":
        return "source_url or source_candidate_path is present"
    if normalized == "missing_source_lane":
        return "source_lane or source_type is present"
    if normalized == "not_gold_source_grade":
        return "source_grade=Gold after materialization and approval evidence passes"
    if normalized.startswith("viewer_"):
        return "viewer_smoke_status=pass"
    return "all gold_contract_checks are true"


def _gold_recovery_rerun_command(reason: str) -> str:
    normalized = str(reason or "").replace("runtime_not_readable::", "").strip()
    if normalized in {"zero_sections", "zero_chunks", "missing_runtime_artifact"}:
        return "python -m play_book_studio.cli source-approval-report && python -m play_book_studio.cli runtime"
    if normalized in {"non_ko_content", "mixed_ko_content", "language_gate_missing"}:
        return "python -m play_book_studio.cli source-approval-report && python -m play_book_studio.cli runtime"
    if normalized.startswith("viewer_") or normalized in {"missing_viewer_path", "viewer_slug_mismatch", "unknown_viewer_route"}:
        return "python -m play_book_studio.cli runtime --ui-base-url http://127.0.0.1:8765"
    if normalized in {"missing_source_provenance", "missing_source_lane", "not_gold_source_grade"}:
        return "python -m play_book_studio.cli source-approval-report"
    return "python -m play_book_studio.cli runtime && python -m play_book_studio.cli eval"


GOLD_RECOVERY_BLOCKER_PRIORITY = {
    "zero_sections": 10,
    "zero_chunks": 11,
    "missing_runtime_artifact": 12,
    "missing_viewer_path": 13,
    "viewer_slug_mismatch": 14,
    "unknown_viewer_route": 15,
    "non_ko_content": 20,
    "mixed_ko_content": 21,
    "language_quality_failed": 22,
    "language_gate_missing": 23,
    "missing_source_provenance": 30,
    "missing_source_lane": 31,
    "not_gold_source_grade": 90,
}


def _gold_recovery_blocker_priority(reason: str) -> tuple[int, str]:
    normalized = str(reason or "").replace("runtime_not_readable::", "").strip()
    if normalized.startswith("viewer_"):
        return (16, normalized)
    if normalized.startswith("non_gold_runtime::"):
        return (91, normalized)
    return (GOLD_RECOVERY_BLOCKER_PRIORITY.get(normalized, 80), normalized)


def _prioritize_gold_blockers(blockers: list[str]) -> list[str]:
    deduped = list(dict.fromkeys(blocker for blocker in blockers if blocker))
    return sorted(deduped, key=_gold_recovery_blocker_priority)


def _gold_contract_payload(
    *,
    grade: str,
    section_count: int,
    chunk_count: int,
    viewer_path: str,
    language_gate: dict[str, Any],
    viewer_smoke: dict[str, Any],
    source_url: str = "",
    source_lane: str = "",
    source_type: str = "",
    hidden_reason: str = "",
) -> dict[str, Any]:
    viewer_smoke_status = str(viewer_smoke.get("viewer_smoke_status") or "").strip().lower()
    language_gate_status = str(language_gate.get("language_gate_status") or "").strip().lower()
    blockers: list[str] = []
    warnings: list[str] = []
    if str(grade or "").strip() != "Gold":
        blockers.append("not_gold_source_grade")
    if section_count <= 0:
        blockers.append("zero_sections")
    if chunk_count <= 0:
        blockers.append("zero_chunks")
    if not str(viewer_path or "").strip():
        blockers.append("missing_viewer_path")
    if not str(source_url or "").strip():
        blockers.append("missing_source_provenance")
    if not str(source_lane or source_type or "").strip():
        blockers.append("missing_source_lane")
    if language_gate_status == "fail":
        blockers.append(str(language_gate.get("language_gate_reason") or "language_quality_failed"))
    elif language_gate_status == "warning":
        blockers.append(str(language_gate.get("language_gate_reason") or "language_quality_warning"))
    elif language_gate_status != "pass":
        blockers.append("language_gate_missing")
    if viewer_smoke_status == "fail":
        blockers.append(str(viewer_smoke.get("viewer_smoke_reason") or "viewer_smoke_failed"))
    elif viewer_smoke_status == "skipped" and hidden_reason:
        blockers.append(str(hidden_reason).replace("runtime_not_readable::", "") or "runtime_gate_skipped")
    elif not viewer_smoke_status:
        blockers.append("viewer_smoke_missing")
    if hidden_reason:
        reason = str(hidden_reason).replace("runtime_not_readable::", "") or hidden_reason
        if reason not in blockers:
            blockers.append(reason)
    deduped_blockers = _prioritize_gold_blockers(blockers)
    deduped_warnings = list(dict.fromkeys(warning for warning in warnings if warning))
    status = "gold_certified" if not deduped_blockers else "gold_recovery"
    gold_build_run = gold_build_contract_from_blockers(
        deduped_blockers,
        title=str(viewer_path or source_url or source_lane or "runtime book"),
        source_kind="approved_wiki_runtime",
        source_scope="official_docs",
        metrics={
            "section_count": section_count,
            "chunk_count": chunk_count,
            "viewer_smoke_status": viewer_smoke_status,
            "language_gate_status": language_gate_status,
        },
    )
    return {
        "certified_gold": status == "gold_certified",
        "gold_contract_status": status,
        "gold_contract_blockers": deduped_blockers,
        "gold_contract_warnings": deduped_warnings,
        "gold_recovery_group": _gold_recovery_group(deduped_blockers[0]) if deduped_blockers else "",
        "gold_recovery_action": _gold_recovery_action(deduped_blockers[0]) if deduped_blockers else "",
        "gold_recovery_blocking_check": _gold_recovery_blocking_check(deduped_blockers[0]) if deduped_blockers else "",
        "gold_recovery_rerun_command": _gold_recovery_rerun_command(deduped_blockers[0]) if deduped_blockers else "",
        "effective_grade": "Gold" if status == "gold_certified" else "Gold Recovery",
        "gold_build_run": gold_build_run,
        "gold_build_status": str(gold_build_run.get("status") or ""),
        "gold_build_stage": str(gold_build_run.get("current_stage") or ""),
        "repair_loop_status": "passed" if status == "gold_certified" else "manual_repair_needed",
        "repair_actions": list(gold_build_run.get("repair_actions") or []),
        "gold_evidence": list(gold_build_run.get("gold_evidence") or []),
        "gold_contract_checks": {
            "source_grade_gold": str(grade or "").strip() == "Gold",
            "has_sections": section_count > 0,
            "has_chunks": chunk_count > 0,
            "has_viewer_path": bool(str(viewer_path or "").strip()),
            "has_source_provenance": bool(str(source_url or "").strip()),
            "has_source_lane": bool(str(source_lane or source_type or "").strip()),
            "language_gate_passed": language_gate_status == "pass",
            "viewer_smoke_passed": viewer_smoke_status == "pass",
        },
    }


def _gold_recovery_book_payload(
    entry: dict[str, Any],
    *,
    title: str,
    grade: str,
    section_count: int,
    chunk_count: int,
    viewer_path: str,
    hidden_reason: str,
    language_gate: dict[str, Any] | None = None,
    viewer_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language_payload = language_gate or {}
    smoke_payload = viewer_smoke or _skipped_viewer_smoke(hidden_reason, viewer_path)
    contract = _gold_contract_payload(
        grade=grade,
        section_count=section_count,
        chunk_count=chunk_count,
        viewer_path=viewer_path,
        source_url=str(entry.get("source_url") or entry.get("source_candidate_path") or "").strip(),
        source_lane=str(entry.get("source_lane") or entry.get("source_type") or "").strip(),
        source_type=str(entry.get("source_type") or "").strip(),
        language_gate=language_payload,
        viewer_smoke=smoke_payload,
        hidden_reason=hidden_reason,
    )
    return {
        "book_slug": str(entry.get("book_slug") or "").strip(),
        "title": title,
        "grade": contract["effective_grade"],
        "source_grade": grade,
        "hidden_reason": hidden_reason,
        "section_count": section_count,
        "chunk_count": chunk_count,
        "viewer_path": viewer_path,
        "runtime_readable": False,
        "runtime_gate": "gold_recovery",
        "runtime_readiness": hidden_reason,
        "source_url": str(entry.get("source_url") or entry.get("source_candidate_path") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
        "source_type": str(entry.get("source_type") or "reader_grade_md"),
        "source_lane": str(entry.get("source_lane") or "approved_wiki_runtime"),
        "review_status": str(entry.get("review_status") or entry.get("approval_status") or "needs_review"),
        "approval_state": str(entry.get("approval_state") or entry.get("approval_status") or ""),
        "publication_state": str(entry.get("publication_state") or ""),
        **language_payload,
        **smoke_payload,
        **contract,
    }


def _build_approved_wiki_runtime_book_bucket(
    root: Path,
    *,
    translation_lane_report: dict[str, Any],
    approved_manifest_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settings = load_settings(root)
    manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
    blocked_slugs = _translation_runtime_blocked_slugs(translation_lane_report)
    books: list[dict[str, Any]] = []
    runtime_paths: list[Path] = []
    hidden_books: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    if approved_manifest_entries is None:
        if str(settings.database_url or "").strip():
            approved_manifest_entries = load_official_manifest_entries(settings.database_url)
        else:
            approved_manifest_payload = _safe_read_json(settings.source_manifest_path)
            approved_manifest_entries = approved_manifest_payload.get("entries") if isinstance(approved_manifest_payload.get("entries"), list) else []
    gate_context = _operational_wiki_gate_context(root, settings, approved_manifest_entries=approved_manifest_entries)
    manifest_entries_by_slug = {
        str(entry.get("book_slug") or "").strip(): entry
        for entry in approved_manifest_entries
        if isinstance(entry, dict) and str(entry.get("book_slug") or "").strip()
    }
    for entry in official_runtime_books(root):
        slug = str(entry.get("book_slug") or "").strip()
        if not slug:
            continue
        seen_slugs.add(slug)
        entry = _merge_manifest_language_evidence(entry, manifest_entries_by_slug.get(slug))
        title = str(entry.get("title") or slug)
        grade = _latest_runtime_grade(entry)
        runtime_path_value = str(entry.get("runtime_path") or "").strip()
        runtime_path = Path(runtime_path_value).resolve() if runtime_path_value else None
        if slug in blocked_slugs:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=_safe_int(entry.get("section_count")),
                    chunk_count=_safe_int(entry.get("chunk_count")),
                    viewer_path=str(entry.get("viewer_path") or entry.get("docs_viewer_path") or "").strip(),
                    hidden_reason="translated_ko_draft_runtime_ineligible",
                )
            )
            continue
        if grade != "Gold":
            section_count = _safe_int(entry.get("section_count"))
            chunk_count = _safe_int(entry.get("chunk_count"))
            if section_count <= 0:
                hidden_reason = "zero_sections"
            elif chunk_count <= 0:
                hidden_reason = "zero_chunks"
            else:
                hidden_reason = f"non_gold_runtime::{grade.lower()}"
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=str(entry.get("viewer_path") or entry.get("docs_viewer_path") or "").strip(),
                    hidden_reason=hidden_reason,
                )
            )
            continue
        section_count = int(entry.get("section_count") or 0)
        chunk_count = int(entry.get("chunk_count") or 0)
        code_block_count = int(entry.get("code_block_count") or 0)
        if runtime_path is not None and runtime_path.exists() and runtime_path.is_file():
            runtime_paths.append(runtime_path)
            section_count = max(section_count, _markdown_heading_count(runtime_path))
            code_block_count = max(code_block_count, _markdown_code_block_count(runtime_path))
        viewer_path = str(entry.get("viewer_path") or entry.get("docs_viewer_path") or "").strip()
        language_gate = _language_gate_payload(entry)
        language_block_reason = _language_gate_block_reason(language_gate)
        if language_block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=language_block_reason,
                    language_gate=language_gate,
                    viewer_smoke=_skipped_viewer_smoke(language_block_reason, viewer_path),
                )
            )
            continue
        block_reason = _operational_wiki_block_reason(
            gate_context,
            expected_slug=slug,
            viewer_path=viewer_path,
            section_count=section_count,
            chunk_count=chunk_count,
        )
        if block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=block_reason,
                    language_gate=language_gate,
                    viewer_smoke=_skipped_viewer_smoke(block_reason, viewer_path),
                )
            )
            continue
        viewer_smoke = _viewer_document_smoke(root, viewer_path, expected_title=title)
        smoke_block_reason = _viewer_smoke_block_reason(viewer_smoke)
        if smoke_block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=smoke_block_reason,
                    language_gate=language_gate,
                    viewer_smoke=viewer_smoke,
                )
            )
            continue
        gold_contract = _gold_contract_payload(
            grade=grade,
            section_count=section_count,
            chunk_count=chunk_count,
            viewer_path=viewer_path,
            source_url=str(entry.get("source_url") or entry.get("source_candidate_path") or "").strip(),
            source_lane=str(entry.get("source_lane") or entry.get("source_type") or "").strip(),
            source_type=str(entry.get("source_type") or "").strip(),
            language_gate=language_gate,
            viewer_smoke=viewer_smoke,
        )
        if not bool(gold_contract.get("certified_gold")):
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=str((gold_contract.get("gold_contract_blockers") or ["gold_contract_failed"])[0]),
                    language_gate=language_gate,
                    viewer_smoke=viewer_smoke,
                )
            )
            continue
        truth = official_runtime_truth_payload(settings=settings, manifest_entry=entry)
        source_payload = _official_docs_source_payload(root, slug=slug, entry=entry, settings=settings)
        books.append(
            {
                "book_slug": slug,
                "title": title,
                "grade": grade,
                "source_grade": grade,
                "review_status": _latest_runtime_review_status(entry, grade=grade),
                "source_type": str(entry.get("source_type") or "reader_grade_md"),
                "source_lane": str(entry.get("source_lane") or "approved_wiki_runtime"),
                "section_count": section_count,
                "chunk_count": chunk_count,
                "code_block_count": code_block_count,
                "viewer_path": viewer_path,
                "runtime_readable": True,
                "runtime_gate": "operational_wiki_published",
                "runtime_readiness": "route_and_artifact_passed",
                **language_gate,
                **viewer_smoke,
                **gold_contract,
                "source_url": str(entry.get("source_url") or entry.get("source_candidate_path") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
                "approval_state": str(truth.get("approval_state") or entry.get("approval_state") or ""),
                "publication_state": str(truth.get("publication_state") or entry.get("publication_state") or ""),
                "parser_backend": str(truth.get("parser_backend") or entry.get("parser_backend") or ""),
                "boundary_truth": str(truth.get("boundary_truth") or ""),
                "runtime_truth_label": str(truth.get("runtime_truth_label") or ""),
                "boundary_badge": str(truth.get("boundary_badge") or ""),
                **source_payload,
            }
        )
    for entry in approved_manifest_entries:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("book_slug") or "").strip()
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        if slug in blocked_slugs:
            continue
        title = str(entry.get("title") or slug)
        grade = _latest_runtime_grade(entry)
        if grade != "Gold":
            continue
        section_count = int(entry.get("section_count") or 0)
        chunk_count = int(entry.get("chunk_count") or 0)
        code_block_count = int(entry.get("code_block_count") or 0)
        viewer_path = str(entry.get("viewer_path") or entry.get("docs_viewer_path") or "").strip()
        language_gate = _language_gate_payload(entry)
        language_block_reason = _language_gate_block_reason(language_gate)
        if language_block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=language_block_reason,
                    language_gate=language_gate,
                    viewer_smoke=_skipped_viewer_smoke(language_block_reason, viewer_path),
                )
            )
            continue
        block_reason = _operational_wiki_block_reason(
            gate_context,
            expected_slug=slug,
            viewer_path=viewer_path,
            section_count=section_count,
            chunk_count=chunk_count,
        )
        if block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=block_reason,
                    language_gate=language_gate,
                    viewer_smoke=_skipped_viewer_smoke(block_reason, viewer_path),
                )
            )
            continue
        viewer_smoke = _viewer_document_smoke(root, viewer_path, expected_title=title)
        smoke_block_reason = _viewer_smoke_block_reason(viewer_smoke)
        if smoke_block_reason:
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=smoke_block_reason,
                    language_gate=language_gate,
                    viewer_smoke=viewer_smoke,
                )
            )
            continue
        gold_contract = _gold_contract_payload(
            grade=grade,
            section_count=section_count,
            chunk_count=chunk_count,
            viewer_path=viewer_path,
            source_url=str(entry.get("source_url") or entry.get("source_candidate_path") or "").strip(),
            source_lane=str(entry.get("source_lane") or entry.get("source_type") or "").strip(),
            source_type=str(entry.get("source_type") or "").strip(),
            language_gate=language_gate,
            viewer_smoke=viewer_smoke,
        )
        if not bool(gold_contract.get("certified_gold")):
            hidden_books.append(
                _gold_recovery_book_payload(
                    entry,
                    title=title,
                    grade=grade,
                    section_count=section_count,
                    chunk_count=chunk_count,
                    viewer_path=viewer_path,
                    hidden_reason=str((gold_contract.get("gold_contract_blockers") or ["gold_contract_failed"])[0]),
                    language_gate=language_gate,
                    viewer_smoke=viewer_smoke,
                )
            )
            continue
        truth = official_runtime_truth_payload(settings=settings, manifest_entry=entry)
        source_payload = _official_docs_source_payload(root, slug=slug, entry=entry, settings=settings)
        books.append(
            {
                "book_slug": slug,
                "title": title,
                "grade": grade,
                "source_grade": grade,
                "review_status": _latest_runtime_review_status(entry, grade=grade),
                "source_type": str(entry.get("source_type") or "reader_grade_md"),
                "source_lane": str(entry.get("source_lane") or "approved_wiki_runtime"),
                "section_count": section_count,
                "chunk_count": chunk_count,
                "code_block_count": code_block_count,
                "viewer_path": viewer_path,
                "runtime_readable": True,
                "runtime_gate": "operational_wiki_published",
                "runtime_readiness": "route_and_artifact_passed",
                **language_gate,
                **viewer_smoke,
                **gold_contract,
                "source_url": str(entry.get("source_url") or entry.get("source_candidate_path") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
                "approval_state": str(truth.get("approval_state") or entry.get("approval_state") or ""),
                "publication_state": str(truth.get("publication_state") or entry.get("publication_state") or ""),
                "parser_backend": str(truth.get("parser_backend") or entry.get("parser_backend") or ""),
                "boundary_truth": str(truth.get("boundary_truth") or ""),
                "runtime_truth_label": str(truth.get("runtime_truth_label") or ""),
                "boundary_badge": str(truth.get("boundary_badge") or ""),
                **source_payload,
            }
        )
    if runtime_paths:
        parents = {str(path.parent) for path in runtime_paths}
        selected_dir = sorted(parents)[0] if len(parents) == 1 else str((root / "data" / "wiki_runtime_books").resolve())
    else:
        selected_dir = str((root / "data" / "wiki_runtime_books").resolve())
    return {
        "selected_dir": selected_dir,
        "books": books,
        "manifest_path": str(manifest_path.resolve()),
        "hidden_books": hidden_books,
        "hidden_count": len(hidden_books),
        "recovery_books": hidden_books,
        "recovery_count": len(hidden_books),
        "surface_policy": "Gold Build promotes only repaired, verified books. Repair-limited candidates stay visible as Gold Build Repair Queue items with blockers, repair actions, and next actions.",
    }


def _build_navigation_backlog_bucket(root: Path) -> dict[str, Any]:
    asset_path = root / "data" / "wiki_relations" / "navigation_backlog.json"
    asset = _safe_read_json(asset_path)
    entries = asset.get("entries") if isinstance(asset.get("entries"), list) else []
    books: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        signal_id = str(entry.get("signal_id") or "").strip()
        label = str(entry.get("label") or signal_id or "Backlog Signal").strip()
        signal_type = str(entry.get("signal_type") or "unknown").strip()
        href = str(entry.get("href") or "").strip()
        books.append(
            {
                "book_slug": signal_id or label.lower().replace(" ", "-"),
                "title": label,
                "grade": "Navigation Backlog",
                "review_status": signal_type,
                "source_type": "chat_navigation_signal",
                "source_lane": "wiki_navigation_backlog",
                "section_count": _safe_int(entry.get("count")),
                "code_block_count": 0,
                "viewer_path": href,
                "source_url": str(asset_path.resolve()),
                "updated_at": str(asset.get("generated_at") or ""),
            }
        )
    return {
        "selected_dir": str((root / "data" / "wiki_relations").resolve()),
        "books": books,
        "manifest_path": str(asset_path.resolve()),
    }


def _build_wiki_usage_signal_bucket(root: Path) -> dict[str, Any]:
    payload = build_wiki_overlay_signal_payload(root)
    top_targets = payload.get("top_targets") if isinstance(payload.get("top_targets"), list) else []
    books: list[dict[str, Any]] = []
    for index, entry in enumerate(top_targets):
        if not isinstance(entry, dict):
            continue
        target_ref = str(entry.get("target_ref") or "").strip()
        title = str(entry.get("title") or target_ref or f"signal-{index + 1}").strip()
        kind = str(entry.get("primary_kind") or entry.get("target_kind") or "signal").strip()
        books.append(
            {
                "book_slug": target_ref.replace(":", "-").replace("#", "-") or f"signal-{index + 1}",
                "title": title,
                "grade": "Wiki Usage Signal",
                "review_status": f"{kind} · {int(entry.get('count') or 0)}",
                "source_type": "wiki_user_overlay_signal",
                "source_lane": "wiki_usage_signals",
                "section_count": int(entry.get("count") or 0),
                "code_block_count": int(entry.get("user_count") or 0),
                "viewer_path": str(entry.get("viewer_path") or ""),
                "source_url": "",
                "updated_at": str(entry.get("last_touched_at") or payload.get("updated_at") or ""),
            }
        )
    runtime_dir = load_settings(root).runtime_dir / "wiki_overlays"
    return {
        "selected_dir": str(runtime_dir.resolve()),
        "books": books,
        "manifest_path": str((runtime_dir / "overlays.json").resolve()),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
    }


def _build_product_gate_bucket(root: Path) -> dict[str, Any]:
    scorecard_path = root / "PRODUCT_GATE_SCORECARD.yaml"
    scorecard = _safe_read_yaml(scorecard_path)
    promotion_gate = (
        scorecard.get("promotion_gate", {}).get("full_sale_requires", [])
        if isinstance(scorecard.get("promotion_gate"), dict)
        else []
    )
    release_blockers = scorecard.get("release_blockers", [])
    scenario_set = scorecard.get("scenario_set", [])

    books = [
        {
            "book_slug": "product_gate__promotion",
            "title": "Full-Sale Promotion Gate",
            "grade": "Gate",
            "review_status": "locked",
            "source_type": "scorecard_gate",
            "source_lane": "product_gate",
            "section_count": len(promotion_gate),
            "code_block_count": 0,
            "viewer_path": "",
            "source_url": str(scorecard_path.resolve()),
            "updated_at": _iso_now(),
            "boundary_badge": "Promotion Gate",
            "runtime_truth_label": f"{len(promotion_gate)} release requirements",
            "approval_state": "full_sale",
            "publication_state": "criteria",
        },
        {
            "book_slug": "product_gate__blockers",
            "title": "Release Blockers",
            "grade": "Gate",
            "review_status": "blocking",
            "source_type": "scorecard_gate",
            "source_lane": "product_gate",
            "section_count": len(release_blockers),
            "code_block_count": 0,
            "viewer_path": "",
            "source_url": str(scorecard_path.resolve()),
            "updated_at": _iso_now(),
            "boundary_badge": "Blockers",
            "runtime_truth_label": f"{len(release_blockers)} hard blockers",
            "approval_state": "release",
            "publication_state": "blocking",
        },
        {
            "book_slug": "product_gate__scenarios",
            "title": "Product Gate Scenarios",
            "grade": "Gate",
            "review_status": "scored",
            "source_type": "scorecard_gate",
            "source_lane": "product_gate",
            "section_count": len(scenario_set),
            "code_block_count": 0,
            "viewer_path": "",
            "source_url": str(scorecard_path.resolve()),
            "updated_at": _iso_now(),
            "boundary_badge": "Product Gate",
            "runtime_truth_label": f"{len(scenario_set)} product scenarios",
            "approval_state": "product_gate",
            "publication_state": str(scorecard.get("current_stage") or "paid_poc_candidate"),
        },
    ]
    return {
        "selected_dir": str(scorecard_path.resolve()),
        "books": books,
        "manifest_path": str(scorecard_path.resolve()),
        "summary": {
            "promotion_requirement_count": len(promotion_gate),
            "release_blocker_count": len(release_blockers),
            "scenario_count": len(scenario_set),
            "current_stage": str(scorecard.get("current_stage") or ""),
        },
    }


def _build_product_rehearsal_summary(root: Path) -> dict[str, Any]:
    report_path = root / "reports" / "build_logs" / "product_rehearsal_report.json"
    payload = _safe_read_json(report_path)
    pass_rate = _safe_float(payload.get("critical_scenario_pass_rate"))
    return {
        "report_path": str(report_path.resolve()),
        "exists": report_path.exists() and bool(payload),
        "status": str(payload.get("status") or ("missing" if not payload else "unknown")),
        "current_stage": str(payload.get("current_stage") or ""),
        "scenario_count": _safe_int(payload.get("scenario_count")),
        "pass_count": _safe_int(payload.get("pass_count")),
        "critical_scenario_pass_rate": pass_rate,
        "blockers": list(payload.get("blockers") or []),
    }


def _build_buyer_packet_bundle_bucket(root: Path) -> dict[str, Any]:
    bundle_path = root / "reports" / "build_logs" / "buyer_packet_bundle_index.json"
    payload = _safe_read_json(bundle_path)
    packets = payload.get("packets") if isinstance(payload.get("packets"), list) else []
    books: list[dict[str, Any]] = []
    for entry in packets:
        if not isinstance(entry, dict):
            continue
        packet_id = str(entry.get("id") or "").strip()
        books.append(
            {
                "book_slug": f"buyer_packet__{packet_id}",
                "title": str(entry.get("title") or packet_id),
                "grade": "Packet",
                "review_status": "ready" if str(entry.get("status") or "") == "ok" else "pending",
                "source_type": "buyer_packet_bundle",
                "source_lane": "buyer_packet_bundle",
                "section_count": 1,
                "code_block_count": 0,
                "viewer_path": f"/buyer-packets/{packet_id}",
                "source_url": str(entry.get("markdown_path") or ""),
                "updated_at": _iso_now(),
                "boundary_badge": "Release Packet",
                "runtime_truth_label": str(entry.get("purpose") or ""),
                "approval_state": str(payload.get("current_stage") or ""),
                "publication_state": "ready" if str(entry.get("status") or "") == "ok" else "pending",
            }
        )
    return {
        "selected_dir": str(bundle_path.resolve()),
        "books": books,
        "manifest_path": str(bundle_path.resolve()),
        "summary": {
            "packet_count": len(books),
            "all_ready": bool(payload.get("all_ready")),
        },
    }


def _build_release_candidate_freeze_summary(root: Path) -> dict[str, Any]:
    freeze_path = root / "reports" / "build_logs" / "release_candidate_freeze_packet.json"
    payload = _safe_read_json(freeze_path)
    runtime_snapshot = payload.get("runtime_snapshot") if isinstance(payload.get("runtime_snapshot"), dict) else {}
    product_gate = payload.get("product_gate") if isinstance(payload.get("product_gate"), dict) else {}
    release_gate = payload.get("release_gate") if isinstance(payload.get("release_gate"), dict) else {}
    product_gate_pass_rate = _safe_float(
        product_gate.get("pass_rate")
        if "pass_rate" in product_gate
        else product_gate.get("critical_scenario_pass_rate")
    )
    return {
        "packet_id": "release-candidate-freeze",
        "title": str(payload.get("title") or "Release Candidate Freeze Packet"),
        "viewer_path": "/buyer-packets/release-candidate-freeze",
        "freeze_date": str(payload.get("freeze_date") or ""),
        "current_stage": str(payload.get("current_stage") or ""),
        "commercial_truth": str(payload.get("commercial_truth") or ""),
        "runtime_count": _safe_int(runtime_snapshot.get("runtime_count")),
        "active_group": str(runtime_snapshot.get("active_group") or ""),
        "product_gate_pass_rate": product_gate_pass_rate,
        "product_gate_pass_count": _safe_int(product_gate.get("pass_count")),
        "product_gate_scenario_count": _safe_int(product_gate.get("scenario_count")),
        "promotion_gate_count": _safe_int(release_gate.get("promotion_gate_count")),
        "release_blocker_count": _safe_int(release_gate.get("release_blocker_count")),
        "sell_now": str(release_gate.get("sell_now") or ""),
        "do_not_sell_yet": str(release_gate.get("do_not_sell_yet") or ""),
        "close": str(payload.get("close") or ""),
        "exists": freeze_path.exists() and bool(payload),
        "report_path": str(freeze_path.resolve()),
    }


__all__ = [
    "_build_approved_wiki_runtime_book_bucket",
    "_build_product_gate_bucket",
    "_build_buyer_packet_bundle_bucket",
    "_build_gold_candidate_book_bucket",
    "_build_navigation_backlog_bucket",
    "_build_product_rehearsal_summary",
    "_build_release_candidate_freeze_summary",
    "_build_wiki_usage_signal_bucket",
    "_iso_now",
    "_safe_int",
    "_safe_read_json",
    "_safe_read_yaml",
]
