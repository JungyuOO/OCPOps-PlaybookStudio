from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

from play_book_studio.app.llmwiki_validation_loop import _safe_int


CONTRACT_RELATIVE_PATH = Path(
    ".kugnusdocs/docs/programs/beyond_rag_llmwiki_absorption_contract_20260427.md"
)

REQUIRED_SOURCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "karpathy_llmwiki": ("Karpathy LLM Wiki", "raw sources", "schema"),
    "contextual_retrieval": ("Contextual Retrieval", "contextual chunk"),
    "raptor": ("RAPTOR", "synthesis tree"),
    "graphrag_lightrag": ("GraphRAG", "LightRAG", "relation graph"),
    "self_rag_crag": ("Self-RAG", "CRAG", "retrieval quality"),
    "agent_memory": ("MemGPT", "session memory"),
    "storm": ("STORM", "outline"),
}

REQUIRED_GAP_PATTERNS: tuple[str, ...] = (
    "No wiki back-write loop",
    "No Contextual Retrieval",
    "No RAPTOR",
    "No GraphRAG",
    "No CRAG/Self-RAG",
)

REQUIRED_P0_LANES: tuple[str, ...] = (
    "Retrieval quality critic",
    "Wiki back-write candidate artifact",
    "LLMWiki absorption audit",
)

NOT_YET_ABSORBED_LANES: tuple[str, ...] = (
    "raptor_summary_tree",
    "graphrag_community_reports",
    "full_crag_self_rag_controller",
    "reviewed_wiki_backwrite_promotion_loop",
    "durable_agent_memory_notes",
    "storm_style_wikibook_scoring",
)


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git_value(root_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_refs(root_dir: Path) -> dict[str, str]:
    return {
        "branch": _git_value(root_dir, "branch", "--show-current"),
        "head": _git_value(root_dir, "rev-parse", "HEAD"),
        "base_ref": "origin/main",
        "base_sha": _git_value(root_dir, "merge-base", "HEAD", "origin/main"),
    }


def _reports_dir(root_dir: Path) -> Path:
    return root_dir / ".kugnusdocs" / "reports"


def _dated_report_path(root_dir: Path, name: str) -> Path:
    return _reports_dir(root_dir) / f"{date.today().isoformat()}-{name}.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _text_contains_all(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return all(term.casefold() in lowered for term in terms)


def _contract_checks(contract_path: Path) -> dict[str, Any]:
    if not contract_path.exists():
        return {
            "ok": False,
            "path": str(contract_path),
            "checks": {"contract_exists": False},
            "missing_source_patterns": list(REQUIRED_SOURCE_PATTERNS),
            "missing_gap_patterns": list(REQUIRED_GAP_PATTERNS),
            "missing_p0_lanes": list(REQUIRED_P0_LANES),
        }

    text = contract_path.read_text(encoding="utf-8")
    source_pattern_results = {
        name: _text_contains_all(text, terms)
        for name, terms in REQUIRED_SOURCE_PATTERNS.items()
    }
    gap_results = {term: term.casefold() in text.casefold() for term in REQUIRED_GAP_PATTERNS}
    p0_results = {term: term.casefold() in text.casefold() for term in REQUIRED_P0_LANES}
    checks = {
        "contract_exists": True,
        "source_patterns_reviewed": all(source_pattern_results.values()),
        "current_gaps_recorded": all(gap_results.values()),
        "p0_lanes_defined": all(p0_results.values()),
        "non_finetune_boundary_recorded": "fine-tuning" in text.casefold(),
    }
    return {
        "ok": all(checks.values()),
        "path": str(contract_path),
        "checks": checks,
        "source_patterns": source_pattern_results,
        "missing_source_patterns": [name for name, ok in source_pattern_results.items() if not ok],
        "missing_gap_patterns": [name for name, ok in gap_results.items() if not ok],
        "missing_p0_lanes": [name for name, ok in p0_results.items() if not ok],
    }


def _promotion_checks(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    contracts = summary.get("contracts") if isinstance(summary.get("contracts"), dict) else {}
    official_gold = contracts.get("official_gold") if isinstance(contracts.get("official_gold"), dict) else {}
    customer_master = contracts.get("customer_master") if isinstance(contracts.get("customer_master"), dict) else {}
    runtime_report = contracts.get("runtime_report") if isinstance(contracts.get("runtime_report"), dict) else {}
    chat_matrix = contracts.get("chat_matrix") if isinstance(contracts.get("chat_matrix"), dict) else {}
    checks = {
        "report_loaded": bool(payload),
        "status_ok": payload.get("status") == "ok",
        "promotion_ready": bool(payload.get("ready_for_llmwiki_promotion")),
        "official_gold_ok": bool(official_gold.get("ok")),
        "customer_master_ok": bool(customer_master.get("ok")),
        "runtime_report_ok": bool(runtime_report.get("ok")),
        "chat_matrix_ok": bool(chat_matrix.get("ok")),
    }
    metrics = {
        "official_chunks": _safe_int(
            (official_gold.get("metrics") if isinstance(official_gold.get("metrics"), dict) else {}).get(
                "chunks_count"
            )
        ),
        "customer_sources": _safe_int(customer_master.get("source_count")),
        "chat_live_total": _safe_int(
            (
                chat_matrix.get("runtime_requirements")
                if isinstance(chat_matrix.get("runtime_requirements"), dict)
                else {}
            ).get("llm_live_total")
        )
        + _safe_int(
            (
                chat_matrix.get("runtime_requirements")
                if isinstance(chat_matrix.get("runtime_requirements"), dict)
                else {}
            ).get("vector_live_total")
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "metrics": metrics}


def _validation_loop_checks(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "report_loaded": bool(payload),
        "status_ok": payload.get("status") == "ok",
        "ready": bool(payload.get("ready")),
        "completed_iterations": _safe_int(payload.get("completed_iterations")) >= 1,
    }
    acceptance = payload.get("acceptance") if isinstance(payload.get("acceptance"), dict) else {}
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "failures": list(acceptance.get("failures") or []),
    }


def _role_continuity_checks(payload: dict[str, Any]) -> dict[str, Any]:
    roles = payload.get("roles") if isinstance(payload.get("roles"), dict) else {}
    operator = roles.get("operator_a") if isinstance(roles.get("operator_a"), dict) else {}
    learner = roles.get("learner_b") if isinstance(roles.get("learner_b"), dict) else {}
    total = _safe_int(payload.get("total"))
    pass_count = _safe_int(payload.get("pass_count"))
    checks = {
        "report_loaded": bool(payload),
        "status_ok": payload.get("status") == "ok",
        "all_turns_pass": total >= 20 and pass_count == total,
        "operator_a_10_turns": _safe_int(operator.get("total")) >= 10
        and _safe_int(operator.get("pass")) == _safe_int(operator.get("total")),
        "learner_b_10_turns": _safe_int(learner.get("total")) >= 10
        and _safe_int(learner.get("pass")) == _safe_int(learner.get("total")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "roles": roles,
        "pass_count": pass_count,
        "total": total,
    }


def _evolution_gate_checks(payload: dict[str, Any]) -> dict[str, Any]:
    checks_payload = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    checks = {
        "report_loaded": bool(payload),
        "status_ok": payload.get("status") == "ok",
        "ready": bool(payload.get("ready")),
        "retrieval_quality_critic_ready": bool(checks_payload.get("retrieval_quality_critic_ready")),
        "wiki_backwrite_candidate_ready": bool(checks_payload.get("wiki_backwrite_candidate_ready")),
        "wiki_lint_anti_rot_ready": bool(checks_payload.get("wiki_lint_anti_rot_ready")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "failures": list(payload.get("failures") or []),
    }


def _contextual_enrichment_checks(payload: dict[str, Any]) -> dict[str, Any]:
    checks_payload = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    checks = {
        "report_loaded": bool(payload),
        "status_ok": payload.get("status") == "ok",
        "ready": bool(payload.get("ready")),
        "runtime_contextual_prefix_ready": bool(checks_payload.get("runtime_contextual_prefix_ready")),
        "runtime_contextual_heading_path_ready": bool(
            checks_payload.get("runtime_contextual_heading_path_ready")
        ),
        "bm25_runtime_uses_contextual_search_text": bool(
            checks_payload.get("bm25_runtime_uses_contextual_search_text")
        ),
        "contextual_recall_fixture_improves": bool(checks_payload.get("contextual_recall_fixture_improves")),
    }
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "failures": list(payload.get("failures") or []),
        "coverage": coverage,
    }


def build_llmwiki_absorption_audit(
    root_dir: str | Path,
    *,
    contract_path: str | Path | None = None,
    promotion_report_path: str | Path | None = None,
    validation_loop_report_path: str | Path | None = None,
    role_continuity_report_path: str | Path | None = None,
    evolution_gate_report_path: str | Path | None = None,
    contextual_enrichment_report_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    contract = Path(contract_path) if contract_path is not None else root / CONTRACT_RELATIVE_PATH
    promotion_path = (
        Path(promotion_report_path)
        if promotion_report_path is not None
        else _dated_report_path(root, "llmwiki-promotion-report")
    )
    validation_loop_path = (
        Path(validation_loop_report_path)
        if validation_loop_report_path is not None
        else _dated_report_path(root, "llmwiki-validation-loop")
    )
    role_path = (
        Path(role_continuity_report_path)
        if role_continuity_report_path is not None
        else _dated_report_path(root, "role-continuity-rehearsal")
    )
    evolution_path = (
        Path(evolution_gate_report_path)
        if evolution_gate_report_path is not None
        else _dated_report_path(root, "llmwiki-evolution-gate")
    )
    contextual_path = (
        Path(contextual_enrichment_report_path)
        if contextual_enrichment_report_path is not None
        else _dated_report_path(root, "llmwiki-contextual-enrichment-gate")
    )

    contract_result = _contract_checks(contract)
    promotion_result = _promotion_checks(_read_json(promotion_path))
    validation_loop_result = _validation_loop_checks(_read_json(validation_loop_path))
    role_result = _role_continuity_checks(_read_json(role_path))
    evolution_result = _evolution_gate_checks(_read_json(evolution_path))
    contextual_result = _contextual_enrichment_checks(_read_json(contextual_path))
    checks = {
        "contract_absorption_locked": bool(contract_result.get("ok")),
        "promotion_runtime_ready": bool(promotion_result.get("ok")),
        "validation_loop_ready": bool(validation_loop_result.get("ok")),
        "role_continuity_ready": bool(role_result.get("ok")),
        "p0_evolution_gate_ready": bool(evolution_result.get("ok")),
        "p1_contextual_chunk_enrichment_ready": bool(contextual_result.get("ok")),
    }
    failures = [name for name, ok in checks.items() if not ok]
    current_ready = not failures
    return {
        "generated_at": _iso_timestamp(),
        "git": _git_refs(root),
        "goal": "beyond_rag_llmwiki_absorption_gate",
        "status": "ok" if current_ready else "fail",
        "ready": current_ready,
        "beyond_rag_stage": (
            "grounded_runtime_with_p1_contextual_retrieval"
            if current_ready
            else "partial_or_blocked_absorption"
        ),
        "full_self_evolving_llmwiki": False,
        "checks": checks,
        "failures": failures,
        "contract": contract_result,
        "promotion_report": promotion_result,
        "validation_loop": validation_loop_result,
        "role_continuity": role_result,
        "p0_evolution_gate": evolution_result,
        "p1_contextual_chunk_enrichment": contextual_result,
        "not_yet_absorbed_lanes": list(NOT_YET_ABSORBED_LANES),
        "next_required_lanes": [
            "raptor_summary_tree",
            "graphrag_community_reports",
            "reviewed_wiki_backwrite_promotion_loop",
        ],
        "evidence": {
            "contract": str(contract),
            "promotion_report": str(promotion_path),
            "validation_loop": str(validation_loop_path),
            "role_continuity": str(role_path),
            "evolution_gate": str(evolution_path),
            "contextual_enrichment_gate": str(contextual_path),
        },
    }


def write_llmwiki_absorption_audit_report(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    contract_path: str | Path | None = None,
    promotion_report_path: str | Path | None = None,
    validation_loop_report_path: str | Path | None = None,
    role_continuity_report_path: str | Path | None = None,
    evolution_gate_report_path: str | Path | None = None,
    contextual_enrichment_report_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir).resolve()
    payload = build_llmwiki_absorption_audit(
        root,
        contract_path=contract_path,
        promotion_report_path=promotion_report_path,
        validation_loop_report_path=validation_loop_report_path,
        role_continuity_report_path=role_continuity_report_path,
        evolution_gate_report_path=evolution_gate_report_path,
        contextual_enrichment_report_path=contextual_enrichment_report_path,
    )
    output = (
        Path(output_path)
        if output_path is not None
        else _dated_report_path(root, "llmwiki-absorption-audit")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, payload
