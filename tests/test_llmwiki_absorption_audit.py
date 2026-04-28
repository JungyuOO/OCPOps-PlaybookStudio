from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.app.llmwiki_absorption_audit import build_llmwiki_absorption_audit


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _contract_text() -> str:
    return """
Karpathy LLM Wiki raw sources schema.
Contextual Retrieval contextual chunk.
RAPTOR synthesis tree.
GraphRAG LightRAG relation graph.
Self-RAG CRAG retrieval quality.
MemGPT session memory.
STORM outline.
fine-tuning boundary.
No wiki back-write loop.
No Contextual Retrieval.
No RAPTOR.
No GraphRAG.
No CRAG/Self-RAG.
Retrieval quality critic.
Wiki back-write candidate artifact.
LLMWiki absorption audit.
"""


def test_llmwiki_absorption_audit_passes_current_evidence_bundle(tmp_path: Path) -> None:
    contract = tmp_path / "contract.md"
    contract.write_text(_contract_text(), encoding="utf-8")
    promotion = _write_json(
        tmp_path / "promotion.json",
        {
            "status": "ok",
            "ready_for_llmwiki_promotion": True,
            "summary": {
                "contracts": {
                    "official_gold": {"ok": True, "metrics": {"chunks_count": 87839}},
                    "customer_master": {"ok": True, "source_count": 10},
                    "runtime_report": {"ok": True},
                    "chat_matrix": {
                        "ok": True,
                        "runtime_requirements": {"llm_live_total": 2, "vector_live_total": 2},
                    },
                }
            },
        },
    )
    validation_loop = _write_json(
        tmp_path / "validation-loop.json",
        {"status": "ok", "ready": True, "completed_iterations": 1, "acceptance": {"failures": []}},
    )
    role_continuity = _write_json(
        tmp_path / "role-continuity.json",
        {
            "status": "ok",
            "pass_count": 20,
            "total": 20,
            "roles": {
                "operator_a": {"pass": 10, "total": 10},
                "learner_b": {"pass": 10, "total": 10},
            },
        },
    )
    evolution_gate = _write_json(
        tmp_path / "evolution-gate.json",
        {
            "status": "ok",
            "ready": True,
            "checks": {
                "retrieval_quality_critic_ready": True,
                "wiki_backwrite_candidate_ready": True,
                "wiki_lint_anti_rot_ready": True,
            },
            "failures": [],
        },
    )
    contextual_gate = _write_json(
        tmp_path / "contextual-gate.json",
        {
            "status": "ok",
            "ready": True,
            "checks": {
                "runtime_contextual_prefix_ready": True,
                "runtime_contextual_heading_path_ready": True,
                "bm25_runtime_uses_contextual_search_text": True,
                "contextual_recall_fixture_improves": True,
            },
            "failures": [],
        },
    )

    payload = build_llmwiki_absorption_audit(
        tmp_path,
        contract_path=contract,
        promotion_report_path=promotion,
        validation_loop_report_path=validation_loop,
        role_continuity_report_path=role_continuity,
        evolution_gate_report_path=evolution_gate,
        contextual_enrichment_report_path=contextual_gate,
    )

    assert payload["status"] == "ok"
    assert payload["ready"] is True
    assert payload["beyond_rag_stage"] == "grounded_runtime_with_p1_contextual_retrieval"
    assert payload["full_self_evolving_llmwiki"] is False
    assert "contextual_chunk_enrichment" not in payload["not_yet_absorbed_lanes"]
    assert "reviewed_wiki_backwrite_promotion_loop" in payload["not_yet_absorbed_lanes"]


def test_llmwiki_absorption_audit_fails_when_contract_is_not_absorbed(tmp_path: Path) -> None:
    contract = tmp_path / "contract.md"
    contract.write_text("Karpathy LLM Wiki only", encoding="utf-8")
    report = _write_json(tmp_path / "empty.json", {})

    payload = build_llmwiki_absorption_audit(
        tmp_path,
        contract_path=contract,
        promotion_report_path=report,
        validation_loop_report_path=report,
        role_continuity_report_path=report,
        evolution_gate_report_path=report,
        contextual_enrichment_report_path=report,
    )

    assert payload["status"] == "fail"
    assert payload["checks"]["contract_absorption_locked"] is False
    assert payload["contract"]["missing_source_patterns"]
