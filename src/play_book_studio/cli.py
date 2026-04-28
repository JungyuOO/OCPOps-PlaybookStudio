"""제품 전체의 표준 실행 진입점.

어떤 명령이 존재하고, 각 명령이 어떤 런타임을 띄우는지 이해하려면
가장 먼저 이 파일을 보면 된다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.app.chat_matrix_smoke import write_chat_matrix_smoke, write_role_rehearsal
from play_book_studio.app.customer_pack_batch import write_customer_pack_material_batch_report
from play_book_studio.app.customer_master_book import (
    DEFAULT_MASTER_BOOK_SLUG,
    DEFAULT_MASTER_BOOK_TITLE,
    write_customer_master_book,
)
from play_book_studio.app.llmwiki_absorption_audit import write_llmwiki_absorption_audit_report
from play_book_studio.app.llmwiki_contextual_enrichment_gate import (
    write_llmwiki_contextual_enrichment_gate_report,
)
from play_book_studio.app.llmwiki_evolution_gate import write_llmwiki_evolution_gate_report
from play_book_studio.app.llmwiki_promotion_report import write_llmwiki_promotion_report
from play_book_studio.app.llmwiki_validation_loop import write_llmwiki_validation_loop_report
from play_book_studio.app.private_lane_smoke import write_private_lane_smoke
from play_book_studio.app.role_continuity_rehearsal import write_role_continuity_rehearsal
from play_book_studio.app.runtime_maintenance_smoke import write_runtime_maintenance_smoke
from play_book_studio.app.runtime_report import (
    DEFAULT_PLAYBOOK_UI_BASE_URL,
    write_runtime_report,
)
from play_book_studio.app.server import serve
from play_book_studio.config.settings import load_effective_env, load_settings
from play_book_studio.evals.answer_eval import evaluate_case, summarize_case_results
from play_book_studio.ingestion.graph_sidecar import write_graph_sidecar_compact_from_artifacts
from play_book_studio.ingestion.localization_quality import build_official_ko_localization_audit
from play_book_studio.ingestion.official_gold_gate import (
    ARTIFACT_MANIFEST_RELATIVE_PATH,
    ONE_CLICK_REPORT_RELATIVE_PATH,
    materialize_runtime_markdown_from_playbooks,
    publish_runtime_manifest_from_playbooks,
    repair_portable_json_paths,
    write_artifact_manifest,
    write_official_gold_gate_report,
)
from play_book_studio.ingestion.pipeline import run_ingestion_pipeline
from play_book_studio.retrieval.models import SessionContext

ROOT = Path(__file__).resolve().parents[2]


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--max-context-chunks", type=int, default=6)


def build_parser() -> argparse.ArgumentParser:
    # 지원하는 명령을 한곳에 모아 두어, 하위 모듈로 내려가기 전에
    # 전체 실행 구조를 한 파일에서 설명할 수 있게 한다.
    parser = argparse.ArgumentParser(
        description="Play Book Studio canonical entrypoint",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ui_parser = subparsers.add_parser("ui", help="Run the local runtime/API server")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=8876)
    ui_parser.add_argument("--no-browser", action="store_true")
    ui_parser.add_argument(
        "--warmup-reranker",
        action="store_true",
        help="Warm the reranker model before serve. Disabled by default to keep shared serve startup fast.",
    )

    ask_parser = subparsers.add_parser("ask", help="Run a single grounded answer query")
    ask_parser.add_argument("--query", required=True)
    ask_parser.add_argument("--context-json")
    ask_parser.add_argument(
        "--mode",
        choices=("chat", "ops", "learn"),
        default="chat",
        help="Answer mode for the query.",
    )
    ask_parser.add_argument("--skip-log", action="store_true")
    _add_runtime_args(ask_parser)

    eval_parser = subparsers.add_parser("eval", help="Run answer evaluation cases")
    eval_parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "manifests" / "answer_eval_cases.jsonl",
    )
    _add_runtime_args(eval_parser)

    ragas_parser = subparsers.add_parser("ragas", help="Run RAGAS evaluation")
    ragas_parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "manifests" / "ragas_eval_cases.jsonl",
    )
    ragas_parser.add_argument("--batch-size", type=int, default=2)
    ragas_parser.add_argument("--judge-model", default=None)
    ragas_parser.add_argument("--embedding-model", default=None)
    ragas_parser.add_argument("--dry-run", action="store_true")
    _add_runtime_args(ragas_parser)

    runtime_parser = subparsers.add_parser("runtime", help="Write a runtime readiness report")
    runtime_parser.add_argument("--output", type=Path, default=None)
    runtime_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    runtime_parser.add_argument("--recent-turns", type=int, default=3)
    runtime_parser.add_argument("--skip-samples", action="store_true")

    maintenance_smoke_parser = subparsers.add_parser(
        "maintenance-smoke",
        help="Refresh graph maintenance artifacts and validate /api/health plus /api/chat",
    )
    maintenance_smoke_parser.add_argument("--output", type=Path, default=None)
    maintenance_smoke_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    maintenance_smoke_parser.add_argument(
        "--query",
        default="OpenShift architecture overview",
    )

    chat_matrix_smoke_parser = subparsers.add_parser(
        "chat-matrix-smoke",
        help="Validate live /api/chat answers across official, customer, and blended document lanes",
    )
    chat_matrix_smoke_parser.add_argument("--output", type=Path, default=None)
    chat_matrix_smoke_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    chat_matrix_smoke_parser.add_argument("--cases", type=Path, default=None)
    chat_matrix_smoke_parser.add_argument("--timeout-seconds", type=float, default=90.0)

    role_rehearsal_parser = subparsers.add_parser(
        "role-rehearsal",
        help="Validate live /api/chat as operator A and learner B product roles",
    )
    role_rehearsal_parser.add_argument("--output", type=Path, default=None)
    role_rehearsal_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    role_rehearsal_parser.add_argument("--cases", type=Path, default=None)
    role_rehearsal_parser.add_argument("--timeout-seconds", type=float, default=90.0)

    role_continuity_parser = subparsers.add_parser(
        "role-continuity",
        help="Validate 10-turn operator and learner continuity against live /api/chat",
    )
    role_continuity_parser.add_argument("--output", type=Path, default=None)
    role_continuity_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    role_continuity_parser.add_argument("--timeout-seconds", type=float, default=120.0)

    private_lane_smoke_parser = subparsers.add_parser(
        "private-lane-smoke",
        help="Ingest a synthetic private markdown pack and validate library plus chat boundary handling",
    )
    private_lane_smoke_parser.add_argument("--output", type=Path, default=None)
    private_lane_smoke_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    private_lane_smoke_parser.add_argument(
        "--query-template",
        default="{token} 문서를 보여줘",
    )

    compact_graph_parser = subparsers.add_parser(
        "graph-compact",
        help="Rebuild the compact graph fallback artifact from current chunks and playbook documents",
    )
    compact_graph_parser.add_argument("--output", type=Path, default=None)

    official_gold_gate_parser = subparsers.add_parser(
        "official-gold-gate",
        help="Validate OCP official gold-book reproducibility, figure, code, and viewer gates",
    )
    official_gold_gate_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ONE_CLICK_REPORT_RELATIVE_PATH,
    )
    official_gold_gate_parser.add_argument(
        "--artifact-manifest",
        type=Path,
        default=ROOT / ARTIFACT_MANIFEST_RELATIVE_PATH,
    )
    official_gold_gate_parser.add_argument(
        "--repair-portable-paths",
        action="store_true",
        help="Rewrite known runtime/source-first manifest paths to repo-relative portable paths before validation.",
    )

    official_gold_rebuild_parser = subparsers.add_parser(
        "official-gold-rebuild",
        help="Rebuild OCP official gold-book artifacts, repair portable paths, and run the gold gate",
    )
    official_gold_rebuild_parser.add_argument("--collect-subset", choices=("all", "high-value"), default="all")
    official_gold_rebuild_parser.add_argument("--process-subset", choices=("all", "high-value"), default="all")
    official_gold_rebuild_parser.add_argument("--collect-limit", type=int, default=None)
    official_gold_rebuild_parser.add_argument("--process-limit", type=int, default=None)
    official_gold_rebuild_parser.add_argument("--force-collect", action="store_true")
    official_gold_rebuild_parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Runtime manifest to rebuild from. Defaults to configured SOURCE_MANIFEST_PATH.",
    )
    official_gold_rebuild_parser.add_argument(
        "--full-official-catalog",
        action="store_true",
        help="Use the active pack html-single catalog as the rebuild source manifest.",
    )
    official_gold_rebuild_parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Also rebuild embeddings. Disabled by default so the gold artifact rebuild stays local and deterministic.",
    )
    official_gold_rebuild_parser.add_argument(
        "--with-qdrant",
        action="store_true",
        help="Also upsert rebuilt embeddings to Qdrant. Implies --with-embeddings.",
    )
    official_gold_rebuild_parser.add_argument(
        "--gold-runtime-profile",
        action="store_true",
        help=(
            "Run the full gold runtime contract: embeddings, Qdrant upsert, "
            "runtime maintenance smoke, and live chat matrix smoke."
        ),
    )
    official_gold_rebuild_parser.add_argument(
        "--ui-base-url",
        default=DEFAULT_PLAYBOOK_UI_BASE_URL,
        help="Runtime server base URL used by --gold-runtime-profile smoke probes.",
    )
    official_gold_rebuild_parser.add_argument(
        "--runtime-smoke-output",
        type=Path,
        default=None,
        help="Output path for the runtime maintenance smoke in --gold-runtime-profile.",
    )
    official_gold_rebuild_parser.add_argument(
        "--runtime-smoke-query",
        default="OpenShift architecture overview",
        help="Probe query for the runtime maintenance smoke in --gold-runtime-profile.",
    )
    official_gold_rebuild_parser.add_argument(
        "--chat-matrix-output",
        type=Path,
        default=None,
        help="Output path for the live chat matrix smoke in --gold-runtime-profile.",
    )
    official_gold_rebuild_parser.add_argument(
        "--chat-matrix-timeout-seconds",
        type=float,
        default=90.0,
        help="Per-request timeout for the live chat matrix smoke in --gold-runtime-profile.",
    )
    official_gold_rebuild_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ONE_CLICK_REPORT_RELATIVE_PATH,
    )
    official_gold_rebuild_parser.add_argument(
        "--artifact-manifest",
        type=Path,
        default=ROOT / ARTIFACT_MANIFEST_RELATIVE_PATH,
    )
    official_gold_rebuild_parser.add_argument(
        "--localization-repair-passes",
        type=int,
        default=2,
        help=(
            "Automatically rerun the full official catalog rebuild when the Korean "
            "localization gate or a transient translation transport error fails."
        ),
    )

    customer_pack_batch_parser = subparsers.add_parser(
        "customer-pack-batch",
        help="Batch ingest customer material PPT sources into the custom playbook pipeline",
    )
    customer_pack_batch_parser.add_argument(
        "--materials-root",
        type=Path,
        default=ROOT / ".P_docs" / "01_검토대기_플레이북재료",
    )
    customer_pack_batch_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-customer-pack-material-batch.json",
    )
    customer_pack_batch_parser.add_argument("--approval-state", default="approved")
    customer_pack_batch_parser.add_argument("--publication-state", default="active")

    customer_master_parser = subparsers.add_parser(
        "customer-master-book",
        help="Compose one customer master playbook from approved customer pack PPT books",
    )
    customer_master_parser.add_argument("--slug", default=DEFAULT_MASTER_BOOK_SLUG)
    customer_master_parser.add_argument("--title", default=DEFAULT_MASTER_BOOK_TITLE)
    customer_master_parser.add_argument(
        "--source-draft-id",
        action="append",
        default=[],
        help="Limit composition to selected source draft ids. Can be passed more than once.",
    )
    customer_master_parser.add_argument(
        "--include-test-sources",
        action="store_true",
        help="Include sources whose title/source path looks like a test run.",
    )
    customer_master_parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-customer-master-book-report.json",
    )

    llmwiki_promotion_parser = subparsers.add_parser(
        "llmwiki-promotion",
        help="Validate official docs, customer master book, live LLM/vector chat, and runtime readiness as one promotion gate",
    )
    llmwiki_promotion_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-llmwiki-promotion-report.json",
    )
    llmwiki_promotion_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    llmwiki_promotion_parser.add_argument("--master-slug", default=DEFAULT_MASTER_BOOK_SLUG)
    llmwiki_promotion_parser.add_argument("--master-title", default=DEFAULT_MASTER_BOOK_TITLE)
    llmwiki_promotion_parser.add_argument(
        "--materials-root",
        type=Path,
        default=ROOT / ".P_docs" / "01_검토대기_플레이북재료",
    )
    llmwiki_promotion_parser.add_argument(
        "--include-test-sources",
        action="store_true",
        help="Include customer sources whose title/source path looks like a test run.",
    )
    llmwiki_promotion_parser.add_argument("--chat-matrix-timeout-seconds", type=float, default=90.0)
    llmwiki_promotion_parser.add_argument(
        "--skip-runtime-samples",
        action="store_true",
        help="Skip direct LLM/embedding samples in the runtime report; live chat matrix still runs.",
    )

    llmwiki_loop_parser = subparsers.add_parser(
        "llmwiki-loop",
        help="Run repeatable LLMWiki validation loops with Surya OCR treated as optional",
    )
    llmwiki_loop_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-llmwiki-validation-loop.json",
    )
    llmwiki_loop_parser.add_argument("--ui-base-url", default=DEFAULT_PLAYBOOK_UI_BASE_URL)
    llmwiki_loop_parser.add_argument("--iterations", type=int, default=1)
    llmwiki_loop_parser.add_argument(
        "--continue-after-pass",
        action="store_true",
        help="Continue running all requested iterations even after the first pass.",
    )
    llmwiki_loop_parser.add_argument("--chat-matrix-timeout-seconds", type=float, default=90.0)
    llmwiki_loop_parser.add_argument(
        "--skip-runtime-samples",
        action="store_true",
        help="Skip direct LLM/embedding samples in the runtime report; live chat matrix still runs.",
    )

    llmwiki_absorption_parser = subparsers.add_parser(
        "llmwiki-absorption-audit",
        help="Audit whether beyond-RAG LLMWiki doctrine is locked and backed by current evidence",
    )
    llmwiki_absorption_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-llmwiki-absorption-audit.json",
    )
    llmwiki_absorption_parser.add_argument("--contract", type=Path, default=None)
    llmwiki_absorption_parser.add_argument("--promotion-report", type=Path, default=None)
    llmwiki_absorption_parser.add_argument("--validation-loop-report", type=Path, default=None)
    llmwiki_absorption_parser.add_argument("--role-continuity-report", type=Path, default=None)
    llmwiki_absorption_parser.add_argument("--evolution-gate-report", type=Path, default=None)
    llmwiki_absorption_parser.add_argument("--contextual-enrichment-report", type=Path, default=None)

    llmwiki_contextual_parser = subparsers.add_parser(
        "llmwiki-contextual-enrichment-gate",
        help="Run P1 contextual chunk enrichment coverage and recall gate",
    )
    llmwiki_contextual_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-llmwiki-contextual-enrichment-gate.json",
    )
    llmwiki_contextual_parser.add_argument("--official-bm25", type=Path, default=None)

    llmwiki_evolution_parser = subparsers.add_parser(
        "llmwiki-evolution-gate",
        help="Run P0 beyond-RAG LLMWiki quality, backwrite-candidate, and anti-rot gates",
    )
    llmwiki_evolution_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-llmwiki-evolution-gate.json",
    )
    llmwiki_evolution_parser.add_argument("--chat-matrix-report", type=Path, default=None)
    llmwiki_evolution_parser.add_argument("--role-continuity-report", type=Path, default=None)
    llmwiki_evolution_parser.add_argument("--promotion-report", type=Path, default=None)
    llmwiki_evolution_parser.add_argument("--validation-loop-report", type=Path, default=None)

    return parser


def _build_answerer() -> ChatAnswerer:
    settings = load_settings(ROOT)
    return ChatAnswerer.from_settings(settings)


def _warmup_ui_runtime(answerer: ChatAnswerer) -> None:
    reranker = getattr(answerer.retriever, "reranker", None)
    if reranker is None:
        return
    try:
        warmed = reranker.warmup()
    except Exception as exc:  # noqa: BLE001
        print(f"[ui] reranker warmup failed: {exc}")
        return
    if warmed:
        print(f"[ui] reranker warmed: {reranker.model_name}")


def _run_ui(args: argparse.Namespace) -> int:
    answerer = _build_answerer()
    if getattr(args, "warmup_reranker", False):
        _warmup_ui_runtime(answerer)
    serve(
        answerer=answerer,
        root_dir=ROOT,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


def _run_ask(args: argparse.Namespace) -> int:
    answerer = _build_answerer()
    context = SessionContext.from_dict(
        json.loads(args.context_json) if args.context_json else None
    )
    result = answerer.answer(
        args.query,
        mode=args.mode,
        context=context,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        max_context_chunks=args.max_context_chunks,
    )
    if not args.skip_log:
        answerer.append_log(result)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _run_eval(args: argparse.Namespace) -> int:
    answerer = _build_answerer()
    cases = _read_jsonl(args.cases)
    details: list[dict] = []
    for case in cases:
        details.append(
            evaluate_case(
                answerer,
                case,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
                max_context_chunks=args.max_context_chunks,
            )
        )

    settings = answerer.settings
    report = {
        "cases_file": str(args.cases),
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "max_context_chunks": args.max_context_chunks,
        **summarize_case_results(details),
        "details": details,
    }
    output_path = settings.answer_eval_report_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote answer eval report: {output_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _run_ragas(args: argparse.Namespace) -> int:
    from play_book_studio.evals.ragas_eval import (
        build_ragas_case_row,
        evaluate_cases_with_ragas,
        generate_answers_for_cases,
        load_openai_judge_config_from_env,
    )

    answerer = _build_answerer()
    cases = _read_jsonl(args.cases)
    settings = answerer.settings
    effective_env = load_effective_env(ROOT)

    if args.dry_run:
        generated_results = generate_answers_for_cases(
            answerer,
            cases,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            max_context_chunks=args.max_context_chunks,
        )
        rows: list[dict] = []
        for case, generated_result in zip(cases, generated_results, strict=True):
            row, metadata = build_ragas_case_row(case, generated_result=generated_result)
            rows.append({**metadata, **row})
        output_path = settings.ragas_dataset_preview_path
        output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote ragas dataset preview: {output_path}")
        print(
            json.dumps(
                {"case_count": len(rows), "preview_path": str(output_path)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        judge_config = load_openai_judge_config_from_env(effective_env)
    except ValueError as exc:
        print(f"ragas judge configuration error: {exc}")
        print("hint: add OPENAI_API_KEY to .env or run with --dry-run first")
        return 1

    judge_config.judge_model = args.judge_model or judge_config.judge_model
    judge_config.embedding_model = args.embedding_model or judge_config.embedding_model

    report = evaluate_cases_with_ragas(
        answerer,
        cases,
        judge_config=judge_config,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        max_context_chunks=args.max_context_chunks,
        batch_size=args.batch_size,
    )
    output_path = settings.ragas_eval_report_path
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote ragas eval report: {output_path}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def _run_runtime(args: argparse.Namespace) -> int:
    output_path, report = write_runtime_report(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        recent_turns=args.recent_turns,
        sample=not args.skip_samples,
    )
    print(f"wrote runtime report: {output_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _run_maintenance_smoke(args: argparse.Namespace) -> int:
    output_path, payload = write_runtime_maintenance_smoke(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        query=args.query,
    )
    print(f"wrote runtime maintenance smoke: {output_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return 0 if bool(summary.get("ok")) else 1


def _run_chat_matrix_smoke(args: argparse.Namespace) -> int:
    output_path, payload = write_chat_matrix_smoke(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        cases_path=args.cases,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"wrote chat matrix smoke: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "pass_count": payload.get("pass_count"),
                "total": payload.get("total"),
                "failures": [
                    {
                        "id": item.get("id"),
                        "checks": item.get("checks"),
                        "warnings": item.get("warnings"),
                        "error": item.get("error"),
                    }
                    for item in payload.get("results", [])
                    if not item.get("pass")
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("status") == "ok" else 1


def _run_role_rehearsal(args: argparse.Namespace) -> int:
    output_path, payload = write_role_rehearsal(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        cases_path=args.cases,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"wrote role rehearsal: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "pass_count": payload.get("pass_count"),
                "total": payload.get("total"),
                "roles": payload.get("roles"),
                "failures": [
                    {
                        "id": item.get("id"),
                        "role": item.get("role"),
                        "goal": item.get("goal"),
                        "checks": item.get("checks"),
                        "warnings": item.get("warnings"),
                        "missing_terms": item.get("missing_terms"),
                        "forbidden_hits": item.get("forbidden_hits"),
                        "answer_preview": item.get("answer_preview"),
                        "error": item.get("error"),
                    }
                    for item in payload.get("results", [])
                    if not item.get("pass")
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("status") == "ok" else 1


def _run_role_continuity(args: argparse.Namespace) -> int:
    output_path, payload = write_role_continuity_rehearsal(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"wrote role continuity rehearsal: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "pass_count": payload.get("pass_count"),
                "total": payload.get("total"),
                "roles": payload.get("roles"),
                "failures": [
                    {
                        "role": item.get("role"),
                        "turn": item.get("turn"),
                        "query": item.get("query"),
                        "checks": item.get("checks"),
                        "response_kind": item.get("response_kind"),
                        "citation_count": item.get("citation_count"),
                        "answer_preview": item.get("answer_preview"),
                        "error": item.get("error"),
                    }
                    for item in payload.get("results", [])
                    if not item.get("pass")
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("status") == "ok" else 1


def _run_private_lane_smoke(args: argparse.Namespace) -> int:
    output_path, payload = write_private_lane_smoke(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        query_template=args.query_template,
    )
    print(f"wrote private lane smoke: {output_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return 0 if bool(summary.get("ok")) else 1


def _run_graph_compact(args: argparse.Namespace) -> int:
    settings = load_settings(ROOT)
    output_path, payload = write_graph_sidecar_compact_from_artifacts(
        settings,
        output_path=args.output,
    )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    print(f"wrote graph sidecar compact artifact: {output_path}")
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "book_count": int(payload.get("book_count") or 0),
                "relation_count": int(payload.get("relation_count") or 0),
                "relation_group_counts": summary.get("relation_group_counts", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run_official_gold_gate(args: argparse.Namespace) -> int:
    repair_results = []
    if getattr(args, "repair_portable_paths", False):
        repair_results = repair_portable_json_paths(ROOT)
    artifact_manifest_path, artifact_manifest = write_artifact_manifest(
        ROOT,
        output_path=args.artifact_manifest,
    )
    report_path, payload = write_official_gold_gate_report(
        ROOT,
        output_path=args.output,
    )
    if repair_results:
        payload["portable_path_repair"] = repair_results
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote official gold gate report: {report_path}")
    print(f"wrote artifact manifest: {artifact_manifest_path}")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "failures": payload.get("failures", []),
                "chunks_count": payload["metrics"]["chunks_count"],
                "bm25_count": payload["metrics"]["bm25_count"],
                "figure_sidecar_count": payload["metrics"]["figure_sidecar_count"],
                "playbook_figure_blocks": payload["metrics"]["playbook_block_counts"].get("figure", 0),
                "artifact_count": len(artifact_manifest.get("artifacts", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("status") == "ok" else 1


def _localized_full_catalog_manifest(root_dir: Path, settings) -> Path:
    active_pack = settings.active_pack
    translated_all_name = f"{active_pack.manifest_prefix}_translated_ko_draft_all_runtime.json"
    translated_all_path = root_dir / "manifests" / translated_all_name
    source_catalog_path = root_dir / "manifests" / active_pack.source_catalog_name
    if not translated_all_path.exists():
        return source_catalog_path

    current_playbooks = _read_jsonl(settings.playbook_documents_path)
    localization_audit = build_official_ko_localization_audit(current_playbooks, max_examples=200)
    blocker_slugs = set(localization_audit.get("failing_book_slugs") or [])
    if not blocker_slugs:
        return source_catalog_path
    current_playbooks_by_slug = {
        str(row.get("book_slug") or "").strip(): row
        for row in current_playbooks
        if str(row.get("book_slug") or "").strip()
    }
    full_translation_slugs = {
        slug
        for slug in blocker_slugs
        if str(current_playbooks_by_slug.get(slug, {}).get("translation_status") or "").strip()
        in {"original", "en_only", "mixed"}
    }
    targeted_repair_slugs = blocker_slugs - full_translation_slugs

    source_payload = json.loads(source_catalog_path.read_text(encoding="utf-8"))
    translated_payload = json.loads(translated_all_path.read_text(encoding="utf-8"))
    translated_by_slug = {
        str(item.get("book_slug") or "").strip(): item
        for item in translated_payload.get("entries") or []
        if str(item.get("book_slug") or "").strip()
    }
    entries = []
    for item in source_payload.get("entries") or []:
        slug = str(item.get("book_slug") or "").strip()
        if slug in full_translation_slugs and slug in translated_by_slug:
            entries.append(translated_by_slug[slug])
        else:
            entries.append(item)
    output_path = root_dir / ".kugnusdocs" / "reports" / f"{active_pack.manifest_prefix}_localized_hybrid_rebuild_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                **source_payload,
                "source_strategy": "hybrid_official_ko_plus_translated_blockers",
                "localized_blocker_count": len(blocker_slugs),
                "localized_blocker_slugs": sorted(blocker_slugs),
                "full_translation_blocker_count": len(full_translation_slugs),
                "full_translation_blocker_slugs": sorted(full_translation_slugs),
                "targeted_repair_blocker_count": len(targeted_repair_slugs),
                "targeted_repair_blocker_slugs": sorted(targeted_repair_slugs),
                "translated_manifest_path": translated_all_path.relative_to(root_dir).as_posix(),
                "base_source_catalog_path": source_catalog_path.relative_to(root_dir).as_posix(),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def _is_transient_pipeline_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "connection aborted",
            "connectionreset",
            "connection reset",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "too many requests",
            "rate limit",
            "503",
            "429",
        )
    )


def _official_gold_rebuild_should_retry(
    *,
    payload: dict[str, Any],
    log_errors: list[dict[str, Any]],
    full_official_catalog: bool,
) -> tuple[bool, str]:
    failures = set(payload.get("failures") or [])
    if full_official_catalog and "ko_runtime_has_no_unlocalized_english_prose" in failures:
        return True, "ko_localization_gate_failed"
    if full_official_catalog and any(
        _is_transient_pipeline_error(str(error.get("message") or ""))
        for error in log_errors
        if isinstance(error, dict)
    ):
        return True, "transient_pipeline_error"
    return False, ""


def _official_gold_runtime_profile_enabled(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "gold_runtime_profile", False))


def _official_gold_rebuild_uses_embeddings(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "with_embeddings", False)
        or getattr(args, "with_qdrant", False)
        or _official_gold_runtime_profile_enabled(args)
    )


def _official_gold_rebuild_uses_qdrant(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "with_qdrant", False)
        or _official_gold_runtime_profile_enabled(args)
    )


def _official_gold_runtime_profile_output(name: str) -> Path:
    return ROOT / ".kugnusdocs" / "reports" / f"{date.today().isoformat()}-{name}.json"


def _runtime_maintenance_smoke_ok(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return bool(summary.get("ok"))


def _chat_matrix_smoke_ok(payload: dict[str, Any]) -> bool:
    runtime_requirements = (
        payload.get("runtime_requirements")
        if isinstance(payload.get("runtime_requirements"), dict)
        else {}
    )
    llm_live_total = int(runtime_requirements.get("llm_live_total") or 0)
    vector_live_total = int(runtime_requirements.get("vector_live_total") or 0)
    llm_live_pass_count = int(runtime_requirements.get("llm_live_pass_count") or 0)
    vector_live_pass_count = int(runtime_requirements.get("vector_live_pass_count") or 0)
    return bool(
        payload.get("status") == "ok"
        and llm_live_total > 0
        and vector_live_total > 0
        and llm_live_pass_count == llm_live_total
        and vector_live_pass_count == vector_live_total
    )


def _run_official_gold_runtime_profile(args: argparse.Namespace) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "enabled": True,
        "status": "fail",
        "ui_base_url": str(getattr(args, "ui_base_url", DEFAULT_PLAYBOOK_UI_BASE_URL)),
        "with_embeddings": _official_gold_rebuild_uses_embeddings(args),
        "with_qdrant": _official_gold_rebuild_uses_qdrant(args),
        "checks": {
            "runtime_maintenance_smoke": False,
            "chat_matrix_smoke": False,
        },
        "failures": [],
    }

    runtime_smoke_output = getattr(args, "runtime_smoke_output", None) or _official_gold_runtime_profile_output(
        "official-gold-runtime-maintenance-smoke"
    )
    try:
        output_path, payload = write_runtime_maintenance_smoke(
            ROOT,
            output_path=runtime_smoke_output,
            ui_base_url=profile["ui_base_url"],
            query=str(getattr(args, "runtime_smoke_query", "OpenShift architecture overview")),
        )
        runtime_ok = _runtime_maintenance_smoke_ok(payload)
        profile["checks"]["runtime_maintenance_smoke"] = runtime_ok
        profile["runtime_maintenance_smoke"] = {
            "path": str(output_path),
            "summary": payload.get("summary", {}),
        }
        if not runtime_ok:
            profile["failures"].append("runtime_maintenance_smoke_failed")
    except Exception as exc:  # noqa: BLE001
        profile["runtime_maintenance_smoke"] = {
            "path": str(runtime_smoke_output),
            "error": str(exc),
        }
        profile["failures"].append("runtime_maintenance_smoke_error")

    chat_matrix_output = getattr(args, "chat_matrix_output", None) or _official_gold_runtime_profile_output(
        "official-gold-chat-matrix-smoke"
    )
    try:
        output_path, payload = write_chat_matrix_smoke(
            ROOT,
            output_path=chat_matrix_output,
            ui_base_url=profile["ui_base_url"],
            timeout_seconds=float(getattr(args, "chat_matrix_timeout_seconds", 90.0) or 90.0),
        )
        chat_ok = _chat_matrix_smoke_ok(payload)
        profile["checks"]["chat_matrix_smoke"] = chat_ok
        profile["chat_matrix_smoke"] = {
            "path": str(output_path),
            "status": payload.get("status"),
            "pass_count": payload.get("pass_count"),
            "total": payload.get("total"),
            "runtime_requirements": payload.get("runtime_requirements", {}),
            "failures": [
                {
                    "id": item.get("id"),
                    "checks": item.get("checks"),
                    "warnings": item.get("warnings"),
                    "error": item.get("error"),
                }
                for item in payload.get("results", [])
                if isinstance(item, dict) and not item.get("pass")
            ],
        }
        if not chat_ok:
            profile["failures"].append("chat_matrix_smoke_failed")
    except Exception as exc:  # noqa: BLE001
        profile["chat_matrix_smoke"] = {
            "path": str(chat_matrix_output),
            "error": str(exc),
        }
        profile["failures"].append("chat_matrix_smoke_error")

    if all(bool(value) for value in profile["checks"].values()):
        profile["status"] = "ok"
    return profile


def _run_official_gold_rebuild_pass(
    args: argparse.Namespace,
    *,
    settings,
) -> dict[str, Any]:
    settings = replace(
        settings,
        graph_backend="local",
        official_html_fallback_allowed=True,
    )
    log = run_ingestion_pipeline(
        settings,
        collect_subset=args.collect_subset,
        process_subset=args.process_subset,
        collect_limit=args.collect_limit,
        process_limit=args.process_limit,
        force_collect=bool(args.force_collect),
        skip_embeddings=not _official_gold_rebuild_uses_embeddings(args),
        skip_qdrant=not _official_gold_rebuild_uses_qdrant(args),
    )
    runtime_manifest_publication = publish_runtime_manifest_from_playbooks(
        ROOT,
        source_manifest_path=settings.source_manifest_path,
    )
    markdown_materialization = materialize_runtime_markdown_from_playbooks(ROOT)
    repair_results = repair_portable_json_paths(ROOT)
    artifact_manifest_path, artifact_manifest = write_artifact_manifest(
        ROOT,
        output_path=args.artifact_manifest,
    )
    report_path, payload = write_official_gold_gate_report(
        ROOT,
        output_path=args.output,
    )
    payload["pipeline_log"] = log.to_dict()
    payload["rebuild_source_manifest_path"] = str(settings.source_manifest_path)
    payload["runtime_manifest_publication"] = runtime_manifest_publication
    payload["runtime_markdown_materialization"] = markdown_materialization
    payload["portable_path_repair"] = repair_results
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pipeline_ok = not log.errors
    gate_ok = payload.get("status") == "ok"
    return {
        "report_path": report_path,
        "artifact_manifest_path": artifact_manifest_path,
        "artifact_manifest": artifact_manifest,
        "runtime_manifest_publication": runtime_manifest_publication,
        "runtime_markdown_materialization": markdown_materialization,
        "payload": payload,
        "log": log,
        "pipeline_ok": pipeline_ok,
        "gate_ok": gate_ok,
    }


def _run_official_gold_rebuild(args: argparse.Namespace) -> int:
    base_settings = load_settings(ROOT)
    source_manifest_path: Path | None = args.source_manifest
    if getattr(args, "full_official_catalog", False):
        source_manifest_path = _localized_full_catalog_manifest(ROOT, base_settings)

    max_repair_passes = max(0, int(getattr(args, "localization_repair_passes", 0) or 0))
    attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for attempt_index in range(max_repair_passes + 1):
        source_manifest_override = str(source_manifest_path) if source_manifest_path is not None else ""
        attempt_settings = replace(
            base_settings,
            source_manifest_path_override=source_manifest_override,
        )
        result = _run_official_gold_rebuild_pass(args, settings=attempt_settings)
        last_result = result
        payload = result["payload"]
        log = result["log"]
        pipeline_ok = bool(result["pipeline_ok"])
        gate_ok = bool(result["gate_ok"])
        attempts.append(
            {
                "attempt": attempt_index + 1,
                "source_manifest_path": str(attempt_settings.source_manifest_path),
                "status": "ok" if pipeline_ok and gate_ok else "fail",
                "gate_status": payload.get("status"),
                "pipeline_error_count": len(log.errors),
                "failures": payload.get("failures", []),
            }
        )
        if pipeline_ok and gate_ok:
            break
        if attempt_index >= max_repair_passes:
            break
        should_retry, retry_reason = _official_gold_rebuild_should_retry(
            payload=payload,
            log_errors=list(log.errors),
            full_official_catalog=bool(getattr(args, "full_official_catalog", False)),
        )
        if not should_retry:
            break
        source_manifest_path = _localized_full_catalog_manifest(ROOT, base_settings)
        print(
            json.dumps(
                {
                    "status": "retrying",
                    "reason": retry_reason,
                    "next_attempt": attempt_index + 2,
                    "source_manifest_path": str(source_manifest_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    if last_result is None:
        return 1
    report_path = last_result["report_path"]
    artifact_manifest_path = last_result["artifact_manifest_path"]
    artifact_manifest = last_result["artifact_manifest"]
    runtime_manifest_publication = last_result["runtime_manifest_publication"]
    markdown_materialization = last_result["runtime_markdown_materialization"]
    payload = last_result["payload"]
    log = last_result["log"]
    pipeline_ok = bool(last_result["pipeline_ok"])
    gate_ok = bool(last_result["gate_ok"])
    payload["rebuild_attempts"] = attempts
    runtime_profile_ok = True
    if _official_gold_runtime_profile_enabled(args):
        if pipeline_ok and gate_ok:
            payload["gold_runtime_profile"] = _run_official_gold_runtime_profile(args)
            runtime_profile_ok = payload["gold_runtime_profile"].get("status") == "ok"
        else:
            payload["gold_runtime_profile"] = {
                "enabled": True,
                "status": "skipped",
                "skip_reason": "pipeline_or_gate_failed",
                "with_embeddings": _official_gold_rebuild_uses_embeddings(args),
                "with_qdrant": _official_gold_rebuild_uses_qdrant(args),
            }
            runtime_profile_ok = False
    else:
        payload["gold_runtime_profile"] = {
            "enabled": False,
            "with_embeddings": _official_gold_rebuild_uses_embeddings(args),
            "with_qdrant": _official_gold_rebuild_uses_qdrant(args),
        }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote official gold gate report: {report_path}")
    print(f"wrote artifact manifest: {artifact_manifest_path}")
    print(
        json.dumps(
            {
                "status": "ok" if pipeline_ok and gate_ok else "fail",
                "gate_status": payload.get("status"),
                "pipeline_error_count": len(log.errors),
                "manifest_count": log.manifest_count,
                "normalized_count": log.normalized_count,
                "chunk_count": log.chunk_count,
                "graph_book_count": log.graph_book_count,
                "graph_relation_count": log.graph_relation_count,
                "runtime_manifest_count": runtime_manifest_publication.get("runtime_count", 0),
                "runtime_markdown_written": sum(
                    len(item.get("written", []))
                    for item in markdown_materialization
                    if isinstance(item, dict)
                ),
                "playbook_figure_blocks": payload["metrics"]["playbook_block_counts"].get("figure", 0),
                "artifact_count": len(artifact_manifest.get("artifacts", [])),
                "gold_runtime_profile": {
                    "enabled": bool(payload["gold_runtime_profile"].get("enabled")),
                    "status": payload["gold_runtime_profile"].get("status"),
                    "checks": payload["gold_runtime_profile"].get("checks", {}),
                    "failures": payload["gold_runtime_profile"].get("failures", []),
                },
                "failures": payload.get("failures", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if pipeline_ok and gate_ok and runtime_profile_ok else 1


def _run_customer_pack_batch(args: argparse.Namespace) -> int:
    output_path, payload = write_customer_pack_material_batch_report(
        ROOT,
        materials_root=args.materials_root,
        output_path=args.output,
        approval_state=args.approval_state,
        publication_state=args.publication_state,
    )
    print(f"wrote customer pack batch report: {output_path}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if bool(payload["summary"].get("customer_llmwiki_ready")) else 1


def _run_customer_master_book(args: argparse.Namespace) -> int:
    _book_path, payload = write_customer_master_book(
        ROOT,
        master_slug=args.slug,
        title=args.title,
        source_draft_ids=tuple(args.source_draft_id or ()) or None,
        include_test_sources=bool(args.include_test_sources),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote customer master book report: {args.report}")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "master_slug": payload["master_slug"],
                "source_count": payload["source_count"],
                "section_count": payload["section_count"],
                "shared_grade": payload["shared_grade"],
                "publish_ready": payload["publish_ready"],
                "runtime_eligible": payload["runtime_eligible"],
                "source_coverage_ratio": payload["validation"]["source_coverage_ratio"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["status"] == "ready" else 1


def _run_llmwiki_promotion(args: argparse.Namespace) -> int:
    output_path, payload = write_llmwiki_promotion_report(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        master_slug=args.master_slug,
        master_title=args.master_title,
        materials_root=args.materials_root,
        include_test_sources=bool(args.include_test_sources),
        chat_matrix_timeout_seconds=float(args.chat_matrix_timeout_seconds),
        runtime_report_sample=not bool(args.skip_runtime_samples),
    )
    print(f"wrote llmwiki promotion report: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "ready_for_llmwiki_promotion": payload.get("ready_for_llmwiki_promotion"),
                "failures": payload.get("summary", {}).get("failures", []),
                "official_gold": payload.get("official_gold", {}).get("checks", {}),
                "customer_master": payload.get("customer_master", {}).get("checks", {}),
                "runtime_report": payload.get("runtime_report", {}).get("checks", {}),
                "runtime_maintenance": payload.get("runtime_maintenance", {}).get("summary", {}),
                "chat_matrix": payload.get("chat_matrix", {}).get("runtime_requirements", {}),
                "evidence": payload.get("evidence", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("ready_for_llmwiki_promotion") else 1


def _run_llmwiki_loop(args: argparse.Namespace) -> int:
    output_path, payload = write_llmwiki_validation_loop_report(
        ROOT,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        iterations=int(args.iterations),
        stop_on_pass=not bool(args.continue_after_pass),
        chat_matrix_timeout_seconds=float(args.chat_matrix_timeout_seconds),
        runtime_report_sample=not bool(args.skip_runtime_samples),
    )
    print(f"wrote llmwiki validation loop report: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "ready": payload.get("ready"),
                "completed_iterations": payload.get("completed_iterations"),
                "failures": payload.get("acceptance", {}).get("failures", []),
                "essential_services": payload.get("acceptance", {}).get("essential_services", {}),
                "surya_policy": payload.get("surya_policy", {}),
                "final_promotion_report_path": payload.get("final_promotion_report_path"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("ready") else 1


def _run_llmwiki_absorption_audit(args: argparse.Namespace) -> int:
    output_path, payload = write_llmwiki_absorption_audit_report(
        ROOT,
        output_path=args.output,
        contract_path=args.contract,
        promotion_report_path=args.promotion_report,
        validation_loop_report_path=args.validation_loop_report,
        role_continuity_report_path=args.role_continuity_report,
        evolution_gate_report_path=args.evolution_gate_report,
        contextual_enrichment_report_path=args.contextual_enrichment_report,
    )
    print(f"wrote llmwiki absorption audit: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "ready": payload.get("ready"),
                "beyond_rag_stage": payload.get("beyond_rag_stage"),
                "full_self_evolving_llmwiki": payload.get("full_self_evolving_llmwiki"),
                "checks": payload.get("checks", {}),
                "failures": payload.get("failures", []),
                "not_yet_absorbed_lanes": payload.get("not_yet_absorbed_lanes", []),
                "next_required_lanes": payload.get("next_required_lanes", []),
                "evidence": payload.get("evidence", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("ready") else 1


def _run_llmwiki_contextual_enrichment_gate(args: argparse.Namespace) -> int:
    output_path, payload = write_llmwiki_contextual_enrichment_gate_report(
        ROOT,
        output_path=args.output,
        official_bm25_path=args.official_bm25,
    )
    coverage = payload.get("coverage", {}) if isinstance(payload.get("coverage"), dict) else {}
    total = coverage.get("total", {}) if isinstance(coverage.get("total"), dict) else {}
    print(f"wrote llmwiki contextual enrichment gate: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "ready": payload.get("ready"),
                "checks": payload.get("checks", {}),
                "failures": payload.get("failures", []),
                "row_count": total.get("row_count"),
                "runtime_contextual_count": total.get("runtime_contextual_count"),
                "persisted_contextual_count": total.get("persisted_contextual_count"),
                "recall_fixture": payload.get("recall_fixture", {}),
                "evidence": payload.get("evidence", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("ready") else 1


def _run_llmwiki_evolution_gate(args: argparse.Namespace) -> int:
    output_path, payload = write_llmwiki_evolution_gate_report(
        ROOT,
        output_path=args.output,
        chat_matrix_report_path=args.chat_matrix_report,
        role_continuity_report_path=args.role_continuity_report,
        promotion_report_path=args.promotion_report,
        validation_loop_report_path=args.validation_loop_report,
    )
    print(f"wrote llmwiki evolution gate: {output_path}")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "ready": payload.get("ready"),
                "checks": payload.get("checks", {}),
                "failures": payload.get("failures", []),
                "quality_blockers": payload.get("retrieval_quality_critic", {}).get("blocker_count"),
                "quality_warnings": payload.get("retrieval_quality_critic", {}).get("warning_count"),
                "backwrite_candidates": payload.get("wiki_backwrite_candidate", {}).get("candidate_count"),
                "anti_rot_blockers": payload.get("wiki_lint_anti_rot", {}).get("blocker_count"),
                "evidence": payload.get("evidence", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("ready") else 1


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "ui":
        return _run_ui(args)
    if args.command == "ask":
        return _run_ask(args)
    if args.command == "eval":
        return _run_eval(args)
    if args.command == "ragas":
        return _run_ragas(args)
    if args.command == "runtime":
        return _run_runtime(args)
    if args.command == "maintenance-smoke":
        return _run_maintenance_smoke(args)
    if args.command == "chat-matrix-smoke":
        return _run_chat_matrix_smoke(args)
    if args.command == "role-rehearsal":
        return _run_role_rehearsal(args)
    if args.command == "role-continuity":
        return _run_role_continuity(args)
    if args.command == "private-lane-smoke":
        return _run_private_lane_smoke(args)
    if args.command == "graph-compact":
        return _run_graph_compact(args)
    if args.command == "official-gold-gate":
        return _run_official_gold_gate(args)
    if args.command == "official-gold-rebuild":
        return _run_official_gold_rebuild(args)
    if args.command == "customer-pack-batch":
        return _run_customer_pack_batch(args)
    if args.command == "customer-master-book":
        return _run_customer_master_book(args)
    if args.command == "llmwiki-promotion":
        return _run_llmwiki_promotion(args)
    if args.command == "llmwiki-loop":
        return _run_llmwiki_loop(args)
    if args.command == "llmwiki-absorption-audit":
        return _run_llmwiki_absorption_audit(args)
    if args.command == "llmwiki-contextual-enrichment-gate":
        return _run_llmwiki_contextual_enrichment_gate(args)
    if args.command == "llmwiki-evolution-gate":
        return _run_llmwiki_evolution_gate(args)
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
