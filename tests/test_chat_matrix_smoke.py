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


if __name__ == "__main__":
    unittest.main()
