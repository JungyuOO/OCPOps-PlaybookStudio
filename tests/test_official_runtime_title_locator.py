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
from play_book_studio.answering.context import assemble_context
from play_book_studio.answering.answerer import _build_doc_locator_answer, _citations_match_rbac_intent
from play_book_studio.answering.models import Citation
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever


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
