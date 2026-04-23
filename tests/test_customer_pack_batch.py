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

from play_book_studio.app.customer_pack_batch import (
    discover_customer_pack_batch_sources,
    find_existing_customer_pack_draft,
    run_customer_pack_material_batch,
)
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.models import CanonicalBookDraft, CustomerPackDraftRecord, DocSourceRequest


def _record_for_source(
    source_path: Path,
    *,
    draft_id: str,
    source_fingerprint: str,
    uploaded_file_name: str = "",
) -> CustomerPackDraftRecord:
    source_uri = str(source_path)
    request = DocSourceRequest(source_type="pptx", uri=source_uri, title=source_path.stem)
    plan = CanonicalBookDraft(
        book_slug=source_path.stem.lower(),
        title=source_path.stem,
        source_type="pptx",
        source_uri=source_uri,
        source_collection="uploaded",
        pack_id="custom-uploaded-custom",
        pack_label="User Custom Pack",
        inferred_product="unknown",
        inferred_version="unknown",
        acquisition_uri=source_uri,
        capture_strategy="pptx_slide_capture_v1",
        acquisition_step="capture",
        normalization_step="normalize",
        derivation_step="derive",
    )
    return CustomerPackDraftRecord(
        draft_id=draft_id,
        status="normalized",
        created_at="2026-04-23T00:00:00Z",
        updated_at="2026-04-23T00:00:00Z",
        request=request,
        plan=plan,
        uploaded_file_name=uploaded_file_name,
        capture_artifact_path=source_uri,
        source_fingerprint=source_fingerprint,
        approval_state="approved",
        publication_state="active",
        canonical_book_path=str(source_path.with_suffix(".json")),
        private_corpus_manifest_path=str(source_path.with_suffix(".manifest.json")),
    )


class CustomerPackBatchTests(unittest.TestCase):
    def test_discover_customer_pack_batch_sources_filters_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            materials = root / ".P_docs" / "01_검토대기_플레이북재료"
            alias_a = materials / "PD-IT" / "A.pptx"
            alias_b = materials / "PD-PERF" / "B.pptx"
            alias_a.parent.mkdir(parents=True, exist_ok=True)
            alias_b.parent.mkdir(parents=True, exist_ok=True)
            alias_a.write_bytes(b"same-content")
            alias_b.write_bytes(b"same-content")
            (materials / "PD-IT" / "~$lock.pptx").write_bytes(b"skip-me")
            excluded = root / ".P_docs" / "99_검토대기_비재료" / "X.pptx"
            excluded.parent.mkdir(parents=True, exist_ok=True)
            excluded.write_bytes(b"skip-excluded")

            sources = discover_customer_pack_batch_sources(root / ".P_docs")

            self.assertEqual(1, len(sources))
            self.assertEqual("A.pptx", sources[0].source_name)
            self.assertEqual(1, len(sources[0].aliases))
            self.assertTrue(str(alias_b) in sources[0].aliases[0])

    def test_find_existing_customer_pack_draft_matches_by_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "sample.pptx"
            source_path.write_bytes(b"ppt-binary")
            fingerprint = "abc123"
            CustomerPackDraftStore(root).save(
                _record_for_source(
                    source_path,
                    draft_id="dtb-existing",
                    source_fingerprint=fingerprint,
                    uploaded_file_name=source_path.name,
                )
            )

            match = find_existing_customer_pack_draft(
                root,
                source_path=source_path,
                fingerprint=fingerprint,
            )

            self.assertIsNotNone(match)
            self.assertEqual("source_fingerprint", match["match_reason"])
            self.assertEqual("dtb-existing", match["record"].draft_id)

    def test_run_customer_pack_material_batch_reuses_existing_and_ingests_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            materials = root / ".P_docs" / "01_검토대기_플레이북재료"
            existing_path = materials / "PD-ARCH" / "existing.pptx"
            new_path = materials / "PD-ARCH" / "new.pptx"
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_bytes(b"existing-doc")
            new_path.write_bytes(b"new-doc")

            existing_source = discover_customer_pack_batch_sources(materials)[0]
            CustomerPackDraftStore(root).save(
                _record_for_source(
                    existing_path,
                    draft_id="dtb-existing",
                    source_fingerprint=existing_source.fingerprint,
                    uploaded_file_name=existing_path.name,
                )
            )

            def _fake_normalize(_root, payload):
                return {
                    "draft_id": payload["draft_id"],
                    "status": "normalized",
                    "publication_state": "active",
                    "surface_kind": "slide_deck",
                    "source_unit_count": 5,
                    "slide_packet_count": 5,
                    "private_corpus_status": "ready",
                    "private_corpus": {
                        "publication_state": "active",
                        "quality_status": "ready",
                        "shared_grade": "gold",
                        "read_ready": True,
                        "publish_ready": True,
                        "retrieval_ready": True,
                    },
                }

            def _fake_ingest(_root, payload):
                return {
                    "draft_id": "dtb-new",
                    "status": "normalized",
                    "publication_state": payload["publication_state"],
                    "surface_kind": "slide_deck",
                    "source_unit_count": 4,
                    "slide_packet_count": 4,
                    "private_corpus_status": "ready",
                    "private_corpus": {
                        "publication_state": payload["publication_state"],
                        "quality_status": "ready",
                        "shared_grade": "gold",
                        "read_ready": True,
                        "publish_ready": True,
                        "retrieval_ready": True,
                    },
                }

            with (
                patch("play_book_studio.app.customer_pack_batch.normalize_customer_pack_draft", side_effect=_fake_normalize),
                patch("play_book_studio.app.customer_pack_batch.ingest_customer_pack", side_effect=_fake_ingest),
            ):
                report = run_customer_pack_material_batch(root, materials_root=materials)

            self.assertEqual(2, report["summary"]["processed_count"])
            self.assertEqual(0, report["summary"]["failed_count"])
            self.assertTrue(report["summary"]["customer_llmwiki_ready"])
            self.assertEqual(2, report["summary"]["wikibook_ready_count"])
            self.assertEqual(2, report["summary"]["llmwiki_ready_count"])
            self.assertEqual(2, report["summary"]["chat_ready_count"])
            self.assertTrue(report["scope"]["material_only"])
            self.assertEqual(2, report["scope"]["material_file_count"])
            self.assertEqual(0, report["scope"]["alias_file_count"])
            reasons = {item["source_name"]: item["match_reason"] for item in report["processed"]}
            self.assertEqual("source_fingerprint", reasons["existing.pptx"])
            self.assertEqual("new_ingest", reasons["new.pptx"])
            for item in report["processed"]:
                self.assertTrue(item["wikibook_ready"])
                self.assertEqual("ready", item["wikibook_status"])
                self.assertTrue(item["llmwiki_ready"])
                self.assertEqual("ready", item["llmwiki_status"])
                self.assertTrue(item["chat_ready"])
                self.assertEqual("ready", item["chat_status"])

    def test_run_customer_pack_material_batch_reports_material_scope_and_surface_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            materials = root / ".P_docs" / "01_검토대기_플레이북재료"
            primary = materials / "PD-IT" / "A.pptx"
            alias = materials / "PD-PERF" / "B.pptx"
            primary.parent.mkdir(parents=True, exist_ok=True)
            alias.parent.mkdir(parents=True, exist_ok=True)
            primary.write_bytes(b"same-content")
            alias.write_bytes(b"same-content")

            def _fake_ingest(_root, payload):
                return {
                    "draft_id": "dtb-scope",
                    "status": "normalized",
                    "publication_state": payload["publication_state"],
                    "surface_kind": "slide_deck",
                    "source_unit_count": 4,
                    "slide_packet_count": 4,
                    "private_corpus_status": "ready",
                    "private_corpus": {
                        "publication_state": payload["publication_state"],
                        "quality_status": "ready",
                        "shared_grade": "gold",
                        "read_ready": True,
                        "publish_ready": True,
                        "retrieval_ready": True,
                        "grade_gate": {
                            "surface_gates": {
                                "wikibook_ready": True,
                                "wikibook_status": "ready",
                                "llmwiki_ready": True,
                                "llmwiki_status": "ready",
                            }
                        },
                    },
                }

            with patch("play_book_studio.app.customer_pack_batch.ingest_customer_pack", side_effect=_fake_ingest):
                report = run_customer_pack_material_batch(root, materials_root=materials)

            self.assertEqual(
                {
                    "scope_kind": "customer_pack_material_only_batch",
                    "materials_root": str(materials),
                    "material_only": True,
                    "material_folder_marker": "01_검토대기_플레이북재료",
                    "excluded_folder_markers": ["99_검토대기_비재료"],
                    "supported_extensions": [".ppt", ".pptx"],
                    "deduplicated_source_count": 1,
                    "material_file_count": 2,
                    "alias_file_count": 1,
                },
                report["scope"],
            )
            self.assertEqual(1, report["summary"]["source_count"])
            self.assertEqual(2, report["summary"]["material_file_count"])
            self.assertEqual(1, report["summary"]["alias_file_count"])
            self.assertEqual(1, report["summary"]["wikibook_ready_count"])
            self.assertEqual(1, report["summary"]["llmwiki_ready_count"])
            self.assertEqual(1, report["summary"]["chat_ready_count"])
            self.assertTrue(report["summary"]["customer_llmwiki_ready"])
            self.assertEqual(1, len(report["processed"]))
            self.assertEqual([str(alias)], report["processed"][0]["aliases"])
            self.assertTrue(report["processed"][0]["wikibook_ready"])
            self.assertEqual("ready", report["processed"][0]["wikibook_status"])
            self.assertTrue(report["processed"][0]["llmwiki_ready"])
            self.assertEqual("ready", report["processed"][0]["llmwiki_status"])
            self.assertTrue(report["processed"][0]["chat_ready"])
            self.assertEqual("ready", report["processed"][0]["chat_status"])


if __name__ == "__main__":
    unittest.main()
