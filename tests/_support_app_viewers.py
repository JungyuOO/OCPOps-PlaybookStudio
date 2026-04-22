from __future__ import annotations

import json
import os
import tempfile
import sys
import unittest
from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from _support_app_ui import (
    Citation,
    _citation,
    _internal_viewer_html,
    _serialize_citation,
    _viewer_path_to_local_html,
)
from play_book_studio.app.server_routes import (
    _build_viewer_document_payload,
    _canonicalize_viewer_path,
    handle_source_meta,
    handle_viewer_document,
    _viewer_source_meta,
)
import play_book_studio.app.presenters as presenters_module
from play_book_studio.app.presenters import _build_citation_presentation_context
from play_book_studio.app.viewer_page import _render_study_viewer_html
from play_book_studio.config.settings import load_settings


class AppViewersTestSupport(unittest.TestCase):
    def _capture_json_response(self) -> object:
        class _CaptureHandler:
            def __init__(self) -> None:
                self.calls: list[tuple[HTTPStatus, dict[str, object]]] = []

            def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
                self.calls.append((status, payload))

        return _CaptureHandler()

    @contextmanager
    def _workspace(self, *, env_text: str | None = None) -> Iterator[Path]:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            if env_text is not None:
                (root / ".env").write_text(env_text, encoding="utf-8")
            yield root

    def _settings(self, root: Path):
        return load_settings(root)

    def _playbook_dir(self, root: Path) -> Path:
        playbook_dir = self._settings(root).playbook_books_dir
        playbook_dir.mkdir(parents=True, exist_ok=True)
        return playbook_dir

    @contextmanager
    def _patched_env(self, *, removed: tuple[str, ...] = (), **updates: str) -> Iterator[None]:
        patched_env = dict(os.environ)
        for key in removed:
            patched_env.pop(key, None)
        patched_env.update(updates)
        with patch.dict(os.environ, patched_env, clear=True):
            yield

    def test_viewer_document_payload_preserves_body_and_normalizes_assets(self) -> None:
        payload = _build_viewer_document_payload(
            """
            <html>
              <head>
                <style>:root { --bg: #fff; } body.is-embedded main { padding: 0; } .section-body p { margin: 0; }</style>
                <script>window.bad = true;</script>
              </head>
              <body class="doc-body">
                <main>
                  <img src="./images/hero.png" />
                  <a href="./guide/next.html">next</a>
                  <a href="#section-1">anchor</a>
                </main>
              </body>
            </html>
            """,
            "/playbooks/wiki-runtime/active/release_notes/index.html",
        )

        self.assertEqual("doc-body", payload["body_class_name"])
        self.assertEqual(1, len(payload["inline_styles"]))
        self.assertIn(".viewer-root", payload["inline_styles"][0])
        self.assertIn(".section-body p", payload["inline_styles"][0])
        self.assertNotIn(".section-.viewer-root p", payload["inline_styles"][0])
        self.assertIn('/playbooks/wiki-runtime/active/release_notes/images/hero.png', payload["html"])
        self.assertIn('/playbooks/wiki-runtime/active/release_notes/guide/next.html', payload["html"])
        self.assertIn('href="#section-1"', payload["html"])
        self.assertNotIn("<script", payload["html"])
        self.assertTrue(payload["interaction_policy"]["code_copy"])

    def test_viewer_document_recovers_labeled_and_unordered_lists(self) -> None:
        with self._workspace() as root:
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_path = runtime_dir / "installation_overview.md"
            runtime_path.write_text(
                (
                    "# 설치 개요\n\n"
                    "## OpenShift Container Platform 설치 정보\n\n"
                    "OpenShift Container Platform 설치 프로그램은 클러스터를 배포하는 네 가지 방법을 제공하며, 다음 목록에서 자세히 설명합니다:\n\n"
                    "대화형: 웹 기반 지원 설치 관리자를 사용하여 클러스터를 배포할 수 있습니다. 이는 인터넷에 연결된 네트워크가 있는 클러스터에 이상적인 방법입니다.\n\n"
                    "지원 설치 프로그램은 OpenShift Container Platform을 설치하는 가장 쉬운 방법이며, 스마트 기본값을 제공합니다.\n\n"
                    "로컬 에이전트 기반: 연결이 끊긴 환경 또는 제한된 네트워크를 위해 에이전트 기반 설치 관리자를 사용하여 로컬로 클러스터를 배포할 수 있습니다.\n\n"
                    "구성은 명령줄 인터페이스를 사용하여 수행됩니다. 이 방법은 연결이 끊긴 환경에 이상적입니다.\n\n"
                    "자동화: 설치 관리자 프로비저닝 인프라에 클러스터를 배포할 수 있습니다.\n\n"
                    "전체 제어: 준비 및 유지 관리하는 인프라에 클러스터를 배포하여 최대 사용자 지정 가능성을 제공할 수 있습니다.\n\n"
                    "각 방법은 다음과 같은 특성을 가진 클러스터를 배포합니다.\n\n"
                    "기본적으로 사용 가능한 단일 장애 지점이 없는 고가용성 인프라입니다.\n\n"
                    "관리자는 적용되는 업데이트 및 시기를 제어할 수 있습니다.\n"
                ),
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "installation_overview",
                                "title": "설치 개요",
                                "runtime_path": str(runtime_path),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/installation_overview/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn('reader-bullet-list reader-bullet-list-labeled', html)
        self.assertIn('<span class="reader-list-lead">대화형:</span>', html)
        self.assertIn('<span class="reader-list-lead">로컬 에이전트 기반:</span>', html)
        self.assertIn('<ul class="reader-bullet-list">', html)
        self.assertIn('관리자는 적용되는 업데이트 및 시기를 제어할 수 있습니다.', html)

    def test_viewer_document_renders_admonition_box_with_simple_list_items(self) -> None:
        with self._workspace() as root:
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_path = runtime_dir / "images.md"
            runtime_path.write_text(
                (
                    "# 이미지\n\n"
                    "## Cluster Samples Operator\n\n"
                    "중요\n\n"
                    "Cluster Samples Operator는 더 이상 사용되지 않습니다. 새 템플릿, 샘플 또는 비 S2I 이미지 스트림은 Cluster Samples Operator에 추가되지 않습니다.\n\n"
                    "그러나 기존 S2I 빌더 이미지 스트림과 템플릿은 계속 업데이트를 수신합니다. S2I 이미지 스트림 및 템플릿은 다음과 같습니다.\n\n"
                    "Ruby\n\n"
                    "Python\n\n"
                    "Node.js\n\n"
                    "Perl\n\n"
                    "Cluster Samples Operator는 S2I가 아닌 샘플 관리 및 지원을 중지합니다.\n"
                ),
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "images",
                                "title": "이미지",
                                "runtime_path": str(runtime_path),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/images/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn('class="note-card note-important"', html)
        self.assertIn('class="note-heading"', html)
        self.assertIn('<ul class="reader-bullet-list">', html)
        self.assertIn(">Ruby<", html)
        self.assertIn(">Node.js<", html)
        self.assertNotIn("<h3>Ruby</h3>", html)

    def test_render_study_viewer_html_tolerates_outline_anchors_with_braces(self) -> None:
        html = _render_study_viewer_html(
            title="설치",
            source_url="https://example.com",
            cards=['<section id="intro" class="section-card"><div class="section-body"><p>body</p></div></section>'],
            section_count=1,
            eyebrow="Source-First Candidate",
            summary="summary",
            section_outline=[{"anchor": "about-sno-{context}", "heading": "SNO", "path": "SNO"}],
        )

        self.assertIn('href="#about-sno-{context}"', html)
        self.assertIn("Quick Nav", html)

    def test_active_runtime_viewer_prefers_playbook_book_for_structured_code_blocks(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "registry.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "registry",
                        "title": "레지스트리",
                        "source_uri": "https://example.com/registry",
                        "sections": [
                            {
                                "section_id": "registry:process",
                                "section_key": "registry:process",
                                "ordinal": 1,
                                "heading": "프로세스",
                                "level": 2,
                                "path": ["프로세스"],
                                "section_path": ["프로세스"],
                                "anchor": "process",
                                "viewer_path": "/docs/ocp/4.20/ko/registry/index.html#process",
                                "semantic_role": "reference",
                                "blocks": [
                                    {
                                        "kind": "code",
                                        "language": "yaml",
                                        "wrap_hint": True,
                                        "overflow_hint": "toggle",
                                        "code": "spec:\n  schedule: 0 0 * * *\n  suspend: false\nstatus:\n  observedGeneration: 2",
                                        "copy_text": "spec:\n  schedule: 0 0 * * *\n  suspend: false\nstatus:\n  observedGeneration: 2",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "registry",
                                "title": "레지스트리",
                                "runtime_path": str(root / "data" / "wiki_runtime_books" / "full_rebuild" / "registry.md"),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/registry/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn("Source-First Candidate", html)
        self.assertNotIn("Approved Wiki Runtime Book", html)
        self.assertIn('data-copy="&quot;spec:\\n  schedule: 0 0 * * *', html)
        self.assertIn('class="code-token code-key">spec:</span>', html)

    def test_active_runtime_viewer_restores_link_lists_and_additional_resources_from_playbook_sections(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "operators.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "operators",
                        "title": "Operator",
                        "source_uri": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
                        "sections": [
                            {
                                "section_id": "operators:dev",
                                "section_key": "operators:dev",
                                "ordinal": 1,
                                "heading": "1.1. 개발자의 경우",
                                "level": 3,
                                "path": ["Operator 개요", "개발자의 경우"],
                                "section_path": ["Operator 개요", "개발자의 경우"],
                                "anchor": "operators-overview-developer-tasks_operators-overview",
                                "viewer_path": "/docs/ocp/4.20/ko/operators/index.html#operators-overview-developer-tasks_operators-overview",
                                "semantic_role": "overview",
                                "blocks": [
                                    {"kind": "paragraph", "text": "Operator 작성자는 OLM 기반 Operator에 대해 다음 개발 작업을 수행할 수 있습니다."},
                                    {"kind": "paragraph", "text": "Operator를 설치하고 네임스페이스에 등록합니다."},
                                    {"kind": "paragraph", "text": "웹 콘솔을 통해 설치된 Operator에서 애플리케이션을 생성합니다."},
                                    {"kind": "paragraph", "text": "추가 리소스"},
                                    {"kind": "paragraph", "text": "Operator 개발자의 머신 삭제 라이프사이클 후크 예"},
                                ],
                            },
                            {
                                "section_id": "operators:install-ns",
                                "section_key": "operators:install-ns",
                                "ordinal": 2,
                                "heading": "3.2. 네임스페이스에 Operator 설치",
                                "level": 3,
                                "path": ["사용자 작업", "네임스페이스에 Operator 설치"],
                                "section_path": ["사용자 작업", "네임스페이스에 Operator 설치"],
                                "anchor": "olm-installing-operators-in-namespace",
                                "viewer_path": "/docs/ocp/4.20/ko/operators/index.html#olm-installing-operators-in-namespace",
                                "semantic_role": "procedure",
                                "blocks": [{"kind": "paragraph", "text": "본문"}],
                            },
                            {
                                "section_id": "operators:create-apps",
                                "section_key": "operators:create-apps",
                                "ordinal": 3,
                                "heading": "3.1. 설치된 Operator에서 애플리케이션 생성",
                                "level": 3,
                                "path": ["사용자 작업", "설치된 Operator에서 애플리케이션 생성"],
                                "section_path": ["사용자 작업", "설치된 Operator에서 애플리케이션 생성"],
                                "anchor": "olm-creating-apps-from-installed-operators",
                                "viewer_path": "/docs/ocp/4.20/ko/operators/index.html#olm-creating-apps-from-installed-operators",
                                "semantic_role": "procedure",
                                "blocks": [{"kind": "paragraph", "text": "본문"}],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "operators",
                                "title": "Operator",
                                "runtime_path": str(root / "data" / "wiki_runtime_books" / "full_rebuild" / "operators.md"),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn('reader-bullet-list reader-bullet-list-linked', html)
        self.assertIn('/playbooks/wiki-runtime/active/operators/index.html#olm-installing-operators-in-namespace', html)
        self.assertIn('/playbooks/wiki-runtime/active/operators/index.html#olm-creating-apps-from-installed-operators', html)
        self.assertIn('class="additional-resources-card"', html)
        self.assertIn('Operator 개발자의 머신 삭제 라이프사이클 후크 예', html)

    def test_viewer_document_supports_single_and_multi_page_modes(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "install_modes.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "install_modes",
                        "title": "설치 형식",
                        "source_uri": "https://example.com/install-modes",
                        "sections": [
                            {
                                "section_id": "install_modes:intro",
                                "section_key": "install_modes:intro",
                                "ordinal": 1,
                                "heading": "설치 개요",
                                "level": 2,
                                "path": ["설치", "설치 개요"],
                                "section_path": ["설치", "설치 개요"],
                                "anchor": "install-overview",
                                "viewer_path": "/docs/ocp/4.20/ko/install_modes/index.html#install-overview",
                                "semantic_role": "overview",
                                "blocks": [{"kind": "paragraph", "text": "개요 본문"}],
                            },
                            {
                                "section_id": "install_modes:post",
                                "section_key": "install_modes:post",
                                "ordinal": 2,
                                "heading": "설치 후 구성",
                                "level": 2,
                                "path": ["설치", "설치 후 구성"],
                                "section_path": ["설치", "설치 후 구성"],
                                "anchor": "post-install",
                                "viewer_path": "/docs/ocp/4.20/ko/install_modes/index.html#post-install",
                                "semantic_role": "procedure",
                                "blocks": [{"kind": "paragraph", "text": "후속 본문"}],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "install_modes",
                                "title": "설치 형식",
                                "runtime_path": str(root / "data" / "wiki_runtime_books" / "full_rebuild" / "install_modes.md"),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            single_handler = self._capture_json_response()
            handle_viewer_document(
                single_handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/install_modes/index.html#post-install",
                        "page_mode": "single",
                    }
                ),
                root_dir=root,
            )
            multi_handler = self._capture_json_response()
            handle_viewer_document(
                multi_handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/install_modes/index.html#post-install",
                        "page_mode": "multi",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(HTTPStatus.OK, single_handler.calls[0][0])
        self.assertEqual(HTTPStatus.OK, multi_handler.calls[0][0])
        single_html = str(single_handler.calls[0][1]["html"])
        multi_html = str(multi_handler.calls[0][1]["html"])
        self.assertIn("개요 본문", single_html)
        self.assertIn("후속 본문", single_html)
        self.assertIn(">Quick Nav</summary>", multi_html)
        self.assertIn("후속 본문", multi_html)
        self.assertNotIn("개요 본문", multi_html)
        self.assertIn('class="document-footer-nav"', multi_html)
        self.assertIn('href="#install-overview"', multi_html)
        self.assertIn(">이전<", multi_html)
        self.assertNotIn(">다음<", multi_html)

    def test_active_runtime_viewer_uses_local_asciidoc_overlay_for_missing_link_metadata(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "installation_overview.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "installation_overview",
                        "title": "설치 개요",
                        "source_uri": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/installation_overview/index",
                        "anchor_map": {
                            "preparing-to-install-with-agent-based-installer": "/docs/ocp/4.20/ko/installing_with_agent_based_installer/index.html#preparing-to-install-with-agent-based-installer",
                            "ipi-install-overview": "/docs/ocp/4.20/ko/installing_on_any_platform/index.html#ipi-install-overview",
                            "installing-bare-metal": "/docs/ocp/4.20/ko/installing_on_bare_metal/index.html#installing-bare-metal",
                        },
                        "sections": [
                            {
                                "section_id": "installation_overview:installation-overview_ocp-installation-overview",
                                "section_key": "installation_overview:installation-overview_ocp-installation-overview",
                                "ordinal": 1,
                                "heading": "1.1. OpenShift Container Platform 설치 정보",
                                "level": 3,
                                "path": ["설치 개요", "설치 정보"],
                                "section_path": ["설치 개요", "설치 정보"],
                                "anchor": "installation-overview_ocp-installation-overview",
                                "viewer_path": "/docs/ocp/4.20/ko/installation_overview/index.html#installation-overview_ocp-installation-overview",
                                "semantic_role": "concept",
                                "blocks": [
                                    {"kind": "paragraph", "text": "OpenShift Container Platform 설치 프로그램은 클러스터를 배포하는 네 가지 방법을 제공하며, 다음 목록에서 자세히 설명합니다:"},
                                    {"kind": "paragraph", "text": "대화형: 웹 기반 지원 설치 관리자를 사용하여 클러스터를 배포할 수 있습니다. 이는 인터넷에 연결된 네트워크가 있는 클러스터에 이상적인 방법입니다."},
                                    {"kind": "paragraph", "text": "지원 설치 프로그램은 OpenShift Container Platform을 설치하는 가장 쉬운 방법이며, 스마트 기본값을 제공하며 클러스터를 설치하기 전에 사전 진행 중 검증을 수행합니다."},
                                    {"kind": "paragraph", "text": "로컬 에이전트 기반: 연결이 끊긴 환경 또는 제한된 네트워크를 위해 에이전트 기반 설치 관리자를 사용하여 로컬로 클러스터를 배포할 수 있습니다."},
                                    {"kind": "paragraph", "text": "자동화: 설치 관리자 프로비저닝 인프라에 클러스터를 배포할 수 있습니다."},
                                    {"kind": "paragraph", "text": "전체 제어: 준비 및 유지 관리하는 인프라에 클러스터를 배포하여 최대 사용자 지정 가능성을 제공할 수 있습니다."},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            tmp_source_module = root / "tmp_source" / "openshift-docs-enterprise-4.20" / "modules"
            tmp_source_module.mkdir(parents=True, exist_ok=True)
            (tmp_source_module / "installation-overview.adoc").write_text(
                (
                    '[id="installation-overview_{context}"]\n'
                    '= About installation\n\n'
                    'The installation program offers methods.\n\n'
                    '* *Interactive*: You can deploy a cluster with the web-based '
                    'link:https://access.redhat.com/documentation/en-us/assisted_installer_for_openshift_container_platform[Assisted Installer].\n\n'
                    '* *Local Agent-based*: You can deploy a cluster locally with the '
                    'xref:../../installing/installing_with_agent_based_installer/preparing-to-install-with-agent-based-installer.adoc#preparing-to-install-with-agent-based-installer[agent-based installer]. '
                    'You must download and configure the link:https://console.redhat.com/openshift/install/metal/agent-based[agent-based installer] first.\n\n'
                    '* *Automated*: You can '
                    'xref:../../installing/installing_bare_metal/ipi/ipi-install-overview.adoc#ipi-install-overview[deploy a cluster on installer-provisioned infrastructure].\n\n'
                    '* *Full control*: You can deploy a cluster on '
                    'xref:../../installing/installing_bare_metal/upi/installing-bare-metal.adoc#installing-bare-metal[infrastructure that you prepare and maintain].\n'
                ),
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "installation_overview",
                                "title": "설치 개요",
                                "runtime_path": str(root / "data" / "wiki_runtime_books" / "full_rebuild" / "installation_overview.md"),
                                "source_lane": "official_ko",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/installation_overview/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn('reader-bullet-list reader-bullet-list-labeled', html)
        self.assertIn('https://access.redhat.com/documentation/en-us/assisted_installer_for_openshift_container_platform', html)
        self.assertIn('/playbooks/wiki-runtime/active/installing_with_agent_based_installer/index.html#preparing-to-install-with-agent-based-installer', html)
        self.assertIn('/playbooks/wiki-runtime/active/installing_on_any_platform/index.html#ipi-install-overview', html)
        self.assertIn('/playbooks/wiki-runtime/active/installing_on_bare_metal/index.html#installing-bare-metal', html)

    def test_viewer_source_meta_resolves_active_runtime_viewer_path(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)

            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "support",
                                "title": "Support",
                                "source_url": "https://example.com/support",
                                "source_lane": "approved_wiki_runtime",
                                "approval_state": "approved",
                                "publication_state": "active",
                                "source_repo": "https://github.com/example/openshift-docs",
                                "source_branch": "enterprise-4.20",
                                "source_binding_kind": "file",
                                "source_relative_path": "support/index.adoc",
                                "source_relative_paths": ["support/index.adoc"],
                                "fallback_source_url": "https://docs.example.com/support",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings.normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            settings.normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "support",
                        "book_title": "Support",
                        "heading": "Get support",
                        "section_path": ["Support", "Get support"],
                        "anchor": "contact-red-hat-support",
                        "source_url": "https://example.com/support",
                        "viewer_path": "/docs/ocp/4.20/ko/support/index.html#contact-red-hat-support",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_source_meta(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/support/index.html#contact-red-hat-support",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("support", payload["book_slug"])
        self.assertEqual("Get support", payload["section"])
        self.assertEqual(["Support", "Get support"], payload["section_path"])
        self.assertEqual(
            "/playbooks/wiki-runtime/active/support/index.html#contact-red-hat-support",
            payload["viewer_path"],
        )
        self.assertEqual("official_candidate_runtime", payload["boundary_truth"])
        self.assertEqual("Source-First Candidate", payload["boundary_badge"])
        self.assertEqual(
            "https://github.com/example/openshift-docs@enterprise-4.20:support/index.adoc",
            payload["source_ref"],
        )
        self.assertEqual("file", payload["source_binding_kind"])
        self.assertEqual(["support/index.adoc"], payload["source_relative_paths"])
        self.assertEqual("https://docs.example.com/support", payload["fallback_source_url"])
        self.assertTrue(payload["source_fingerprint"])

    def test_active_runtime_viewer_document_renders_repo_first_source_trace(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-18T14:00:00+00:00",
                        "entries": [
                            {
                                "book_slug": "support",
                                "title": "Support",
                                "source_lane": "official_ko",
                                "approval_state": "approved",
                                "publication_state": "active",
                                "source_repo": "https://github.com/example/openshift-docs",
                                "source_branch": "enterprise-4.20",
                                "source_binding_kind": "file",
                                "source_relative_path": "support/index.adoc",
                                "source_relative_paths": ["support/index.adoc"],
                                "fallback_source_url": "https://docs.example.com/support",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_path = runtime_dir / "support.md"
            runtime_path.write_text(
                "# Support\n\n## Get support\n\n본문\n",
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-18T14:10:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "support",
                                "title": "Support",
                                "source_lane": "official_ko",
                                "source_ref": "https://github.com/example/openshift-docs@enterprise-4.20:support/index.adoc",
                                "source_fingerprint": "supportfingerprint",
                                "source_binding_kind": "file",
                                "source_relative_paths": ["support/index.adoc"],
                                "fallback_source_url": "https://docs.example.com/support",
                                "runtime_path": str(runtime_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/playbooks/wiki-runtime/active/support/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        html = str(payload["html"])
        self.assertIn("Repo/AsciiDoc First", html)
        self.assertIn("https://github.com/example/openshift-docs", html)
        self.assertIn("support/index.adoc", html)
        self.assertIn("Red Hat HTML Single", html)

    def test_active_runtime_viewer_document_accepts_windows_manifest_runtime_path_inside_container(self) -> None:
        with self._workspace() as root:
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_path = runtime_dir / "support.md"
            runtime_path.write_text(
                "# Support\n\n## Get support\n\n본문\n",
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T09:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "support",
                                "title": "Support",
                                "source_lane": "official_ko",
                                "runtime_path": r"C:\\host\\workspace\\data\\wiki_runtime_books\\full_rebuild\\support.md",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode({"viewer_path": "/playbooks/wiki-runtime/active/support/index.html"}),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        self.assertIn("Get support", str(payload["html"]))

    def test_active_runtime_viewer_document_uses_relation_indexes_for_sections_figures_and_siblings(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            relation_dir = root / "data" / "wiki_relations"
            relation_dir.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-18T15:00:00+00:00",
                        "entries": [
                            {
                                "book_slug": "advanced_networking",
                                "title": "고급 네트워킹",
                                "source_lane": "official_ko",
                                "approval_state": "approved",
                                "publication_state": "active",
                                "source_repo": "https://github.com/example/openshift-docs",
                                "source_branch": "enterprise-4.20",
                                "source_binding_kind": "collection",
                                "source_relative_paths": ["networking/advanced_networking/index.adoc"],
                                "fallback_source_url": "https://docs.example.com/advanced-networking",
                            },
                            {
                                "book_slug": "architecture",
                                "title": "아키텍처",
                                "source_lane": "official_ko",
                                "approval_state": "approved",
                                "publication_state": "active",
                                "source_repo": "https://github.com/example/openshift-docs",
                                "source_branch": "enterprise-4.20",
                                "source_binding_kind": "file",
                                "source_relative_paths": ["architecture/index.adoc"],
                                "fallback_source_url": "https://docs.example.com/architecture",
                            },
                            {
                                "book_slug": "installation_overview",
                                "title": "설치 개요",
                                "source_lane": "official_ko",
                                "approval_state": "approved",
                                "publication_state": "active",
                            },
                            {
                                "book_slug": "networking_overview",
                                "title": "네트워킹 개요",
                                "source_lane": "official_ko",
                                "approval_state": "approved",
                                "publication_state": "active",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "advanced_networking.md").write_text(
                "# 고급 네트워킹\n\n## Network bonding considerations\n\n본문\n",
                encoding="utf-8",
            )
            (runtime_dir / "architecture.md").write_text(
                "# 아키텍처\n\n## About installation and updates\n\n본문\n",
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-18T15:10:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "advanced_networking",
                                "title": "고급 네트워킹",
                                "source_lane": "official_ko",
                                "runtime_path": str(runtime_dir / "advanced_networking.md"),
                            },
                            {
                                "slug": "architecture",
                                "title": "아키텍처",
                                "source_lane": "official_ko",
                                "runtime_path": str(runtime_dir / "architecture.md"),
                            },
                            {
                                "slug": "installation_overview",
                                "title": "설치 개요",
                                "source_lane": "official_ko",
                                "runtime_path": str(runtime_dir / "architecture.md"),
                            },
                            {
                                "slug": "networking_overview",
                                "title": "네트워킹 개요",
                                "source_lane": "official_ko",
                                "runtime_path": str(runtime_dir / "advanced_networking.md"),
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (relation_dir / "candidate_relations.json").write_text(
                json.dumps(
                    {
                        "advanced_networking": {
                            "entities": [],
                            "related_docs": [],
                            "next_reading_path": [],
                            "siblings": [
                                {
                                    "label": "네트워킹 개요",
                                    "href": "/playbooks/wiki-runtime/active/networking_overview/index.html",
                                    "summary": "같은 작업군 문서",
                                }
                            ],
                        },
                        "architecture": {
                            "entities": [],
                            "related_docs": [],
                            "next_reading_path": [],
                            "siblings": [
                                {
                                    "label": "설치 개요",
                                    "href": "/playbooks/wiki-runtime/active/installation_overview/index.html",
                                    "summary": "연결된 설치 문서",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (relation_dir / "figure_assets.json").write_text(
                json.dumps(
                    {
                        "entries": {
                            "advanced_networking": [
                                {
                                    "caption": "OVS balance-slb mode",
                                    "asset_url": "/playbooks/wiki-assets/full_rebuild/advanced_networking/ovs-balance-slb.png",
                                    "viewer_path": "/wiki/figures/advanced_networking/ovs-balance-slb.png/index.html",
                                    "section_hint": "고급 네트워킹 > Network bonding considerations",
                                }
                            ],
                            "installation_overview": [
                                {
                                    "caption": "OpenShift Container Platform installation targets and dependencies",
                                    "asset_url": "/playbooks/wiki-assets/full_rebuild/installation_overview/targets-and-dependencies.png",
                                    "viewer_path": "/wiki/figures/installation_overview/targets-and-dependencies.png/index.html",
                                    "section_hint": "설치 개요 > Figures > Figure 1. OpenShift Container Platform installation targets and dependencies",
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (relation_dir / "figure_entity_index.json").write_text(
                json.dumps({"by_entity": {}, "by_book": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (relation_dir / "figure_section_index.json").write_text(
                json.dumps(
                    {
                        "by_slug": {
                            "installation_overview": [
                                {
                                    "asset_name": "targets-and-dependencies.png",
                                    "viewer_path": "/wiki/figures/installation_overview/targets-and-dependencies.png/index.html",
                                    "caption": "OpenShift Container Platform installation targets and dependencies",
                                    "section_hint": "OpenShift Container Platform installation overview",
                                    "section_path": "설치 개요 > Figures > Figure 1. OpenShift Container Platform installation targets and dependencies",
                                    "section_href": "/playbooks/wiki-runtime/active/installation_overview/index.html#figure-1-openshift-container-platform-installation-targets-and-dependencies",
                                    "section_anchor": "figure-1-openshift-container-platform-installation-targets-and-dependencies",
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (relation_dir / "section_relation_index.json").write_text(
                json.dumps(
                    {
                        "by_book": {
                            "advanced_networking": [
                                {
                                    "label": "Network bonding considerations",
                                    "href": "/playbooks/wiki-runtime/active/advanced_networking/index.html#network-bonding-considerations",
                                    "summary": "고급 네트워킹 > Network bonding considerations",
                                    "source": "figure_section",
                                }
                            ],
                            "architecture": [
                                {
                                    "label": "Figure 1. OpenShift Container Platform installation targets and dependencies",
                                    "href": "/playbooks/wiki-runtime/active/installation_overview/index.html#figure-1-openshift-container-platform-installation-targets-and-dependencies",
                                    "summary": "설치 개요 > Figures > Figure 1. OpenShift Container Platform installation targets and dependencies",
                                    "source": "related_doc_section",
                                }
                            ],
                        },
                        "by_entity": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (relation_dir / "entity_hubs.json").write_text("{}", encoding="utf-8")
            (relation_dir / "chat_navigation_aliases.json").write_text("{}", encoding="utf-8")

            with patch("play_book_studio.app.wiki_relations.WIKI_RELATIONS_DIR", relation_dir):
                advanced_handler = self._capture_json_response()
                handle_viewer_document(
                    advanced_handler,
                    urlencode({"viewer_path": "/playbooks/wiki-runtime/active/advanced_networking/index.html"}),
                    root_dir=root,
                )
                architecture_handler = self._capture_json_response()
                handle_viewer_document(
                    architecture_handler,
                    urlencode({"viewer_path": "/playbooks/wiki-runtime/active/architecture/index.html"}),
                    root_dir=root,
                )

        advanced_html = str(advanced_handler.calls[0][1]["html"])
        architecture_html = str(architecture_handler.calls[0][1]["html"])
        self.assertIn("Network bonding considerations", advanced_html)
        self.assertIn("/wiki/figures/advanced_networking/ovs-balance-slb.png/index.html", advanced_html)
        self.assertIn("/playbooks/wiki-runtime/active/networking_overview/index.html", advanced_html)
        self.assertNotIn("연결된 절차 섹션이 아직 없습니다.", advanced_html)
        self.assertNotIn("연결된 figure 자산이 아직 없습니다.", advanced_html)
        self.assertIn("OpenShift Container Platform installation targets and dependencies", architecture_html)
        self.assertIn("/wiki/figures/installation_overview/targets-and-dependencies.png/index.html", architecture_html)
        self.assertNotIn("연결된 figure 자산이 아직 없습니다.", architecture_html)

    def test_viewer_source_meta_uses_registry_for_derived_docs_viewer_path(self) -> None:
        with self._workspace(env_text="ARTIFACTS_DIR=artifacts\n") as root:
            settings = self._settings(root)

            settings.playbook_documents_path.parent.mkdir(parents=True, exist_ok=True)
            settings.playbook_documents_path.write_text(
                json.dumps(
                    {
                        "book_slug": "backup_restore_operations",
                        "title": "Backup Restore Operations",
                        "source_uri": "https://example.com/backup_restore_operations",
                        "review_status": "approved",
                        "section_count": 3,
                        "source_metadata": {
                            "source_type": "operation_playbook",
                            "source_lane": "applied_playbook",
                            "approval_state": "approved",
                            "publication_state": "published",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_source_meta(
                handler,
                urlencode(
                    {
                        "viewer_path": "/docs/ocp/4.20/ko/backup_restore_operations/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("backup_restore_operations", payload["book_slug"])
        self.assertEqual("Backup Restore Operations", payload["book_title"])
        self.assertEqual("applied_playbook", payload["source_lane"])
        self.assertEqual("official_candidate_runtime", payload["boundary_truth"])
        self.assertEqual(
            "/docs/ocp/4.20/ko/backup_restore_operations/index.html",
            payload["viewer_path"],
        )

    def test_viewer_document_route_falls_back_to_normalized_sections_for_known_book(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)

            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "distributed_tracing",
                                "title": "Distributed Tracing",
                                "source_url": "https://example.com/distributed-tracing",
                                "source_lane": "approved_wiki_runtime",
                                "approval_state": "approved",
                                "publication_state": "active",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings.normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            settings.normalized_docs_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "book_slug": "distributed_tracing",
                                "book_title": "Distributed Tracing",
                                "heading": "Overview",
                                "section_path": ["Distributed Tracing", "Overview"],
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/distributed_tracing/index.html#overview",
                                "source_url": "https://example.com/distributed-tracing",
                                "text": "Distributed tracing overview.",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "book_slug": "distributed_tracing",
                                "book_title": "Distributed Tracing",
                                "heading": "Configuration",
                                "section_path": ["Distributed Tracing", "Configuration"],
                                "anchor": "configuration",
                                "viewer_path": "/docs/ocp/4.20/ko/distributed_tracing/index.html#configuration",
                                "source_url": "https://example.com/distributed-tracing",
                                "text": "Configure the collector.",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_viewer_document(
                handler,
                urlencode(
                    {
                        "viewer_path": "/docs/ocp/4.20/ko/distributed_tracing/index.html",
                    }
                ),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual(
            "/docs/ocp/4.20/ko/distributed_tracing/index.html",
            payload["viewer_path"],
        )
        self.assertIn("Distributed Tracing", payload["html"])
        self.assertIn('id="overview"', payload["html"])
        self.assertIn('id="configuration"', payload["html"])

    def test_canonicalize_viewer_path_adds_index_for_short_known_paths(self) -> None:
        self.assertEqual(
            "/playbooks/wiki-runtime/active/support/index.html#contact-red-hat-support",
            _canonicalize_viewer_path("/playbooks/wiki-runtime/active/support#contact-red-hat-support"),
        )
        self.assertEqual(
            "/wiki/entities/etcd/index.html",
            _canonicalize_viewer_path("/wiki/entities/etcd"),
        )
        self.assertEqual(
            "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
            _canonicalize_viewer_path("/wiki/figures/overview/oke-about-ocp-stack-image.png"),
        )

    def test_viewer_source_meta_route_supports_entity_and_figure_paths(self) -> None:
        cases = [
            (
                "/wiki/entities/etcd/index.html",
                {
                    "book_slug": "etcd",
                    "book_title": "Etcd",
                    "section": "Etcd",
                    "section_path": ["Etcd"],
                    "viewer_path": "/wiki/entities/etcd/index.html",
                    "source_url": "",
                    "boundary_truth": "official_validated_runtime",
                    "runtime_truth_label": "Validated Runtime Entity Hub",
                    "source_lane": "approved_wiki_runtime",
                    "approval_state": "approved",
                    "publication_state": "active",
                    "parser_backend": "",
                    "boundary_badge": "Validated Runtime",
                },
            ),
            (
                "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                {
                    "book_slug": "overview",
                    "book_title": "Red Hat OpenShift Kubernetes Engine",
                    "anchor": "oke-about-ocp-stack-image.png",
                    "section": "Red Hat OpenShift Kubernetes Engine",
                    "section_path": [
                        "Introduction to OpenShift Container Platform",
                        "Red Hat OpenShift Kubernetes Engine",
                    ],
                    "viewer_path": "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                    "source_url": "/playbooks/wiki-assets/full_rebuild/overview/oke-about-ocp-stack-image.png",
                    "boundary_truth": "official_candidate_runtime",
                    "runtime_truth_label": "Source-First Candidate Figure",
                    "source_lane": "official_source_first_candidate",
                    "approval_state": "",
                    "publication_state": "published",
                    "parser_backend": "render_bound_markdown",
                    "boundary_badge": "Source-First Candidate",
                },
            ),
            (
                "/wiki/entities/etcd",
                {
                    "book_slug": "etcd",
                    "book_title": "Etcd",
                    "section": "Etcd",
                    "section_path": ["Etcd"],
                    "viewer_path": "/wiki/entities/etcd/index.html",
                    "source_url": "",
                    "boundary_truth": "official_validated_runtime",
                    "runtime_truth_label": "Validated Runtime Entity Hub",
                    "source_lane": "approved_wiki_runtime",
                    "approval_state": "approved",
                    "publication_state": "active",
                    "parser_backend": "",
                    "boundary_badge": "Validated Runtime",
                },
            ),
            (
                "/wiki/figures/overview/oke-about-ocp-stack-image.png",
                {
                    "book_slug": "overview",
                    "book_title": "Red Hat OpenShift Kubernetes Engine",
                    "anchor": "oke-about-ocp-stack-image.png",
                    "section": "Red Hat OpenShift Kubernetes Engine",
                    "section_path": [
                        "Introduction to OpenShift Container Platform",
                        "Red Hat OpenShift Kubernetes Engine",
                    ],
                    "viewer_path": "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                    "source_url": "/playbooks/wiki-assets/full_rebuild/overview/oke-about-ocp-stack-image.png",
                    "boundary_truth": "official_candidate_runtime",
                    "runtime_truth_label": "Source-First Candidate Figure",
                    "source_lane": "official_source_first_candidate",
                    "approval_state": "",
                    "publication_state": "published",
                    "parser_backend": "render_bound_markdown",
                    "boundary_badge": "Source-First Candidate",
                },
            ),
        ]

        for viewer_path, expected in cases:
            with self.subTest(viewer_path=viewer_path):
                handler = self._capture_json_response()
                handle_source_meta(handler, urlencode({"viewer_path": viewer_path}), root_dir=ROOT)

                self.assertEqual(1, len(handler.calls))
                status, payload = handler.calls[0]
                self.assertEqual(HTTPStatus.OK, status)
                for key, value in expected.items():
                    self.assertEqual(value, payload[key], key)
                self.assertTrue(payload["section_match_exact"])

    def test_active_runtime_source_meta_demotes_untranslated_source_first_runtime(self) -> None:
        with self._workspace() as root:
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_path = runtime_dir / "installing_on_any_platform.md"
            runtime_path.write_text(
                "# 플랫폼 비종속 설치 플레이북\n\nAdditional resources\n\nInstalling OpenShift Container Platform on any platform\n",
                encoding="utf-8",
            )
            active_manifest_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            active_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            active_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-04-19T08:00:00+00:00",
                        "active_group": "full_rebuild",
                        "entries": [
                            {
                                "slug": "installing_on_any_platform",
                                "title": "플랫폼 비종속 설치 플레이북",
                                "runtime_path": str(runtime_path),
                                "source_lane": "official_ko",
                                "parser_backend": "render_bound_markdown",
                                "promotion_strategy": "full_rebuild_source_repo_binding",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            handler = self._capture_json_response()
            handle_source_meta(
                handler,
                urlencode({"viewer_path": "/playbooks/wiki-runtime/active/installing_on_any_platform/index.html"}),
                root_dir=root,
            )

        self.assertEqual(1, len(handler.calls))
        status, payload = handler.calls[0]
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("official_candidate_runtime", payload["boundary_truth"])
        self.assertEqual("Source-First Candidate", payload["boundary_badge"])
        self.assertEqual("official_source_first_candidate", payload["source_lane"])
        self.assertEqual("", payload["approval_state"])
        self.assertEqual("active", payload["publication_state"])
        self.assertEqual("render_bound_markdown", payload["parser_backend"])

    def test_viewer_document_route_supports_entity_and_figure_paths(self) -> None:
        cases = [
            (
                "/wiki/entities/etcd/index.html",
                "/wiki/entities/etcd/index.html",
                [
                    'class="wiki-parent-card"',
                    'class="wiki-parent-eyebrow"',
                    'href="/playbooks/wiki-runtime/active/backup_and_restore/index.html"',
                ],
            ),
            (
                "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                [
                    'class="figure-block"',
                    '<figcaption>Red Hat OpenShift Kubernetes Engine</figcaption>',
                    'src="/playbooks/wiki-assets/full_rebuild/overview/oke-about-ocp-stack-image.png"',
                    'href="/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html"',
                ],
            ),
            (
                "/wiki/entities/etcd",
                "/wiki/entities/etcd/index.html",
                [
                    'class="wiki-parent-card"',
                    'class="wiki-parent-eyebrow"',
                    'href="/playbooks/wiki-runtime/active/backup_and_restore/index.html"',
                ],
            ),
            (
                "/wiki/figures/overview/oke-about-ocp-stack-image.png",
                "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html",
                [
                    'class="figure-block"',
                    '<figcaption>Red Hat OpenShift Kubernetes Engine</figcaption>',
                    'src="/playbooks/wiki-assets/full_rebuild/overview/oke-about-ocp-stack-image.png"',
                    'href="/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html"',
                ],
            ),
        ]

        for viewer_path, expected_viewer_path, markers in cases:
            with self.subTest(viewer_path=viewer_path):
                handler = self._capture_json_response()
                handle_viewer_document(handler, urlencode({"viewer_path": viewer_path}), root_dir=ROOT)

                self.assertEqual(1, len(handler.calls))
                status, payload = handler.calls[0]
                self.assertEqual(HTTPStatus.OK, status)
                self.assertEqual(expected_viewer_path, payload["viewer_path"])
                self.assertIn("html", payload)
                html = str(payload["html"])
                for marker in markers:
                    self.assertIn(marker, html)
                self.assertTrue(payload["interaction_policy"]["anchor_navigation"])

    def test_viewer_document_route_falls_back_to_runtime_markdown_when_artifacts_are_missing(self) -> None:
        with self._workspace() as root:
            runtime_dir = root / "data" / "wiki_runtime_books" / "full_rebuild"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            markdown_path = runtime_dir / "monitoring.md"
            markdown_path.write_text(
                (ROOT / "data" / "wiki_runtime_books" / "full_rebuild" / "monitoring.md").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )

            manifest_path = root / "data" / "wiki_runtime_books" / "full_rebuild_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "slug": "monitoring",
                                "title": "Monitoring",
                                "runtime_path": str(markdown_path),
                                "promotion_strategy": "full_rebuild_generic_export",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cases = [
                "/docs/ocp/4.20/ko/monitoring/index.html",
                "/playbooks/wiki-runtime/active/monitoring/index.html",
            ]

            for viewer_path in cases:
                with self.subTest(viewer_path=viewer_path):
                    handler = self._capture_json_response()
                    handle_viewer_document(handler, urlencode({"viewer_path": viewer_path}), root_dir=root)

                    self.assertEqual(1, len(handler.calls))
                    status, payload = handler.calls[0]
                    self.assertEqual(HTTPStatus.OK, status)
                    self.assertEqual(viewer_path, payload["viewer_path"])
                    html = str(payload["html"])
                    self.assertIn("OpenShift Container Platform includes a preconfigured", html)
                    self.assertIn("self-updating monitoring stack", html)

    def test_viewer_path_local_raw_html_fallback_is_disabled(self) -> None:
        with self._workspace() as root:
            raw_html_dir = root / "custom_raw_html"
            raw_html_dir.mkdir(parents=True)
            expected = raw_html_dir / "architecture.html"
            expected.write_text("<html><body>ok</body></html>", encoding="utf-8")

            with self._patched_env(removed=("ARTIFACTS_DIR",), RAW_HTML_DIR=str(raw_html_dir)):
                target = _viewer_path_to_local_html(
                    root,
                    "/docs/ocp/4.20/ko/architecture/index.html#overview",
                )

        self.assertIsNone(target)

    def test_viewer_path_local_raw_html_fallback_is_disabled_for_other_versions(self) -> None:
        with self._workspace(
            env_text=(
                "RAW_HTML_DIR=custom_raw_html\n"
                "OCP_VERSION=4.18\n"
            )
        ) as root:
            raw_html_dir = root / "custom_raw_html"
            raw_html_dir.mkdir(parents=True)
            expected = raw_html_dir / "architecture.html"
            expected.write_text("<html><body>ok</body></html>", encoding="utf-8")

            target = _viewer_path_to_local_html(
                root,
                "/docs/ocp/4.18/ko/architecture/index.html#overview",
            )

        self.assertIsNone(target)

    def test_serialize_citation_enriches_source_labels(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            manifest_path = settings.source_manifest_path
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "architecture",
                                "title": "아키텍처",
                                "source_url": "https://example.com/architecture",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            normalized_docs_path = settings.normalized_docs_path
            normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "heading": "컨트롤 플레인",
                        "section_level": 2,
                        "section_path": ["개요", "컨트롤 플레인"],
                        "anchor": "overview",
                        "source_url": "https://example.com/architecture",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with self._patched_env(
                removed=("ARTIFACTS_DIR", "RAW_HTML_DIR", "SOURCE_MANIFEST_PATH"),
            ):
                payload = _serialize_citation(root, _citation(1))

        self.assertEqual("아키텍처", payload["book_title"])
        self.assertEqual(["개요", "컨트롤 플레인"], payload["section_path"])
        self.assertEqual("개요 > 컨트롤 플레인", payload["section_path_label"])
        self.assertEqual("아키텍처 · 개요 > 컨트롤 플레인", payload["source_label"])
        self.assertEqual("core", payload["source_collection"])
        self.assertEqual("openshift-4-20-core", payload["pack_id"])
        self.assertEqual("OpenShift 4.20", payload["pack_label"])
        self.assertEqual("openshift", payload["inferred_product"])
        self.assertEqual("4.20", payload["inferred_version"])
        self.assertTrue(payload["section_match_exact"])

    def test_serialize_citation_strips_heading_number_prefix_from_source_labels(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            manifest_path = settings.source_manifest_path
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "cli_reference",
                                "title": "CLI Reference",
                                "source_url": "https://example.com/cli-reference",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            normalized_docs_path = settings.normalized_docs_path
            normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "cli_reference",
                        "book_title": "CLI Reference",
                        "heading": "2.6.1.78. oc expose",
                        "section_level": 4,
                        "section_path": [
                            "2장. OpenShift CLI(oc)",
                            "2.6. OpenShift CLI 개발자 명령 참조",
                            "2.6.1. OpenShift CLI (oc) 개발자",
                        ],
                        "anchor": "oc-expose",
                        "source_url": "https://example.com/cli-reference",
                        "viewer_path": "/docs/ocp/4.20/ko/cli_reference/index.html#oc-expose",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = _serialize_citation(
                root,
                Citation(
                    index=1,
                    chunk_id="chunk-1",
                    book_slug="cli_reference",
                    section="2.6.1.78. oc expose",
                    anchor="oc-expose",
                    source_url="https://example.com/cli-reference",
                    viewer_path="/docs/ocp/4.20/ko/cli_reference/index.html#oc-expose",
                    excerpt="본문",
                ),
            )

        self.assertEqual("oc expose", payload["section"])
        self.assertEqual(
            [
                "OpenShift CLI(oc)",
                "OpenShift CLI 개발자 명령 참조",
                "OpenShift CLI (oc) 개발자",
            ],
            payload["section_path"],
        )
        self.assertEqual(
            "OpenShift CLI(oc) > OpenShift CLI 개발자 명령 참조 > OpenShift CLI (oc) 개발자",
            payload["section_path_label"],
        )
        self.assertEqual(
            "CLI Reference · OpenShift CLI(oc) > OpenShift CLI 개발자 명령 참조 > OpenShift CLI (oc) 개발자",
            payload["source_label"],
        )

    def test_serialize_citation_marks_section_fallback_when_anchor_missing(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            manifest_path = settings.source_manifest_path
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "architecture",
                                "title": "아키텍처",
                                "source_url": "https://example.com/architecture",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            normalized_docs_path = settings.normalized_docs_path
            normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "heading": "개요",
                        "section_level": 1,
                        "section_path": ["개요"],
                        "anchor": "overview",
                        "source_url": "https://example.com/architecture",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = _serialize_citation(
                root,
                Citation(
                    index=1,
                    chunk_id="chunk-1",
                    book_slug="architecture",
                    section="존재하지 않는 섹션",
                    anchor="missing-anchor",
                    source_url="https://example.com/architecture",
                    viewer_path="/docs/ocp/4.20/ko/architecture/index.html#missing-anchor",
                    excerpt="본문",
                ),
            )

        self.assertFalse(payload["section_match_exact"])

    def test_serialize_citation_reuses_request_local_presentation_context(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "architecture",
                                "title": "아키텍처",
                                "source_url": "https://example.com/architecture",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings.normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            settings.normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "heading": "컨트롤 플레인",
                        "section_level": 2,
                        "section_path": ["개요", "컨트롤 플레인"],
                        "anchor": "overview",
                        "source_url": "https://example.com/architecture",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("play_book_studio.app.presenters.load_settings", wraps=load_settings) as load_settings_spy:
                presentation_context = _build_citation_presentation_context(root)
                first = _serialize_citation(
                    root,
                    _citation(1),
                    presentation_context=presentation_context,
                )
                second = _serialize_citation(
                    root,
                    _citation(2),
                    presentation_context=presentation_context,
                )

        self.assertEqual(first["book_title"], second["book_title"])
        self.assertEqual(first["source_label"], second["source_label"])
        self.assertEqual(first["section_path_label"], second["section_path_label"])
        self.assertEqual(1, load_settings_spy.call_count)

    def test_serialize_citation_skips_normalized_lookup_when_citation_has_section_path(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "post_installation_configuration__cluster_tasks",
                                "title": "설치 후 클러스터 작업",
                                "source_url": "https://example.com/post-install",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            citation = Citation(
                index=1,
                chunk_id="chunk-1",
                book_slug="post_installation_configuration__cluster_tasks",
                section="Informational Resources",
                anchor="informational-resources",
                source_url="https://example.com/post-install",
                viewer_path="/docs/ocp/4.20/ko/post_installation_configuration__cluster_tasks/index.html#informational-resources",
                excerpt="본문",
                section_path=("Available cluster customizations", "Informational Resources"),
                section_path_label="Available cluster customizations > Informational Resources",
            )
            presentation_context = _build_citation_presentation_context(root)
            with patch(
                "play_book_studio.app.presenters._resolve_normalized_row_for_viewer_path",
                side_effect=AssertionError("normalized lookup should not run"),
            ):
                payload = _serialize_citation(
                    root,
                    citation,
                    presentation_context=presentation_context,
                )

        self.assertEqual("설치 후 클러스터 작업", payload["book_title"])
        self.assertEqual(
            ["Available cluster customizations", "Informational Resources"],
            payload["section_path"],
        )
        self.assertEqual(
            "Available cluster customizations > Informational Resources",
            payload["section_path_label"],
        )
        self.assertTrue(payload["section_match_exact"])

    def test_serialize_citation_reuses_process_local_cache_without_context(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            settings.source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            settings.source_manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "book_slug": "architecture",
                                "title": "아키텍처",
                                "source_url": "https://example.com/architecture",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings.normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            settings.normalized_docs_path.write_text(
                json.dumps(
                    {
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "heading": "컨트롤 플레인",
                        "section_level": 2,
                        "section_path": ["개요", "컨트롤 플레인"],
                        "anchor": "overview",
                        "source_url": "https://example.com/architecture",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                        "text": "본문",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            presenters_module._serialize_citation_cached.cache_clear()
            with patch(
                "play_book_studio.app.presenters._serialize_citation_uncached",
                wraps=presenters_module._serialize_citation_uncached,
            ) as uncached_spy:
                first = _serialize_citation(root, _citation(1))
                second = _serialize_citation(root, _citation(1))

        self.assertEqual(first["source_label"], second["source_label"])
        self.assertEqual(1, uncached_spy.call_count)

    def test_internal_viewer_html_falls_back_to_normalized_sections_without_playbook_artifact(self) -> None:
        with self._workspace() as root:
            settings = self._settings(root)
            normalized_docs_path = settings.normalized_docs_path
            normalized_docs_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_docs_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "book_slug": "architecture",
                                "book_title": "아키텍처",
                                "heading": "개요",
                                "section_level": 1,
                                "section_path": ["개요"],
                                "anchor": "overview",
                                "source_url": "https://example.com/architecture",
                                "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                                "text": "Red Hat OpenShift Documentation Team 법적 공지 초록\n\nOpenShift 아키텍처는 `컨트롤 플레인`과 작업자 노드로 구성됩니다.\n\n[CODE]\noc get nodes\n[/CODE]",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "book_slug": "architecture",
                                "book_title": "아키텍처",
                                "heading": "컨트롤 플레인",
                                "section_level": 2,
                                "section_path": ["개요", "컨트롤 플레인"],
                                "anchor": "control-plane",
                                "source_url": "https://example.com/architecture",
                                "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#control-plane",
                                "text": "API 서버와 스케줄러가 핵심 역할을 담당합니다.",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with self._patched_env(removed=("ARTIFACTS_DIR", "RAW_HTML_DIR")):
                html = _internal_viewer_html(
                    root,
                    "/docs/ocp/4.20/ko/architecture/index.html#overview",
                )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("아키텍처", html)
        self.assertIn('id="overview"', html)
        self.assertIn('id="control-plane"', html)
        self.assertIn("oc get nodes", html)

    def test_internal_viewer_html_prefers_playbook_artifact_when_available(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "architecture.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "architecture",
                        "title": "아키텍처",
                        "source_uri": "https://example.com/architecture",
                        "language_hint": "ko",
                        "pack_id": "openshift-4-20-core",
                        "inferred_version": "4.20",
                        "sections": [
                            {
                                "section_id": "architecture:overview",
                                "section_key": "architecture:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "section_path_label": "개요",
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                                "semantic_role": "overview",
                                "block_kinds": ["prerequisite", "procedure", "code", "note"],
                                "blocks": [
                                    {"kind": "prerequisite", "items": ["cluster-admin 권한", "oc CLI 설치"]},
                                    {"kind": "procedure", "steps": [{"ordinal": 1, "text": "리소스를 확인합니다.", "substeps": ["출력 결과를 검토합니다."]}]},
                                    {"kind": "code", "language": "shell", "code": "oc get nodes", "copy_text": "oc get nodes", "wrap_hint": True, "overflow_hint": "toggle", "caption": "예제 명령"},
                                    {"kind": "note", "variant": "warning", "title": "주의", "text": "운영 중에는 영향도를 먼저 확인합니다."},
                                ],
                            }
                        ],
                        "quality_status": "draft",
                        "quality_score": 0.0,
                        "quality_flags": [],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/architecture/index.html#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertNotIn("정리된 AST 기준의 유저용 매뉴얼북을 보여줍니다.", html)
        self.assertIn("사전 요구 사항", html)
        self.assertIn("리소스를 확인합니다.", html)
        self.assertIn("운영 중에는 영향도를 먼저 확인합니다.", html)
        self.assertIn("예제 명령", html)
        self.assertIn('data-label-active="줄바꿈 해제"', html)
        self.assertIn('title="줄바꿈 해제"', html)
        self.assertIn('class="code-block overflow-toggle is-wrapped"', html)

    def test_internal_viewer_html_renders_topic_playbook_chrome(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "backup_restore_control_plane.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "backup_restore_control_plane",
                        "title": "컨트롤 플레인 백업/복구 플레이북",
                        "source_uri": "https://example.com/backup",
                        "topic_summary": "백업과 quorum 복원 절차만 추린 토픽 플레이북입니다.",
                        "source_metadata": {
                            "source_type": "topic_playbook",
                            "derived_from_title": "Backup and restore",
                        },
                        "sections": [
                            {
                                "section_id": "backup_restore_control_plane:overview",
                                "section_key": "backup_restore_control_plane:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "section_path_label": "개요",
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/backup_restore_control_plane/index.html#overview",
                                "semantic_role": "overview",
                                "block_kinds": ["paragraph"],
                                "blocks": [
                                    {"kind": "paragraph", "text": "복구 흐름"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/backup_restore_control_plane/index.html#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("Topic Playbook", html)
        self.assertIn("백업과 quorum 복원 절차만 추린 토픽 플레이북입니다.", html)

    def test_internal_viewer_html_renders_operation_playbook_chrome(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "backup_restore_operations.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "backup_restore_operations",
                        "title": "컨트롤 플레인 백업 운영 플레이북",
                        "source_uri": "https://example.com/backup-ops",
                        "topic_summary": "백업 실행, 결과 검증, 보관 원칙만 추린 운영 절차본입니다.",
                        "source_metadata": {
                            "source_type": "operation_playbook",
                            "derived_from_title": "Backup and restore",
                        },
                        "sections": [
                            {
                                "section_id": "backup_restore_operations:overview",
                                "section_key": "backup_restore_operations:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "section_path_label": "개요",
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/backup_restore_operations/index.html#overview",
                                "semantic_role": "overview",
                                "block_kinds": ["paragraph"],
                                "blocks": [
                                    {"kind": "paragraph", "text": "운영 절차 요약"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/backup_restore_operations/index.html#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("Operation Playbook", html)
        self.assertIn("백업 실행, 결과 검증, 보관 원칙만 추린 운영 절차본입니다.", html)

    def test_internal_viewer_html_embed_mode_omits_nested_hero(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "architecture.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "architecture",
                        "title": "아키텍처",
                        "source_uri": "https://example.com/architecture",
                        "sections": [
                            {
                                "section_id": "architecture:overview",
                                "section_key": "architecture:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "section_path_label": "개요",
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#overview",
                                "semantic_role": "overview",
                                "block_kinds": ["paragraph"],
                                "blocks": [
                                    {"kind": "paragraph", "text": "임베드 본문만 보여야 합니다."},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/architecture/index.html?embed=1#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("is-embedded", html)
        self.assertNotIn('<section class="hero">', html)
        self.assertNotIn('class="section-card', html)
        self.assertIn('class="study-document study-document-embedded"', html)
        self.assertIn('class="embedded-section', html)
        self.assertIn("Quick Nav", html)
        self.assertIn('class="overlay-page-target"', html)
        self.assertIn("임베드 본문만 보여야 합니다.", html)
        self.assertIn("--bg:", html)
        self.assertIn("body.is-embedded {", html)
        self.assertNotIn("--bg: #f5f1e8;", html)

    def test_internal_viewer_html_renders_table_headers_and_code_caption(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "nodes.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "nodes",
                        "title": "노드",
                        "source_uri": "https://example.com/nodes",
                        "language_hint": "ko",
                        "pack_id": "openshift-4-20-core",
                        "inferred_version": "4.20",
                        "sections": [
                            {
                                "section_id": "nodes:overview",
                                "section_key": "nodes:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "section_path_label": "개요",
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/nodes/index.html#overview",
                                "semantic_role": "overview",
                                "block_kinds": ["code", "table"],
                                "blocks": [
                                    {
                                        "kind": "code",
                                        "language": "yaml",
                                        "code": "kind: Pod",
                                        "copy_text": "kind: Pod",
                                        "wrap_hint": True,
                                        "overflow_hint": "toggle",
                                        "caption": "Pod 오브젝트 정의(YAML)",
                                    },
                                    {
                                        "kind": "table",
                                        "headers": ["이름", "역할"],
                                        "rows": [["master-0", "control-plane"]],
                                        "caption": "노드 역할",
                                    },
                                ],
                            }
                        ],
                        "quality_status": "ready",
                        "quality_score": 0.9,
                        "quality_flags": [],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/nodes/index.html#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("Pod 오브젝트 정의(YAML)", html)
        self.assertIn("노드 역할", html)
        self.assertIn("<thead><tr><th>이름</th><th>역할</th></tr></thead>", html)

    def test_internal_viewer_html_exposes_quick_navigation_and_metrics(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "operations.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "operations",
                        "title": "운영 개요",
                        "source_uri": "https://example.com/operations",
                        "sections": [
                            {
                                "section_id": "operations:overview",
                                "section_key": "operations:overview",
                                "ordinal": 1,
                                "heading": "개요",
                                "level": 1,
                                "path": ["개요"],
                                "section_path": ["개요"],
                                "anchor": "overview",
                                "viewer_path": "/docs/ocp/4.20/ko/operations/index.html#overview",
                                "semantic_role": "overview",
                                "blocks": [{"kind": "paragraph", "text": "운영 개요입니다."}],
                            },
                            {
                                "section_id": "operations:procedure",
                                "section_key": "operations:procedure",
                                "ordinal": 2,
                                "heading": "적용 절차",
                                "level": 1,
                                "path": ["적용 절차"],
                                "section_path": ["적용 절차"],
                                "anchor": "apply",
                                "viewer_path": "/docs/ocp/4.20/ko/operations/index.html#apply",
                                "semantic_role": "procedure",
                                "blocks": [{"kind": "paragraph", "text": "절차 안내입니다."}],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/operations/index.html#overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('class="document-nav-menu"', html)
        self.assertIn(">Quick Nav</summary>", html)
        self.assertIn('href="#overview"', html)
        self.assertIn('href="#apply"', html)
        self.assertIn(">절차 1<", html)

    def test_internal_viewer_html_splits_inline_command_paragraph_into_code_box(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "installation_overview.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "installation_overview",
                        "title": "설치 개요",
                        "source_uri": "https://example.com/installation_overview",
                        "language_hint": "ko",
                        "pack_id": "openshift-4-20-core",
                        "inferred_version": "4.20",
                        "sections": [
                            {
                                "section_id": "installation:apply",
                                "section_key": "installation:apply",
                                "ordinal": 1,
                                "heading": "설치 적용",
                                "level": 1,
                                "path": ["설치 적용"],
                                "section_path": ["설치 적용"],
                                "section_path_label": "설치 적용",
                                "anchor": "apply",
                                "viewer_path": "/docs/ocp/4.20/ko/installation_overview/index.html#apply",
                                "semantic_role": "procedure",
                                "block_kinds": ["paragraph"],
                                "blocks": [
                                    {
                                        "kind": "paragraph",
                                        "text": "그런 다음 `oc apply -f install-config.yaml` 명령을 실행하여 클러스터에 적용합니다.",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/installation_overview/index.html#apply",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("그런 다음 아래 명령을 실행하여 클러스터에 적용합니다.", html)
        self.assertIn("oc apply -f install-config.yaml", html)
        self.assertIn("copyViewerCode", html)
        self.assertIn("toggleViewerCodeWrap", html)

    def test_internal_viewer_html_renders_procedure_step_command_as_code_box(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "etcd.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "etcd",
                        "title": "etcd",
                        "source_uri": "https://example.com/etcd",
                        "language_hint": "ko",
                        "pack_id": "openshift-4-20-core",
                        "inferred_version": "4.20",
                        "sections": [
                            {
                                "section_id": "etcd:backup",
                                "section_key": "etcd:backup",
                                "ordinal": 1,
                                "heading": "백업 절차",
                                "level": 1,
                                "path": ["백업 절차"],
                                "section_path": ["백업 절차"],
                                "section_path_label": "백업 절차",
                                "anchor": "backup",
                                "viewer_path": "/docs/ocp/4.20/ko/etcd/index.html#backup",
                                "semantic_role": "procedure",
                                "block_kinds": ["procedure"],
                                "blocks": [
                                    {
                                        "kind": "procedure",
                                        "steps": [
                                            {
                                                "ordinal": 1,
                                                "text": "`cluster-backup.sh` 로 snapshot과 정적 pod 리소스를 생성합니다.",
                                                "substeps": [],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/etcd/index.html#backup",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn("다음 명령으로 snapshot과 정적 pod 리소스를 생성합니다.", html)
        self.assertIn("cluster-backup.sh", html)
        self.assertIn('class="procedure-list"', html)
        self.assertIn("copyViewerCode", html)

    def test_internal_viewer_html_keeps_ascii_grid_output_unwrapped(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "support.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "support",
                        "title": "지원",
                        "source_uri": "https://example.com/support",
                        "language_hint": "ko",
                        "pack_id": "openshift-4-20-core",
                        "inferred_version": "4.20",
                        "sections": [
                            {
                                "section_id": "support:ascii-grid",
                                "section_key": "support:ascii-grid",
                                "ordinal": 1,
                                "heading": "출력 예",
                                "level": 1,
                                "path": ["출력 예"],
                                "section_path": ["출력 예"],
                                "section_path_label": "출력 예",
                                "anchor": "ascii-grid",
                                "viewer_path": "/docs/ocp/4.20/ko/support/index.html#ascii-grid",
                                "semantic_role": "example",
                                "block_kinds": ["code"],
                                "blocks": [
                                    {
                                        "kind": "code",
                                        "language": "shell-session",
                                        "wrap_hint": True,
                                        "overflow_hint": "toggle",
                                        "caption": "표 출력",
                                        "code": "+-----+-----+\n| A   | B   |\n+-----+-----+\n| 1   | 2   |\n+-----+-----+",
                                    }
                                ],
                            }
                        ],
                        "quality_status": "ready",
                        "quality_score": 0.9,
                        "quality_flags": [],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/support/index.html#ascii-grid",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('class="code-block preserve-layout overflow-toggle"', html)
        self.assertNotIn('class="code-block preserve-layout overflow-toggle is-wrapped"', html)

    def test_internal_viewer_html_renders_collapsible_highlighted_yaml_code_block(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "process.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "process",
                        "title": "Process",
                        "source_uri": "https://example.com/process",
                        "sections": [
                            {
                                "section_id": "process:yaml",
                                "section_key": "process:yaml",
                                "ordinal": 1,
                                "heading": "프로세스",
                                "level": 2,
                                "path": ["프로세스"],
                                "section_path": ["프로세스"],
                                "anchor": "yaml",
                                "viewer_path": "/docs/ocp/4.20/ko/process/index.html#yaml",
                                "semantic_role": "reference",
                                "blocks": [
                                    {
                                        "kind": "code",
                                        "language": "shell",
                                        "wrap_hint": True,
                                        "overflow_hint": "toggle",
                                        "code": "\n".join(
                                            [
                                                "spec:",
                                                "  schedule: 0 0 * * *",
                                                "  suspend: false",
                                                "  keepTagRevisions: 3",
                                                "  resources: {}",
                                                "status:",
                                                "  observedGeneration: 2",
                                                "  conditions:",
                                                '  - type: Available',
                                                '    status: \"True\"',
                                                '    lastTransitionTime: 2019-10-09T03:13:45',
                                                '    reason: Ready',
                                                '    message: \"Periodic image pruner has been created.\"',
                                                '  - type: Scheduled',
                                                '    status: \"True\"',
                                                '    reason: Scheduled',
                                            ]
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/process/index.html#yaml",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('class="code-block is-collapsible overflow-toggle is-wrapped"', html)
        self.assertIn('class="collapse-button"', html)
        self.assertIn('Show less', html)
        self.assertIn('&nbsp;&nbsp;<span class="code-token code-key">schedule:</span>', html)
        self.assertIn('class="code-token code-key">spec:</span>', html)
        self.assertIn('class="code-token code-string">&quot;True&quot;</span>', html)
        self.assertIn('class="copy-button icon-button"', html)
        self.assertIn('class="wrap-button icon-button"', html)

    def test_internal_viewer_html_renders_outline_as_toolbar_menu(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "install.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "install",
                        "title": "설치",
                        "source_uri": "https://example.com/install",
                        "sections": [
                            {
                                "section_id": "install:intro",
                                "section_key": "install:intro",
                                "ordinal": 1,
                                "heading": "설치 개요",
                                "level": 2,
                                "path": ["설치", "설치 개요"],
                                "section_path": ["설치", "설치 개요"],
                                "section_path_label": "설치 > 설치 개요",
                                "anchor": "install-overview",
                                "viewer_path": "/docs/ocp/4.20/ko/install/index.html#install-overview",
                                "semantic_role": "overview",
                                "blocks": [{"kind": "paragraph", "text": "본문"}],
                            },
                            {
                                "section_id": "install:post",
                                "section_key": "install:post",
                                "ordinal": 2,
                                "heading": "설치 후 구성",
                                "level": 2,
                                "path": ["설치", "설치 후 구성"],
                                "section_path": ["설치", "설치 후 구성"],
                                "section_path_label": "설치 > 설치 후 구성",
                                "anchor": "post-install",
                                "viewer_path": "/docs/ocp/4.20/ko/install/index.html#post-install",
                                "semantic_role": "procedure",
                                "blocks": [{"kind": "paragraph", "text": "후속"}],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/install/index.html#install-overview",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('class="document-nav-menu"', html)
        self.assertIn(">Quick Nav</summary>", html)
        self.assertIn('href="#post-install"', html)
        self.assertNotIn("Quick Navigation", html)

    def test_internal_viewer_html_preserves_raw_html_tables(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "matrix.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "matrix",
                        "title": "Matrix",
                        "source_uri": "https://example.com/matrix",
                        "sections": [
                            {
                                "section_id": "matrix:table",
                                "section_key": "matrix:table",
                                "ordinal": 1,
                                "heading": "매트릭스",
                                "level": 1,
                                "path": ["매트릭스"],
                                "section_path": ["매트릭스"],
                                "anchor": "matrix",
                                "viewer_path": "/docs/ocp/4.20/ko/matrix/index.html#matrix",
                                "semantic_role": "reference",
                                "blocks": [
                                    {
                                        "kind": "paragraph",
                                        "text": '<table><thead><tr><th colspan="2">지원</th></tr></thead><tbody><tr><td>A</td><td>B</td></tr></tbody></table>',
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/matrix/index.html#matrix",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('<th colspan="2">지원</th>', html)
        self.assertIn("<td>A</td><td>B</td>", html)

    def test_internal_viewer_html_renders_structured_table_cells(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "compatibility.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "compatibility",
                        "title": "Compatibility",
                        "source_uri": "https://example.com/compatibility",
                        "sections": [
                            {
                                "section_id": "compatibility:matrix",
                                "section_key": "compatibility:matrix",
                                "ordinal": 1,
                                "heading": "지원 매트릭스",
                                "level": 2,
                                "path": ["지원", "지원 매트릭스"],
                                "section_path": ["지원", "지원 매트릭스"],
                                "anchor": "matrix",
                                "viewer_path": "/docs/ocp/4.20/ko/compatibility/index.html#matrix",
                                "semantic_role": "reference",
                                "blocks": [
                                    {
                                        "kind": "table",
                                        "caption": "버전 호환성",
                                        "header_cells": [
                                            {"text": "플랫폼", "rowspan": 2},
                                            {"text": "지원", "colspan": 2},
                                        ],
                                        "row_cells": [
                                            [
                                                {"text": "AWS"},
                                                {"text": "4.20"},
                                                {"text": "GA"},
                                            ]
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/compatibility/index.html#matrix",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('<th rowspan="2">플랫폼</th>', html)
        self.assertIn('<th colspan="2">지원</th>', html)
        self.assertIn(">버전 호환성<", html)

    def test_internal_viewer_html_renders_figure_metadata_strip(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "networking.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "networking",
                        "title": "Networking",
                        "source_uri": "https://example.com/networking",
                        "sections": [
                            {
                                "section_id": "networking:diagram",
                                "section_key": "networking:diagram",
                                "ordinal": 1,
                                "heading": "토폴로지",
                                "level": 3,
                                "path": ["네트워킹", "토폴로지"],
                                "section_path": ["네트워킹", "토폴로지"],
                                "anchor": "topology",
                                "viewer_path": "/docs/ocp/4.20/ko/networking/index.html#topology",
                                "semantic_role": "reference",
                                "blocks": [
                                    {
                                        "kind": "figure",
                                        "src": "/playbooks/wiki-assets/networking/topology.png",
                                        "caption": "네트워크 토폴로지",
                                        "alt": "네트워크 토폴로지",
                                        "kind_label": "diagram",
                                        "diagram_type": "network_map",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/networking/index.html#topology",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn('class="figure-meta"', html)
        self.assertIn("network map", html)
        self.assertIn('class="section-card section-level-3', html)

    def test_internal_viewer_html_strips_heading_number_prefix_from_visible_title(self) -> None:
        with self._workspace() as root:
            playbook_dir = self._playbook_dir(root)
            (playbook_dir / "cli_reference.json").write_text(
                json.dumps(
                    {
                        "canonical_model": "playbook_document_v1",
                        "source_view_strategy": "playbook_ast_v1",
                        "book_slug": "cli_reference",
                        "title": "CLI Reference",
                        "source_uri": "https://example.com/cli-reference",
                        "sections": [
                            {
                                "section_id": "cli_reference:oc-expose",
                                "section_key": "cli_reference:oc-expose",
                                "ordinal": 1,
                                "heading": "2.6.1.78. oc expose",
                                "level": 4,
                                "path": [
                                    "2장. OpenShift CLI(oc)",
                                    "2.6. OpenShift CLI 개발자 명령 참조",
                                    "2.6.1. OpenShift CLI (oc) 개발자",
                                ],
                                "section_path": [
                                    "2장. OpenShift CLI(oc)",
                                    "2.6. OpenShift CLI 개발자 명령 참조",
                                    "2.6.1. OpenShift CLI (oc) 개발자",
                                ],
                                "section_path_label": "2장. OpenShift CLI(oc) > 2.6. OpenShift CLI 개발자 명령 참조 > 2.6.1. OpenShift CLI (oc) 개발자",
                                "anchor": "oc-expose",
                                "viewer_path": "/docs/ocp/4.20/ko/cli_reference/index.html#oc-expose",
                                "semantic_role": "reference",
                                "block_kinds": ["paragraph"],
                                "blocks": [
                                    {"kind": "paragraph", "text": "복제된 애플리케이션을 서비스 또는 경로로 노출"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            html = _internal_viewer_html(
                root,
                "/docs/ocp/4.20/ko/cli_reference/index.html#oc-expose",
            )

        self.assertIsNotNone(html)
        assert html is not None
        self.assertIn(">oc expose</h2>", html)
        self.assertIn("OpenShift CLI(oc) &gt; OpenShift CLI 개발자 명령 참조 &gt; OpenShift CLI (oc) 개발자", html)
        self.assertNotIn(">2.6.1.78. oc expose</h2>", html)
        self.assertNotIn("2장. OpenShift CLI(oc)", html)


AppViewersTestSupport.__test__ = False


__all__ = ["AppViewersTestSupport"]
