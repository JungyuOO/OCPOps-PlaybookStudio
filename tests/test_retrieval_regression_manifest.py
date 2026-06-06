from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.evals.rag_foundation_audit import DEFAULT_RETRIEVAL_CASES


REPO_ROOT = Path(__file__).resolve().parents[1]
REGRESSION_CASES = Path("corpus/manifests/eval/retrieval_official_hit1_regression_cases.jsonl")


def test_official_hit1_regression_manifest_is_valid() -> None:
    path = REPO_ROOT / REGRESSION_CASES
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) == 17
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["query_type"] == "official_hit1_regression" for row in rows)
    assert all(row["expected_source_scopes"] == ["official_docs"] for row in rows)
    assert all(row.get("expected_book_slugs") for row in rows)
    assert all(row.get("original_suite") and row.get("original_id") for row in rows)


def test_official_hit1_regression_manifest_is_not_a_default_go_no_go_gate() -> None:
    assert REGRESSION_CASES not in DEFAULT_RETRIEVAL_CASES
