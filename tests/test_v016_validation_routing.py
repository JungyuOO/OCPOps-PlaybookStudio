from play_book_studio.answering.context import _should_force_clarification
from play_book_studio.answering.answerer import _is_low_confidence_retrieval
from play_book_studio.answering.models import Citation
from play_book_studio.answering.router import route_non_rag
from play_book_studio.retrieval.intent_profile import build_intent_profile
from play_book_studio.retrieval.models import RetrievalHit


def test_validation_operational_questions_are_not_smalltalk_or_clarification() -> None:
    queries = [
        "PDB가 설정되어 있는지는 어떻게 확인해?",
        "HPA 스케일링 정책은 어디서 수정해?",
        "Local Storage Operator를 제거할 때 어떤 리소스부터 정리해야 해?",
    ]

    for query in queries:
        assert route_non_rag(query) is None, query

    hits = [
        RetrievalHit(
            chunk_id="1",
            book_slug="ops",
            chapter="",
            section="ops",
            anchor="a",
            source_url="",
            viewer_path="",
            text="operator command",
            source="official",
            raw_score=0.01,
        )
    ]
    assert _should_force_clarification(hits, query="PDB에서 비정상 Pod 정책을 적용하려면 어떻게 해?") is False
    assert _should_force_clarification(hits, query="Local Storage Operator를 제거할 때 어떤 리소스부터 정리해야 해?") is False
    assert not _is_low_confidence_retrieval(
        query="PDB가 설정되어 있는지는 어떻게 확인해?",
        citations=[
            Citation(
                index=1,
                chunk_id="pdb",
                book_slug="nodes",
                section="Pod disruption budgets",
                anchor="pdb",
                source_url="",
                viewer_path="/docs/pdb",
                excerpt="Pod disruption budgets describe application availability.",
            )
        ],
        selected_hits=[{"fused_score": 0.01, "pre_rerank_fused_score": 0.01}],
    )


def test_validation_operational_questions_have_specific_intent_profiles() -> None:
    local_storage = build_intent_profile("Local Storage Operator를 제거할 때 어떤 리소스부터 정리해야 해?")
    pdb_check = build_intent_profile("PDB가 설정되어 있는지는 어떻게 확인해?")
    pdb_apply = build_intent_profile("PDB에서 비정상 Pod 정책을 적용하려면 어떻게 해?")
    hpa_edit = build_intent_profile("HPA 스케일링 정책은 어디서 수정해?")

    assert local_storage.target_object == "local-storage-operator"
    assert "oc delete localvolume --all --all-namespaces" in local_storage.primary_commands
    assert pdb_check.primary_commands[0] == "oc get poddisruptionbudget --all-namespaces"
    assert pdb_apply.primary_commands == ("oc create -f pod-disruption-budget.yaml",)
    assert hpa_edit.primary_commands == ("oc edit hpa <hpa-name> -n <namespace>",)
