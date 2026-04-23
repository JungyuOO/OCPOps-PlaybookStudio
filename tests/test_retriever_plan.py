from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan


class RetrievalPlanTests(unittest.TestCase):
    def test_selected_customer_pack_generic_intro_query_keeps_raw_normalization(self) -> None:
        query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
        plan = build_retrieval_plan(
            query,
            context=SessionContext(
                mode="chat",
                selected_draft_ids=["dtb-3860785ca6b5"],
                restrict_uploaded_sources=False,
            ),
            candidate_k=20,
        )

        self.assertEqual(query, plan.normalized_query)
        self.assertNotIn("OpenShift Container Platform", plan.normalized_query)
        self.assertNotIn("문서 가이드 참고 개요 플랫폼", plan.normalized_query)

    def test_unselected_generic_intro_query_still_expands_runtime_terms(self) -> None:
        query = "OpenShift 아키텍처가 뭐야"
        plan = build_retrieval_plan(
            query,
            context=SessionContext(mode="chat"),
            candidate_k=20,
        )

        self.assertIn("OpenShift", plan.normalized_query)
        self.assertIn("개요", plan.normalized_query)

    def test_selected_customer_pack_blended_query_appends_official_runtime_subquery(self) -> None:
        query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
        plan = build_retrieval_plan(
            query,
            context=SessionContext(
                mode="chat",
                selected_draft_ids=["dtb-3860785ca6b5"],
                restrict_uploaded_sources=False,
            ),
            candidate_k=20,
        )

        official_queries = [
            item
            for item in plan.rewritten_queries
            if item != plan.normalized_query and "openshift" in item.lower()
        ]
        self.assertEqual(50, plan.effective_candidate_k)
        self.assertGreaterEqual(len(official_queries), 3)
        self.assertTrue(any("router" in item.lower() for item in official_queries))
        self.assertTrue(
            any("아키텍처" in item or "architecture" in item.lower() for item in official_queries)
        )
        self.assertTrue(any("개요" in item or "overview" in item.lower() for item in official_queries))

    def test_selected_customer_pack_title_locator_query_keeps_single_official_lookup(self) -> None:
        query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 문서를 찾아줘"
        plan = build_retrieval_plan(
            query,
            context=SessionContext(
                mode="chat",
                selected_draft_ids=["dtb-3860785ca6b5"],
                restrict_uploaded_sources=False,
            ),
            candidate_k=20,
        )

        official_queries = [
            item
            for item in plan.rewritten_queries
            if item != plan.normalized_query and "openshift" in item.lower()
        ]
        self.assertEqual(40, plan.effective_candidate_k)
        self.assertEqual(1, len(official_queries))
        self.assertFalse(any("개요" in item or "overview" in item.lower() for item in official_queries))

    def test_selected_customer_pack_compare_query_skips_official_explainer_variants(self) -> None:
        query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Route와 Ingress 차이를 설명해줘"
        plan = build_retrieval_plan(
            query,
            context=SessionContext(
                mode="chat",
                selected_draft_ids=["dtb-3860785ca6b5"],
                restrict_uploaded_sources=False,
            ),
            candidate_k=20,
        )

        self.assertEqual(40, plan.effective_candidate_k)
        self.assertEqual(4, len(plan.rewritten_queries))
        self.assertFalse(
            any(
                "openshift route ingress 개요" in item.lower()
                or "openshift route ingress overview" in item.lower()
                for item in plan.rewritten_queries
            )
        )


if __name__ == "__main__":
    unittest.main()
