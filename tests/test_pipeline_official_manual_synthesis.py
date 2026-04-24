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
from play_book_studio.ingestion.models import NormalizedSection, SourceManifestEntry
from play_book_studio.ingestion.pipeline import run_ingestion_pipeline


class PipelineOfficialManualSynthesisTests(unittest.TestCase):
    def test_manual_synthesis_entry_skips_collect_and_uses_payload_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            entry = SourceManifestEntry(
                book_slug="hosted_control_planes",
                title="Hosted Control Planes",
                source_url="https://docs.example/hosted_control_planes",
                viewer_path="/docs/ocp/4.20/ko/hosted_control_planes/index.html",
                source_type="manual_synthesis",
                source_kind="source-first",
                source_lane="applied_playbook",
                content_status="approved_ko",
                primary_input_kind="html_single",
            )
            section = NormalizedSection(
                book_slug="hosted_control_planes",
                book_title="Hosted Control Planes",
                heading="Hosted Control Planes overview",
                section_level=2,
                section_path=["Hosted Control Planes overview"],
                anchor="hosted-control-planes-overview",
                source_url=entry.source_url,
                viewer_path=f"{entry.viewer_path}#hosted-control-planes-overview",
                text="Hosted Control Planes overview\n\n운영 설명 본문",
                section_id="hosted_control_planes:hosted-control-planes-overview",
                semantic_role="concept",
                block_kinds=("paragraph",),
                source_language="ko",
                display_language="ko",
                translation_status="approved_ko",
                translation_stage="approved_ko",
                source_id="source:hosted_control_planes",
                source_lane="applied_playbook",
                source_type="manual_synthesis",
                source_collection="core",
                product="openshift",
                version="4.20",
                locale="ko",
                review_status="approved",
                approval_state="approved",
                publication_state="published",
            )

            with (
                patch(
                    "play_book_studio.ingestion.pipeline.load_runtime_manifest_entries",
                    return_value=[entry],
                ),
                patch(
                    "play_book_studio.ingestion.pipeline.load_approved_playbook_payload",
                    return_value={
                        "book_slug": "hosted_control_planes",
                        "title": "Hosted Control Planes",
                        "source_metadata": {"source_type": "manual_synthesis"},
                    },
                ),
                patch(
                    "play_book_studio.ingestion.pipeline.project_playbook_payload_sections",
                    return_value=[section],
                ),
                patch(
                    "play_book_studio.ingestion.pipeline.collect_entry",
                    side_effect=AssertionError("manual_synthesis should not hit collect_entry"),
                ),
                patch(
                    "play_book_studio.ingestion.pipeline.chunk_sections",
                    return_value=[],
                ),
                patch(
                    "play_book_studio.ingestion.pipeline.refresh_active_runtime_graph_artifacts",
                    return_value={
                        "full_sidecar": {"book_count": 1, "relation_count": 0},
                        "compact_sidecar": {"book_count": 1, "relation_count": 0},
                    },
                ),
            ):
                log = run_ingestion_pipeline(
                    settings,
                    refresh_manifest=False,
                    collect_subset="all",
                    process_subset="all",
                    skip_embeddings=True,
                    skip_qdrant=True,
                )

            payload = log.to_dict()
            self.assertEqual([], payload["errors"])
            self.assertEqual(0, payload["collected_count"])
            self.assertEqual(["hosted_control_planes"], payload["processed_sources"])
            self.assertEqual(1, payload["normalized_count"])


if __name__ == "__main__":
    unittest.main()
