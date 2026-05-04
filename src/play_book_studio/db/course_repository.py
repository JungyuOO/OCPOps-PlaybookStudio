"""Persistence helpers for Study-docs course runtime chunks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
