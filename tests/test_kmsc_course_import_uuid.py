from __future__ import annotations

import uuid

from play_book_studio.ingestion.kmsc_course_import import _chunk_metadata, _chunk_uuid, _parent_chunk_uuid, _with_parent_rows


class _FakeQuestionLlm:
    def __init__(self) -> None:
        self.messages = []

    def generate(self, messages, *, max_tokens=None):  # noqa: ANN001
        del max_tokens
        self.messages.append(messages)
        return (
            '{"starter_question_candidates":["실운영 문서에서 성능 병목은 어디서 먼저 확인하면 될까요?"],'
            '"followup_question_candidates":["TPS 목표와 테스트 환경 차이는 어떻게 이어서 확인할까요?"]}'
        )


class _FailingQuestionLlm:
    def generate(self, messages, *, max_tokens=None):  # noqa: ANN001
        del messages, max_tokens
        raise RuntimeError("llm unavailable")


def test_kmsc_chunk_uuid_accepts_existing_uuid() -> None:
    raw = str(uuid.uuid4())

    assert _chunk_uuid({"chunk_id": raw}) == raw


def test_kmsc_chunk_uuid_normalizes_slug_ids_stably() -> None:
    row = {"chunk_id": "completion--CH-02--default--none--chapter-summary--summary--54364cf6"}

    first = _chunk_uuid(row)
    second = _chunk_uuid(row)

    assert first == second
    assert str(uuid.UUID(first)) == first


def test_kmsc_parent_chunk_uuid_normalizes_slug_parent_ids() -> None:
    parent_id = _parent_chunk_uuid(
        {"parent_chunk_id": "architecture--parent--summary"},
        {},
    )

    assert str(uuid.UUID(parent_id)) == parent_id


def test_kmsc_parent_rows_are_derived_before_children() -> None:
    rows = _with_parent_rows(
        [
            {
                "chunk_id": "child-a",
                "parent_chunk_id": "parent-a",
                "source_pptx": "ops.pptx",
                "title": "성능 목표",
                "body_md": "TPS 목표를 먼저 확인합니다.",
            },
            {
                "chunk_id": "child-b",
                "parent_chunk_id": "parent-a",
                "source_pptx": "ops.pptx",
                "title": "성능 목표",
                "body_md": "Staging과 운영 환경 차이를 확인합니다.",
            },
        ]
    )

    assert rows[0]["chunk_id"] == "ops.pptx#parent-a"
    assert rows[0]["chunk_role"] == "parent"
    assert rows[0]["child_chunk_ids"] == ["child-a", "child-b"]
    assert rows[1]["parent_chunk_id"] == "parent-a"


def test_kmsc_parent_metadata_generates_starter_questions_from_course_chunk_text() -> None:
    llm = _FakeQuestionLlm()
    parent = _with_parent_rows(
        [
            {
                "chunk_id": "child-a",
                "parent_chunk_id": "parent-a",
                "source_pptx": "ops.pptx",
                "title": "성능 목표",
                "body_md": "TPS 목표와 운영 환경 차이를 먼저 확인합니다.",
            }
        ]
    )[0]

    metadata = _chunk_metadata(parent, question_llm_client=llm)
    prompt_text = "\n".join(message["content"] for message in llm.messages[0])

    assert "TPS 목표와 운영 환경 차이" in prompt_text
    assert metadata["starter_question_candidates"] == ["실운영 문서에서 성능 병목은 어디서 먼저 확인하면 될까요?"]
    assert metadata["question_candidates_version"] == 2


def test_kmsc_summary_kind_metadata_generates_starter_questions_from_course_chunk_text() -> None:
    llm = _FakeQuestionLlm()

    metadata = _chunk_metadata(
        {
            "chunk_id": "architecture--design-summary--summary--3e8f3baf",
            "chunk_kind": "design_summary",
            "source_pptx": "ops.pptx",
            "title": "Architecture design",
            "body_md": "Review production network configuration and storage networking.",
        },
        question_llm_client=llm,
    )
    prompt_text = "\n".join(message["content"] for message in llm.messages[0])

    assert "Review production network configuration and storage networking." in prompt_text
    assert metadata["starter_question_candidates"]
    assert metadata["question_candidates_version"] == 2


def test_kmsc_chunk_with_children_generates_starter_questions_without_chunk_role() -> None:
    llm = _FakeQuestionLlm()

    metadata = _chunk_metadata(
        {
            "chunk_id": "ops.pptx#parent-a",
            "child_chunk_ids": ["child-a"],
            "source_pptx": "ops.pptx",
            "title": "Course section",
            "body_md": "Review the course section before checking child chunks.",
        },
        question_llm_client=llm,
    )

    assert len(llm.messages) == 1
    assert metadata["question_candidates_version"] == 2


def test_kmsc_leaf_metadata_does_not_call_question_llm() -> None:
    llm = _FakeQuestionLlm()
    metadata = _chunk_metadata(
        {
            "chunk_id": "child-a",
            "parent_chunk_id": "parent-a",
            "source_pptx": "ops.pptx",
            "title": "성능 목표",
            "body_md": "TPS 목표를 확인합니다.",
        },
        question_llm_client=llm,
    )

    assert llm.messages == []
    assert metadata["starter_question_candidates"] == []
    assert metadata["question_candidates_version"] == 0


def test_kmsc_test_case_summary_metadata_does_not_call_question_llm() -> None:
    llm = _FakeQuestionLlm()
    metadata = _chunk_metadata(
        {
            "chunk_id": "unit--test-case-summary--summary--abc",
            "chunk_kind": "test_case_summary",
            "child_chunk_ids": ["unit--test-case-method--abc"],
            "source_pptx": "ops.pptx",
            "title": "Test case",
            "body_md": "Review test case purpose and expected result.",
        },
        question_llm_client=llm,
    )

    assert llm.messages == []
    assert metadata["starter_question_candidates"] == []
    assert metadata["question_candidates_version"] == 0


def test_kmsc_starter_generation_warning_when_llm_client_missing() -> None:
    metadata = _chunk_metadata(
        {
            "chunk_id": "completion--chapter-summary--summary--abc",
            "chunk_kind": "chapter_summary",
            "source_pptx": "ops.pptx",
            "title": "Chapter",
            "body_md": "Review operating document prerequisites.",
        }
    )

    assert metadata["starter_question_candidates"] == []
    assert metadata["question_candidates_version"] == 0
    assert metadata["question_candidates_warning"] == "llm_client_missing"


def test_kmsc_starter_generation_warning_when_llm_returns_empty() -> None:
    metadata = _chunk_metadata(
        {
            "chunk_id": "perf--section-summary--summary--abc",
            "chunk_kind": "perf_section_summary",
            "source_pptx": "ops.pptx",
            "title": "Performance",
            "body_md": "Review performance baseline and bottlenecks.",
        },
        question_llm_client=_FailingQuestionLlm(),
    )

    assert metadata["starter_question_candidates"] == []
    assert metadata["question_candidates_version"] == 0
    assert metadata["question_candidates_warning"] == "llm_generation_failed_or_empty"
