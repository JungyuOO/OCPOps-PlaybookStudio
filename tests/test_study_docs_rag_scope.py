from __future__ import annotations

from play_book_studio.http.session_flow import context_with_request_overrides
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever_pipeline import (
    _filter_preferred_source_scope,
    _preserve_specific_customer_candidate,
    _preserve_specific_user_upload_candidate,
)


def _hit(chunk_id: str, source_scope: str, **overrides) -> RetrievalHit:
    payload = {
        "chunk_id": chunk_id,
        "book_slug": "uploaded-documents" if source_scope == "user_upload" else "kmsc" if source_scope == "study_docs" else "official",
        "chapter": "chapter",
        "section": "section",
        "anchor": chunk_id,
        "source_url": "",
        "viewer_path": "",
        "text": "text",
        "source": "source",
        "raw_score": 1.0,
        "source_scope": source_scope,
    }
    payload.update(overrides)
    return RetrievalHit(
        **payload,
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


def test_enabled_source_scopes_override_route_preferred_scope() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={
            "route_kind": "official",
            "enabled_source_scopes": ["official_docs", "user_upload"],
            "enabled_official_book_slugs": ["ocp-storage"],
            "enabled_customer_draft_ids": ["draft-a"],
            "enabled_customer_document_ids": ["study-doc-a"],
            "enabled_upload_document_ids": ["doc-a"],
        },
        mode="ops",
    )

    assert context.preferred_source_scope is None
    assert context.enabled_source_scopes == ["official_docs", "user_upload"]
    assert context.enabled_official_book_slugs == ["ocp-storage"]
    assert context.enabled_customer_draft_ids == ["draft-a"]
    assert context.enabled_customer_document_ids == ["study-doc-a"]
    assert context.enabled_upload_document_ids == ["doc-a"]


def test_study_docs_route_keeps_kmsc_scope_when_ui_source_scopes_are_sent() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={
            "route_kind": "study_docs",
            "enabled_source_scopes": ["official_docs", "customer_docs", "user_upload"],
        },
        mode="ops",
    )

    assert context.preferred_source_scope == "study_docs"
    assert context.enabled_source_scopes == []


def test_course_route_is_not_main_chat_study_docs_scope() -> None:
    context = context_with_request_overrides(
        SessionContext(),
        payload={"route_kind": "course"},
        mode="ops",
    )

    assert context.preferred_source_scope is None


def test_preferred_source_scope_filters_retrieval_hits_to_study_docs() -> None:
    context = SessionContext(preferred_source_scope="study_docs")

    hits = _filter_preferred_source_scope(
        [_hit("official-1", "official_docs"), _hit("study-1", "study_docs")],
        context,
    )

    assert [hit.chunk_id for hit in hits] == ["study-1"]


def test_enabled_source_scopes_filter_multiple_groups() -> None:
    context = SessionContext(
        preferred_source_scope="official_docs",
        enabled_source_scopes=["official_docs", "user_upload"],
    )
    upload = _hit("upload-1", "user_upload")

    hits = _filter_preferred_source_scope(
        [_hit("official-1", "official_docs"), _hit("study-1", "study_docs"), upload],
        context,
    )

    assert [hit.chunk_id for hit in hits] == ["official-1", "upload-1"]


def test_enabled_source_scopes_filter_upload_only() -> None:
    context = SessionContext(
        preferred_source_scope="official_docs",
        enabled_source_scopes=["user_upload"],
    )

    hits = _filter_preferred_source_scope(
        [_hit("official-1", "official_docs"), _hit("study-1", "study_docs"), _hit("upload-1", "user_upload")],
        context,
    )

    assert [hit.chunk_id for hit in hits] == ["upload-1"]


def test_session_context_round_trips_rag_scope_fields() -> None:
    context = SessionContext(
        enabled_source_scopes=["user_upload"],
        enabled_official_book_slugs=["storage"],
        enabled_customer_draft_ids=["draft-a"],
        enabled_customer_document_ids=["study-doc-a"],
        enabled_upload_document_ids=["upload-doc-a"],
    )

    round_tripped = SessionContext.from_dict(context.to_dict())

    assert round_tripped.enabled_source_scopes == ["user_upload"]
    assert round_tripped.enabled_official_book_slugs == ["storage"]
    assert round_tripped.enabled_customer_draft_ids == ["draft-a"]
    assert round_tripped.enabled_customer_document_ids == ["study-doc-a"]
    assert round_tripped.enabled_upload_document_ids == ["upload-doc-a"]


def test_specific_upload_identifier_is_preserved_inside_full_scope() -> None:
    context = SessionContext(enabled_source_scopes=["official_docs", "customer_docs", "user_upload"])
    upload = _hit(
        "upload-demo",
        "user_upload",
        raw_score=0.03,
        text="PV 생성\noc apply -f demo-pv.yaml\nPVC 생성\noc apply -f demo-pvc.yaml\noc get pv\noc get pvc",
    )
    official_top = _hit(
        "official-pvc",
        "official_docs",
        raw_score=0.2,
        fused_score=0.2,
        text="oc create -f <pvc-restore-filename>.yaml\noc get pvc",
    )

    hits = _preserve_specific_user_upload_candidate(
        "demo-pv.yaml이랑 demo-pvc.yaml로 PV/PVC 생성하고 확인하는 순서 알려줘",
        target_hits=[official_top],
        candidate_hits=[upload, official_top],
        context=context,
    )

    assert hits[0].chunk_id == "upload-demo"


def test_specific_upload_identifier_does_not_bypass_disabled_upload_scope() -> None:
    context = SessionContext(enabled_source_scopes=["official_docs"])
    upload = _hit("upload-demo", "user_upload", text="oc apply -f demo-pv.yaml")
    official_top = _hit("official-pvc", "official_docs", fused_score=0.2)

    hits = _preserve_specific_user_upload_candidate(
        "demo-pv.yaml 적용 순서 알려줘",
        target_hits=[official_top],
        candidate_hits=[upload, official_top],
        context=context,
    )

    assert [hit.chunk_id for hit in hits] == ["official-pvc"]


def test_customer_scope_signal_is_preserved_inside_full_scope() -> None:
    context = SessionContext(enabled_source_scopes=["official_docs", "customer_docs", "user_upload"])
    customer = _hit(
        "customer-pv-delete",
        "study_docs",
        raw_score=0.03,
        book_slug="kmsc-operations",
        chapter="unit_test",
        section="5. OCP PV/PVC 관리 테스트",
        text=(
            "TEST-UN-OCP-23-03 unit_test PV 삭제 및 확인 "
            "oc delete -f pv.yaml oc get pv | grep nfs-chak-test "
            "Storage -> PersistentVolumes -> Delete PersistentVolume"
        ),
    )
    official_top = _hit(
        "official-local-pv",
        "official_docs",
        raw_score=0.2,
        fused_score=0.2,
        text="Local Storage Operator없이 로컬 볼륨 프로비저닝 oc get pv",
    )

    hits = _preserve_specific_customer_candidate(
        "KMSC 단위 테스트에서 PV를 삭제한 뒤 정상적으로 삭제됐는지 확인하는 절차를 알려줘",
        target_hits=[official_top],
        candidate_hits=[customer, official_top],
        context=context,
    )

    assert hits[0].chunk_id == "customer-pv-delete"


def test_customer_scope_signal_does_not_bypass_disabled_customer_scope() -> None:
    context = SessionContext(enabled_source_scopes=["official_docs"])
    customer = _hit(
        "customer-pv-delete",
        "study_docs",
        book_slug="kmsc-operations",
        chapter="unit_test",
        text="TEST-UN-OCP-23-03 unit_test PV 삭제 및 확인",
    )
    official_top = _hit("official-local-pv", "official_docs", fused_score=0.2)

    hits = _preserve_specific_customer_candidate(
        "KMSC 단위 테스트에서 PV 삭제 확인 절차 알려줘",
        target_hits=[official_top],
        candidate_hits=[customer, official_top],
        context=context,
    )

    assert [hit.chunk_id for hit in hits] == ["official-local-pv"]
