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
                    "source_lane": "official_ko",
                    "topic_path": ["Operations"],
                    "section_family": ["Machine config"],
                },
                42,
                12,
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
            "metadata": {
                "source_lane": "official_ko",
                "topic_path": ["Operations"],
                "section_family": ["Machine config"],
            },
        }
    ]
