from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from play_book_studio.app.llmwiki_promotion_report import write_llmwiki_promotion_report
from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL
from play_book_studio.chat_modes import chat_mode_contract
from play_book_studio.config.settings import Settings, load_settings

PromotionWriter = Callable[..., tuple[Path, dict[str, Any]]]


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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dict_from(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_from(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _reports_dir(root_dir: Path) -> Path:
    return root_dir / ".kugnusdocs" / "reports"


def _evidence_path(root_dir: Path, name: str) -> Path:
    return _reports_dir(root_dir) / f"{date.today().isoformat()}-{name}.json"


def build_surya_optional_policy(settings: Settings) -> dict[str, Any]:
    endpoint_configured = bool(settings.surya_ocr_endpoint)
    health_endpoint_configured = bool(settings.surya_health_endpoint)
    qwen_ocr_configured = bool(settings.qwen_ocr_endpoint and settings.qwen_ocr_model)
    return {
        "id": "surya_ocr",
        "label": "Surya OCR",
        "status": "offline_allowed" if endpoint_configured or health_endpoint_configured else "not_configured",
        "required_for_llmwiki_runtime": False,
        "required_for_chat_and_playbook_reading": False,
        "endpoint_configured": endpoint_configured,
        "health_endpoint_configured": health_endpoint_configured,
        "qwen_ocr_fallback_configured": qwen_ocr_configured,
        "gate_policy": "do_not_fail_llmwiki_runtime_when_surya_is_off",
        "unaffected_when_off": [
            "official_manual_viewer",
            "customer_ppt_playbooks_already_materialized",
            "qdrant_vector_retrieval",
            "bm25_retrieval",
            "learn_ops_chat_modes",
            "control_tower_readiness",
        ],
        "degraded_when_off": [
            "new_scanned_pdf_ocr",
            "new_image_only_document_ocr",
            "ocr_fallback_quality_validation",
        ],
    }


def _chat_modes_locked() -> bool:
    modes = {
        str(item.get("id") or "").strip()
        for item in _list_from(chat_mode_contract().get("supported_modes"))
        if isinstance(item, dict)
    }
    return modes == {"learn", "ops"}


def _promotion_acceptance(payload: dict[str, Any], *, surya_policy: dict[str, Any]) -> dict[str, Any]:
    official_gold = _dict_from(payload.get("official_gold"))
    customer_master = _dict_from(payload.get("customer_master"))
    runtime_report = _dict_from(payload.get("runtime_report"))
    runtime_maintenance = _dict_from(payload.get("runtime_maintenance"))
    chat_matrix = _dict_from(payload.get("chat_matrix"))
    chat_runtime = _dict_from(chat_matrix.get("runtime_requirements"))
    runtime_checks = _dict_from(runtime_report.get("checks"))
    checks = {
        "official_gold_ready": bool(official_gold.get("ok")),
        "customer_master_ready": bool(customer_master.get("ok")),
        "essential_runtime_ready": bool(runtime_report.get("ok")),
        "runtime_maintenance_ready": bool(runtime_maintenance.get("ok")),
        "chat_matrix_ready": bool(chat_matrix.get("ok")),
        "chat_live_llm_ready": _safe_int(chat_runtime.get("llm_live_total")) > 0
        and _safe_int(chat_runtime.get("llm_live_pass_count")) == _safe_int(chat_runtime.get("llm_live_total")),
        "chat_live_vector_ready": _safe_int(chat_runtime.get("vector_live_total")) > 0
        and _safe_int(chat_runtime.get("vector_live_pass_count")) == _safe_int(chat_runtime.get("vector_live_total")),
        "learn_ops_modes_locked": _chat_modes_locked(),
        "surya_is_optional": not bool(surya_policy.get("required_for_llmwiki_runtime")),
    }
    services = {
        "local_ui": bool(runtime_checks.get("local_ui_health_ok")),
        "embedding": bool(runtime_checks.get("embedding_sample_ok")),
        "qdrant": bool(runtime_checks.get("qdrant_collection_present")),
        "llm_config": bool(runtime_checks.get("llm_endpoint_configured")),
        "chat_llm": checks["chat_live_llm_ready"],
        "chat_vector": checks["chat_live_vector_ready"],
        "surya_ocr": "optional_offline_allowed",
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failures,
        "checks": checks,
        "failures": failures,
        "essential_services": services,
        "metrics": {
            "official_chunks": _safe_int(_dict_from(official_gold.get("metrics")).get("chunks_count")),
            "official_code_blocks": _safe_int(_dict_from(official_gold.get("metrics")).get("code_blocks")),
            "official_figures": _safe_int(_dict_from(official_gold.get("metrics")).get("playbook_figure_blocks")),
            "customer_sources": _safe_int(customer_master.get("source_count")),
            "customer_sections": _safe_int(customer_master.get("section_count")),
            "chat_live_pass_count": _safe_int(chat_runtime.get("llm_live_pass_count"))
            + _safe_int(chat_runtime.get("vector_live_pass_count")),
            "chat_live_total": _safe_int(chat_runtime.get("llm_live_total"))
            + _safe_int(chat_runtime.get("vector_live_total")),
        },
    }


def _iteration_row(
    *,
    index: int,
    report_path: Path,
    payload: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "iteration": index,
        "generated_at": str(payload.get("generated_at") or ""),
        "promotion_report_path": str(report_path),
        "status": "ok" if acceptance.get("ok") else "fail",
        "ready_for_llmwiki_promotion": bool(payload.get("ready_for_llmwiki_promotion")),
        "failures": list(acceptance.get("failures") or []),
        "metrics": acceptance.get("metrics", {}),
    }


def build_llmwiki_validation_loop_report(
    root_dir: str | Path,
    *,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    iterations: int = 1,
    stop_on_pass: bool = True,
    chat_matrix_timeout_seconds: float = 90.0,
    runtime_report_sample: bool = True,
    promotion_writer: PromotionWriter = write_llmwiki_promotion_report,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    surya_policy = build_surya_optional_policy(settings)
    requested_iterations = max(1, int(iterations or 1))
    iteration_rows: list[dict[str, Any]] = []
    final_acceptance: dict[str, Any] = {
        "ok": False,
        "checks": {},
        "failures": ["validation_loop_not_run"],
        "essential_services": {},
        "metrics": {},
    }
    final_payload: dict[str, Any] = {}
    final_report_path = Path("")

    for index in range(1, requested_iterations + 1):
        try:
            report_path, payload = promotion_writer(
                root,
                ui_base_url=ui_base_url,
                chat_matrix_timeout_seconds=chat_matrix_timeout_seconds,
                runtime_report_sample=runtime_report_sample,
            )
        except Exception as exc:  # noqa: BLE001
            acceptance = {
                "ok": False,
                "checks": {"promotion_command_completed": False, "surya_is_optional": True},
                "failures": ["promotion_command_error"],
                "essential_services": {"surya_ocr": "optional_offline_allowed"},
                "metrics": {},
                "error": str(exc),
            }
            iteration_rows.append(
                {
                    "iteration": index,
                    "generated_at": _iso_timestamp(),
                    "promotion_report_path": "",
                    "status": "fail",
                    "ready_for_llmwiki_promotion": False,
                    "failures": acceptance["failures"],
                    "error": str(exc),
                }
            )
            final_acceptance = acceptance
            final_payload = {}
            continue

        acceptance = _promotion_acceptance(payload, surya_policy=surya_policy)
        iteration_rows.append(
            _iteration_row(
                index=index,
                report_path=report_path,
                payload=payload,
                acceptance=acceptance,
            )
        )
        final_acceptance = acceptance
        final_payload = payload
        final_report_path = report_path
        if acceptance.get("ok") and stop_on_pass:
            break

    status = "ok" if final_acceptance.get("ok") else "fail"
    return {
        "generated_at": _iso_timestamp(),
        "git": _git_refs(root),
        "goal": "repeatable_llmwiki_validation_loop_without_surya_runtime_dependency",
        "status": status,
        "ready": status == "ok",
        "requested_iterations": requested_iterations,
        "completed_iterations": len(iteration_rows),
        "stop_on_pass": stop_on_pass,
        "ui_base_url": ui_base_url.rstrip("/"),
        "surya_policy": surya_policy,
        "acceptance": final_acceptance,
        "iterations": iteration_rows,
        "final_promotion_report_path": str(final_report_path) if str(final_report_path) != "." else "",
        "final_promotion_status": str(final_payload.get("status") or ""),
        "final_promotion_ready": bool(final_payload.get("ready_for_llmwiki_promotion")),
        "commands": {
            "validation_loop": (
                "python -m play_book_studio.cli llmwiki-loop "
                f"--ui-base-url {ui_base_url} --iterations {requested_iterations}"
            ),
            "promotion_report": (
                "python -m play_book_studio.cli llmwiki-promotion "
                f"--ui-base-url {ui_base_url}"
            ),
            "gold_rebuild": (
                "python -m play_book_studio.cli official-gold-rebuild "
                f"--full-official-catalog --gold-runtime-profile --ui-base-url {ui_base_url}"
            ),
        },
        "evidence": {
            "final_promotion_report": str(final_report_path) if str(final_report_path) != "." else "",
        },
    }


def write_llmwiki_validation_loop_report(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    iterations: int = 1,
    stop_on_pass: bool = True,
    chat_matrix_timeout_seconds: float = 90.0,
    runtime_report_sample: bool = True,
    promotion_writer: PromotionWriter = write_llmwiki_promotion_report,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir).resolve()
    payload = build_llmwiki_validation_loop_report(
        root,
        ui_base_url=ui_base_url,
        iterations=iterations,
        stop_on_pass=stop_on_pass,
        chat_matrix_timeout_seconds=chat_matrix_timeout_seconds,
        runtime_report_sample=runtime_report_sample,
        promotion_writer=promotion_writer,
    )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else _evidence_path(root, "llmwiki-validation-loop")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload


__all__ = [
    "build_llmwiki_validation_loop_report",
    "build_surya_optional_policy",
    "write_llmwiki_validation_loop_report",
]
