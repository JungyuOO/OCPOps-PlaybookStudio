import json

import play_book_studio.app.data_control_room as data_control_room


def _write_role_rehearsal_report(root, payload):
    reports_dir = root / ".kugnusdocs" / "reports"
    reports_dir.mkdir(parents=True)
    report_path = reports_dir / "2026-04-27-operator-learner-role-rehearsal.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    return report_path


def _git_context(head="abc123", dirty_mtime=0):
    return {
        "branch": "feat/dev-kugnus",
        "head": head,
        "dirty_tracked_files": bool(dirty_mtime),
        "dirty_tracked_latest_mtime_ns": dirty_mtime,
    }


def _ready_report():
    return {
        "generated_at": "2026-04-27T15:09:29+09:00",
        "branch": "feat/dev-kugnus",
        "head": "abc123",
        "status": "ok",
        "pass_count": 4,
        "total": 4,
        "roles": {
            "operator_a": {"pass": 2, "total": 2},
            "learner_b": {"pass": 2, "total": 2},
        },
        "acceptance": {
            "operator_a": "운영모드는 절차/명령/검증 중심이다.",
            "learner_b": "학습모드는 개념/학습 경로 중심이다.",
        },
        "results": [
            {"id": "operator_a_monitoring", "role": "operator_a", "pass": True, "status": "ok"},
            {"id": "operator_a_buildconfig", "role": "operator_a", "pass": True, "status": "ok"},
            {"id": "learner_b_official", "role": "learner_b", "pass": True, "status": "ok"},
            {"id": "learner_b_blend", "role": "learner_b", "pass": True, "status": "ok"},
        ],
    }


def _promotion_stub():
    return {
        "ready": True,
        "selected_report": {"head_matches_current": True},
        "mode_contract": {"supported_modes": [{"id": "learn"}, {"id": "ops"}]},
        "metrics": {
            "official_chunks_count": 1,
            "official_code_blocks": 1,
            "official_inline_figures": 1,
            "customer_master_source_count": 1,
            "customer_master_section_count": 1,
            "chat_live_pass_count": 2,
            "chat_live_total": 2,
        },
        "status_rail": [
            {"key": "official", "ready": True},
            {"key": "customer", "ready": True},
            {"key": "runtime", "ready": True},
            {"key": "chat", "ready": True},
        ],
        "failures": [],
    }


def _validation_loop_stub():
    return {
        "ready": True,
        "status": "ok",
        "failures": [],
        "metrics": {"completed_iterations": 1, "requested_iterations": 1},
        "surya_policy": {"required_for_llmwiki_runtime": False, "status": "offline_allowed"},
    }


def _runtime_dependencies_stub(*, ready=True):
    return {
        "status": "ok" if ready else "blocked",
        "ready": ready,
        "failures": [] if ready else ["qdrant: connection refused"],
        "qdrant": {
            "id": "qdrant",
            "ready": ready,
            "status": "ok" if ready else "down",
            "url": "http://127.0.0.1:6335/collections",
            "collection": "openshift_docs",
            "error": "" if ready else "connection refused",
        },
    }


def test_role_rehearsal_ready_report_requires_operator_and_learner(tmp_path, monkeypatch):
    _write_role_rehearsal_report(tmp_path, _ready_report())
    monkeypatch.setattr(data_control_room, "_current_git_context", lambda root: _git_context())

    status = data_control_room._build_role_rehearsal_control_status(tmp_path)

    assert status["ready"] is True
    assert status["status"] == "ok"
    assert status["pass_count"] == 4
    assert status["total"] == 4
    assert status["roles"]["operator_a"]["ready"] is True
    assert status["roles"]["learner_b"]["ready"] is True
    assert status["failures"] == []


def test_role_rehearsal_stale_report_blocks_readiness(tmp_path, monkeypatch):
    _write_role_rehearsal_report(tmp_path, _ready_report())
    monkeypatch.setattr(data_control_room, "_current_git_context", lambda root: _git_context(head="different"))

    status = data_control_room._build_role_rehearsal_control_status(tmp_path)

    assert status["ready"] is False
    assert status["status"] == "stale"
    assert status["selected_report"]["head_matches_current"] is False
    assert any("stale" in failure for failure in status["failures"])


def test_development_control_requires_role_rehearsal_surface(tmp_path, monkeypatch):
    _write_role_rehearsal_report(tmp_path, {**_ready_report(), "roles": {"operator_a": {"pass": 2, "total": 2}, "learner_b": {"pass": 0, "total": 2}}})
    monkeypatch.setattr(data_control_room, "_current_git_context", lambda root: _git_context())
    role_rehearsal = data_control_room._build_role_rehearsal_control_status(tmp_path)

    status = data_control_room._build_development_control_status(
        llmwiki_promotion=_promotion_stub(),
        llmwiki_validation_loop=_validation_loop_stub(),
        official_playbook_count=1,
        customer_playbook_count=1,
        user_corpus_chunk_count=1,
        custom_document_count=0,
        playable_asset_count=1,
        source_of_truth_drift={"status_alignment": {"mismatches": []}},
        product_rehearsal={"exists": False, "status": "missing", "blockers": []},
        role_rehearsal=role_rehearsal,
        runtime_dependencies=_runtime_dependencies_stub(),
    )

    role_surface = next(surface for surface in status["surfaces"] if surface["id"] == "role_rehearsal")
    assert status["ready"] is False
    assert role_surface["required"] is True
    assert role_surface["status"] == "blocked"
    assert any("learner_b" in blocker for blocker in role_surface["blockers"])


def test_development_control_blocks_when_qdrant_runtime_dependency_is_down(tmp_path, monkeypatch):
    _write_role_rehearsal_report(tmp_path, _ready_report())
    monkeypatch.setattr(data_control_room, "_current_git_context", lambda root: _git_context())
    role_rehearsal = data_control_room._build_role_rehearsal_control_status(tmp_path)

    status = data_control_room._build_development_control_status(
        llmwiki_promotion=_promotion_stub(),
        llmwiki_validation_loop=_validation_loop_stub(),
        official_playbook_count=1,
        customer_playbook_count=1,
        user_corpus_chunk_count=1,
        custom_document_count=0,
        playable_asset_count=1,
        source_of_truth_drift={"status_alignment": {"mismatches": []}},
        product_rehearsal={"exists": False, "status": "missing", "blockers": []},
        role_rehearsal=role_rehearsal,
        runtime_dependencies=_runtime_dependencies_stub(ready=False),
    )

    runtime_surface = next(surface for surface in status["surfaces"] if surface["id"] == "runtime_dependencies")
    assert status["ready"] is False
    assert runtime_surface["required"] is True
    assert runtime_surface["status"] == "blocked"
    assert any("qdrant" in blocker for blocker in runtime_surface["blockers"])
