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

from play_book_studio.answering.models import Citation
from play_book_studio.app.data_control_room import build_data_control_room_payload
from play_book_studio.app.presenters import _customer_pack_meta_for_viewer_path, _serialize_citation
from play_book_studio.app.source_books_customer_pack import load_customer_pack_book
from play_book_studio.config.settings import load_settings
from play_book_studio.intake.private_corpus import customer_pack_private_manifest_path
from tests.test_customer_pack_read_boundary import _ingest_pack


class CustomerPackSurfacePacketTests(unittest.TestCase):
    def test_data_control_room_reloads_authoritative_manifest_truth_after_in_place_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="manifest-rewrite",
                tenant_id="tenant-cache",
                workspace_id="workspace-cache",
                approval_state="approved",
            )
            draft_id = str(approved["draft_id"])

            first_payload = build_data_control_room_payload(root)
            first_runtime_book = next(
                item
                for item in first_payload["customer_pack_runtime_books"]["books"]
                if item.get("draft_id") == draft_id
            )
            self.assertIn(first_runtime_book["shared_grade"], {"gold", "silver"})

            manifest_path = customer_pack_private_manifest_path(load_settings(root), draft_id)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["quality_status"] = "review"
            manifest["quality_summary"] = "control room should reload this"
            manifest["shared_grade"] = "silver"
            manifest["grade_gate"] = {
                "shared_grade": "silver",
                "citation_gate": {"status": "exact"},
                "retrieval_gate": {"ready": True},
                "promotion_gate": {"read_ready": True, "publish_ready": False},
            }
            manifest["citation_landing_status"] = "exact"
            manifest["retrieval_ready"] = True
            manifest["read_ready"] = True
            manifest["publish_ready"] = False
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            second_payload = build_data_control_room_payload(root)
            second_runtime_book = next(
                item
                for item in second_payload["customer_pack_runtime_books"]["books"]
                if item.get("draft_id") == draft_id
            )
            self.assertEqual("silver", second_runtime_book["shared_grade"])
            self.assertEqual("review", second_runtime_book["quality_status"])
            self.assertEqual("control room should reload this", second_runtime_book["quality_summary"])
            self.assertEqual("Silver", second_runtime_book["grade"])

    def test_data_control_room_customer_pack_surface_uses_shared_grade_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="surface-approved",
                tenant_id="tenant-surface",
                workspace_id="workspace-surface",
                approval_state="approved",
            )
            draft_id = str(approved["draft_id"])

            payload = build_data_control_room_payload(root)

            runtime_books = payload["customer_pack_runtime_books"]["books"]
            runtime_book = next(
                item
                for item in runtime_books
                if item.get("draft_id") == draft_id
                and item.get("viewer_path") == f"/playbooks/customer-packs/{draft_id}/index.html"
            )
            self.assertEqual(draft_id, runtime_book["draft_id"])
            self.assertIn(runtime_book["shared_grade"], {"gold", "silver"})
            self.assertEqual(runtime_book["shared_grade"].capitalize(), runtime_book["grade"])
            self.assertEqual("exact", runtime_book["citation_landing_status"])
            self.assertTrue(runtime_book["retrieval_ready"])
            self.assertTrue(runtime_book["read_ready"])
            self.assertFalse(runtime_book["publish_ready"])

            user_library_books = payload["user_library_books"]["books"]
            user_library_book = next(item for item in user_library_books if item.get("draft_id") == draft_id)
            self.assertEqual(draft_id, user_library_book["draft_id"])
            self.assertEqual(runtime_book["shared_grade"], user_library_book["shared_grade"])
            self.assertTrue(user_library_book["read_ready"])

            user_library_corpus = payload["user_library_corpus"]["books"]
            user_library_corpus_book = next(item for item in user_library_corpus if item.get("draft_id") == draft_id)
            self.assertEqual(draft_id, user_library_corpus_book["draft_id"])
            self.assertEqual("exact", user_library_corpus_book["citation_landing_status"])
            self.assertTrue(user_library_corpus_book["retrieval_ready"])

    def test_customer_pack_citation_surface_inherits_shared_grade_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="citation-approved",
                tenant_id="tenant-citation",
                workspace_id="workspace-citation",
                approval_state="approved",
            )
            draft_id = str(approved["draft_id"])
            book = load_customer_pack_book(root, draft_id)
            assert book is not None
            sections = [dict(section) for section in (book.get("sections") or []) if isinstance(section, dict)]
            target = next(
                (section for section in sections if str(section.get("anchor") or "").strip()),
                sections[0],
            )
            anchor = str(target.get("anchor") or "").strip()
            section = str(target.get("heading") or "").strip() or str(book.get("title") or draft_id)

            citation = Citation(
                index=1,
                chunk_id=f"{draft_id}:{anchor or 'section'}",
                book_slug=str(book.get("book_slug") or draft_id),
                section=section,
                anchor=anchor,
                source_url=f"/api/customer-packs/captured?draft_id={draft_id}",
                viewer_path=f"/playbooks/customer-packs/{draft_id}/index.html#{anchor}" if anchor else f"/playbooks/customer-packs/{draft_id}/index.html",
                excerpt="Customer pack citation surface packet.",
                source_collection="uploaded",
            )

            payload = _serialize_citation(root, citation)

            self.assertIn(payload["shared_grade"], {"gold", "silver"})
            self.assertIn("grade_gate", payload)
            self.assertEqual("exact", payload["citation_landing_status"])
            self.assertTrue(payload["retrieval_ready"])
            self.assertTrue(payload["read_ready"])
            self.assertFalse(payload["publish_ready"])
            self.assertEqual("private_customer_pack_runtime", payload["boundary_truth"])

    def test_customer_pack_surface_uses_stored_manifest_truth_without_recalculation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="manifest-truth",
                tenant_id="tenant-manifest",
                workspace_id="workspace-manifest",
                approval_state="approved",
            )
            draft_id = str(approved["draft_id"])
            manifest_path = customer_pack_private_manifest_path(load_settings(root), draft_id)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["quality_status"] = "review"
            manifest["quality_summary"] = "stored manifest truth"
            manifest["shared_grade"] = "silver"
            manifest["grade_gate"] = {
                "shared_grade": "silver",
                "citation_gate": {"status": "exact"},
                "retrieval_gate": {"ready": True},
                "promotion_gate": {"read_ready": True, "publish_ready": False},
            }
            manifest["citation_landing_status"] = "exact"
            manifest["retrieval_ready"] = True
            manifest["read_ready"] = True
            manifest["publish_ready"] = False
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            book = load_customer_pack_book(root, draft_id)
            self.assertIsNotNone(book)
            assert book is not None
            self.assertEqual("silver", book["shared_grade"])
            self.assertEqual("exact", book["citation_landing_status"])
            self.assertTrue(book["retrieval_ready"])
            self.assertTrue(book["read_ready"])
            self.assertFalse(book["publish_ready"])

            meta = _customer_pack_meta_for_viewer_path(root, f"/playbooks/customer-packs/{draft_id}/index.html")
            self.assertIsNotNone(meta)
            assert meta is not None
            self.assertEqual("silver", meta["shared_grade"])
            self.assertEqual("silver", meta["grade_gate"]["shared_grade"])
            self.assertEqual("exact", meta["citation_landing_status"])
            self.assertTrue(meta["retrieval_ready"])
            self.assertTrue(meta["read_ready"])
            self.assertFalse(meta["publish_ready"])


if __name__ == "__main__":
    unittest.main()
