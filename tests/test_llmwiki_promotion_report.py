from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.llmwiki_promotion_report import build_llmwiki_promotion_summary


def _official_gold_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "failures": [],
        "metrics": {
            "chunks_count": 100,
            "bm25_count": 100,
            "playbook_document_count": 10,
            "figure_sidecar_count": 3,
            "playbook_block_counts": {
                "code": 12,
                "figure": 3,
            },
        },
    }


def _customer_master_payload() -> dict[str, object]:
    return {
        "status": "ready",
        "master_slug": "customer-master-kmsc-ocp-operations-playbook",
        "source_count": 2,
        "section_count": 8,
        "chunk_count": 8,
        "shared_grade": "gold",
        "publish_ready": True,
        "runtime_eligible": True,
        "validation": {
            "ok": True,
            "source_coverage_ratio": 1.0,
        },
    }


def _runtime_report_payload() -> dict[str, object]:
    return {
        "probes": {
            "local_ui": {"health_status": 200},
            "embedding": {
                "mode": "remote",
                "base_url": "http://tei.example/v1",
                "model": "dragonkue/bge-m3-ko",
                "sample_embedding_ok": True,
                "sample_vector_dim": 1024,
            },
            "qdrant": {
                "url": "http://127.0.0.1:6335",
                "collection": "openshift_docs",
                "collection_present": True,
            },
            "llm": {
                "endpoint": "http://llm.example/v1",
                "model": "Qwen/Qwen3.5-9B",
                "models_status": 200,
            },
        },
    }


def _chat_matrix_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "pass_count": 6,
        "total": 6,
        "runtime_requirements": {
            "llm_live_pass_count": 2,
            "llm_live_total": 2,
            "vector_live_pass_count": 2,
            "vector_live_total": 2,
        },
    }


class LlmwikiPromotionReportTests(unittest.TestCase):
    def test_summary_passes_when_official_customer_runtime_and_chat_contracts_pass(self) -> None:
        summary = build_llmwiki_promotion_summary(
            official_gold=_official_gold_payload(),
            customer_master=_customer_master_payload(),
            runtime_report=_runtime_report_payload(),
            runtime_maintenance={"summary": {"ok": True}},
            chat_matrix=_chat_matrix_payload(),
            material_scope={"enabled": True, "deduplicated_source_count": 2},
        )

        self.assertEqual("ok", summary["status"])
        self.assertTrue(summary["ready_for_llmwiki_promotion"])
        self.assertEqual([], summary["failures"])

    def test_summary_fails_when_chat_matrix_has_no_live_vector_contract(self) -> None:
        chat_matrix = _chat_matrix_payload()
        chat_matrix["runtime_requirements"] = {
            "llm_live_pass_count": 2,
            "llm_live_total": 2,
            "vector_live_pass_count": 0,
            "vector_live_total": 0,
        }

        summary = build_llmwiki_promotion_summary(
            official_gold=_official_gold_payload(),
            customer_master=_customer_master_payload(),
            runtime_report=_runtime_report_payload(),
            runtime_maintenance={"summary": {"ok": True}},
            chat_matrix=chat_matrix,
            material_scope={"enabled": True, "deduplicated_source_count": 2},
        )

        self.assertEqual("fail", summary["status"])
        self.assertIn("chat_matrix", summary["failures"])
        self.assertIn("runtime_report", summary["failures"])

    def test_summary_fails_when_customer_materials_are_not_covered_by_master_book(self) -> None:
        summary = build_llmwiki_promotion_summary(
            official_gold=_official_gold_payload(),
            customer_master=_customer_master_payload(),
            runtime_report=_runtime_report_payload(),
            runtime_maintenance={"summary": {"ok": True}},
            chat_matrix=_chat_matrix_payload(),
            material_scope={"enabled": True, "deduplicated_source_count": 3},
        )

        self.assertEqual("fail", summary["status"])
        self.assertIn("customer_master", summary["failures"])


if __name__ == "__main__":
    unittest.main()
