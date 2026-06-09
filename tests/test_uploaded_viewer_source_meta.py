from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from urllib.parse import urlencode

import psycopg

from play_book_studio.http import server_routes_viewer


class _CaptureHandler:
    def __init__(self, owner_hash: str) -> None:
        self.calls: list[tuple[HTTPStatus, dict[str, object]]] = []
        self.owner_hash = owner_hash

    def _session_owner(self) -> SimpleNamespace:
        return SimpleNamespace(owner_hash=self.owner_hash)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.calls.append((status, payload))


class _FakeCursor:
    def __init__(self, expected_owner: str) -> None:
        self.expected_owner = expected_owner
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, _sql: str, params: tuple[object, ...]) -> None:
        self.params = params

    def fetchone(self) -> dict[str, object] | None:
        owner_param = str(self.params[-1] or "")
        if owner_param != self.expected_owner:
            return None
        return {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "filename": "03. 네트워킹(03.19).pdf",
            "storage_key": "storage/uploads/sources/03-networking.pdf",
            "owner_user_id": self.expected_owner,
            "visibility": "private_user",
            "source_scope": "user_upload",
            "source_metadata": {},
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "title": "네트워킹",
            "parser_name": "internal_upload_parser",
            "parsed_metadata": {},
            "chunk_id": "33333333-3333-3333-3333-333333333333",
            "heading_title": "Service",
            "source_anchor": "chunk-service",
            "chunk_section_path": ["네트워킹", "Service"],
        }


class _FakeConnection:
    def __init__(self, expected_owner: str) -> None:
        self.cursor_obj = _FakeCursor(expected_owner)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


class _FakeStudyDocsCursor:
    def __enter__(self) -> "_FakeStudyDocsCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[object, ...]) -> None:
        return None

    def fetchone(self) -> dict[str, object]:
        return {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "filename": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
            "storage_key": "storage/study-docs/cicd.pptx",
            "owner_user_id": "",
            "visibility": "workspace_shared",
            "source_scope": "study_docs",
            "source_metadata": {},
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "title": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
            "parser_name": "kmsc-course-import",
            "parsed_metadata": {},
            "chunk_id": "33333333-3333-3333-3333-333333333333",
            "heading_title": "Git 저장소 연결",
            "source_anchor": "chunk-cicd",
            "chunk_section_path": ["CI/CD", "Git 저장소 연결"],
        }


class _FakeStudyDocsConnection:
    def __enter__(self) -> "_FakeStudyDocsConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeStudyDocsCursor:
        return _FakeStudyDocsCursor()


def test_uploaded_document_source_meta_uses_current_owner_scope(monkeypatch, tmp_path):
    owner_hash = "owner-hash-for-viewer"

    monkeypatch.setattr(
        server_routes_viewer,
        "load_settings",
        lambda _root_dir: SimpleNamespace(database_url="postgresql://unit-test"),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda _database_url, row_factory=None: _FakeConnection(owner_hash),
    )

    handler = _CaptureHandler(owner_hash)
    server_routes_viewer.handle_source_meta(
        handler,
        urlencode(
            {
                "viewer_path": (
                    "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html"
                    "#chunk-service"
                )
            }
        ),
        root_dir=tmp_path,
    )

    assert len(handler.calls) == 1
    status, payload = handler.calls[0]
    assert status == HTTPStatus.OK
    assert payload["book_slug"] == "uploaded-documents"
    assert payload["book_title"] == "네트워킹"
    assert payload["section"] == "Service"
    assert payload["section_path"] == ["네트워킹", "Service"]
    assert payload["anchor"] == "33333333-3333-3333-3333-333333333333"
    assert payload["viewer_path"] == (
        "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html"
        "#33333333-3333-3333-3333-333333333333"
    )
    assert payload["source_collection"] == "uploads"
    assert payload["boundary_truth"] == "private_user_upload_runtime"


def test_study_docs_source_meta_is_labeled_as_customer_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        server_routes_viewer,
        "load_settings",
        lambda _root_dir: SimpleNamespace(database_url="postgresql://unit-test"),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda _database_url, row_factory=None: _FakeStudyDocsConnection(),
    )

    handler = _CaptureHandler("owner-hash-for-viewer")
    server_routes_viewer.handle_source_meta(
        handler,
        urlencode(
            {
                "viewer_path": (
                    "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html"
                    "#chunk-cicd"
                )
            }
        ),
        root_dir=tmp_path,
    )

    assert len(handler.calls) == 1
    status, payload = handler.calls[0]
    assert status == HTTPStatus.OK
    assert payload["book_slug"] == "customer-data-documents"
    assert payload["source_scope"] == "study_docs"
    assert payload["source_collection"] == "customer_data"
    assert payload["source_lane"] == "customer_data"
    assert payload["pack_label"] == "Customer Data"
    assert payload["runtime_truth_label"] == "Customer Data Document"
    assert payload["boundary_badge"] == "Customer Data"
    assert payload["boundary_truth"] == "customer_data_runtime"


def test_uploaded_document_viewer_renders_upload_asset_as_source_capture():
    html = server_routes_viewer._markdownish_to_html(
        "![pdf-page-004-image-01.png](asset://asset-1)",
        asset_sources={
            "asset-1": {
                "src": "data:image/png;base64,AAAA",
                "caption": "원본 문서 캡처 · Page 4 · 836 x 775 · pdf-page-004-image-01.png",
                "width": "836",
                "height": "775",
            }
        },
    )

    assert 'class="upload-asset-figure upload-source-asset-figure"' in html
    assert 'style="--asset-width: 836px;"' in html
    assert 'class="upload-asset-frame"' in html
    assert 'width="836" height="775"' in html
    assert 'src="data:image/png;base64,AAAA"' in html
    assert "원본 문서 캡처" in html


def test_uploaded_document_viewer_marks_missing_upload_asset():
    html = server_routes_viewer._markdownish_to_html(
        "![pdf-page-001-image-01.png](asset://missing)",
        asset_sources={},
    )

    assert 'class="upload-asset-missing"' in html
    assert "이미지 asset을 찾을 수 없습니다." in html
    assert "<p>pdf-page-001-image-01.png</p>" not in html


def test_uploaded_document_viewer_renders_kmsc_course_asset_figures():
    html = server_routes_viewer._uploaded_document_course_asset_figures_html(
        {
            "metadata": {
                "image_attachments": [
                    {
                        "asset_path": "data/course_pbs/assets/unit-test__img_01.png",
                        "visual_summary": "OpenShift 콘솔에서 PV 상태를 확인하는 화면",
                        "slide_no": 12,
                        "instructional_role": "command_result_evidence",
                        "is_default_visible": True,
                    }
                ]
            }
        }
    )

    assert 'class="upload-asset-figure upload-course-asset-figure"' in html
    assert 'class="upload-asset-frame"' in html
    assert 'src="/api/v1/course/assets?path=data/course_pbs/assets/unit-test__img_01.png"' in html
    assert 'loading="lazy"' in html
    assert "OpenShift 콘솔에서 PV 상태를 확인하는 화면" in html


def test_uploaded_document_viewer_ignores_unsafe_or_hidden_course_assets():
    html = server_routes_viewer._uploaded_document_course_asset_figures_html(
        {
            "metadata": {
                "image_attachments": [
                    {
                        "asset_path": "../../secrets.png",
                        "visual_summary": "unsafe",
                    },
                    {
                        "asset_path": "data/course_pbs/assets/hidden.png",
                        "visual_summary": "hidden",
                        "exclude_from_default": True,
                    },
                ]
            }
        }
    )

    assert html == ""
