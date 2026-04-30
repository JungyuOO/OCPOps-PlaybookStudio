"""제품 전체의 표준 실행 진입점.

어떤 명령이 존재하고, 각 명령이 어떤 런타임을 띄우는지 이해하려면
가장 먼저 이 파일을 보면 된다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from play_book_studio.config.settings import load_effective_env, load_settings

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAYBOOK_UI_BASE_URL = "http://127.0.0.1:8765"


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
    ui_parser.add_argument("--port", type=int, default=8765)
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

    course_qa_parser = subparsers.add_parser(
        "course-qa",
        help="Generate, quality-gate, and run Study-docs course chat QA cases",
    )
    course_qa_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_qa_parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    course_qa_parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.jsonl"))
    course_qa_parser.add_argument("--accepted-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    course_qa_parser.add_argument("--rejected-path", type=Path, default=Path("manifests/course_qa_cases.rejected.jsonl"))
    course_qa_parser.add_argument("--report-path", type=Path, default=Path("data/course_pbs/manifests/course_qa_report.json"))
    course_qa_parser.add_argument("--target-count", type=int, default=96)
    course_qa_parser.add_argument("--min-accepted", type=int, default=None)
    course_qa_parser.add_argument("--allow-rejected", action="store_true")
    course_qa_parser.add_argument("--verbose-results", action="store_true")
    course_qa_parser.add_argument("--generate", action="store_true")
    course_qa_parser.add_argument("--run", action="store_true")

    course_qdrant_parser = subparsers.add_parser(
        "course-qdrant-upsert",
        help="Upsert existing Study-docs course and ops learning chunks into Qdrant",
    )
    course_qdrant_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_qdrant_parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    course_qdrant_parser.add_argument("--limit", type=int, default=0)
    course_qdrant_parser.add_argument("--skip-course", action="store_true")
    course_qdrant_parser.add_argument("--skip-ops-learning", action="store_true")

    course_visual_audit_parser = subparsers.add_parser(
        "course-visual-audit",
        help="Generate Course QA browser audit pages and optionally capture them with Playwright",
    )
    course_visual_audit_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_visual_audit_parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    course_visual_audit_parser.add_argument("--output-dir", type=Path, default=Path("output/playwright/course-qa-audit"))
    course_visual_audit_parser.add_argument("--capture", action="store_true")
    course_visual_audit_parser.add_argument("--host", default="127.0.0.1")
    course_visual_audit_parser.add_argument("--port", type=int, default=0)
    course_visual_audit_parser.add_argument("--session", default="course-visual-audit")
    course_visual_audit_parser.add_argument("--playwright-cmd", default="playwright-cli")

    course_ui_smoke_parser = subparsers.add_parser(
        "course-ui-smoke",
        help="Run Playwright smoke checks against the built Course UI",
    )
    course_ui_smoke_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_ui_smoke_parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    course_ui_smoke_parser.add_argument("--output-dir", type=Path, default=Path("output/playwright/course-ui-smoke"))
    course_ui_smoke_parser.add_argument("--scenario-count", type=int, default=12)
    course_ui_smoke_parser.add_argument("--host", default="127.0.0.1")
    course_ui_smoke_parser.add_argument("--port", type=int, default=0)
    course_ui_smoke_parser.add_argument("--session", default="course-ui-smoke")
    course_ui_smoke_parser.add_argument("--playwright-cmd", default="playwright-cli")

    course_ops_anchor_audit_parser = subparsers.add_parser(
        "course-ops-anchor-audit",
        help="Build the Study-docs operational learning source-anchor audit manifest",
    )
    course_ops_anchor_audit_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_ops_anchor_audit_parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    course_ops_anchor_audit_parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("data/course_pbs/manifests/ops_learning_anchor_audit_v1.json"),
    )

    course_ops_guides_parser = subparsers.add_parser(
        "course-ops-guides",
        help="Build initial Study-docs operational learning guides and beginner golden cases",
    )
    course_ops_guides_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_ops_guides_parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    course_ops_guides_parser.add_argument(
        "--guides-path",
        type=Path,
        default=Path("data/course_pbs/manifests/ops_learning_guides_v1.json"),
    )
    course_ops_guides_parser.add_argument(
        "--golden-path",
        type=Path,
        default=Path("manifests/course_ops_learning_golden_cases.jsonl"),
    )
    course_ops_guides_parser.add_argument(
        "--learning-chunks-path",
        type=Path,
        default=Path("data/course_pbs/manifests/ops_learning_chunks_v1.jsonl"),
    )

    return parser


def _build_answerer() -> ChatAnswerer:
    from play_book_studio.answering.answerer import ChatAnswerer

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
    from play_book_studio.app.server import serve

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
    from play_book_studio.retrieval.models import SessionContext

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
    from play_book_studio.evals.answer_eval import evaluate_case, summarize_case_results

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
    from play_book_studio.app.runtime_report import write_runtime_report

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
    from play_book_studio.app.runtime_maintenance_smoke import write_runtime_maintenance_smoke

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


def _run_private_lane_smoke(args: argparse.Namespace) -> int:
    from play_book_studio.app.private_lane_smoke import write_private_lane_smoke

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
    from play_book_studio.ingestion.graph_sidecar import write_graph_sidecar_compact_from_artifacts

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
    if args.command == "private-lane-smoke":
        return _run_private_lane_smoke(args)
    if args.command == "graph-compact":
        return _run_graph_compact(args)
    if args.command == "course-qa":
        from play_book_studio.course.quality_eval import run_quality_eval

        return run_quality_eval(args, default_root=ROOT)
    if args.command == "course-qdrant-upsert":
        from play_book_studio.course.qdrant_course import (
            COURSE_QDRANT_COLLECTION,
            COURSE_OPS_LEARNING_QDRANT_COLLECTION,
            load_course_chunks,
            load_ops_learning_chunks,
            upsert_course_chunks,
            upsert_ops_learning_chunks,
        )

        root_dir = args.root_dir.resolve()
        course_dir = (root_dir / args.course_dir).resolve() if not args.course_dir.is_absolute() else args.course_dir.resolve()
        settings = load_settings(root_dir)
        course_chunks = [] if args.skip_course else load_course_chunks(course_dir)
        ops_learning_chunks = [] if args.skip_ops_learning else load_ops_learning_chunks(course_dir)
        if int(args.limit or 0) > 0:
            limit = int(args.limit)
            course_chunks = course_chunks[:limit]
            ops_learning_chunks = ops_learning_chunks[:limit]
        course_upserted = 0 if args.skip_course else upsert_course_chunks(settings, course_chunks)
        ops_learning_upserted = (
            0 if args.skip_ops_learning else upsert_ops_learning_chunks(settings, ops_learning_chunks)
        )
        print(
            json.dumps(
                {
                    "course_dir": str(course_dir),
                    "course_collection": COURSE_QDRANT_COLLECTION,
                    "course_chunk_count": len(course_chunks),
                    "course_qdrant_upserted": course_upserted,
                    "ops_learning_collection": COURSE_OPS_LEARNING_QDRANT_COLLECTION,
                    "ops_learning_chunk_count": len(ops_learning_chunks),
                    "ops_learning_qdrant_upserted": ops_learning_upserted,
                    "qdrant_upserted": course_upserted + ops_learning_upserted,
                    "qdrant_url": settings.qdrant_url,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "course-visual-audit":
        from play_book_studio.course.visual_audit import capture_visual_audit, generate_visual_audit

        root_dir = args.root_dir.resolve()
        cases_path = (root_dir / args.cases_path).resolve() if not args.cases_path.is_absolute() else args.cases_path.resolve()
        output_dir = (root_dir / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
        report = generate_visual_audit(root_dir, cases_path=cases_path, output_dir=output_dir)
        console_report = {key: value for key, value in report.items() if key != "items"}
        if args.capture:
            capture_report = capture_visual_audit(
                output_dir=output_dir,
                host=args.host,
                port=args.port,
                session=args.session,
                playwright_cmd=args.playwright_cmd,
            )
            console_report["capture"] = {key: value for key, value in capture_report.items() if key not in {"results", "failed"}}
            console_report["capture_failed"] = capture_report.get("failed", [])
        print(json.dumps(console_report, ensure_ascii=False, indent=2))
        if report["failed"]:
            return 1
        if args.capture and console_report.get("capture", {}).get("failedCount"):
            return 1
        return 0
    if args.command == "course-ui-smoke":
        from play_book_studio.course.frontend_smoke import run_course_frontend_smoke

        root_dir = args.root_dir.resolve()
        cases_path = (root_dir / args.cases_path).resolve() if not args.cases_path.is_absolute() else args.cases_path.resolve()
        output_dir = (root_dir / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
        report = run_course_frontend_smoke(
            root_dir,
            cases_path=cases_path,
            output_dir=output_dir,
            scenario_count=max(1, int(args.scenario_count)),
            host=args.host,
            port=args.port,
            session=args.session,
            playwright_cmd=args.playwright_cmd,
        )
        console_report = {key: value for key, value in report.items() if key not in {"results", "failed"}}
        console_report["failed"] = report.get("failed", [])
        print(json.dumps(console_report, ensure_ascii=False, indent=2))
        return 0 if int(report.get("failedCount") or 0) == 0 else 1
    if args.command == "course-ops-anchor-audit":
        from play_book_studio.course.ops_learning import write_anchor_audit

        root_dir = args.root_dir.resolve()
        payload = write_anchor_audit(args.course_dir, args.output_path, root_dir=root_dir)
        output_path = (root_dir / args.output_path).resolve() if not args.output_path.is_absolute() else args.output_path.resolve()
        print(
            json.dumps(
                {
                    "output_path": str(output_path),
                    "source_chunk_count": payload["source_chunk_count"],
                    "source_route_stop_count": payload["source_route_stop_count"],
                    "summary": payload["summary"],
                    "stage_summaries": {
                        stage_id: {
                            "chunk_count": summary["chunk_count"],
                            "classification_counts": summary["classification_counts"],
                            "beginner_candidate_count": summary["beginner_candidate_count"],
                            "weak_route_starts": summary["weak_route_starts"],
                        }
                        for stage_id, summary in payload["stage_summaries"].items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "course-ops-guides":
        from play_book_studio.course.ops_learning import write_initial_guides_and_golden

        root_dir = args.root_dir.resolve()
        result = write_initial_guides_and_golden(
            args.course_dir,
            args.guides_path,
            args.golden_path,
            learning_chunks_path=args.learning_chunks_path,
            root_dir=root_dir,
        )
        guides_path = (root_dir / args.guides_path).resolve() if not args.guides_path.is_absolute() else args.guides_path.resolve()
        golden_path = (root_dir / args.golden_path).resolve() if not args.golden_path.is_absolute() else args.golden_path.resolve()
        learning_chunks_path = (root_dir / args.learning_chunks_path).resolve() if not args.learning_chunks_path.is_absolute() else args.learning_chunks_path.resolve()
        print(
            json.dumps(
                {
                    "guides_path": str(guides_path),
                    "golden_path": str(golden_path),
                    "learning_chunks_path": str(learning_chunks_path),
                    "report": result["report"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if int(result["report"].get("rejected_case_count") or 0) == 0 else 1
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
