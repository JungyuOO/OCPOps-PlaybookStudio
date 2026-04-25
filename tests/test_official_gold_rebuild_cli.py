from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.cli import _official_gold_rebuild_should_retry


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


if __name__ == "__main__":
    unittest.main()
