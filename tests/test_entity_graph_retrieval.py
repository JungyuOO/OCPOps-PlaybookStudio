from __future__ import annotations

from types import SimpleNamespace

import pytest

from play_book_studio.db import graph_repository
from play_book_studio.retrieval import entity_graph
from play_book_studio.retrieval.entity_graph import maybe_expand_entity_graph
from play_book_studio.retrieval.models import RetrievalHit, SessionContext


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor()


def _settings(**overrides):
    values = {
        "entity_graph_enabled": True,
        "database_url": "postgresql://test",
        "entity_graph_max_neighbors": 20,
        "entity_graph_max_injected_hits": 3,
        "entity_graph_boost_weight": 0.08,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _retriever(**overrides):
    return SimpleNamespace(settings=_settings(**overrides))


def _hit(chunk_id: str, *, score: float, book_slug: str = "uploaded-documents") -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="결제 API 장애",
        section="Route 503 점검",
        anchor=chunk_id,
        source_url="https://docs.example.test",
        viewer_path=f"/uploads/documents/src-1/index.html#{chunk_id}",
        text="결제 API Route가 503이면 ori-pay-prod namespace를 확인한다.",
        source="hybrid",
        raw_score=score,
        fused_score=score,
        source_scope="user_upload",
        visibility="workspace_shared",
    )


def _payload_row(chunk_id: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_key": f"doc:{chunk_id}",
        "ordinal": 0,
        "chunk_type": "document",
        "markdown": "PVC txn-ledger-pvc는 ori-pay-prod namespace에서 사용한다.",
        "embedding_text": "PVC txn-ledger-pvc",
        "section_path": ["PVC Pending 점검"],
        "section_number": "4",
        "heading_title": "PVC Pending 점검 기준",
        "source_anchor": chunk_id,
        "toc_path": [],
        "asset_ids": [],
        "repository_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "owner_user_id": "",
        "visibility": "workspace_shared",
        "source_scope": "user_upload",
        "chunk_metadata": {},
        "parsed_document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "document_title": "오리은행 운영 점검 기준",
        "parsed_metadata": {},
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "filename": "ori-bank.md",
        "storage_key": "uploads/sources/x/ori-bank.md",
        "source_kind": "upload",
        "source_metadata": {},
        "created_by": "owner-1",
    }


def _patch_graph_data(
    monkeypatch,
    *,
    name_entities=None,
    chunk_entities=None,
    relations=None,
    evidence_rows=None,
    lightspeed_rows=None,
    payload_rows=None,
):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeConnection())
    monkeypatch.setattr(
        graph_repository,
        "find_entities_by_names",
        lambda cursor, names, *, scope: list(name_entities or []),
    )
    monkeypatch.setattr(
        graph_repository,
        "find_entities_for_chunks",
        lambda cursor, chunk_ids, *, scope: list(chunk_entities or []),
    )
    monkeypatch.setattr(
        graph_repository,
        "expand_relations",
        lambda cursor, entity_ids, *, scope, limit: list(relations or []),
    )
    monkeypatch.setattr(
        graph_repository,
        "load_evidence_chunk_rows",
        lambda cursor, entity_ids, *, scope, limit: list(evidence_rows or []),
    )
    monkeypatch.setattr(
        graph_repository,
        "load_lightspeed_evidence_rows",
        lambda cursor, entity_ids, *, limit: list(lightspeed_rows or []),
    )
    monkeypatch.setattr(
        entity_graph,
        "load_document_chunk_payload_rows",
        lambda connection, *, chunk_ids: dict(payload_rows or {}),
    )


_NAMESPACE_ENTITY = {
    "entity_id": "11111111-1111-1111-1111-111111111111",
    "entity_kind": "namespace",
    "name": "ori-pay-prod",
    "entity_key": "namespace:ori-pay-prod",
    "display_name": "ori-pay-prod",
}
_ROUTE_ENTITY = {
    "entity_id": "22222222-2222-2222-2222-222222222222",
    "entity_kind": "route",
    "name": "pay-api",
    "entity_key": "route:pay-api",
    "display_name": "pay-api",
}
_RELATION_ROW = {
    "relation_id": "r-1",
    "relation_type": "in_namespace",
    "confidence": 1.0,
    "quote": "oc get route pay-api -n ori-pay-prod",
    "source_kind": "chunk",
    "source_ref": "",
    "chunk_id": "chunk-1",
    "subject_entity_id": _ROUTE_ENTITY["entity_id"],
    "subject_key": "route:pay-api",
    "subject_kind": "route",
    "subject_name": "pay-api",
    "object_entity_id": _NAMESPACE_ENTITY["entity_id"],
    "object_key": "namespace:ori-pay-prod",
    "object_kind": "namespace",
    "object_name": "ori-pay-prod",
}


def test_disabled_flag_returns_hits_unchanged():
    hits = [_hit("chunk-1", score=0.8)]

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(entity_graph_enabled=False),
        query="결제 API Route 503",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    assert result_hits is hits
    assert payload["enabled"] is False
    assert payload["status"] == "skipped"
    assert payload["reason"] == "entity_graph_disabled"


def test_missing_database_url_skips():
    hits = [_hit("chunk-1", score=0.8)]

    _, payload = maybe_expand_entity_graph(
        _retriever(database_url=""),
        query="결제 API Route 503",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_database_url"


def test_no_hits_skips():
    _, payload = maybe_expand_entity_graph(
        _retriever(),
        query="결제 API Route 503",
        hits=[],
        context=SessionContext(),
        candidate_k=10,
    )

    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_hits"


def test_no_seed_entities_returns_hits_unchanged(monkeypatch):
    _patch_graph_data(monkeypatch)
    hits = [_hit("chunk-1", score=0.8)]

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(),
        query="오늘 날씨 어때?",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    assert [hit.chunk_id for hit in result_hits] == ["chunk-1"]
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_seed_entities"


def test_boosts_hits_with_entity_evidence(monkeypatch):
    _patch_graph_data(
        monkeypatch,
        chunk_entities=[{**_NAMESPACE_ENTITY, "chunk_id": "chunk-1"}],
        relations=[_RELATION_ROW],
        evidence_rows=[
            {
                "entity_id": _NAMESPACE_ENTITY["entity_id"],
                "entity_key": "namespace:ori-pay-prod",
                "entity_kind": "namespace",
                "chunk_id": "chunk-1",
                "quote": "| 업무 namespace | ori-pay-prod |",
                "confidence": 0.9,
            },
            {
                "entity_id": _ROUTE_ENTITY["entity_id"],
                "entity_key": "route:pay-api",
                "entity_kind": "route",
                "chunk_id": "chunk-1",
                "quote": "oc get route pay-api -n ori-pay-prod",
                "confidence": 1.0,
            },
        ],
    )
    hits = [_hit("chunk-1", score=0.5), _hit("chunk-2", score=0.6)]
    trace_events: list[dict] = []
    timings: dict[str, float] = {}

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(),
        query="오리은행 결제 API Route가 503이면 어떤 namespace부터 확인해?",
        hits=hits,
        context=SessionContext(owner_user_id="user-1"),
        candidate_k=10,
        trace_callback=trace_events.append,
        timings_ms=timings,
    )

    boosted = next(hit for hit in result_hits if hit.chunk_id == "chunk-1")
    untouched = next(hit for hit in result_hits if hit.chunk_id == "chunk-2")
    assert boosted.component_scores["entity_graph_score"] == pytest.approx(0.16)
    assert boosted.component_scores["entity_graph_entity_count"] == 2.0
    assert boosted.fused_score == pytest.approx(0.66)
    assert "entity_graph_score" not in untouched.component_scores
    # Boosted hit overtakes the previously higher-scored chunk-2.
    assert result_hits[0].chunk_id == "chunk-1"

    assert payload["status"] == "expanded"
    assert payload["boosted_count"] == 1
    assert payload["seed_entities"] == ["namespace:ori-pay-prod"]
    assert payload["relations"][0]["relation_type"] == "in_namespace"
    assert payload["relations"][0]["object"] == "namespace:ori-pay-prod"
    assert "entity_graph" in timings
    statuses = [event["status"] for event in trace_events if event.get("step") == "entity_graph"]
    assert statuses == ["running", "done"]


def test_injects_evidence_chunks_below_boosted_hits(monkeypatch):
    _patch_graph_data(
        monkeypatch,
        chunk_entities=[{**_NAMESPACE_ENTITY, "chunk_id": "chunk-1"}],
        relations=[_RELATION_ROW],
        evidence_rows=[
            {
                "entity_id": _NAMESPACE_ENTITY["entity_id"],
                "entity_key": "namespace:ori-pay-prod",
                "entity_kind": "namespace",
                "chunk_id": "chunk-1",
                "quote": "| 업무 namespace | ori-pay-prod |",
                "confidence": 0.9,
            },
            {
                "entity_id": _ROUTE_ENTITY["entity_id"],
                "entity_key": "route:pay-api",
                "entity_kind": "route",
                "chunk_id": "chunk-9",
                "quote": "oc get pvc txn-ledger-pvc -n ori-pay-prod",
                "confidence": 1.0,
            },
        ],
        payload_rows={"chunk-9": _payload_row("chunk-9")},
    )
    hits = [_hit("chunk-1", score=0.5)]

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(),
        query="결제 API Route 503 점검",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    injected = next(hit for hit in result_hits if hit.chunk_id == "chunk-9")
    boosted = next(hit for hit in result_hits if hit.chunk_id == "chunk-1")
    assert injected.source == "entity_graph"
    assert injected.fused_score < boosted.fused_score
    assert injected.source_scope == "user_upload"  # hydrated scope fields survive filters
    assert injected.book_slug == "uploaded-documents"
    assert payload["injected_count"] == 1
    assert payload["injected_chunk_ids"] == ["chunk-9"]


def test_injection_respects_max_injected_hits(monkeypatch):
    evidence_rows = [
        {
            "entity_id": _NAMESPACE_ENTITY["entity_id"],
            "entity_key": "namespace:ori-pay-prod",
            "entity_kind": "namespace",
            "chunk_id": f"chunk-extra-{index}",
            "quote": f"quote {index}",
            "confidence": 1.0,
        }
        for index in range(5)
    ] + [
        {
            "entity_id": _NAMESPACE_ENTITY["entity_id"],
            "entity_key": "namespace:ori-pay-prod",
            "entity_kind": "namespace",
            "chunk_id": "chunk-1",
            "quote": "anchor",
            "confidence": 1.0,
        }
    ]
    _patch_graph_data(
        monkeypatch,
        chunk_entities=[{**_NAMESPACE_ENTITY, "chunk_id": "chunk-1"}],
        evidence_rows=evidence_rows,
        payload_rows={f"chunk-extra-{index}": _payload_row(f"chunk-extra-{index}") for index in range(5)},
    )
    hits = [_hit("chunk-1", score=0.5)]

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(entity_graph_max_injected_hits=2),
        query="결제 API 점검",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    assert payload["injected_count"] == 2
    assert len(result_hits) == 3


def test_database_error_returns_original_hits(monkeypatch):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeConnection())

    def broken(cursor, names, *, scope):
        raise RuntimeError("relation graph_entities does not exist")

    monkeypatch.setattr(graph_repository, "find_entities_by_names", broken)
    hits = [_hit("chunk-1", score=0.5)]
    trace_events: list[dict] = []

    result_hits, payload = maybe_expand_entity_graph(
        _retriever(),
        query="결제 API Route 503",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
        trace_callback=trace_events.append,
    )

    assert result_hits is hits
    assert payload["status"] == "failed"
    assert "graph_entities" in payload["reason"]
    statuses = [event["status"] for event in trace_events if event.get("step") == "entity_graph"]
    assert statuses == ["running", "warning"]


def test_kind_hints_order_seed_entities(monkeypatch):
    pvc_entity = {
        "entity_id": "33333333-3333-3333-3333-333333333333",
        "entity_kind": "pvc",
        "name": "txn-ledger-pvc",
        "entity_key": "pvc:txn-ledger-pvc",
        "display_name": "txn-ledger-pvc",
    }
    _patch_graph_data(
        monkeypatch,
        chunk_entities=[
            {**_NAMESPACE_ENTITY, "chunk_id": "chunk-1"},
            {**pvc_entity, "chunk_id": "chunk-1"},
        ],
        evidence_rows=[],
    )
    hits = [_hit("chunk-1", score=0.5)]

    _, payload = maybe_expand_entity_graph(
        _retriever(),
        query="PVC Pending이면 어떤 PVC를 봐야 해?",
        hits=hits,
        context=SessionContext(),
        candidate_k=10,
    )

    # PVC kind hint ranks the pvc entity ahead of the namespace entity.
    assert payload["seed_entities"][0] == "pvc:txn-ledger-pvc"
