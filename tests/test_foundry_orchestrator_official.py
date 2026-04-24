from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.foundry_orchestrator import _run_approved_runtime_rebuild


class _FakeLog:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self._payload)


class FoundryOfficialRebuildTests(unittest.TestCase):
    def test_official_rebuild_raises_when_pipeline_has_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)

            with (
                patch(
                    "play_book_studio.ingestion.foundry_orchestrator.apply_all_curated_gold",
                    return_value={"summary": {"requested_count": 0, "promoted_count": 0}, "books": []},
                ),
                patch(
                    "play_book_studio.ingestion.foundry_orchestrator.run_ingestion_pipeline",
                    return_value=_FakeLog(
                        {
                            "status": "ok",
                            "errors": [
                                {
                                    "book_slug": "ai_workloads",
                                    "message": "translation payload missing",
                                }
                            ],
                        }
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "approved runtime rebuild encountered 1 pipeline errors",
                ):
                    _run_approved_runtime_rebuild(settings, root / "reports", "official_runtime_rebuild")


if __name__ == "__main__":
    unittest.main()
