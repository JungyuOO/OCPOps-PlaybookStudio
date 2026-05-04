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
            "owner_user_id": "owner-a",
            "visibility": "private_user",
            "source_scope": "user_upload",
        },
        source="vector",
        score=0.8,
    )

    assert hit.repository_id == "repo-a"
    assert hit.owner_user_id == "owner-a"
    assert hit.visibility == "private_user"
    assert hit.source_scope == "user_upload"
