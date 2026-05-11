from __future__ import annotations

from pathlib import Path

from play_book_studio.http.starter_questions import (
    STARTER_GROUPS,
    STARTER_CATEGORY_RULES,
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


def test_official_faq_templates_are_readable_and_not_english_placeholders() -> None:
    question = _official_faq_query(_rule("troubleshooting"), "검증 및 문제 해결")

    assert question == "검증 및 문제 해결 문서를 기준으로 장애를 좁힐 때 먼저 확인할 증상, 로그, 명령어는 뭐야?"
    assert "What should" not in question


def test_operations_chunk_question_uses_chunk_terms_without_fixed_user_query() -> None:
    question = _ops_chunk_question(
        {
            "title": "성능 목표와 조건 먼저 보기",
            "learning_goal": "성능 목표와 테스트 환경을 먼저 확인한다.",
            "source_terms": ["TPS 목표", "테스트 환경"],
            "query_variants": ["성능 테스트는 어떤 목표와 조건부터 확인해야 해?"],
        }
    )

    assert question == "성능 목표와 조건 먼저 보기에서 TPS 목표, 테스트 환경 기준으로 먼저 확인할 것은 뭐야?"
    assert "성능 테스트는 어떤 목표와 조건부터 확인해야 해?" not in question


def test_empty_starter_payload_keeps_readable_group_titles(tmp_path: Path) -> None:
    payload = build_studio_starter_questions(tmp_path, seed="stable")
    groups = {str(group["key"]): group for group in payload["groups"]}

    assert groups["faq"]["title"] == "자주 묻는 질문"
    assert groups["operations"]["description"] == "KMSC 운영 문서 기반 질문"
