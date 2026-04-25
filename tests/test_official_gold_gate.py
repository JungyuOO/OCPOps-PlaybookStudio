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

from play_book_studio.app.server_routes_viewer import resolve_viewer_html
from play_book_studio.canonical.asciidoc import build_source_repo_document_ast
from play_book_studio.canonical.html import _blocks_from_text
from play_book_studio.canonical.models import FigureBlock
from play_book_studio.ingestion.models import SourceManifestEntry
from play_book_studio.ingestion.official_gold_gate import (
    _portable_path_findings,
    publish_runtime_manifest_from_playbooks,
    repair_portable_json_paths,
)
from play_book_studio.ingestion.localization_quality import build_official_ko_localization_audit


class OfficialGoldGateTests(unittest.TestCase):
    def test_canonical_text_parser_preserves_figure_blocks(self) -> None:
        blocks = _blocks_from_text(
            '[FIGURE src="/playbooks/wiki-assets/full_rebuild/demo/diagram.png" '
            'asset_ref="diagram.png" alt="Demo"]\nDemo caption\n[/FIGURE]'
        )

        self.assertEqual(1, len(blocks))
        self.assertIsInstance(blocks[0], FigureBlock)
        self.assertEqual("figure", blocks[0].kind)
        self.assertEqual("Demo caption", blocks[0].caption)
        self.assertEqual("/playbooks/wiki-assets/full_rebuild/demo/diagram.png", blocks[0].src)

    def test_source_repo_asciidoc_preserves_image_as_figure_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mirror_root = root / "tmp_source" / "openshift-docs-enterprise-4.20"
            source_path = mirror_root / "demo" / "index.adoc"
            image_path = mirror_root / "images" / "demo.png"
            source_path.parent.mkdir(parents=True)
            image_path.parent.mkdir(parents=True)
            source_path.write_text(
                "= Demo Book\n\n"
                "== Overview\n\n"
                "image::demo.png[Demo figure]\n\n"
                "본문\n",
                encoding="utf-8",
            )
            image_path.write_bytes(b"png-bytes")
            (mirror_root / "_attributes").mkdir()
            entry = SourceManifestEntry(
                book_slug="demo",
                title="Demo Book",
                source_kind="source-first",
                viewer_path="/docs/ocp/4.20/ko/demo/index.html",
            )

            document = build_source_repo_document_ast(
                entry=entry,
                source_paths=[source_path],
                fallback_title="Demo Book",
            )

            figures = [
                block
                for section in document.sections
                for block in section.blocks
                if isinstance(block, FigureBlock)
            ]
            self.assertEqual(1, len(figures))
            self.assertEqual("Demo figure", figures[0].caption)
            self.assertEqual("/playbooks/wiki-assets/full_rebuild/demo/demo.png", figures[0].src)
            self.assertTrue((root / "data" / "wiki_assets" / "full_rebuild" / "demo" / "demo.png").exists())

    def test_direct_viewer_url_query_controls_page_mode(self) -> None:
        html = resolve_viewer_html(
            ROOT,
            "/playbooks/wiki-runtime/active/advanced_networking/index.html?page_mode=multi",
        )

        self.assertIsNotNone(html)
        self.assertGreater(str(html).count("section-card"), 1)

    def test_portable_path_repair_rewrites_known_old_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            active_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            full_path = root / "data" / "wiki_runtime_books" / "full_rebuild_manifest.json"
            source_path = root / "manifests" / "ocp420_source_first_full_rebuild_manifest.json"
            figure_path = root / "data" / "wiki_relations" / "figure_assets.json"
            for path in (active_path, full_path, source_path, figure_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "source_manifest_path": (
                                "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                "data\\wiki_runtime_books\\full_rebuild_manifest.json"
                            ),
                            "entries": [
                                {
                                    "runtime_path": (
                                        "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                        "data\\wiki_runtime_books\\full_rebuild\\demo.md"
                                    ),
                                    "source_file": (
                                        "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                        "tmp_source\\openshift-docs-enterprise-4.20\\modules\\demo.adoc"
                                    ),
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            repair_portable_json_paths(root)
            findings = _portable_path_findings(root)

            self.assertEqual("ok", findings["status"])
            repaired = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertEqual("data/wiki_runtime_books/full_rebuild_manifest.json", repaired["source_manifest_path"])
            self.assertEqual("data/wiki_runtime_books/full_rebuild/demo.md", repaired["entries"][0]["runtime_path"])
            self.assertEqual(
                "tmp_source/openshift-docs-enterprise-4.20/modules/demo.adoc",
                repaired["entries"][0]["source_file"],
            )

    def test_publish_runtime_manifest_from_playbooks_uses_full_playbook_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            playbooks_path = root / "data" / "gold_manualbook_ko" / "playbook_documents.jsonl"
            source_manifest_path = root / "manifests" / "ocp_ko_4_20_html_single.json"
            playbooks_path.parent.mkdir(parents=True, exist_ok=True)
            source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "book_slug": "authorization_apis",
                    "title": "권한 부여 API",
                    "source_uri": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/authorization_apis/index",
                    "translation_status": "approved_ko",
                    "translation_stage": "approved_ko",
                    "review_status": "approved",
                    "quality_status": "ready",
                    "sections": [],
                    "source_metadata": {
                        "source_lane": "official_ko",
                        "source_type": "official_doc",
                        "approval_state": "approved",
                        "publication_state": "published",
                        "citation_eligible": True,
                    },
                },
                {
                    "book_slug": "pipelines",
                    "title": "파이프라인",
                    "source_uri": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/pipelines/index",
                    "translation_status": "original",
                    "translation_stage": "original",
                    "review_status": "needs_review",
                    "quality_status": "translation_required",
                    "sections": [],
                    "source_metadata": {
                        "source_lane": "official_en_fallback",
                        "source_type": "official_doc",
                        "approval_state": "review_required",
                        "publication_state": "candidate",
                    },
                },
            ]
            playbooks_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": row["book_slug"],
                                "title": row["title"],
                                "source_url": row["source_uri"],
                                "viewer_path": f"/docs/ocp/4.20/ko/{row['book_slug']}/index.html",
                                "source_fingerprint": row["book_slug"],
                            }
                            for row in rows
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = publish_runtime_manifest_from_playbooks(
                root,
                source_manifest_path=source_manifest_path,
            )

            self.assertEqual(2, report["runtime_count"])
            active = json.loads((root / "data" / "wiki_runtime_books" / "active_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(2, active["runtime_count"])
            self.assertEqual(
                ["authorization_apis", "pipelines"],
                [entry["slug"] for entry in active["entries"]],
            )
            self.assertEqual(
                "data/wiki_runtime_books/full_rebuild/pipelines.md",
                active["entries"][1]["runtime_path"],
            )
            self.assertEqual(
                "data/wiki_runtime_books/full_rebuild_manifest.json",
                active["source_manifest_path"],
            )

    def test_ko_localization_audit_fails_untranslated_english_prose(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "builds_using_buildconfig",
                    "title": "Builds using BuildConfig",
                    "translation_status": "original",
                    "sections": [
                        {
                            "heading": "Understanding OpenShift Container Platform pipelines",
                            "blocks": [
                                {
                                    "kind": "paragraph",
                                    "text": (
                                        "The Pipeline build strategy is deprecated in "
                                        "OpenShift Container Platform 4."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("fail", audit["status"])
        self.assertEqual(1, audit["failing_book_count"])
        self.assertEqual("builds_using_buildconfig", audit["examples"][0]["book_slug"])

    def test_ko_localization_audit_allows_commands_urls_and_product_terms(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "cli_tools",
                    "title": "CLI 툴",
                    "translation_status": "approved_ko",
                    "sections": [
                        {
                            "heading": "OpenShift CLI 사용",
                            "blocks": [
                                {"kind": "paragraph", "text": "다음 명령으로 BuildConfig 상태를 확인합니다."},
                                {"kind": "code", "code": "oc get buildconfig example -o yaml"},
                                {
                                    "kind": "paragraph",
                                    "text": "https://docs.redhat.com/en/documentation/openshift_container_platform",
                                },
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("ok", audit["status"])
        self.assertEqual(0, audit["failing_book_count"])

    def test_ko_localization_audit_fails_short_english_body_sentences(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "builds_using_buildconfig",
                    "title": "BuildConfig를 사용한 빌드",
                    "translation_status": "translated_ko_draft",
                    "sections": [
                        {
                            "heading": "빌드",
                            "blocks": [
                                {
                                    "kind": "paragraph",
                                    "text": "A `BuildConfig` object is the definition of the entire build process.",
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("fail", audit["status"])
        self.assertEqual(1, audit["failing_book_count"])

    def test_ko_localization_audit_fails_cyrillic_translation_contamination(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "builds_using_buildconfig",
                    "title": "BuildConfig를 사용한 빌드",
                    "translation_status": "translated_ko_draft",
                    "sections": [
                        {
                            "heading": "증분 빌드",
                            "blocks": [
                                {
                                    "kind": "paragraph",
                                    "text": "S2I는 이전에 빌드된 артефакt를 재사용합니다.",
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("fail", audit["status"])
        self.assertEqual("cyrillic_translation_contamination", audit["examples"][0]["findings"][0]["reason"])

    def test_ko_localization_audit_allows_api_field_paths_and_yaml_snippets(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "operator_apis",
                    "title": "Operator API",
                    "translation_status": "translated_ko_draft",
                    "sections": [
                        {
                            "heading": (
                                "5.1.28. "
                                ".spec.customization.perspectives[].visibility.accessReview.missing[].fieldSelector"
                            ),
                            "blocks": [
                                {
                                    "kind": "paragraph",
                                    "text": (
                                        "matches: - method: service: foo.bar "
                                        "headers: values: version: 2"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("ok", audit["status"])
        self.assertEqual(0, audit["failing_book_count"])

    def test_ko_localization_audit_allows_product_and_numeric_table_fragments(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "storage",
                    "title": "스토리지",
                    "translation_status": "translated_ko_draft",
                    "sections": [
                        {
                            "heading": "지원되는 스토리지",
                            "blocks": [
                                {"kind": "paragraph", "text": "GCP PD(Google Compute Engine Persistent Disk)"},
                                {
                                    "kind": "paragraph",
                                    "text": "60 pods per node; 30 server pods and 30 client pods (total 30k)",
                                },
                                {
                                    "kind": "paragraph",
                                    "text": "NBDE(Network-bound Disk Encryption) Tang Server Operator",
                                },
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("ok", audit["status"])
        self.assertEqual(0, audit["failing_book_count"])

    def test_ko_localization_audit_allows_korean_sentence_with_ui_option_labels(self) -> None:
        audit = build_official_ko_localization_audit(
            [
                {
                    "book_slug": "building_applications",
                    "title": "애플리케이션 빌드",
                    "translation_status": "translated_ko_draft",
                    "sections": [
                        {
                            "heading": "서비스 추가",
                            "blocks": [
                                {
                                    "kind": "paragraph",
                                    "text": (
                                        "애플리케이션에 추가 를 사용하여 애플리케이션 그룹에 서비스를 "
                                        "추가하는 방법을 선택합니다(예: From Git, Container Image, "
                                        "From Dockerfile, From Devfile, Upload JAR file, Event Source, "
                                        "Channel, 또는 Broker)."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual("ok", audit["status"])
        self.assertEqual(0, audit["failing_book_count"])


if __name__ == "__main__":
    unittest.main()
