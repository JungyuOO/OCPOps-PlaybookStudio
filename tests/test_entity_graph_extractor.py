from __future__ import annotations

from pathlib import Path

import pytest

from play_book_studio.graph.models import (
    RELATION_TYPE_CO_REFERENCED,
    RELATION_TYPE_IN_NAMESPACE,
)
from play_book_studio.graph.rules import (
    RuleBasedEntityExtractor,
    detect_kind_hints,
    query_name_tokens,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "ori_bank_ocp_dummy_customer_data.md"


@pytest.fixture(scope="module")
def ori_bank_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def extraction(ori_bank_text):
    return RuleBasedEntityExtractor().extract(ori_bank_text)


def _entity_keys(extraction) -> set[str]:
    return {mention.entity.entity_key for mention in extraction.mentions}


def _relation_triples(extraction) -> set[tuple[str, str, str]]:
    return {
        (relation.subject.entity_key, relation.relation_type, relation.object.entity_key)
        for relation in extraction.relations
    }


def test_extracts_expected_operational_entities(extraction):
    keys = _entity_keys(extraction)

    assert "namespace:ori-pay-prod" in keys
    assert "namespace:ci-pipelines" in keys
    assert "namespace:openshift-pipelines" in keys
    assert "namespace:ori-mobile-prod" in keys
    assert "namespace:ori-batch-prod" in keys
    assert "namespace:banking-monitoring" in keys
    assert "route:pay-api" in keys
    assert "service:pay-api-svc" in keys
    assert "deployment:pay-api" in keys
    assert "deployment:pipelines-as-code-controller" in keys
    assert "pvc:txn-ledger-pvc" in keys
    assert "storageclass:ocs-storagecluster-ceph-rbd" in keys
    assert "repository_cr:ori-payments-api-repository" in keys
    assert "secret:ori-pac-webhook-secret" in keys
    assert "github_org:ori-bank-demo" in keys
    assert "github_repo:ori-payments-api" in keys


def test_extracts_expected_relations(extraction):
    triples = _relation_triples(extraction)

    assert ("pvc:txn-ledger-pvc", RELATION_TYPE_IN_NAMESPACE, "namespace:ori-pay-prod") in triples
    assert ("route:pay-api", RELATION_TYPE_IN_NAMESPACE, "namespace:ori-pay-prod") in triples
    assert ("service:pay-api-svc", RELATION_TYPE_IN_NAMESPACE, "namespace:ori-pay-prod") in triples
    assert (
        "repository_cr:ori-payments-api-repository",
        RELATION_TYPE_IN_NAMESPACE,
        "namespace:ci-pipelines",
    ) in triples
    assert (
        "deployment:pipelines-as-code-controller",
        RELATION_TYPE_IN_NAMESPACE,
        "namespace:openshift-pipelines",
    ) in triples
    assert ("route:pay-api", RELATION_TYPE_CO_REFERENCED, "service:pay-api-svc") in triples


def test_does_not_extract_placeholders_or_noise(extraction):
    keys = _entity_keys(extraction)

    assert not any("<" in key or ">" in key for key in keys)
    assert not any("pod-name" in key for key in keys)
    assert "pod:pod-name" not in keys
    assert not any("5xx" in key for key in keys)
    assert not any(key.startswith("pod:") for key in keys)  # only <pod-name> placeholders appear


def test_no_cross_namespace_guesses_from_multi_namespace_table(extraction):
    triples = _relation_triples(extraction)

    in_namespace_objects = {
        obj for subject, relation_type, obj in triples if relation_type == RELATION_TYPE_IN_NAMESPACE
    }
    # These namespaces only appear in the section-1 environment summary table, which
    # lists multiple namespaces and therefore must not yield in_namespace edges.
    assert "namespace:ori-mobile-prod" not in in_namespace_objects
    assert "namespace:ori-batch-prod" not in in_namespace_objects
    assert "namespace:banking-monitoring" not in in_namespace_objects
    assert "namespace:openshift-storage" not in in_namespace_objects

    # in_namespace subjects must never be namespaces or cluster-scoped kinds.
    for subject, relation_type, _ in triples:
        if relation_type == RELATION_TYPE_IN_NAMESPACE:
            assert not subject.startswith("namespace:")
            assert not subject.startswith("storageclass:")


def test_every_quote_is_a_substring_of_the_source(ori_bank_text, extraction):
    for mention in extraction.mentions:
        assert mention.quote
        assert mention.quote in ori_bank_text
    for relation in extraction.relations:
        assert relation.quote
        assert relation.quote in ori_bank_text


def test_mentions_carry_locator_patterns(extraction):
    patterns = {mention.locator.get("pattern") for mention in extraction.mentions}

    assert "oc_command" in patterns
    assert "table_row" in patterns
    assert "prose" in patterns


def test_table_labels_become_entity_labels(extraction):
    labels = {
        mention.entity.label
        for mention in extraction.mentions
        if mention.entity.entity_key == "namespace:ori-pay-prod" and mention.entity.label
    }

    assert any("namespace" in label.lower() for label in labels)


def test_empty_text_returns_empty_result():
    result = RuleBasedEntityExtractor().extract("   \n  ")

    assert result.mentions == ()
    assert result.relations == ()


def test_detect_kind_hints_for_demo_questions():
    assert "route" in detect_kind_hints("오리은행 결제 API Route가 503이면 어떤 namespace와 리소스부터 확인해?")
    assert "namespace" in detect_kind_hints("오리은행 결제 API Route가 503이면 어떤 namespace와 리소스부터 확인해?")
    assert "pvc" in detect_kind_hints("오리은행 기준으로 PVC Pending이면 어떤 PVC와 StorageClass를 봐야 해?")
    assert "storageclass" in detect_kind_hints("어떤 PVC와 StorageClass를 봐야 해?")
    assert detect_kind_hints("오늘 날씨 어때?") == ()


def test_query_name_tokens_extracts_hyphenated_names():
    tokens = query_name_tokens("ori-pay-prod의 pay-api route 상태 알려줘")

    assert "ori-pay-prod" in tokens
    assert "pay-api" in tokens
    assert "route" not in tokens
