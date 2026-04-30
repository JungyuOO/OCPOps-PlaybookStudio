"""PostgreSQL migration runner for Play Book Studio."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    checksum: str
    path: Path
    sql: str


def list_migrations(migrations_dir: Path) -> list[Migration]:
    root = migrations_dir.resolve()
    if not root.exists():
        raise FileNotFoundError(f"migrations directory does not exist: {root}")
    migrations: list[Migration] = []
    for path in sorted(root.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append(
            Migration(
                version=path.stem,
                checksum=checksum,
                path=path,
                sql=sql,
            )
        )
    if not migrations:
        raise ValueError(f"no migration files found in: {root}")
    return migrations


def apply_migrations(database_url: str, migrations_dir: Path) -> dict:
    if not database_url.strip():
        raise ValueError("database_url is required")

    migrations = list_migrations(migrations_dir)

    import psycopg

    applied: list[str] = []
    skipped: list[str] = []
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version text PRIMARY KEY,
                    checksum text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute("SELECT version, checksum FROM schema_migrations")
            existing = {str(version): str(checksum) for version, checksum in cursor.fetchall()}

        for migration in migrations:
            current_checksum = existing.get(migration.version)
            if current_checksum == migration.checksum:
                skipped.append(migration.version)
                continue
            if current_checksum is not None:
                raise ValueError(
                    "migration checksum mismatch for "
                    f"{migration.version}: database={current_checksum} file={migration.checksum}"
                )

            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(migration.sql)
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (version, checksum)
                        VALUES (%s, %s)
                        """,
                        (migration.version, migration.checksum),
                    )
            applied.append(migration.version)

    return {
        "migration_count": len(migrations),
        "applied": applied,
        "skipped": skipped,
    }
