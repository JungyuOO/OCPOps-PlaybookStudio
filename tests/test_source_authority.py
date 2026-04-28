from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.source_authority import (
    COMMUNITY_AUTHORITY,
    CUSTOMER_PRIVATE_AUTHORITY,
    OFFICIAL_AUTHORITY,
    UNVERIFIED_AUTHORITY,
    canonical_source_authority,
    source_authority_payload,
)
from play_book_studio.source_provenance import source_provenance_payload


class SourceAuthorityTests(unittest.TestCase):
    def test_redhat_docs_url_is_official(self) -> None:
        payload = source_authority_payload(
            {
                "source_url": "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20",
                "source_lane": "official_ko",
            }
        )

        self.assertEqual(OFFICIAL_AUTHORITY, payload["source_authority"])
        self.assertFalse(payload["source_requires_review"])

    def test_openshift_docs_repo_is_official(self) -> None:
        self.assertEqual(
            OFFICIAL_AUTHORITY,
            canonical_source_authority(
                {
                    "source_repo": "https://github.com/openshift/openshift-docs",
                    "source_relative_path": "modules/foo.adoc",
                }
            ),
        )

    def test_random_github_asciidoc_is_community_review_required(self) -> None:
        payload = source_authority_payload(
            {
                "source_repo": "https://github.com/example/ocp-troubleshooting-notes",
                "source_type": "asciidoc",
                "source_relative_path": "troubleshooting/routes.adoc",
            }
        )

        self.assertEqual(COMMUNITY_AUTHORITY, payload["source_authority"])
        self.assertTrue(payload["source_requires_review"])
        self.assertIn("Not an official", payload["source_authority_warning"])

    def test_public_uri_alias_is_classified_as_community(self) -> None:
        payload = source_authority_payload(
            {
                "uri": "https://github.com/example/openshift-route-debug/blob/main/notes.adoc",
                "source_type": "asciidoc",
            }
        )

        self.assertEqual(COMMUNITY_AUTHORITY, payload["source_authority"])
        self.assertTrue(payload["source_requires_review"])

    def test_customer_pack_boundary_is_private(self) -> None:
        payload = source_authority_payload(
            {
                "source_collection": "uploaded",
                "source_lane": "customer_source_first_pack",
                "boundary_truth": "private_customer_pack_runtime",
            }
        )

        self.assertEqual(CUSTOMER_PRIVATE_AUTHORITY, payload["source_authority"])
        self.assertFalse(payload["source_requires_review"])

    def test_community_source_pack_is_not_reclassified_as_private_upload(self) -> None:
        payload = source_authority_payload(
            {
                "source_collection": "uploaded",
                "source_lane": "community_source_pack",
                "classification": "community",
            }
        )

        self.assertEqual(COMMUNITY_AUTHORITY, payload["source_authority"])
        self.assertTrue(payload["source_requires_review"])

    def test_unreviewed_candidate_is_not_silently_official(self) -> None:
        payload = source_authority_payload(
            {
                "source_lane": "candidate_external",
                "approval_state": "unreviewed",
            }
        )

        self.assertEqual(UNVERIFIED_AUTHORITY, payload["source_authority"])
        self.assertTrue(payload["source_requires_review"])

    def test_source_provenance_carries_authority(self) -> None:
        payload = source_provenance_payload(
            {
                "source_url": "https://github.com/example/incident-notes/blob/main/ocp.adoc",
                "source_relative_path": "ocp.adoc",
            }
        )

        self.assertEqual(COMMUNITY_AUTHORITY, payload["source_authority"])
        self.assertTrue(payload["source_fingerprint"])


if __name__ == "__main__":
    unittest.main()
