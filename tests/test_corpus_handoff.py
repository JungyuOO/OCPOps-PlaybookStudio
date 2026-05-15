from play_book_studio.db.corpus_handoff import build_corpus_handoff_report


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((sql, tuple(params)))

    def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self):
        return self.cursor_obj


def test_corpus_handoff_filters_private_sources_by_owner_scope() -> None:
    connection = _FakeConnection()

    report = build_corpus_handoff_report(connection, owner_user_id="owner-a")

    assert report["schema"] == "corpus_handoff_report_v1"
    assert len(connection.cursor_obj.calls) == 4
    for sql, params in connection.cursor_obj.calls:
        assert "ds.visibility IN ('workspace_shared', 'global_shared')" in sql
        assert "ds.owner_user_id = %s" in sql
        assert params[0:2] == ("owner-a", "owner-a")
