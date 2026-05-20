from __future__ import annotations

from play_book_studio.retrieval.access_scope import filter_hits_by_session_scope, hit_visible_to_session
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever_search import _session_scope_qdrant_filter, _session_scope_row_filter
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


def test_private_hits_are_visible_to_matching_owner_without_repository_selection():
    context = SessionContext(owner_user_id="owner-a")
    private_hit = _hit(
        chunk_id="private",
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

    assert hit_visible_to_session(private_hit, context)
    assert not hit_visible_to_session(wrong_owner, context)


def test_active_document_allows_matching_private_upload_without_active_repository():
    context = SessionContext(owner_user_id="owner-a", active_document_id="doc-a")
    visible = _hit(
        chunk_id="private-doc",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )

    assert hit_visible_to_session(visible, context)


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


def test_active_repository_filters_workspace_shared_hits():
    context = SessionContext(owner_user_id="owner-a", active_repository_id="repo-a")
    visible = _hit(
        chunk_id="repo-a-hit",
        repository_id="repo-a",
        visibility="workspace_shared",
        source_scope="user_upload",
    )
    wrong_repository = _hit(
        chunk_id="repo-b-hit",
        repository_id="repo-b",
        visibility="workspace_shared",
        source_scope="user_upload",
    )
    official_without_repository = _hit(
        chunk_id="official-hit",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope([visible, wrong_repository, official_without_repository], context=context)
    ] == ["repo-a-hit"]


def test_enabled_combined_scope_keeps_official_and_selected_repository_uploads():
    context = SessionContext(
        owner_user_id="owner-a",
        active_repository_id="repo-a",
        enabled_source_scopes=["official_docs", "user_upload"],
    )
    visible_upload = _hit(
        chunk_id="repo-a-hit",
        repository_id="repo-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    wrong_repository_upload = _hit(
        chunk_id="repo-b-hit",
        repository_id="repo-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    official_without_repository = _hit(
        chunk_id="official-hit",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope(
            [visible_upload, wrong_repository_upload, official_without_repository],
            context=context,
        )
    ] == ["repo-a-hit", "official-hit"]


def test_enabled_user_upload_scope_excludes_official_hits():
    context = SessionContext(
        owner_user_id="owner-a",
        enabled_source_scopes=["user_upload"],
    )
    upload = _hit(
        chunk_id="upload-hit",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    official = _hit(
        chunk_id="official-hit",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope([upload, official], context=context)
    ] == ["upload-hit"]


def test_enabled_official_book_slugs_filter_official_hits():
    context = SessionContext(
        enabled_source_scopes=["official_docs"],
        enabled_official_book_slugs=["ocp-storage"],
    )
    visible = _hit(
        chunk_id="selected-book",
        book_slug="ocp-storage",
        visibility="workspace_shared",
        source_scope="official_docs",
    )
    hidden = _hit(
        chunk_id="unselected-book",
        book_slug="ocp-networking",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([visible, hidden], context=context)] == [
        "selected-book"
    ]


def test_enabled_customer_document_ids_filter_study_docs_hits():
    context = SessionContext(
        enabled_source_scopes=["customer_docs"],
        enabled_customer_document_ids=["study-doc-a"],
    )
    visible = _hit(
        chunk_id="study-doc-a-hit",
        book_slug="kmsc-operations",
        document_source_id="study-doc-a",
        visibility="workspace_shared",
        source_scope="study_docs",
    )
    hidden = _hit(
        chunk_id="study-doc-b-hit",
        book_slug="kmsc-operations",
        document_source_id="study-doc-b",
        visibility="workspace_shared",
        source_scope="study_docs",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([visible, hidden], context=context)] == [
        "study-doc-a-hit"
    ]


def test_enabled_customer_draft_ids_filter_customer_hits():
    context = SessionContext(
        enabled_source_scopes=["customer_docs"],
        enabled_customer_draft_ids=["draft-a"],
    )
    visible = _hit(
        chunk_id="draft-a:section-1",
        source_id="customer_pack:draft-a",
        source_lane="customer_pack",
        viewer_path="/playbooks/customer-packs/draft-a/index.html#section-1",
    )
    hidden = _hit(
        chunk_id="draft-b:section-1",
        source_id="customer_pack:draft-b",
        source_lane="customer_pack",
        viewer_path="/playbooks/customer-packs/draft-b/index.html#section-1",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([visible, hidden], context=context)] == [
        "draft-a:section-1"
    ]


def test_enabled_upload_document_ids_override_active_repository_filter():
    context = SessionContext(
        owner_user_id="owner-a",
        active_repository_id="repo-a",
        enabled_source_scopes=["user_upload"],
        enabled_upload_document_ids=["doc-b"],
    )
    hidden = _hit(
        chunk_id="doc-a-hit",
        repository_id="repo-a",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    visible = _hit(
        chunk_id="doc-b-hit",
        repository_id="repo-b",
        document_source_id="doc-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )

    assert [hit.chunk_id for hit in filter_hits_by_session_scope([hidden, visible], context=context)] == [
        "doc-b-hit"
    ]


def test_enabled_upload_document_ids_are_prefiltered_for_bm25_and_qdrant():
    context = SessionContext(
        owner_user_id="owner-a",
        enabled_source_scopes=["user_upload"],
        enabled_upload_document_ids=["doc-b"],
    )

    row_filter = _session_scope_row_filter(context)
    assert row_filter is not None
    assert row_filter({"document_source_id": "doc-b", "source_scope": "user_upload"})
    assert not row_filter({"document_source_id": "doc-a", "source_scope": "user_upload"})

    assert _session_scope_qdrant_filter(context) == {
        "must": [{"key": "document_source_id", "match": {"value": "doc-b"}}]
    }


def test_active_document_overrides_single_selected_upload_document_id():
    context = SessionContext(
        owner_user_id="owner-a",
        active_document_id="doc-a",
        enabled_source_scopes=["official_docs", "user_upload"],
        enabled_upload_document_ids=["doc-a"],
    )

    row_filter = _session_scope_row_filter(context)
    assert row_filter is not None
    assert row_filter({"document_source_id": "doc-a", "source_scope": "user_upload"})
    assert not row_filter({"document_source_id": "doc-b", "source_scope": "user_upload"})
    assert not row_filter({"book_slug": "storage", "source_scope": "official_docs"})

    assert _session_scope_qdrant_filter(context) == {
        "must": [{"key": "document_source_id", "match": {"value": "doc-a"}}]
    }


def test_active_document_does_not_override_expanded_upload_document_ids():
    context = SessionContext(
        owner_user_id="owner-a",
        active_document_id="doc-a",
        enabled_source_scopes=["official_docs", "user_upload"],
        enabled_upload_document_ids=["doc-a", "doc-b"],
    )

    row_filter = _session_scope_row_filter(context)
    assert row_filter is not None
    assert row_filter({"document_source_id": "doc-a", "source_scope": "user_upload"})
    assert row_filter({"document_source_id": "doc-b", "source_scope": "user_upload"})
    assert row_filter({"book_slug": "storage", "source_scope": "official_docs"})

    assert _session_scope_qdrant_filter(context) == {
        "should": [
            {"key": "document_source_id", "match": {"value": "doc-a"}},
            {"key": "document_source_id", "match": {"value": "doc-b"}},
            {"key": "source_scope", "match": {"value": "official_docs"}},
        ]
    }


def test_active_document_overrides_single_selected_upload_hit_after_search():
    context = SessionContext(
        owner_user_id="owner-a",
        active_document_id="doc-a",
        enabled_source_scopes=["official_docs", "user_upload"],
        enabled_upload_document_ids=["doc-a"],
    )
    visible = _hit(
        chunk_id="doc-a-hit",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    hidden_upload = _hit(
        chunk_id="doc-b-hit",
        document_source_id="doc-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    hidden_official = _hit(
        chunk_id="official-hit",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope([visible, hidden_upload, hidden_official], context=context)
    ] == ["doc-a-hit"]


def test_active_document_does_not_override_expanded_upload_hits_after_search():
    context = SessionContext(
        owner_user_id="owner-a",
        active_document_id="doc-a",
        enabled_source_scopes=["official_docs", "user_upload"],
        enabled_upload_document_ids=["doc-a", "doc-b"],
    )
    doc_a = _hit(
        chunk_id="doc-a-hit",
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    doc_b = _hit(
        chunk_id="doc-b-hit",
        document_source_id="doc-b",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
    )
    official = _hit(
        chunk_id="official-hit",
        visibility="workspace_shared",
        source_scope="official_docs",
    )

    assert [
        hit.chunk_id
        for hit in filter_hits_by_session_scope([doc_a, doc_b, official], context=context)
    ] == ["doc-a-hit", "doc-b-hit", "official-hit"]


def test_active_document_does_not_override_when_user_upload_scope_is_disabled():
    context = SessionContext(
        owner_user_id="owner-a",
        active_document_id="doc-a",
        enabled_source_scopes=["official_docs"],
        enabled_upload_document_ids=["doc-a"],
    )

    row_filter = _session_scope_row_filter(context)
    assert row_filter is not None
    assert not row_filter({"document_source_id": "doc-a", "source_scope": "user_upload"})
    assert row_filter({"book_slug": "storage", "source_scope": "official_docs"})

    assert _session_scope_qdrant_filter(context) == {
        "should": [{"key": "source_scope", "match": {"value": "official_docs"}}]
    }


def test_enabled_upload_document_ids_keep_other_enabled_scopes_in_qdrant_filter():
    context = SessionContext(
        owner_user_id="owner-a",
        enabled_source_scopes=["official_docs", "user_upload"],
        enabled_upload_document_ids=["doc-b"],
    )

    row_filter = _session_scope_row_filter(context)
    assert row_filter is not None
    assert row_filter({"document_source_id": "doc-b", "source_scope": "user_upload"})
    assert not row_filter({"document_source_id": "doc-a", "source_scope": "user_upload"})
    assert row_filter({"book_slug": "storage", "source_scope": "official_docs"})

    qdrant_filter = _session_scope_qdrant_filter(context)
    assert qdrant_filter == {
        "should": [
            {"key": "document_source_id", "match": {"value": "doc-b"}},
            {"key": "source_scope", "match": {"value": "official_docs"}},
        ]
    }


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
