"""Import tracked KMSC course chunks into the shared document RAG repository."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.course.qdrant_course import load_course_chunks
from play_book_studio.db.document_repository import (
    _fetch_id,
    _json,
    _upsert_repository,
    _upsert_tenant,
    _upsert_workspace,
)
from play_book_studio.ingestion.chunk_question_candidates import build_chunk_question_candidates
from play_book_studio.ingestion.kmsc_beginner_narrative import NARRATIVE_VERSION, build_beginner_narrative


@dataclass(frozen=True, slots=True)
class KmscCourseImportSummary:
    course_dir: str
    source_count: int
    chunk_count: int
    imported_chunk_count: int
    repository_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_dir": self.course_dir,
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "imported_chunk_count": self.imported_chunk_count,
            "repository_id": self.repository_id,
            "source_scope": "study_docs",
        }


def build_kmsc_course_import_plan(course_dir: Path, *, limit: int = 0) -> dict[str, Any]:
    rows = _load_rows(course_dir, limit=limit)
    grouped = _group_rows_by_source(rows)
    return {
        "course_dir": str(course_dir.resolve()),
        "source_count": len(grouped),
        "chunk_count": len(rows),
        "repository_slug": "study-docs",
        "repository_kind": "study",
        "visibility": "workspace_shared",
        "source_scope": "study_docs",
        "sources": [
            {
                "source_key": source_key,
                "title": _source_title(source_key, source_rows),
                "chunk_count": len(source_rows),
            }
            for source_key, source_rows in sorted(grouped.items())
        ],
    }


def import_kmsc_course_chunks(
    connection,
    *,
    course_dir: Path,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    limit: int = 0,
) -> KmscCourseImportSummary:
    rows = _load_rows(course_dir, limit=limit)
    grouped = _group_rows_by_source(rows)
    imported_chunk_count = 0
    repository_id = ""

    with connection.transaction():
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_slug=tenant_slug, tenant_name=tenant_name)
            workspace_id = _upsert_workspace(
                cursor,
                tenant_id=tenant_id,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
            )
            repository_id = _upsert_repository(
                cursor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id="",
                slug="study-docs",
                title="Study Docs",
                repository_kind="study",
                visibility="workspace_shared",
            )
            for source_key, source_rows in grouped.items():
                source_id = _upsert_source(
                    cursor,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    source_key=source_key,
                    rows=source_rows,
                    course_dir=course_dir,
                )
                version_id = _upsert_version(cursor, source_id=source_id, source_key=source_key, course_dir=course_dir)
                parse_job_id = _upsert_parse_job(cursor, source_id=source_id, version_id=version_id, source_key=source_key)
                parsed_document_id = _upsert_parsed_document(
                    cursor,
                    source_id=source_id,
                    version_id=version_id,
                    parse_job_id=parse_job_id,
                    source_key=source_key,
                    rows=source_rows,
                )
                for ordinal, row in enumerate(source_rows):
                    _upsert_chunk(cursor, parsed_document_id=parsed_document_id, row=row, ordinal=ordinal)
                    imported_chunk_count += 1

    return KmscCourseImportSummary(
        course_dir=str(course_dir.resolve()),
        source_count=len(grouped),
        chunk_count=len(rows),
        imported_chunk_count=imported_chunk_count,
        repository_id=repository_id,
    )


def _load_rows(course_dir: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    rows = [row for row in load_course_chunks(course_dir) if isinstance(row, dict)]
    if limit > 0:
        rows = rows[:limit]
    return rows


def _group_rows_by_source(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_source_key(row)].append(row)
    return dict(grouped)


def _source_key(row: dict[str, Any]) -> str:
    value = str(row.get("source_pptx") or "").strip()
    if value:
        return value
    refs = row.get("slide_refs")
    if isinstance(refs, list) and refs and isinstance(refs[0], dict):
        value = str(refs[0].get("pptx") or "").strip()
        if value:
            return value
    return "kmsc-course-pbs"


def _source_title(source_key: str, rows: list[dict[str, Any]]) -> str:
    first = rows[0] if rows else {}
    title = Path(source_key).name or str(first.get("stage_id") or "KMSC Course")
    return title


def _source_storage_key(course_dir: Path, source_key: str) -> str:
    return f"{course_dir.as_posix()}#source={source_key}"


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _stable_sha256(*parts: str) -> str:
    return hashlib.sha256("\n".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _source_metadata(source_key: str, rows: list[dict[str, Any]], course_dir: Path) -> dict[str, Any]:
    first = rows[0] if rows else {}
    return {
        "source_id": source_key,
        "book_slug": "kmsc-operations",
        "book_title": _source_title(source_key, rows),
        "category_key": "study",
        "category_label": "Study Docs",
        "document_format": "kmsc_course_jsonl",
        "source_scope": "study_docs",
        "visibility": "workspace_shared",
        "chunk_count": len(rows),
        "course_dir": str(course_dir.resolve()),
        "stage_id": str(first.get("stage_id") or ""),
    }


def _upsert_source(
    cursor,
    *,
    tenant_id: str,
    workspace_id: str,
    repository_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
    course_dir: Path,
) -> str:
    source_id = _stable_uuid("kmsc-course-source", source_key)
    cursor.execute(
        """
        INSERT INTO document_sources (
            id, tenant_id, workspace_id, source_kind, filename, mime_type, sha256,
            storage_key, byte_size, access_policy, metadata, created_by,
            repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, 'kmsc_course_jsonl', %s, 'application/x-jsonlines', %s,
            %s, 0, '{}'::jsonb, %s::jsonb, '',
            %s::uuid, '', 'workspace_shared', 'study_docs'
        )
        ON CONFLICT (id) DO UPDATE SET
            filename = EXCLUDED.filename,
            storage_key = EXCLUDED.storage_key,
            metadata = EXCLUDED.metadata,
            repository_id = EXCLUDED.repository_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope
        RETURNING id
        """,
        (
            source_id,
            tenant_id,
            workspace_id,
            _source_title(source_key, rows),
            _stable_sha256("kmsc-course-source", source_key),
            _source_storage_key(course_dir, source_key),
            _json(_source_metadata(source_key, rows, course_dir)),
            repository_id,
        ),
    )
    return _fetch_id(cursor)


def _upsert_version(cursor, *, source_id: str, source_key: str, course_dir: Path) -> str:
    version_id = _stable_uuid("kmsc-course-version", source_key)
    cursor.execute(
        """
        INSERT INTO document_versions (id, document_source_id, version_no, source_sha256, storage_key)
        VALUES (%s, %s, 1, %s, %s)
        ON CONFLICT (document_source_id, version_no) DO UPDATE SET
            source_sha256 = EXCLUDED.source_sha256,
            storage_key = EXCLUDED.storage_key
        RETURNING id
        """,
        (version_id, source_id, _stable_sha256("kmsc-course-source", source_key), _source_storage_key(course_dir, source_key)),
    )
    return _fetch_id(cursor)


def _upsert_parse_job(cursor, *, source_id: str, version_id: str, source_key: str) -> str:
    parse_job_id = _stable_uuid("kmsc-course-parse-job", source_key)
    cursor.execute(
        """
        INSERT INTO parse_jobs (
            id, document_source_id, document_version_id, parser_name, parser_version,
            status, completed_at
        )
        VALUES (%s, %s, %s, 'kmsc-course-import', '0.1', 'succeeded', now())
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = now()
        RETURNING id
        """,
        (parse_job_id, source_id, version_id),
    )
    return _fetch_id(cursor)


def _upsert_parsed_document(
    cursor,
    *,
    source_id: str,
    version_id: str,
    parse_job_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
) -> str:
    parsed_document_id = _stable_uuid("kmsc-course-parsed-document", source_key)
    cursor.execute(
        """
        INSERT INTO parsed_documents (
            id, document_source_id, document_version_id, parse_job_id,
            parser_name, parser_version, title, markdown, metadata, outline, warnings
        )
        VALUES (%s, %s, %s, %s, 'kmsc-course-import', '0.1', %s, '', %s::jsonb, '[]'::jsonb, '[]'::jsonb)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (
            parsed_document_id,
            source_id,
            version_id,
            parse_job_id,
            _source_title(source_key, rows),
            _json({"source_key": source_key, "chunk_count": len(rows), "document_format": "kmsc_course_jsonl"}),
        ),
    )
    return _fetch_id(cursor)


def _upsert_chunk(cursor, *, parsed_document_id: str, row: dict[str, Any], ordinal: int) -> str:
    chunk_id = _chunk_uuid(row)
    chunk_text = _chunk_text(row)
    metadata = _chunk_metadata(row)
    beginner_narrative = str(metadata.get("beginner_narrative") or "").strip()
    if beginner_narrative and not chunk_text.startswith(beginner_narrative):
        chunk_text = "\n".join(part for part in (beginner_narrative, chunk_text) if part.strip())
    slide_range = row.get("source_slide_range") if isinstance(row.get("source_slide_range"), list) else []
    page_start = int(slide_range[0]) if slide_range and str(slide_range[0]).isdigit() else None
    page_end = int(slide_range[-1]) if slide_range and str(slide_range[-1]).isdigit() else page_start
    section_path = [str(item) for item in (row.get("stage_id"), row.get("title")) if str(item or "").strip()]
    cursor.execute(
        """
        INSERT INTO document_chunks (
            id, parsed_document_id, chunk_key, ordinal, chunk_type, markdown,
            embedding_text, token_count, page_start, page_end, section_path,
            section_number, heading_title, source_anchor, toc_path,
            asset_ids, metadata, repository_id, owner_user_id, visibility, source_scope,
            chunk_role, parent_chunk_id, child_chunk_ids, navigation_only, beginner_narrative,
            starter_question_candidates, followup_question_candidates, question_candidates_version
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
            '', %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
            (
                SELECT ds.repository_id
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ),
            '', 'workspace_shared', 'study_docs',
            %s, NULLIF(%s, '')::uuid, %s::jsonb, %s, %s,
            %s::jsonb, %s::jsonb, %s
        )
        ON CONFLICT (id) DO UPDATE SET
            parsed_document_id = EXCLUDED.parsed_document_id,
            chunk_key = EXCLUDED.chunk_key,
            ordinal = EXCLUDED.ordinal,
            chunk_type = EXCLUDED.chunk_type,
            markdown = EXCLUDED.markdown,
            embedding_text = EXCLUDED.embedding_text,
            token_count = EXCLUDED.token_count,
            page_start = EXCLUDED.page_start,
            page_end = EXCLUDED.page_end,
            section_path = EXCLUDED.section_path,
            heading_title = EXCLUDED.heading_title,
            source_anchor = EXCLUDED.source_anchor,
            toc_path = EXCLUDED.toc_path,
            asset_ids = EXCLUDED.asset_ids,
            metadata = EXCLUDED.metadata,
            repository_id = EXCLUDED.repository_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope,
            chunk_role = EXCLUDED.chunk_role,
            parent_chunk_id = EXCLUDED.parent_chunk_id,
            child_chunk_ids = EXCLUDED.child_chunk_ids,
            navigation_only = EXCLUDED.navigation_only,
            beginner_narrative = EXCLUDED.beginner_narrative,
            starter_question_candidates = EXCLUDED.starter_question_candidates,
            followup_question_candidates = EXCLUDED.followup_question_candidates,
            question_candidates_version = EXCLUDED.question_candidates_version
        RETURNING id
        """,
        (
            chunk_id,
            parsed_document_id,
            str(row.get("chunk_id") or chunk_id),
            ordinal,
            str(row.get("chunk_kind") or "study_reference"),
            str(row.get("body_md") or row.get("title") or chunk_text),
            chunk_text,
            len(chunk_text.split()),
            page_start,
            page_end,
            _json(section_path),
            str(row.get("title") or ""),
            _source_anchor(row),
            _json(section_path),
            _json(_asset_ids(row)),
            _json(metadata),
            parsed_document_id,
            str(row.get("chunk_role") or metadata.get("chunk_role") or "leaf"),
            str(row.get("parent_chunk_id") or metadata.get("parent_chunk_id") or ""),
            _json(row.get("child_chunk_ids") or metadata.get("child_chunk_ids") or []),
            bool(row.get("navigation_only") or metadata.get("navigation_only") or False),
            str(row.get("beginner_narrative") or metadata.get("beginner_narrative") or ""),
            _json(row.get("starter_question_candidates") or metadata.get("starter_question_candidates") or []),
            _json(row.get("followup_question_candidates") or metadata.get("followup_question_candidates") or []),
            int(row.get("question_candidates_version") or metadata.get("question_candidates_version") or 0),
        ),
    )
    return _fetch_id(cursor)


def _chunk_uuid(row: dict[str, Any]) -> str:
    raw = str(row.get("chunk_id") or "").strip()
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return _stable_uuid("kmsc-course-chunk", raw or json.dumps(row, sort_keys=True, ensure_ascii=False))


def _chunk_text(row: dict[str, Any]) -> str:
    index_texts = row.get("index_texts") if isinstance(row.get("index_texts"), dict) else {}
    beginner_narrative = str(row.get("beginner_narrative") or "").strip()
    body = str(
        index_texts.get("dense_text")
        or row.get("search_text")
        or row.get("body_md")
        or row.get("title")
        or ""
    )
    return "\n".join(part for part in (beginner_narrative, body) if part.strip())


def _asset_ids(row: dict[str, Any]) -> list[str]:
    attachments = row.get("image_attachments") if isinstance(row.get("image_attachments"), list) else []
    return [str(item.get("asset_id") or "") for item in attachments if isinstance(item, dict) and str(item.get("asset_id") or "").strip()]


def _source_anchor(row: dict[str, Any]) -> str:
    slide_range = row.get("source_slide_range") if isinstance(row.get("source_slide_range"), list) else []
    if slide_range:
        return f"slide:{slide_range[0]}"
    return str(row.get("chunk_id") or "")


def _chunk_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row)
    candidates = build_chunk_question_candidates({**row, "text": _chunk_text(row)})
    metadata["source_scope"] = "study_docs"
    metadata["document_format"] = "kmsc_course_jsonl"
    metadata["book_slug"] = "kmsc-operations"
    metadata["book_title"] = "KMSC Operations"
    metadata["category_key"] = "study"
    metadata.setdefault("beginner_narrative", build_beginner_narrative(row))
    metadata.setdefault("beginner_narrative_version", NARRATIVE_VERSION)
    metadata.setdefault("starter_question_candidates", candidates["starter_question_candidates"])
    metadata.setdefault("followup_question_candidates", candidates["followup_question_candidates"])
    metadata.setdefault("question_candidates_version", 1 if candidates["starter_question_candidates"] else 0)
    return metadata


__all__ = [
    "KmscCourseImportSummary",
    "build_kmsc_course_import_plan",
    "import_kmsc_course_chunks",
]
