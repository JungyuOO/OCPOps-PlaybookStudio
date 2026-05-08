from __future__ import annotations

from play_book_studio.retrieval.access_scope import filter_hits_by_session_scope, hit_visible_to_session
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.vector import hit_from_payload


def _hit(**overrides) -> RetrievalHit:
    base = {
        "chunk_id": "chunk",
        "book_slug": "uploaded-documents",
        "chapter": "",
        "section": "",
        "anchor": "",
        "source_url": "",
        "viewer_path": "",
        "text": "text",
        "source": "vector",
        "raw_score": 1.0,
    }
    base.update(overrides)
    return RetrievalHit(**base)


def test_legacy_hits_without_scope_metadata_remain_visible():
    assert hit_visible_to_session(_hit(), SessionContext(owner_user_id="owner-a"))


def test_private_hits_require_matching_owner_and_active_repository():
    context = SessionContext(
        owner_user_id="owner-a",
        active_repository_id="repo-a",
    )
    visible = _hit(
        chunk_id="visible",
        repository_id="repo-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    wrong_owner = _hit(
        chunk_id="wrong-owner",
        repository_id="repo-a",
        owner_user_id="owner-b",
        visibility="private_user",
        source_scope="user_upload",
    )
    wrong_repo = _hit(
        chunk_id="wrong-repo",
        repository_id="repo-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([visible, wrong_owner, wrong_repo], context=context)] == [
        "visible"
    ]


def test_private_hits_are_hidden_without_active_repository_selection():
    context = SessionContext(owner_user_id="owner-a")
    private_hit = _hit(
        chunk_id="private",
        repository_id="repo-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )

    assert not hit_visible_to_session(private_hit, context)


def test_active_document_filters_shared_hits():
    context = SessionContext(owner_user_id="owner-a", active_document_id="doc-a")
    visible = _hit(
        chunk_id="doc-a-hit",
        document_source_id="doc-a",
        visibility="workspace_shared",
        source_scope="study_docs",
    )
    wrong_document = _hit(
        chunk_id="doc-b-hit",
        document_source_id="doc-b",
        visibility="workspace_shared",
        source_scope="study_docs",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([visible, wrong_document], context=context)] == [
        "doc-a-hit"
    ]


def test_active_document_still_requires_private_repository_scope():
    context = SessionContext(
        owner_user_id="owner-a",
        active_repository_id="repo-a",
        active_document_id="doc-a",
    )
    visible = _hit(
        chunk_id="visible-private-doc",
        repository_id="repo-a",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    wrong_document = _hit(
        chunk_id="wrong-private-doc",
        repository_id="repo-a",
        document_source_id="doc-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    wrong_repository = _hit(
        chunk_id="wrong-private-repo",
        repository_id="repo-b",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope([visible, wrong_document, wrong_repository], context=context)
    ] == ["visible-private-doc"]


def test_shared_hits_are_visible_across_owners():
    assert hit_visible_to_session(
        _hit(visibility="workspace_shared", owner_user_id="owner-b", source_scope="study_docs"),
        SessionContext(owner_user_id="owner-a"),
    )


def test_vector_payload_preserves_repository_scope_fields():
    hit = hit_from_payload(
        {
            "chunk_id": "chunk-a",
            "book_slug": "uploaded-documents",
            "text": "body",
            "repository_id": "repo-a",
            "document_source_id": "doc-a",
            "owner_user_id": "owner-a",
            "visibility": "private_user",
            "source_scope": "user_upload",
        },
        source="vector",
        score=0.8,
    )

    assert hit.repository_id == "repo-a"
    assert hit.document_source_id == "doc-a"
    assert hit.owner_user_id == "owner-a"
    assert hit.visibility == "private_user"
    assert hit.source_scope == "user_upload"
