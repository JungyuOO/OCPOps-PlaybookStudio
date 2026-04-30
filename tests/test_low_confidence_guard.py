from play_book_studio.answering.answerer import (
    _is_low_confidence_retrieval,
    _low_confidence_clarification_answer,
)
from play_book_studio.answering.models import Citation
from play_book_studio.app.session_flow import suggest_follow_up_questions
from play_book_studio.app.sessions import ChatSession
from play_book_studio.answering.models import AnswerResult


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

    assert "조금 더" in answer
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
