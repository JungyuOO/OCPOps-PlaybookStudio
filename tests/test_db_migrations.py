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
        "0004_repository_session_scope",
        "0005_course_runtime_chunks",
        "0006_course_runtime_assets",
        "0007_course_runtime_manifest",
        "0008_chunk_runtime_enrichment",
        "0008_document_topology_snapshots",
        "0009_qdrant_payload_contract",
        "0009_upload_pipeline_events_quality_snapshots",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)
    assert "document_chunks" in migrations[1].sql
    assert "qwen_description" in migrations[1].sql
    assert "learning_paths" in migrations[2].sql
    assert "command_checks" in migrations[2].sql
    assert "terminal_sessions" in migrations[3].sql
    assert "command_check_results" in migrations[3].sql
    assert "repositories" in migrations[4].sql
    assert "chat_sessions" in migrations[4].sql
    assert "section_number" in migrations[4].sql
    assert "course_chunks" in migrations[5].sql
    assert "course_assets" in migrations[6].sql
    assert "course_manifests" in migrations[7].sql
    assert "navigation_only" in migrations[8].sql
    assert "starter_question_candidates" in migrations[8].sql
    migration_sql = {migration.version: migration.sql for migration in migrations}
    assert "document_topology_snapshots" in migration_sql["0008_document_topology_snapshots"]
    assert "input_fingerprint" in migration_sql["0008_document_topology_snapshots"]
    assert "payload_version" in migration_sql["0009_qdrant_payload_contract"]
    assert "upload_pipeline_events" in migration_sql["0009_upload_pipeline_events_quality_snapshots"]
    assert "document_quality_snapshots" in migration_sql["0009_upload_pipeline_events_quality_snapshots"]


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


def test_course_chunk_import_parser_accepts_dry_run_args():
    args = build_parser().parse_args(
        [
            "course-chunk-import",
            "--root-dir",
            str(REPO_ROOT),
            "--course-dir",
            "corpus/sources/kmsc/parsed-preview/course_pbs",
            "--limit",
            "3",
            "--dry-run",
        ]
    )

    assert args.command == "course-chunk-import"
    assert args.root_dir == REPO_ROOT
    assert args.course_dir == Path("corpus/sources/kmsc/parsed-preview/course_pbs")
    assert args.limit == 3
    assert args.dry_run is True


def test_kmsc_course_import_parser_accepts_dry_run_args():
    args = build_parser().parse_args(
        [
            "kmsc-course-import",
            "--root-dir",
            str(REPO_ROOT),
            "--course-dir",
            "corpus/sources/kmsc/parsed-preview/course_pbs",
            "--index",
            "--collection",
            "openshift_docs",
            "--dry-run",
        ]
    )

    assert args.command == "kmsc-course-import"
    assert args.root_dir == REPO_ROOT
    assert args.course_dir == Path("corpus/sources/kmsc/parsed-preview/course_pbs")
    assert args.index is True
    assert args.collection == "openshift_docs"
    assert args.dry_run is True
