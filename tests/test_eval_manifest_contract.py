from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "corpus/manifests/eval"
ACTIVE_MANIFEST_PATH = REPO_ROOT / "corpus/data/wiki_runtime_books/active_manifest.json"
EMBEDDING_CHUNKS_PATH = (
    REPO_ROOT
    / "corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl"
)
OFFICIAL_DATA_VALIDATION_PATH = EVAL_DIR / "retrieval_official_data_validation_cases.jsonl"

FOLLOW_UP_MARKERS = ("그거", "아까", "그 설정", "그 명령", "그 문서", "그 복구", "그 부분")
OFFICIAL_REQUIRED_FIELDS = {
    "id",
    "query",
    "expected_book_slugs",
    "expected_landing_terms",
    "validation_focus",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion path
            raise AssertionError(f"{path}:{line_no} is not valid JSONL: {exc}") from exc
        assert isinstance(row, dict), f"{path}:{line_no} must be a JSON object"
        rows.append(row)
    return rows


def _active_embedding_book_slugs() -> set[str]:
    slugs: set[str] = set()
    for row in _read_jsonl(EMBEDDING_CHUNKS_PATH):
        slug = str(row.get("book_slug") or "").strip()
        if slug:
            slugs.add(slug)
    return slugs


def _active_manifest_book_slugs() -> set[str]:
    payload = json.loads(ACTIVE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        str(entry.get("slug") or "").strip()
        for entry in payload.get("entries", [])
        if str(entry.get("slug") or "").strip()
    }


def test_active_official_book_set_is_29_books() -> None:
    embedding_slugs = _active_embedding_book_slugs()
    manifest_slugs = _active_manifest_book_slugs()

    assert len(embedding_slugs) == 29
    assert len(manifest_slugs) == 29
    assert embedding_slugs == manifest_slugs


def test_eval_expected_book_slugs_are_active_official_books() -> None:
    active_slugs = _active_embedding_book_slugs()
    failures: list[str] = []

    for path in sorted(EVAL_DIR.glob("*.jsonl")):
        for line_no, row in enumerate(_read_jsonl(path), start=1):
            expected = row.get("expected_book_slugs") or []
            if isinstance(expected, str):
                expected = [expected]
            invalid = [
                str(slug)
                for slug in expected
                if str(slug).strip() and str(slug).strip() not in active_slugs
            ]
            if invalid:
                case_id = row.get("id") or row.get("case_id") or f"line-{line_no}"
                failures.append(f"{path.name}:{case_id}:{invalid}")

    assert failures == []


def test_official_data_validation_cases_are_single_turn_and_complete() -> None:
    rows = _read_jsonl(OFFICIAL_DATA_VALIDATION_PATH)
    assert len(rows) == 30

    for row in rows:
        case_id = row.get("id", "<missing-id>")
        missing = sorted(field for field in OFFICIAL_REQUIRED_FIELDS if not row.get(field))
        assert missing == [], f"{case_id} missing fields: {missing}"
        assert not row.get("context"), f"{case_id} must not include context"
        assert not row.get("session_context"), f"{case_id} must not include session_context"

        query = str(row["query"])
        found_markers = [marker for marker in FOLLOW_UP_MARKERS if marker in query]
        assert found_markers == [], f"{case_id} contains follow-up markers: {found_markers}"
