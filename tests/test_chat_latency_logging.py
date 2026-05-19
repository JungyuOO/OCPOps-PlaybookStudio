from __future__ import annotations

from types import SimpleNamespace

from play_book_studio.http.server_chat import _build_chat_latency_log
from play_book_studio.retrieval.models import SessionContext


def test_chat_latency_log_flattens_answer_retrieval_and_payload_timings() -> None:
    result = SimpleNamespace(
        response_kind="rag",
        warnings=["low-margin"],
        retrieval_trace={
            "timings_ms": {
                "bm25_search": 4.4,
                "vector_search": 20.0,
                "rerank": 7.1,
            },
            "vector_runtime": {
                "subqueries": [
                    {
                        "embedding_ms": 5.2,
                        "qdrant_ms": 3.0,
                        "hydrate_ms": 1.0,
                    },
                    {
                        "embedding_ms": 6.3,
                        "qdrant_ms": 2.0,
                        "hydrate_ms": 0.5,
                    },
                ],
            },
            "ablation": {"reranked_top_book_slugs": ["storage", "networking"]},
        },
        pipeline_trace={
            "timings_ms": {
                "total": 90.0,
                "retrieval_total": 31.0,
                "context_assembly": 3.5,
                "prompt_build": 2.5,
                "llm_generate_total": 40.0,
                "llm_provider_round_trip": 38.0,
                "citation_finalize": 1.5,
            },
            "llm": {"model": "gpt-test"},
        },
    )
    response_payload = {
        "citations": [
            {"source_scope": "official_docs"},
            {"source_scope": "study_docs"},
        ]
    }

    payload = _build_chat_latency_log(
        request_id="req-1",
        session_id="session-1",
        route="/api/chat/stream",
        payload={"route_kind": "official"},
        query="전체 프로젝트 목록 확인 어떻게 해?",
        request_context=SessionContext(preferred_source_scope="official_docs"),
        result=result,
        response_payload=response_payload,
        server_timings_ms={
            "request_total": 120.0,
            "answerer_runtime": 100.0,
            "payload_build": 8.0,
            "payload_related_links": 2.0,
            "payload_related_sections": 1.0,
            "payload_suggested_queries": 0.5,
            "session_persist_pre_payload": 3.0,
            "session_persist_post_payload": 4.0,
        },
    )

    assert payload["event"] == "chat_latency"
    assert payload["query_len"] == len("전체 프로젝트 목록 확인 어떻게 해?")
    assert payload["preferred_source_scope"] == "official_docs"
    assert payload["total_ms"] == 120.0
    assert payload["answerer_ms"] == 100.0
    assert payload["retrieval_ms"] == 31.0
    assert payload["bm25_ms"] == 4.4
    assert payload["vector_ms"] == 20.0
    assert payload["embedding_ms"] == 11.5
    assert payload["qdrant_ms"] == 5.0
    assert payload["hydrate_ms"] == 1.5
    assert payload["rerank_ms"] == 7.1
    assert payload["llm_ms"] == 40.0
    assert payload["llm_provider_ms"] == 38.0
    assert payload["session_persist_ms"] == 7.0
    assert payload["source_scopes"] == ["official_docs", "study_docs"]
    assert payload["top_book_slugs"] == ["storage", "networking"]
    assert payload["llm_model"] == "gpt-test"
