from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.db.migrations import list_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_list_migrations_includes_ingestion_foundation():
    migrations = list_migrations(REPO_ROOT / "db" / "migrations")

    versions = [migration.version for migration in migrations]

    assert versions == [
        "0000_schema_migrations",
        "0001_ingestion_foundation",
        "0002_learning_foundation",
        "0003_terminal_learning_runtime",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)
    assert "document_chunks" in migrations[1].sql
    assert "qwen_description" in migrations[1].sql
    assert "learning_paths" in migrations[2].sql
    assert "command_checks" in migrations[2].sql
    assert "terminal_sessions" in migrations[-1].sql
    assert "command_check_results" in migrations[-1].sql


def test_db_migrate_parser_accepts_dry_run_args():
    args = build_parser().parse_args(
        [
            "db-migrate",
            "--root-dir",
            str(REPO_ROOT),
            "--dry-run",
        ]
    )

    assert args.command == "db-migrate"
    assert args.dry_run is True
    assert args.root_dir == REPO_ROOT
    assert args.migrations_dir == Path("db/migrations")
