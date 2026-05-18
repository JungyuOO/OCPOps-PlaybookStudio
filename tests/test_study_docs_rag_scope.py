from __future__ import annotations

from play_book_studio.http.server_chat import _answer_query_from_payload
from play_book_studio.http.session_flow import context_with_request_overrides
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever_pipeline import _filter_preferred_source_scope


def _hit(chunk_id: str, source_scope: str) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug="kmsc" if source_scope == "study_docs" else "official",
        chapter="chapter",
        section="section",
        anchor=chunk_id,
        source_url="",
        viewer_path="",
        text="text",
        source="source",
        raw_score=1.0,
        source_scope=source_scope,
    )


def test_course_and_study_docs_routes_scope_context_to_study_docs() -> None:
    for route_kind in ("course", "study_docs"):
        context = context_with_request_overrides(
            SessionContext(),
            payload={"route_kind": route_kind},
            mode="ops",
        )

        assert context.preferred_source_scope == "study_docs"
        assert "KMSC" in context.open_entities


def test_course_and_study_docs_routes_add_kmsc_query_hint() -> None:
    for route_kind in ("course", "study_docs"):
        query = _answer_query_from_payload("성능 병목은 어디서 보면 될까요?", {"route_kind": route_kind})

        assert "KMSC 실운영 문서" in query
        assert "source_scope:study_docs" in query


def test_preferred_source_scope_filters_retrieval_hits_to_study_docs() -> None:
    context = SessionContext(preferred_source_scope="study_docs")

    hits = _filter_preferred_source_scope(
        [_hit("official-1", "official_docs"), _hit("study-1", "study_docs")],
        context,
    )

    assert [hit.chunk_id for hit in hits] == ["study-1"]
