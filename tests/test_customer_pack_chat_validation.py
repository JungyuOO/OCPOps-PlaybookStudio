from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.answerer import ChatAnswerer, _build_doc_locator_answer
from play_book_studio.answering.context import (
    _is_customer_pack_title_locator_query as _is_context_customer_pack_title_locator_query,
    _select_hits,
    _should_force_clarification,
    assemble_context,
)
from play_book_studio.answering.models import Citation, ContextBundle
from play_book_studio.app.intake_api import ingest_customer_pack
from play_book_studio.app.intake_api import (
    capture_customer_pack_draft,
    normalize_customer_pack_draft,
    upload_customer_pack_draft,
)
from play_book_studio.app.server_support import _build_chat_payload
from play_book_studio.app.sessions import ChatSession
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever
from play_book_studio.retrieval.retriever_search import _is_customer_pack_title_locator_query
from tests.test_customer_pack_native_ooxml_smoke import _create_messy_pptx, _fake_render_slide_previews
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


class _FakeMissingCoverageLlmClient:
    def generate(self, messages, trace_callback=None, max_tokens=None) -> str:
        del messages, trace_callback, max_tokens
        return "제공된 근거에 포함되어 있지 않습니다. 대신 별도 자료가 필요합니다."

    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
            "last_requested_max_tokens": 0,
        }


def _official_doc_row(
    *,
    chunk_id: str,
    book_slug: str,
    section: str,
    text: str,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "book_slug": book_slug,
        "chapter": section,
        "section": section,
        "section_id": chunk_id,
        "anchor": chunk_id,
        "source_url": f"https://docs.redhat.com/{book_slug}",
        "viewer_path": f"/playbooks/wiki/{book_slug}/index.html#{chunk_id}",
        "text": text,
        "section_path": [section],
        "chunk_type": "reference",
        "source_id": f"official:{book_slug}",
        "source_lane": "official_ko",
        "source_type": "official_doc",
        "source_collection": "core",
        "surface_kind": "document",
        "source_unit_kind": "section",
        "source_unit_id": chunk_id,
        "source_unit_anchor": chunk_id,
        "origin_method": "native",
        "ocr_status": "not_run",
        "review_status": "approved",
        "trust_score": 1.0,
        "semantic_role": "reference",
        "block_kinds": [],
        "cli_commands": [],
        "error_strings": [],
        "k8s_objects": [],
        "operator_names": [],
        "verification_hints": [],
        "graph_relations": [],
    }


def _uploaded_hit(
    *,
    chunk_id: str,
    book_slug: str,
    title: str,
    viewer_path: str,
    source_url: str,
    fused_score: float,
    pre_rerank_fused_score: float,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter=title,
        section=title,
        anchor=chunk_id,
        source_url=source_url,
        viewer_path=viewer_path,
        text=(
            f"문서 제목: {title}\n"
            f"원본 파일: {Path(source_url).name}\n"
            f"문서 제목: {title}\n"
            f"섹션 제목: {title}\n"
            "2025. 07. 25"
        ),
        source="hybrid_reranked",
        raw_score=fused_score,
        fused_score=fused_score,
        chunk_type="reference",
        source_id=f"customer_pack:{book_slug}",
        source_lane="customer_pack",
        source_type="pptx",
        source_collection="uploaded",
        review_status="ready",
        semantic_role="concept",
        component_scores={"pre_rerank_fused_score": pre_rerank_fused_score},
    )


class CustomerPackChatValidationTests(unittest.TestCase):
    def test_save_to_wiki_promotes_customer_ppt_for_global_title_locator_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-title-locator.pptx"
            _create_messy_pptx(source_path)

            uploaded = upload_customer_pack_draft(
                root,
                {
                    "source_type": "pptx",
                    "file_name": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
                    "file_bytes": source_path.read_bytes(),
                    "title": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL",
                    "approval_state": "approved",
                },
            )
            draft_id = str(uploaded["draft_id"])
            capture_customer_pack_draft(root, {"draft_id": draft_id})

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
                normalized = normalize_customer_pack_draft(
                    root,
                    {
                        "draft_id": draft_id,
                        "publication_state": "active",
                    },
                )

            self.assertEqual("active", normalized["publication_state"])
            private_corpus = normalized.get("private_corpus") or {}
            self.assertTrue(private_corpus.get("publish_ready"))
            self.assertTrue(private_corpus.get("runtime_eligible"))

            settings = load_settings(root)
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            result = retriever.retrieve(
                "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘",
                context=SessionContext(mode="chat"),
                top_k=5,
                candidate_k=12,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            top_hit = result.hits[0]
            self.assertEqual("uploaded", top_hit.source_collection)
            self.assertEqual("pptx", top_hit.source_type)
            self.assertTrue(
                top_hit.viewer_path.startswith(f"/playbooks/customer-packs/{draft_id}/index.html#")
            )

    def test_title_locator_cache_refreshes_when_private_manifest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-title-cache.pptx"
            _create_messy_pptx(source_path)

            uploaded = upload_customer_pack_draft(
                root,
                {
                    "source_type": "pptx",
                    "file_name": "KOMSCO-ARCHITECTURE-TITLE-CACHE.pptx",
                    "file_bytes": source_path.read_bytes(),
                    "title": "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서",
                    "approval_state": "approved",
                },
            )
            draft_id = str(uploaded["draft_id"])
            capture_customer_pack_draft(root, {"draft_id": draft_id})

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
                normalize_customer_pack_draft(
                    root,
                    {
                        "draft_id": draft_id,
                        "publication_state": "active",
                    },
                )

            settings = load_settings(root)
            manifest_path = settings.customer_pack_corpus_dir / draft_id / "manifest.json"
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload["approval_state"] = "review_required"
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            query = "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘"

            blocked = retriever.retrieve(
                query,
                context=SessionContext(mode="chat"),
                top_k=5,
                candidate_k=12,
                use_vector=False,
            )
            self.assertFalse(blocked.hits)

            manifest_payload["approval_state"] = "approved"
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            recovered = retriever.retrieve(
                query,
                context=SessionContext(mode="chat"),
                top_k=5,
                candidate_k=12,
                use_vector=False,
            )
            self.assertTrue(recovered.hits)
            self.assertEqual("uploaded", recovered.hits[0].source_collection)
            self.assertTrue(
                recovered.hits[0].viewer_path.startswith(f"/playbooks/customer-packs/{draft_id}/index.html#")
            )

    def test_unpublished_customer_pack_is_excluded_from_global_title_locator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-title-draft-only.pptx"
            _create_messy_pptx(source_path)

            uploaded = upload_customer_pack_draft(
                root,
                {
                    "source_type": "pptx",
                    "file_name": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
                    "file_bytes": source_path.read_bytes(),
                    "title": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL",
                    "approval_state": "approved",
                },
            )
            draft_id = str(uploaded["draft_id"])
            capture_customer_pack_draft(root, {"draft_id": draft_id})

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
                normalized = normalize_customer_pack_draft(
                    root,
                    {
                        "draft_id": draft_id,
                        "publication_state": "draft",
                    },
                )

            self.assertEqual("draft", normalized["publication_state"])
            private_corpus = normalized.get("private_corpus") or {}
            self.assertFalse(private_corpus.get("publish_ready"))

            settings = load_settings(root)
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            result = retriever.retrieve(
                "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘",
                context=SessionContext(mode="chat"),
                top_k=5,
                candidate_k=12,
                use_vector=False,
            )

            self.assertFalse(result.hits)

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

    def test_title_only_customer_pack_query_keeps_uploaded_citation_ahead_of_service_mesh(self) -> None:
        hits = [
            RetrievalHit(
                chunk_id="uploaded-cicd",
                book_slug="customer-cicd",
                chapter="CICD",
                section="KOMSCO 서비스 메시 CICD 설계서",
                anchor="cicd",
                source_url="/private/customer-cicd",
                viewer_path="/playbooks/customer-packs/draft-cicd/index.html#cicd",
                text="문서 제목: KOMSCO 서비스 메시 아키텍처 설계서\nCICD 흐름과 배포 구조",
                source="hybrid",
                raw_score=0.92,
                fused_score=0.92,
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="pptx",
                review_status="approved",
                semantic_role="concept",
            ),
            RetrievalHit(
                chunk_id="official-service-mesh",
                book_slug="service_mesh",
                chapter="Service Mesh 개요",
                section="Service Mesh 개요",
                anchor="service-mesh-overview",
                source_url="https://docs.redhat.com/service-mesh",
                viewer_path="/playbooks/wiki/service_mesh/index.html#service-mesh-overview",
                text="service mesh 공식 개요 문서",
                source="hybrid",
                raw_score=0.61,
                fused_score=0.61,
                source_collection="core",
                source_lane="official_ko",
                source_type="official_doc",
                review_status="approved",
                semantic_role="concept",
            ),
        ]

        bundle = assemble_context(
            hits,
            query="KOMSCO 서비스 메시 아키텍처 설계서",
            session_context=SessionContext(mode="chat"),
            max_chunks=2,
        )

        self.assertTrue(bundle.citations)
        citation = bundle.citations[0]
        self.assertEqual("uploaded", citation.source_collection)
        self.assertEqual("customer-cicd", citation.book_slug)
        self.assertTrue(citation.viewer_path.startswith("/playbooks/customer-packs/draft-cicd/index.html#"))

    def test_selected_customer_pack_explainer_query_keeps_router_citation_ahead_of_generic_intro_books(self) -> None:
        query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
        hits = [
            RetrievalHit(
                chunk_id="customer-router",
                book_slug="customer-router",
                chapter="네트워크",
                section="Router Node 구성",
                anchor="router-node-구성",
                source_url="/private/customer-router",
                viewer_path="/playbooks/customer-packs/dtb-router/index.html#router-node-구성",
                text="Router Node 구성과 외부 L4, Route, IngressController 관계를 설명한다.",
                source="hybrid",
                raw_score=0.98,
                fused_score=0.98,
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="pptx",
                review_status="approved",
                semantic_role="procedure",
                chunk_type="procedure",
            ),
            RetrievalHit(
                chunk_id="customer-derived-network",
                book_slug="customer-router--troubleshooting_playbook",
                chapter="트러블슈팅",
                section="가상 및 물리 노드 네트워크 및 도메인",
                anchor="가상-및-물리-노드-네트워크-및-도메인",
                source_url="/private/customer-router-derived",
                viewer_path="/playbooks/customer-packs/dtb-router-derived/index.html#가상-및-물리-노드-네트워크-및-도메인",
                text="Router 노드와 도메인 목록을 나열한다.",
                source="hybrid",
                raw_score=0.93,
                fused_score=0.93,
                source_collection="uploaded",
                source_lane="customer_source_first_pack",
                source_type="operation_playbook",
                review_status="approved",
                semantic_role="reference",
                chunk_type="reference",
            ),
            RetrievalHit(
                chunk_id="official-architecture",
                book_slug="architecture",
                chapter="아키텍처",
                section="OpenShift Container Platform의 아키텍처 개요",
                anchor="architecture-overview",
                source_url="https://docs.redhat.com/architecture",
                viewer_path="/playbooks/wiki-runtime/active/architecture/index.html#architecture-overview",
                text="OpenShift Router와 Ingress Controller의 기본 아키텍처를 설명한다.",
                source="hybrid",
                raw_score=0.74,
                fused_score=0.74,
                source_collection="core",
                source_lane="official_ko",
                source_type="official_doc",
                review_status="approved",
                semantic_role="concept",
                chunk_type="concept",
            ),
        ]

        bundle = assemble_context(
            hits,
            query=query,
            session_context=SessionContext(
                mode="chat",
                selected_draft_ids=["dtb-router"],
                restrict_uploaded_sources=False,
            ),
            max_chunks=4,
        )

        self.assertTrue(bundle.citations)
        self.assertEqual("uploaded", bundle.citations[0].source_collection)
        self.assertEqual("customer-router", bundle.citations[0].book_slug)
        self.assertEqual("Router Node 구성", bundle.citations[0].section)
        self.assertIn("core", {citation.source_collection for citation in bundle.citations})

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

    def test_title_locator_query_prefers_uploaded_customer_pack_without_active_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "messy.pptx"
            _create_messy_pptx(source_path)

            uploaded = upload_customer_pack_draft(
                root,
                {
                    "source_type": "pptx",
                    "file_name": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
                    "file_bytes": source_path.read_bytes(),
                    "title": "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서",
                    "approval_state": "approved",
                },
            )
            draft_id = str(uploaded["draft_id"])
            capture_customer_pack_draft(root, {"draft_id": draft_id})
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
                normalize_customer_pack_draft(
                    root,
                    {
                        "draft_id": draft_id,
                        "publication_state": "active",
                    },
                )

            settings = load_settings(root)
            session_context = SessionContext(
                mode="chat",
                ocp_version=settings.ocp_version,
                restrict_uploaded_sources=True,
            )
            official_rows = [
                _official_doc_row(
                    chunk_id="architecture-overview",
                    book_slug="architecture",
                    section="OpenShift 아키텍처 개요",
                    text=(
                        "OpenShift 아키텍처 설계 문서와 플랫폼 구조를 설명합니다. "
                        "아키텍처 문서, 설계 문서, 플랫폼 아키텍처 자료를 찾을 때 참고합니다."
                    ),
                ),
                _official_doc_row(
                    chunk_id="support-doc-locator",
                    book_slug="support",
                    section="문서 찾기와 지원 가이드",
                    text="운영 문서와 지원 문서를 찾는 일반적인 방법을 설명합니다.",
                ),
            ]
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows(official_rows),
                vector_retriever=None,
                reranker=None,
            )
            query = "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘"

            retrieval = retriever.retrieve(
                query,
                context=session_context,
                top_k=5,
                candidate_k=10,
                use_vector=False,
            )

            self.assertTrue(retrieval.hits)
            top_hit = retrieval.hits[0]
            self.assertEqual("uploaded", top_hit.source_collection)
            self.assertTrue(top_hit.viewer_path.startswith(f"/playbooks/customer-packs/{draft_id}/index.html"))

            bundle = assemble_context(
                retrieval.hits,
                query=query,
                session_context=session_context,
                max_chunks=3,
            )

            self.assertTrue(bundle.citations)
            citation = bundle.citations[0]
            self.assertEqual("uploaded", citation.source_collection)
            self.assertTrue(citation.viewer_path.startswith(f"/playbooks/customer-packs/{draft_id}/index.html"))
            self.assertIn("KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서", citation.excerpt)
            self.assertNotEqual("architecture", citation.book_slug)

    def test_selected_customer_pack_can_blend_with_official_docs_when_not_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-route.md"
            source_path.write_text(
                "# 고객 Route 운영\n\n"
                "Route 점검 절차\n"
                "oc get route -A\n"
                "Ingress Controller 상태를 함께 확인한다.\n",
                encoding="utf-8",
            )

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
                normalized = ingest_customer_pack(
                    root,
                    {
                        "source_type": "md",
                        "uri": str(source_path),
                        "title": "고객 Route 운영",
                        "approval_state": "approved",
                        "publication_state": "active",
                    },
                )

            draft_id = str(normalized["draft_id"])
            settings = load_settings(root)
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows(
                    [
                        _official_doc_row(
                            chunk_id="route-official",
                            book_slug="ingress_and_load_balancing",
                            section="Route 운영과 Ingress 점검",
                            text="OpenShift Route 와 Ingress 점검 절차, ingress controller 상태 확인, route 리소스 점검 순서를 설명합니다.",
                        )
                    ]
                ),
                vector_retriever=None,
                reranker=None,
            )

            retrieval = retriever.retrieve(
                "Route 점검 절차를 고객 문서와 OpenShift 공식문서를 같이 참고해서 알려줘",
                context=SessionContext(
                    mode="chat",
                    selected_draft_ids=[draft_id],
                    restrict_uploaded_sources=False,
                ),
                top_k=6,
                candidate_k=10,
                use_vector=False,
            )

            source_collections = {str(hit.source_collection or "") for hit in retrieval.hits}
            self.assertIn("uploaded", source_collections)
            self.assertIn("core", source_collections)

            bundle = assemble_context(
                retrieval.hits,
                query="Route 점검 절차를 고객 문서와 OpenShift 공식문서를 같이 참고해서 알려줘",
                session_context=SessionContext(
                    mode="chat",
                    selected_draft_ids=[draft_id],
                    restrict_uploaded_sources=False,
                ),
                max_chunks=4,
            )
            citation_source_collections = {
                str(citation.source_collection or "")
                for citation in bundle.citations
            }
            self.assertIn("uploaded", citation_source_collections)
            self.assertIn("core", citation_source_collections)

    def test_explicit_customer_content_query_uses_active_overlay_without_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-cicd.md"
            source_path.write_text(
                "# 고객 CI/CD 운영\n\n"
                "CI/CD 운영 구조\n"
                "파이프라인 빌드와 배포 승인, 운영 전환 점검 절차를 설명한다.\n",
                encoding="utf-8",
            )

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
                ingest_customer_pack(
                    root,
                    {
                        "source_type": "md",
                        "uri": str(source_path),
                        "title": "고객 CI/CD 운영",
                        "approval_state": "approved",
                        "publication_state": "active",
                    },
                )

            settings = load_settings(root)
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            query = "고객 문서 기준 CI/CD 운영 구조를 요약해줘"
            retrieval = retriever.retrieve(
                query,
                context=SessionContext(mode="chat", restrict_uploaded_sources=True),
                top_k=4,
                candidate_k=8,
                use_vector=False,
            )

            self.assertTrue(retrieval.hits)
            self.assertEqual("uploaded", retrieval.hits[0].source_collection)

            bundle = assemble_context(
                retrieval.hits,
                query=query,
                session_context=SessionContext(mode="chat", restrict_uploaded_sources=True),
                max_chunks=2,
            )
            self.assertTrue(bundle.citations)
            self.assertEqual("uploaded", bundle.citations[0].source_collection)

    def test_normalize_fast_path_updates_runtime_metadata_without_rebuilding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "customer-cicd.pptx"
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
                patch(
                    "play_book_studio.intake.pptx_slide_packets.render_pptx_slide_preview_assets",
                    side_effect=_fake_render_slide_previews,
                ),
            ):
                normalized = ingest_customer_pack(
                    root,
                    {
                        "source_type": "pptx",
                        "uri": str(source_path),
                        "title": "고객 CICD 문서",
                        "approval_state": "approved",
                    },
                )

            draft_id = str(normalized["draft_id"])
            self.assertEqual("draft", normalized["publication_state"])

            with (
                patch(
                    "play_book_studio.intake.normalization.service.build_canonical_book",
                    side_effect=AssertionError("fast-path should not rebuild canonical book"),
                ),
                patch(
                    "play_book_studio.intake.normalization.service.materialize_customer_pack_private_corpus",
                    side_effect=AssertionError("fast-path should not rebuild private corpus"),
                ),
                patch(
                    "play_book_studio.intake.normalization.service.build_customer_pack_playable_books",
                    side_effect=AssertionError("fast-path should not rebuild playable books"),
                ),
            ):
                refreshed = normalize_customer_pack_draft(
                    root,
                    {
                        "draft_id": draft_id,
                        "publication_state": "active",
                    },
                )

            self.assertEqual("normalized", refreshed["status"])
            self.assertEqual("active", refreshed["publication_state"])
            self.assertEqual("active", dict(refreshed.get("private_corpus") or {}).get("publication_state"))
            self.assertTrue(bool(dict(refreshed.get("private_corpus") or {}).get("publish_ready")))

            settings = load_settings(root)
            canonical_path = settings.customer_pack_books_dir / f"{draft_id}.json"
            manifest_path = settings.customer_pack_books_dir / f"{draft_id}.manifest.json"
            corpus_manifest_path = settings.customer_pack_corpus_dir / draft_id / "manifest.json"

            canonical_payload = json.loads(canonical_path.read_text(encoding="utf-8"))
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            corpus_manifest = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))

            self.assertEqual("active", canonical_payload["publication_state"])
            self.assertEqual("active", manifest_payload["publication_state"])
            self.assertEqual("active", corpus_manifest["publication_state"])
            self.assertTrue(bool(canonical_payload["publish_ready"]))
            self.assertTrue(bool(manifest_payload["publish_ready"]))
            self.assertTrue(bool(corpus_manifest["publish_ready"]))

    def test_title_locator_query_prefers_real_uploaded_customer_doc_over_test_and_wrong_uploaded_doc(self) -> None:
        query = "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘"
        session_context = SessionContext(
            mode="chat",
            restrict_uploaded_sources=True,
        )
        hits = [
            _uploaded_hit(
                chunk_id="test-3-cicd",
                book_slug="test-3-hybrid",
                title="Test 3 - Hybrid",
                viewer_path="/playbooks/customer-packs/dtb-test3/index.html#cicd",
                source_url=(
                    "C:\\Users\\soulu\\cywell\\PBS_OPS_Cywell_Part3\\OCPOps-PlaybookStudio"
                    "\\.P_docs\\01_검토대기_플레이북재료\\PD-ARCH\\KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx"
                ),
                fused_score=10.2468,
                pre_rerank_fused_score=9.1,
            ),
            _uploaded_hit(
                chunk_id="real-cicd",
                book_slug="kmsc-cocp-recr-005-아키텍처설계서-cicd-20251208-final",
                title="KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서 (CICD)",
                viewer_path="/playbooks/customer-packs/dtb-real/index.html#cicd",
                source_url=(
                    "C:\\Users\\soulu\\cywell\\PBS_OPS_Cywell_Part3\\OCPOps-PlaybookStudio"
                    "\\artifacts\\customer_packs\\captures\\_uploads\\15c7bdc6df-KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx"
                ),
                fused_score=10.1811,
                pre_rerank_fused_score=8.9,
            ),
            _uploaded_hit(
                chunk_id="service-mesh",
                book_slug="kmsc-cocp-recr-005-아키텍처설계서-서비스메쉬-20260116-final",
                title="KOMSCO 지급결제플랫폼 아키텍처 개선 사업 현행 아키텍처 설계서(서비스메쉬)",
                viewer_path="/playbooks/customer-packs/dtb-mesh/index.html#service-mesh",
                source_url=(
                    "C:\\Users\\soulu\\cywell\\PBS_OPS_Cywell_Part3\\OCPOps-PlaybookStudio"
                    "\\artifacts\\customer_packs\\captures\\_uploads\\8b9b6fb0de-KMSC-COCP-RECR-005_아키텍처설계서_서비스메쉬_20260116_FINAL.pptx"
                ),
                fused_score=9.7501,
                pre_rerank_fused_score=9.8,
            ),
        ]

        bundle = assemble_context(
            hits,
            query=query,
            session_context=session_context,
            max_chunks=3,
        )

        self.assertTrue(bundle.citations)
        citation = bundle.citations[0]
        self.assertEqual(
            "kmsc-cocp-recr-005-아키텍처설계서-cicd-20251208-final",
            citation.book_slug,
        )
        self.assertTrue(citation.viewer_path.startswith("/playbooks/customer-packs/dtb-real/index.html"))
        self.assertIn("아키텍처 설계서 (CICD)", citation.excerpt)

    def test_doc_locator_answer_preserves_uploaded_and_official_citations_for_blended_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
            selected_draft_id = "dtb-3860785ca6b5"
            selected_citations = [
                Citation(
                    index=1,
                    chunk_id="customer-router",
                    book_slug="customer-router-playbook",
                    section="Router 구성",
                    anchor="router-section",
                    source_url=f"/playbooks/customer-packs/{selected_draft_id}/index.html#router-section",
                    viewer_path=f"/playbooks/customer-packs/{selected_draft_id}/index.html#router-section",
                    excerpt="고객 OCP 운영 설계서의 Router 구성",
                    source_collection="uploaded",
                ),
                Citation(
                    index=2,
                    chunk_id="official-architecture",
                    book_slug="architecture",
                    section="OpenShift 아키텍처 개요",
                    anchor="architecture-overview",
                    source_url="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
                    viewer_path="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
                    excerpt="OpenShift Router와 아키텍처 개요",
                    source_collection="core",
                ),
            ]
            retriever = Mock()
            retriever.retrieve.return_value = SimpleNamespace(
                hits=[],
                rewritten_query=query,
                trace={"warnings": []},
            )
            answerer = ChatAnswerer(
                settings=settings,
                retriever=retriever,
                llm_client=_FakeRelationLlmClient(),
            )

            with (
                patch("play_book_studio.answering.answerer.route_non_rag", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.assemble_context",
                    return_value=ContextBundle(prompt_context="", citations=selected_citations),
                ),
                patch(
                    "play_book_studio.answering.answerer._build_doc_locator_answer",
                    return_value="답변: 먼저 `Router 구성` 문서를 여는 것이 맞습니다 [1].",
                ),
            ):
                result = answerer.answer(
                    query,
                    context=SessionContext(
                        mode="chat",
                        ocp_version=settings.ocp_version,
                        selected_draft_ids=[selected_draft_id],
                        restrict_uploaded_sources=False,
                    ),
                    top_k=5,
                    candidate_k=10,
                    max_context_chunks=4,
                )

            self.assertEqual("rag", result.response_kind)
            self.assertEqual([1], result.cited_indices)
            self.assertEqual(2, len(result.citations))
            self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in result.citations})

    def test_blended_query_replaces_false_missing_coverage_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
            selected_citations = [
                Citation(
                    index=1,
                    chunk_id="customer-router",
                    book_slug="customer-router-playbook",
                    section="Router 구성",
                    anchor="router-section",
                    source_url="/playbooks/customer-packs/dtb-router/index.html#router-section",
                    viewer_path="/playbooks/customer-packs/dtb-router/index.html#router-section",
                    excerpt="고객 OCP 운영 설계서의 Router 구성",
                    source_collection="uploaded",
                ),
                Citation(
                    index=2,
                    chunk_id="official-network",
                    book_slug="ingress_and_load_balancing",
                    section="Ingress Controller 상태 확인",
                    anchor="ingress-controller-status",
                    source_url="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#ingress-controller-status",
                    viewer_path="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#ingress-controller-status",
                    excerpt="OpenShift 공식 문서의 Ingress Controller 상태 확인 절차",
                    source_collection="core",
                ),
            ]
            retriever = Mock()
            retriever.retrieve.return_value = SimpleNamespace(
                hits=[],
                rewritten_query=query,
                trace={"warnings": []},
            )
            answerer = ChatAnswerer(
                settings=settings,
                retriever=retriever,
                llm_client=_FakeMissingCoverageLlmClient(),
            )

            with (
                patch("play_book_studio.answering.answerer.route_non_rag", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.assemble_context",
                    return_value=ContextBundle(prompt_context="", citations=selected_citations),
                ),
            ):
                result = answerer.answer(
                    query,
                    context=SessionContext(
                        mode="chat",
                        selected_draft_ids=["dtb-router"],
                        restrict_uploaded_sources=False,
                    ),
                    top_k=5,
                    candidate_k=10,
                    max_context_chunks=4,
                )

            self.assertEqual("rag", result.response_kind)
            self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in result.citations})
            self.assertIn("고객 업로드 운영북", result.answer)
            self.assertNotIn("자료 추가가 필요합니다", result.answer)

    def test_explicit_blended_query_keeps_core_even_when_uploads_are_restricted(self) -> None:
        query = "고객 문서와 공식 문서를 같이 참고해서 Route 점검 절차를 알려줘"
        hits = [
            RetrievalHit(
                chunk_id="customer-route",
                book_slug="customer-route-playbook",
                chapter="Route 점검",
                section="Route 점검",
                anchor="route-check",
                source_url="/playbooks/customer-packs/dtb-route/index.html#route-check",
                viewer_path="/playbooks/customer-packs/dtb-route/index.html#route-check",
                text="고객 환경의 Route 점검 절차와 Ingress Controller 확인 순서",
                source="hybrid_reranked",
                raw_score=0.9,
                fused_score=0.9,
                source_collection="uploaded",
                source_lane="customer_pack",
            ),
            RetrievalHit(
                chunk_id="official-route",
                book_slug="ingress_and_load_balancing",
                chapter="Ingress",
                section="Ingress Controller 상태 확인",
                anchor="ingress-status",
                source_url="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#ingress-status",
                viewer_path="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#ingress-status",
                text="OpenShift 공식 문서의 Ingress Controller와 Route 상태 확인 절차",
                source="hybrid_reranked",
                raw_score=0.8,
                fused_score=0.8,
                source_collection="core",
            ),
        ]

        bundle = assemble_context(
            hits,
            query=query,
            session_context=SessionContext(mode="chat", restrict_uploaded_sources=True),
            max_chunks=4,
        )

        self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in bundle.citations})

    def test_explainer_query_does_not_take_doc_locator_fast_path_without_explicit_locator_signal(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="customer-router",
                book_slug="customer-router-playbook",
                section="Router 구성",
                anchor="router-section",
                source_url="/playbooks/customer-packs/dtb-3860785ca6b5/index.html#router-section",
                viewer_path="/playbooks/customer-packs/dtb-3860785ca6b5/index.html#router-section",
                excerpt="고객 OCP 운영 설계서의 Router 구성",
                source_collection="uploaded",
            )
        ]

        self.assertIsNone(
            _build_doc_locator_answer(
                query="고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘",
                citations=citations,
            )
        )
        self.assertIsNotNone(
            _build_doc_locator_answer(
                query="고객 OCP 운영 설계서에서 Router 구성을 어디서 찾아?",
                citations=citations,
            )
        )

    def test_customer_pack_content_query_does_not_collapse_to_locator_answer(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="customer-quality",
                book_slug="customer-master-kmsc-ocp-operations-playbook",
                section="테스트 결과와 품질 판정",
                anchor="quality-section",
                source_url="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#quality-section",
                viewer_path="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#quality-section",
                excerpt="고객 PPT 운영북의 테스트 결과와 품질 판정 내용",
                source_collection="uploaded",
            )
        ]

        self.assertIsNone(
            _build_doc_locator_answer(
                query="고객 문서 기준 테스트 결과와 품질 판정 내용을 알려줘",
                citations=citations,
            )
        )
        self.assertIsNotNone(
            _build_doc_locator_answer(
                query="고객 문서에서 테스트 결과와 품질 판정을 어디서 찾아?",
                citations=citations,
            )
        )

    def test_selected_customer_pack_reranked_top_hit_bypasses_clarification(self) -> None:
        query = "고객 운영북 기준 목표 아키텍처와 OCP 구성 핵심을 설명해줘"
        session_context = SessionContext(
            mode="chat",
            selected_draft_ids=["customer-master-kmsc-ocp-operations-playbook"],
            restrict_uploaded_sources=True,
        )
        hits = [
            RetrievalHit(
                chunk_id="customer-master:architecture",
                book_slug="customer-master-kmsc-ocp-operations-playbook",
                chapter="목표 아키텍처와 OCP 구성",
                section="목표 아키텍처와 OCP 구성",
                anchor="목표-아키텍처와-ocp-구성",
                source_url="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#목표-아키텍처와-ocp-구성",
                viewer_path="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#목표-아키텍처와-ocp-구성",
                text="OCP 네트워크 구성도와 Master, Infra, Router, Worker Node 구성을 설명한다.",
                source="hybrid_reranked",
                raw_score=8.0672,
                fused_score=8.0672,
                source_id="customer_pack:customer-master-kmsc-ocp-operations-playbook",
                source_lane="customer_pack",
                source_type="pptx",
                source_collection="uploaded",
                review_status="ready",
                semantic_role="reference",
                component_scores={"pre_rerank_fused_score": 0.037},
            ),
            RetrievalHit(
                chunk_id="official-security",
                book_slug="security",
                chapter="보안",
                section="클러스터 보안",
                anchor="cluster-security",
                source_url="https://docs.redhat.com/security",
                viewer_path="/docs/ocp/4.20/ko/security/index.html#cluster-security",
                text="OpenShift Container Platform 보안 구성 설명",
                source="hybrid_reranked",
                raw_score=0.106,
                fused_score=0.106,
                source_collection="core",
                component_scores={"pre_rerank_fused_score": 0.106},
            ),
            RetrievalHit(
                chunk_id="official-architecture",
                book_slug="architecture",
                chapter="아키텍처",
                section="OpenShift Container Platform의 아키텍처 개요",
                anchor="architecture-overview",
                source_url="https://docs.redhat.com/architecture",
                viewer_path="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
                text="OpenShift Container Platform 아키텍처 개요",
                source="hybrid_reranked",
                raw_score=0.102,
                fused_score=0.102,
                source_collection="core",
                component_scores={"pre_rerank_fused_score": 0.102},
            ),
        ]

        self.assertFalse(
            _should_force_clarification(
                hits,
                query=query,
                session_context=session_context,
            )
        )
        selected = _select_hits(
            hits,
            query=query,
            session_context=session_context,
            max_chunks=3,
        )

        self.assertTrue(selected)
        self.assertEqual("uploaded", selected[0].source_collection)
        self.assertEqual(
            "customer-master-kmsc-ocp-operations-playbook",
            selected[0].book_slug,
        )

    def test_customer_pack_content_summary_query_is_not_global_title_locator(self) -> None:
        query = "고객 문서 기준 CI/CD 운영 구조를 요약해줘"
        self.assertFalse(
            _is_customer_pack_title_locator_query(query)
        )
        self.assertFalse(
            _is_context_customer_pack_title_locator_query(query)
        )
        self.assertTrue(
            _is_customer_pack_title_locator_query(
                "KOMSCO 지급결제플랫폼 아키텍처 개선 사업 아키텍처 설계서를 찾아줘"
            )
        )
        official_hit = RetrievalHit(
            chunk_id="official-cicd",
            book_slug="security_and_compliance",
            chapter="빌드",
            section="빌드 프로세스 설계",
            anchor="security-build-designing",
            source_url="https://docs.redhat.com/security-build-designing",
            viewer_path="/docs/ocp/4.20/ko/security_and_compliance/index.html#security-build-designing",
            text="CI/CD 운영 구조에서 보안 스캔과 GitOps 배포 자동화를 설명한다.",
            source="hybrid_reranked",
            raw_score=0.12,
            fused_score=0.12,
            source_collection="core",
        )
        bundle = assemble_context(
            [official_hit],
            query=query,
            session_context=SessionContext(mode="chat", restrict_uploaded_sources=True),
            max_chunks=2,
        )
        self.assertFalse(bundle.citations)


if __name__ == "__main__":
    unittest.main()
