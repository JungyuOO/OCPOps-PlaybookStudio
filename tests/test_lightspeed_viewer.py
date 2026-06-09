from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.http.server_support import _build_chat_payload
from play_book_studio.http.sessions import ChatSession
from play_book_studio.http import server_routes_viewer
from play_book_studio.retrieval.models import SessionContext

ROOT = Path(__file__).resolve().parents[1]


def test_lightspeed_external_answer_is_added_as_related_link(tmp_path):
    result = AnswerResult(
        query="Pod Pending이면?",
        mode="chat",
        answer="답변: Events를 확인합니다 [1].",
        rewritten_query="Pod Pending이면?",
        citations=[],
        cited_indices=[],
        pipeline_trace={
            "answer_source": "lightspeed_with_pbs_rag",
            "external_answer": {
                "status": "used",
                "viewer_path": "/external/lightspeed/unit-test",
                "label": "OpenShift Lightspeed 공식 답변",
                "source_lane": "openshift_lightspeed",
                "boundary_truth": "external_openshift_lightspeed",
                "runtime_truth_label": "OpenShift Lightspeed",
                "boundary_badge": "Lightspeed",
            },
        },
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)

    assert payload["answer_source"] == "lightspeed_with_pbs_rag"
    assert payload["related_links"][0]["href"] == "/external/lightspeed/unit-test"
    assert payload["related_links"][0]["boundary_badge"] == "Lightspeed"
    assert payload["related_links"][0]["source_lane"] == "openshift_lightspeed"


def test_lightspeed_external_answer_keeps_supporting_gold_citations(tmp_path):
    result = AnswerResult(
        query="클러스터 이벤트중 워닝만 필터링할수있어?",
        mode="chat",
        answer="답변: `oc get events --field-selector type=Warning` 명령을 사용합니다. [1]",
        rewritten_query="클러스터 이벤트중 워닝만 필터링할수있어?",
        citations=[
            Citation(
                index=1,
                chunk_id="gold-1",
                book_slug="support",
                section="지원",
                anchor="cleaning-crio-storage",
                source_url="",
                viewer_path="/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage",
                excerpt="Gold Playbook fallback citation",
                section_path=("지원",),
            )
        ],
        cited_indices=[1],
        pipeline_trace={
            "answer_source": "lightspeed_with_pbs_rag",
            "external_answer": {
                "status": "used",
                "viewer_path": "/external/lightspeed/unit-test",
                "label": "OpenShift Lightspeed 공식 답변",
                "source_lane": "openshift_lightspeed",
                "boundary_truth": "external_openshift_lightspeed",
                "runtime_truth_label": "OpenShift Lightspeed",
                "boundary_badge": "Lightspeed",
            },
        },
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=ROOT, session=session, result=result)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert payload["answer_source"] == "lightspeed_with_pbs_rag"
    assert payload["citations"][0] == {
        "index": 1,
        "book_slug": "openshift_lightspeed",
        "book_title": "OpenShift Lightspeed",
        "section": "OpenShift Lightspeed 공식 답변",
        "section_path": ["OpenShift Lightspeed 공식 답변"],
        "section_path_label": "OpenShift Lightspeed 공식 답변",
        "heading_title": "OpenShift Lightspeed 공식 답변",
        "viewer_path": "/external/lightspeed/unit-test",
        "excerpt": "OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변",
        "source_label": "OpenShift Lightspeed 공식 답변",
        "source_collection": "external_tool",
        "source_lane": "openshift_lightspeed",
        "approval_state": "external",
        "publication_state": "external",
        "boundary_truth": "external_openshift_lightspeed",
        "runtime_truth_label": "OpenShift Lightspeed",
        "boundary_badge": "Lightspeed",
        "cli_commands": [],
        "verification_hints": [],
    }
    assert len(payload["citations"]) == 2
    assert payload["citations"][1]["index"] == 2
    assert (
        payload["citations"][1]["viewer_path"]
        == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
    )
    assert (
        payload["citations"][1]["href"]
        == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
    )
    assert payload["citations"][1]["boundary_badge"] == "Gold Playbook"
    assert payload["related_links"][0] == {
        "label": "OpenShift Lightspeed 공식 답변",
        "href": "/external/lightspeed/unit-test",
        "kind": "external_tool",
        "summary": "OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변",
        "source_lane": "openshift_lightspeed",
        "boundary_truth": "external_openshift_lightspeed",
        "runtime_truth_label": "OpenShift Lightspeed",
        "boundary_badge": "Lightspeed",
    }
    assert any(
        link.get("href") == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
        for link in payload["related_links"]
    )
    assert any(
        section.get("href") == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
        for section in payload["related_sections"]
    )
    assert "/external/lightspeed/unit-test" in payload_text
    assert "/playbooks/wiki-runtime/active/support" in payload_text
    assert "Gold Playbook fallback citation" in payload_text


def test_lightspeed_external_answer_marks_customer_upload_context(tmp_path):
    result = AnswerResult(
        query="OpenShift PipelineRun이 안 뜨면 어디부터 확인해?",
        mode="chat",
        answer="답변: 이벤트와 PipelineRun 생성을 확인합니다. [1]",
        rewritten_query="OpenShift PipelineRun이 안 뜨면 어디부터 확인해?",
        citations=[
            Citation(
                index=1,
                chunk_id="ci-webhook",
                book_slug="uploaded-documents",
                section="Webhook 설정",
                anchor="ci-webhook",
                source_url="uploads/sources/ci.pdf",
                viewer_path="/uploads/documents/11111111-1111-1111-1111-111111111111/index.html#ci-webhook",
                excerpt="고객 CI 문서는 smee URL과 Webhook secret 설정을 설명합니다.",
                section_path=("CI 순서", "Webhook 설정"),
                source_collection="uploads",
            )
        ],
        cited_indices=[1],
        pipeline_trace={
            "answer_source": "lightspeed_with_pbs_rag",
            "external_answer": {
                "status": "used",
                "viewer_path": "/external/lightspeed/unit-test",
                "label": "OpenShift Lightspeed 공식 답변",
                "source_lane": "openshift_lightspeed",
                "boundary_truth": "external_openshift_lightspeed",
                "runtime_truth_label": "OpenShift Lightspeed",
                "boundary_badge": "Lightspeed",
                "context_bridge": {
                    "customer_context_applied": True,
                    "customer_context_citation_count": 1,
                    "bridge_label": "OpenShift Lightspeed + Customer Context",
                },
            },
        },
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)

    assert payload["answer_source"] == "lightspeed_with_pbs_rag"
    assert payload["primary_source_lane"] == "lightspeed_customer_context_bridge"
    assert payload["primary_boundary_truth"] == "external_lightspeed_with_customer_context"
    assert payload["primary_runtime_truth_label"] == "OpenShift Lightspeed + Customer Context"
    assert payload["primary_boundary_badge"] == "Lightspeed + Customer"
    assert payload["citations"][0]["boundary_badge"] == "Lightspeed"
    assert payload["citations"][1]["boundary_badge"] == "User Upload"
    assert payload["citations"][1]["source_lane"] == "user_upload"
    assert payload["citations"][1]["boundary_truth"] == "private_user_upload_runtime"
    assert payload["citations"][1]["book_title"] == "CI 순서"
    assert (
        payload["citations"][1]["href"]
        == "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html#ci-webhook"
    )
    assert payload["related_links"][0]["href"] == "/external/lightspeed/unit-test"


def test_lightspeed_external_answer_without_gold_keeps_external_only(tmp_path):
    result = AnswerResult(
        query="Pod Pending이면?",
        mode="chat",
        answer="답변: Events를 확인합니다 [1].",
        rewritten_query="Pod Pending이면?",
        citations=[],
        cited_indices=[],
        pipeline_trace={
            "answer_source": "lightspeed_with_pbs_rag",
            "external_answer": {
                "status": "used",
                "viewer_path": "/external/lightspeed/unit-test",
                "label": "OpenShift Lightspeed 공식 답변",
                "source_lane": "openshift_lightspeed",
                "boundary_truth": "external_openshift_lightspeed",
                "runtime_truth_label": "OpenShift Lightspeed",
                "boundary_badge": "Lightspeed",
            },
        },
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)

    assert payload["citations"] == [
        {
            "index": 1,
            "book_slug": "openshift_lightspeed",
            "book_title": "OpenShift Lightspeed",
            "section": "OpenShift Lightspeed 공식 답변",
            "section_path": ["OpenShift Lightspeed 공식 답변"],
            "section_path_label": "OpenShift Lightspeed 공식 답변",
            "heading_title": "OpenShift Lightspeed 공식 답변",
            "viewer_path": "/external/lightspeed/unit-test",
            "excerpt": "OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변",
            "source_label": "OpenShift Lightspeed 공식 답변",
            "source_collection": "external_tool",
            "source_lane": "openshift_lightspeed",
            "approval_state": "external",
            "publication_state": "external",
            "boundary_truth": "external_openshift_lightspeed",
            "runtime_truth_label": "OpenShift Lightspeed",
            "boundary_badge": "Lightspeed",
            "cli_commands": [],
            "verification_hints": [],
        }
    ]
    assert payload["related_links"] == [
        {
            "label": "OpenShift Lightspeed 공식 답변",
            "href": "/external/lightspeed/unit-test",
            "kind": "external_tool",
            "summary": "OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변",
            "source_lane": "openshift_lightspeed",
            "boundary_truth": "external_openshift_lightspeed",
            "runtime_truth_label": "OpenShift Lightspeed",
            "boundary_badge": "Lightspeed",
        }
    ]
    assert payload["related_sections"] == []


def test_pbs_gold_answer_keeps_internal_gold_citations_without_lightspeed_boundary(tmp_path):
    result = AnswerResult(
        query="CRI-O 스토리지 정리 절차 알려줘",
        mode="chat",
        answer="답변: CRI-O 스토리지 정리는 Gold Playbook 절차를 따릅니다. [1]",
        rewritten_query="CRI-O 스토리지 정리 절차 알려줘",
        citations=[
            Citation(
                index=1,
                chunk_id="gold-1",
                book_slug="support",
                section="지원",
                anchor="cleaning-crio-storage",
                source_url="",
                viewer_path="/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage",
                excerpt="Gold Playbook citation",
                section_path=("지원", "CRI-O 스토리지 정리"),
            )
        ],
        cited_indices=[1],
        pipeline_trace={"answer_source": "pbs_rag"},
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert payload["answer_source"] == "pbs_rag"
    assert payload["citations"][0]["viewer_path"] == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
    assert payload["citations"][0]["href"] == "/playbooks/wiki-runtime/active/support/index.html#cleaning-crio-storage"
    assert payload["citations"][0]["source_collection"] != "external_tool"
    assert "/external/lightspeed" not in payload_text


def test_pbs_gold_answer_rewrites_docs_citation_to_runtime_viewer_path():
    result = AnswerResult(
        query="OCP 설치 방법 종류 알려줘",
        mode="chat",
        answer="답변: 설치 방법은 플랫폼별 요구사항에 따라 선택합니다. [1]",
        rewritten_query="OCP 설치 방법 종류 알려줘",
        citations=[
            Citation(
                index=1,
                chunk_id="gold-1",
                book_slug="installing_on_any_platform",
                section="설치 방법",
                anchor="supported-installation-methods-for-different-platforms",
                source_url="/docs/ocp/4.20/ko/installing_on_any_platform/index.html",
                viewer_path="/docs/ocp/4.20/ko/installing_on_any_platform/index.html#supported-installation-methods-for-different-platforms",
                excerpt="Gold Playbook citation",
                section_path=("설치", "설치 방법"),
            )
        ],
        cited_indices=[1],
        pipeline_trace={"answer_source": "pbs_rag"},
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=ROOT, session=session, result=result)
    payload_text = json.dumps(payload, ensure_ascii=False)

    expected = (
        "/playbooks/wiki-runtime/active/installing_on_any_platform/index.html"
        "#supported-installation-methods-for-different-platforms"
    )
    assert payload["answer_source"] == "pbs_rag"
    assert payload["citations"][0]["viewer_path"] == expected
    assert payload["citations"][0]["href"] == expected
    assert payload["related_links"][0]["href"] == expected
    assert "/external/lightspeed" not in payload_text
    assert payload["citations"][0]["viewer_path"].startswith("/playbooks/wiki-runtime/active/")
    assert payload["citations"][0]["href"].startswith("/playbooks/wiki-runtime/active/")
    assert payload["related_links"][0]["href"].startswith("/playbooks/wiki-runtime/active/")


def test_internal_no_answer_does_not_create_fake_citations_or_related_links(tmp_path):
    result = AnswerResult(
        query="사내에 없는 문서 찾아줘",
        mode="chat",
        answer="답변: 현재 Playbook Library에 해당 자료가 없습니다. 자료 추가가 필요합니다.",
        rewritten_query="사내에 없는 문서 찾아줘",
        citations=[],
        cited_indices=[],
        response_kind="no_answer",
        pipeline_trace={"answer_source": "pbs_rag"},
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert payload["answer_source"] == "pbs_rag"
    assert payload["response_kind"] == "no_answer"
    assert payload["citations"] == []
    assert payload["related_links"] == []
    assert payload["related_sections"] == []
    assert payload["acquisition"]["kind"] == "repository_search"
    assert "/external/lightspeed" not in payload_text


def test_internal_clarification_does_not_create_fake_citations_or_related_links(tmp_path):
    result = AnswerResult(
        query="이거 어떻게 해?",
        mode="chat",
        answer="답변: 대상 리소스나 증상을 한 단계만 더 좁혀 주세요.",
        rewritten_query="이거 어떻게 해?",
        citations=[],
        cited_indices=[],
        response_kind="clarification",
        pipeline_trace={"answer_source": "pbs_rag"},
    )
    session = ChatSession(
        session_id="session-1",
        context=SessionContext(user_id="tester"),
    )

    payload = _build_chat_payload(root_dir=tmp_path, session=session, result=result)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert payload["answer_source"] == "pbs_rag"
    assert payload["response_kind"] == "clarification"
    assert payload["citations"] == []
    assert payload["related_links"] == []
    assert payload["related_sections"] == []
    assert "acquisition" not in payload
    assert "/external/lightspeed" not in payload_text


def test_lightspeed_artifact_opens_in_viewer(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "external_answers" / "lightspeed"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "unit-test.json").write_text(
        json.dumps(
            {
                "schema": "pbs.external_answer.lightspeed.v1",
                "artifact_id": "unit-test",
                "created_at": "2026-06-05T00:00:00Z",
                "provider": "OpenShift Lightspeed",
                "query": "Pod Pending이면?",
                "answer": (
                    "Events에서 **FailedScheduling** 여부를 확인합니다.\n\n"
                    "### 1. `kubectl describe pod` 명령으로 이벤트 확인\n"
                    "가장 먼저 파드의 상세 정보를 확인합니다.\n\n"
                    "```bash\noc describe pod my-pod -n demo\n```\n\n"
                    "Events 섹션에서 찾아야 할 주요 메시지:\n"
                    "* **FailedScheduling**: 스케줄러가 노드를 할당하지 못했습니다.\n"
                    "* `nodes are unavailable`: 노드가 NotReady 상태입니다.\n\n"
                    "1. `Events`를 확인합니다.\n"
                    "2. 리소스 요청량을 확인합니다."
                ),
                "conversation_id": "conv-viewer-1",
                "input_tokens": 10,
                "output_tokens": 20,
                "referenced_documents": [
                    {
                        "doc_title": "Pods",
                        "doc_url": "https://docs.openshift.example/pods",
                        "summary": "Pod scheduling guide",
                    }
                ],
                "truncated": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    viewer_html = server_routes_viewer._viewer_html_for_path(
        tmp_path,
        "/external/lightspeed/unit-test",
    )
    source_meta = server_routes_viewer._viewer_source_meta(
        tmp_path,
        "/external/lightspeed/unit-test",
    )

    assert viewer_html is not None
    assert "OpenShift Lightspeed 공식 답변" in viewer_html
    assert "conversation_id: conv-viewer-1" in viewer_html
    assert "referenced_documents: 1" in viewer_html
    assert "tokens: 10/20" in viewer_html
    assert "OpenShift Lightspeed 참조 문서 (1)" in viewer_html
    assert 'href="https://docs.openshift.example/pods"' in viewer_html
    assert "Events에서 <strong>FailedScheduling</strong> 여부를 확인합니다." in viewer_html
    assert "### 1." not in viewer_html
    assert "<h4>1. <code>kubectl describe pod</code> 명령으로 이벤트 확인</h4>" in viewer_html
    assert 'class="code-block' in viewer_html
    assert "oc describe pod my-pod -n demo" in viewer_html
    assert "body.external-lightspeed-viewer .code-block pre code" in viewer_html
    assert "color: #e2e8f0 !important;" in viewer_html
    assert "* <strong>FailedScheduling</strong>" not in viewer_html
    assert "<ul><li><strong>FailedScheduling</strong>: 스케줄러가 노드를 할당하지 못했습니다.</li><li><code>nodes are unavailable</code>: 노드가 NotReady 상태입니다.</li></ul>" in viewer_html
    assert "<code>Events</code>" in viewer_html
    assert "<ol><li><code>Events</code>를 확인합니다.</li><li>리소스 요청량을 확인합니다.</li></ol>" in viewer_html
    assert "**FailedScheduling**" not in viewer_html
    assert ">복사</span>" in viewer_html
    assert ".sr-only" in viewer_html
    assert source_meta is not None
    assert source_meta["title"] == "OpenShift Lightspeed 공식 답변"
    assert source_meta["book_title"] == "OpenShift Lightspeed 공식 답변"
    assert source_meta["source_label"] == "OpenShift Lightspeed 공식 답변"
    assert source_meta["boundary_badge"] == "Lightspeed"
    assert source_meta["source_collection"] == "external_tool"


def test_lightspeed_viewer_renders_markdown_tables(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "external_answers" / "lightspeed"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "table-test.json").write_text(
        json.dumps(
            {
                "schema": "pbs.external_answer.lightspeed.v1",
                "artifact_id": "table-test",
                "created_at": "2026-06-09T00:00:00Z",
                "provider": "OpenShift Lightspeed",
                "query": "openshift-lightspeed pod status",
                "answer": (
                    "`openshift-lightspeed` 네임스페이스의 Pod 목록입니다.\n\n"
                    "| Pod 이름 | READY | STATUS | RESTARTS | AGE |\n"
                    "| :--- | :--- | :--- | :--- | :--- |\n"
                    "| `lightspeed-app-server-68789c9985-tw89b` | 3/3 | **Running** | 0 | 29m |\n"
                    "| `lightspeed-console-plugin-58dbdd79fc-szgxw` | 1/1 | **Running** | 1 | 3d21h |"
                ),
                "conversation_id": "conv-table",
                "input_tokens": 4175,
                "output_tokens": 242,
                "referenced_documents": [],
                "truncated": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    viewer_html = server_routes_viewer._viewer_html_for_path(
        tmp_path,
        "/external/lightspeed/table-test",
    )

    assert viewer_html is not None
    assert '<table class="upload-table">' in viewer_html
    assert "<th>Pod 이름</th>" in viewer_html
    assert "<th>READY</th>" in viewer_html
    assert "<td><code>lightspeed-app-server-68789c9985-tw89b</code></td>" in viewer_html
    assert "<td><strong>Running</strong></td>" in viewer_html
    assert "| Pod 이름 | READY | STATUS |" not in viewer_html


def test_lightspeed_viewer_shows_when_references_are_not_provided(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "external_answers" / "lightspeed"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "no-refs-unit.json").write_text(
        json.dumps(
            {
                "schema": "pbs.external_answer.lightspeed.v1",
                "artifact_id": "no-refs-unit",
                "created_at": "2026-06-05T00:00:00Z",
                "provider": "OpenShift Lightspeed",
                "query": "사용자 권한은 어떤 명령으로 확인해?",
                "answer": "권한 확인은 `oc auth can-i` 명령을 사용합니다.",
                "conversation_id": "conv-no-refs",
                "referenced_documents": [],
                "input_tokens": 5,
                "output_tokens": 6,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    viewer_html = server_routes_viewer._viewer_html_for_path(
        tmp_path,
        "/external/lightspeed/no-refs-unit",
    )

    assert viewer_html is not None
    assert "conversation_id: conv-no-refs" in viewer_html
    assert "referenced_documents: 0" in viewer_html
    assert "OpenShift Lightspeed 참조 문서 (0)" in viewer_html
    assert "이번 OpenShift Lightspeed API 응답에는 참조 문서 목록이 포함되지 않았습니다." in viewer_html
