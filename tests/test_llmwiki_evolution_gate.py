from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.app.llmwiki_evolution_gate import build_llmwiki_evolution_gate


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _ok_chat_matrix() -> dict:
    return {
        "head": "",
        "status": "ok",
        "pass_count": 1,
        "total": 1,
        "results": [
            {
                "id": "official_buildconfig",
                "query": "BuildConfig 확인 순서를 알려줘",
                "pass": True,
                "response_kind": "rag",
                "citation_count": 1,
                "cited_indices": [1],
                "collections": ["core"],
                "books": ["builds_using_buildconfig"],
                "checks": {
                    "min_citations": True,
                    "expected_collections": True,
                    "expected_books": True,
                    "not_doc_locator_only": True,
                },
                "answer_preview": "답변: BuildConfig 상태와 이벤트를 확인하고 조치 후 검증합니다 [1].",
            }
        ],
    }


def _ok_role_continuity() -> dict:
    results = []
    for turn in range(1, 21):
        role = "operator_a" if turn <= 10 else "learner_b"
        results.append(
            {
                "role": role,
                "turn": turn,
                "query": f"{role} turn {turn}",
                "pass": True,
                "response_kind": "rag",
                "citation_count": 1,
                "cited_indices": [1],
                "checks": {
                    "response_ok": True,
                    "min_answer_length": True,
                    "min_citations": True,
                    "not_doc_locator_only": True,
                    "role_terms": True,
                },
                "answer_preview": f"답변: {role} {turn} 단계별 근거 기반 설명입니다 [1].",
            }
        )
    return {"head": "", "status": "ok", "pass_count": 20, "total": 20, "results": results}


def _ok_validation_loop() -> dict:
    return {"git": {"head": ""}, "status": "ok", "ready": True, "completed_iterations": 1}


def test_llmwiki_evolution_gate_passes_clean_evidence_bundle(tmp_path: Path) -> None:
    chat = _write_json(tmp_path / "chat.json", _ok_chat_matrix())
    role = _write_json(tmp_path / "role.json", _ok_role_continuity())
    promotion = _write_json(tmp_path / "promotion.json", {"git": {"head": ""}, "status": "ok"})
    loop = _write_json(tmp_path / "loop.json", _ok_validation_loop())

    payload = build_llmwiki_evolution_gate(
        tmp_path,
        chat_matrix_report_path=chat,
        role_continuity_report_path=role,
        promotion_report_path=promotion,
        validation_loop_report_path=loop,
    )

    assert payload["status"] == "ok"
    assert payload["checks"]["retrieval_quality_critic_ready"] is True
    assert payload["checks"]["wiki_backwrite_candidate_ready"] is True
    assert payload["checks"]["wiki_lint_anti_rot_ready"] is True
    assert payload["wiki_backwrite_candidate"]["candidate_count"] > 0


def test_llmwiki_evolution_gate_blocks_unrelated_reporting_command(tmp_path: Path) -> None:
    chat_payload = _ok_chat_matrix()
    role_payload = _ok_role_continuity()
    role_payload["results"][8]["query"] = "운영자에게 보고할 때 핵심 증거를 어떻게 정리하지?"
    role_payload["results"][8][
        "answer_preview"
    ] = "답변: 아래 명령으로 진행하면 됩니다 [1].\n```bash\noc adm prune builds\n```"
    chat = _write_json(tmp_path / "chat.json", chat_payload)
    role = _write_json(tmp_path / "role.json", role_payload)
    promotion = _write_json(tmp_path / "promotion.json", {"git": {"head": ""}, "status": "ok"})
    loop = _write_json(tmp_path / "loop.json", _ok_validation_loop())

    payload = build_llmwiki_evolution_gate(
        tmp_path,
        chat_matrix_report_path=chat,
        role_continuity_report_path=role,
        promotion_report_path=promotion,
        validation_loop_report_path=loop,
    )

    assert payload["status"] == "fail"
    assert payload["checks"]["retrieval_quality_critic_ready"] is False
    assert any(
        finding["code"] == "reporting_or_evidence_query_contains_unrelated_build_or_compliance_command"
        for finding in payload["retrieval_quality_critic"]["findings"]
    )


def test_llmwiki_evolution_gate_blocks_candidate_without_provenance(tmp_path: Path) -> None:
    chat_payload = _ok_chat_matrix()
    chat_payload["results"][0]["citation_count"] = 0
    chat_payload["results"][0]["checks"]["min_citations"] = False
    role_payload = _ok_role_continuity()
    chat = _write_json(tmp_path / "chat.json", chat_payload)
    role = _write_json(tmp_path / "role.json", role_payload)
    promotion = _write_json(tmp_path / "promotion.json", {"git": {"head": ""}, "status": "ok"})
    loop = _write_json(tmp_path / "loop.json", _ok_validation_loop())

    payload = build_llmwiki_evolution_gate(
        tmp_path,
        chat_matrix_report_path=chat,
        role_continuity_report_path=role,
        promotion_report_path=promotion,
        validation_loop_report_path=loop,
    )

    assert payload["status"] == "fail"
    assert payload["retrieval_quality_critic"]["blocker_count"] >= 1
