from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.presenters_runtime as presenters_runtime
import play_book_studio.http.runtime_report as runtime_report
from play_book_studio.config.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "runtime_seed_inputs_tests"


def _workspace(name: str) -> Path:
    root = TEST_TMP / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_health_payload_marks_seed_inputs_not_required_in_database_runtime(monkeypatch) -> None:
    root = _workspace("health")
    (root / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://unit-test",
                "ARTIFACTS_DIR=artifacts",
                "LLM_ENDPOINT=http://llm.example/v1",
                "LLM_MODEL=Qwen/Qwen3.5-9B",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(presenters_runtime, "build_corpus_status", lambda **_kwargs: {"ready": False})
    monkeypatch.setattr(presenters_runtime, "build_course_runtime_status", lambda **_kwargs: {"ready": False})
    monkeypatch.setattr(
        presenters_runtime,
        "graph_sidecar_compact_artifact_status",
        lambda _settings: {"ready": False},
    )
    answerer = SimpleNamespace(
        settings=load_settings(root),
        llm_client=SimpleNamespace(runtime_metadata=lambda: {}),
    )

    payload = presenters_runtime._build_health_payload(answerer)
    runtime = payload["runtime"]

    assert runtime["database_runtime"] is True
    assert runtime["seed_inputs_required_for_runtime"] is False
    assert runtime["seed_inputs"]["required_for_runtime"] is False
    assert "source_manifest_path" not in runtime
    assert runtime["seed_inputs"]["source_manifest_path"]


def test_runtime_report_marks_legacy_files_as_seed_inputs_in_database_runtime(monkeypatch) -> None:
    root = _workspace("runtime_report")
    (root / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://unit-test",
                "ARTIFACTS_DIR=artifacts",
                "LLM_ENDPOINT=http://llm.example/v1",
                "LLM_MODEL=Qwen/Qwen3.5-9B",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_report, "build_corpus_status", lambda **_kwargs: {"ready": False})
    monkeypatch.setattr(runtime_report, "build_course_runtime_status", lambda **_kwargs: {"ready": False})
    monkeypatch.setattr(runtime_report, "graph_sidecar_compact_artifact_status", lambda _settings: {"ready": False})
    monkeypatch.setattr(runtime_report, "_probe_llm", lambda _settings, *, sample: {"sample": sample})
    monkeypatch.setattr(runtime_report, "_probe_embedding", lambda _settings, *, sample: {"sample": sample})
    monkeypatch.setattr(runtime_report, "_probe_qdrant", lambda _settings: {"ok": True})

    payload = runtime_report.build_runtime_report(root, ui_base_url=None, sample=False)

    assert payload["runtime"]["database_runtime"] is True
    assert payload["runtime"]["seed_inputs_required_for_runtime"] is False
    assert payload["artifacts"]["source_manifest"]["role"] == "seed_input"
    assert payload["artifacts"]["source_manifest"]["required_for_runtime"] is False
    assert payload["artifacts"]["chunks"]["role"] == "seed_input"
    assert payload["artifacts"]["bm25_corpus"]["required_for_runtime"] is False
