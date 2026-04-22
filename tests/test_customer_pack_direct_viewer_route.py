from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from play_book_studio.intake import CustomerPackDraftStore
from tests.test_customer_pack_read_boundary import _ingest_pack, _test_server


class CustomerPackDirectViewerRouteTests(unittest.TestCase):
    def test_direct_customer_pack_viewer_route_serves_html_for_approved_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="approved",
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                approval_state="approved",
            )

            with _test_server(root) as (base_url, _store, _answerer):
                response = requests.get(
                    f"{base_url}/playbooks/customer-packs/{approved['draft_id']}/index.html",
                    timeout=10,
                )

            self.assertEqual(200, response.status_code)
            self.assertIn("Customer Source-First Pack", response.text)
            self.assertIn("<!DOCTYPE html>", response.text)

    def test_direct_customer_pack_viewer_route_fail_closes_for_non_read_ready_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            blocked = _ingest_pack(
                root,
                draft_tag="needs-review",
                tenant_id="tenant-b",
                workspace_id="workspace-b",
                approval_state="approved",
            )
            store = CustomerPackDraftStore(root)
            record = store.get(str(blocked["draft_id"]))
            assert record is not None
            record.approval_state = "needs_review"
            store.save(record)

            with _test_server(root) as (base_url, _store, _answerer):
                response = requests.get(
                    f"{base_url}/playbooks/customer-packs/{blocked['draft_id']}/index.html",
                    timeout=10,
                )

            self.assertEqual(404, response.status_code)
