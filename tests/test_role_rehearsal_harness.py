from __future__ import annotations

from pathlib import Path

from play_book_studio.app import chat_matrix_smoke


class _FakeResponse:
    status_code = 200
    text = "{}"

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _citation(index: int, *, collection: str, book_slug: str) -> dict:
    return {
        "index": index,
        "chunk_id": f"{book_slug}:{index}",
        "book_slug": book_slug,
        "section": "section",
        "anchor": "section",
        "source_url": "source",
        "viewer_path": "/viewer",
        "excerpt": "근거",
        "source_collection": collection,
    }


def _vector_runtime() -> dict:
    return {
        "retrieval_trace": {
            "vector_runtime": {
                "endpoint_used": "search",
                "endpoints_used": ["search"],
                "subquery_count": 1,
                "empty_subqueries": 0,
            }
        }
    }


def _ready_runtime_dependencies() -> dict:
    return {"status": "ok", "ready": True, "failures": []}


def test_role_rehearsal_passes_operator_and_learner_contracts(monkeypatch) -> None:
    responses = {
        "ops_bridge": {
            "mode": "ops",
            "response_kind": "rag",
            "answer": "답변: 먼저 Operator 상태를 확인하고 모니터링 신호로 검증합니다 [1][2].",
            "citations": [
                _citation(1, collection="core", book_slug="monitoring"),
                _citation(2, collection="core", book_slug="operators"),
            ],
            "cited_indices": [1, 2],
            "warnings": [],
            "suggested_queries": ["다음 확인", "검증", "분기"],
            "suggested_followups": [
                {"query": "다음 확인", "dimension": "next_action"},
                {"query": "검증", "dimension": "verify"},
                {"query": "분기", "dimension": "branch"},
            ],
            **_vector_runtime(),
        },
        "ops_buildconfig": {
            "mode": "ops",
            "response_kind": "rag",
            "answer": "답변: 먼저 BuildConfig 상태를 확인하고 검증합니다 [1].\n\n```bash\noc get buildconfig\n```",
            "citations": [_citation(1, collection="core", book_slug="builds_using_buildconfig")],
            "cited_indices": [1],
            "warnings": [],
            "suggested_queries": ["다음 확인", "검증", "분기"],
            "suggested_followups": [
                {"query": "다음 확인", "dimension": "next_action"},
                {"query": "검증", "dimension": "verify"},
                {"query": "분기", "dimension": "branch"},
            ],
            **_vector_runtime(),
        },
        "learn_official": {
            "mode": "learn",
            "response_kind": "rag",
            "answer": "답변: 학습 순서는 먼저 개요와 아키텍처 개념을 잡고 Operator를 이어서 이해하는 흐름입니다 [1].",
            "citations": [_citation(1, collection="core", book_slug="overview")],
            "cited_indices": [1],
            "warnings": [],
            "suggested_queries": ["개념", "검증", "분기"],
            "suggested_followups": [
                {"query": "개념", "dimension": "next_action"},
                {"query": "검증", "dimension": "verify"},
                {"query": "분기", "dimension": "branch"},
            ],
            **_vector_runtime(),
        },
        "learn_blend": {
            "mode": "learn",
            "response_kind": "rag",
            "answer": "답변: 학습 경로는 고객 맥락 -> 공식 개념 -> 차이점 정리 순서입니다 [1][2].",
            "citations": [
                _citation(1, collection="uploaded", book_slug="customer-master-kmsc-ocp-operations-playbook"),
                _citation(2, collection="core", book_slug="overview"),
            ],
            "cited_indices": [1, 2],
            "warnings": [],
            "suggested_queries": ["개념", "검증", "분기"],
            "suggested_followups": [
                {"query": "개념", "dimension": "next_action"},
                {"query": "검증", "dimension": "verify"},
                {"query": "분기", "dimension": "branch"},
            ],
            **_vector_runtime(),
        },
        "learn_same_question": {
            "mode": "learn",
            "response_kind": "rag",
            "answer": "답변: 같은 Operator 문제도 학습자는 개념, 역할, 확인 순서를 먼저 이해한 뒤 상태를 해석하는 순서로 봅니다 [1].",
            "citations": [_citation(1, collection="core", book_slug="operators")],
            "cited_indices": [1],
            "warnings": [],
            "suggested_queries": ["개념", "검증", "분기"],
            "suggested_followups": [
                {"query": "개념", "dimension": "next_action"},
                {"query": "검증", "dimension": "verify"},
                {"query": "분기", "dimension": "branch"},
            ],
            **_vector_runtime(),
        },
    }

    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):  # noqa: ARG001
        mode = str(json.get("mode") or "")
        query = str(json.get("query") or "")
        if mode == "ops" and "BuildConfig" in query:
            return _FakeResponse(responses["ops_buildconfig"])
        if mode == "ops":
            return _FakeResponse(responses["ops_bridge"])
        if "고객 PPT" in query:
            return _FakeResponse(responses["learn_blend"])
        if "처음 만났을 때" in query:
            return _FakeResponse(responses["learn_same_question"])
        return _FakeResponse(responses["learn_official"])

    monkeypatch.setattr(chat_matrix_smoke.requests, "post", fake_post)
    monkeypatch.setattr(chat_matrix_smoke, "_runtime_dependency_status", lambda root: _ready_runtime_dependencies())

    payload = chat_matrix_smoke.build_role_rehearsal(
        Path(__file__).resolve().parents[1],
        cases_path=None,
    )

    assert payload["status"] == "ok"
    assert payload["roles"]["operator_a"] == {"pass": 3, "total": 3}
    assert payload["roles"]["learner_b"] == {"pass": 3, "total": 3}
    assert payload["contrast_checks"][0]["pass"] is True


def test_role_rehearsal_fails_when_learner_is_short_circuited_to_guide(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):  # noqa: ARG001
        return _FakeResponse(
            {
                "mode": "learn",
                "response_kind": "guide",
                "answer": "답변: 일반적인 학습 조언입니다.",
                "citations": [],
                "cited_indices": [],
                "warnings": [],
                "suggested_queries": [],
                "suggested_followups": [],
            }
        )

    monkeypatch.setattr(chat_matrix_smoke.requests, "post", fake_post)
    monkeypatch.setattr(chat_matrix_smoke, "_runtime_dependency_status", lambda root: _ready_runtime_dependencies())

    payload = chat_matrix_smoke.build_role_rehearsal(
        Path(__file__).resolve().parents[1],
        cases_path=None,
    )

    assert payload["status"] == "fail"
    first = payload["results"][0]
    assert first["checks"]["response_kind_rag"] is False
    assert first["checks"]["min_citations"] is False


def test_role_rehearsal_fails_when_citation_metadata_is_not_linkable(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):  # noqa: ARG001
        return _FakeResponse(
            {
                "mode": "ops" if json.get("mode") == "ops" else "learn",
                "response_kind": "rag",
                "answer": "답변: 먼저 상태를 확인하고 근거를 봅니다 [1].",
                "citations": [{"index": 1, "book_slug": "operators", "source_collection": "core"}],
                "cited_indices": [1],
                "warnings": [],
                "suggested_queries": ["다음 확인", "검증", "분기"],
                "suggested_followups": [
                    {"query": "다음 확인", "dimension": "next_action"},
                    {"query": "검증", "dimension": "verify"},
                    {"query": "분기", "dimension": "branch"},
                ],
                **_vector_runtime(),
            }
        )

    monkeypatch.setattr(chat_matrix_smoke.requests, "post", fake_post)
    monkeypatch.setattr(chat_matrix_smoke, "_runtime_dependency_status", lambda root: _ready_runtime_dependencies())

    payload = chat_matrix_smoke.build_role_rehearsal(
        Path(__file__).resolve().parents[1],
        cases_path=None,
    )

    assert payload["status"] == "fail"
    first = payload["results"][0]
    assert first["checks"]["citation_metadata"] is False
    assert first["citation_metadata_gaps"]


def test_role_rehearsal_blocks_before_cases_when_runtime_dependency_is_down(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("role rehearsal should not call /api/chat when preflight blocks")

    monkeypatch.setattr(chat_matrix_smoke.requests, "post", fail_if_called)
    monkeypatch.setattr(
        chat_matrix_smoke,
        "_runtime_dependency_status",
        lambda root: {"status": "blocked", "ready": False, "failures": ["qdrant: connection refused"]},
    )

    payload = chat_matrix_smoke.build_role_rehearsal(
        Path(__file__).resolve().parents[1],
        cases_path=None,
    )

    assert payload["status"] == "blocked"
    assert payload["pass_count"] == 0
    assert payload["roles"]["operator_a"] == {"pass": 0, "total": 3}
    assert payload["roles"]["learner_b"] == {"pass": 0, "total": 3}
    assert payload["results"][0]["checks"]["runtime_dependency_preflight"] is False
