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

from play_book_studio.app.data_control_room import _build_llmwiki_promotion_control_status


def _write_report(root: Path, *, head: str = "abc123") -> Path:
    reports_dir = root / ".kugnusdocs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-04-25-llmwiki-promotion-report-v1.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-25T23:13:39+09:00",
                "git": {"branch": "feat/pipe-kugnus", "head": head},
                "status": "ok",
                "ready_for_llmwiki_promotion": True,
                "summary": {"status": "ok", "ready_for_llmwiki_promotion": True, "failures": []},
                "official_gold": {
                    "ok": True,
                    "metrics": {
                        "chunks_count": 87858,
                        "bm25_count": 87858,
                        "code_blocks": 27191,
                        "playbook_figure_blocks": 454,
                    },
                },
                "customer_master": {
                    "ok": True,
                    "source_count": 10,
                    "section_count": 10,
                    "chunk_count": 10,
                    "validation": {"source_coverage_ratio": 1.0},
                },
                "runtime_report": {"ok": True},
                "runtime_maintenance": {"ok": True},
                "chat_matrix": {
                    "ok": True,
                    "runtime_requirements": {
                        "llm_live_pass_count": 2,
                        "llm_live_total": 2,
                        "vector_live_pass_count": 2,
                        "vector_live_total": 2,
                    },
                },
                "evidence": {"chat_matrix": "chat.json"},
                "commands": {"promotion_report": "python -m play_book_studio.cli llmwiki-promotion"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


class DataControlRoomLlmWikiTests(unittest.TestCase):
    def test_missing_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/pipe-kugnus", "head": "abc123", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_promotion_control_status(root)

        self.assertEqual("missing", status["status"])
        self.assertFalse(status["ready"])
        self.assertTrue(status["selected_report"]["stale"])

    def test_current_report_builds_status_rail_and_mode_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_report(root, head="abc123")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/pipe-kugnus", "head": "abc123", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_promotion_control_status(root)

        self.assertEqual("ok", status["status"])
        self.assertTrue(status["ready"])
        self.assertFalse(status["selected_report"]["stale"])
        self.assertEqual(5, len(status["status_rail"]))
        self.assertEqual(87858, status["metrics"]["official_chunks_count"])
        self.assertEqual(4, status["metrics"]["chat_live_pass_count"])
        supported_modes = status["mode_contract"]["supported_modes"]
        self.assertEqual(["learn", "ops"], [item["id"] for item in supported_modes])

    def test_head_mismatch_marks_report_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_report(root, head="old")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/pipe-kugnus", "head": "new", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_promotion_control_status(root)

        self.assertEqual("stale", status["status"])
        self.assertFalse(status["ready"])
        self.assertTrue(status["selected_report"]["stale"])


if __name__ == "__main__":
    unittest.main()
