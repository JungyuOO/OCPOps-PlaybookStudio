from __future__ import annotations

from dataclasses import dataclass
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ["ARTIFACTS_DIR"] = "artifacts"

from play_book_studio.intake.models import CanonicalBookDraft, CustomerPackDraftRecord, DocSourceRequest
from play_book_studio.intake.normalization import builders
from play_book_studio.intake.planner import CustomerPackPlanner, build_customer_pack_support_matrix


@dataclass
class _FakeBook:
    notes: tuple[str, ...] = ()


def _build_record(source_type: str, *, capture_artifact_path: str | None = None) -> CustomerPackDraftRecord:
    source_uri = f"C:/tmp/sample.{source_type}"
    request = DocSourceRequest(source_type=source_type, uri=source_uri, title="Sample Book")
    plan = CanonicalBookDraft(
        book_slug="sample-book",
        title="Sample Book",
        source_type=source_type,
        source_uri=source_uri,
        source_collection="customer_uploads",
        pack_id="sample-pack",
        pack_label="Sample Pack",
        inferred_product="unknown",
        inferred_version="unknown",
        acquisition_uri=source_uri,
        capture_strategy="test_capture_v1",
        acquisition_step="capture",
        normalization_step="normalize",
        derivation_step="derive",
    )
    return CustomerPackDraftRecord(
        draft_id="draft-1",
        status="captured",
        created_at="2026-04-23T00:00:00Z",
        updated_at="2026-04-23T00:00:00Z",
        request=request,
        plan=plan,
        capture_artifact_path=capture_artifact_path or source_uri,
    )


class CustomerPackIntakeDispatchTests(unittest.TestCase):
    def test_docx_prefers_native_lane_before_markitdown_fallback(self) -> None:
        record = _build_record("docx")
        with (
            patch.object(builders, "_build_docx_canonical_book", return_value=_FakeBook()) as native_builder,
            patch.object(
                builders,
                "_build_markitdown_canonical_book",
                side_effect=AssertionError("MarkItDown fallback should not run on healthy DOCX lane"),
            ),
        ):
            book = builders.build_canonical_book(record)

        native_builder.assert_called_once_with(record)
        self.assertIn("source-first DOCX native structured lane", book.notes[-1])

    def test_docx_uses_markitdown_only_after_native_failure(self) -> None:
        record = _build_record("docx")
        with (
            patch.object(builders, "_build_docx_canonical_book", side_effect=RuntimeError("native unavailable")),
            patch.object(builders, "_build_markitdown_canonical_book", return_value=_FakeBook()) as fallback_builder,
        ):
            book = builders.build_canonical_book(record)

        fallback_builder.assert_called_once_with(record)
        self.assertIn("MarkItDown fallback", book.notes[-1])
        self.assertIn("docx native lane failure", book.notes[-1])

    def test_pdf_prefers_native_triage_before_markitdown_fallback(self) -> None:
        record = _build_record("pdf")
        with (
            patch.object(builders, "_build_pdf_canonical_book", return_value=_FakeBook()) as native_builder,
            patch.object(
                builders,
                "_build_markitdown_canonical_book",
                side_effect=AssertionError("MarkItDown fallback should not run on healthy PDF lane"),
            ),
        ):
            book = builders.build_canonical_book(record)

        native_builder.assert_called_once()
        self.assertIn("source-first PDF native lane", book.notes[-1])

    def test_hwp_prefers_structured_rows_before_markdown_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_path = Path(tmpdir) / "sample.hwp"
            capture_path.write_bytes(b"fake-hwp")
            record = _build_record("hwp", capture_artifact_path=str(capture_path))

            with (
                patch.object(
                    builders,
                    "extract_hwp_rows_with_unhwp",
                    return_value=[{"heading": "1. 개요", "text": "본문"}],
                ) as rows_builder,
                patch.object(
                    builders.CustomerPackPlanner,
                    "build_canonical_book",
                    return_value=_FakeBook(),
                ) as planner_builder,
                patch.object(
                    builders,
                    "extract_hwp_markdown_with_unhwp",
                    side_effect=AssertionError("Markdown bridge should not run on healthy HWP lane"),
                ),
            ):
                book = builders.build_canonical_book(record)

        rows_builder.assert_called_once()
        planner_builder.assert_called_once()
        self.assertIn("unhwp structured rows first", book.notes[-1])

    def test_hwp_uses_markdown_bridge_after_structured_rows_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_path = Path(tmpdir) / "sample.hwpx"
            capture_path.write_bytes(b"fake-hwpx")
            record = _build_record("hwpx", capture_artifact_path=str(capture_path))

            with (
                patch.object(
                    builders,
                    "extract_hwp_rows_with_unhwp",
                    side_effect=RuntimeError("structured unavailable"),
                ),
                patch.object(
                    builders,
                    "extract_hwp_markdown_with_unhwp",
                    return_value="# 1. 개요\n\n본문",
                ) as markdown_bridge,
                patch.object(
                    builders,
                    "_build_rows_canonical_book",
                    return_value=_FakeBook(),
                ) as row_book_builder,
            ):
                book = builders.build_canonical_book(record)

        markdown_bridge.assert_called_once()
        row_book_builder.assert_called_once()
        self.assertIn("markdown bridge", book.notes[-1])
        self.assertIn("Structured rows fallback reason: RuntimeError", book.notes[-1])

    def test_native_ooxml_builders_go_directly_to_typed_rows(self) -> None:
        cases = (
            ("docx", "_build_docx_canonical_book", "_docx_to_rows"),
            ("pptx", "_build_pptx_canonical_book", "_pptx_to_rows"),
            ("xlsx", "_build_xlsx_canonical_book", "_xlsx_to_rows"),
        )
        for source_type, builder_name, row_builder_name in cases:
            with self.subTest(source_type=source_type):
                with tempfile.TemporaryDirectory() as tmpdir:
                    capture_path = Path(tmpdir) / f"sample.{source_type}"
                    capture_path.write_bytes(f"fake-{source_type}".encode("utf-8"))
                    record = _build_record(source_type, capture_artifact_path=str(capture_path))
                    with (
                        patch.object(
                            builders,
                            row_builder_name,
                            return_value=[
                                {
                                    "book_slug": "sample-book",
                                    "book_title": "Sample Book",
                                    "heading": "운영 절차",
                                    "section_level": 1,
                                    "section_path": ["운영 절차"],
                                    "anchor": "operating-guide",
                                    "source_url": record.request.uri,
                                    "viewer_path": f"/playbooks/customer-packs/{record.draft_id}/index.html#operating-guide",
                                    "text": "oc get pods -A\n확인: Pod 상태를 점검한다.",
                                }
                            ],
                        ) as row_builder,
                        patch.object(
                            builders,
                            "_build_structured_text_canonical_book",
                            side_effect=AssertionError("OOXML native lane should not route through markdown-shaped text builder"),
                        ),
                        patch.object(
                            builders.CustomerPackPlanner,
                            "build_canonical_book",
                            return_value=_FakeBook(),
                        ) as planner_builder,
                    ):
                        book = getattr(builders, builder_name)(record)

                row_builder.assert_called_once()
                planner_builder.assert_called_once()
                self.assertEqual((), book.notes)


class CustomerPackPlannerMetadataTests(unittest.TestCase):
    def test_planner_preserves_typed_operational_metadata_in_canonical_sections(self) -> None:
        request = DocSourceRequest(
            source_type="md",
            uri="C:/tmp/sample.md",
            title="운영 절차 샘플",
        )
        book = CustomerPackPlanner().build_canonical_book(
            [
                {
                    "book_slug": "ops-guide",
                    "book_title": "운영 절차 샘플",
                    "heading": "백업 절차",
                    "section_level": 1,
                    "section_path": ["백업 절차"],
                    "anchor": "backup-procedure",
                    "source_url": "C:/tmp/sample.md",
                    "viewer_path": "/playbooks/customer-packs/draft-1/index.html#backup-procedure",
                    "text": "oc get pods -A\nConfigMap 과 Secret 상태를 확인한다.\n확인: Pod 상태를 점검한다.",
                }
            ],
            request=request,
        )

        section = book.to_dict()["sections"][0]
        self.assertEqual("procedure", section["semantic_role"])
        self.assertIn("code", section["block_kinds"])
        self.assertIn("oc get pods -A", section["cli_commands"])
        self.assertIn("ConfigMap", section["k8s_objects"])
        self.assertIn("Secret", section["k8s_objects"])
        self.assertTrue(any("확인:" in item for item in section["verification_hints"]))


class CustomerPackSupportMatrixTests(unittest.TestCase):
    def test_support_matrix_describes_source_first_native_routes(self) -> None:
        matrix = build_customer_pack_support_matrix()
        entries = {entry.format_id: entry for entry in matrix.entries}

        self.assertEqual(entries["pdf_text"].normalization_strategy, "pdf_source_first_rows_to_canonical_sections_v1")
        self.assertEqual(entries["docx"].normalization_strategy, "docx_native_structured_to_canonical_sections_v1")
        self.assertEqual(entries["pptx"].normalization_strategy, "pptx_native_slide_to_canonical_sections_v1")
        self.assertEqual(entries["xlsx"].normalization_strategy, "xlsx_native_sheet_to_canonical_sections_v1")
        self.assertEqual(entries["pdf_text"].lane_kind, "native")
        self.assertEqual(entries["pdf_scan_ocr"].lane_kind, "rescue")
        self.assertEqual(entries["docx"].lane_kind, "native")
        self.assertEqual(entries["pptx"].lane_kind, "native")
        self.assertEqual(entries["xlsx"].lane_kind, "native")
        self.assertEqual(entries["hwp"].lane_kind, "native")
        self.assertEqual(entries["hwpx"].lane_kind, "native")
        self.assertEqual(entries["json"].lane_kind, "blocked")
        self.assertEqual(entries["docx"].fallback_lanes, ("bridge",))
        self.assertEqual(entries["pdf_text"].fallback_lanes, ("rescue", "bridge"))
        self.assertEqual(entries["hwp"].fallback_lanes, ("bridge", "rescue"))
        self.assertEqual(entries["hwpx"].fallback_lanes, ("bridge", "rescue"))
        self.assertIn("fallback", entries["docx"].review_rule.lower())
        self.assertIn("fallback", entries["pptx"].review_rule.lower())
        self.assertIn("fallback", entries["xlsx"].review_rule.lower())
        self.assertIn("unhwp", entries["hwp"].review_rule.lower())
        self.assertIn("unhwp", entries["hwpx"].review_rule.lower())


if __name__ == "__main__":
    unittest.main()
