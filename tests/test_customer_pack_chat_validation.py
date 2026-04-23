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

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.answering.context import assemble_context
from play_book_studio.app.intake_api import ingest_customer_pack
from play_book_studio.app.server_support import _build_chat_payload
from play_book_studio.app.sessions import ChatSession
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever
from tests.test_customer_pack_native_ooxml_smoke import _create_messy_pptx
from tests.test_customer_pack_read_boundary import (
    _FakeChunkingModel,
    _FakeEmbeddingModel,
)


class _FakeRelationLlmClient:
    def generate(self, messages, trace_callback=None, max_tokens=None) -> str:
        del messages, trace_callback, max_tokens
        return "답변: 개발 환경에서 운영 환경으로 넘어가는 흐름입니다 [1]."

    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
            "last_requested_max_tokens": 0,
        }


class CustomerPackChatValidationTests(unittest.TestCase):
    def test_customer_pack_relation_query_bypasses_ambiguity_clarification_for_uploaded_hits(self) -> None:
        session_context = SessionContext(
            mode="chat",
            selected_draft_ids=["draft-p"],
            restrict_uploaded_sources=True,
        )
        hits = [
            RetrievalHit(
                chunk_id="relation-hit",
                book_slug="p",
                chapter="CICD 프로세스",
                section="CICD 프로세스",
                anchor="cicd-프로세스",
                source_url="/private/P",
                viewer_path="/playbooks/customer-packs/draft-p/index.html#cicd-프로세스",
                text=(
                    "CICD 프로세스\n"
                    "개발(aka. 검증) 환경 -> 운영 환경\n"
                    "relation_type: phase_sequence\n"
                    "question_classes: flow"
                ),
                source="hybrid_reranked",
                raw_score=0.2032,
                fused_score=0.2032,
                chunk_type="relation",
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="pptx",
                review_status="approved",
                semantic_role="flow",
                graph_relations=("flow", "same_book", "shared_collection"),
            ),
            RetrievalHit(
                chunk_id="procedure-hit",
                book_slug="p",
                chapter="CICD 관련 주요 변경 사항",
                section="CICD 관련 주요 변경 사항",
                anchor="cicd-관련-주요-변경-사항",
                source_url="/private/P",
                viewer_path="/playbooks/customer-packs/draft-p/index.html#cicd-관련-주요-변경-사항",
                text="개발 환경은 개발 클러스터를 사용하며 운영 환경은 운영 클러스터 사용",
                source="hybrid_reranked",
                raw_score=0.2072,
                fused_score=0.2072,
                chunk_type="procedure",
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="pptx",
                review_status="approved",
                semantic_role="procedure",
                graph_relations=("same_book", "shared_collection"),
            ),
            RetrievalHit(
                chunk_id="derived-hit-1",
                book_slug="draft-p--topic_playbook",
                chapter="CICD 관련 주요 변경 사항",
                section="CICD 관련 주요 변경 사항",
                anchor="cicd-관련-주요-변경-사항",
                source_url="/private/P",
                viewer_path="/playbooks/customer-packs/draft-p/assets/topic/index.html#cicd-관련-주요-변경-사항",
                text="토픽 플레이북 파생 절차",
                source="hybrid_reranked",
                raw_score=0.1869,
                fused_score=0.1869,
                chunk_type="procedure",
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="topic_playbook",
                review_status="approved",
                semantic_role="procedure",
                graph_relations=("shared_collection",),
            ),
            RetrievalHit(
                chunk_id="derived-hit-2",
                book_slug="draft-p--operation_playbook",
                chapter="CICD 관련 주요 변경 사항",
                section="CICD 관련 주요 변경 사항",
                anchor="cicd-관련-주요-변경-사항",
                source_url="/private/P",
                viewer_path="/playbooks/customer-packs/draft-p/assets/operation/index.html#cicd-관련-주요-변경-사항",
                text="운영 플레이북 파생 절차",
                source="hybrid_reranked",
                raw_score=0.1867,
                fused_score=0.1867,
                chunk_type="procedure",
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="operation_playbook",
                review_status="approved",
                semantic_role="procedure",
                graph_relations=("shared_collection",),
            ),
        ]

        bundle = assemble_context(
            hits,
            query="CI에서 운영 환경으로 어떤 흐름으로 넘어가?",
            session_context=session_context,
            max_chunks=4,
        )

        self.assertTrue(bundle.citations)
        self.assertEqual("relation", bundle.citations[0].chunk_type)
        self.assertEqual("flow", bundle.citations[0].semantic_role)

    def test_relation_query_keeps_relation_citation_and_private_viewer_landing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "messy.pptx"
            _create_messy_pptx(source_path)

            with (
                patch(
                    "play_book_studio.intake.private_corpus.load_sentence_model",
                    return_value=_FakeEmbeddingModel(),
                ),
                patch(
                    "play_book_studio.ingestion.chunking.load_sentence_model",
                    return_value=_FakeChunkingModel(),
                ),
            ):
                ingest_result = ingest_customer_pack(
                    root,
                    {
                        "source_type": "pptx",
                        "uri": str(source_path),
                        "title": "P 유형 샘플",
                        "approval_state": "approved",
                    },
                )

            settings = load_settings(root)
            draft_id = str(ingest_result["draft_id"])
            session_context = SessionContext(
                mode="chat",
                ocp_version=settings.ocp_version,
                selected_draft_ids=[draft_id],
                restrict_uploaded_sources=True,
            )
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            answerer = ChatAnswerer(
                settings=settings,
                retriever=retriever,
                llm_client=_FakeRelationLlmClient(),
            )

            result = answerer.answer(
                "CI에서 운영 환경으로 어떤 흐름으로 넘어가?",
                context=session_context,
                top_k=5,
                candidate_k=10,
                max_context_chunks=4,
            )

            self.assertEqual("rag", result.response_kind)
            self.assertEqual([1], result.cited_indices)
            self.assertTrue(result.citations)
            citation = result.citations[0]
            self.assertEqual("relation", citation.chunk_type)
            self.assertEqual("flow", citation.semantic_role)
            self.assertTrue(citation.viewer_path.startswith(f"/playbooks/customer-packs/{draft_id}/index.html#"))
            self.assertGreaterEqual(int(result.retrieval_trace.get("effective_candidate_k") or 0), 30)

            session = ChatSession(
                session_id="packet-4-validation",
                context=session_context,
            )
            payload = _build_chat_payload(
                root_dir=root,
                answerer=answerer,
                session=session,
                result=result,
            )

            self.assertTrue(payload["citations"])
            serialized = payload["citations"][0]
            self.assertEqual("private_customer_pack_runtime", serialized["boundary_truth"])
            self.assertTrue(serialized["read_ready"])
            self.assertEqual("exact", serialized["citation_landing_status"])


if __name__ == "__main__":
    unittest.main()
