from __future__ import annotations

from play_book_studio.answering.models import ContextBundle
from play_book_studio.answering.prompt import build_messages


def _user_prompt(query: str) -> str:
    messages = build_messages(
        query=query,
        mode="chat",
        context_bundle=ContextBundle(prompt_context="[1] grounded context", citations=[]),
    )
    return messages[-1]["content"]


def test_install_overview_prompt_requests_beginner_install_structure() -> None:
    prompt = _user_prompt("OCP 설치 어떻게 해")

    assert "설치 개요 질문이면" in prompt
    assert "설치 방식 비교" in prompt
    assert "설치 전 준비물" in prompt
    assert "확인 명령" in prompt


def test_secret_config_troubleshooting_prompt_requests_judgement_flow() -> None:
    prompt = _user_prompt("Secret config error keeps happening")

    assert "Secret/ConfigMap 오류 질문이면" in prompt
    assert "확인 명령" in prompt
    assert "정상/비정상 판단 기준" in prompt
    assert "다음 분기" in prompt


def test_namespace_command_prompt_requests_direct_command_first() -> None:
    prompt = _user_prompt("namespace check command")

    assert "명령어 질문이면" in prompt
    assert "첫 문장에 바로 핵심 명령" in prompt
    assert "코드 블록" in prompt
