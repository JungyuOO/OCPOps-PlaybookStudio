"""Import existing official gold retrieval chunks into PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.config.corpus_paths import OFFICIAL_GOLD_CHUNKS_PATH
from play_book_studio.db.document_repository import (
    _fetch_id,
    _json,
    _upsert_repository,
    _upsert_tenant,
    _upsert_workspace,
)
from play_book_studio.ingestion.learning_metadata import (
    CATEGORY_LABELS,
    build_chunk_learning_metadata,
    build_learning_book_index,
    infer_category_key,
)

_SECTION_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)(?:[.)]|\.?)\s+(.+?)\s*$")


def _official_gold_storage_key(source_key: str = "") -> str:
    base = OFFICIAL_GOLD_CHUNKS_PATH.as_posix()
    suffix = str(source_key or "").strip()
    return f"{base}#{suffix}" if suffix else base


@dataclass(frozen=True, slots=True)
class OfficialGoldImportSummary:
    chunks_path: str
    source_count: int
    chunk_count: int
    imported_chunk_count: int
    repository_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks_path": self.chunks_path,
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "imported_chunk_count": self.imported_chunk_count,
            "repository_id": self.repository_id,
        }


def build_official_gold_import_plan(chunks_path: Path, *, limit: int = 0) -> dict[str, Any]:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    grouped = _group_rows_by_source(rows)
    learning_by_book = _learning_by_book_slug(grouped)
    return {
        "chunks_path": str(chunks_path.resolve()),
        "source_count": len(grouped),
        "chunk_count": len(rows),
        "repository_slug": "official-docs",
        "repository_kind": "official",
        "visibility": "global_shared",
        "source_scope": "official_docs",
        "sources": [
            {
                "source_key": source_key,
                "book_slug": str(source_rows[0].get("book_slug") or source_key),
                "title": _source_title(source_rows),
                "category_key": str(
                    (learning_by_book.get(str(source_rows[0].get("book_slug") or source_key)) or {}).get("category_key")
                    or infer_category_key(str(source_rows[0].get("book_slug") or source_key))
                ),
                "next_refs": list(
                    (
                        (learning_by_book.get(str(source_rows[0].get("book_slug") or source_key)) or {})
                        .get("learning")
                        or {}
                    ).get("next_refs")
                    or []
                ),
                "chunk_count": len(source_rows),
            }
            for source_key, source_rows in sorted(grouped.items())
        ],
    }


def import_official_gold_chunks(
    connection,
    *,
    chunks_path: Path,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    limit: int = 0,
) -> OfficialGoldImportSummary:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    grouped = _group_rows_by_source(rows)
    learning_by_book = _learning_by_book_slug(grouped)
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
                slug="official-docs",
                title="Official Docs",
                repository_kind="official",
                visibility="global_shared",
            )
            for source_key, source_rows in grouped.items():
                source_id = _upsert_official_document_source(
                    cursor,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    source_key=source_key,
                    rows=source_rows,
                    chunks_path=chunks_path,
                    learning_by_book=learning_by_book,
                )
                version_id = _upsert_official_document_version(
                    cursor,
                    source_id=source_id,
                    source_key=source_key,
                    chunks_path=chunks_path,
                )
                parse_job_id = _upsert_official_parse_job(
                    cursor,
                    source_id=source_id,
                    version_id=version_id,
                    source_key=source_key,
                )
                parsed_document_id = _upsert_official_parsed_document(
                    cursor,
                    source_id=source_id,
                    version_id=version_id,
                    parse_job_id=parse_job_id,
                    source_key=source_key,
                    rows=source_rows,
                    learning_by_book=learning_by_book,
                )
                for ordinal, row in enumerate(source_rows):
                    _upsert_official_document_chunk(
                        cursor,
                        parsed_document_id=parsed_document_id,
                        row=row,
                        ordinal=ordinal,
                        learning_by_book=learning_by_book,
                    )
                    imported_chunk_count += 1

    return OfficialGoldImportSummary(
        chunks_path=str(chunks_path.resolve()),
        source_count=len(grouped),
        chunk_count=len(rows),
        imported_chunk_count=imported_chunk_count,
        repository_id=repository_id,
    )


def _load_gold_chunk_rows(chunks_path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    chunks_path = chunks_path.resolve()
    rows: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def _group_rows_by_source(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_source_key(row)].append(row)
    return dict(grouped)


def _learning_by_book_slug(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    book_slugs = tuple(
        str((source_rows[0] if source_rows else {}).get("book_slug") or source_key).strip()
        for source_key, source_rows in sorted(grouped.items())
    )
    return build_learning_book_index(book_slugs, corpus_kind="official_docs")


def _source_key(row: dict[str, Any]) -> str:
    return str(row.get("source_id") or row.get("book_slug") or "official-doc").strip()


def _source_title(rows: list[dict[str, Any]]) -> str:
    first = rows[0] if rows else {}
    return str(first.get("book_title") or first.get("book_slug") or _source_key(first))


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _uuid_from_row_chunk_id(row: dict[str, Any]) -> str:
    raw = str(row.get("chunk_id") or "").strip()
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return _stable_uuid("official-gold-chunk", raw or json.dumps(row, sort_keys=True))


def _stable_sha256(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _section_path(row: dict[str, Any]) -> list[str]:
    value = row.get("section_path")
    if isinstance(value, list):
        return [_split_section_number_title(str(item))[1] for item in value if str(item).strip()]
    chapter = str(row.get("chapter") or "").strip()
    section = str(row.get("section") or "").strip()
    return [_split_section_number_title(item)[1] for item in (chapter, section) if item]


def _section_number(row: dict[str, Any]) -> str:
    explicit = str(row.get("section_number") or "").strip()
    if explicit:
        return explicit
    for candidate in reversed(_raw_section_labels(row)):
        section_number, _ = _split_section_number_title(candidate)
        if section_number:
            return section_number
    return ""


def _heading_title(row: dict[str, Any], section_path: list[str]) -> str:
    if section_path:
        return section_path[-1]
    for candidate in (row.get("section"), row.get("chapter"), row.get("book_title"), row.get("book_slug")):
        text = str(candidate or "").strip()
        if text:
            return _split_section_number_title(text)[1]
    return ""


def _toc_path(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for raw_label in _raw_section_labels(row):
        section_number, heading_title = _split_section_number_title(raw_label)
        if not heading_title:
            continue
        labels.append(f"{section_number} {heading_title}".strip() if section_number else heading_title)
    return labels


def _raw_section_labels(row: dict[str, Any]) -> list[str]:
    value = row.get("section_path")
    if isinstance(value, list):
        labels = [str(item).strip() for item in value if str(item).strip()]
        if labels:
            return labels
    labels = []
    for item in (row.get("chapter"), row.get("section")):
        text = str(item or "").strip()
        if text and text not in labels:
            labels.append(text)
    return labels


def _split_section_number_title(title: str) -> tuple[str, str]:
    title = str(title or "").strip()
    match = _SECTION_NUMBER_RE.match(title)
    if not match:
        return "", title
    section_number = match.group(1).strip().rstrip(".")
    heading_title = match.group(2).strip()
    return section_number, heading_title or title


def _source_anchor(row: dict[str, Any]) -> str:
    for key in ("anchor", "anchor_id", "source_anchor"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    section_id = str(row.get("section_id") or "").strip()
    if ":" in section_id:
        return section_id.rsplit(":", 1)[-1]
    return section_id


def _normalized_chunk_text(row: dict[str, Any]) -> str:
    text = str(row.get("text") or "").strip()
    if not text:
        return ""
    raw_labels = _raw_section_labels(row)
    removable = {
        str(row.get("book_title") or "").strip(),
        str(row.get("book_slug") or "").strip(),
        *raw_labels,
        " > ".join(raw_labels),
        *_section_path(row),
        *_toc_path(row),
    }
    lines = text.splitlines()
    while lines and lines[0].strip() in removable:
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).strip() or text


def _chunk_metadata(row: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "book_slug",
        "book_title",
        "chapter",
        "section",
        "section_id",
        "anchor",
        "source_url",
        "viewer_path",
        "source_id",
        "source_lane",
        "source_type",
        "source_collection",
        "review_status",
        "trust_score",
        "parsed_artifact_id",
        "semantic_role",
        "block_kinds",
        "cli_commands",
        "error_strings",
        "k8s_objects",
        "operator_names",
        "verification_hints",
        "product",
        "version",
        "locale",
        "translation_status",
        "approval_state",
        "publication_state",
    )
    return {key: row[key] for key in keep_keys if key in row}


def _official_chunk_metadata(
    row: dict[str, Any],
    *,
    ordinal: int,
    learning_by_book: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    section_path = _section_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    chunk_text = _normalized_chunk_text(row)
    metadata = _chunk_metadata(row)
    book_slug = str(row.get("book_slug") or "").strip()
    learning = dict(((learning_by_book or {}).get(book_slug) or {}).get("learning") or {})
    metadata["learning"] = build_chunk_learning_metadata(
        learning,
        ordinal=int(row.get("ordinal") if row.get("ordinal") is not None else ordinal),
        section_number=section_number,
        heading=heading_title,
        text="\n".join([chunk_text, " ".join(str(item) for item in row.get("cli_commands", []) if str(item).strip())]),
    )
    return metadata


def _source_metadata(
    source_key: str,
    rows: list[dict[str, Any]],
    chunks_path: Path,
    *,
    learning_by_book: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    first = rows[0] if rows else {}
    book_slug = str(first.get("book_slug") or source_key)
    learning_node = (learning_by_book or {}).get(book_slug) or {}
    category_key = str(learning_node.get("category_key") or infer_category_key(book_slug))
    return {
        **_chunk_metadata(first),
        "source_id": source_key,
        "book_slug": book_slug,
        "book_title": _source_title(rows),
        "category_key": category_key,
        "category_label": str(learning_node.get("category_label") or CATEGORY_LABELS.get(category_key, "Wiki")),
        "learning": dict(learning_node.get("learning") or {}),
        "document_format": "official_gold_jsonl",
        "source_scope": "official_docs",
        "visibility": "global_shared",
        "chunk_count": len(rows),
        "source_jsonl": str(chunks_path.resolve()),
    }


def _upsert_official_document_source(
    cursor,
    *,
    tenant_id: str,
    workspace_id: str,
    repository_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
    chunks_path: Path,
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    first = rows[0]
    source_id = _stable_uuid("official-gold-source", source_key)
    source_sha256 = _stable_sha256("official-gold-source", source_key)
    cursor.execute(
        """
        INSERT INTO document_sources (
            id, tenant_id, workspace_id, source_kind, filename, mime_type, sha256,
            storage_key, byte_size, access_policy, metadata, created_by,
            repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, 'official_gold', %s, 'application/x-jsonlines', %s,
            %s, 0, '{}'::jsonb, %s::jsonb, '',
            %s::uuid, '', 'global_shared', 'official_docs'
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
            f"{str(first.get('book_slug') or source_key)}.jsonl",
            source_sha256,
            _official_gold_storage_key(source_key),
            _json(_source_metadata(source_key, rows, chunks_path, learning_by_book=learning_by_book)),
            repository_id,
        ),
    )
    return _fetch_id(cursor)


def _upsert_official_document_version(
    cursor,
    *,
    source_id: str,
    source_key: str,
    chunks_path: Path,
) -> str:
    version_id = _stable_uuid("official-gold-version", source_key)
    source_sha256 = _stable_sha256("official-gold-source", source_key)
    cursor.execute(
        """
        INSERT INTO document_versions (id, document_source_id, version_no, source_sha256, storage_key)
        VALUES (%s, %s, 1, %s, %s)
        ON CONFLICT (document_source_id, version_no) DO UPDATE SET
            source_sha256 = EXCLUDED.source_sha256,
            storage_key = EXCLUDED.storage_key
        RETURNING id
        """,
        (version_id, source_id, source_sha256, _official_gold_storage_key()),
    )
    return _fetch_id(cursor)


def _upsert_official_parse_job(
    cursor,
    *,
    source_id: str,
    version_id: str,
    source_key: str,
) -> str:
    parse_job_id = _stable_uuid("official-gold-parse-job", source_key)
    cursor.execute(
        """
        INSERT INTO parse_jobs (
            id, document_source_id, document_version_id, parser_name, parser_version,
            status, completed_at
        )
        VALUES (%s, %s, %s, 'official-gold-import', '0.1', 'succeeded', now())
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = now()
        RETURNING id
        """,
        (parse_job_id, source_id, version_id),
    )
    return _fetch_id(cursor)


def _upsert_official_parsed_document(
    cursor,
    *,
    source_id: str,
    version_id: str,
    parse_job_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    parsed_document_id = _stable_uuid("official-gold-parsed-document", source_key)
    book_slug = str((rows[0] if rows else {}).get("book_slug") or source_key).strip()
    learning = dict(((learning_by_book or {}).get(book_slug) or {}).get("learning") or {})
    cursor.execute(
        """
        INSERT INTO parsed_documents (
            id, document_source_id, document_version_id, parse_job_id,
            parser_name, parser_version, title, markdown, metadata, outline, warnings
        )
        VALUES (%s, %s, %s, %s, 'official-gold-import', '0.1', %s, '', %s::jsonb, '[]'::jsonb, '[]'::jsonb)
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
            _source_title(rows),
            _json({"source_key": source_key, "chunk_count": len(rows), "document_format": "official_gold_jsonl", "learning": learning}),
        ),
    )
    return _fetch_id(cursor)


def _upsert_official_document_chunk(
    cursor,
    *,
    parsed_document_id: str,
    row: dict[str, Any],
    ordinal: int,
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    chunk_id = _uuid_from_row_chunk_id(row)
    section_path = _section_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    source_anchor = _source_anchor(row)
    toc_path = _toc_path(row)
    chunk_text = _normalized_chunk_text(row)
    metadata = _official_chunk_metadata(row, ordinal=ordinal, learning_by_book=learning_by_book)
    cursor.execute(
        """
        INSERT INTO document_chunks (
            id, parsed_document_id, chunk_key, ordinal, chunk_type, markdown,
            embedding_text, token_count, page_start, page_end, section_path,
            section_number, heading_title, source_anchor, toc_path,
            asset_ids, metadata, repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s::jsonb,
            %s, %s, %s, %s::jsonb, '[]'::jsonb, %s::jsonb,
            (
                SELECT ds.repository_id
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ),
            '', 'global_shared', 'official_docs'
        )
        ON CONFLICT (id) DO UPDATE SET
            parsed_document_id = EXCLUDED.parsed_document_id,
            chunk_key = EXCLUDED.chunk_key,
            ordinal = EXCLUDED.ordinal,
            chunk_type = EXCLUDED.chunk_type,
            markdown = EXCLUDED.markdown,
            embedding_text = EXCLUDED.embedding_text,
            token_count = EXCLUDED.token_count,
            section_path = EXCLUDED.section_path,
            section_number = EXCLUDED.section_number,
            heading_title = EXCLUDED.heading_title,
            source_anchor = EXCLUDED.source_anchor,
            toc_path = EXCLUDED.toc_path,
            metadata = EXCLUDED.metadata,
            repository_id = EXCLUDED.repository_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope
        RETURNING id
        """,
        (
            chunk_id,
            parsed_document_id,
            chunk_id,
            int(row.get("ordinal") if row.get("ordinal") is not None else ordinal),
            str(row.get("chunk_type") or "reference"),
            chunk_text,
            chunk_text,
            len(chunk_text.split()),
            _json(section_path),
            section_number,
            heading_title,
            source_anchor,
            _json(toc_path),
            _json(metadata),
            parsed_document_id,
        ),
    )
    return _fetch_id(cursor)


__all__ = [
    "OfficialGoldImportSummary",
    "build_official_gold_import_plan",
    "import_official_gold_chunks",
]
