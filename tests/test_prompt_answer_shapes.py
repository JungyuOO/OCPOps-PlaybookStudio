from __future__ import annotations

from play_book_studio.answering.models import ContextBundle
from play_book_studio.answering.prompt import SYSTEM_PROMPT, build_messages


def test_prompt_uses_explanatory_korean_grounded_contract() -> None:
    messages = build_messages(
        query="Service와 Route 연결 구조를 먼저 이해하고 싶은데, 어디를 보면 될까요?",
        mode="chat",
        context_bundle=ContextBundle(prompt_context="[1] Service exposes pods and Route exposes Service.", citations=[]),
    )

    assert messages[0]["role"] == "system"
    assert "ChatGPT에게 묻듯 친절하고 설명적인 한국어" in messages[0]["content"]
    assert "제공된 근거에 있는 내용만" in messages[0]["content"]
    assert "답변은 '답변:'으로 시작" in messages[0]["content"]
    assert "_intent_shape_hint" not in messages[1]["content"]
    assert "답변 구조 힌트" not in messages[1]["content"]


def test_user_prompt_is_only_question_session_and_context() -> None:
    messages = build_messages(
        query="PVC 상태 확인 명령 알려줘",
        mode="chat",
        context_bundle=ContextBundle(prompt_context="[1] oc get pvc", citations=[]),
        session_summary="직전에는 PVC Pending을 물었다.",
    )

    user = messages[1]["content"]
    assert user.startswith("질문: PVC 상태 확인 명령 알려줘")
    assert "세션 맥락:\n직전에는 PVC Pending을 물었다." in user
    assert "근거:\n[1] oc get pvc" in user
    assert "출력 계약" not in user
    assert "위 근거만으로, 질문에 직접 답하세요." in user


def test_system_prompt_does_not_encode_intent_specific_answer_shapes() -> None:
    assert "install_overview" not in SYSTEM_PROMPT
    assert "Secret/ConfigMap 오류 질문" not in SYSTEM_PROMPT
    assert "답변 구조 힌트" not in SYSTEM_PROMPT
