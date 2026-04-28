from __future__ import annotations

from pathlib import Path

from play_book_studio.app import role_continuity_rehearsal


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _citation() -> dict:
    return {
        "index": 1,
        "chunk_id": "operators:1",
        "book_slug": "operators",
        "section": "Operator",
        "anchor": "operator",
        "source_url": "source",
        "viewer_path": "/viewer",
        "excerpt": "근거",
        "source_collection": "core",
    }


def _ready_runtime_dependencies() -> dict:
    return {"status": "ok", "ready": True, "failures": []}


def test_role_continuity_rehearsal_passes_all_default_turns(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):  # noqa: ARG001
        mode = str(json.get("mode") or "")
        if mode == "ops":
            answer = "답변: 먼저 대상 상태를 확인하고 이벤트와 로그를 순서대로 좁힌 뒤 필요한 조치를 적용합니다. 조치 후에는 조건, Ready 상태, 반복 이벤트 해소 여부로 검증 체크를 남깁니다. 운영자에게 넘길 때는 확인 명령, 관찰 신호, 조치 결과를 함께 정리합니다 [1]."
        else:
            answer = "답변: 학습 관점에서는 먼저 개념과 구조를 잡고, 다음으로 차이와 관계를 비교하며, 마지막으로 단계별 흐름을 이해하는 순서로 정리합니다. 초보자는 각 단계마다 공식 용어, 실제 예시, 다음 질문을 함께 붙여 학습 경로를 이어가면 됩니다 [1]."
        return _FakeResponse(
            {
                "mode": mode,
                "response_kind": "rag",
                "answer": answer,
                "citations": [_citation()],
                "cited_indices": [1],
            }
        )

    monkeypatch.setattr(role_continuity_rehearsal.requests, "post", fake_post)
    monkeypatch.setattr(role_continuity_rehearsal, "_runtime_dependency_status", lambda root: _ready_runtime_dependencies())

    payload = role_continuity_rehearsal.build_role_continuity_rehearsal(Path(__file__).resolve().parents[1])

    assert payload["status"] == "ok"
    assert payload["pass_count"] == 20
    assert payload["roles"]["operator_a"] == {"pass": 10, "total": 10}
    assert payload["roles"]["learner_b"] == {"pass": 10, "total": 10}


def test_role_continuity_rehearsal_fails_doc_locator_only(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):  # noqa: ARG001
        return _FakeResponse(
            {
                "mode": "ops",
                "response_kind": "rag",
                "answer": "답변: 먼저 `문제 해결` 문서를 여는 것이 맞습니다 [1].",
                "citations": [_citation()],
                "cited_indices": [1],
            }
        )

    monkeypatch.setattr(role_continuity_rehearsal.requests, "post", fake_post)
    monkeypatch.setattr(role_continuity_rehearsal, "_runtime_dependency_status", lambda root: _ready_runtime_dependencies())

    payload = role_continuity_rehearsal.build_role_continuity_rehearsal(Path(__file__).resolve().parents[1])

    assert payload["status"] == "fail"
    assert payload["pass_count"] == 0
    assert payload["results"][0]["checks"]["not_doc_locator_only"] is False


def test_role_continuity_rehearsal_blocks_when_runtime_dependency_is_down(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("role continuity should not call /api/chat when dependency preflight blocks")

    monkeypatch.setattr(role_continuity_rehearsal.requests, "post", fail_if_called)
    monkeypatch.setattr(
        role_continuity_rehearsal,
        "_runtime_dependency_status",
        lambda root: {"status": "blocked", "ready": False, "failures": ["qdrant: down"]},
    )

    payload = role_continuity_rehearsal.build_role_continuity_rehearsal(Path(__file__).resolve().parents[1])

    assert payload["status"] == "blocked"
    assert payload["pass_count"] == 0
    assert payload["failures"] == ["qdrant: down"]
