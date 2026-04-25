from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.cli import (
    _chat_matrix_smoke_ok,
    _official_gold_rebuild_should_retry,
    _official_gold_rebuild_uses_embeddings,
    _official_gold_rebuild_uses_qdrant,
    _official_gold_runtime_profile_enabled,
)


class OfficialGoldRebuildCliTests(unittest.TestCase):
    def test_localization_gate_failure_triggers_automatic_repair_pass(self) -> None:
        should_retry, reason = _official_gold_rebuild_should_retry(
            payload={"failures": ["ko_runtime_has_no_unlocalized_english_prose"]},
            log_errors=[],
            full_official_catalog=True,
        )

        self.assertTrue(should_retry)
        self.assertEqual("ko_localization_gate_failed", reason)

    def test_transient_translation_transport_error_triggers_retry(self) -> None:
        should_retry, reason = _official_gold_rebuild_should_retry(
            payload={"failures": []},
            log_errors=[
                {
                    "stage": "normalize",
                    "source": "installing_on_vmware_vsphere",
                    "message": "Connection aborted: connection reset by peer",
                }
            ],
            full_official_catalog=True,
        )

        self.assertTrue(should_retry)
        self.assertEqual("transient_pipeline_error", reason)

    def test_non_full_catalog_rebuild_does_not_auto_retry(self) -> None:
        should_retry, reason = _official_gold_rebuild_should_retry(
            payload={"failures": ["ko_runtime_has_no_unlocalized_english_prose"]},
            log_errors=[{"message": "Connection aborted"}],
            full_official_catalog=False,
        )

        self.assertFalse(should_retry)
        self.assertEqual("", reason)

    def test_gold_runtime_profile_forces_embeddings_and_qdrant(self) -> None:
        args = SimpleNamespace(
            gold_runtime_profile=True,
            with_embeddings=False,
            with_qdrant=False,
        )

        self.assertTrue(_official_gold_runtime_profile_enabled(args))
        self.assertTrue(_official_gold_rebuild_uses_embeddings(args))
        self.assertTrue(_official_gold_rebuild_uses_qdrant(args))

    def test_qdrant_option_implies_embeddings_without_gold_runtime_profile(self) -> None:
        args = SimpleNamespace(
            gold_runtime_profile=False,
            with_embeddings=False,
            with_qdrant=True,
        )

        self.assertTrue(_official_gold_rebuild_uses_embeddings(args))
        self.assertTrue(_official_gold_rebuild_uses_qdrant(args))

    def test_local_rebuild_without_runtime_options_skips_external_artifacts(self) -> None:
        args = SimpleNamespace(
            gold_runtime_profile=False,
            with_embeddings=False,
            with_qdrant=False,
        )

        self.assertFalse(_official_gold_rebuild_uses_embeddings(args))
        self.assertFalse(_official_gold_rebuild_uses_qdrant(args))

    def test_chat_matrix_gold_profile_requires_live_llm_and_vector_cases(self) -> None:
        self.assertFalse(
            _chat_matrix_smoke_ok(
                {
                    "status": "ok",
                    "runtime_requirements": {
                        "llm_live_pass_count": 0,
                        "llm_live_total": 0,
                        "vector_live_pass_count": 0,
                        "vector_live_total": 0,
                    },
                }
            )
        )
        self.assertTrue(
            _chat_matrix_smoke_ok(
                {
                    "status": "ok",
                    "runtime_requirements": {
                        "llm_live_pass_count": 2,
                        "llm_live_total": 2,
                        "vector_live_pass_count": 2,
                        "vector_live_total": 2,
                    },
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
