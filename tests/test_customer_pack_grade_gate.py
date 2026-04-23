from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.service import evaluate_canonical_book_quality


def _base_payload() -> dict[str, object]:
    return {
        "title": "운영 가이드",
        "source_type": "md",
        "approval_state": "approved",
        "publication_state": "draft",
        "sections": [
            {
                "ordinal": 1,
                "section_key": "backup",
                "heading": "백업 절차",
                "section_level": 1,
                "section_path": ["백업 절차"],
                "anchor": "backup",
                "viewer_path": "/playbooks/customer-packs/draft-1/index.html#backup",
                "source_url": "/api/customer-packs/captured?draft_id=draft-1",
                "text": "oc get pods -A\n확인: Pod 상태를 점검한다.",
                "semantic_role": "procedure",
                "block_kinds": ["code"],
            },
            {
                "ordinal": 2,
                "section_key": "policy",
                "heading": "정책 검증",
                "section_level": 1,
                "section_path": ["정책 검증"],
                "anchor": "policy",
                "viewer_path": "/playbooks/customer-packs/draft-1/index.html#policy",
                "source_url": "/api/customer-packs/captured?draft_id=draft-1",
                "text": "must keep audit logging enabled.\n확인: 정책을 다시 검증한다.",
                "semantic_role": "reference",
                "block_kinds": ["paragraph"],
            },
        ],
    }


class CustomerPackGradeGateTests(unittest.TestCase):
    def test_grade_gate_promotes_exact_anchor_and_retrieval_ready_bundle(self) -> None:
        quality = evaluate_canonical_book_quality(
            _base_payload(),
            corpus_manifest={
                "chunk_count": 4,
                "bm25_ready": True,
                "vector_status": "ready",
                "anchor_lineage_count": 2,
            },
        )

        self.assertIn(quality["shared_grade"], {"gold", "silver"})
        self.assertEqual("ready", quality["quality_status"])
        self.assertEqual("exact", quality["grade_gate"]["citation_gate"]["status"])
        self.assertTrue(quality["grade_gate"]["retrieval_gate"]["ready"])
        self.assertTrue(quality["grade_gate"]["promotion_gate"]["read_ready"])
        self.assertFalse(quality["grade_gate"]["promotion_gate"]["publish_ready"])
        self.assertEqual("candidate", quality["grade_gate"]["promotion_gate"]["status"])

    def test_grade_gate_downgrades_partial_citation_landing_to_bronze(self) -> None:
        payload = _base_payload()
        sections = [dict(section) for section in (payload.get("sections") or []) if isinstance(section, dict)]
        sections[0]["viewer_path"] = "/playbooks/customer-packs/draft-1/index.html"
        sections[1]["viewer_path"] = "/playbooks/customer-packs/draft-1/index.html"
        payload["sections"] = sections

        quality = evaluate_canonical_book_quality(
            payload,
            corpus_manifest={
                "chunk_count": 4,
                "bm25_ready": True,
                "vector_status": "ready",
                "anchor_lineage_count": 2,
            },
        )

        self.assertEqual("bronze", quality["shared_grade"])
        self.assertEqual("review", quality["quality_status"])
        self.assertEqual("partial", quality["grade_gate"]["citation_gate"]["status"])
        self.assertFalse(quality["grade_gate"]["promotion_gate"]["read_ready"])

    def test_private_runtime_boundary_requires_grade_gate_read_ready(self) -> None:
        summary = summarize_private_runtime_boundary(
            {
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "pack_id": "customer-pack:draft-1",
                "pack_version": "draft-1",
                "classification": "private",
                "access_groups": ["workspace-a", "tenant-a"],
                "provider_egress_policy": "local_only",
                "approval_state": "approved",
                "publication_state": "draft",
                "redaction_state": "masked",
                "boundary_truth": "private_customer_pack_runtime",
                "runtime_truth_label": "Customer Source-First Pack",
                "boundary_badge": "Private Pack Runtime",
                "read_ready": False,
                "grade_gate": {
                    "promotion_gate": {
                        "read_ready": False,
                        "publish_ready": False,
                    }
                },
            }
        )

        self.assertFalse(summary["runtime_eligible"])
        self.assertFalse(summary["read_ready"])
        self.assertIn("grade_gate_not_runtime_ready", summary["fail_reasons"])


if __name__ == "__main__":
    unittest.main()
