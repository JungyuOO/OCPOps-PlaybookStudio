"""PostgreSQL course runtime readiness summaries for deployment checks."""

from __future__ import annotations

from typing import Any

from play_book_studio.db.course_repository import DEFAULT_COURSE_SLUG


def load_course_runtime_status(
    connection,
    *,
    course_slug: str = DEFAULT_COURSE_SLUG,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(1)::int
            FROM course_chunks
            WHERE course_slug = %s
            """,
            (course_slug,),
        )
        chunk_count = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            """
            SELECT count(1)::int, COALESCE(sum(byte_size), 0)::bigint
            FROM course_assets
            WHERE course_slug = %s
            """,
            (course_slug,),
        )
        asset_row = cursor.fetchone() or [0, 0]
        asset_count = int(asset_row[0] or 0)
        asset_total_bytes = int(asset_row[1] or 0)
        cursor.execute(
            """
            SELECT count(1)::int, COALESCE(max(stage_count), 0)::int, COALESCE(max(stop_count), 0)::int
            FROM course_manifests
            WHERE course_slug = %s AND manifest_key = 'course_v1'
            """,
            (course_slug,),
        )
        manifest_row = cursor.fetchone() or [0, 0, 0]
        manifest_count = int(manifest_row[0] or 0)
        stage_count = int(manifest_row[1] or 0)
        stop_count = int(manifest_row[2] or 0)

    return {
        "database": "postgres",
        "course_slug": course_slug,
        "chunk_count": chunk_count,
        "asset_count": asset_count,
        "asset_total_bytes": asset_total_bytes,
        "manifest_count": manifest_count,
        "stage_count": stage_count,
        "stop_count": stop_count,
        "has_chunks": chunk_count > 0,
        "has_assets": asset_count > 0,
        "has_manifest": manifest_count > 0 and stage_count > 0,
        "ready": chunk_count > 0 and asset_count > 0 and manifest_count > 0 and stage_count > 0,
    }


def disabled_course_runtime_status(*, course_slug: str = DEFAULT_COURSE_SLUG) -> dict[str, Any]:
    return {
        "database": "disabled",
        "course_slug": course_slug,
        "chunk_count": 0,
        "asset_count": 0,
        "asset_total_bytes": 0,
        "manifest_count": 0,
        "stage_count": 0,
        "stop_count": 0,
        "has_chunks": False,
        "has_assets": False,
        "has_manifest": False,
        "ready": False,
    }


def build_course_runtime_status(
    *,
    database_url: str,
    course_slug: str = DEFAULT_COURSE_SLUG,
) -> dict[str, Any]:
    if not database_url.strip():
        return disabled_course_runtime_status(course_slug=course_slug)
    import psycopg

    try:
        with psycopg.connect(database_url) as connection:
            return load_course_runtime_status(connection, course_slug=course_slug)
    except Exception as exc:  # noqa: BLE001
        payload = disabled_course_runtime_status(course_slug=course_slug)
        payload["database"] = "error"
        payload["error"] = str(exc)
        return payload


__all__ = [
    "build_course_runtime_status",
    "disabled_course_runtime_status",
    "load_course_runtime_status",
]
