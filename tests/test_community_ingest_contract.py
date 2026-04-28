from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.intake_api import (  # noqa: E402
    create_customer_pack_draft,
    customer_pack_request_from_payload,
)
from play_book_studio.app.presenters import _merge_customer_pack_surface_truth  # noqa: E402
from play_book_studio.app.customer_pack_read_boundary import (  # noqa: E402
    load_customer_pack_read_boundary,
    sanitize_customer_pack_source_meta_payload,
)
from play_book_studio.app.source_books_customer_pack import _customer_pack_boundary_payload  # noqa: E402
from play_book_studio.config.settings import load_settings  # noqa: E402
from play_book_studio.intake import CustomerPackDraftStore  # noqa: E402
from play_book_studio.intake.private_corpus import _bm25_row, customer_pack_private_manifest_path  # noqa: E402
from play_book_studio.retrieval.intake_overlay import _runtime_eligible_selected_draft_ids  # noqa: E402
from play_book_studio.retrieval.models import SessionContext  # noqa: E402


class CommunityIngestContractTests(unittest.TestCase):
    def test_source_url_alias_is_accepted_for_repository_repair(self) -> None:
        request = customer_pack_request_from_payload(
            {
                "title": "Community Route TLS note",
                "source_type": "md",
                "source_url": "https://gist.githubusercontent.com/example/raw/route.md",
            }
        )

        self.assertEqual("https://gist.githubusercontent.com/example/raw/route.md", request.uri)

    def test_community_lane_metadata_is_persisted_on_draft_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "title": "Community Route TLS note",
                "source_type": "md",
                "source_url": "https://gist.githubusercontent.com/example/raw/route.md",
                "source_lane": "community_source_pack",
                "classification": "community",
                "provider_egress_policy": "public_web",
                "approval_state": "review_required",
                "publication_state": "draft",
            }

            created = create_customer_pack_draft(Path(tmp), payload)
            record = CustomerPackDraftStore(Path(tmp)).get(str(created["draft_id"]))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("community_source_pack", record.source_lane)
        self.assertEqual("community", record.classification)
        self.assertEqual("public_web", record.provider_egress_policy)
        self.assertEqual("review_required", record.approval_state)
        surface_payload = _customer_pack_boundary_payload(record)
        self.assertEqual("community", surface_payload["source_authority"])
        self.assertEqual("Community Source", surface_payload["boundary_badge"])

    def test_community_bm25_row_carries_review_required_authority(self) -> None:
        row = _bm25_row(
            {
                "chunk_id": "community-route-1",
                "book_slug": "community-route-tls",
                "chapter": "Community Route TLS note",
                "section": "Wildcard routes",
                "anchor": "wildcard-routes",
                "source_url": "https://gist.githubusercontent.com/example/raw/route.md",
                "viewer_path": "/playbooks/customer-packs/draft-1/index.html#wildcard-routes",
                "text": "If wildcard routes are rejected, check routeAdmission wildcardPolicy.",
                "section_path": ["Community Route TLS note", "Wildcard routes"],
                "chunk_type": "troubleshooting",
                "source_id": "customer_pack:draft-1",
                "source_lane": "community_source_pack",
                "source_type": "md",
                "source_collection": "uploaded",
                "product": "openshift",
                "version": "4.20",
                "locale": "ko",
                "translation_status": "approved_ko",
                "review_status": "unreviewed",
                "trust_score": 1.0,
                "classification": "community",
                "approval_state": "review_required",
                "publication_state": "draft",
                "provider_egress_policy": "public_web",
                "redaction_state": "raw",
            }
        )

        self.assertEqual("community", row["source_authority"])
        self.assertTrue(row["source_requires_review"])
        self.assertEqual("review_required", row["approval_state"])

    def test_source_meta_payload_keeps_community_authority_badge(self) -> None:
        sanitized = sanitize_customer_pack_source_meta_payload(
            {
                "book_slug": "community-route-tls",
                "source_lane": "community_source_pack",
                "boundary_truth": "community_source_pack_runtime",
                "runtime_truth_label": "Community Source Pack",
                "boundary_badge": "Community Source",
                "source_authority": "community",
                "source_authority_label": "Community Source",
                "source_authority_badge": "Community",
                "source_authority_warning": "Not an official vendor source; verify before operational use.",
                "source_requires_review": True,
                "source_fingerprint": "should-not-leak",
            }
        )

        self.assertEqual("community", sanitized["source_authority"])
        self.assertEqual("Community Source", sanitized["boundary_badge"])
        self.assertTrue(sanitized["source_requires_review"])
        self.assertNotIn("source_fingerprint", sanitized)

    def test_presenter_surface_truth_promotes_community_manifest(self) -> None:
        payload = {
            "source_collection": "uploaded",
            "source_lane": "community_source_pack",
            "boundary_truth": "private_customer_pack_runtime",
            "runtime_truth_label": "Customer Source-First Pack",
            "boundary_badge": "Private Pack Runtime",
        }
        manifest = {
            "classification": "community",
            "source_authority": "community",
            "source_requires_review": True,
        }

        merged = _merge_customer_pack_surface_truth(payload, manifest)

        self.assertEqual("community", merged["source_authority"])
        self.assertEqual("community_source_pack_runtime", merged["boundary_truth"])
        self.assertEqual("Community Source", merged["boundary_badge"])

    def test_review_required_community_pack_is_readable_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = create_customer_pack_draft(
                root,
                {
                    "title": "Community Route TLS note",
                    "source_type": "md",
                    "source_url": "https://gist.githubusercontent.com/example/raw/route.md",
                    "source_lane": "community_source_pack",
                    "classification": "community",
                    "provider_egress_policy": "public_web",
                    "approval_state": "review_required",
                    "publication_state": "draft",
                },
            )
            store = CustomerPackDraftStore(root)
            record = store.get(str(created["draft_id"]))
            self.assertIsNotNone(record)
            assert record is not None
            manifest_path = root / "community-manifest.json"
            manifest_path.write_text(
                """
{
  "draft_id": "dtb-community",
  "source_lane": "community_source_pack",
  "source_collection": "uploaded",
  "classification": "community",
  "provider_egress_policy": "public_web",
  "approval_state": "review_required",
  "publication_state": "draft",
  "redaction_state": "raw",
  "retrieval_ready": true,
  "read_ready": false,
  "publish_ready": false,
  "citation_landing_status": "exact",
  "grade_gate": {
    "promotion_gate": {"read_ready": false, "publish_ready": false},
    "retrieval_gate": {"ready": true},
    "citation_gate": {"status": "exact"}
  },
  "boundary_truth": "private_customer_pack_runtime",
  "runtime_truth_label": "Customer Source-First Pack",
  "boundary_badge": "Private Pack Runtime"
}
""".strip()
                + "\n",
                encoding="utf-8",
            )
            record.private_corpus_manifest_path = str(manifest_path)
            store.save(record)

            boundary = load_customer_pack_read_boundary(root, record.draft_id)

        self.assertTrue(boundary["read_allowed"], boundary["fail_reasons"])
        self.assertEqual("community", boundary["source_authority"])
        self.assertTrue(boundary["source_requires_review"])

    def test_review_required_community_pack_is_retrieval_eligible_when_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = load_settings(root)
            draft_id = "dtb-community"
            manifest_path = customer_pack_private_manifest_path(settings, draft_id)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                """
{
  "draft_id": "dtb-community",
  "source_lane": "community_source_pack",
  "source_collection": "uploaded",
  "classification": "community",
  "approval_state": "review_required",
  "publication_state": "draft",
  "retrieval_ready": true,
  "citation_landing_status": "exact"
}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            selected = _runtime_eligible_selected_draft_ids(
                settings,
                SessionContext(selected_draft_ids=[draft_id]),
            )

        self.assertEqual((draft_id,), selected)


if __name__ == "__main__":
    unittest.main()
