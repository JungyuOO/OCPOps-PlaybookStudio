from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.query_signal_pipeline import QuerySignalPlan
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan
import play_book_studio.retrieval.retriever_plan as retriever_plan


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


def test_etcd_backup_plan_expands_candidate_budget_for_script_recall() -> None:
    plan = build_retrieval_plan(
        "etcd 백업은 실제로 어떤 표준 절차로 해야 해?",
        context=SessionContext(),
        candidate_k=24,
    )

    assert plan.effective_candidate_k == 64


def test_active_repository_scope_keeps_raw_korean_query_before_llm_embedding_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_plan,
        "build_query_signal_plan",
        lambda _query, llm_client=None: QuerySignalPlan(
            raw_query="업로드 문서 기준 CI 순서 핵심을 알려줘",
            normalized_query="CI sequence core steps",
            correction_notes=(),
            classification={},
            search_signals={},
            confidence={},
            embedding_queries=("CI sequence core steps", "CI process order"),
            metadata_filter={},
            debug={"mode": "unit-test"},
        ),
    )

    plan = build_retrieval_plan(
        "업로드 문서 기준 CI 순서 핵심을 알려줘",
        context=SessionContext(
            active_repository_id="1e53febb-d212-4327-80e5-71a4828fbad0",
            enabled_source_scopes=["user_upload"],
        ),
        candidate_k=10,
    )

    assert plan.retrieval_queries[0] == "업로드 문서 기준 CI 순서 핵심을 알려줘 가이드 참고"
    assert plan.retrieval_queries[1] == "CI sequence core steps"


def test_official_scope_keeps_deterministic_query_before_llm_embedding_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_plan,
        "build_query_signal_plan",
        lambda _query, llm_client=None: QuerySignalPlan(
            raw_query="OpenShift 웹 콘솔에서 프로젝트와 워크로드를 확인하려면 어디를 봐야 해?",
            normalized_query="where to view projects and workloads in OpenShift web console",
            correction_notes=(),
            classification={"domain": "ui_tooling"},
            search_signals={"intent_labels": ("find_document",)},
            confidence={"domain": 0.9},
            embedding_queries=(
                "where to view projects and workloads in OpenShift web console",
                "OpenShift console projects workloads",
            ),
            metadata_filter={},
            debug={"mode": "unit-test"},
        ),
    )

    plan = build_retrieval_plan(
        "OpenShift 웹 콘솔에서 프로젝트와 워크로드를 확인하려면 어디를 봐야 해?",
        context=SessionContext(
            enabled_source_scopes=["official_docs"],
            preferred_source_scope="official_docs",
        ),
        candidate_k=24,
        llm_client=object(),
    )

    assert plan.retrieval_queries[0].startswith("OpenShift 웹 콘솔에서 프로젝트와 워크로드")
    assert "웹 콘솔" in plan.retrieval_queries[0]
    assert plan.retrieval_queries[1] == "where to view projects and workloads in OpenShift web console"


def test_strong_official_topic_uses_rule_based_signal_plan(monkeypatch) -> None:
    captured = {}

    def fake_build_query_signal_plan(_query, llm_client=None):
        captured["llm_client"] = llm_client
        return QuerySignalPlan(
            raw_query="ImagePullBackOff가 나면 이미지 레지스트리와 pull secret에서 무엇을 확인해야 해?",
            normalized_query="ImagePullBackOff registry pull secret",
            correction_notes=(),
            classification={"domain": "registry"},
            search_signals={"intent_labels": ("troubleshoot",)},
            confidence={"domain": 0.9},
            embedding_queries=("ImagePullBackOff registry pull secret",),
            metadata_filter={},
            debug={"mode": "unit-test"},
        )

    monkeypatch.setattr(retriever_plan, "build_query_signal_plan", fake_build_query_signal_plan)

    plan = build_retrieval_plan(
        "ImagePullBackOff가 나면 이미지 레지스트리와 pull secret에서 무엇을 확인해야 해?",
        context=SessionContext(
            enabled_source_scopes=["official_docs"],
            preferred_source_scope="official_docs",
        ),
        candidate_k=24,
        llm_client=object(),
    )

    assert captured["llm_client"] is None
    assert plan.retrieval_queries[0].startswith("ImagePullBackOff가 나면")
