from __future__ import annotations

from play_book_studio.db.official_documents import load_official_manifest_entries


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        self.executed_sql = sql

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_load_official_manifest_entries_shapes_db_rows() -> None:
    connection = _Connection(
        [
            (
                "machine_configuration",
                "Machine configuration",
                "/playbooks/wiki-runtime/active/machine_configuration/index.html",
                "https://docs.example/machine_configuration",
                "machine_configuration/index.html",
                "official",
                "official_docs",
                "global_shared",
                {
                    "book_slug": "machine_configuration",
                    "source_lane": "official_ko",
                    "topic_path": ["Operations"],
                    "section_family": ["Machine config"],
                },
                42,
                12,
                40,
                8,
                2,
            )
        ]
    )

    entries = load_official_manifest_entries(connection)

    assert entries == [
        {
            "book_slug": "machine_configuration",
            "title": "Machine configuration",
            "viewer_path": "/playbooks/wiki-runtime/active/machine_configuration/index.html",
            "docs_viewer_path": "/playbooks/wiki-runtime/active/machine_configuration/index.html",
            "source_url": "https://docs.example/machine_configuration",
            "source_candidate_path": "https://docs.example/machine_configuration",
            "source_relative_path": "machine_configuration/index.html",
            "source_kind": "official",
            "source_scope": "official_docs",
            "source_lane": "official_ko",
            "visibility": "global_shared",
            "grade": "Gold",
            "approval_state": "approved",
            "publication_state": "published",
            "parser_backend": "postgres",
            "topic_path": ["Operations"],
            "section_family": ["Machine config"],
            "source_relative_paths": [],
            "chunk_count": 42,
            "section_count": 12,
            "body_language_guess": "ko",
            "language_quality": "ko",
            "hangul_chunk_count": 40,
            "latin_chunk_count": 8,
            "latin_only_chunk_count": 2,
            "hangul_chunk_ratio": 0.9524,
            "latin_only_chunk_ratio": 0.0476,
            "metadata": {
                "book_slug": "machine_configuration",
                "source_lane": "official_ko",
                "topic_path": ["Operations"],
                "section_family": ["Machine config"],
                "body_language_guess": "ko",
                "language_quality": "ko",
                "hangul_chunk_count": 40,
                "latin_chunk_count": 8,
                "latin_only_chunk_count": 2,
                "hangul_chunk_ratio": 0.9524,
                "latin_only_chunk_ratio": 0.0476,
            },
        }
    ]


def test_load_official_manifest_entries_skips_rows_without_metadata_book_slug() -> None:
    connection = _Connection(
        [
            (
                None,
                "Filename fallback must not publish",
                "/playbooks/wiki-runtime/active/file_only/index.html",
                "",
                "",
                "official",
                "official_docs",
                "global_shared",
                {},
                3,
                1,
                0,
                3,
                3,
            )
        ]
    )

    entries = load_official_manifest_entries(connection)

    assert entries == []
