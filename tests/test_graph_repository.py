from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from play_book_studio.db import graph_repository
from play_book_studio.db.graph_repository import GraphScopeFilter
from play_book_studio.graph import service
from play_book_studio.graph.rules import RuleBasedEntityExtractor


@dataclass(frozen=True)
class Column:
    name: str


class ScriptedCursor:
    """Cursor fake that replays scripted results per execute call."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, tuple]] = []
        self.description = None
        self.rowcount = 0
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), params))
        step = self.results.pop(0) if self.results else {}
        self._rows = list(step.get("rows", []))
        columns = step.get("columns")
        self.description = [Column(name) for name in columns] if columns else None
        self.rowcount = step.get("rowcount", len(self._rows))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, cursor: ScriptedCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_quote_sha256_matches_hashlib():
    assert graph_repository.quote_sha256("abc") == hashlib.sha256(b"abc").hexdigest()
    assert graph_repository.quote_sha256("") == hashlib.sha256(b"").hexdigest()


def test_upsert_entity_builds_entity_key_and_conflict_sql():
    cursor = ScriptedCursor([{"rows": [("entity-1",)]}])

    entity_id = graph_repository.upsert_entity(
        cursor,
        entity_kind="route",
        name="pay-api",
        display_name="pay-api",
        label="Route",
        source_scope="user_upload",
        owner_user_id="",
    )

    assert entity_id == "entity-1"
    sql, params = cursor.calls[0]
    assert "INSERT INTO graph_entities" in sql
    assert "ON CONFLICT (entity_key, source_scope, owner_user_id)" in sql
    assert "jsonb_array_elements_text" in sql
    assert "route:pay-api" in params
    assert json.loads(params[4]) == ["Route"]


def test_insert_mention_computes_quote_hash_and_bumps_mention_count():
    cursor = ScriptedCursor([{"rows": [("mention-1",)]}, {}])

    inserted = graph_repository.insert_mention(
        cursor,
        entity_id="entity-1",
        chunk_id="chunk-1",
        document_source_id="source-1",
        parsed_document_id="parsed-1",
        quote="oc get route pay-api -n ori-pay-prod",
        locator={"pattern": "oc_command"},
        source_scope="user_upload",
        owner_user_id="user-1",
        visibility="private_user",
    )

    assert inserted is True
    assert len(cursor.calls) == 2
    insert_sql, insert_params = cursor.calls[0]
    assert "ON CONFLICT" in insert_sql
    assert "DO NOTHING" in insert_sql
    assert graph_repository.quote_sha256("oc get route pay-api -n ori-pay-prod") in insert_params
    update_sql, _ = cursor.calls[1]
    assert "mention_count = mention_count + 1" in update_sql


def test_insert_mention_conflict_skips_mention_count_update():
    cursor = ScriptedCursor([{"rows": []}])

    inserted = graph_repository.insert_mention(
        cursor,
        entity_id="entity-1",
        chunk_id="chunk-1",
        quote="dup",
        source_scope="user_upload",
    )

    assert inserted is False
    assert len(cursor.calls) == 1


def test_insert_relation_uses_dedup_conflict_target():
    cursor = ScriptedCursor([{"rows": [("relation-1",)]}])

    inserted = graph_repository.insert_relation(
        cursor,
        subject_entity_id="entity-route",
        object_entity_id="entity-ns",
        relation_type="in_namespace",
        chunk_id="chunk-1",
        quote="oc get route pay-api -n ori-pay-prod",
        source_scope="user_upload",
    )

    assert inserted is True
    sql, params = cursor.calls[0]
    assert "INSERT INTO graph_entity_relations" in sql
    assert "subject_entity_id, object_entity_id, relation_type, source_kind" in sql
    assert "in_namespace" in params


def test_delete_document_source_graph_removes_relations_then_mentions():
    cursor = ScriptedCursor([{"rowcount": 3}, {"rowcount": 7}])

    summary = graph_repository.delete_document_source_graph(
        cursor, document_source_id="source-1"
    )

    assert summary == {"deleted_mentions": 7, "deleted_relations": 3}
    assert "graph_entity_relations" in cursor.calls[0][0]
    assert "graph_entity_mentions" in cursor.calls[1][0]


def test_find_entities_by_names_returns_empty_without_names():
    cursor = ScriptedCursor()

    assert graph_repository.find_entities_by_names(cursor, [], scope=GraphScopeFilter()) == []
    assert cursor.calls == []


def test_find_entities_by_names_applies_owner_and_scope_filters():
    columns = ["entity_id", "entity_kind", "name", "entity_key", "display_name", "aliases"]
    cursor = ScriptedCursor(
        [
            {
                "rows": [
                    (
                        "entity-1",
                        "namespace",
                        "ori-pay-prod",
                        "namespace:ori-pay-prod",
                        "ori-pay-prod",
                        ["결제 API namespace"],
                    )
                ],
                "columns": columns,
            }
        ]
    )

    rows = graph_repository.find_entities_by_names(
        cursor,
        ["ori-pay-prod"],
        scope=GraphScopeFilter(
            owner_user_id="user-1",
            enabled_source_scopes=("user_upload", "official_docs"),
        ),
    )

    assert rows[0]["entity_key"] == "namespace:ori-pay-prod"
    sql, params = cursor.calls[0]
    assert "owner_user_id = '' OR owner_user_id = %s" in sql
    assert "source_scope = ANY(%s)" in sql
    assert ["user_upload", "official_docs"] in params


def test_expand_relations_queries_both_directions_with_scope():
    cursor = ScriptedCursor([{"rows": [], "columns": ["relation_id"]}])

    graph_repository.expand_relations(
        cursor,
        ["entity-1"],
        scope=GraphScopeFilter(owner_user_id="user-1"),
        limit=5,
    )

    sql, params = cursor.calls[0]
    assert "r.subject_entity_id = ANY(%s::uuid[]) OR r.object_entity_id = ANY(%s::uuid[])" in sql
    assert "r.visibility <> 'private_user' OR r.owner_user_id = %s" in sql
    assert params[-1] == 5


def test_load_evidence_chunk_rows_applies_latest_document_guard():
    cursor = ScriptedCursor([{"rows": [], "columns": ["entity_id"]}])

    graph_repository.load_evidence_chunk_rows(
        cursor,
        ["entity-1"],
        scope=GraphScopeFilter(owner_user_id="user-1"),
        limit=10,
    )

    sql, _ = cursor.calls[0]
    assert "gem.source_kind = 'chunk'" in sql
    assert "latest_pd" in sql
    assert "c.source_scope <> 'user_upload'" in sql


def test_load_lightspeed_evidence_rows_filters_artifact_mentions():
    cursor = ScriptedCursor([{"rows": [], "columns": ["entity_id"]}])

    graph_repository.load_lightspeed_evidence_rows(cursor, ["entity-1"], limit=4)

    sql, params = cursor.calls[0]
    assert "gem.source_kind = 'lightspeed_artifact'" in sql
    assert params[-1] == 4


def _patch_repository_writes(monkeypatch):
    recorded = {"deletes": [], "upserts": [], "mentions": [], "relations": []}

    def fake_delete(cursor, *, document_source_id):
        recorded["deletes"].append(document_source_id)
        return {"deleted_mentions": 0, "deleted_relations": 0}

    def fake_upsert(cursor, *, entity_kind, name, **kwargs):
        recorded["upserts"].append({"entity_kind": entity_kind, "name": name, **kwargs})
        return f"id-{entity_kind}:{name}"

    def fake_mention(cursor, **kwargs):
        recorded["mentions"].append(kwargs)
        return True

    def fake_relation(cursor, **kwargs):
        recorded["relations"].append(kwargs)
        return True

    monkeypatch.setattr(graph_repository, "delete_document_source_graph", fake_delete)
    monkeypatch.setattr(graph_repository, "upsert_entity", fake_upsert)
    monkeypatch.setattr(graph_repository, "insert_mention", fake_mention)
    monkeypatch.setattr(graph_repository, "insert_relation", fake_relation)
    return recorded


def test_extract_graph_for_parsed_document_writes_scoped_rows(monkeypatch):
    recorded = _patch_repository_writes(monkeypatch)
    chunk_columns = [
        "chunk_id",
        "markdown",
        "section_path",
        "source_scope",
        "repository_id",
        "owner_user_id",
        "visibility",
    ]
    cursor = ScriptedCursor(
        [
            {
                "rows": [
                    (
                        "chunk-1",
                        "```bash\noc get route pay-api -n ori-pay-prod\n```",
                        ["결제 API 장애 점검"],
                        "user_upload",
                        None,
                        "user-1",
                        "private_user",
                    )
                ],
                "columns": chunk_columns,
            }
        ]
    )

    summary = service.extract_graph_for_parsed_document(
        FakeConnection(cursor),
        parsed_document_id="parsed-1",
        document_source_id="source-1",
        extractor=RuleBasedEntityExtractor(),
    )

    assert recorded["deletes"] == ["source-1"]
    assert summary["chunk_count"] == 1
    assert summary["entity_count"] == 2  # route:pay-api + namespace:ori-pay-prod
    assert summary["mention_count"] == 2
    assert summary["relation_count"] == 1

    # Private uploads keep per-owner entities.
    assert all(item["owner_user_id"] == "user-1" for item in recorded["upserts"])
    mention = recorded["mentions"][0]
    assert mention["chunk_id"] == "chunk-1"
    assert mention["parsed_document_id"] == "parsed-1"
    assert mention["document_source_id"] == "source-1"
    assert mention["source_scope"] == "user_upload"
    assert mention["visibility"] == "private_user"
    assert mention["extractor_version"] == "rule-v1"
    relation = recorded["relations"][0]
    assert relation["subject_entity_id"] == "id-route:pay-api"
    assert relation["object_entity_id"] == "id-namespace:ori-pay-prod"
    assert relation["relation_type"] == "in_namespace"


def test_extract_graph_for_lightspeed_artifact_uses_polymorphic_source(
    monkeypatch, tmp_path: Path
):
    recorded = _patch_repository_writes(monkeypatch)
    artifact_path = tmp_path / "abc123.json"
    artifact_path.write_text(
        json.dumps(
            {
                "artifact_id": "abc123",
                "query": "PipelineRun이 안 떠요",
                "answer": "ci-pipelines namespace에서 확인하세요:\n\noc get pipelinerun -n ci-pipelines",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cursor = ScriptedCursor()

    summary = service.extract_graph_for_lightspeed_artifact(
        FakeConnection(cursor),
        artifact_path=artifact_path,
        extractor=RuleBasedEntityExtractor(),
    )

    assert summary["status"] == "ok"
    assert summary["artifact_id"] == "abc123"
    assert recorded["deletes"] == []
    assert recorded["mentions"]
    for mention in recorded["mentions"]:
        assert mention["source_kind"] == "lightspeed_artifact"
        assert mention["chunk_id"] is None
        assert mention["source_ref"] == "abc123"
        assert mention["source_scope"] == service.LIGHTSPEED_SOURCE_SCOPE


def test_extract_graph_for_lightspeed_artifact_handles_unreadable_file(tmp_path: Path):
    artifact_path = tmp_path / "broken.json"
    artifact_path.write_text("{not json", encoding="utf-8")

    summary = service.extract_graph_for_lightspeed_artifact(
        FakeConnection(ScriptedCursor()),
        artifact_path=artifact_path,
        extractor=RuleBasedEntityExtractor(),
    )

    assert summary["status"] == "unreadable"
    assert summary["mention_count"] == 0
