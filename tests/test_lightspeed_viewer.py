from __future__ import annotations

import json

from play_book_studio.answering.models import AnswerResult
from play_book_studio.http.server_support import _build_chat_payload
from play_book_studio.http.sessions import ChatSession
from play_book_studio.http import server_routes_viewer
from play_book_studio.retrieval.models import SessionContext


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
                    "```bash\noc describe pod my-pod -n demo\n```\n\n"
                    "1. `Events`를 확인합니다.\n"
                    "2. 리소스 요청량을 확인합니다."
                ),
                "referenced_documents": [{"title": "Pods", "summary": "Pod scheduling guide"}],
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
    assert "Events에서 <strong>FailedScheduling</strong> 여부를 확인합니다." in viewer_html
    assert 'class="code-block' in viewer_html
    assert "oc describe pod my-pod -n demo" in viewer_html
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
