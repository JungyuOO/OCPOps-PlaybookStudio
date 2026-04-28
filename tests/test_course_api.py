from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from play_book_studio.app.course_api import (
    _apply_course_answer_typography,
    _course_answer_style_issues,
    _course_chat_payload,
    _load_chunk,
    _resolve_course_path,
    course_viewer_html,
    course_viewer_source_meta,
    handle_course_get,
)


def _write_chunk(root: Path, chunk_id: str, payload: dict) -> None:
    chunks_dir = root / "data" / "course_pbs" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / f"{chunk_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_chunks_jsonl(root: Path, rows: list[dict]) -> None:
    course_dir = root / "data" / "course_pbs"
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_manifest(root: Path, payload: dict) -> None:
    manifests_dir = root / "data" / "course_pbs" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "course_v1.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_guides(root: Path, payload: dict) -> None:
    manifests_dir = root / "data" / "course_pbs" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "ops_learning_guides_v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_learning_chunks(root: Path, rows: list[dict]) -> None:
    manifests_dir = root / "data" / "course_pbs" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "ops_learning_chunks_v1.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


@contextmanager
def _temp_root() -> Iterator[Path]:
    temp_parent = Path.cwd() / ".pytest-tmp" / "course-api"
    temp_parent.mkdir(parents=True, exist_ok=True)
    root = temp_parent / f"case-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    yield root


def test_load_chunk_rejects_path_traversal_ids() -> None:
    with _temp_root() as root:
        with pytest.raises(ValueError):
            _load_chunk(root, "../secret")


def test_load_chunk_reads_consolidated_chunks_jsonl() -> None:
    with _temp_root() as root:
        _write_chunks_jsonl(
            root,
            [
                {
                    "chunk_id": "chunk-01",
                    "title": "단일 파일 청크",
                    "body_md": "chunks.jsonl에서 읽는다.",
                }
            ],
        )

        payload = _load_chunk(root, "chunk-01")

    assert payload["title"] == "단일 파일 청크"
    assert payload["schema_version"] == "ppt_chunk_v1"


def test_resolve_course_path_rejects_assets_outside_workspace() -> None:
    with _temp_root() as root:
        outside = root.parent / "outside.png"

        with pytest.raises(ValueError):
            _resolve_course_path(root, str(outside))


def test_course_answer_style_issues_detects_korean_spacing_artifacts() -> None:
    answer = "HPA 는 기본값인 15 초마다 metrics-server 로부터 대상 Pod 의 CPU를 수집하고 Pod 를 확장합니다. [1]"

    issues = _course_answer_style_issues(answer)
    cleaned = _apply_course_answer_typography(answer)

    assert "HPA 는" in issues
    assert "15 초" in issues
    assert "metrics-server 로부터" in issues
    assert "Pod 의" in issues
    assert "Pod 를" in issues
    assert cleaned == "HPA는 기본값인 15초마다 metrics-server로부터 대상 Pod의 CPU를 수집하고 Pod를 확장합니다. [1]"


def test_course_asset_endpoint_serves_only_course_assets() -> None:
    class Handler:
        def __init__(self) -> None:
            self.json_payload = None
            self.status = None
            self.bytes_payload = b""
            self.content_type = ""

        def _send_json(self, payload: dict, status=200) -> None:  # noqa: ANN001
            self.json_payload = payload
            self.status = status

        def _send_bytes(self, payload: bytes, *, content_type: str) -> None:
            self.bytes_payload = payload
            self.content_type = content_type

    with _temp_root() as root:
        asset = root / "data" / "course_pbs" / "assets" / "a.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"png-bytes")

        handler = Handler()
        handled = handle_course_get(handler, "/api/v1/course/assets", "path=data/course_pbs/assets/a.png", root_dir=root)

        assert handled is True
        assert handler.bytes_payload == b"png-bytes"
        assert handler.content_type == "image/png"

        blocked = Handler()
        handle_course_get(blocked, "/api/v1/course/assets", "path=data/course_pbs/chunks/a.json", root_dir=root)
        assert blocked.status == 400


def test_course_asset_endpoint_converts_browser_incompatible_image_payloads() -> None:
    class Handler:
        def __init__(self) -> None:
            self.json_payload = None
            self.status = None
            self.bytes_payload = b""
            self.content_type = ""

        def _send_json(self, payload: dict, status=200) -> None:  # noqa: ANN001
            self.json_payload = payload
            self.status = status

        def _send_bytes(self, payload: bytes, *, content_type: str) -> None:
            self.bytes_payload = payload
            self.content_type = content_type

    with _temp_root() as root:
        from PIL import Image

        asset = root / "data" / "course_pbs" / "assets" / "wmf-like.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2, 2), color="white").save(asset, format="BMP")

        handler = Handler()
        handled = handle_course_get(handler, "/api/v1/course/assets", "path=data/course_pbs/assets/wmf-like.png", root_dir=root)

        assert handled is True
        assert handler.content_type == "image/png"
        assert handler.bytes_payload.startswith(b"\x89PNG\r\n\x1a\n")


def test_course_chat_uses_ops_learning_guide_before_raw_chunk_route() -> None:
    with _temp_root() as root:
        current_chunk_id = "perf-current"
        next_chunk_id = "perf-next"
        _write_chunk(
            root,
            current_chunk_id,
            {
                "chunk_id": current_chunk_id,
                "stage_id": "perf_test",
                "title": "성능 테스트 결과",
                "native_id": "PERF-4",
                "body_md": "DB SQL 응답 지연과 DB Connection Pool 대기를 확인한다.",
                "search_text": "PERF-4 DB SQL 응답 지연 DB Connection Pool worker-thread HPA HAProxy",
            },
        )
        _write_chunk(
            root,
            next_chunk_id,
            {
                "chunk_id": next_chunk_id,
                "stage_id": "perf_test",
                "title": "개선 권고",
                "native_id": "PERF-5",
                "body_md": "DB Connection Pool과 worker-thread 조정을 확인한다.",
                "search_text": "개선 권고 DB Connection Pool worker-thread JVM",
            },
        )
        _write_guides(
            root,
            {
                "canonical_model": "ops_learning_guide_v1",
                "guides": [
                    {
                        "guide_id": "performance_bottleneck_review",
                        "stage_id": "perf_test",
                        "title": "성능 테스트 병목 분석 흐름",
                        "steps": [
                            {
                                "step_id": "perf_result_bottleneck",
                                "stage_id": "perf_test",
                                "card_text": "병목과 개선 포인트 확인하기",
                                "user_query": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
                                "learning_objective": "DB SQL 응답 지연, Connection Pool, HPA를 순서대로 확인한다.",
                                "answer_outline": [
                                    "먼저 전체 응답시간 지연 구간을 확인한다.",
                                    "DB SQL 응답 지연과 DB Connection Pool 대기 여부를 함께 본다.",
                                ],
                                "source_anchors": [{"chunk_id": current_chunk_id, "native_id": "PERF-4", "hidden_from_user": True}],
                                "next_step_ids": ["perf_improvement_actions"],
                            },
                            {
                                "step_id": "perf_improvement_actions",
                                "stage_id": "perf_test",
                                "card_text": "개선 권고 정리하기",
                                "user_query": "성능 개선 권고는 어떤 항목부터 정리하면 돼?",
                                "learning_objective": "개선 후보를 정리한다.",
                                "answer_outline": ["DB Connection Pool과 worker-thread를 조정 포인트로 본다."],
                                "source_anchors": [{"chunk_id": next_chunk_id, "native_id": "PERF-5", "hidden_from_user": True}],
                                "next_step_ids": [],
                            },
                        ],
                    }
                ],
            },
        )

        response = _course_chat_payload(
            root,
            {"message": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?", "stage_id": "perf_test"},
        )

    assert response["sources"][0]["chunk_id"] == current_chunk_id
    assert "PERF-4" not in response["answer"]
    assert "DB SQL 응답 지연" in response["answer"]
    assert "원문 근거" not in response["answer"]
    assert response["suggested_queries"] == ["성능 개선 권고는 어떤 항목부터 정리하면 돼?"]
    guided = next(item for item in response["artifacts"] if item["kind"] == "course_guided_tour")
    assert [item["role"] for item in guided["items"]] == ["current", "next"]


def test_course_chat_retrieves_ops_learning_chunk_without_exact_golden_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    monkeypatch.setattr("play_book_studio.app.course_api.search_ops_learning_chunks", lambda settings, query, top_k=5: [])
    with _temp_root() as root:
        source_id = "perf-source"
        next_source_id = "perf-next"
        _write_chunk(
            root,
            source_id,
            {
                "chunk_id": source_id,
                "stage_id": "perf_test",
                "title": "Performance result",
                "native_id": "PERF-4",
                "body_md": "DB SQL response latency and DB Connection Pool waits are the first bottleneck evidence. HPA scale-out is checked next.",
                "search_text": "DB SQL response latency DB Connection Pool worker-thread HPA HAProxy bottleneck",
                "related_official_docs": [],
            },
        )
        _write_chunk(
            root,
            next_source_id,
            {
                "chunk_id": next_source_id,
                "stage_id": "perf_test",
                "title": "Improvement action",
                "native_id": "PERF-5",
                "body_md": "Tune DB Connection Pool and worker-thread settings.",
                "search_text": "DB Connection Pool worker-thread improvement",
                "related_official_docs": [],
            },
        )
        _write_learning_chunks(
            root,
            [
                {
                    "learning_chunk_id": "performance_bottleneck_review::perf_result_bottleneck",
                    "chunk_type": "ops_learning_step",
                    "guide_id": "performance_bottleneck_review",
                    "step_id": "perf_result_bottleneck",
                    "stage_id": "perf_test",
                    "title": "성능 병목 확인",
                    "learning_goal": "DB 응답 지연과 Connection Pool 대기를 먼저 확인한다.",
                    "beginner_explanation": "성능 결과에서 병목 근거를 운영자가 볼 수 있게 정리한다.",
                    "operational_sequence": [
                        "DB SQL response latency evidence를 먼저 확인한다.",
                        "HPA 지표 수집 HPA는 설정된 시간 간격(default 15초)마다 metrics-server로 부터 대상 POD들의 현재 지표(CPU 사용량, Memory 사용률)를 수집 Scale-out : POD 확장, 설정된 max 값 까지 기준을 초과하면 POD를 늘림 15초 마다 수집된 지표를 통해 설정된 기준을 초과하면 Scale-out 이 발생",
                        "DB Connection Pool waits와 worker-thread 관계를 확인한다.",
                    ],
                    "what_to_look_for": ["DB SQL response latency", "DB Connection Pool", "HPA"],
                    "source_chunk_ids": [source_id],
                    "hidden_native_ids": ["PERF-4"],
                    "next_step_ids": ["perf_improvement_actions"],
                    "query_variants": [
                        "성능 병목은 어디부터 보면 돼?",
                        "Connection Pool 대기는 성능 결과에서 어떻게 확인해?",
                    ],
                },
                {
                    "learning_chunk_id": "performance_bottleneck_review::perf_improvement_actions",
                    "chunk_type": "ops_learning_step",
                    "guide_id": "performance_bottleneck_review",
                    "step_id": "perf_improvement_actions",
                    "stage_id": "perf_test",
                    "title": "개선 권고 정리",
                    "learning_goal": "DB Connection Pool과 worker-thread 조정 항목을 정리한다.",
                    "operational_sequence": ["Tune DB Connection Pool and worker-thread settings."],
                    "what_to_look_for": ["DB Connection Pool", "worker-thread"],
                    "source_chunk_ids": [next_source_id],
                    "hidden_native_ids": ["PERF-5"],
                    "next_step_ids": [],
                    "query_variants": ["성능 개선 권고는 어떤 항목부터 정리하면 돼?"],
                },
            ],
        )

        response = _course_chat_payload(root, {"message": "Connection Pool 대기가 보이면 병목은 어디서 확인해?", "stage_id": "perf_test"})

    assert response["sources"][0]["chunk_id"] == source_id
    assert "PERF-4" not in response["answer"]
    assert "DB Connection Pool" in response["answer"]
    assert "원문 근거" not in response["answer"]
    assert "Tune DB Connection Pool" not in response["answer"]
    assert response["suggested_queries"]
    assert any("개선" in query or "Connection Pool" in query for query in response["suggested_queries"])
    guided = next(item for item in response["artifacts"] if item["kind"] == "course_guided_tour")
    assert [item["role"] for item in guided["items"]] == ["current", "next"]
    assert all(not str(item["reason"]).startswith("retrieved_context_variant") for item in guided["items"])


def test_course_chat_rewrites_ops_learning_answer_with_llm_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeLLMClient:
        def __init__(self, settings: Any) -> None:
            captured["settings_model"] = settings.llm_model

        def generate(self, messages: list[dict[str, str]], *, max_tokens: int | None = None, trace_callback=None) -> str:  # noqa: ANN001
            del trace_callback
            captured["messages"] = messages
            captured["max_tokens"] = max_tokens
            prompt_text = "\n".join(message["content"] for message in messages)
            if "selected_learning_chunk_ids" in prompt_text and "후보(JSON)" in prompt_text:
                return json.dumps(
                    {
                        "selected_learning_chunk_ids": ["performance_bottleneck_review::perf_result_bottleneck"],
                        "rejected_learning_chunk_ids": [],
                        "reason": "질문이 성능 병목 확인을 묻고 있습니다.",
                    },
                    ensure_ascii=False,
                )
            return (
                "Study-docs 기준 성능 병목은 먼저 DB 응답 지연과 Connection Pool 대기를 확인하고, "
                "그 다음 HPA의 지표 수집과 scale-out 반응을 함께 보면 됩니다. [9]\n"
                "- metrics-server에서 수집되는 CPU/Memory 지표가 기준을 넘는지 확인합니다. [9]\n"
                "- 기준 초과 시 Pod 확장이 일어나는지 보고, 다음 단계에서 개선 권고를 정리합니다. [9]"
            )

    monkeypatch.setenv("COURSE_CHAT_LLM_REWRITE", "true")
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake-llm/v1")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    monkeypatch.setattr("play_book_studio.app.course_api.LLMClient", FakeLLMClient)
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    monkeypatch.setattr("play_book_studio.app.course_api.search_ops_learning_chunks", lambda settings, query, top_k=5: [])

    with _temp_root() as root:
        source_id = "perf-source"
        _write_chunk(
            root,
            source_id,
            {
                "chunk_id": source_id,
                "stage_id": "perf_test",
                "title": "Performance result",
                "native_id": "PERF-4",
                "body_md": "DB SQL response latency and DB Connection Pool waits are the first bottleneck evidence.",
                "search_text": "DB SQL response latency DB Connection Pool HPA bottleneck",
                "related_official_docs": [],
            },
        )
        _write_learning_chunks(
            root,
            [
                {
                    "learning_chunk_id": "performance_bottleneck_review::perf_result_bottleneck",
                    "chunk_type": "ops_learning_step",
                    "guide_id": "performance_bottleneck_review",
                    "step_id": "perf_result_bottleneck",
                    "stage_id": "perf_test",
                    "title": "성능 병목 확인",
                    "learning_goal": "DB 응답 지연과 Connection Pool 대기를 먼저 확인한다.",
                    "operational_sequence": [
                        "HPA 지표 수집 HPA는 설정된 시간 간격(default 15초)마다 metrics-server로 부터 대상 POD들의 현재 지표(CPU 사용량, Memory 사용률)를 수집 Scale-out : POD 확장, 설정된 max 값 까지 기준을 초과하면 POD를 늘림"
                    ],
                    "what_to_look_for": ["DB SQL response latency", "DB Connection Pool", "HPA"],
                    "source_chunk_ids": [source_id],
                    "hidden_native_ids": ["PERF-4"],
                    "next_step_ids": [],
                    "query_variants": ["성능 병목은 어디부터 보면 돼?"],
                }
            ],
        )

        response = _course_chat_payload(root, {"message": "성능 병목은 어디부터 보면 돼?", "stage_id": "perf_test"})

    assert response["answer_rewrite"] == {"mode": "llm"}
    assert response["answer_generation"]["selector"]["mode"] == "fallback"
    assert not response["answer"].startswith("Study-docs 기준")
    assert "scale-out 반응" in response["answer"]
    assert "Scale-out : POD 확장" not in response["answer"]
    assert "[1]" in response["answer"]
    assert "[9]" not in response["answer"]
    prompt_text = "\n".join(message["content"] for message in captured["messages"])
    assert "청크 문장을 그대로 복사하지 말고" in prompt_text
    assert "'HPA 는'이 아니라 'HPA는'" in prompt_text
    assert "Scale-out : POD 확장" in prompt_text
    assert "Scale-out은 Pod를 확장하는 동작입니다" in prompt_text


def test_course_chat_llm_selector_chooses_grounding_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLLMClient:
        def __init__(self, settings: Any) -> None:
            del settings

        def generate(self, messages: list[dict[str, str]], *, max_tokens: int | None = None, trace_callback=None) -> str:  # noqa: ANN001
            del max_tokens, trace_callback
            prompt_text = "\n".join(message["content"] for message in messages)
            if "selected_learning_chunk_ids" in prompt_text and "후보(JSON)" in prompt_text:
                return json.dumps(
                    {
                        "selected_learning_chunk_ids": ["guide::selected"],
                        "rejected_learning_chunk_ids": ["guide::rejected"],
                        "reason": "사용자 질문은 선택 후보의 운영 절차에 직접 연결됩니다.",
                    },
                    ensure_ascii=False,
                )
            return "선택된 근거 기준으로 운영 절차를 먼저 확인하고, 관련 지표를 이어서 점검합니다. [1]"

    monkeypatch.setenv("COURSE_CHAT_LLM_REWRITE", "true")
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake-llm/v1")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    monkeypatch.setattr("play_book_studio.app.course_api.LLMClient", FakeLLMClient)
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    monkeypatch.setattr("play_book_studio.app.course_api.search_ops_learning_chunks", lambda settings, query, top_k=5: [])

    with _temp_root() as root:
        _write_chunk(
            root,
            "source-rejected",
            {
                "chunk_id": "source-rejected",
                "stage_id": "perf_test",
                "title": "Rejected source",
                "native_id": "PERF-1",
                "body_md": "이 후보는 질문과 느슨하게만 관련됩니다.",
                "search_text": "공통 질문 loose candidate",
                "related_official_docs": [],
            },
        )
        _write_chunk(
            root,
            "source-selected",
            {
                "chunk_id": "source-selected",
                "stage_id": "perf_test",
                "title": "Selected source",
                "native_id": "PERF-2",
                "body_md": "이 후보는 사용자가 묻는 운영 절차에 직접 답합니다.",
                "search_text": "공통 질문 selected candidate",
                "related_official_docs": [],
            },
        )
        _write_learning_chunks(
            root,
            [
                {
                    "learning_chunk_id": "guide::rejected",
                    "chunk_type": "ops_learning_step",
                    "guide_id": "guide",
                    "step_id": "rejected",
                    "stage_id": "perf_test",
                    "title": "느슨한 후보",
                    "learning_goal": "공통 질문 후보",
                    "operational_sequence": ["느슨한 후보 절차"],
                    "what_to_look_for": ["loose"],
                    "source_chunk_ids": ["source-rejected"],
                    "hidden_native_ids": ["PERF-1"],
                    "next_step_ids": [],
                    "query_variants": ["공통 질문"],
                },
                {
                    "learning_chunk_id": "guide::selected",
                    "chunk_type": "ops_learning_step",
                    "guide_id": "guide",
                    "step_id": "selected",
                    "stage_id": "perf_test",
                    "title": "선택 후보",
                    "learning_goal": "공통 질문 후보",
                    "operational_sequence": ["선택된 운영 절차"],
                    "what_to_look_for": ["selected"],
                    "source_chunk_ids": ["source-selected"],
                    "hidden_native_ids": ["PERF-2"],
                    "next_step_ids": [],
                    "query_variants": ["공통 질문"],
                },
            ],
        )

        response = _course_chat_payload(root, {"message": "공통 질문", "stage_id": "perf_test"})

    assert response["sources"][0]["chunk_id"] == "source-selected"
    assert all(source["chunk_id"] != "source-rejected" for source in response["sources"])
    assert response["answer_generation"]["selector"]["mode"] == "llm"
    assert response["answer_generation"]["selected_learning_chunk_ids"] == ["guide::selected"]
    assert response["answer_generation"]["selector"]["rejected_learning_chunk_ids"] == ["guide::rejected"]
    assert response["answer"] == "선택된 근거 기준으로 운영 절차를 먼저 확인하고, 관련 지표를 이어서 점검합니다. [1]"


def test_course_stage_payload_prefers_ops_learning_guide_cards() -> None:
    class Handler:
        def __init__(self) -> None:
            self.json_payload = None
            self.status = None

        def _send_json(self, payload: dict, status=200) -> None:  # noqa: ANN001
            self.json_payload = payload
            self.status = status

    with _temp_root() as root:
        chunk_id = "perf-current"
        _write_manifest(
            root,
            {
                "stages": [
                    {
                        "stage_id": "perf_test",
                        "title": "성능 테스트",
                        "chunk_refs": [chunk_id],
                        "learning_route": {"start_here": [chunk_id], "then_open": [], "why_this_order": ""},
                    }
                ]
            },
        )
        _write_chunk(
            root,
            chunk_id,
            {
                "chunk_id": chunk_id,
                "stage_id": "perf_test",
                "title": "성능 테스트 결과",
                "native_id": "PERF-4",
                "body_md": "DB SQL 응답 지연과 DB Connection Pool 대기를 확인한다.",
                "search_text": "PERF-4 DB SQL 응답 지연 DB Connection Pool",
                "slide_refs": [{"slide_no": 1}],
            },
        )
        _write_guides(
            root,
            {
                "canonical_model": "ops_learning_guide_v1",
                "guides": [
                    {
                        "guide_id": "performance_bottleneck_review",
                        "stage_id": "perf_test",
                        "entry_step_id": "perf_result_bottleneck",
                        "step_ids": ["perf_result_bottleneck"],
                        "steps": [
                            {
                                "step_id": "perf_result_bottleneck",
                                "stage_id": "perf_test",
                                "card_text": "병목과 개선 포인트 확인하기",
                                "user_query": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
                                "learning_objective": "DB SQL 응답 지연과 Connection Pool을 확인한다.",
                                "source_anchors": [{"chunk_id": chunk_id, "native_id": "PERF-4", "hidden_from_user": True}],
                                "quality": {"status": "draft", "needs_review": []},
                            }
                        ],
                    }
                ],
            },
        )

        handler = Handler()
        handled = handle_course_get(handler, "/api/v1/course/stages/perf_test", "", root_dir=root)

    assert handled is True
    card = handler.json_payload["guided_cards"]["start_here"][0]
    assert card["guide_id"] == "performance_bottleneck_review"
    assert card["step_id"] == "perf_result_bottleneck"
    assert card["label"] == "병목과 개선 포인트 확인하기"
    assert card["source"]["hidden_doc_anchor"] is True


def test_load_chunk_projects_missing_index_contract_fields() -> None:
    with _temp_root() as root:
        _write_chunk(
            root,
            "chunk-01",
            {
                "chunk_id": "chunk-01",
                "title": "서비스메쉬",
                "native_id": "DSGN-005-209",
                "body_md": "svc-member 경로 매핑",
                "visual_text": "라우팅 다이어그램",
                "facets": {"service_names": ["svc-member"]},
                "related_official_docs": [{"score": 0.42, "title": "low"}, {"score": 0.7, "title": "trusted"}],
            },
        )

        payload = _load_chunk(root, "chunk-01")

        assert payload["schema_version"] == "ppt_chunk_v1"
        assert payload["source_kind"] == "project_artifact"
        assert "서비스메쉬" in payload["index_texts"]["dense_text"]
        assert "svc-member" in payload["index_texts"]["sparse_text"]
        assert payload["related_official_docs"][0]["trusted"] is False
        assert payload["related_official_docs"][1]["trusted"] is True


def test_course_chunk_viewer_meta_and_html_support_workspace_preview() -> None:
    with _temp_root() as root:
        assets_dir = root / "data" / "course_pbs" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "chunk-01__img_01.png").write_bytes(b"not-a-real-png")
        _write_chunk(
            root,
            "chunk-01",
            {
                "chunk_id": "chunk-01",
                "stage_id": "unit_test",
                "title": "Pod Running 확인",
                "native_id": "TEST-01",
                "chunk_kind": "test_case_summary",
                "body_md": "Running 상태를 확인한다.",
                "search_text": "TEST-01 Running Ready",
                "source_pptx": "study-docs/unit.pptx",
                "slide_refs": [{"slide_no": 3, "pptx": "study-docs/unit.pptx"}],
                "image_attachments": [
                    {
                        "asset_id": "chunk-01::asset:01",
                        "asset_path": "data/course_pbs/assets/chunk-01__img_01.png",
                        "slide_no": 3,
                        "visual_summary": "Pod Running screen",
                    }
                ],
                "structured": {"method": "oc get pods"},
            },
        )

        meta = course_viewer_source_meta(root, "/course/chunks/chunk-01")
        viewer_html = course_viewer_html(root, "/course/chunks/chunk-01")

    assert meta is not None
    assert meta["viewer_path"] == "/course/chunks/chunk-01"
    assert meta["source_lane"] == "study_docs_course_runtime"
    assert viewer_html is not None
    assert "Pod Running 확인" in viewer_html
    assert "/api/v1/course/assets?path=data/course_pbs/assets/chunk-01__img_01.png" in viewer_html


def test_course_chat_separates_study_docs_official_docs_and_guided_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    current_id = "unit-test--TEST-UN-OCP-30-01--summary"
    next_id = "unit-test--TEST-UN-OCP-30-02--summary"
    with _temp_root() as root:
        _write_chunk(
            root,
            current_id,
            {
                "chunk_id": current_id,
                "stage_id": "unit_test",
                "title": "etcd 백업 수행",
                "native_id": "TEST-UN-OCP-30-01",
                "chunk_kind": "test_case_summary",
                "body_md": "마스터노드에서 etcd 백업을 수행한다.",
                "search_text": "TEST-UN-OCP-30-01 etcd 백업 수행. 주요 기술: ETCD.",
                "source_pptx": "study-docs/unit.pptx",
                "slide_refs": [{"slide_no": 10, "pptx": "study-docs/unit.pptx"}],
                "related_official_docs": [
                    {"score": 0.42, "title": "low doc", "section_title": "ignored"},
                    {
                        "score": 0.72,
                        "title": "OpenShift Docs",
                        "book_slug": "openshift",
                        "section_id": "backup-etcd",
                        "section_title": "Backing up etcd",
                        "snippet": "Back up etcd from a control plane host.",
                        "match_reason": "ETCD keyword match",
                    },
                ],
                "tour_stop": {
                    "stop_order": 1,
                    "total_stops": 2,
                    "route_role": "start_here",
                    "next_chunk_id": next_id,
                },
            },
        )
        _write_chunk(
            root,
            next_id,
            {
                "chunk_id": next_id,
                "stage_id": "unit_test",
                "title": "etcd 백업 확인",
                "native_id": "TEST-UN-OCP-30-02",
                "chunk_kind": "test_case_summary",
                "body_md": "백업 파일 생성 여부를 확인한다.",
                "search_text": "TEST-UN-OCP-30-02 etcd 백업 확인. 주요 기술: ETCD.",
                "source_pptx": "study-docs/unit.pptx",
                "slide_refs": [{"slide_no": 11, "pptx": "study-docs/unit.pptx"}],
                "related_official_docs": [],
                "tour_stop": {
                    "stop_order": 2,
                    "total_stops": 2,
                    "route_role": "standard",
                    "next_chunk_id": "",
                },
            },
        )

        response = _course_chat_payload(root, {"message": "etcd 백업 공식문서 기준도 같이 알려줘", "stage_id": "unit_test"})

        assert "etcd 백업 수행" in response["answer"]
        assert "공식문서 확인" in response["answer"]
        assert "다음에 볼 단계" in response["answer"]
        assert "OpenShift Docs" in response["answer"]
        assert "low doc" not in response["answer"]
        assert any(item["source_kind"] == "official_doc" and item["title"] == "OpenShift Docs" for item in response["sources"])
        assert response["citations"][0]["viewer_path"] == f"/course/chunks/{current_id}"
        assert response["citations"][0]["source_lane"] == "study_docs_course_runtime"
        assert any(citation["source_lane"] == "official_validated_runtime" for citation in response["citations"])
        assert "[1]" in response["answer"]
        assert response["related_sections"][0]["href"] == f"/course/chunks/{next_id}"
        assert response["suggested_queries"]
        guided = next(item for item in response["artifacts"] if item["kind"] == "course_guided_tour")
        assert [item["role"] for item in guided["items"]] == ["current", "next"]
        assert guided["items"][1]["chunk_id"] == next_id


def test_course_chat_uses_stage_official_route_when_chunk_mapping_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    chunk_id = "completion--CH-01--summary"
    with _temp_root() as root:
        _write_chunk(
            root,
            chunk_id,
            {
                "chunk_id": chunk_id,
                "stage_id": "completion",
                "title": "완료보고 완료본",
                "native_id": "CH-01",
                "chunk_kind": "chapter_summary",
                "body_md": "완료보고 첫 장",
                "search_text": "CH-01 완료보고 완료본",
                "source_pptx": "study-docs/completion.pptx",
                "slide_refs": [{"slide_no": 1, "pptx": "study-docs/completion.pptx"}],
                "related_official_docs": [],
                "tour_stop": {
                    "stop_order": 1,
                    "total_stops": 1,
                    "route_role": "start_here",
                    "next_chunk_id": "",
                },
            },
        )
        _write_manifest(
            root,
            {
                "stages": [
                    {
                        "stage_id": "completion",
                        "official_route_refs": [
                            {
                                "book_slug": "overview",
                                "section_id": "overview:kubernetes",
                                "title": "개요",
                                "section_title": "Kubernetes 개요",
                                "snippet": "Kubernetes 기반 컨테이너 오케스트레이션 개요",
                                "score": 0.66,
                                "match_reason": "stage-level official route for completion",
                            }
                        ],
                    }
                ]
            },
        )

        response = _course_chat_payload(root, {"message": "완료보고 공식문서 기준도 같이 알려줘", "stage_id": "completion"})

        assert "공식문서 확인" in response["answer"]
        assert "Kubernetes 기반" in response["answer"]
        official = next(item for item in response["artifacts"] if item["kind"] == "official_check")
        assert official["items"][0]["title"] == "개요"
        assert official["items"][0]["match_reason"] == "stage-level official route for completion"


def test_course_chat_returns_ranked_image_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    chunk_id = "unit-test--image-evidence"
    with _temp_root() as root:
        _write_chunk(
            root,
            chunk_id,
            {
                "chunk_id": chunk_id,
                "stage_id": "unit_test",
                "title": "Pod Running 확인",
                "native_id": "TEST-IMG-01",
                "chunk_kind": "test_case_summary",
                "body_md": "oc get pods 결과에서 Running 상태를 확인한다.",
                "search_text": "TEST-IMG-01 Running Ready 상태 확인",
                "source_pptx": "study-docs/unit.pptx",
                "slide_refs": [{"slide_no": 3, "pptx": "study-docs/unit.pptx"}],
                "image_attachments": [
                    {
                        "asset_id": "asset-running",
                        "slide_no": 3,
                        "visual_summary": "Pod status row shows Running.",
                        "ocr_text": "NAME READY STATUS api-1 1/1 Running",
                        "instructional_role": "expected_state_indicator",
                        "instructional_roles": ["expected_state_indicator", "success_state"],
                        "quality_label": "tiny_strip_or_icon",
                        "state_signal": "Running",
                        "evidence_strength": 0.87,
                        "rank_profiles": {"concept": 0.2, "procedure": 0.95, "troubleshooting": 0.25},
                        "is_default_visible": True,
                    }
                ],
                "related_official_docs": [],
            },
        )

        response = _course_chat_payload(root, {"message": "Running 정상 상태 확인", "stage_id": "unit_test"})

        image_artifact = next(item for item in response["artifacts"] if item["kind"] == "course_image_evidence")
        assert image_artifact["items"][0]["asset_id"] == "asset-running"
        assert image_artifact["items"][0]["state_signal"] == "Running"
        assert "화면 증적" in response["answer"]


def test_course_chat_image_evidence_prefers_query_matched_state_and_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("play_book_studio.app.course_api.search_course_and_official", lambda settings, query: ([], []))
    chunk_id = "perf-test--dashboard-ready"
    with _temp_root() as root:
        _write_chunk(
            root,
            chunk_id,
            {
                "chunk_id": chunk_id,
                "stage_id": "perf_test",
                "title": "Performance evidence",
                "native_id": "PERF-IMG-01",
                "chunk_kind": "perf_slide_detail",
                "body_md": "Prometheus dashboard and Ready condition evidence.",
                "search_text": "PERF-IMG-01 Prometheus dashboard Ready condition.",
                "source_pptx": "study-docs/perf.pptx",
                "slide_refs": [{"slide_no": 58, "pptx": "study-docs/perf.pptx"}],
                "image_attachments": [
                    {
                        "asset_id": "asset-command",
                        "slide_no": 58,
                        "visual_summary": "Generic command result output.",
                        "instructional_role": "command_result_evidence",
                        "instructional_roles": ["command_result_evidence"],
                        "evidence_strength": 0.9,
                        "rank_profiles": {"procedure": 0.95, "troubleshooting": 0.6},
                        "is_default_visible": True,
                    },
                    {
                        "asset_id": "asset-dashboard",
                        "slide_no": 58,
                        "visual_summary": "Prometheus monitoring dashboard shows resource metrics.",
                        "instructional_role": "dashboard_metric",
                        "instructional_roles": ["dashboard_metric"],
                        "evidence_strength": 0.6,
                        "rank_profiles": {"procedure": 0.4, "troubleshooting": 0.55},
                        "is_default_visible": True,
                    },
                    {
                        "asset_id": "asset-ready",
                        "slide_no": 58,
                        "visual_summary": "Pod Ready condition is True.",
                        "instructional_role": "expected_state_indicator",
                        "instructional_roles": ["expected_state_indicator", "success_state"],
                        "state_signal": "Ready",
                        "evidence_strength": 0.6,
                        "rank_profiles": {"procedure": 0.45, "troubleshooting": 0.3},
                        "is_default_visible": True,
                    },
                ],
                "related_official_docs": [],
            },
        )

        dashboard = _course_chat_payload(root, {"message": "Prometheus dashboard metric 화면", "stage_id": "perf_test"})
        ready = _course_chat_payload(root, {"message": "Ready 상태 증적", "stage_id": "perf_test"})

        dashboard_items = next(item for item in dashboard["artifacts"] if item["kind"] == "course_image_evidence")["items"]
        ready_items = next(item for item in ready["artifacts"] if item["kind"] == "course_image_evidence")["items"]
        assert dashboard_items[0]["asset_id"] == "asset-dashboard"
        assert ready_items[0]["asset_id"] == "asset-ready"
