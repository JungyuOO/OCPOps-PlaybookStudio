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

from play_book_studio.config.settings import load_settings
from play_book_studio.answering.context import (
    _is_customer_pack_explicit_query as answer_context_customer_pack_explicit,
    assemble_context,
)
from play_book_studio.answering.answerer import _build_doc_locator_answer, _citations_match_rbac_intent
from play_book_studio.answering.models import Citation
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever
from play_book_studio.retrieval.retriever_pipeline import (
    _is_customer_pack_explicit_query as retrieval_pipeline_customer_pack_explicit,
)
from play_book_studio.retrieval.retriever_search import (
    _is_customer_pack_explicit_query as retrieval_search_customer_pack_explicit,
    _official_title_match_score,
)


def _write_active_manifest(root: Path, entries: list[dict[str, str]]) -> None:
    manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _official_doc_row(
    *,
    chunk_id: str,
    book_slug: str,
    section: str,
    text: str,
    review_status: str = "approved",
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
        "review_status": review_status,
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


class OfficialRuntimeTitleLocatorTests(unittest.TestCase):
    def test_ocp_topic_signal_routes_decisive_buildconfig_title_token(self) -> None:
        score = _official_title_match_score(
            "OCP 4.20에서 BuildConfig 운영자가 먼저 확인할 점과 예시 명령을 알려줘",
            title_candidates=("Builds using BuildConfig",),
        )

        self.assertGreater(score, 0.0)

    def test_customer_broad_phrase_counts_as_uploaded_runtime_query(self) -> None:
        query = "고객 CI/CD 운영 자료와 OCP 4.20 BuildConfig 공식문서를 같이 참고해줘"

        self.assertTrue(retrieval_search_customer_pack_explicit(query))
        self.assertTrue(retrieval_pipeline_customer_pack_explicit(query))
        self.assertTrue(answer_context_customer_pack_explicit(query))

    def test_exact_korean_official_title_seeds_matching_api_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_active_manifest(
                root,
                [
                    {"slug": "authorization_apis", "title": "권한 부여 API"},
                    {"slug": "authentication_and_authorization", "title": "인증 및 권한 부여"},
                ],
            )
            rows = [
                _official_doc_row(
                    chunk_id="authn-authz-general",
                    book_slug="authentication_and_authorization",
                    section="RBAC 개요",
                    text="인증 및 권한 부여는 RBAC, 역할, 권한, 사용자 액세스를 설명합니다.",
                ),
                _official_doc_row(
                    chunk_id="selfsubjectrulesreview",
                    book_slug="authorization_apis",
                    section="SelfSubjectRulesReview",
                    text=(
                        "권한 부여 API SelfSubjectRulesReview는 사용자가 네임스페이스에서 "
                        "수행할 수 있는 작업 규칙을 검토하는 API 오브젝트입니다."
                    ),
                ),
            ]
            settings = load_settings(root)
            retriever = ChatRetriever(settings, BM25Index.from_rows(rows), vector_retriever=None)

            result = retriever.retrieve(
                "권한 부여 API에서 SelfSubjectRulesReview가 무엇인지 공식문서 기준으로 설명해줘",
                context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                top_k=3,
                candidate_k=5,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            self.assertEqual("authorization_apis", result.hits[0].book_slug)

            bundle = assemble_context(
                result.hits,
                query="권한 부여 API에서 SelfSubjectRulesReview가 무엇인지 공식문서 기준으로 설명해줘",
                session_context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                max_chunks=3,
            )

            self.assertTrue(bundle.citations)
            self.assertEqual("authorization_apis", bundle.citations[0].book_slug)

    def test_english_official_title_beats_generic_iam_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_active_manifest(
                root,
                [
                    {"slug": "installing_on_aws", "title": "Installing on AWS"},
                    {"slug": "hosted_control_planes", "title": "Hosted control planes"},
                ],
            )
            rows = [
                _official_doc_row(
                    chunk_id="hcp-iam",
                    book_slug="hosted_control_planes",
                    section="AWS IAM 권한",
                    text=(
                        "Hosted control planes의 AWS IAM 권한 요구사항과 역할 정책을 "
                        "요약합니다. IAM 권한 권한 권한"
                    ),
                ),
                _official_doc_row(
                    chunk_id="aws-iam",
                    book_slug="installing_on_aws",
                    section="Required AWS permissions",
                    text=(
                        "Installing on AWS 공식 매뉴얼은 클러스터 설치 전 필요한 IAM "
                        "역할, 정책, 권한 요구사항을 설명합니다."
                    ),
                    review_status="needs_review",
                ),
            ]
            settings = load_settings(root)
            retriever = ChatRetriever(settings, BM25Index.from_rows(rows), vector_retriever=None)

            result = retriever.retrieve(
                "Installing on AWS 공식 매뉴얼에서 IAM 권한 요구사항을 요약해줘",
                context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                top_k=3,
                candidate_k=5,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            self.assertEqual("installing_on_aws", result.hits[0].book_slug)

    def test_decisive_title_token_routes_buildconfig_queries_to_buildconfig_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_active_manifest(
                root,
                [
                    {"slug": "building_applications", "title": "애플리케이션 빌드"},
                    {"slug": "builds_using_buildconfig", "title": "Builds using BuildConfig"},
                ],
            )
            rows = [
                _official_doc_row(
                    chunk_id="building-applications",
                    book_slug="building_applications",
                    section="빌드 개요",
                    text="애플리케이션 빌드는 소스 코드와 이미지를 빌드하는 일반적인 흐름을 설명합니다.",
                ),
                _official_doc_row(
                    chunk_id="buildconfig-overview",
                    book_slug="builds_using_buildconfig",
                    section="BuildConfig",
                    text=(
                        "Builds using BuildConfig 문서는 BuildConfig가 빌드 전략, 입력, "
                        "출력, 트리거를 정의하는 Kubernetes API 리소스라고 설명합니다."
                    ),
                    review_status="needs_review",
                ),
            ]
            settings = load_settings(root)
            retriever = ChatRetriever(settings, BM25Index.from_rows(rows), vector_retriever=None)

            result = retriever.retrieve(
                "공식문서 기준 애플리케이션 빌드에서 BuildConfig가 어떤 역할인지 요약해줘",
                context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                top_k=3,
                candidate_k=5,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            self.assertEqual("builds_using_buildconfig", result.hits[0].book_slug)

    def test_decisive_title_token_routes_buildconfig_followup_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_active_manifest(
                root,
                [
                    {"slug": "building_applications", "title": "애플리케이션 빌드"},
                    {"slug": "builds_using_buildconfig", "title": "Builds using BuildConfig"},
                ],
            )
            rows = [
                _official_doc_row(
                    chunk_id="building-applications",
                    book_slug="building_applications",
                    section="빌드 상태",
                    text="애플리케이션 빌드 상태를 일반적으로 확인합니다.",
                ),
                _official_doc_row(
                    chunk_id="buildconfig-verify",
                    book_slug="builds_using_buildconfig",
                    section="BuildConfig 검증",
                    text=(
                        "BuildConfig 적용 후 build 상태, pod 상태, 이벤트, 로그를 확인하여 "
                        "빌드 결과를 검증합니다."
                    ),
                    review_status="needs_review",
                ),
            ]
            settings = load_settings(root)
            retriever = ChatRetriever(settings, BM25Index.from_rows(rows), vector_retriever=None)

            result = retriever.retrieve(
                "BuildConfig 적용 후 build와 pod 상태를 검증하는 순서를 알려줘",
                context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                top_k=3,
                candidate_k=5,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            self.assertEqual("builds_using_buildconfig", result.hits[0].book_slug)

    def test_buildconfig_followup_context_keeps_citation_when_hits_are_close(self) -> None:
        query = "BuildConfig 적용 후 build와 pod 상태를 검증하는 순서를 알려줘"
        hits = [
            RetrievalHit(
                chunk_id="workload-status",
                book_slug="workloads_apis",
                chapter="BuildConfig API",
                section=".status.imageChangeTriggers[]",
                anchor="status-image-change-triggers",
                source_url="https://docs.redhat.com/workloads_apis",
                viewer_path="/docs/ocp/4.20/ko/workloads_apis/index.html#status-image-change-triggers",
                text="BuildConfig status image triggers and build status reference.",
                source="hybrid_reranked",
                raw_score=0.0164,
                component_scores={"pre_rerank_fused_score": 0.2069},
            ),
            RetrievalHit(
                chunk_id="buildconfig-edit",
                book_slug="builds_using_buildconfig",
                chapter="BuildConfig",
                section="Editing a BuildConfig",
                anchor="editing-a-buildconfig",
                source_url="https://docs.redhat.com/builds_using_buildconfig",
                viewer_path="/docs/ocp/4.20/ko/builds_using_buildconfig/index.html#editing-a-buildconfig",
                text="BuildConfig 적용 후 build 상태, pod 상태, 이벤트, 로그를 확인하여 빌드 결과를 검증합니다.",
                source="hybrid_reranked",
                raw_score=0.0161,
                chunk_type="command",
                semantic_role="procedure",
                cli_commands=("oc describe bc <name>",),
                verification_hints=("oc describe bc <name>",),
                component_scores={"pre_rerank_fused_score": 0.2067},
            ),
        ]

        bundle = assemble_context(
            hits,
            query=query,
            session_context=SessionContext(mode="chat", ocp_version="4.20"),
            max_chunks=3,
        )

        self.assertTrue(bundle.citations)
        self.assertEqual("builds_using_buildconfig", bundle.citations[0].book_slug)

    def test_official_basis_operational_query_is_not_doc_locator_answer(self) -> None:
        citation = Citation(
            index=1,
            chunk_id="buildconfig",
            book_slug="builds_using_buildconfig",
            section="BuildConfig 운영",
            anchor="buildconfig",
            source_url="https://docs.redhat.com/builds_using_buildconfig",
            viewer_path="/docs/ocp/4.20/ko/builds_using_buildconfig/index.html#buildconfig",
            excerpt="BuildConfig 점검 절차",
        )

        self.assertIsNone(
            _build_doc_locator_answer(
                query="OpenShift 4.20 공식문서 기준 BuildConfig 운영자가 점검해야 할 순서를 알려줘",
                citations=[citation],
            )
        )

    def test_exact_virtualization_title_beats_generic_migration_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_active_manifest(
                root,
                [
                    {"slug": "virtualization", "title": "Virtualization"},
                    {
                        "slug": "migration_toolkit_for_containers",
                        "title": "Migration Toolkit for Containers",
                    },
                ],
            )
            rows = [
                _official_doc_row(
                    chunk_id="mtc-live-migration",
                    book_slug="migration_toolkit_for_containers",
                    section="Migration plan",
                    text="Migration Toolkit for Containers에서 migration plan과 live migration 유사 용어를 설명합니다.",
                ),
                _official_doc_row(
                    chunk_id="virt-live-migration",
                    book_slug="virtualization",
                    section="Live migration",
                    text="Virtualization 공식 매뉴얼은 가상 머신의 live migration 동작과 운영 조건을 설명합니다.",
                    review_status="needs_review",
                ),
            ]
            settings = load_settings(root)
            retriever = ChatRetriever(settings, BM25Index.from_rows(rows), vector_retriever=None)

            result = retriever.retrieve(
                "Virtualization 공식 매뉴얼에서 live migration 관련 핵심을 설명해줘",
                context=SessionContext(mode="chat", ocp_version=settings.ocp_version),
                top_k=3,
                candidate_k=5,
                use_vector=False,
            )

            self.assertTrue(result.hits)
            self.assertEqual("virtualization", result.hits[0].book_slug)

    def test_iam_permission_citation_satisfies_permission_grounding(self) -> None:
        citation = Citation(
            index=1,
            chunk_id="aws-iam",
            book_slug="installing_on_aws",
            section="Required AWS permissions for the IAM user",
            anchor="required-aws-permissions",
            source_url="https://docs.redhat.com/installing_on_aws",
            viewer_path="/docs/ocp/4.20/ko/installing_on_aws/index.html#required-aws-permissions",
            excerpt="Required AWS permissions for the IAM user",
        )

        self.assertTrue(_citations_match_rbac_intent([citation]))


if __name__ == "__main__":
    unittest.main()
