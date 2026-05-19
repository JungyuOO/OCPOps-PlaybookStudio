"""Folder-level corpus import for shared document repositories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.db.document_repository import persist_parsed_upload_document
from play_book_studio.db.qdrant_indexer import index_pending_document_chunks
from play_book_studio.config.corpus_paths import OFFICIAL_IMPORTED_GOLD_DIR, STUDY_DOCS_DIR
from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document
from play_book_studio.ingestion.learning_metadata import attach_learning_metadata, build_learning_document_index
from play_book_studio.ingestion.vision import build_company_llm_image_describer


SUPPORTED_CORPUS_SUFFIXES = {
    ".adoc",
    ".asciidoc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".md",
    ".markdown",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".webp",
    ".xlsx",
}

EXCLUDED_CORPUS_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "artifacts",
    "dist",
    "node_modules",
    "reports",
    "tmp",
}


@dataclass(frozen=True, slots=True)
class CorpusImportProfile:
    repository_slug: str
    repository_title: str
    repository_kind: str
    visibility: str
    source_scope: str
    storage_prefix: Path


def corpus_import_profile(kind: str) -> CorpusImportProfile:
    normalized = str(kind or "").strip().lower().replace("-", "_")
    if normalized in {"official", "official_docs"}:
        return CorpusImportProfile(
            repository_slug="official-docs",
            repository_title="Official Docs",
            repository_kind="official",
            visibility="global_shared",
            source_scope="official_docs",
            storage_prefix=OFFICIAL_IMPORTED_GOLD_DIR,
        )
    if normalized in {"study", "study_docs"}:
        return CorpusImportProfile(
            repository_slug="study-docs",
            repository_title="Study Docs",
            repository_kind="study",
            visibility="workspace_shared",
            source_scope="study_docs",
            storage_prefix=STUDY_DOCS_DIR,
        )
    raise ValueError("corpus kind must be official_docs or study_docs")


def iter_corpus_source_files(source_dir: Path) -> tuple[Path, ...]:
    source_dir = source_dir.resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"corpus source directory does not exist: {source_dir}")
    return tuple(
        sorted(
            (
                path
                for path in source_dir.rglob("*")
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_CORPUS_SUFFIXES
                and not path.name.startswith("~$")
                and not set(path.relative_to(source_dir).parts[:-1]).intersection(EXCLUDED_CORPUS_DIR_NAMES)
            ),
            key=lambda path: path.relative_to(source_dir).as_posix().lower(),
        )
    )


def build_corpus_import_plan(source_dir: Path, *, corpus_kind: str) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    profile = corpus_import_profile(corpus_kind)
    files = iter_corpus_source_files(source_dir)
    return {
        "source_dir": str(source_dir),
        "file_count": len(files),
        "repository_slug": profile.repository_slug,
        "repository_title": profile.repository_title,
        "repository_kind": profile.repository_kind,
        "visibility": profile.visibility,
        "source_scope": profile.source_scope,
        "storage_prefix": profile.storage_prefix.as_posix(),
        "files": [
            {
                "path": str(path),
                "relative_path": path.relative_to(source_dir).as_posix(),
                "suffix": path.suffix.lower(),
                "byte_size": path.stat().st_size,
            }
            for path in files
        ],
    }


def import_corpus_documents(
    connection,
    *,
    source_dir: Path,
    corpus_kind: str,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    chunk_max_chars: int = 1800,
    chunk_overlap_blocks: int = 1,
    index: bool = False,
    settings: Any | None = None,
    collection: str = "",
) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    profile = corpus_import_profile(corpus_kind)
    files = iter_corpus_source_files(source_dir)
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    seen_sha256: dict[str, str] = {}
    image_describer = build_company_llm_image_describer(settings) if settings is not None else None
    document_index = build_learning_document_index(
        tuple(path.relative_to(source_dir).as_posix() for path in files),
        corpus_kind=corpus_kind,
    )

    for path in files:
        relative_path = path.relative_to(source_dir).as_posix()
        try:
            source_sha256 = _sha256_file(path)
            if source_sha256 in seen_sha256:
                skipped.append(
                    {
                        "relative_path": relative_path,
                        "reason": "duplicate_sha256",
                        "duplicate_of": seen_sha256[source_sha256],
                    }
                )
                continue
            seen_sha256[source_sha256] = relative_path
            parsed = parse_upload_document(path, image_describer=image_describer)
            chunks = build_document_chunks(
                parsed,
                max_chars=chunk_max_chars,
                overlap_blocks=chunk_overlap_blocks,
            )
            parsed, chunks = attach_learning_metadata(
                parsed,
                chunks,
                relative_path=relative_path,
                corpus_kind=corpus_kind,
                document_index=document_index,
            )
            persisted = persist_parsed_upload_document(
                connection,
                parsed,
                chunks,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
                storage_key=(profile.storage_prefix / relative_path).as_posix(),
                created_by="",
                repository_slug=profile.repository_slug,
                repository_title=profile.repository_title,
                repository_kind=profile.repository_kind,
                visibility=profile.visibility,
                source_scope=profile.source_scope,
            )
            imported.append(
                {
                    "relative_path": relative_path,
                    "document_format": parsed.document_format,
                    "repository_id": persisted.repository_id,
                    "document_source_id": persisted.document_source_id,
                    "chunk_count": len(persisted.chunk_ids),
                    "asset_count": len(persisted.asset_ids),
                    "warnings": list(parsed.warnings),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed.append({"relative_path": relative_path, "error": str(exc)})

    index_result = None
    if index and settings is not None and imported:
        index_result = index_pending_document_chunks(
            settings,
            connection,
            collection=collection.strip() or None,
            limit=max(100, sum(int(item["chunk_count"]) for item in imported)),
        )

    return {
        "source_dir": str(source_dir),
        "repository_slug": profile.repository_slug,
        "repository_kind": profile.repository_kind,
        "visibility": profile.visibility,
        "source_scope": profile.source_scope,
        "file_count": len(files),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "index": index_result,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CorpusImportProfile",
    "SUPPORTED_CORPUS_SUFFIXES",
    "build_corpus_import_plan",
    "corpus_import_profile",
    "import_corpus_documents",
    "iter_corpus_source_files",
]
