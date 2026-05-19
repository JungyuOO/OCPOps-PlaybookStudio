from __future__ import annotations

from play_book_studio.http.session_flow import context_with_request_overrides
from play_book_studio.retrieval.hybrid_search import filter_preferred_source_scope
from play_book_studio.retrieval.models import RetrievalHit, SessionContext


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


def test_study_docs_route_scopes_context_to_study_docs() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={"route_kind": "study_docs"},
        mode="ops",
    )

    assert context.preferred_source_scope == "study_docs"
    assert "KMSC" in context.open_entities


def test_official_route_scopes_context_to_official_docs() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={"route_kind": "official"},
        mode="ops",
    )

    assert context.preferred_source_scope == "official_docs"


def test_course_route_is_not_main_chat_study_docs_scope() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={"route_kind": "course"},
        mode="ops",
    )

    assert context.preferred_source_scope is None


def test_preferred_source_scope_filters_retrieval_hits_to_study_docs() -> None:
    context = SessionContext(preferred_source_scope="study_docs")

    hits = filter_preferred_source_scope(
        [_hit("official-1", "official_docs"), _hit("study-1", "study_docs")],
        context,
    )

    assert [hit.chunk_id for hit in hits] == ["study-1"]
