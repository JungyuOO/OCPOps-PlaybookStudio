from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.llmwiki_validation_loop import build_llmwiki_validation_loop_report


def _promotion_payload(*, vector_live_total: int = 1) -> dict[str, Any]:
    return {
        "generated_at": "2026-04-26T12:00:00+09:00",
        "status": "ok",
        "ready_for_llmwiki_promotion": True,
        "official_gold": {
            "ok": True,
            "metrics": {
                "chunks_count": 100,
                "code_blocks": 8,
                "playbook_figure_blocks": 3,
            },
        },
        "customer_master": {
            "ok": True,
            "source_count": 2,
            "section_count": 4,
        },
        "runtime_report": {
            "ok": True,
            "checks": {
                "local_ui_health_ok": True,
                "embedding_sample_ok": True,
                "qdrant_collection_present": True,
                "llm_endpoint_configured": True,
            },
        },
        "runtime_maintenance": {"ok": True},
        "chat_matrix": {
            "ok": True,
            "runtime_requirements": {
                "llm_live_pass_count": 1,
                "llm_live_total": 1,
                "vector_live_pass_count": vector_live_total,
                "vector_live_total": vector_live_total,
            },
        },
    }


class LlmwikiValidationLoopTests(unittest.TestCase):
    def test_loop_stops_after_first_passing_iteration_by_default(self) -> None:
        calls: list[int] = []

        def writer(root: Path, **_kwargs: Any) -> tuple[Path, dict[str, Any]]:
            calls.append(1)
            return root / f"promotion-{len(calls)}.json", _promotion_payload()

        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_llmwiki_validation_loop_report(
                tmpdir,
                iterations=3,
                promotion_writer=writer,
            )

        self.assertTrue(report["ready"])
        self.assertEqual(1, report["completed_iterations"])
        self.assertEqual(1, len(calls))

    def test_loop_can_continue_after_passing_iteration(self) -> None:
        calls: list[int] = []

        def writer(root: Path, **_kwargs: Any) -> tuple[Path, dict[str, Any]]:
            calls.append(1)
            return root / f"promotion-{len(calls)}.json", _promotion_payload()

        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_llmwiki_validation_loop_report(
                tmpdir,
                iterations=3,
                stop_on_pass=False,
                promotion_writer=writer,
            )

        self.assertTrue(report["ready"])
        self.assertEqual(3, report["completed_iterations"])
        self.assertEqual(3, len(calls))

    def test_loop_fails_closed_when_vector_live_contract_is_missing(self) -> None:
        def writer(root: Path, **_kwargs: Any) -> tuple[Path, dict[str, Any]]:
            return root / "promotion.json", _promotion_payload(vector_live_total=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_llmwiki_validation_loop_report(
                tmpdir,
                promotion_writer=writer,
            )

        self.assertFalse(report["ready"])
        self.assertIn("chat_live_vector_ready", report["acceptance"]["failures"])
        self.assertEqual("optional_offline_allowed", report["acceptance"]["essential_services"]["surya_ocr"])


if __name__ == "__main__":
    unittest.main()
