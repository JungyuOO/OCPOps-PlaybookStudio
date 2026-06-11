from __future__ import annotations

from types import SimpleNamespace

from play_book_studio.answering.answerer import _apply_customer_context_answer_contract
from play_book_studio.answering.graph_context import load_graph_customer_context_values
from play_book_studio.answering.models import Citation
from play_book_studio.db import graph_repository


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
    values = {"entity_graph_enabled": True, "database_url": "postgresql://test"}
    values.update(overrides)
    return SimpleNamespace(**values)


_ORI_BANK_ENTITIES = [
    {
        "entity_id": "e-repo",
        "entity_kind": "repository_cr",
        "name": "ori-payments-api-repository",
        "entity_key": "repository_cr:ori-payments-api-repository",
        "display_name": "ori-payments-api-repository",
        "aliases": ["Repository CR"],
        "chunk_id": "chunk-cicd",
    },
    {
        "entity_id": "e-ns-ci",
        "entity_kind": "namespace",
        "name": "ci-pipelines",
        "entity_key": "namespace:ci-pipelines",
        "display_name": "ci-pipelines",
        "aliases": ["CI/CD namespace"],
        "chunk_id": "chunk-cicd",
    },
    {
        "entity_id": "e-ns-ctrl",
        "entity_kind": "namespace",
        "name": "openshift-pipelines",
        "entity_key": "namespace:openshift-pipelines",
        "display_name": "openshift-pipelines",
        "aliases": ["Controller namespace"],
        "chunk_id": "chunk-cicd",
    },
    {
        "entity_id": "e-smee",
        "entity_kind": "webhook_url",
        "name": "https://smee.io/ori-bank-pac-demo-webhook",
        "entity_key": "webhook_url:https://smee.io/ori-bank-pac-demo-webhook",
        "display_name": "https://smee.io/ori-bank-pac-demo-webhook",
        "aliases": ["Webhook relay URL"],
        "chunk_id": "chunk-cicd",
    },
]

_ORI_BANK_RELATIONS = [
    {
        "relation_id": "r-1",
        "relation_type": "in_namespace",
        "confidence": 1.0,
        "quote": "oc describe repository ori-payments-api-repository -n ci-pipelines",
        "source_kind": "chunk",
        "source_ref": "",
        "chunk_id": "chunk-cicd",
        "subject_entity_id": "e-repo",
        "subject_key": "repository_cr:ori-payments-api-repository",
        "subject_kind": "repository_cr",
        "subject_name": "ori-payments-api-repository",
        "object_entity_id": "e-ns-ci",
        "object_key": "namespace:ci-pipelines",
        "object_kind": "namespace",
        "object_name": "ci-pipelines",
    },
    {
        "relation_id": "r-2",
        "relation_type": "in_namespace",
        "confidence": 1.0,
        "quote": "oc logs -n openshift-pipelines deployment/pipelines-as-code-controller",
        "source_kind": "chunk",
        "source_ref": "",
        "chunk_id": "chunk-cicd",
        "subject_entity_id": "e-deploy",
        "subject_key": "deployment:pipelines-as-code-controller",
        "subject_kind": "deployment",
        "subject_name": "pipelines-as-code-controller",
        "object_entity_id": "e-ns-ctrl",
        "object_key": "namespace:openshift-pipelines",
        "object_kind": "namespace",
        "object_name": "openshift-pipelines",
    },
]


def _patch_graph(monkeypatch, *, entities=None, relations=None, broken=False):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeConnection())
    if broken:
        def explode(cursor, chunk_ids, *, scope):
            raise RuntimeError("graph tables missing")

        monkeypatch.setattr(graph_repository, "find_entities_for_chunks", explode)
        return
    monkeypatch.setattr(
        graph_repository,
        "find_entities_for_chunks",
        lambda cursor, chunk_ids, *, scope: list(entities or []),
    )
    monkeypatch.setattr(
        graph_repository,
        "find_entities_by_names",
        lambda cursor, names, *, scope: [],
    )
    monkeypatch.setattr(
        graph_repository,
        "expand_relations",
        lambda cursor, entity_ids, *, scope, limit: list(relations or []),
    )


def test_loads_ci_cd_values_from_graph(monkeypatch):
    _patch_graph(monkeypatch, entities=_ORI_BANK_ENTITIES, relations=_ORI_BANK_RELATIONS)

    result = load_graph_customer_context_values(
        _settings(),
        query="오리은행 기준으로 PipelineRun이 안 뜰 때 뭐부터 확인해?",
        chunk_ids=["chunk-cicd"],
    )

    values = result["values"]
    assert values["repository_name"] == "ori-payments-api-repository"
    assert values["repository_namespace"] == "ci-pipelines"
    assert values["pipeline_namespace"] == "ci-pipelines"
    assert values["controller_namespace"] == "openshift-pipelines"
    assert values["smee_url"] == "https://smee.io/ori-bank-pac-demo-webhook"
    evidence_keys = {item["key"] for item in result["evidence"]}
    assert {"repository_name", "repository_namespace", "controller_namespace"} <= evidence_keys


def test_seeds_from_answer_text_when_cited_chunk_has_no_entities(monkeypatch):
    captured: dict[str, list[str]] = {}

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeConnection())
    monkeypatch.setattr(
        graph_repository,
        "find_entities_for_chunks",
        lambda cursor, chunk_ids, *, scope: [],  # Q&A 헤딩 chunk라 entity 없음
    )

    def fake_by_names(cursor, names, *, scope):
        captured["names"] = list(names)
        return [entity for entity in _ORI_BANK_ENTITIES if entity["name"] in names]

    monkeypatch.setattr(graph_repository, "find_entities_by_names", fake_by_names)
    monkeypatch.setattr(
        graph_repository,
        "expand_relations",
        lambda cursor, entity_ids, *, scope, limit: list(_ORI_BANK_RELATIONS),
    )

    result = load_graph_customer_context_values(
        _settings(),
        query="오리은행 기준으로 PipelineRun이 안 뜰 때 뭐부터 확인해?",
        chunk_ids=["chunk-question-heading"],
        answer_text="먼저 ci-pipelines 네임스페이스를 확인하고, openshift-pipelines 네임스페이스의 컨트롤러 로그를 본다.",
    )

    assert "ci-pipelines" in captured["names"]
    assert "openshift-pipelines" in captured["names"]
    values = result["values"]
    assert values["pipeline_namespace"] == "ci-pipelines"
    assert values["controller_namespace"] == "openshift-pipelines"


def test_disabled_or_broken_graph_returns_empty(monkeypatch):
    assert load_graph_customer_context_values(
        _settings(entity_graph_enabled=False), query="q", chunk_ids=["c"]
    ) == {"values": {}, "evidence": []}
    assert load_graph_customer_context_values(
        _settings(database_url=""), query="q", chunk_ids=["c"]
    ) == {"values": {}, "evidence": []}

    _patch_graph(monkeypatch, broken=True)
    assert load_graph_customer_context_values(
        _settings(), query="q", chunk_ids=["c"]
    ) == {"values": {}, "evidence": []}


def _customer_citation(excerpt: str) -> Citation:
    return Citation(
        index=1,
        chunk_id="chunk-cicd",
        book_slug="uploaded-documents",
        section="CI/CD 연결 기준",
        anchor="cicd",
        source_url="uploads/source.md",
        viewer_path="/uploads/documents/doc-1/index.html#cicd",
        excerpt=excerpt,
        source_collection="uploads",
        source_scope="user_upload",
    )


def test_contract_uses_graph_values_when_regex_finds_nothing():
    citations = [
        _customer_citation("PipelineRun이 생성되지 않으면 GitHub Webhook 전달 상태를 확인한다.")
    ]
    graph_values = {
        "pipeline_namespace": "ci-pipelines",
        "repository_namespace": "ci-pipelines",
        "repository_name": "ori-payments-api-repository",
        "controller_namespace": "openshift-pipelines",
    }

    updated, meta = _apply_customer_context_answer_contract(
        "PipelineRun 문제는 controller 로그를 확인하세요.",
        query="오리은행 기준으로 PipelineRun이 안 뜰 때 뭐부터 확인해?",
        citations=citations,
        graph_values=graph_values,
    )

    assert meta["status"] == "used"
    assert "oc get pipelinerun -n ci-pipelines" in updated
    assert "oc describe repository ori-payments-api-repository -n ci-pipelines" in updated
    # 명령 카드는 4개 cap이라 controller 카드는 잘릴 수 있지만 값 자체는 채워진다.
    assert meta["values"]["controller_namespace"] == "openshift-pipelines"
    assert set(meta["graph_filled_keys"]) >= {"repository_name", "controller_namespace"}


def test_contract_prefers_regex_values_over_graph():
    citations = [
        _customer_citation(
            "CI/CD namespace는 ci-pipelines 이다. PipelineRun은 ci-pipelines namespace에서 확인한다."
        )
    ]
    graph_values = {"pipeline_namespace": "wrong-namespace"}

    _, meta = _apply_customer_context_answer_contract(
        "PipelineRun 상태를 확인하세요.",
        query="PipelineRun이 안 떠요",
        citations=citations,
        graph_values=graph_values,
    )

    assert meta["values"]["pipeline_namespace"] == "ci-pipelines"
    assert "pipeline_namespace" not in meta["graph_filled_keys"]


def test_contract_without_graph_values_keeps_existing_behavior():
    citations = [_customer_citation("일반 설명만 있는 문서")]

    answer, meta = _apply_customer_context_answer_contract(
        "그냥 답변",
        query="일반 질문",
        citations=citations,
    )

    assert answer == "그냥 답변"
    assert meta["status"] == "skipped"
