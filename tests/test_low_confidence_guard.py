from play_book_studio.answering.answerer import (
    _confidence_tokens,
    _is_low_confidence_retrieval,
    _low_confidence_query_input,
    _low_confidence_clarification_answer,
)
from play_book_studio.answering.models import Citation
from play_book_studio.http.session_flow import suggest_follow_up_questions
from play_book_studio.http.sessions import ChatSession
from play_book_studio.answering.models import AnswerResult
from play_book_studio.retrieval.models import SessionContext


def _citation(**overrides) -> Citation:
    payload = {
        "index": 1,
        "chunk_id": "nodes-ready",
        "book_slug": "nodes",
        "section": "6.1.1. 클러스터의 모든 노드 나열 정보",
        "anchor": "nodes-ready",
        "source_url": "",
        "viewer_path": "/docs/ocp/4.20/ko/nodes/index.html#nodes-ready",
        "excerpt": "oc get nodes 명령으로 노드 Ready 상태를 확인합니다.",
    }
    payload.update(overrides)
    return Citation(**payload)


def test_low_confidence_guard_blocks_mismatched_retrieval() -> None:
    assert _is_low_confidence_retrieval(
        query="성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
        citations=[_citation()],
        selected_hits=[
            {
                "section": "6.1.1. 클러스터의 모든 노드 나열 정보",
                "book_slug": "nodes",
                "fused_score": -5.0,
                "pre_rerank_fused_score": 0.02,
            }
        ],
    )


def test_low_confidence_guard_allows_matching_command_grounding() -> None:
    assert not _is_low_confidence_retrieval(
        query="노드 Ready 상태를 확인하는 명령을 알려줘",
        citations=[_citation(cli_commands=("oc get nodes",))],
        selected_hits=[
            {
                "section": "6.1.1. 클러스터의 모든 노드 나열 정보",
                "book_slug": "nodes",
                "fused_score": 0.2,
                "pre_rerank_fused_score": 0.12,
            }
        ],
    )


def test_low_confidence_answer_includes_example_questions() -> None:
    answer = _low_confidence_clarification_answer(
        selected_hits=[
            {
                "section": "6.1.1. 클러스터의 모든 노드 나열 정보",
                "book_slug": "nodes",
            }
        ]
    )

    assert "한 단계만 더 좁혀" in answer
    assert "클러스터의 모든 노드 나열 정보 기준으로" in answer
    assert "6.1.1." not in answer


def test_low_confidence_guard_allows_guided_learning_questions() -> None:
    assert not _is_low_confidence_retrieval(
        query="Operations 단계에서는 Machine Config Operator 기준으로 무엇을 순서대로 학습하면 돼?",
        citations=[_citation(section="1.1. 설치 후 구성 작업")],
        selected_hits=[
            {
                "section": "1.1. 설치 후 구성 작업",
                "book_slug": "postinstallation_configuration",
                "fused_score": -3.0,
                "pre_rerank_fused_score": 0.01,
            }
        ],
    )


def test_low_confidence_guard_allows_ocp_install_overview_grounding() -> None:
    assert not _is_low_confidence_retrieval(
        query="OCP 설치 어떻게 해",
        citations=[
            _citation(
                book_slug="installation_overview",
                section="OpenShift Container Platform 설치 정보",
                excerpt="OpenShift Container Platform 설치 프로그램은 클러스터를 배포하는 여러 설치 방법을 제공합니다.",
            )
        ],
        selected_hits=[
            {
                "section": "OpenShift Container Platform 설치 정보",
                "book_slug": "installation_overview",
                "fused_score": -4.0,
                "pre_rerank_fused_score": 0.01,
            }
        ],
    )


def test_confidence_tokens_strip_latin_korean_josa_for_product_terms() -> None:
    tokens = _confidence_tokens("observability와 monitoring은 어떻게 달라?")

    assert "observability" in tokens
    assert "monitoring" in tokens
    assert "observability와" not in tokens
    assert "monitoring은" not in tokens


def test_low_confidence_guard_allows_observability_monitoring_comparison() -> None:
    assert not _is_low_confidence_retrieval(
        query="observability와 monitoring은 어떻게 달라?",
        citations=[
            _citation(
                book_slug="observability_overview",
                section="Observability 정보",
                excerpt="Observability는 monitoring, logging, telemetry 신호를 함께 사용해 클러스터 상태를 이해합니다.",
            )
        ],
        selected_hits=[
            {
                "section": "Observability 정보",
                "book_slug": "observability_overview",
                "fused_score": 0.03,
                "pre_rerank_fused_score": 0.02,
                "vector_score": 0.02,
            }
        ],
    )


def test_follow_up_low_confidence_uses_session_rewritten_query_context() -> None:
    query = "아까 말한 이미지 저장소는?"
    rewritten_query = "OCP 4.20 | 주제 외부 이미지 레지스트리 구성 | 엔터티 registry, image registry | 아까 말한 이미지 저장소는?"
    confidence_query = _low_confidence_query_input(
        query=query,
        rewritten_query=rewritten_query,
        context=SessionContext(
            mode="ops",
            current_topic="외부 이미지 레지스트리 구성",
            open_entities=["registry", "image registry"],
            ocp_version="4.20",
        ),
    )

    assert "registry" in confidence_query
    assert not _is_low_confidence_retrieval(
        query=confidence_query,
        citations=[
            _citation(
                book_slug="registry",
                section="OpenShift Container Registry",
                excerpt="OpenShift Container Registry는 클러스터 내부 이미지 저장소로 registry 및 image registry 구성을 다룹니다.",
            )
        ],
        selected_hits=[
            {
                "section": "OpenShift Container Registry",
                "book_slug": "registry",
                "fused_score": 0.03,
                "pre_rerank_fused_score": 0.02,
                "vector_score": 0.02,
            }
        ],
    )


def test_low_confidence_guard_allows_beginner_secret_config_troubleshooting_grounding() -> None:
    assert not _is_low_confidence_retrieval(
        query="Secret config error keeps happening",
        citations=[
            _citation(
                book_slug="applications",
                section="Troubleshooting application configuration",
                excerpt="Use oc describe pod to inspect events and verify Secret or ConfigMap volume and environment variable configuration.",
            )
        ],
        selected_hits=[
            {
                "fused_score": 0.03,
                "pre_rerank_fused_score": 0.02,
                "vector_score": 0.02,
            }
        ],
    )


def test_low_confidence_followups_use_retrieval_hits_without_overlap() -> None:
    session = ChatSession(session_id="s1", mode="ops")
    result = AnswerResult(
        query="성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
        mode="ops",
        answer="답변: 지금 질문은 현재 공식 문서 근거와 정확히 맞물리는 점수가 낮습니다.",
        rewritten_query="성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
        citations=[],
        response_kind="clarification",
        warnings=["low retrieval confidence"],
        retrieval_trace={
            "metrics": {
                "hybrid": {
                    "top_hits": [
                        {
                            "section": "6.1.1. 클러스터의 모든 노드 나열 정보",
                            "book_slug": "nodes",
                        }
                    ]
                }
            }
        },
    )

    suggestions = suggest_follow_up_questions(session=session, result=result)

    assert suggestions == ["클러스터의 모든 노드 나열 정보 기준으로 설명해줘"]
