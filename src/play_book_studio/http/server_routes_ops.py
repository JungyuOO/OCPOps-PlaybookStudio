from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.http.customer_pack_read_boundary import (
    blocked_customer_pack_draft_ids_from_payload,
    sanitize_debug_chat_log_entry,
)
from play_book_studio.http.data_control_room import build_data_control_room_payload
from play_book_studio.http.data_control_room_detail import (
    build_data_control_room_chunk_payload,
)
from play_book_studio.http.server_routes_customer_pack import (
    _customer_pack_read_allowed,
    _send_customer_pack_read_blocked,
)
from play_book_studio.http.repository_registry import (
    list_repository_favorites as _list_repository_favorites,
    remove_repository_favorite as _remove_repository_favorite,
    save_repository_favorites as _save_repository_favorites,
    search_github_issues_prs as _search_github_issues_prs,
    search_github_repositories as _search_github_repositories,
)
from play_book_studio.http.sessions import ChatSession, RUNTIME_CHAT_MODE
from play_book_studio.http.server_routes_viewer import (
    _viewer_source_meta as _viewer_source_meta_payload,
    resolve_viewer_html as _resolve_viewer_html,
)
from play_book_studio.http.wiki_user_overlay import (
    build_wiki_overlay_signal_payload as _build_wiki_overlay_signal_payload,
    list_wiki_user_overlays as _list_wiki_user_overlays,
    remove_wiki_user_overlay as _remove_wiki_user_overlay,
    save_wiki_user_overlay as _save_wiki_user_overlay,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.db.official_documents import load_official_manifest_entries
from play_book_studio.ingestion.manifest import (
    _source_fingerprint,
    read_manifest,
    write_manifest,
)
from play_book_studio.ingestion.models import (
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    SOURCE_STATE_PUBLISHED_NATIVE,
    SourceManifestEntry,
)
from play_book_studio.ingestion.source_first import (
    derive_official_docs_legal_notice_url,
    derive_official_docs_license_or_terms,
    source_mirror_root,
)
from play_book_studio.ingestion.translation_draft_generation import (
    _source_repo_runtime_entry,
    generate_translation_drafts,
)
from play_book_studio.ingestion.translation_gold_promotion import promote_translation_gold
from play_book_studio.retrieval.book_adjustments import query_book_adjustments
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.query_terms import normalize_query
from play_book_studio.source_discovery import (
    SOURCE_LANE_COMMUNITY_TROUBLESHOOTING,
    SOURCE_LANE_OFFICIAL_ISSUE_PR,
    SOURCE_LANE_OFFICIAL_MANUAL,
    SOURCE_LANE_OFFICIAL_SOURCE_REPO,
    SOURCE_LANE_UNSAFE_UNVERIFIED,
    SOURCE_LANE_VENDOR_KB,
    build_source_discovery_plan_from_payload,
    build_source_discovery_plan_response,
    list_source_discovery_judge_reports,
    list_verification_queue,
    save_source_discovery_judge_report,
    save_verification_candidate,
    source_lane_policy,
)


_QUERY_TOKEN_RE = re.compile(r"[^\w가-힣]+", re.UNICODE)


def _safe_read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_entries(path: Path | None) -> list[dict[str, Any]]:
    payload = _safe_read_json_object(path)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    return [dict(item) for item in entries if isinstance(item, dict)]


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
    if Path(normalized).suffix:
        return normalized
    return f"{normalized.rstrip('/')}/index.adoc"


def _repo_blob_href(*, repo_url: str, branch: str, relative_path: str) -> str:
    repo = str(repo_url or "").strip().rstrip("/")
    path = _normalize_repo_relative_path(relative_path)
    branch_name = str(branch or "").strip() or "main"
    if not repo or not path:
        return ""
    return f"{repo}/blob/{branch_name}/{path}"


def _search_query_tokens(query: str) -> list[str]:
    tokens = [
        token
        for token in _QUERY_TOKEN_RE.split(str(query or "").lower())
        if token and len(token) > 1
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _official_candidate_source_payload(entry: dict[str, Any], settings: Any) -> dict[str, Any]:
    slug = str(entry.get("book_slug") or "").strip()
    current_source_url = _first_nonempty(entry.get("source_url"), entry.get("resolved_source_url"))
    homepage_url = _first_nonempty(
        current_source_url if "docs.redhat.com" in current_source_url else "",
        settings.book_url_template.format(slug=slug) if slug else "",
    )
    repo_relative_path = _first_nonempty(
        entry.get("source_relative_path"),
        *(entry.get("source_relative_paths") or []),
    )
    repo_url = _first_nonempty(entry.get("source_repo"))
    repo_branch = _first_nonempty(entry.get("source_branch"), f"enterprise-{settings.ocp_version}")
    repo_href = _first_nonempty(
        current_source_url if "github.com" in current_source_url else "",
        _repo_blob_href(repo_url=repo_url, branch=repo_branch, relative_path=repo_relative_path),
    )
    primary_input_kind = _first_nonempty(entry.get("primary_input_kind"))
    source_kind = _first_nonempty(entry.get("source_kind"))
    current_basis = "unknown"
    if "github.com" in current_source_url or primary_input_kind == "source_repo" or source_kind == "source-first":
        current_basis = "official_repo"
    elif "docs.redhat.com" in current_source_url or primary_input_kind == "html_single" or source_kind == "html-single":
        current_basis = "official_homepage"
    elif repo_href and not homepage_url:
        current_basis = "official_repo"
    elif homepage_url and not repo_href:
        current_basis = "official_homepage"
    current_label = {
        "official_homepage": "공식 홈페이지 기준",
        "official_repo": "공식 레포 기준",
    }.get(current_basis, "원천 기준 미기록")
    return {
        "current_source_basis": current_basis,
        "current_source_label": current_label,
        "source_options": [
            {
                "key": "official_homepage",
                "label": "공식 홈페이지",
                "href": homepage_url,
                "availability": "available" if homepage_url else "missing",
                "note": "공식 KO published manual",
                "is_current": current_basis == "official_homepage",
            },
            {
                "key": "official_repo",
                "label": "공식 레포",
                "href": repo_href,
                "availability": "available" if repo_href else "missing",
                "note": "공식 AsciiDoc 원천",
                "is_current": current_basis == "official_repo",
            },
        ],
    }


def _candidate_match_score(query: str, entry: dict[str, Any]) -> int:
    normalized_query = " ".join(str(query or "").strip().lower().split())
    if not normalized_query:
        return 0
    slug = str(entry.get("book_slug") or "").strip().lower()
    slug_label = slug.replace("_", " ").replace("-", " ")
    title = str(entry.get("title") or "").strip().lower()
    source_relative_path = _first_nonempty(entry.get("source_relative_path"), *(entry.get("source_relative_paths") or [])).lower()
    source_url = str(entry.get("source_url") or "").strip().lower()
    haystack = " ".join([slug, slug_label, title, source_relative_path, source_url])
    tokens = _search_query_tokens(normalized_query)
    if not tokens:
        return 0
    score = 0
    if normalized_query in title or normalized_query in slug_label or normalized_query in slug:
        score += 100
    for token in tokens:
        if token in title:
            score += 25
        elif token in slug_label or token in slug:
            score += 18
        elif token in source_relative_path:
            score += 10
        elif token in haystack:
            score += 6
    return score


_TROUBLESHOOTING_QUERY_TERMS = (
    "troubleshoot",
    "troubleshooting",
    "debug",
    "error",
    "failure",
    "failed",
    "timeout",
    "crashloopbackoff",
    "imagepullbackoff",
    "장애",
    "오류",
    "에러",
    "실패",
    "복구",
    "원인",
    "해결",
    "문제",
)


def _candidate_domain_adjustment(query: str, entry: dict[str, Any]) -> int:
    normalized_query = normalize_query(query)
    if not normalized_query or not any(term in normalized_query for term in _TROUBLESHOOTING_QUERY_TERMS):
        return 0
    slug = str(entry.get("book_slug") or "").strip().lower()
    slug_label = slug.replace("_", " ").replace("-", " ")
    title = str(entry.get("title") or "").strip().lower()
    source_relative_path = _first_nonempty(entry.get("source_relative_path"), *(entry.get("source_relative_paths") or [])).lower()
    haystack = " ".join([slug, slug_label, title, source_relative_path])
    if "validation_and_troubleshooting" in slug or "troubleshoot" in haystack or "문제 해결" in haystack:
        return 90
    if slug == "support" or "지원" in title or "/support" in source_relative_path:
        return 45
    if "image" in normalized_query and ("image" in haystack or "이미지" in haystack):
        return 35
    if "route" in normalized_query and ("route" in haystack or "라우트" in haystack or "ingress" in haystack):
        return 30
    return 0


def _candidate_book_adjustment_scores(query: str) -> dict[str, int]:
    normalized_query = normalize_query(query)
    if not normalized_query:
        return {}
    try:
        boosts, _penalties = query_book_adjustments(normalized_query, context=SessionContext())
    except Exception:  # noqa: BLE001
        return {}
    scores: dict[str, int] = {}
    for slug, boost in boosts.items():
        if boost < 1.5:
            continue
        scores[str(slug)] = int(min(96, max(12, round((float(boost) - 1.0) * 60))))
    return scores


def _official_candidate_manifest_paths(root_dir: Path, settings: Any) -> tuple[Path, ...]:
    manifest_dir = settings.manifest_dir
    prefix = settings.active_pack.manifest_prefix
    candidates = [
        manifest_dir / f"{prefix}_translated_ko_draft_all_runtime.json",
        settings.translation_draft_manifest_path,
        settings.source_manifest_path,
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique)


def _manifest_entry_by_slug(path: Path | None) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for entry in _manifest_entries(path):
        slug = str(entry.get("book_slug") or "").strip()
        if slug:
            rows[slug] = entry
    return rows


def _official_db_entries(settings: Any) -> list[dict[str, Any]]:
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        return []
    return load_official_manifest_entries(database_url)


def _official_db_entries_by_slug(settings: Any) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("book_slug") or "").strip(): entry
        for entry in _official_db_entries(settings)
        if str(entry.get("book_slug") or "").strip()
    }


def _is_empty_official_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_official_candidate_entry(primary: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(fallback or {})
    for key, value in primary.items():
        if _is_empty_official_value(value) and key in merged:
            continue
        merged[key] = value
    return merged


def _official_candidate_entries_by_slug(root_dir: Path, settings: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in _official_candidate_manifest_paths(root_dir, settings):
        for entry in _manifest_entries(path):
            slug = str(entry.get("book_slug") or "").strip()
            if slug and slug not in rows:
                rows[slug] = entry
    return rows


def _official_source_candidate_row(
    *,
    slug: str,
    entry: dict[str, Any],
    settings: Any,
    status_kind: str,
    status_label: str,
    match_score: int,
) -> dict[str, Any]:
    source_payload = _official_candidate_source_payload(entry, settings)
    return {
        "book_slug": slug,
        "title": str(entry.get("title") or slug),
        "viewer_path": str(entry.get("viewer_path") or settings.viewer_path_template.format(slug=slug)),
        "source_relative_path": _first_nonempty(
            entry.get("source_relative_path"),
            *(entry.get("source_relative_paths") or []),
        ),
        "source_repo": str(entry.get("source_repo") or "").strip(),
        "source_kind": str(entry.get("source_kind") or "").strip(),
        "status_kind": status_kind,
        "status_label": status_label,
        "match_score": match_score,
        **source_payload,
    }


def _search_official_source_candidates(root_dir: Path, *, query: str, limit: int = 8) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    db_entries_by_slug = _official_db_entries_by_slug(settings) if str(getattr(settings, "database_url", "") or "").strip() else {}
    manifest_entries_by_slug = _official_candidate_entries_by_slug(root_dir, settings)
    live_entries_by_slug = db_entries_by_slug or _manifest_entry_by_slug(settings.source_manifest_path)
    adjustment_scores = _candidate_book_adjustment_scores(query)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for slug in sorted(set(manifest_entries_by_slug) | set(live_entries_by_slug)):
        live_entry = live_entries_by_slug.get(slug)
        manifest_entry = manifest_entries_by_slug.get(slug)
        entry = _merge_official_candidate_entry(live_entry or {}, manifest_entry) if live_entry else dict(manifest_entry or {})
        score = _candidate_match_score(query, entry) + adjustment_scores.get(slug, 0) + _candidate_domain_adjustment(query, entry)
        if score > 0:
            ranked.append((score, slug, entry))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    rows: list[dict[str, Any]] = []
    for score, slug, entry in ranked[: max(1, min(limit, 12))]:
        is_live = slug in live_entries_by_slug
        rows.append(
            _official_source_candidate_row(
                slug=slug,
                entry=entry,
                settings=settings,
                status_kind="live" if is_live else "candidate",
                status_label="available_in_postgres" if slug in db_entries_by_slug else "이미 Library에 있음" if is_live else "생산 후보",
                match_score=score,
            )
        )
    return rows


def _list_official_source_catalog(root_dir: Path) -> dict[str, Any]:
    settings = load_settings(root_dir)
    db_entries_by_slug = _official_db_entries_by_slug(settings) if str(getattr(settings, "database_url", "") or "").strip() else {}
    manifest_entries_by_slug = _official_candidate_entries_by_slug(root_dir, settings)
    live_entries_by_slug = db_entries_by_slug or _manifest_entry_by_slug(settings.source_manifest_path)
    rows: list[dict[str, Any]] = []
    for slug in sorted(set(manifest_entries_by_slug) | set(live_entries_by_slug)):
        live_entry = live_entries_by_slug.get(slug)
        manifest_entry = manifest_entries_by_slug.get(slug)
        resolved_entry = _merge_official_candidate_entry(live_entry or {}, manifest_entry) if live_entry else dict(manifest_entry or {})
        is_live = slug in live_entries_by_slug
        rows.append(
            _official_source_candidate_row(
                slug=slug,
                entry=resolved_entry,
                settings=settings,
                status_kind="live" if is_live else "candidate",
                status_label="available_in_postgres" if slug in db_entries_by_slug else "이미 Library에 있음" if is_live else "아직 없음",
                match_score=0,
            )
        )
    rows.sort(key=lambda item: (str(item.get("status_kind") or "") != "live", str(item.get("title") or "").lower(), str(item.get("book_slug") or "").lower()))
    live_count = sum(1 for row in rows if str(row.get("status_kind") or "") == "live")
    return {
        "source": "postgres_and_candidate_manifests" if db_entries_by_slug else "ocp_4_20_all_runtime_catalog",
        "total_count": len(rows),
        "live_count": live_count,
        "candidate_count": max(len(rows) - live_count, 0),
        "rows": rows,
    }


def _official_materialize_manifest_dir(root_dir: Path) -> Path:
    return root_dir / "tmp" / "book_factory_official_materialize"


def _official_materialize_manifest_path(root_dir: Path, *, slug: str, source_basis: str) -> Path:
    safe_slug = slug.strip().replace("/", "_").replace("\\", "_")
    safe_basis = source_basis.strip().replace("/", "_")
    return _official_materialize_manifest_dir(root_dir) / f"{safe_slug}.{safe_basis}.manifest.json"


def _official_materialize_report_path(root_dir: Path, *, slug: str, source_basis: str) -> Path:
    safe_slug = slug.strip().replace("/", "_").replace("\\", "_")
    safe_basis = source_basis.strip().replace("/", "_")
    return root_dir / "reports" / "build_logs" / f"book_factory_{safe_slug}_{safe_basis}.json"


def _candidate_seed_entry(root_dir: Path, *, slug: str) -> SourceManifestEntry:
    settings = load_settings(root_dir)
    for path in _official_candidate_manifest_paths(root_dir, settings):
        for entry in read_manifest(path):
            if entry.book_slug == slug:
                return entry
    raise ValueError(f"official source candidate not found for {slug}")


def _official_homepage_entry(seed: SourceManifestEntry, *, root_dir: Path) -> SourceManifestEntry:
    settings = load_settings(root_dir)
    source_payload = _official_candidate_source_payload(seed.to_dict(), settings)
    homepage_url = _first_nonempty(
        next(
            (
                option.get("href")
                for option in source_payload.get("source_options", [])
                if isinstance(option, dict) and str(option.get("key") or "").strip() == "official_homepage"
            ),
            "",
        ),
        settings.book_url_template.format(slug=seed.book_slug),
    )
    if not homepage_url:
        raise ValueError(f"official homepage source missing for {seed.book_slug}")
    payload = {
        **seed.to_dict(),
        "source_kind": "html-single",
        "source_url": homepage_url,
        "resolved_source_url": homepage_url,
        "source_lane": "official_ko",
        "source_state": SOURCE_STATE_PUBLISHED_NATIVE,
        "source_state_reason": "official_ko_published_surface_selected_in_book_factory",
        "content_status": CONTENT_STATUS_APPROVED_KO,
        "citation_eligible": True,
        "citation_block_reason": "",
        "approval_status": "approved",
        "approval_state": "approved",
        "publication_state": "published",
        "review_status": "approved",
        "resolved_language": "ko",
        "body_language_guess": "ko",
        "fallback_detected": False,
        "primary_input_kind": "html_single",
        "fallback_input_kind": "",
        "translation_source_language": "ko",
        "translation_target_language": "ko",
        "translation_source_url": homepage_url,
        "translation_source_fingerprint": "",
        "translation_stage": CONTENT_STATUS_APPROVED_KO,
        "legal_notice_url": str(seed.legal_notice_url or derive_official_docs_legal_notice_url(seed)).strip(),
        "license_or_terms": str(
            seed.license_or_terms
            or derive_official_docs_license_or_terms(seed, legal_notice_url=str(seed.legal_notice_url or ""))
        ).strip(),
    }
    payload["source_fingerprint"] = _source_fingerprint(
        product_slug=str(payload.get("product_slug") or seed.product_slug),
        ocp_version=str(payload.get("ocp_version") or seed.ocp_version),
        docs_language=str(payload.get("docs_language") or seed.docs_language),
        source_kind=str(payload.get("source_kind") or "html-single"),
        book_slug=str(payload.get("book_slug") or seed.book_slug),
        source_url=str(payload.get("source_url") or ""),
        resolved_source_url=str(payload.get("resolved_source_url") or ""),
        viewer_path=str(payload.get("viewer_path") or seed.viewer_path),
        resolved_language=str(payload.get("resolved_language") or "ko"),
        source_relative_path="",
        primary_input_kind="html_single",
    )
    return SourceManifestEntry(**payload)


def _official_repo_entry(seed: SourceManifestEntry, *, root_dir: Path) -> SourceManifestEntry:
    settings = load_settings(root_dir)
    runtime_seed = SourceManifestEntry(
        **{
            **seed.to_dict(),
            "source_mirror_root": str(source_mirror_root(settings.root_dir)),
        }
    )
    runtime_entry, _source_paths = _source_repo_runtime_entry(settings, runtime_seed)
    return runtime_entry


def _official_source_entry(root_dir: Path, *, slug: str, source_basis: str) -> SourceManifestEntry:
    seed = _candidate_seed_entry(root_dir, slug=slug)
    basis = str(source_basis or "").strip()
    if basis == "official_homepage":
        return _official_homepage_entry(seed, root_dir=root_dir)
    if basis == "official_repo":
        return _official_repo_entry(seed, root_dir=root_dir)
    raise ValueError("source_basis must be official_homepage or official_repo")


def _official_source_smoke(root_dir: Path, *, viewer_path: str, slug: str) -> dict[str, Any]:
    settings = load_settings(root_dir)
    approved_entries = read_manifest(settings.source_manifest_path) if settings.source_manifest_path.exists() else []
    approved_entry = next((entry for entry in approved_entries if entry.book_slug == slug), None)
    viewer_html = _resolve_viewer_html(root_dir, viewer_path)
    source_meta = _viewer_source_meta_payload(root_dir, viewer_path)
    return {
        "approved_manifest_present": approved_entry is not None,
        "approved_manifest_count": len(approved_entries),
        "approved_source_kind": str(approved_entry.source_kind if approved_entry is not None else ""),
        "approved_source_url": str(approved_entry.source_url if approved_entry is not None else ""),
        "approved_source_lane": str(approved_entry.source_lane if approved_entry is not None else ""),
        "viewer_ready": bool(str(viewer_html or "").strip()),
        "source_meta_ready": bool(source_meta),
        "viewer_path": viewer_path,
    }


def _materialize_official_source(root_dir: Path, *, slug: str, source_basis: str) -> dict[str, Any]:
    settings = load_settings(root_dir)
    entry = _official_source_entry(root_dir, slug=slug, source_basis=source_basis)
    manifest_path = _official_materialize_manifest_path(root_dir, slug=slug, source_basis=source_basis)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest_path, [entry])
    generation_report = generate_translation_drafts(
        settings,
        slugs=[slug],
        force_collect=source_basis == "official_homepage",
        force_regenerate=True,
        manifest_path=manifest_path,
    )
    promotion_report = promote_translation_gold(
        settings,
        slugs=[slug],
        generate_first=False,
        sync_qdrant=True,
        refresh_synthesis_report=True,
        manifest_path=manifest_path,
    )
    smoke = _official_source_smoke(root_dir, viewer_path=entry.viewer_path, slug=slug)
    if not (smoke.get("approved_manifest_present") and smoke.get("viewer_ready") and smoke.get("source_meta_ready")):
        raise RuntimeError(f"post-switch smoke failed for {slug}")
    report = {
        "book_slug": slug,
        "source_basis": source_basis,
        "source_label": "공식 홈페이지 기준" if source_basis == "official_homepage" else "공식 레포 기준",
        "title": entry.title,
        "viewer_path": entry.viewer_path,
        "request_manifest_path": str(manifest_path.resolve()),
        "draft_summary": generation_report.get("summary", {}),
        "gold_summary": promotion_report.get("summary", {}),
        "smoke": smoke,
    }
    report_path = _official_materialize_report_path(root_dir, slug=slug, source_basis=source_basis)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path.resolve())
    return report


def _list_unanswered_questions(root_dir: Path, *, limit: int = 20) -> dict[str, Any]:
    settings = load_settings(root_dir)
    target = settings.unanswered_questions_path
    if not target.exists():
        return {"count": 0, "items": []}
    rows: list[dict[str, Any]] = []
    row_by_query: dict[str, dict[str, Any]] = {}

    def merge_unanswered_row(existing: dict[str, Any], older: dict[str, Any]) -> None:
        for key in ("rewritten_query", "failure_reason", "source_request_origin", "status"):
            if not str(existing.get(key) or "").strip() and str(older.get(key) or "").strip():
                existing[key] = older[key]
        existing_warnings = [str(item) for item in (existing.get("warnings") or []) if str(item).strip()]
        for warning in [str(item) for item in (older.get("warnings") or []) if str(item).strip()]:
            if warning not in existing_warnings:
                existing_warnings.append(warning)
        existing["warnings"] = existing_warnings

    for line in reversed(target.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(payload.get("record_kind") or "") != "unanswered_question":
            continue
        query = str(payload.get("query") or "").strip()
        if not query:
            continue
        row = {
            "query": query,
            "rewritten_query": str(payload.get("rewritten_query") or "").strip(),
            "timestamp": str(payload.get("timestamp") or "").strip(),
            "response_kind": str(payload.get("response_kind") or "").strip(),
            "failure_reason": str(payload.get("failure_reason") or "").strip(),
            "source_request_origin": str(payload.get("source_request_origin") or "").strip(),
            "status": str(payload.get("status") or "queued").strip() or "queued",
            "warnings": [str(item) for item in (payload.get("warnings") or []) if str(item).strip()],
        }
        existing = row_by_query.get(query)
        if existing is not None:
            merge_unanswered_row(existing, row)
            continue
        if len(rows) >= max(1, limit):
            continue
        rows.append(row)
        row_by_query[query] = row
    return {"count": len(rows), "items": rows}


def _save_repository_source_request(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or payload.get("repository_query") or "").strip()
    if not query:
        raise ValueError("query가 필요합니다.")
    warnings = payload.get("warnings")
    warning_rows = [str(item) for item in warnings if str(item).strip()] if isinstance(warnings, list) else []
    record = {
        "record_kind": "unanswered_question",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": str(payload.get("session_id") or "").strip(),
        "query": query,
        "rewritten_query": str(payload.get("rewritten_query") or query).strip(),
        "response_kind": str(payload.get("response_kind") or "manual_source_request").strip() or "manual_source_request",
        "failure_reason": str(payload.get("failure_reason") or "user_requested_source_enrichment").strip(),
        "source_request_origin": str(payload.get("source_request_origin") or "chat_acquisition").strip(),
        "status": str(payload.get("status") or "queued").strip() or "queued",
        "warnings": warning_rows,
    }
    settings = load_settings(root_dir)
    target = settings.unanswered_questions_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def handle_sessions_list(handler: Any, query: str, *, store: Any) -> None:
    params = parse_qs(query, keep_blank_values=False)
    limit_raw = str((params.get("limit") or ["50"])[0]).strip()
    try:
        limit = max(1, min(200, int(limit_raw)))
    except ValueError:
        limit = 50
    summaries = store.list_summaries(limit=limit)
    handler._send_json({"sessions": summaries, "count": len(summaries)})


def handle_session_load(handler: Any, query: str, *, store: Any) -> None:
    params = parse_qs(query, keep_blank_values=False)
    session_id = str((params.get("session_id") or [""])[0]).strip()
    if not session_id:
        handler._send_json({"error": "session_id is required"}, HTTPStatus.BAD_REQUEST)
        return
    session = store.peek(session_id)
    if session is None:
        handler._send_json({"error": "Session not found"}, HTTPStatus.NOT_FOUND)
        return
    from play_book_studio.http.sessions import serialize_session_snapshot

    payload = serialize_session_snapshot(session)
    blocked = blocked_customer_pack_draft_ids_from_payload(Path(store._root_dir or "."), payload)
    if blocked:
        handler._send_json({"error": "Session not found"}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(payload)


def handle_session_delete(handler: Any, payload: dict[str, Any], *, store: Any) -> None:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        handler._send_json({"error": "session_id is required"}, HTTPStatus.BAD_REQUEST)
        return
    deleted = bool(store.delete(session_id))
    if not deleted:
        handler._send_json({"error": "Session not found"}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json({"success": True, "session_id": session_id})


def handle_sessions_delete_all(handler: Any, payload: dict[str, Any], *, store: Any) -> None:
    del payload
    deleted_count = int(store.delete_all())
    handler._send_json({"success": True, "deleted_count": deleted_count})


def handle_debug_session(handler: Any, query: str, *, store: Any, build_session_debug_payload: Any) -> None:
    params = parse_qs(query, keep_blank_values=False)
    session_id = str((params.get("session_id") or [""])[0]).strip()
    session = store.peek(session_id) if session_id else store.latest()
    if session is None:
        handler._send_json({"error": "조회할 세션이 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    payload = build_session_debug_payload(session)
    blocked = blocked_customer_pack_draft_ids_from_payload(Path(store._root_dir or "."), payload)
    if blocked:
        handler._send_json({"error": "조회할 세션이 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(payload)


def handle_debug_chat_log(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    limit_raw = str((params.get("limit") or ["20"])[0]).strip()
    try:
        limit = max(1, min(200, int(limit_raw or "20")))
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    log_path = load_settings(root_dir).chat_log_path
    if not log_path.exists():
        handler._send_json({"entries": [], "count": 0})
        return
    lines = log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines[-limit:] if line.strip()]
    sanitized_entries = [
        sanitize_debug_chat_log_entry(entry)
        for entry in entries
        if not blocked_customer_pack_draft_ids_from_payload(root_dir, entry)
    ]
    handler._send_json({"entries": sanitized_entries, "count": len(sanitized_entries)})


def handle_data_control_room(handler: Any, query: str, *, root_dir: Path) -> dict[str, Any]:
    del query
    payload = build_data_control_room_payload(root_dir)
    handler._send_json(payload)
    return payload


def handle_data_control_room_chunks(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    scope = str((params.get("scope") or ["runtime"])[0]).strip()
    book_slug = str((params.get("book_slug") or [""])[0]).strip()
    draft_id = str((params.get("draft_id") or [""])[0]).strip()
    if scope == "customer_pack":
        effective_draft_id = draft_id or (book_slug.split("--", 1)[0].strip() if "--" in book_slug else book_slug)
        if not effective_draft_id or not _customer_pack_read_allowed(root_dir, effective_draft_id):
            _send_customer_pack_read_blocked(handler)
            return
        draft_id = effective_draft_id
    try:
        payload = build_data_control_room_chunk_payload(
            root_dir,
            scope=scope,
            book_slug=book_slug,
            draft_id=draft_id,
        )
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except FileNotFoundError:
        handler._send_json({"error": "chunk detail을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"chunk detail 구성 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(payload)


def handle_buyer_packet(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    packet_id = str((params.get("packet_id") or [""])[0]).strip()
    if not packet_id:
        handler._send_json({"error": "packet_id가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    bundle_path = root_dir / "reports" / "build_logs" / "buyer_packet_bundle_index.json"
    if not bundle_path.exists():
        handler._send_json({"error": "buyer packet bundle이 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    packets = bundle.get("packets") if isinstance(bundle.get("packets"), list) else []
    match = next(
        (
            entry for entry in packets
            if isinstance(entry, dict) and str(entry.get("id") or "").strip() == packet_id
        ),
        None,
    )
    if not isinstance(match, dict):
        handler._send_json({"error": "buyer packet을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    markdown_path = root_dir / str(match.get("markdown_path") or "")
    json_path = root_dir / str(match.get("json_path") or "")
    if not markdown_path.exists():
        handler._send_json({"error": "buyer packet markdown을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(
        {
            "packet_id": packet_id,
            "title": str(match.get("title") or packet_id),
            "purpose": str(match.get("purpose") or ""),
            "status": str(match.get("status") or ""),
            "markdown_path": str(markdown_path.resolve()),
            "json_path": str(json_path.resolve()) if json_path.exists() else "",
            "body": markdown_path.read_text(encoding="utf-8"),
        }
    )


def handle_repository_search(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    search_query = str((params.get("query") or [""])[0]).strip()
    limit_raw = str((params.get("limit") or ["12"])[0]).strip()
    try:
        limit = int(limit_raw or "12")
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    try:
        payload = _search_github_repositories(root_dir, query=search_query, limit=limit)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"repository search 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    payload["official_candidates"] = _search_official_source_candidates(
        root_dir,
        query=search_query,
        limit=min(limit, 8),
    )
    handler._send_json(payload)


def handle_repository_official_catalog(handler: Any, query: str, *, root_dir: Path) -> None:
    del query
    try:
        payload = _list_official_source_catalog(root_dir)
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"official source catalog 구성 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(payload)


def handle_repository_official_materialize(
    handler: Any,
    payload: dict[str, Any],
    *,
    root_dir: Path,
) -> dict[str, Any] | None:
    slug = str(payload.get("book_slug") or "").strip()
    source_basis = str(payload.get("source_basis") or "").strip()
    if not slug:
        handler._send_json({"error": "book_slug가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return None
    if source_basis not in {"official_homepage", "official_repo"}:
        handler._send_json(
            {"error": "source_basis는 official_homepage 또는 official_repo 여야 합니다."},
            HTTPStatus.BAD_REQUEST,
        )
        return None
    try:
        report = _materialize_official_source(root_dir, slug=slug, source_basis=source_basis)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return None
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"official source materialize 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return None
    handler._send_json(report, HTTPStatus.CREATED)
    return report


def handle_repository_unanswered(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    limit_raw = str((params.get("limit") or ["20"])[0]).strip()
    try:
        limit = int(limit_raw or "20")
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(_list_unanswered_questions(root_dir, limit=limit))


def handle_repository_source_request_save(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        item = _save_repository_source_request(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"source request 저장 중 오류가 발생했습니다: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    rows = _list_unanswered_questions(root_dir, limit=20)
    handler._send_json({"success": True, "item": item, **rows}, HTTPStatus.CREATED)


def handle_repository_source_discovery_plan(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    del root_dir
    try:
        response = build_source_discovery_plan_response(payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"source discovery plan 구성 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(response)


def _source_discovery_lane_result(
    *,
    lane: str,
    provider: str,
    query: str,
    status: str,
    items: list[dict[str, Any]] | None = None,
    message: str = "",
    error: str = "",
    filtered_count: int = 0,
    trust_note: str = "",
) -> dict[str, Any]:
    policy = source_lane_policy(lane)
    return {
        "lane": lane,
        "label": str(policy.get("label") or lane),
        "provider": provider,
        "query": query,
        "status": status,
        "count": len(items or []),
        "items": items or [],
        "message": message,
        "error": error,
        "trust_level": str(policy.get("trust_level") or ""),
        "gold_policy": str(policy.get("default_gold_policy") or ""),
        "requires_human_review": bool(policy.get("requires_human_review", False)),
        "filtered_count": max(0, int(filtered_count or 0)),
        "trust_note": trust_note,
    }


_OFFICIAL_GITHUB_SOURCE_OWNERS = frozenset({"openshift"})


def _is_official_github_source_repository(item: dict[str, Any]) -> bool:
    owner = str(item.get("owner_login") or "").strip().lower()
    full_name = str(item.get("full_name") or "").strip().lower()
    if not owner and "/" in full_name:
        owner = full_name.split("/", 1)[0]
    return owner in _OFFICIAL_GITHUB_SOURCE_OWNERS


def _build_repository_source_discovery_search(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    plan = build_source_discovery_plan_from_payload(payload)
    limit = int(payload.get("limit") or 8)
    limit = max(1, min(12, limit))
    lane_results: list[dict[str, Any]] = []
    auth_modes: set[str] = set()
    official_candidates: list[dict[str, Any]] = []
    github_repository_results: list[dict[str, Any]] = []
    github_issue_pr_results: list[dict[str, Any]] = []

    for query in plan.search_queries:
        lane = query.lane
        if lane == SOURCE_LANE_OFFICIAL_MANUAL:
            try:
                items = _search_official_source_candidates(root_dir, query=query.query, limit=limit)
                official_candidates.extend(items)
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="official_catalog",
                        query=query.query,
                        status="ok",
                        items=items,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="official_catalog",
                        query=query.query,
                        status="error",
                        error=str(exc),
                    )
                )
        elif lane == SOURCE_LANE_OFFICIAL_SOURCE_REPO:
            try:
                payload_repo = _search_github_repositories(root_dir, query=query.query, limit=limit)
                raw_items = [dict(item) for item in payload_repo.get("results") or [] if isinstance(item, dict)]
                items = [item for item in raw_items if _is_official_github_source_repository(item)]
                filtered_count = len(raw_items) - len(items)
                for item in items:
                    item["source_trust_label"] = "official_org"
                    item["suggested_category"] = "Official Source Repo"
                auth_modes.add(str(payload_repo.get("auth_mode") or "public"))
                github_repository_results.extend(items)
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="github_repositories",
                        query=str(payload_repo.get("rewritten_query") or query.query),
                        status="ok",
                        items=items,
                        message=(
                            f"비공식/데모 repo {filtered_count}건은 official_source_repo lane에서 제외했습니다."
                            if filtered_count
                            else ""
                        ),
                        filtered_count=filtered_count,
                        trust_note="openshift GitHub org 소속 repo만 official source로 표시합니다.",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="github_repositories",
                        query=query.query,
                        status="error",
                        error=str(exc),
                    )
                )
        elif lane == SOURCE_LANE_OFFICIAL_ISSUE_PR:
            try:
                payload_issue = _search_github_issues_prs(root_dir, query=query.query, limit=limit, official_scope=True)
                items = [dict(item) for item in payload_issue.get("results") or [] if isinstance(item, dict)]
                auth_modes.add(str(payload_issue.get("auth_mode") or "public"))
                github_issue_pr_results.extend(items)
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="github_issues_prs",
                        query=str(payload_issue.get("rewritten_query") or query.query),
                        status="ok",
                        items=items,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                lane_results.append(
                    _source_discovery_lane_result(
                        lane=lane,
                        provider="github_issues_prs",
                        query=query.query,
                        status="error",
                        error=str(exc),
                    )
                )
        elif lane in {SOURCE_LANE_COMMUNITY_TROUBLESHOOTING, SOURCE_LANE_VENDOR_KB}:
            lane_results.append(
                _source_discovery_lane_result(
                    lane=lane,
                    provider="external_search_pending",
                    query=query.query,
                    status="not_configured",
                    message="외부 web/provider 연결 전까지 이 lane은 Bronze 후보 수동 검증 큐로만 표시합니다.",
                )
            )
        elif lane == SOURCE_LANE_UNSAFE_UNVERIFIED:
            lane_results.append(
                _source_discovery_lane_result(
                    lane=lane,
                    provider="manual_review",
                    query=query.query,
                    status="blocked",
                    message="출처 불명 자료는 자동 검색/승격하지 않고 사람 검토 대상으로만 남깁니다.",
                )
            )

    return {
        "success": True,
        "planner_mode": "deterministic_contract_v1",
        "llm_planner_enabled": False,
        "plan": plan.to_dict(),
        "lane_results": lane_results,
        "totals": {
            "lane_count": len(lane_results),
            "official_candidates": len(official_candidates),
            "github_repositories": len(github_repository_results),
            "github_issues_prs": len(github_issue_pr_results),
        },
        "auth_mode": "token" if "token" in auth_modes else "public",
        "official_candidates": official_candidates,
        "github_repository_results": github_repository_results,
        "github_issue_pr_results": github_issue_pr_results,
    }


def handle_repository_source_discovery_search(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        response = _build_repository_source_discovery_search(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"source discovery search 구성 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(response)


def handle_repository_source_discovery_verification_queue(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    limit_raw = str((params.get("limit") or ["50"])[0]).strip()
    try:
        limit = int(limit_raw or "50")
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(list_verification_queue(root_dir, limit=limit))


def handle_repository_source_discovery_verification_save(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        response = save_verification_candidate(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"source verification queue 저장 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(response, HTTPStatus.CREATED if response.get("saved") else HTTPStatus.OK)


def handle_repository_source_discovery_judge_reports(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    limit_raw = str((params.get("limit") or ["20"])[0]).strip()
    try:
        limit = int(limit_raw or "20")
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(list_source_discovery_judge_reports(root_dir, limit=limit))


def _clean_judge_scope_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _verification_record_matches_judge_scope(record: dict[str, Any], *, question: str, candidate_ids: set[str]) -> bool:
    candidate_id = str(record.get("candidate_id") or "").strip()
    if candidate_id and candidate_id in candidate_ids:
        return True
    if not question:
        return False
    record_queries = [
        _clean_judge_scope_text(record.get("source_request_query")),
        _clean_judge_scope_text(record.get("query")),
    ]
    return any(query and (query == question or query in question or question in query) for query in record_queries)


def _scoped_judge_verification_records(root_dir: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    payload_records = [dict(item) for item in (payload.get("verification_records") or []) if isinstance(item, dict)]
    if payload_records:
        return payload_records

    question = _clean_judge_scope_text(payload.get("question") or payload.get("query"))
    candidate_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in (payload.get("source_candidates") or [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    queue_records = [
        dict(item)
        for item in (list_verification_queue(root_dir, limit=50).get("items") or [])
        if isinstance(item, dict)
    ]
    return [
        record
        for record in queue_records
        if _verification_record_matches_judge_scope(record, question=question, candidate_ids=candidate_ids)
    ]


def build_repository_source_discovery_judge_report(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verification_records = []
    if bool(payload.get("include_verification_queue", True)):
        verification_records = _scoped_judge_verification_records(root_dir, payload)
    return save_source_discovery_judge_report(root_dir, payload, verification_records=verification_records)


def handle_repository_source_discovery_judge_save(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        response = build_repository_source_discovery_judge_report(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"source discovery judge 실행 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(response, HTTPStatus.CREATED)


def handle_repository_source_discovery_judge_replay(
    handler: Any,
    payload: dict[str, Any],
    *,
    root_dir: Path,
    current_answerer: Any,
    context_with_request_overrides: Any,
    build_chat_payload: Any,
    owner_user_id: str = "",
) -> None:
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        handler._send_json({"error": "question이 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    try:
        active_answerer = current_answerer()
        session = ChatSession(session_id=f"source-judge-replay-{uuid.uuid4().hex}", mode=RUNTIME_CHAT_MODE)
        scoped_payload = dict(payload)
        if owner_user_id:
            scoped_payload["owner_user_id"] = owner_user_id
        request_context = context_with_request_overrides(
            session.context,
            payload=scoped_payload,
            mode=RUNTIME_CHAT_MODE,
            default_ocp_version=active_answerer.settings.ocp_version,
        )
        session.context = request_context
        result = active_answerer.answer(
            question,
            mode=RUNTIME_CHAT_MODE,
            context=request_context,
            top_k=8,
            candidate_k=20,
            max_context_chunks=6,
        )
        replay_payload = build_chat_payload(
            root_dir=root_dir,
            answerer=active_answerer,
            session=session,
            result=result,
        )
        judge_payload = dict(payload)
        judge_payload["question"] = question
        judge_payload["before_answer"] = str(payload.get("before_answer") or "")
        judge_payload["after_answer"] = str(replay_payload.get("answer") or "")
        judge_payload["citations"] = [
            dict(item)
            for item in (replay_payload.get("citations") or [])
            if isinstance(item, dict)
        ]
        judge_payload["include_verification_queue"] = bool(payload.get("include_verification_queue", True))
        report = build_repository_source_discovery_judge_report(root_dir, judge_payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"source discovery judge replay 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return

    handler._send_json(
        {
            "schema": "source_discovery_judge_replay_v1",
            "question": question,
            "replay": replay_payload,
            "judge_report": report,
        },
        HTTPStatus.CREATED,
    )


def handle_repository_favorites(handler: Any, query: str, *, root_dir: Path) -> None:
    del query
    handler._send_json(_list_repository_favorites(root_dir))


def handle_repository_favorites_save(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        saved = _save_repository_favorites(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(saved, HTTPStatus.CREATED)


def handle_repository_favorites_remove(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        saved = _remove_repository_favorite(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(saved)


def handle_wiki_user_overlays(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    user_id = str((params.get("user_id") or [""])[0]).strip()
    if not user_id:
        handler._send_json({"error": "user_id가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    try:
        payload = _list_wiki_user_overlays(root_dir, user_id=user_id)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(payload)


def handle_wiki_overlay_signals(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    user_id = str((params.get("user_id") or [""])[0]).strip()
    handler._send_json(_build_wiki_overlay_signal_payload(root_dir, user_id=user_id or None))


def handle_wiki_user_overlay_save(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        saved = _save_wiki_user_overlay(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(saved, HTTPStatus.CREATED)


def handle_wiki_user_overlay_remove(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        saved = _remove_wiki_user_overlay(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(saved)


__all__ = [
    "handle_buyer_packet",
    "handle_data_control_room",
    "handle_debug_chat_log",
    "handle_debug_session",
    "handle_repository_favorites",
    "handle_repository_favorites_remove",
    "handle_repository_favorites_save",
    "handle_repository_official_materialize",
    "handle_repository_search",
    "handle_repository_source_discovery_plan",
    "handle_repository_source_discovery_search",
    "handle_repository_source_discovery_judge_reports",
    "handle_repository_source_discovery_judge_replay",
    "handle_repository_source_discovery_judge_save",
    "handle_repository_source_discovery_verification_queue",
    "handle_repository_source_discovery_verification_save",
    "handle_repository_source_request_save",
    "handle_repository_unanswered",
    "handle_session_delete",
    "handle_session_load",
    "handle_sessions_delete_all",
    "handle_sessions_list",
    "handle_wiki_overlay_signals",
    "handle_wiki_user_overlay_remove",
    "handle_wiki_user_overlay_save",
    "handle_wiki_user_overlays",
]
