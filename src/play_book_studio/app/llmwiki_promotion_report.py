from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

from play_book_studio.app.chat_matrix_smoke import write_chat_matrix_smoke
from play_book_studio.app.customer_master_book import (
    DEFAULT_MASTER_BOOK_SLUG,
    DEFAULT_MASTER_BOOK_TITLE,
    write_customer_master_book,
)
from play_book_studio.app.customer_pack_batch import discover_customer_pack_batch_sources
from play_book_studio.app.runtime_maintenance_smoke import write_runtime_maintenance_smoke
from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL, write_runtime_report
from play_book_studio.ingestion.official_gold_gate import (
    OFFICIAL_GOLD_REBUILD_COMMAND,
    write_artifact_manifest,
    write_official_gold_gate_report,
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


def _evidence_path(root_dir: Path, name: str) -> Path:
    return _reports_dir(root_dir) / f"{date.today().isoformat()}-{name}.json"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _chat_matrix_live_contract(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_requirements = (
        payload.get("runtime_requirements")
        if isinstance(payload.get("runtime_requirements"), dict)
        else {}
    )
    total = _safe_int(payload.get("total"))
    pass_count = _safe_int(payload.get("pass_count"))
    llm_live_total = _safe_int(runtime_requirements.get("llm_live_total"))
    vector_live_total = _safe_int(runtime_requirements.get("vector_live_total"))
    llm_live_pass_count = _safe_int(runtime_requirements.get("llm_live_pass_count"))
    vector_live_pass_count = _safe_int(runtime_requirements.get("vector_live_pass_count"))
    checks = {
        "status_ok": payload.get("status") == "ok",
        "all_cases_pass": total > 0 and pass_count == total,
        "llm_live_cases_present": llm_live_total > 0,
        "llm_live_cases_pass": llm_live_total > 0 and llm_live_pass_count == llm_live_total,
        "vector_live_cases_present": vector_live_total > 0,
        "vector_live_cases_pass": vector_live_total > 0 and vector_live_pass_count == vector_live_total,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "runtime_requirements": runtime_requirements,
    }


def _runtime_report_contract(
    payload: dict[str, Any],
    *,
    chat_matrix_contract: dict[str, Any],
) -> dict[str, Any]:
    probes = payload.get("probes") if isinstance(payload.get("probes"), dict) else {}
    local_ui = probes.get("local_ui") if isinstance(probes.get("local_ui"), dict) else {}
    embedding = probes.get("embedding") if isinstance(probes.get("embedding"), dict) else {}
    qdrant = probes.get("qdrant") if isinstance(probes.get("qdrant"), dict) else {}
    llm = probes.get("llm") if isinstance(probes.get("llm"), dict) else {}
    health_status = _safe_int(local_ui.get("health_status"))
    checks = {
        "local_ui_health_ok": 0 < health_status < 400,
        "embedding_sample_ok": bool(embedding.get("sample_embedding_ok")),
        "qdrant_collection_present": bool(qdrant.get("collection_present")),
        "llm_endpoint_configured": bool(str(llm.get("endpoint") or "").strip()),
        "llm_live_chat_ok": bool(chat_matrix_contract.get("ok")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "embedding": {
            "mode": embedding.get("mode"),
            "base_url": embedding.get("base_url"),
            "model": embedding.get("model"),
            "sample_vector_dim": embedding.get("sample_vector_dim"),
        },
        "qdrant": {
            "url": qdrant.get("url"),
            "collection": qdrant.get("collection"),
            "collection_present": qdrant.get("collection_present"),
        },
        "llm": {
            "endpoint": llm.get("endpoint"),
            "model": llm.get("model"),
            "models_status": llm.get("models_status"),
        },
    }


def _official_gold_contract(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    block_counts = (
        metrics.get("playbook_block_counts")
        if isinstance(metrics.get("playbook_block_counts"), dict)
        else {}
    )
    figure_sidecar_count = _safe_int(metrics.get("figure_sidecar_count"))
    figure_blocks = _safe_int(block_counts.get("figure"))
    figure_relation_coverage = (
        metrics.get("figure_relation_coverage")
        if isinstance(metrics.get("figure_relation_coverage"), dict)
        else {}
    )
    bm25_metadata_contract = (
        metrics.get("bm25_metadata_contract")
        if isinstance(metrics.get("bm25_metadata_contract"), dict)
        else {}
    )
    checks = {
        "official_gate_ok": payload.get("status") == "ok",
        "chunks_and_bm25_match": _safe_int(metrics.get("chunks_count")) > 0
        and _safe_int(metrics.get("chunks_count")) == _safe_int(metrics.get("bm25_count")),
        "code_blocks_present": _safe_int(block_counts.get("code")) > 0,
        "inline_figures_preserved": figure_sidecar_count == 0 or figure_blocks > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "metrics": {
            "chunks_count": metrics.get("chunks_count"),
            "bm25_count": metrics.get("bm25_count"),
            "playbook_document_count": metrics.get("playbook_document_count"),
            "code_blocks": block_counts.get("code"),
            "figure_sidecar_count": figure_sidecar_count,
            "playbook_figure_blocks": figure_blocks,
            "figure_relation_status": figure_relation_coverage.get("status"),
            "figure_missing_relation_count": _safe_int(figure_relation_coverage.get("missing_relation_count")),
            "figure_matched_section_count": _safe_int(figure_relation_coverage.get("matched_section_count")),
            "bm25_metadata_status": bm25_metadata_contract.get("status"),
            "bm25_metadata_missing_row_count": _safe_int(bm25_metadata_contract.get("missing_row_count")),
        },
        "failures": list(payload.get("failures") or []),
    }


def _customer_master_contract(
    payload: dict[str, Any],
    *,
    material_scope: dict[str, Any],
) -> dict[str, Any]:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    material_enabled = bool(material_scope.get("enabled"))
    material_count = _safe_int(material_scope.get("deduplicated_source_count"))
    source_count = _safe_int(payload.get("source_count"))
    checks = {
        "customer_master_ready": payload.get("status") == "ready",
        "publish_ready": bool(payload.get("publish_ready")),
        "runtime_eligible": bool(payload.get("runtime_eligible")),
        "validation_ok": bool(validation.get("ok")),
        "all_master_sources_covered": float(validation.get("source_coverage_ratio") or 0.0) >= 1.0,
        "source_count_present": source_count > 0,
        "material_sources_covered": (
            True
            if not material_enabled or material_count == 0
            else source_count >= material_count
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "master_slug": payload.get("master_slug"),
        "source_count": source_count,
        "section_count": payload.get("section_count"),
        "chunk_count": payload.get("chunk_count"),
        "shared_grade": payload.get("shared_grade"),
        "validation": validation,
        "material_scope": material_scope,
    }


def _runtime_maintenance_contract(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "ok": bool(summary.get("ok")),
        "summary": summary,
    }


def _material_scope(root_dir: Path, materials_root: Path | None) -> dict[str, Any]:
    if materials_root is None:
        return {"enabled": False, "reason": "materials_root_not_configured"}
    target = materials_root if materials_root.is_absolute() else root_dir / materials_root
    if not target.exists():
        return {
            "enabled": False,
            "materials_root": str(target),
            "reason": "materials_root_missing",
        }
    sources = discover_customer_pack_batch_sources(target)
    return {
        "enabled": True,
        "materials_root": str(target),
        "deduplicated_source_count": len(sources),
        "material_file_count": len(sources) + sum(len(source.aliases) for source in sources),
        "source_names": [source.source_name for source in sources],
    }


def build_llmwiki_promotion_summary(
    *,
    official_gold: dict[str, Any],
    customer_master: dict[str, Any],
    runtime_report: dict[str, Any],
    runtime_maintenance: dict[str, Any],
    chat_matrix: dict[str, Any],
    material_scope: dict[str, Any],
) -> dict[str, Any]:
    chat_contract = _chat_matrix_live_contract(chat_matrix)
    contracts = {
        "official_gold": _official_gold_contract(official_gold),
        "customer_master": _customer_master_contract(
            customer_master,
            material_scope=material_scope,
        ),
        "runtime_report": _runtime_report_contract(
            runtime_report,
            chat_matrix_contract=chat_contract,
        ),
        "runtime_maintenance": _runtime_maintenance_contract(runtime_maintenance),
        "chat_matrix": chat_contract,
    }
    failures = [name for name, contract in contracts.items() if not contract.get("ok")]
    return {
        "status": "ok" if not failures else "fail",
        "ready_for_llmwiki_promotion": not failures,
        "failures": failures,
        "contracts": contracts,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_llmwiki_promotion_report(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    master_slug: str = DEFAULT_MASTER_BOOK_SLUG,
    master_title: str = DEFAULT_MASTER_BOOK_TITLE,
    materials_root: str | Path | None = None,
    include_test_sources: bool = False,
    chat_matrix_timeout_seconds: float = 90.0,
    runtime_report_sample: bool = True,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir)
    target = Path(output_path).resolve() if output_path else _evidence_path(root, "llmwiki-promotion-report")
    material_root_path = Path(materials_root) if materials_root is not None else root / ".P_docs" / "01_검토대기_플레이북재료"
    evidence_paths = {
        "artifact_manifest": _evidence_path(root, "llmwiki-promotion-artifact-manifest"),
        "official_gold_gate": _evidence_path(root, "llmwiki-promotion-official-gold-gate"),
        "customer_master": _evidence_path(root, "llmwiki-promotion-customer-master"),
        "runtime_report": _evidence_path(root, "llmwiki-promotion-runtime-report"),
        "runtime_maintenance": _evidence_path(root, "llmwiki-promotion-runtime-maintenance"),
        "chat_matrix": _evidence_path(root, "llmwiki-promotion-chat-matrix"),
    }

    artifact_manifest_path, artifact_manifest = write_artifact_manifest(
        root,
        output_path=evidence_paths["artifact_manifest"],
    )
    official_gate_path, official_gold = write_official_gold_gate_report(
        root,
        output_path=evidence_paths["official_gold_gate"],
    )
    _book_path, customer_master = write_customer_master_book(
        root,
        master_slug=master_slug,
        title=master_title,
        include_test_sources=include_test_sources,
    )
    _write_json(evidence_paths["customer_master"], customer_master)
    material_scope = _material_scope(root, material_root_path)
    runtime_report_path, runtime_report = write_runtime_report(
        root,
        output_path=evidence_paths["runtime_report"],
        ui_base_url=ui_base_url,
        sample=runtime_report_sample,
    )
    runtime_maintenance_path, runtime_maintenance = write_runtime_maintenance_smoke(
        root,
        output_path=evidence_paths["runtime_maintenance"],
        ui_base_url=ui_base_url,
    )
    chat_matrix_path, chat_matrix = write_chat_matrix_smoke(
        root,
        output_path=evidence_paths["chat_matrix"],
        ui_base_url=ui_base_url,
        timeout_seconds=chat_matrix_timeout_seconds,
    )
    summary = build_llmwiki_promotion_summary(
        official_gold=official_gold,
        customer_master=customer_master,
        runtime_report=runtime_report,
        runtime_maintenance=runtime_maintenance,
        chat_matrix=chat_matrix,
        material_scope=material_scope,
    )
    payload = {
        "generated_at": _iso_timestamp(),
        "git": _git_refs(root),
        "goal": "growing_llmwiki_operational_and_training_runtime",
        "status": summary["status"],
        "ready_for_llmwiki_promotion": summary["ready_for_llmwiki_promotion"],
        "summary": summary,
        "commands": {
            "promotion_report": (
                "python -m play_book_studio.cli llmwiki-promotion "
                f"--ui-base-url {ui_base_url}"
            ),
            "full_official_gold_rebuild": (
                f"{OFFICIAL_GOLD_REBUILD_COMMAND} "
                f"--full-official-catalog --gold-runtime-profile --ui-base-url {ui_base_url}"
            ),
        },
        "evidence": {
            "artifact_manifest": str(artifact_manifest_path),
            "official_gold_gate": str(official_gate_path),
            "customer_master": str(evidence_paths["customer_master"]),
            "runtime_report": str(runtime_report_path),
            "runtime_maintenance": str(runtime_maintenance_path),
            "chat_matrix": str(chat_matrix_path),
        },
        "official_gold": summary["contracts"]["official_gold"],
        "customer_master": summary["contracts"]["customer_master"],
        "runtime_report": summary["contracts"]["runtime_report"],
        "runtime_maintenance": summary["contracts"]["runtime_maintenance"],
        "chat_matrix": summary["contracts"]["chat_matrix"],
        "artifact_manifest": {
            "path": str(artifact_manifest_path),
            "artifact_count": len(artifact_manifest.get("artifacts", [])),
            "policy": artifact_manifest.get("policy", {}),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload


__all__ = [
    "build_llmwiki_promotion_summary",
    "write_llmwiki_promotion_report",
]
