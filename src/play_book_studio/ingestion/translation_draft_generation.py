"""translation_draft manifest를 실제 한국어 draft 산출물로 변환한다."""

from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.canonical import (
    build_source_repo_document_ast,
    project_playbook_document,
    translate_document_ast,
    validate_document_ast,
    write_playbook_documents,
)
from play_book_studio.config.settings import Settings

from .chunking import chunk_sections
from .collector import collect_entry, entry_with_collected_metadata, raw_html_path
from .data_quality import build_playbook_reader_grade_audit_for_dirs
from .manifest import read_manifest
from .models import CONTENT_STATUS_TRANSLATED_KO_DRAFT, SourceManifestEntry
from .normalize import extract_document_ast, project_normalized_sections
from .source_first import (
    SOURCE_BRANCH,
    SOURCE_REPO_URL,
    derive_official_docs_legal_notice_url,
    derive_official_docs_license_or_terms,
    derive_source_repo_updated_at,
    resolve_repo_binding,
    source_mirror_root,
)


def _draft_root(settings: Settings) -> Path:
    return settings.silver_ko_dir / "translation_drafts"


def _normalized_docs_path(settings: Settings) -> Path:
    return _draft_root(settings) / "normalized_docs.jsonl"


def _chunks_path(settings: Settings) -> Path:
    return _draft_root(settings) / "chunks.jsonl"


def _playbook_documents_path(settings: Settings) -> Path:
    return _draft_root(settings) / "playbook_documents.jsonl"


def _playbook_books_dir(settings: Settings) -> Path:
    return _draft_root(settings) / "playbooks"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _rows_by_slug(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        slug = str(row.get("book_slug", "")).strip()
        if not slug:
            continue
        grouped.setdefault(slug, []).append(row)
    return grouped


def _playbooks_by_slug(path: Path) -> dict[str, dict[str, object]]:
    return {
        str(row.get("book_slug", "")).strip(): row
        for row in _read_jsonl(path)
        if str(row.get("book_slug", "")).strip()
    }


def _source_repo_runtime_entry(settings: Settings, entry: SourceManifestEntry) -> tuple[SourceManifestEntry, list[Path]]:
    source_relative_paths = [str(path).strip() for path in entry.source_relative_paths if str(path).strip()]
    source_relative_path = str(entry.source_relative_path or "").strip()
    source_binding_kind = str(entry.source_binding_kind or "").strip()
    binding = resolve_repo_binding(settings.root_dir, entry.book_slug)
    if binding is not None and (
        not source_relative_paths
        or not source_binding_kind
        or not source_relative_path
        or not source_relative_path.endswith(".adoc")
    ):
        source_relative_paths = list(binding.source_relative_paths)
        source_relative_path = binding.root_relative_path
        source_binding_kind = binding.binding_kind
    if not source_relative_paths:
        raise ValueError(f"repo/AsciiDoc binding missing for {entry.book_slug}")
    mirror_root = Path(entry.source_mirror_root or source_mirror_root(settings.root_dir))
    source_paths = [(mirror_root / relative_path).resolve() for relative_path in source_relative_paths]
    missing = [str(path) for path in source_paths if not path.exists()]
    if missing:
        raise ValueError(f"missing repo source files for {entry.book_slug}: {', '.join(missing[:3])}")
    legal_notice_url = str(entry.legal_notice_url or derive_official_docs_legal_notice_url(entry)).strip()
    license_or_terms = str(
        entry.license_or_terms
        or derive_official_docs_license_or_terms(entry, legal_notice_url=legal_notice_url)
    ).strip()
    updated_at = str(
        entry.updated_at
        or derive_source_repo_updated_at(
            settings.root_dir,
            source_relative_paths=source_relative_paths,
            mirror_root=mirror_root,
        )
    ).strip()
    runtime_entry = SourceManifestEntry(
        **{
            **entry.to_dict(),
            "source_kind": "source-first",
            "source_url": "",
            "resolved_source_url": "",
            "source_lane": "official_source_first",
            "primary_input_kind": "source_repo",
            "fallback_input_kind": "",
            "source_repo": str(entry.source_repo or SOURCE_REPO_URL).strip(),
            "source_branch": str(entry.source_branch or SOURCE_BRANCH).strip(),
            "source_binding_kind": source_binding_kind,
            "source_relative_path": source_relative_path,
            "source_relative_paths": source_relative_paths,
            "source_mirror_root": str(mirror_root),
            "legal_notice_url": legal_notice_url,
            "license_or_terms": license_or_terms,
            "updated_at": updated_at,
            "translation_source_url": str(entry.translation_source_url or entry.resolved_source_url or entry.source_url).strip(),
            "fallback_source_url": "",
            "fallback_viewer_path": "",
        }
    )
    return runtime_entry, source_paths


def _validate_source_repo_document(document, slug: str) -> None:
    errors = [issue for issue in validate_document_ast(document) if issue.severity == "error"]
    if errors:
        joined = ", ".join(issue.code for issue in errors[:5])
        raise ValueError(f"Invalid canonical AST for {slug}: {joined}")


def _materialize_outputs(
    settings: Settings,
    *,
    normalized_by_slug: dict[str, list[dict[str, object]]],
    chunks_by_slug: dict[str, list[dict[str, object]]],
    playbooks_by_slug: dict[str, dict[str, object]],
) -> None:
    normalized_rows = [
        row
        for slug in sorted(normalized_by_slug)
        for row in normalized_by_slug[slug]
    ]
    chunk_rows = [
        row
        for slug in sorted(chunks_by_slug)
        for row in chunks_by_slug[slug]
    ]
    playbook_rows = [playbooks_by_slug[slug] for slug in sorted(playbooks_by_slug)]
    _write_jsonl(_normalized_docs_path(settings), normalized_rows)
    _write_jsonl(_chunks_path(settings), chunk_rows)
    _write_jsonl(_playbook_documents_path(settings), playbook_rows)
    books_dir = _playbook_books_dir(settings)
    books_dir.mkdir(parents=True, exist_ok=True)
    expected_filenames = {f"{slug}.json" for slug in playbooks_by_slug}
    for slug, payload in playbooks_by_slug.items():
        (books_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    for stale_path in books_dir.glob("*.json"):
        if stale_path.name not in expected_filenames:
            stale_path.unlink()


def generate_translation_drafts(
    settings: Settings,
    *,
    slugs: list[str] | None = None,
    force_collect: bool = False,
    force_regenerate: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    draft_manifest_path = manifest_path or settings.translation_draft_manifest_path
    entries = read_manifest(draft_manifest_path)
    selected = [
        entry for entry in entries
        if not slugs or entry.book_slug in set(slugs)
    ]
    normalized_by_slug = (
        {}
        if force_regenerate
        else _rows_by_slug(_read_jsonl(_normalized_docs_path(settings)))
    )
    chunks_by_slug = (
        {}
        if force_regenerate
        else _rows_by_slug(_read_jsonl(_chunks_path(settings)))
    )
    playbooks_by_slug = (
        {}
        if force_regenerate
        else _playbooks_by_slug(_playbook_documents_path(settings))
    )
    books: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    reused_books: list[str] = []

    for entry in selected:
        print(
            json.dumps(
                {
                    "stage": "draft",
                    "book_slug": entry.book_slug,
                    "resume": (
                        not force_regenerate
                        and entry.book_slug in normalized_by_slug
                        and entry.book_slug in chunks_by_slug
                        and entry.book_slug in playbooks_by_slug
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if (
            not force_regenerate
            and entry.book_slug in normalized_by_slug
            and entry.book_slug in chunks_by_slug
            and entry.book_slug in playbooks_by_slug
        ):
            playbook_row = playbooks_by_slug[entry.book_slug]
            books.append(
                {
                    "book_slug": entry.book_slug,
                    "section_count": len(normalized_by_slug[entry.book_slug]),
                    "chunk_count": len(chunks_by_slug[entry.book_slug]),
                    "title": str(playbook_row.get("title") or entry.title),
                    "translation_status": str(
                        playbook_row.get("translation_status") or entry.content_status
                    ),
                    "resume_state": "reused",
                }
            )
            reused_books.append(entry.book_slug)
            continue
        try:
            if entry.primary_input_kind == "source_repo":
                runtime_entry, source_paths = _source_repo_runtime_entry(settings, entry)
                document = build_source_repo_document_ast(
                    entry=runtime_entry,
                    source_paths=source_paths,
                    fallback_title=runtime_entry.title or entry.title or entry.book_slug,
                )
                if runtime_entry.content_status == CONTENT_STATUS_TRANSLATED_KO_DRAFT:
                    document = translate_document_ast(document, settings)
                _validate_source_repo_document(document, runtime_entry.book_slug)
            else:
                collect_entry(entry, settings, force=force_collect)
                html = raw_html_path(settings, entry.book_slug).read_text(encoding="utf-8")
                runtime_entry = entry_with_collected_metadata(settings, entry)
                document = extract_document_ast(html, runtime_entry, settings=settings)
            sections = project_normalized_sections(document)
            chunks = chunk_sections(sections, settings)
            playbook_document = project_playbook_document(document)

            normalized_by_slug[entry.book_slug] = [section.to_dict() for section in sections]
            chunks_by_slug[entry.book_slug] = [chunk.to_dict() for chunk in chunks]
            playbooks_by_slug[entry.book_slug] = playbook_document.to_dict()
            _materialize_outputs(
                settings,
                normalized_by_slug=normalized_by_slug,
                chunks_by_slug=chunks_by_slug,
                playbooks_by_slug=playbooks_by_slug,
            )
            books.append(
                {
                    "book_slug": entry.book_slug,
                    "section_count": len(sections),
                    "chunk_count": len(chunks),
                    "title": getattr(document, "title", playbook_document.title),
                    "translation_status": getattr(
                        document,
                        "translation_status",
                        playbook_document.translation_status,
                    ),
                    "resume_state": "generated",
                }
            )
            print(
                json.dumps(
                    {
                        "stage": "draft_complete",
                        "book_slug": entry.book_slug,
                        "section_count": len(sections),
                        "chunk_count": len(chunks),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"book_slug": entry.book_slug, "error": str(exc)})
            print(
                json.dumps(
                    {
                        "stage": "draft_error",
                        "book_slug": entry.book_slug,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    manualbook_audit = build_playbook_reader_grade_audit_for_dirs(
        (_playbook_books_dir(settings),)
    )
    normalized_rows = [
        row for slug in sorted(normalized_by_slug) for row in normalized_by_slug[slug]
    ]
    chunk_rows = [
        row for slug in sorted(chunks_by_slug) for row in chunks_by_slug[slug]
    ]

    return {
        "summary": {
            "requested_count": len(selected),
            "generated_count": len(books),
            "reused_count": len(reused_books),
            "error_count": len(errors),
            "section_count": len(normalized_rows),
            "chunk_count": len(chunk_rows),
            "draft_manualbook_failing_book_count": int(
                manualbook_audit.get("failing_book_count", 0)
            ),
        },
        "books": books,
        "errors": errors,
        "draft_manualbook_audit": manualbook_audit,
        "output_targets": {
            "translation_draft_manifest_path": str(draft_manifest_path),
            "normalized_docs_path": str(_normalized_docs_path(settings)),
            "chunks_path": str(_chunks_path(settings)),
            "playbook_documents_path": str(_playbook_documents_path(settings)),
            "playbook_books_dir": str(_playbook_books_dir(settings)),
        },
    }
