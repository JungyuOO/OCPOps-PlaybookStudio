from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.chat_matrix_smoke import build_chat_matrix_smoke


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


def _write_cases(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _suggestions() -> dict[str, object]:
    return {
        "suggested_queries": [
            "다음 행동을 알려줘",
            "적용 후 검증 방법도 알려줘",
            "실패하면 어디부터 봐야 해?",
        ],
        "suggested_followups": [
            {"query": "다음 행동을 알려줘", "dimension": "next_action", "label": "다음 행동"},
            {"query": "적용 후 검증 방법도 알려줘", "dimension": "verify", "label": "검증"},
            {"query": "실패하면 어디부터 봐야 해?", "dimension": "branch", "label": "분기"},
        ],
    }


class ChatMatrixSmokeTests(unittest.TestCase):
    def test_chat_matrix_passes_when_expected_lanes_books_and_code_are_cited(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "blended-code",
                        "query": "고객 문서와 공식 BuildConfig 문서를 같이 봐줘",
                        "payload": {"restrict_uploaded_sources": False},
                        "expected_collections": ["uploaded", "core"],
                        "expected_book_slugs_any": [
                            "customer-master-kmsc-ocp-operations-playbook",
                            "builds_using_buildconfig",
                        ],
                        "require_code_block": True,
                        "must_include_terms": ["BuildConfig"],
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: BuildConfig 점검은 고객 운영 기준과 공식 문서를 함께 확인합니다 [1][2].\n```bash\noc get buildconfig\n```",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1, 2],
                "citations": [
                    {
                        "index": 1,
                        "source_collection": "uploaded",
                        "book_slug": "customer-master-kmsc-ocp-operations-playbook",
                    },
                    {
                        "index": 2,
                        "source_collection": "core",
                        "book_slug": "builds_using_buildconfig",
                    },
                ],
                "retrieval_trace": {"selected": []},
                **_suggestions(),
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("ok", report["status"])
            self.assertEqual(1, report["pass_count"])
            self.assertTrue(report["results"][0]["checks"]["code_block"])
            self.assertTrue(report["results"][0]["checks"]["llm_runtime_live"])
            self.assertTrue(report["results"][0]["checks"]["vector_runtime_live"])

    def test_chat_matrix_can_require_live_llm_and_vector_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "live-runtime",
                        "query": "고객 운영북과 공식문서를 같이 봐줘",
                        "expected_collections": ["uploaded", "core"],
                        "require_llm_runtime": True,
                        "require_vector_runtime": True,
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: 고객 운영북과 공식 문서를 함께 확인합니다 [1][2].",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1, 2],
                "citations": [
                    {
                        "index": 1,
                        "source_collection": "uploaded",
                        "book_slug": "customer-master-kmsc-ocp-operations-playbook",
                    },
                    {
                        "index": 2,
                        "source_collection": "core",
                        "book_slug": "architecture",
                    },
                ],
                "pipeline_trace": {
                    "llm": {
                        "last_provider": "openai-compatible",
                        "last_fallback_used": False,
                        "provider_round_trip_ms": 321.5,
                    }
                },
                "retrieval_trace": {
                    "vector_runtime": {
                        "subquery_count": 1,
                        "endpoint_used": "search",
                        "endpoints_used": ["search"],
                        "empty_subqueries": 0,
                    }
                },
                **_suggestions(),
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("ok", report["status"])
            self.assertEqual(1, report["runtime_requirements"]["llm_live_pass_count"])
            self.assertEqual(1, report["runtime_requirements"]["vector_live_pass_count"])
            self.assertTrue(report["results"][0]["checks"]["llm_runtime_live"])
            self.assertTrue(report["results"][0]["checks"]["vector_runtime_live"])

    def test_chat_matrix_fails_live_runtime_gate_when_trace_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "missing-runtime",
                        "query": "고객 운영북과 공식문서를 같이 봐줘",
                        "expected_collections": ["uploaded", "core"],
                        "require_llm_runtime": True,
                        "require_vector_runtime": True,
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: 고객 운영북과 공식 문서를 함께 확인합니다 [1][2].",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1, 2],
                "citations": [
                    {"index": 1, "source_collection": "uploaded", "book_slug": "customer-master"},
                    {"index": 2, "source_collection": "core", "book_slug": "architecture"},
                ],
                "retrieval_trace": {"selected": []},
                **_suggestions(),
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("fail", report["status"])
            self.assertFalse(report["results"][0]["checks"]["llm_runtime_live"])
            self.assertFalse(report["results"][0]["checks"]["vector_runtime_live"])

    def test_chat_matrix_blocks_before_cases_when_runtime_dependency_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "needs-runtime",
                        "query": "고객 운영북과 공식문서를 같이 봐줘",
                        "require_dependency_preflight": True,
                    }
                ],
            )

            with (
                patch(
                    "play_book_studio.app.chat_matrix_smoke._runtime_dependency_status",
                    return_value={"status": "blocked", "ready": False, "failures": ["qdrant: connection refused"]},
                ),
                patch("play_book_studio.app.chat_matrix_smoke.requests.post") as post_mock,
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("blocked", report["status"])
            self.assertEqual(["qdrant: connection refused"], report["failures"])
            self.assertFalse(report["results"][0]["checks"]["runtime_dependency_preflight"])
            post_mock.assert_not_called()

    def test_chat_matrix_fails_when_expected_collection_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "needs-uploaded",
                        "query": "고객 문서 기준 설명해줘",
                        "expected_collections": ["uploaded"],
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: 공식 문서 기준 설명입니다 [1].",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1],
                "citations": [
                    {
                        "index": 1,
                        "source_collection": "core",
                        "book_slug": "architecture",
                    }
                ],
                "retrieval_trace": {"selected": []},
                **_suggestions(),
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("fail", report["status"])
            self.assertFalse(report["results"][0]["checks"]["expected_collections"])

    def test_chat_matrix_fails_when_structured_followups_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "needs-next-play",
                        "query": "BuildConfig 점검 순서를 알려줘",
                        "expected_collections": ["core"],
                        "expected_book_slugs": ["builds_using_buildconfig"],
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: BuildConfig 상태를 확인합니다 [1].",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1],
                "citations": [
                    {
                        "index": 1,
                        "source_collection": "core",
                        "book_slug": "builds_using_buildconfig",
                    }
                ],
                "suggested_queries": ["다음 질문"],
                "retrieval_trace": {"selected": []},
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("fail", report["status"])
            self.assertFalse(report["results"][0]["checks"]["structured_followups"])

    def test_chat_matrix_fails_when_suggested_queries_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_path = root / "cases.jsonl"
            _write_cases(
                cases_path,
                [
                    {
                        "id": "needs-legacy-next-play",
                        "query": "BuildConfig 점검 순서를 알려줘",
                        "expected_collections": ["core"],
                        "expected_book_slugs": ["builds_using_buildconfig"],
                    }
                ],
            )
            fake_payload = {
                "answer": "답변: BuildConfig 상태를 확인합니다 [1].",
                "response_kind": "rag",
                "warnings": [],
                "cited_indices": [1],
                "citations": [
                    {
                        "index": 1,
                        "source_collection": "core",
                        "book_slug": "builds_using_buildconfig",
                    }
                ],
                "suggested_followups": [
                    {"query": "다음 행동", "dimension": "next_action"},
                    {"query": "검증", "dimension": "verify"},
                    {"query": "분기", "dimension": "branch"},
                ],
                "retrieval_trace": {"selected": []},
            }

            with patch(
                "play_book_studio.app.chat_matrix_smoke.requests.post",
                return_value=_FakeResponse(fake_payload),
            ):
                report = build_chat_matrix_smoke(
                    root,
                    ui_base_url="http://127.0.0.1:8896",
                    cases_path=cases_path,
                )

            self.assertEqual("fail", report["status"])
            self.assertFalse(report["results"][0]["checks"]["suggested_queries_present"])


if __name__ == "__main__":
    unittest.main()
