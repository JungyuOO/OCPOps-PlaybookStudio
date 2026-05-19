from play_book_studio.answering.router import route_non_rag
from play_book_studio.answering.context import _should_force_clarification
from play_book_studio.retrieval.models import RetrievalHit


def test_security_ambiguity_asks_which_security_scope() -> None:
    routed = route_non_rag("보안 문제는 어디서 봐?")

    assert routed is not None
    assert routed.route == "clarification"
    assert "어떤 보안 문제" in routed.answer


def test_postinstall_ambiguity_asks_what_to_do_first() -> None:
    routed = route_non_rag("설치 후에 뭐 먼저 해야 해?")

    assert routed is not None
    assert routed.route == "clarification"
    assert "무엇을 먼저" in routed.answer


def test_observability_comparison_is_not_treated_as_ambiguous() -> None:
    assert route_non_rag("Monitoring, Logging, Observability를 운영 관점에서 구분해서 설명해줘") is None


def test_short_operational_status_question_is_not_smalltalk() -> None:
    assert route_non_rag("PVC가 Pending인데 뭐 확인해야 해?") is None


def test_active_uploaded_document_questions_can_mention_external_product_names() -> None:
    assert route_non_rag("ArgoCD에서 path 설정 방법은?", allow_unsupported_product=True) is None

    routed = route_non_rag("ArgoCD에서 path 설정 방법은?")
    assert routed is not None
    assert routed.route == "no_answer"


def test_korean_only_operational_questions_are_not_smalltalk() -> None:
    for query in (
        "디플로이먼트 상태 어떻게봐?",
        "라우트 어떻게 만들어?",
        "파드 로그 봐줘",
    ):
        assert route_non_rag(query) is None


def test_explicit_smalltalk_still_routes_to_smalltalk() -> None:
    for query in ("안녕", "고마워"):
        routed = route_non_rag(query)
        assert routed is not None
        assert routed.route == "smalltalk"


def test_v016_basic_ocp_command_questions_are_not_smalltalk() -> None:
    queries = [
        "추가 OAuth 클라이언트는 어떻게 등록해?",
        "CSR 승인은 어떤 명령어로 진행해?",
        "새 프로젝트는 어떻게 만들어?",
        "새 애플리케이션은 어떻게 만들어?",
        "현재 선택된 프로젝트는 어떻게 확인해?",
        "현재 프로젝트 상태는 어떻게 확인해?",
        "지원되는 API 리소스 목록은 어떻게 봐?",
    ]

    for query in queries:
        routed = route_non_rag(query)
        assert routed is None, query


def test_v016_operational_questions_bypass_force_clarification() -> None:
    hits = [
        RetrievalHit(
            chunk_id="1",
            book_slug="events",
            chapter="",
            section="cluster events",
            anchor="a",
            source_url="",
            viewer_path="",
            text="oc get events",
            source="official",
            raw_score=0.01,
        ),
        RetrievalHit(
            chunk_id="2",
            book_slug="nodes",
            chapter="",
            section="node list",
            anchor="b",
            source_url="",
            viewer_path="",
            text="oc get nodes",
            source="official",
            raw_score=0.01,
        ),
    ]

    assert _should_force_clarification(hits, query="클러스터 이벤트는 어떻게 확인해?") is False
