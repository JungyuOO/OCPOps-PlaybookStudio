from __future__ import annotations

import sys
import tempfile
import unittest
import json
from unittest.mock import Mock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.canonical.models import (
    AstProvenance,
    CanonicalDocumentAst,
    CanonicalSectionAst,
    FigureBlock,
    ParagraphBlock,
)
from play_book_studio.canonical.translate import (
    _TextUnit,
    _translation_still_needs_repair,
    _translate_single_unit,
    _translate_units,
    _translation_cache_path,
    repair_unlocalized_english_units,
)
from play_book_studio.canonical.project_playbook import project_playbook_document
from play_book_studio.ingestion.models import (
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    NormalizedSection,
    SourceManifestEntry,
)
from play_book_studio.ingestion.pipeline import (
    _entry_with_inferred_runtime_status,
    _maybe_translate_source_first_document,
    _write_jsonl,
    run_ingestion_pipeline,
)
from play_book_studio.ingestion.translation_draft_generation import _resolved_source_mirror_root


def _section(text: str) -> NormalizedSection:
    return NormalizedSection(
        book_slug="demo",
        book_title="데모",
        heading="개요",
        section_level=2,
        section_path=["개요"],
        anchor="overview",
        source_url="https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/demo/index",
        viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
        text=text,
    )


class IngestionPipelineStatusTests(unittest.TestCase):
    def test_inferred_approved_book_updates_approval_and_publication_state(self) -> None:
        entry = SourceManifestEntry(book_slug="demo", title="데모")

        inferred = _entry_with_inferred_runtime_status(
            entry,
            html="",
            sections=[_section("이 문서는 한국어 본문입니다.")],
        )

        self.assertEqual("approved_ko", inferred.content_status)
        self.assertEqual("approved", inferred.review_status)
        self.assertEqual("approved", inferred.approval_state)
        self.assertEqual("published", inferred.publication_state)
        self.assertTrue(inferred.citation_eligible)

    def test_inferred_english_only_book_sets_review_required_candidate_state(self) -> None:
        entry = SourceManifestEntry(book_slug="demo", title="Demo")

        inferred = _entry_with_inferred_runtime_status(
            entry,
            html="",
            sections=[_section("This document is written in English only.")],
        )

        self.assertEqual("en_only", inferred.content_status)
        self.assertEqual("needs_review", inferred.review_status)
        self.assertEqual("review_required", inferred.approval_state)
        self.assertEqual("candidate", inferred.publication_state)
        self.assertFalse(inferred.citation_eligible)

    def test_source_first_translated_draft_entry_runs_translation_step(self) -> None:
        document = CanonicalDocumentAst(
            doc_id="demo",
            book_slug="demo",
            title="Builds using BuildConfig",
            source_type="repo",
            source_url="https://docs.redhat.com/demo",
            viewer_base_path="/docs/ocp/4.20/ko/demo/index.html",
            source_language="en",
            display_language="ko",
            translation_status="original",
            pack_id="openshift-4-20-core",
            pack_label="OpenShift 4.20",
            inferred_product="openshift",
            inferred_version="4.20",
            sections=(
                CanonicalSectionAst(
                    section_id="overview",
                    ordinal=1,
                    heading="Understanding pipelines",
                    level=2,
                    path=("Understanding pipelines",),
                    anchor="overview",
                    source_url="https://docs.redhat.com/demo#overview",
                    viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
                    blocks=(ParagraphBlock("The Pipeline build strategy is deprecated."),),
                ),
            ),
            provenance=AstProvenance(),
        )
        translated = CanonicalDocumentAst(
            **{
                **document.to_dict(),
                "title": "BuildConfig를 사용한 빌드",
                "translation_status": "translated_ko_draft",
            }
        )
        entry = SourceManifestEntry(
            book_slug="demo",
            content_status=CONTENT_STATUS_TRANSLATED_KO_DRAFT,
        )

        with patch(
            "play_book_studio.ingestion.pipeline.translate_document_ast",
            Mock(return_value=translated),
        ) as translate_mock:
            result = _maybe_translate_source_first_document(document, Mock(), entry)

        translate_mock.assert_called_once()
        self.assertEqual("BuildConfig를 사용한 빌드", result.title)

    def test_source_first_non_translation_entry_runs_targeted_repair(self) -> None:
        document = Mock()
        repaired = Mock()
        entry = SourceManifestEntry(book_slug="demo", content_status="approved_ko")

        with patch("play_book_studio.ingestion.pipeline.translate_document_ast") as translate_mock, patch(
            "play_book_studio.ingestion.pipeline.repair_unlocalized_english_units",
            Mock(return_value=repaired),
        ) as repair_mock:
            result = _maybe_translate_source_first_document(document, Mock(), entry)

        translate_mock.assert_not_called()
        repair_mock.assert_called_once()
        self.assertIs(repaired, result)

    def test_stale_source_mirror_root_falls_back_to_current_workspace_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            current_mirror = root / "tmp_source" / "openshift-docs-enterprise-4.20"
            current_mirror.mkdir(parents=True)
            (current_mirror / "_attributes").mkdir()
            settings = Mock(root_dir=root)

            resolved = _resolved_source_mirror_root(
                settings,
                "C:/Users/soulu/cywell/ocp-play-studio/ocp-play-studio/tmp_source/openshift-docs-enterprise-4.20",
            )

            self.assertEqual(current_mirror, resolved)

    def test_pipeline_refuses_to_overwrite_artifacts_when_normalize_outputs_zero_sections(self) -> None:
        settings = Mock()
        settings.preprocessing_log_path.parent.mkdir.return_value = None
        settings.preprocessing_log_path.write_text.return_value = None
        entry = SourceManifestEntry(
            book_slug="missing",
            title="Missing",
            source_kind="source-first",
        )

        with patch(
            "play_book_studio.ingestion.pipeline.load_runtime_manifest_entries",
            return_value=[entry],
        ), patch("play_book_studio.ingestion.pipeline.hydrate_source_repo_artifacts"), patch(
            "play_book_studio.ingestion.pipeline._source_repo_runtime_entry",
            side_effect=ValueError("missing repo binding"),
        ), patch(
            "play_book_studio.ingestion.pipeline.collect_entry",
            side_effect=RuntimeError("fallback blocked"),
        ), patch(
            "play_book_studio.ingestion.pipeline._write_jsonl_targets",
        ) as write_jsonl_targets:
            with self.assertRaisesRegex(RuntimeError, "zero sections"):
                run_ingestion_pipeline(
                    settings,
                    collect_subset="all",
                    process_subset="all",
                    skip_embeddings=True,
                    skip_qdrant=True,
                )

        write_jsonl_targets.assert_not_called()

    def test_write_jsonl_uses_replaceable_temp_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "large.jsonl"

            _write_jsonl(path, [{"book_slug": "demo"}, {"book_slug": "next"}])

            self.assertEqual(
                ['{"book_slug": "demo"}', '{"book_slug": "next"}'],
                path.read_text(encoding="utf-8").splitlines(),
            )
            self.assertEqual([], list(Path(tmpdir).glob("*.tmp")))

    def test_single_unit_translation_repairs_malformed_json_response(self) -> None:
        client = Mock()
        client.max_tokens = 1024
        client.generate.side_effect = [
            '{"id":"s0.heading","text":"잘린 문자열',
            '{"id":"s0.heading","text":"설치 개요"}',
        ]

        translated = _translate_single_unit(
            client,
            _TextUnit(unit_id="s0.heading", text="Installation overview"),
        )

        self.assertEqual("설치 개요", translated)
        self.assertEqual(2, client.generate.call_count)

    def test_single_unit_translation_returns_original_after_connection_failures(self) -> None:
        client = Mock()
        client.max_tokens = 1024
        client.generate.side_effect = ConnectionResetError("reset by peer")

        translated = _translate_single_unit(
            client,
            _TextUnit(unit_id="s0.heading", text="Installation overview"),
        )

        self.assertEqual("Installation overview", translated)
        self.assertEqual(3, client.generate.call_count)

    def test_multi_batch_translation_uses_parallel_batch_fallback_worker(self) -> None:
        units = [
            _TextUnit(unit_id=f"u{i}", text=f"English paragraph number {i}.")
            for i in range(33)
        ]

        def fake_batch(_settings, batch):
            return {unit.unit_id: f"번역 {unit.unit_id}" for unit in batch}

        with patch(
            "play_book_studio.canonical.translate._translate_batch_with_fallback",
            side_effect=fake_batch,
        ) as batch_mock, patch(
            "play_book_studio.canonical.translate._translate_unit_batch",
            side_effect=AssertionError("sequential batch path should not run"),
        ):
            translated = _translate_units(
                Mock(),
                units,
                settings=Mock(),
            )

        self.assertEqual(2, batch_mock.call_count)
        self.assertEqual("번역 u32", translated["u32"])

    def test_translation_repairs_batch_output_that_still_contains_english_prose(self) -> None:
        unit = _TextUnit(
            unit_id="s0.b0.paragraph",
            text="It is still supported, but the installer displays a warning message.",
        )
        fake_client = Mock(max_tokens=1024)

        with patch(
            "play_book_studio.canonical.translate._translate_unit_batch",
            return_value={unit.unit_id: unit.text},
        ), patch(
            "play_book_studio.canonical.translate._translate_single_unit_strict",
            return_value="계속 지원되지만 설치 프로그램은 경고 메시지를 표시합니다.",
        ) as strict_mock:
            translated = _translate_units(fake_client, [unit])

        self.assertEqual(
            "계속 지원되지만 설치 프로그램은 경고 메시지를 표시합니다.",
            translated[unit.unit_id],
        )
        strict_mock.assert_called_once()
        self.assertFalse(_translation_still_needs_repair(unit, translated[unit.unit_id]))

    def test_translation_uses_deterministic_override_for_known_figure_caption_leaks(self) -> None:
        unit = _TextUnit(
            unit_id="s0.b0.figure.caption",
            text="Istio Control Plane Dashboard showing data for bookinfo sample project",
        )
        fake_client = Mock(max_tokens=1024)

        with patch(
            "play_book_studio.canonical.translate._translate_unit_batch",
            return_value={unit.unit_id: unit.text},
        ), patch(
            "play_book_studio.canonical.translate._translate_single_unit_strict",
            side_effect=AssertionError("deterministic caption override should run first"),
        ):
            translated = _translate_units(fake_client, [unit])

        self.assertEqual(
            "bookinfo 샘플 프로젝트의 데이터를 보여주는 Istio Control Plane 대시보드",
            translated[unit.unit_id],
        )

    def test_playbook_projection_normalizes_short_official_labels(self) -> None:
        document = CanonicalDocumentAst(
            doc_id="demo",
            book_slug="demo",
            title="Builds using BuildConfig",
            source_type="repo",
            source_url="https://docs.redhat.com/demo",
            viewer_base_path="/docs/ocp/4.20/ko/demo/index.html",
            source_language="en",
            display_language="ko",
            translation_status="translated_ko_draft",
            pack_id="openshift-4-20-core",
            pack_label="OpenShift 4.20",
            inferred_product="openshift",
            inferred_version="4.20",
            sections=(
                CanonicalSectionAst(
                    section_id="overview",
                    ordinal=1,
                    heading="개요",
                    level=2,
                    path=("개요",),
                    anchor="overview",
                    source_url="https://docs.redhat.com/demo#overview",
                    viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
                    blocks=(
                        ParagraphBlock("Builds for OpenShift Container Platform"),
                        ParagraphBlock("Tip"),
                    ),
                ),
            ),
            provenance=AstProvenance(source_fingerprint="fingerprint-labels"),
        )

        projected = project_playbook_document(document).to_dict()
        blocks = projected["sections"][0]["blocks"]

        self.assertEqual("OpenShift Container Platform 빌드", blocks[0]["text"])
        self.assertEqual("팁", blocks[1]["text"])

    def test_targeted_english_repair_preserves_existing_full_translation_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = Mock(silver_ko_dir=root / "data" / "silver_ko")
            document = CanonicalDocumentAst(
                doc_id="demo",
                book_slug="demo",
                title="데모",
                source_type="repo",
                source_url="https://docs.redhat.com/demo",
                viewer_base_path="/docs/ocp/4.20/ko/demo/index.html",
                source_language="en",
                display_language="ko",
                translation_status="translated_ko_draft",
                pack_id="openshift-4-20-core",
                pack_label="OpenShift 4.20",
                inferred_product="openshift",
                inferred_version="4.20",
                sections=(
                    CanonicalSectionAst(
                        section_id="overview",
                        ordinal=1,
                        heading="개요",
                        level=2,
                        path=("개요",),
                        anchor="overview",
                        source_url="https://docs.redhat.com/demo#overview",
                        viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
                        blocks=(
                            ParagraphBlock("이미 번역된 본문입니다."),
                            ParagraphBlock(
                                "This installation procedure explains how administrators configure clusters before production rollout."
                            ),
                        ),
                    ),
                ),
                provenance=AstProvenance(source_fingerprint="fingerprint-targeted-cache"),
            )
            cache_path = _translation_cache_path(document, settings)
            assert cache_path is not None
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "book_slug": "demo",
                        "doc_id": "demo",
                        "source_fingerprint": "fingerprint-targeted-cache",
                        "item_count": 2,
                        "items": {
                            "s0.b0.paragraph": "캐시에 있던 기존 번역",
                            "doc.title": "데모",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            fake_client = Mock()
            fake_client.max_tokens = 1024
            fake_client.generate.return_value = json.dumps(
                {
                    "items": [
                        {
                            "id": "s0.b1.paragraph",
                            "text": "보수된 한국어 본문입니다.",
                        }
                    ]
                },
                ensure_ascii=False,
            )

            with patch(
                "play_book_studio.canonical.translate.LLMClient",
                Mock(return_value=fake_client),
            ):
                repaired = repair_unlocalized_english_units(document, settings)

            self.assertIn("보수된 한국어", repaired.sections[0].blocks[1].text)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual("캐시에 있던 기존 번역", payload["items"]["s0.b0.paragraph"])
            self.assertEqual("보수된 한국어 본문입니다.", payload["items"]["s0.b1.paragraph"])

    def test_targeted_english_repair_rejects_stale_english_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = Mock(silver_ko_dir=root / "data" / "silver_ko")
            document = CanonicalDocumentAst(
                doc_id="demo",
                book_slug="demo",
                title="데모",
                source_type="repo",
                source_url="https://docs.redhat.com/demo",
                viewer_base_path="/docs/ocp/4.20/ko/demo/index.html",
                source_language="en",
                display_language="ko",
                translation_status="translated_ko_draft",
                pack_id="openshift-4-20-core",
                pack_label="OpenShift 4.20",
                inferred_product="openshift",
                inferred_version="4.20",
                sections=(
                    CanonicalSectionAst(
                        section_id="overview",
                        ordinal=1,
                        heading="개요",
                        level=2,
                        path=("개요",),
                        anchor="overview",
                        source_url="https://docs.redhat.com/demo#overview",
                        viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
                        blocks=(
                            ParagraphBlock(
                                "This installation procedure explains how administrators configure clusters before production rollout."
                            ),
                        ),
                    ),
                ),
                provenance=AstProvenance(source_fingerprint="fingerprint-stale-cache"),
            )
            cache_path = _translation_cache_path(document, settings)
            assert cache_path is not None
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "book_slug": "demo",
                        "doc_id": "demo",
                        "source_fingerprint": "fingerprint-stale-cache",
                        "item_count": 1,
                        "items": {
                            "s0.b0.paragraph": "This installation procedure explains how administrators configure clusters before production rollout.",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            fake_client = Mock()
            fake_client.max_tokens = 1024
            fake_client.generate.return_value = json.dumps(
                {
                    "items": [
                        {
                            "id": "s0.b0.paragraph",
                            "text": "이 설치 절차는 운영자가 운영 배포 전에 클러스터를 구성하는 방법을 설명합니다.",
                        }
                    ]
                },
                ensure_ascii=False,
            )

            with patch(
                "play_book_studio.canonical.translate.LLMClient",
                Mock(return_value=fake_client),
            ):
                repaired = repair_unlocalized_english_units(document, settings)

            self.assertIn("클러스터", repaired.sections[0].blocks[0].text)
            self.assertEqual(1, fake_client.generate.call_count)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "이 설치 절차는 운영자가 운영 배포 전에 클러스터를 구성하는 방법을 설명합니다.",
                payload["items"]["s0.b0.paragraph"],
            )

    def test_translation_includes_figure_caption_and_alt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = Mock(silver_ko_dir=root / "data" / "silver_ko")
            document = CanonicalDocumentAst(
                doc_id="demo",
                book_slug="demo",
                title="데모",
                source_type="repo",
                source_url="https://docs.redhat.com/demo",
                viewer_base_path="/docs/ocp/4.20/ko/demo/index.html",
                source_language="en",
                display_language="ko",
                translation_status="translated_ko_draft",
                pack_id="openshift-4-20-core",
                pack_label="OpenShift 4.20",
                inferred_product="openshift",
                inferred_version="4.20",
                sections=(
                    CanonicalSectionAst(
                        section_id="overview",
                        ordinal=1,
                        heading="개요",
                        level=2,
                        path=("개요",),
                        anchor="overview",
                        source_url="https://docs.redhat.com/demo#overview",
                        viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
                        blocks=(
                            FigureBlock(
                                src="/playbooks/wiki-assets/full_rebuild/demo/network.png",
                                caption=(
                                    "An image that shows an example network workflow of an "
                                    "Ingress Controller operating in an OpenShift Container Platform environment."
                                ),
                                alt=(
                                    "An image that shows an example network workflow of an "
                                    "Ingress Controller operating in an OpenShift Container Platform environment."
                                ),
                                asset_ref="network.png",
                            ),
                        ),
                    ),
                ),
                provenance=AstProvenance(source_fingerprint="fingerprint-figure-cache"),
            )
            fake_client = Mock()
            fake_client.max_tokens = 1024
            fake_client.generate.return_value = json.dumps(
                {
                    "items": [
                        {
                            "id": "s0.b0.figure.caption",
                            "text": "예제 네트워크 워크플로를 보여주는 이미지입니다.",
                        },
                        {
                            "id": "s0.b0.figure.alt",
                            "text": "예제 네트워크 워크플로를 보여주는 이미지입니다.",
                        },
                    ]
                },
                ensure_ascii=False,
            )

            with patch(
                "play_book_studio.canonical.translate.LLMClient",
                Mock(return_value=fake_client),
            ):
                repaired = repair_unlocalized_english_units(document, settings)

            figure = repaired.sections[0].blocks[0]
            self.assertEqual("예제 네트워크 워크플로를 보여주는 이미지입니다.", figure.caption)
            self.assertEqual("예제 네트워크 워크플로를 보여주는 이미지입니다.", figure.alt)


if __name__ == "__main__":
    unittest.main()
