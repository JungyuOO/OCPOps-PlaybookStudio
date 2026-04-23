from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.data_control_room import build_data_control_room_payload


class CustomerCustomDocumentsBucketTests(unittest.TestCase):
    def test_data_control_room_lists_only_material_custom_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            material_dir = root / ".P_docs" / "01_검토대기_플레이북재료" / "PD-ARCH" / "docs"
            non_material_dir = root / ".P_docs" / "99_검토대기_비재료" / "PD-REPORT" / "docs"
            material_dir.mkdir(parents=True, exist_ok=True)
            non_material_dir.mkdir(parents=True, exist_ok=True)

            material_path = material_dir / "architecture-source.pptx"
            non_material_path = non_material_dir / "report-only.pptx"
            material_path.write_bytes(b"material")
            non_material_path.write_bytes(b"non-material")

            manifest_path = root / ".P_docs" / "_review_bucket_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "bucket": "material",
                                "family": "01.아키텍처정의서",
                                "relative_path": "01_검토대기_플레이북재료/PD-ARCH/docs/architecture-source.pptx",
                                "name": "architecture-source.pptx",
                                "size_bytes": 8,
                            },
                            {
                                "bucket": "non_material",
                                "family": "05.완료보고서",
                                "relative_path": "99_검토대기_비재료/PD-REPORT/docs/report-only.pptx",
                                "name": "report-only.pptx",
                                "size_bytes": 12,
                            },
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_data_control_room_payload(root)
            bucket = payload["custom_documents"]

            self.assertEqual(1, bucket["source_count"])
            self.assertEqual(1, bucket["slot_count"])
            self.assertEqual("customer_custom_document_slot", bucket["source_kind"])
            self.assertEqual("커스텀 슬롯", bucket["source_kind_label"])
            self.assertEqual("material_catalog", bucket["promotion_stage"])
            self.assertEqual("북팩토리 재료", bucket["promotion_stage_label"])
            self.assertEqual("custom_playbook_pipeline", bucket["pipeline_target"])
            self.assertEqual(1, len(bucket["books"]))
            book = bucket["books"][0]
            self.assertEqual("customer_custom_materials_only", book["source_lane"])
            self.assertEqual("custom_documents", book["source_collection"])
            self.assertEqual("커스텀 문서", book["source_collection_label"])
            self.assertEqual("customer_custom_document_slot", book["source_kind"])
            self.assertEqual("커스텀 슬롯", book["source_kind_label"])
            self.assertEqual("material_catalog", book["promotion_stage"])
            self.assertEqual("북팩토리 재료", book["promotion_stage_label"])
            self.assertEqual("custom_playbook_pipeline", book["pipeline_target"])
            self.assertEqual("아키텍처 설계", book["title"])
            self.assertEqual("architecture", book["custom_document_kind"])
            self.assertEqual("아키텍처 설계", book["custom_document_kind_label"])
            self.assertEqual("01.아키텍처정의서", book["custom_document_family"])
            self.assertEqual("ui_ready_source_hidden", book["custom_document_status"])
            self.assertEqual(1, book["custom_document_source_count"])
            self.assertEqual({"pptx": 1}, book["custom_document_ext_breakdown"])
            self.assertEqual(1, payload["summary"]["custom_document_count"])
            self.assertEqual(1, payload["summary"]["custom_document_slot_count"])
            serialized_bucket = json.dumps(bucket, ensure_ascii=False)
            self.assertNotIn("architecture-source.pptx", serialized_bucket)
            self.assertNotIn("report-only.pptx", serialized_bucket)
            self.assertNotIn(".P_docs", serialized_bucket)
            self.assertNotIn("99_검토대기_비재료", serialized_bucket)

        # non-material documents never enter the custom_documents bucket

    def test_data_control_room_keeps_duplicate_material_documents_when_bucket_has_two_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_dir = root / ".P_docs" / "01_검토대기_플레이북재료" / "PD-IT" / "case-a"
            second_dir = root / ".P_docs" / "01_검토대기_플레이북재료" / "PD-PERF" / "case-b"
            first_dir.mkdir(parents=True, exist_ok=True)
            second_dir.mkdir(parents=True, exist_ok=True)

            first_path = first_dir / "shared-result.pptx"
            second_path = second_dir / "shared-result.pptx"
            first_path.write_bytes(b"it")
            second_path.write_bytes(b"perf")

            payload = build_data_control_room_payload(root)
            books = payload["custom_documents"]["books"]
            self.assertEqual(2, payload["custom_documents"]["source_count"])
            self.assertEqual(2, payload["custom_documents"]["slot_count"])
            self.assertEqual(2, len(books))
            self.assertEqual(
                {"integration_test", "performance_test"},
                {str(book["custom_document_kind"]) for book in books},
            )
            self.assertEqual(
                {"통합 테스트", "성능 테스트"},
                {str(book["title"]) for book in books},
            )
            self.assertEqual(
                {1},
                {int(book["custom_document_source_count"]) for book in books},
            )
            self.assertEqual(2, payload["summary"]["custom_document_count"])
            self.assertEqual(2, payload["summary"]["custom_document_slot_count"])
            serialized_bucket = json.dumps(payload["custom_documents"], ensure_ascii=False)
            self.assertNotIn("shared-result.pptx", serialized_bucket)


if __name__ == "__main__":
    unittest.main()
