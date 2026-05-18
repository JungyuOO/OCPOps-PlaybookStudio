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

    assert question == "설치 검증 실패 시 어떤 로그와 상태를 먼저 확인하나요?"
    assert "What should" not in question
    assert "문서를 기준으로" not in question
    assert "Day-2" not in question
    assert "검증 및 문제 해결 기준으로" not in question
    assert "troubleshoot" not in question.lower()


def test_learning_questions_are_beginner_natural_language() -> None:
    day2 = _beginner_learning_question(_rule("day2"), "Postinstallation configuration")
    networking = _beginner_learning_question(_rule("networking"), "Networking overview")

    assert day2 == "설치 후 구성 작업은 어떤 흐름으로 이해하면 될까요?"
    assert networking == "Route가 Service를 통해 애플리케이션을 노출하는 구조는 어떻게 이해하면 될까요?"
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

    assert question == "성능 테스트 결과에서 목표와 병목은 어떤 순서로 확인하나요?"
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

    assert question == "운영 점검에서 Node 상태는 어떤 기준으로 확인하나요?"
    assert "검증부터 보기" not in question


def test_operations_chunk_question_cleans_generic_section_suffix() -> None:
    question = _ops_chunk_question(
        {
            "title": "사업 범위와 추진 배경 보기",
            "learning_goal": "사업 범위와 추진 배경을 확인한다.",
            "source_terms": ["사업 범위", "추진 배경"],
        }
    )

    assert question == "KMSC 운영 문서 근거로 확인할 항목과 판단 기준은 무엇인가요?"
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


def test_starter_fallback_questions_are_rag_answerable_and_lane_specific() -> None:
    official_storage = _official_faq_query(_rule("storage"), "Storage")
    learning_network = _beginner_learning_question(_rule("networking"), "Networking overview")
    operations_network = _ops_chunk_question(
        {
            "title": "Service Route 연결 확인",
            "learning_goal": "운영 문서 기준으로 연결 흐름을 확인한다.",
            "source_terms": ["Service", "Route", "운영"],
        }
    )

    assert official_storage == "PVC와 PV 바인딩 상태는 어떤 명령으로 확인하나요?"
    assert "어디부터" not in official_storage
    assert "처음에 어디" not in official_storage
    assert learning_network != operations_network
    assert operations_network == "운영 문서에서 Service와 Route 연결 확인은 어떤 흐름으로 보나요?"
