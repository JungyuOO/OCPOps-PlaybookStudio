from __future__ import annotations

from pathlib import Path

from play_book_studio.http.starter_questions import (
    STARTER_CATEGORY_RULES,
    STARTER_GROUPS,
    _beginner_learning_question,
    _official_faq_query,
    _ops_chunk_question,
    build_studio_starter_questions,
)


def _rule(key: str):
    for rule in STARTER_CATEGORY_RULES:
        if rule.key == key:
            return rule
    raise AssertionError(f"missing rule: {key}")


def test_starter_group_labels_are_readable_korean() -> None:
    groups = {str(group["key"]): group for group in STARTER_GROUPS}

    assert groups["faq"]["title"] == "자주 묻는 질문"
    assert groups["learning"]["title"] == "단계별 학습 질문"
    assert groups["operations"]["title"] == "실운영 문서 질문"


def test_official_faq_questions_are_composed_as_beginner_language() -> None:
    question = _official_faq_query(_rule("troubleshooting"), "검증 및 문제 해결")

    assert question == "문제 해결은 어디부터 확인하면 될까요?"
    assert "What should" not in question
    assert "문서를 기준으로" not in question
    assert "Day-2" not in question
    assert "검증 및 문제 해결 기준으로" not in question
    assert "troubleshoot" not in question.lower()


def test_learning_questions_are_beginner_natural_language() -> None:
    day2 = _beginner_learning_question(_rule("day2"), "Postinstallation configuration")
    networking = _beginner_learning_question(_rule("networking"), "Networking overview")

    assert day2 == "설치 후 작업은 무엇부터 이어서 진행하면 될까요?"
    assert networking == "Service와 Route 연결 구조를 먼저 이해하고 싶은데, 어디를 보면 될까요?"
    assert "Day-2" not in day2
    assert "Networking overview" not in networking


def test_operations_chunk_question_uses_chunk_context_without_fixed_query_variant() -> None:
    question = _ops_chunk_question(
        {
            "title": "성능 목표와 조건 먼저 보기",
            "learning_goal": "성능 목표와 테스트 환경을 먼저 확인한다.",
            "source_terms": ["TPS 목표", "테스트 환경"],
            "query_variants": ["성능 테스트는 어떤 목표와 조건부터 확인해야 해?"],
        }
    )

    assert question == "성능 결과에서 목표와 조건은 어디를 먼저 보면 될까요?"
    assert "성능 테스트는 어떤 목표와 조건부터 확인해야 해?" not in question
    assert "성능 목표와 조건 먼저 보기에서" not in question


def test_operations_chunk_question_does_not_expose_chunk_title_suffix() -> None:
    question = _ops_chunk_question(
        {
            "title": "노드 상태 검증부터 보기",
            "learning_goal": "노드 상태를 검증한다.",
            "source_terms": ["노드 상태", "검증"],
        }
    )

    assert question == "노드 상태는 처음에 어디를 보면 될까요?"
    assert "검증부터 보기" not in question


def test_operations_chunk_question_cleans_generic_section_suffix() -> None:
    question = _ops_chunk_question(
        {
            "title": "사업 범위와 추진 배경 보기",
            "learning_goal": "사업 범위와 추진 배경을 확인한다.",
            "source_terms": ["사업 범위", "추진 배경"],
        }
    )

    assert question == "실운영 문서에서 무엇부터 확인하면 될까요?"
    assert "보기" not in question


def test_empty_starter_payload_keeps_readable_group_titles(tmp_path: Path) -> None:
    payload = build_studio_starter_questions(tmp_path, seed="stable")
    groups = {str(group["key"]): group for group in payload["groups"]}

    assert groups["faq"]["title"] == "자주 묻는 질문"
    assert groups["operations"]["description"] == "KMSC 운영 문서 기반 질문"


def test_learning_starter_questions_rotate_by_seed(tmp_path: Path) -> None:
    first = build_studio_starter_questions(tmp_path, seed="alice")
    second = build_studio_starter_questions(tmp_path, seed="bob")

    first_questions = [item["question"] for group in first["groups"] if group["key"] == "learning" for item in group["questions"]]
    second_questions = [item["question"] for group in second["groups"] if group["key"] == "learning" for item in group["questions"]]

    assert first_questions
    assert second_questions
    assert first_questions != second_questions
    assert all("단계에서는" not in question for question in first_questions + second_questions)
