"""Persistence helpers for Study-docs course runtime chunks."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_COURSE_SLUG = "project-playbook"


@dataclass(frozen=True, slots=True)
class CourseChunkRecord:
    course_slug: str
    chunk_key: str
    stage_id: str
    title: str
    payload: dict[str, Any]
    search_text: str
    source_ref: str
    checksum: str


@dataclass(frozen=True, slots=True)
class CourseAssetRecord:
    course_slug: str
    asset_key: str
    asset_path: str
    content_type: str
    byte_size: int
    checksum: str
    payload: dict[str, Any]
    content: bytes
    source_ref: str


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string_value(value: Any) -> str:
    return str(value or "").strip()


def build_course_chunk_record(
    payload: dict[str, Any],
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
    source_ref: str = "",
) -> CourseChunkRecord:
    chunk_key = _string_value(payload.get("chunk_id"))
    if not chunk_key:
        raise ValueError("course chunk payload requires chunk_id")
    stored_payload = dict(payload)
    stored_payload["chunk_id"] = chunk_key
    search_text = _string_value(
        stored_payload.get("search_text")
        or stored_payload.get("body_md")
        or stored_payload.get("visual_text")
        or stored_payload.get("title")
    )
    checksum = hashlib.sha256(_compact_json(stored_payload).encode("utf-8")).hexdigest()
    return CourseChunkRecord(
        course_slug=_string_value(course_slug) or DEFAULT_COURSE_SLUG,
        chunk_key=chunk_key,
        stage_id=_string_value(stored_payload.get("stage_id")),
        title=_string_value(stored_payload.get("title")),
        payload=stored_payload,
        search_text=search_text,
        source_ref=_string_value(source_ref),
        checksum=checksum,
    )


def _content_type_for_path(path: str) -> str:
    guessed = mimetypes.guess_type(path)[0]
    return guessed or "application/octet-stream"


def build_course_asset_record(
    *,
    asset_key: str,
    asset_path: str,
    content: bytes,
    payload: dict[str, Any] | None = None,
    content_type: str = "",
    course_slug: str = DEFAULT_COURSE_SLUG,
    source_ref: str = "",
) -> CourseAssetRecord:
    normalized_key = _string_value(asset_key) or _string_value(Path(asset_path).name)
    normalized_path = _string_value(asset_path).replace("\\", "/")
    if not normalized_key:
        raise ValueError("course asset requires asset_key")
    if not normalized_path:
        raise ValueError("course asset requires asset_path")
    body = bytes(content)
    metadata = dict(payload or {})
    metadata["asset_key"] = normalized_key
    metadata["asset_path"] = normalized_path
    checksum = hashlib.sha256(body).hexdigest()
    return CourseAssetRecord(
        course_slug=_string_value(course_slug) or DEFAULT_COURSE_SLUG,
        asset_key=normalized_key,
        asset_path=normalized_path,
        content_type=_string_value(content_type) or _content_type_for_path(normalized_path),
        byte_size=len(body),
        checksum=checksum,
        payload=metadata,
        content=body,
        source_ref=_string_value(source_ref),
    )


def load_course_chunks(
    connection,
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT payload
            FROM course_chunks
            WHERE course_slug = %s
            ORDER BY stage_id ASC, chunk_key ASC
            """,
            (_string_value(course_slug) or DEFAULT_COURSE_SLUG,),
        )
        rows: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            payload = row[0]
            if isinstance(payload, dict):
                rows.append(dict(payload))
        return rows


def load_course_chunk(
    connection,
    chunk_key: str,
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT payload
            FROM course_chunks
            WHERE course_slug = %s AND chunk_key = %s
            """,
            (_string_value(course_slug) or DEFAULT_COURSE_SLUG, _string_value(chunk_key)),
        )
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    return dict(row[0])


def load_course_asset_by_path(
    connection,
    asset_path: str,
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT asset_key, asset_path, content_type, content, payload, checksum
            FROM course_assets
            WHERE course_slug = %s AND asset_path = %s
            """,
            (_string_value(course_slug) or DEFAULT_COURSE_SLUG, _string_value(asset_path).replace("\\", "/")),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    content = row[3]
    return {
        "asset_key": str(row[0]),
        "asset_path": str(row[1]),
        "content_type": str(row[2] or "application/octet-stream"),
        "content": bytes(content),
        "payload": dict(row[4]) if isinstance(row[4], dict) else {},
        "checksum": str(row[5] or ""),
    }


def import_course_assets(
    connection,
    assets: list[CourseAssetRecord],
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
    source_ref: str = "",
) -> dict[str, Any]:
    scanned_count = 0
    imported_count = 0
    skipped_count = 0
    with connection.cursor() as cursor:
        for asset in assets:
            scanned_count += 1
            if not asset.asset_key or not asset.asset_path:
                skipped_count += 1
                continue
            cursor.execute(
                """
                INSERT INTO course_assets (
                    course_slug,
                    asset_key,
                    asset_path,
                    content_type,
                    byte_size,
                    checksum,
                    payload,
                    content,
                    source_ref,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, now(), now())
                ON CONFLICT (course_slug, asset_key) DO UPDATE SET
                    asset_path = EXCLUDED.asset_path,
                    content_type = EXCLUDED.content_type,
                    byte_size = EXCLUDED.byte_size,
                    checksum = EXCLUDED.checksum,
                    payload = EXCLUDED.payload,
                    content = EXCLUDED.content,
                    source_ref = EXCLUDED.source_ref,
                    updated_at = now()
                """,
                (
                    asset.course_slug,
                    asset.asset_key,
                    asset.asset_path,
                    asset.content_type,
                    asset.byte_size,
                    asset.checksum,
                    _compact_json(asset.payload),
                    asset.content,
                    _string_value(source_ref) or asset.source_ref,
                ),
            )
            imported_count += 1
    return {
        "course_slug": _string_value(course_slug) or DEFAULT_COURSE_SLUG,
        "source_ref": _string_value(source_ref),
        "scanned_count": scanned_count,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
    }


def import_course_chunks(
    connection,
    chunks: list[dict[str, Any]],
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
    source_ref: str = "",
) -> dict[str, Any]:
    scanned_count = 0
    imported_count = 0
    skipped_count = 0
    with connection.cursor() as cursor:
        for chunk in chunks:
            if not isinstance(chunk, dict):
                skipped_count += 1
                continue
            scanned_count += 1
            try:
                record = build_course_chunk_record(
                    chunk,
                    course_slug=course_slug,
                    source_ref=source_ref,
                )
            except ValueError:
                skipped_count += 1
                continue
            cursor.execute(
                """
                INSERT INTO course_chunks (
                    course_slug,
                    chunk_key,
                    stage_id,
                    title,
                    payload,
                    search_text,
                    source_ref,
                    checksum,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, now(), now())
                ON CONFLICT (course_slug, chunk_key) DO UPDATE SET
                    stage_id = EXCLUDED.stage_id,
                    title = EXCLUDED.title,
                    payload = EXCLUDED.payload,
                    search_text = EXCLUDED.search_text,
                    source_ref = EXCLUDED.source_ref,
                    checksum = EXCLUDED.checksum,
                    updated_at = now()
                """,
                (
                    record.course_slug,
                    record.chunk_key,
                    record.stage_id,
                    record.title,
                    _compact_json(record.payload),
                    record.search_text,
                    record.source_ref,
                    record.checksum,
                ),
            )
            imported_count += 1
    return {
        "course_slug": _string_value(course_slug) or DEFAULT_COURSE_SLUG,
        "source_ref": _string_value(source_ref),
        "scanned_count": scanned_count,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
    }
