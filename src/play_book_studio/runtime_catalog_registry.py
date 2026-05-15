"""Shared official runtime registry for viewer, library, and chat surfaces."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.config.validation import read_jsonl
from play_book_studio.source_provenance import source_provenance_payload


def _safe_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _humanize_book_slug(slug: str) -> str:
    return str(slug or "").replace("_", " ").replace("-", " ").strip().title()


def _docs_viewer_path(settings: Settings, slug: str) -> str:
    return settings.viewer_path_template.format(slug=slug)


def _active_manifest_path(root_dir: Path) -> Path:
    return root_dir / "data" / "wiki_runtime_books" / "active_manifest.json"


def _is_customer_or_private_payload(payload: dict[str, Any], *, source_metadata: dict[str, Any] | None = None) -> bool:
    metadata = source_metadata or {}
    source_lane = str(
        metadata.get("source_lane")
        or payload.get("source_lane")
        or ""
    ).strip()
    boundary_truth = str(
        metadata.get("boundary_truth")
        or payload.get("boundary_truth")
        or ""
    ).strip()
    classification = str(
        metadata.get("classification")
        or payload.get("classification")
        or ""
    ).strip()
    return (
        source_lane == "customer_source_first_pack"
        or boundary_truth == "private_customer_pack_runtime"
        or classification == "private"
    )


def _source_manifest_entry_is_runtime_eligible(entry: dict[str, Any]) -> bool:
    if _is_customer_or_private_payload(entry):
        return False
    approval_state = str(entry.get("approval_state") or "").strip()
    review_status = str(entry.get("review_status") or entry.get("approval_status") or "").strip()
    content_status = str(entry.get("content_status") or "").strip()
    publication_state = str(entry.get("publication_state") or "").strip()
    return (
        approval_state == "approved"
        or review_status == "approved"
        or content_status == "approved_ko"
        or publication_state in {"active", "published"}
    )


def _playbook_row_is_runtime_eligible(row: dict[str, Any]) -> bool:
    source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    if _is_customer_or_private_payload(row, source_metadata=source_metadata):
        return False
    approval_state = str(source_metadata.get("approval_state") or row.get("approval_state") or "").strip()
    review_status = str(row.get("review_status") or "").strip()
    translation_status = str(row.get("translation_status") or row.get("translation_stage") or "").strip()
    publication_state = str(source_metadata.get("publication_state") or row.get("publication_state") or "").strip()
    return (
        approval_state == "approved"
        or review_status == "approved"
        or translation_status == "approved_ko"
        or publication_state in {"active", "published"}
    )


def _registry_key(root_dir: Path) -> tuple[str, str, str, str, str, str, str, int, int, int]:
    settings = load_settings(root_dir)
    active_manifest_path = _active_manifest_path(root_dir)
    return (
        str(root_dir.resolve()),
        str(active_manifest_path.resolve()),
        str(settings.source_manifest_path.resolve()),
        str(settings.playbook_documents_path.resolve()),
        settings.active_pack_id,
        settings.docs_language,
        settings.viewer_path_template,
        _safe_mtime_ns(active_manifest_path),
        _safe_mtime_ns(settings.source_manifest_path),
        _safe_mtime_ns(settings.playbook_documents_path),
    )


def _base_registry_entry(*, slug: str, settings: Settings) -> dict[str, Any]:
    docs_viewer_path = _docs_viewer_path(settings, slug)
    return {
        "book_slug": slug,
        "title": _humanize_book_slug(slug),
        "viewer_path": docs_viewer_path,
        "docs_viewer_path": docs_viewer_path,
        "source_url": "",
        "source_lane": "",
        "source_type": "",
        "approval_state": "",
        "publication_state": "",
        "review_status": "",
        "content_status": "",
        "translation_status": "",
        "translation_stage": "",
        "parser_backend": "",
        "promotion_strategy": "",
        "pack_id": settings.active_pack_id,
        "pack_label": settings.active_pack.pack_label,
        "section_count": 0,
        "code_block_count": 0,
        "updated_at": "",
        "active_runtime": False,
        "active_runtime_viewer_path": "",
        "runtime_path": "",
        "source_candidate_path": "",
        "source_origin": "",
        "source_ref": "",
        "source_fingerprint": "",
        "source_repo": "",
        "source_branch": "",
        "source_binding_kind": "",
        "source_relative_path": "",
        "source_relative_paths": [],
        "fallback_source_url": "",
        "fallback_viewer_path": "",
    }


def _upsert_registry_entry(
    registry: dict[str, dict[str, Any]],
    *,
    slug: str,
    settings: Settings,
    incoming: dict[str, Any],
    prefer_viewer_path: bool = False,
) -> None:
    current = registry.get(slug)
    if current is None:
        current = _base_registry_entry(slug=slug, settings=settings)
        registry[slug] = current

    for key, value in incoming.items():
        if key == "viewer_path":
            if prefer_viewer_path and str(value or "").strip():
                current[key] = str(value)
            elif not str(current.get(key) or "").strip() and str(value or "").strip():
                current[key] = str(value)
            continue
        if key == "title":
            normalized = str(value or "").strip()
            if not normalized:
                continue
            existing_title = str(current.get("title") or "").strip()
            if not existing_title or existing_title == _humanize_book_slug(slug):
                current["title"] = normalized
            continue
        if key in {"section_count", "code_block_count"}:
            current[key] = max(int(current.get(key) or 0), int(value or 0))
            continue
        if key == "active_runtime":
            current[key] = bool(current.get(key) or value)
            continue
        normalized = str(value or "").strip() if isinstance(value, str) else value
        if normalized in ("", None, [], {}):
            continue
        if key == "source_origin":
            current[key] = normalized
            continue
        if not current.get(key):
            current[key] = normalized

    if current.get("active_runtime") and str(current.get("active_runtime_viewer_path") or "").strip():
        current["viewer_path"] = str(current["active_runtime_viewer_path"])


@lru_cache(maxsize=8)
def _load_registry_cached(
    root_dir_str: str,
    active_manifest_path_str: str,
    source_manifest_path_str: str,
    playbook_documents_path_str: str,
    active_pack_id: str,
    docs_language: str,
    viewer_path_template: str,
    active_manifest_mtime_ns: int,
    source_manifest_mtime_ns: int,
    playbook_documents_mtime_ns: int,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    del (
        active_manifest_path_str,
        source_manifest_path_str,
        playbook_documents_path_str,
        active_pack_id,
        docs_language,
        viewer_path_template,
        active_manifest_mtime_ns,
        source_manifest_mtime_ns,
        playbook_documents_mtime_ns,
    )
    root_dir = Path(root_dir_str)
    settings = load_settings(root_dir)
    registry: dict[str, dict[str, Any]] = {}

    source_manifest_payload = _safe_read_json(settings.source_manifest_path)
    source_manifest_entries = source_manifest_payload.get("entries") if isinstance(source_manifest_payload.get("entries"), list) else []
    source_manifest_by_slug: dict[str, dict[str, Any]] = {}
    for entry in source_manifest_entries:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("book_slug") or "").strip()
        if not slug or not _source_manifest_entry_is_runtime_eligible(entry):
            continue
        source_manifest_by_slug[slug] = entry
        _upsert_registry_entry(
            registry,
            slug=slug,
            settings=settings,
            incoming={
                "title": str(entry.get("title") or _humanize_book_slug(slug)),
                "viewer_path": str(entry.get("viewer_path") or _docs_viewer_path(settings, slug)),
                "docs_viewer_path": str(entry.get("viewer_path") or _docs_viewer_path(settings, slug)),
                "source_url": str(entry.get("source_url") or ""),
                "source_lane": str(entry.get("source_lane") or ""),
                "source_type": str(entry.get("source_type") or ""),
                "approval_state": str(entry.get("approval_state") or entry.get("approval_status") or ""),
                "publication_state": str(entry.get("publication_state") or ""),
                "review_status": str(entry.get("review_status") or ""),
                "content_status": str(entry.get("content_status") or ""),
                "translation_status": str(entry.get("translation_status") or ""),
                "translation_stage": str(entry.get("translation_stage") or ""),
                "parser_backend": str(entry.get("parser_backend") or ""),
                "promotion_strategy": str(entry.get("promotion_strategy") or ""),
                "pack_id": str(entry.get("pack_id") or settings.active_pack_id),
                "pack_label": str(entry.get("pack_label") or settings.active_pack.pack_label),
                "section_count": int(entry.get("section_count") or 0),
                "updated_at": str(entry.get("updated_at") or ""),
                "source_origin": "source_manifest",
                **source_provenance_payload(entry),
            },
        )

    active_manifest_payload = _safe_read_json(_active_manifest_path(root_dir))
    active_entries = active_manifest_payload.get("entries") if isinstance(active_manifest_payload.get("entries"), list) else []
    active_manifest_slugs: list[str] = []
    for entry in active_entries:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        active_manifest_slugs.append(slug)
        source_entry = source_manifest_by_slug.get(slug, {})
        _upsert_registry_entry(
            registry,
            slug=slug,
            settings=settings,
            incoming={
                "title": str(entry.get("title") or source_entry.get("title") or _humanize_book_slug(slug)),
                "viewer_path": f"/playbooks/wiki-runtime/active/{slug}/index.html",
                "docs_viewer_path": _docs_viewer_path(settings, slug),
                "source_url": str(source_entry.get("source_url") or source_entry.get("fallback_source_url") or ""),
                "source_lane": str(entry.get("source_lane") or source_entry.get("source_lane") or ""),
                "source_type": str(entry.get("source_type") or source_entry.get("source_type") or "reader_grade_md"),
                "approval_state": str(entry.get("approval_state") or source_entry.get("approval_state") or source_entry.get("approval_status") or ""),
                "publication_state": str(entry.get("publication_state") or source_entry.get("publication_state") or "active"),
                "review_status": str(entry.get("review_status") or source_entry.get("review_status") or ""),
                "content_status": str(entry.get("content_status") or source_entry.get("content_status") or ""),
                "translation_status": str(entry.get("translation_status") or source_entry.get("translation_status") or ""),
                "translation_stage": str(entry.get("translation_stage") or source_entry.get("translation_stage") or ""),
                "parser_backend": str(entry.get("parser_backend") or source_entry.get("parser_backend") or ""),
                "promotion_strategy": str(entry.get("promotion_strategy") or source_entry.get("promotion_strategy") or ""),
                "pack_id": str(source_entry.get("pack_id") or settings.active_pack_id),
                "pack_label": str(source_entry.get("pack_label") or settings.active_pack.pack_label),
                "updated_at": str(entry.get("updated_at") or active_manifest_payload.get("generated_at_utc") or source_entry.get("updated_at") or ""),
                "active_runtime": True,
                "active_runtime_viewer_path": f"/playbooks/wiki-runtime/active/{slug}/index.html",
                "runtime_path": str(entry.get("runtime_path") or ""),
                "source_candidate_path": str(entry.get("source_candidate_path") or ""),
                "source_origin": "active_manifest",
                **source_provenance_payload(source_entry),
                **source_provenance_payload(entry),
            },
            prefer_viewer_path=True,
        )

    playbook_rows = read_jsonl(settings.playbook_documents_path) if settings.playbook_documents_path.exists() else []
    for row in playbook_rows:
        if not isinstance(row, dict) or not _playbook_row_is_runtime_eligible(row):
            continue
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        _upsert_registry_entry(
            registry,
            slug=slug,
            settings=settings,
            incoming={
                "title": str(row.get("title") or source_metadata.get("original_title") or _humanize_book_slug(slug)),
                "viewer_path": _docs_viewer_path(settings, slug),
                "docs_viewer_path": _docs_viewer_path(settings, slug),
                "source_url": str(row.get("source_uri") or source_metadata.get("original_url") or ""),
                "source_lane": str(source_metadata.get("source_lane") or row.get("source_lane") or ""),
                "source_type": str(source_metadata.get("source_type") or row.get("source_type") or ""),
                "approval_state": str(source_metadata.get("approval_state") or row.get("approval_state") or row.get("review_status") or ""),
                "publication_state": str(source_metadata.get("publication_state") or row.get("publication_state") or "published"),
                "review_status": str(row.get("review_status") or ""),
                "content_status": str(row.get("content_status") or ""),
                "translation_status": str(row.get("translation_status") or ""),
                "translation_stage": str(row.get("translation_stage") or ""),
                "parser_backend": str(row.get("parser_backend") or ""),
                "promotion_strategy": str(row.get("promotion_strategy") or ""),
                "pack_id": str(row.get("pack_id") or source_metadata.get("pack_id") or settings.active_pack_id),
                "pack_label": str(row.get("pack_label") or settings.active_pack.pack_label),
                "section_count": int(row.get("section_count") or 0),
                "updated_at": str(source_metadata.get("updated_at") or row.get("updated_at") or ""),
                "source_origin": "playbook_documents",
                **source_provenance_payload(source_metadata),
                **source_provenance_payload(row),
            },
        )

    sorted_registry = {
        slug: registry[slug]
        for slug in sorted(registry)
    }
    return sorted_registry, sorted(active_manifest_slugs)


def official_runtime_book_registry(root_dir: Path) -> dict[str, dict[str, Any]]:
    registry, _active_manifest_slugs = _load_registry_cached(*_registry_key(root_dir))
    return {slug: dict(payload) for slug, payload in registry.items()}


def official_runtime_book_entry(root_dir: Path, book_slug: str) -> dict[str, Any]:
    registry = official_runtime_book_registry(root_dir)
    return dict(registry.get(str(book_slug or "").strip(), {}))


def official_runtime_book_slugs(root_dir: Path) -> set[str]:
    return set(official_runtime_book_registry(root_dir))


def active_manifest_runtime_slugs(root_dir: Path) -> list[str]:
    _registry, active_manifest_slugs = _load_registry_cached(*_registry_key(root_dir))
    return list(active_manifest_slugs)


def official_runtime_books(root_dir: Path) -> list[dict[str, Any]]:
    return [payload for _, payload in sorted(official_runtime_book_registry(root_dir).items())]


__all__ = [
    "active_manifest_runtime_slugs",
    "official_runtime_book_entry",
    "official_runtime_book_registry",
    "official_runtime_book_slugs",
    "official_runtime_books",
]
