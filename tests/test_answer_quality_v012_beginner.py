import json
from pathlib import Path

from play_book_studio.config.corpus_paths import PBS_CHAT_QUALITY_V012_BEGINNER_CASES_PATH


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_cases() -> list[dict]:
    path = REPO_ROOT / PBS_CHAT_QUALITY_V012_BEGINNER_CASES_PATH
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_v012_beginner_cases_are_schema_valid() -> None:
    cases = _load_cases()

    assert [case["id"] for case in cases] == [f"v012-beginner-{index:03d}" for index in range(1, 7)]
    for case in cases:
        assert case["mode"] == "beginner"
        assert case["query"].strip()
        assert case["expected_book_slugs"]
        assert case["must_include_terms"]
        assert case["clarification_expected"] is False
        assert case["no_answer_expected"] is False


