from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan


def test_active_document_scope_bypasses_unsupported_product_gate() -> None:
    plan = build_retrieval_plan(
        "업로드한 CD(ArgoCD) 문서의 path 값은?",
        context=SessionContext(active_document_id="3ce81bf3-6261-4788-a3b6-bfc21ef24b14"),
        candidate_k=10,
    )

    assert plan.unsupported_product is None


def test_external_product_without_active_document_stays_out_of_scope() -> None:
    plan = build_retrieval_plan(
        "ArgoCD에서 path 설정 방법은?",
        context=SessionContext(),
        candidate_k=10,
    )

    assert plan.unsupported_product == "argocd"
