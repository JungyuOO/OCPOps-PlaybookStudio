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

from play_book_studio.app.data_control_room import (
    _build_development_control_status,
    _build_llmwiki_contextual_enrichment_control_status,
    _build_llmwiki_evolution_gate_control_status,
    _build_llmwiki_promotion_control_status,
    _build_llmwiki_validation_loop_control_status,
)


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
                        "ko_localization_status": "ok",
                        "ko_localization_failing_book_count": 0,
                        "ko_localization_book_count": 113,
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


def _write_loop_report(root: Path, *, head: str = "abc123") -> Path:
    reports_dir = root / ".kugnusdocs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-04-26-llmwiki-validation-loop.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-26T01:00:00+09:00",
                "git": {"branch": "feat/dev-kugnus", "head": head},
                "status": "ok",
                "ready": True,
                "requested_iterations": 2,
                "completed_iterations": 2,
                "surya_policy": {
                    "status": "offline_allowed",
                    "required_for_llmwiki_runtime": False,
                },
                "acceptance": {
                    "ok": True,
                    "failures": [],
                    "essential_services": {
                        "embedding": True,
                        "qdrant": True,
                        "chat_llm": True,
                        "chat_vector": True,
                        "surya_ocr": "optional_offline_allowed",
                    },
                    "metrics": {
                        "official_chunks": 87858,
                        "official_code_blocks": 27191,
                        "official_figures": 454,
                        "customer_sources": 10,
                        "customer_sections": 10,
                        "chat_live_pass_count": 4,
                        "chat_live_total": 4,
                    },
                },
                "commands": {"validation_loop": "python -m play_book_studio.cli llmwiki-loop"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def _write_evolution_gate_report(root: Path, *, head: str = "abc123") -> Path:
    reports_dir = root / ".kugnusdocs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-04-27-llmwiki-evolution-gate.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-27T02:00:00+09:00",
                "git": {"branch": "feat/dev-kugnus", "head": head},
                "status": "ok",
                "ready": True,
                "checks": {
                    "retrieval_quality_critic_ready": True,
                    "wiki_backwrite_candidate_ready": True,
                    "wiki_lint_anti_rot_ready": True,
                },
                "failures": [],
                "retrieval_quality_critic": {"blocker_count": 0, "warning_count": 1},
                "wiki_backwrite_candidate": {"candidate_count": 6},
                "wiki_lint_anti_rot": {"blocker_count": 0, "warning_count": 0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def _write_contextual_enrichment_report(root: Path, *, head: str = "abc123") -> Path:
    reports_dir = root / ".kugnusdocs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-04-27-llmwiki-contextual-enrichment-gate.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-27T03:00:00+09:00",
                "git": {"branch": "feat/dev-kugnus", "head": head},
                "status": "ok",
                "ready": True,
                "checks": {
                    "runtime_contextual_prefix_ready": True,
                    "runtime_contextual_heading_path_ready": True,
                    "bm25_runtime_uses_contextual_search_text": True,
                    "contextual_recall_fixture_improves": True,
                },
                "failures": [],
                "coverage": {
                    "total": {
                        "row_count": 87858,
                        "runtime_contextual_count": 87858,
                        "persisted_contextual_count": 0,
                        "contextual_prefix_count": 87858,
                        "contextual_heading_path_count": 87858,
                    }
                },
                "recall_fixture": {"improved": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def _ready_role_rehearsal_status() -> dict[str, object]:
    return {
        "status": "ok",
        "ready": True,
        "pass_count": 4,
        "total": 4,
        "roles": {
            "operator_a": {"pass": 2, "total": 2, "ready": True},
            "learner_b": {"pass": 2, "total": 2, "ready": True},
        },
        "failures": [],
        "selected_report": {"head_matches_current": True, "stale": False},
        "results": [],
    }


def _ready_runtime_dependencies_status() -> dict[str, object]:
    return {
        "status": "ok",
        "ready": True,
        "failures": [],
        "qdrant": {
            "id": "qdrant",
            "ready": True,
            "status": "ok",
            "url": "http://127.0.0.1:6335/collections",
            "collection": "openshift_docs",
        },
    }


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
        self.assertEqual("ok", status["metrics"]["official_ko_localization_status"])
        self.assertEqual(0, status["metrics"]["official_ko_localization_failing_book_count"])
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

    def test_development_control_excludes_ops_console_and_scores_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_report(root, head="abc123")
            _write_loop_report(root, head="abc123")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/dev-kugnus", "head": "abc123", "dirty_tracked_files": False},
            ):
                promotion = _build_llmwiki_promotion_control_status(root)
                validation_loop = _build_llmwiki_validation_loop_control_status(root)

        status = _build_development_control_status(
            llmwiki_promotion=promotion,
            llmwiki_validation_loop=validation_loop,
            official_playbook_count=70,
            customer_playbook_count=10,
            user_corpus_chunk_count=10,
            custom_document_count=10,
            playable_asset_count=90,
            source_of_truth_drift={"status_alignment": {"mismatches": []}},
            product_rehearsal={"exists": True, "status": "ok", "blockers": []},
            role_rehearsal=_ready_role_rehearsal_status(),
            runtime_dependencies=_ready_runtime_dependencies_status(),
        )

        self.assertTrue(status["ready"])
        self.assertEqual("ready", status["status"])
        self.assertEqual(0, status["summary"]["blocked_count"])
        surface_ids = [item["id"] for item in status["surfaces"]]
        self.assertIn("studio_chat", surface_ids)
        self.assertIn("runtime_dependencies", surface_ids)
        self.assertIn("role_rehearsal", surface_ids)
        self.assertIn("automation_harness", surface_ids)
        self.assertIn("surya_optional_boundary", surface_ids)
        self.assertNotIn("ops_console", surface_ids)
        excluded_ids = [item["id"] for item in status["scope"]["excluded"]]
        self.assertEqual(["ops_console"], excluded_ids)

    def test_validation_loop_status_marks_report_stale_on_head_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_loop_report(root, head="old")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/dev-kugnus", "head": "new", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_validation_loop_control_status(root)

        self.assertEqual("stale", status["status"])
        self.assertFalse(status["ready"])
        self.assertTrue(status["selected_report"]["stale"])

    def test_evolution_gate_status_exposes_p0_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_evolution_gate_report(root, head="abc123")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/dev-kugnus", "head": "abc123", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_evolution_gate_control_status(root)

        self.assertEqual("ok", status["status"])
        self.assertTrue(status["ready"])
        self.assertEqual(6, status["metrics"]["backwrite_candidates"])
        self.assertEqual(0, status["metrics"]["quality_blockers"])

    def test_contextual_enrichment_status_exposes_p1_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_contextual_enrichment_report(root, head="abc123")
            with patch(
                "play_book_studio.app.data_control_room._current_git_context",
                return_value={"branch": "feat/dev-kugnus", "head": "abc123", "dirty_tracked_files": False},
            ):
                status = _build_llmwiki_contextual_enrichment_control_status(root)

        self.assertEqual("ok", status["status"])
        self.assertTrue(status["ready"])
        self.assertEqual(87858, status["metrics"]["row_count"])
        self.assertEqual(87858, status["metrics"]["runtime_contextual_count"])
        self.assertTrue(status["metrics"]["recall_fixture_improved"])


if __name__ == "__main__":
    unittest.main()
