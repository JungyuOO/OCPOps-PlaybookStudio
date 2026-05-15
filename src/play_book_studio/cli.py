"""제품 전체의 표준 실행 진입점.

어떤 명령이 존재하고, 각 명령이 어떤 런타임을 띄우는지 이해하려면
가장 먼저 이 파일을 보면 된다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from play_book_studio.console_encoding import force_utf8_stdio
from play_book_studio.config.corpus_paths import (
    ANSWER_EVAL_CASES_PATH,
    COURSE_OPS_LEARNING_GOLDEN_CASES_PATH,
    COURSE_PBS_DIR,
    COURSE_QA_ACCEPTED_CASES_PATH,
    COURSE_QA_CASES_PATH,
    COURSE_QA_REJECTED_CASES_PATH,
    COURSE_QA_REPORT_PATH,
    OFFICIAL_GOLD_CHUNKS_PATH,
    OPS_LEARNING_ANCHOR_AUDIT_PATH,
    OPS_LEARNING_CHUNKS_PATH,
    OPS_LEARNING_GUIDES_PATH,
    RAGAS_EVAL_CASES_PATH,
    RETRIEVAL_EVAL_CASES_PATH,
)
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
    ask_parser.add_argument("--database-url", default="")
    _add_runtime_args(ask_parser)

    eval_parser = subparsers.add_parser("eval", help="Run answer evaluation cases")
    eval_parser.add_argument(
        "--cases",
        type=Path,
        default=ANSWER_EVAL_CASES_PATH,
    )
    eval_parser.add_argument("--database-url", default="")
    _add_runtime_args(eval_parser)

    retrieval_eval_parser = subparsers.add_parser("retrieval-eval", help="Run retrieval evaluation cases")
    retrieval_eval_parser.add_argument(
        "--cases",
        type=Path,
        default=RETRIEVAL_EVAL_CASES_PATH,
    )
    retrieval_eval_parser.add_argument("--database-url", default="")
    retrieval_eval_parser.add_argument("--output", type=Path, default=None)
    _add_runtime_args(retrieval_eval_parser)

    ragas_parser = subparsers.add_parser("ragas", help="Run RAGAS evaluation")
    ragas_parser.add_argument(
        "--cases",
        type=Path,
        default=RAGAS_EVAL_CASES_PATH,
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

    db_migrate_parser = subparsers.add_parser(
        "db-migrate",
        help="Apply PostgreSQL migrations for ingestion runtime tables",
    )
    db_migrate_parser.add_argument("--root-dir", type=Path, default=ROOT)
    db_migrate_parser.add_argument("--database-url", default="")
    db_migrate_parser.add_argument("--migrations-dir", type=Path, default=Path("db/migrations"))
    db_migrate_parser.add_argument("--dry-run", action="store_true")

    upload_ingest_parser = subparsers.add_parser(
        "upload-ingest",
        help="Parse an uploaded document and persist its blocks/assets/chunks to PostgreSQL",
    )
    upload_ingest_parser.add_argument("--root-dir", type=Path, default=ROOT)
    upload_ingest_parser.add_argument("--path", type=Path, required=True)
    upload_ingest_parser.add_argument("--database-url", default="")
    upload_ingest_parser.add_argument("--tenant-slug", default="public")
    upload_ingest_parser.add_argument("--tenant-name", default="Public")
    upload_ingest_parser.add_argument("--workspace-slug", default="default")
    upload_ingest_parser.add_argument("--workspace-name", default="Default")
    upload_ingest_parser.add_argument("--created-by", default="")
    upload_ingest_parser.add_argument("--storage-key", default="")
    upload_ingest_parser.add_argument("--repository-id", default="")
    upload_ingest_parser.add_argument("--repository-slug", default="")
    upload_ingest_parser.add_argument("--repository-title", default="")
    upload_ingest_parser.add_argument("--repository-kind", default="")
    upload_ingest_parser.add_argument("--visibility", default="")
    upload_ingest_parser.add_argument("--source-scope", default="user_upload")
    upload_ingest_parser.add_argument("--chunk-max-chars", type=int, default=1800)
    upload_ingest_parser.add_argument("--chunk-overlap-blocks", type=int, default=1)
    upload_ingest_parser.add_argument("--dry-run", action="store_true")

    corpus_ingest_parser = subparsers.add_parser(
        "corpus-ingest",
        help="Parse a local official/study corpus folder into shared PostgreSQL document repositories",
    )
    corpus_ingest_parser.add_argument("--root-dir", type=Path, default=ROOT)
    corpus_ingest_parser.add_argument("--source-dir", type=Path, required=True)
    corpus_ingest_parser.add_argument("--corpus-kind", choices=("official_docs", "study_docs"), required=True)
    corpus_ingest_parser.add_argument("--database-url", default="")
    corpus_ingest_parser.add_argument("--tenant-slug", default="public")
    corpus_ingest_parser.add_argument("--tenant-name", default="Public")
    corpus_ingest_parser.add_argument("--workspace-slug", default="default")
    corpus_ingest_parser.add_argument("--workspace-name", default="Default")
    corpus_ingest_parser.add_argument("--chunk-max-chars", type=int, default=1800)
    corpus_ingest_parser.add_argument("--chunk-overlap-blocks", type=int, default=1)
    corpus_ingest_parser.add_argument("--index", action="store_true")
    corpus_ingest_parser.add_argument("--collection", default="")
    corpus_ingest_parser.add_argument("--dry-run", action="store_true")

    corpus_quality_audit_parser = subparsers.add_parser(
        "corpus-quality-audit",
        help="Audit tracked corpus JSONL chunks for RAG input quality signals",
    )
    corpus_quality_audit_parser.add_argument("--root-dir", type=Path, default=ROOT)
    corpus_quality_audit_parser.add_argument("--output", type=Path, default=None)
    corpus_quality_audit_parser.add_argument("--max-examples", type=int, default=5)
    corpus_quality_audit_parser.add_argument("--fail-on-mojibake-ratio", type=float, default=None)

    db_qdrant_index_parser = subparsers.add_parser(
        "db-qdrant-index",
        help="Embed pending PostgreSQL document chunks and upsert them to Qdrant",
    )
    db_qdrant_index_parser.add_argument("--root-dir", type=Path, default=ROOT)
    db_qdrant_index_parser.add_argument("--database-url", default="")
    db_qdrant_index_parser.add_argument("--collection", default="")
    db_qdrant_index_parser.add_argument("--source-scope", default="")
    db_qdrant_index_parser.add_argument("--limit", type=int, default=100)

    db_qdrant_backfill_parser = subparsers.add_parser(
        "db-qdrant-backfill",
        help="Record qdrant_index_entries for PostgreSQL chunks whose Qdrant points already exist",
    )
    db_qdrant_backfill_parser.add_argument("--root-dir", type=Path, default=ROOT)
    db_qdrant_backfill_parser.add_argument("--database-url", default="")
    db_qdrant_backfill_parser.add_argument("--collection", default="")
    db_qdrant_backfill_parser.add_argument("--limit", type=int, default=1000)
    db_qdrant_backfill_parser.add_argument("--batch-size", type=int, default=256)

    db_qdrant_refresh_parser = subparsers.add_parser(
        "db-qdrant-refresh-payloads",
        help="Refresh Qdrant payloads whose PostgreSQL-derived payload hash changed",
    )
    db_qdrant_refresh_parser.add_argument("--root-dir", type=Path, default=ROOT)
    db_qdrant_refresh_parser.add_argument("--database-url", default="")
    db_qdrant_refresh_parser.add_argument("--collection", default="")
    db_qdrant_refresh_parser.add_argument("--source-scope", default="")
    db_qdrant_refresh_parser.add_argument("--limit", type=int, default=1000)
    db_qdrant_refresh_parser.add_argument("--batch-size", type=int, default=256)

    metadata_spine_parser = subparsers.add_parser(
        "metadata-spine-backfill",
        help="Backfill deterministic answer-ready metadata onto existing document chunks",
    )
    metadata_spine_parser.add_argument("--root-dir", type=Path, default=ROOT)
    metadata_spine_parser.add_argument("--database-url", default="")
    metadata_spine_parser.add_argument("--source-scope", default="")
    metadata_spine_parser.add_argument("--limit", type=int, default=0)
    metadata_spine_parser.add_argument("--dry-run", action="store_true")
    metadata_spine_parser.add_argument("--force", action="store_true")

    db_corpus_status_parser = subparsers.add_parser(
        "db-corpus-status",
        help="Report PostgreSQL corpus and qdrant_index_entries readiness",
    )
    db_corpus_status_parser.add_argument("--root-dir", type=Path, default=ROOT)
    db_corpus_status_parser.add_argument("--database-url", default="")
    db_corpus_status_parser.add_argument("--collection", default="")

    course_runtime_status_parser = subparsers.add_parser(
        "course-runtime-status",
        help="Report PostgreSQL course runtime readiness for chunks, assets, and manifest",
    )
    course_runtime_status_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_runtime_status_parser.add_argument("--database-url", default="")
    course_runtime_status_parser.add_argument("--course-slug", default="project-playbook")

    official_gold_import_parser = subparsers.add_parser(
        "official-gold-import",
        help="Import existing official gold retrieval chunks into PostgreSQL document repositories",
    )
    official_gold_import_parser.add_argument("--root-dir", type=Path, default=ROOT)
    official_gold_import_parser.add_argument(
        "--chunks-path",
        type=Path,
        default=OFFICIAL_GOLD_CHUNKS_PATH,
    )
    official_gold_import_parser.add_argument("--database-url", default="")
    official_gold_import_parser.add_argument("--tenant-slug", default="public")
    official_gold_import_parser.add_argument("--tenant-name", default="Public")
    official_gold_import_parser.add_argument("--workspace-slug", default="default")
    official_gold_import_parser.add_argument("--workspace-name", default="Default")
    official_gold_import_parser.add_argument("--limit", type=int, default=0)
    official_gold_import_parser.add_argument("--index", action="store_true")
    official_gold_import_parser.add_argument("--index-limit", type=int, default=0)
    official_gold_import_parser.add_argument("--refresh-qdrant-payloads", action="store_true")
    official_gold_import_parser.add_argument("--collection", default="")
    official_gold_import_parser.add_argument("--refresh-limit", type=int, default=0)
    official_gold_import_parser.add_argument("--refresh-batch-size", type=int, default=256)
    official_gold_import_parser.add_argument("--enrich-runtime-metadata", action="store_true")
    official_gold_import_parser.add_argument("--bm25-path", type=Path, default=None)
    official_gold_import_parser.add_argument("--dry-run", action="store_true")

    learning_seed_parser = subparsers.add_parser(
        "learning-seed-import",
        help="Import guided learning path seed manifests into PostgreSQL",
    )
    learning_seed_parser.add_argument("--root-dir", type=Path, default=ROOT)
    learning_seed_parser.add_argument(
        "--guides-path",
        type=Path,
        default=OPS_LEARNING_GUIDES_PATH,
    )
    learning_seed_parser.add_argument("--database-url", default="")
    learning_seed_parser.add_argument("--tenant-slug", default="public")
    learning_seed_parser.add_argument("--tenant-name", default="Public")
    learning_seed_parser.add_argument("--workspace-slug", default="default")
    learning_seed_parser.add_argument("--workspace-name", default="Default")
    learning_seed_parser.add_argument("--dry-run", action="store_true")

    course_chunk_import_parser = subparsers.add_parser(
        "course-chunk-import",
        help="Import Study-docs course chunks into PostgreSQL for runtime course viewers",
    )
    course_chunk_import_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_chunk_import_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    course_chunk_import_parser.add_argument("--database-url", default="")
    course_chunk_import_parser.add_argument("--course-slug", default="project-playbook")
    course_chunk_import_parser.add_argument("--limit", type=int, default=0)
    course_chunk_import_parser.add_argument("--skip-assets", action="store_true")
    course_chunk_import_parser.add_argument("--skip-manifest", action="store_true")
    course_chunk_import_parser.add_argument("--dry-run", action="store_true")

    kmsc_course_import_parser = subparsers.add_parser(
        "kmsc-course-import",
        help="Import tracked KMSC course chunks into the shared study_docs document RAG",
    )
    kmsc_course_import_parser.add_argument("--root-dir", type=Path, default=ROOT)
    kmsc_course_import_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    kmsc_course_import_parser.add_argument("--database-url", default="")
    kmsc_course_import_parser.add_argument("--tenant-slug", default="public")
    kmsc_course_import_parser.add_argument("--tenant-name", default="Public")
    kmsc_course_import_parser.add_argument("--workspace-slug", default="default")
    kmsc_course_import_parser.add_argument("--workspace-name", default="Default")
    kmsc_course_import_parser.add_argument("--limit", type=int, default=0)
    kmsc_course_import_parser.add_argument("--index", action="store_true")
    kmsc_course_import_parser.add_argument("--collection", default="")
    kmsc_course_import_parser.add_argument("--dry-run", action="store_true")

    course_qa_parser = subparsers.add_parser(
        "course-qa",
        help="Generate, quality-gate, and run Study-docs course chat QA cases",
    )
    course_qa_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_qa_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    course_qa_parser.add_argument("--cases-path", type=Path, default=COURSE_QA_CASES_PATH)
    course_qa_parser.add_argument("--accepted-path", type=Path, default=COURSE_QA_ACCEPTED_CASES_PATH)
    course_qa_parser.add_argument("--rejected-path", type=Path, default=COURSE_QA_REJECTED_CASES_PATH)
    course_qa_parser.add_argument("--report-path", type=Path, default=COURSE_QA_REPORT_PATH)
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
    course_qdrant_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    course_qdrant_parser.add_argument("--limit", type=int, default=0)
    course_qdrant_parser.add_argument("--skip-course", action="store_true")
    course_qdrant_parser.add_argument("--skip-ops-learning", action="store_true")

    course_visual_audit_parser = subparsers.add_parser(
        "course-visual-audit",
        help="Generate Course QA browser audit pages and optionally capture them with Playwright",
    )
    course_visual_audit_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_visual_audit_parser.add_argument("--cases-path", type=Path, default=COURSE_QA_ACCEPTED_CASES_PATH)
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
    course_ui_smoke_parser.add_argument("--cases-path", type=Path, default=COURSE_QA_ACCEPTED_CASES_PATH)
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
    course_ops_anchor_audit_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    course_ops_anchor_audit_parser.add_argument(
        "--output-path",
        type=Path,
        default=OPS_LEARNING_ANCHOR_AUDIT_PATH,
    )

    course_ops_guides_parser = subparsers.add_parser(
        "course-ops-guides",
        help="Build initial Study-docs operational learning guides and beginner golden cases",
    )
    course_ops_guides_parser.add_argument("--root-dir", type=Path, default=ROOT)
    course_ops_guides_parser.add_argument("--course-dir", type=Path, default=COURSE_PBS_DIR)
    course_ops_guides_parser.add_argument(
        "--guides-path",
        type=Path,
        default=OPS_LEARNING_GUIDES_PATH,
    )
    course_ops_guides_parser.add_argument(
        "--golden-path",
        type=Path,
        default=COURSE_OPS_LEARNING_GOLDEN_CASES_PATH,
    )
    course_ops_guides_parser.add_argument(
        "--learning-chunks-path",
        type=Path,
        default=OPS_LEARNING_CHUNKS_PATH,
    )

    return parser


def _build_answerer(*, database_url: str = "") -> ChatAnswerer:
    from play_book_studio.answering.answerer import ChatAnswerer

    settings = load_settings(ROOT)
    if database_url.strip():
        from dataclasses import replace

        settings = replace(settings, database_url=database_url.strip())
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
    from play_book_studio.http.server import serve

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

    answerer = _build_answerer(database_url=args.database_url)
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

    answerer = _build_answerer(database_url=args.database_url)
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


def _retrieval_trace_book_slugs(trace: dict, key: str) -> list[str]:
    return [
        str(item.get("book_slug", ""))
        for item in trace.get(key, [])
        if str(item.get("book_slug", "")).strip()
    ]


def _run_retrieval_eval(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from play_book_studio.evals.retrieval_eval import summarize_case_results
    from play_book_studio.retrieval import ChatRetriever
    from play_book_studio.retrieval.models import SessionContext

    settings = load_settings(ROOT)
    if args.database_url.strip():
        settings = replace(settings, database_url=args.database_url.strip())
    retriever = ChatRetriever.from_settings(settings)
    cases = _read_jsonl(args.cases)
    details: list[dict] = []
    for case in cases:
        context = SessionContext.from_dict(case.get("context") or case.get("session_context"))
        result = retriever.retrieve(
            str(case.get("query", "")),
            context=context,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
        )
        top_hits = [
            {
                "chunk_id": hit.chunk_id,
                "book_slug": hit.book_slug,
                "section": hit.section,
                "anchor": hit.anchor,
                "viewer_path": hit.viewer_path,
                "score": hit.fused_score or hit.raw_score,
            }
            for hit in result.hits
        ]
        trace = result.trace or {}
        details.append(
            {
                "id": case.get("id", ""),
                "mode": case.get("mode", "retrieval"),
                "query_type": case.get("query_type", case.get("category", "unknown")),
                "query": case.get("query", ""),
                "rewritten_query": result.rewritten_query,
                "expected_book_slugs": list(case.get("expected_book_slugs", [])),
                "expected_landing_terms": list(case.get("expected_landing_terms", [])),
                "top_book_slugs": [hit["book_slug"] for hit in top_hits],
                "top_hits": top_hits,
                "warnings": list(trace.get("warnings", [])),
                "bm25_top_book_slugs": _retrieval_trace_book_slugs(trace, "bm25"),
                "vector_top_book_slugs": _retrieval_trace_book_slugs(trace, "vector"),
                "hybrid_top_book_slugs": _retrieval_trace_book_slugs(trace, "hybrid"),
                "reranked_top_book_slugs": _retrieval_trace_book_slugs(trace, "reranked"),
                "rewrite_applied": bool(trace.get("plan", {}).get("rewrite_applied", False)),
                "rewrite_reason": str(trace.get("plan", {}).get("rewrite_reason", "")),
                "follow_up_detected": bool(trace.get("plan", {}).get("follow_up_detected", False)),
                "vector_endpoint_used": str(trace.get("vector_runtime", {}).get("endpoint_used", "")),
                "hybrid_top_support": str(trace.get("ablation", {}).get("hybrid_top_support", "")),
                "rerank_top1_changed": bool(trace.get("reranker", {}).get("top1_changed", False)),
                "rerank_reasons": list(trace.get("reranker", {}).get("reasons", [])),
            }
        )

    report = {
        "cases_file": str(args.cases),
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        **summarize_case_results(details),
        "details": details,
    }
    output_path = args.output or settings.retrieval_eval_report_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote retrieval eval report: {output_path}")
    print(json.dumps({key: report[key] for key in ("case_count", "overall", "graph_signal_counts")}, ensure_ascii=False, indent=2))
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
    from play_book_studio.http.runtime_report import write_runtime_report

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
    from play_book_studio.http.runtime_maintenance_smoke import write_runtime_maintenance_smoke

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
    from play_book_studio.http.private_lane_smoke import write_private_lane_smoke

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


def _run_db_migrate(args: argparse.Namespace) -> int:
    from play_book_studio.db.migrations import apply_migrations, list_migrations

    root_dir = args.root_dir.resolve()
    migrations_dir = args.migrations_dir
    if not migrations_dir.is_absolute():
        migrations_dir = root_dir / migrations_dir
    migrations_dir = migrations_dir.resolve()

    if args.dry_run:
        migrations = list_migrations(migrations_dir)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "migrations_dir": str(migrations_dir),
                    "migration_count": len(migrations),
                    "migrations": [
                        {
                            "version": migration.version,
                            "checksum": migration.checksum,
                            "path": str(migration.path),
                        }
                        for migration in migrations
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    result = apply_migrations(database_url, migrations_dir)
    print(
        json.dumps(
            {
                "dry_run": False,
                "migrations_dir": str(migrations_dir),
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _upload_ingest_summary(parsed, chunks, *, persisted=None) -> dict:
    from play_book_studio.wiki_gold_builder import prepare_upload_gold_build_candidate

    gold_candidate = prepare_upload_gold_build_candidate(
        parsed,
        tuple(chunks),
        source_scope=getattr(parsed, "source_scope", "user_upload"),
        dry_run=persisted is None,
    )
    return {
        "filename": parsed.filename,
        "document_format": parsed.document_format,
        "mime_type": parsed.mime_type,
        "sha256": parsed.sha256,
        "status": parsed.status,
        "warning_count": len(parsed.warnings),
        "warnings": list(parsed.warnings),
        "block_count": len(parsed.blocks),
        "asset_count": len(parsed.assets),
        "chunk_count": len(chunks),
        "sections": [
            list(chunk.section_path)
            for chunk in chunks
            if chunk.section_path
        ],
        "gold_build_run": gold_candidate.run,
        "persisted": None if persisted is None else {
            "document_source_id": persisted.document_source_id,
            "document_version_id": persisted.document_version_id,
            "parse_job_id": persisted.parse_job_id,
            "parsed_document_id": persisted.parsed_document_id,
            "repository_id": persisted.repository_id,
            "block_count": len(persisted.block_ids),
            "asset_count": len(persisted.asset_ids),
            "chunk_count": len(persisted.chunk_ids),
        },
    }


def _run_upload_ingest(args: argparse.Namespace) -> int:
    from play_book_studio.db.document_repository import persist_parsed_upload_document
    from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document
    from play_book_studio.ingestion.vision import build_qwen_image_describer

    root_dir = args.root_dir.resolve()
    source_path = args.path
    if not source_path.is_absolute():
        source_path = root_dir / source_path
    source_path = source_path.resolve()
    if not source_path.exists():
        print(f"upload source does not exist: {source_path}")
        return 1

    settings = load_settings(root_dir)
    parsed = parse_upload_document(source_path, image_describer=build_qwen_image_describer(settings))
    chunks = build_document_chunks(
        parsed,
        max_chars=args.chunk_max_chars,
        overlap_blocks=args.chunk_overlap_blocks,
    )
    if args.dry_run:
        print(json.dumps(_upload_ingest_summary(parsed, chunks), ensure_ascii=False, indent=2))
        return 0

    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        persisted = persist_parsed_upload_document(
            connection,
            parsed,
            chunks,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
            storage_key=args.storage_key,
            created_by=args.created_by,
            repository_id=args.repository_id,
            repository_slug=args.repository_slug,
            repository_title=args.repository_title,
            repository_kind=args.repository_kind,
            visibility=args.visibility,
            source_scope=args.source_scope,
        )
    print(json.dumps(_upload_ingest_summary(parsed, chunks, persisted=persisted), ensure_ascii=False, indent=2))
    return 0


def _run_corpus_ingest(args: argparse.Namespace) -> int:
    from play_book_studio.ingestion.corpus_import import build_corpus_import_plan, import_corpus_documents

    root_dir = args.root_dir.resolve()
    source_dir = args.source_dir
    if not source_dir.is_absolute():
        source_dir = root_dir / source_dir
    source_dir = source_dir.resolve()
    if args.dry_run:
        print(json.dumps(build_corpus_import_plan(source_dir, corpus_kind=args.corpus_kind), ensure_ascii=False, indent=2))
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = import_corpus_documents(
            connection,
            source_dir=source_dir,
            corpus_kind=args.corpus_kind,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
            chunk_max_chars=args.chunk_max_chars,
            chunk_overlap_blocks=args.chunk_overlap_blocks,
            index=bool(args.index),
            settings=settings,
            collection=args.collection,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if int(result.get("failed_count") or 0) == 0 else 1


def _run_db_qdrant_index(args: argparse.Namespace) -> int:
    from play_book_studio.db.qdrant_indexer import index_pending_document_chunks

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = index_pending_document_chunks(
            settings,
            connection,
            collection=args.collection.strip() or None,
            source_scope=args.source_scope,
            limit=args.limit,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_db_qdrant_backfill(args: argparse.Namespace) -> int:
    from play_book_studio.db.qdrant_indexer import backfill_existing_qdrant_index_entries

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = backfill_existing_qdrant_index_entries(
            settings,
            connection,
            collection=args.collection.strip() or None,
            limit=args.limit,
            batch_size=args.batch_size,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_db_qdrant_refresh_payloads(args: argparse.Namespace) -> int:
    from play_book_studio.db.qdrant_indexer import refresh_stale_qdrant_payloads

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = refresh_stale_qdrant_payloads(
            settings,
            connection,
            collection=args.collection.strip() or None,
            source_scope=args.source_scope,
            limit=args.limit,
            batch_size=args.batch_size,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_metadata_spine_backfill(args: argparse.Namespace) -> int:
    from play_book_studio.db.metadata_spine_backfill import backfill_metadata_spine

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = backfill_metadata_spine(
            connection,
            source_scope=args.source_scope,
            limit=args.limit,
            dry_run=bool(args.dry_run),
            force=bool(args.force),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_db_corpus_status(args: argparse.Namespace) -> int:
    from play_book_studio.db.corpus_status import build_corpus_status

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    payload = build_corpus_status(
        database_url=database_url,
        collection=args.collection.strip() or settings.qdrant_collection,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ready")) else 1


def _run_course_runtime_status(args: argparse.Namespace) -> int:
    from play_book_studio.db.course_runtime_status import build_course_runtime_status

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    payload = build_course_runtime_status(
        database_url=database_url,
        course_slug=args.course_slug,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ready")) else 1


def _run_official_gold_import(args: argparse.Namespace) -> int:
    from play_book_studio.ingestion.official_gold_import import (
        build_official_gold_import_plan,
        import_official_gold_chunks,
    )

    root_dir = args.root_dir.resolve()
    chunks_path = args.chunks_path
    if not chunks_path.is_absolute():
        chunks_path = root_dir / chunks_path
    chunks_path = chunks_path.resolve()
    bm25_path = args.bm25_path
    if bm25_path is not None and not bm25_path.is_absolute():
        bm25_path = root_dir / bm25_path
    if bm25_path is not None:
        bm25_path = bm25_path.resolve()
    elif args.enrich_runtime_metadata:
        bm25_path = load_settings(root_dir).bm25_corpus_path.resolve()
    enrich_report = None
    if args.enrich_runtime_metadata:
        from play_book_studio.ingestion.official_gold_enrichment import enrich_official_gold_chunks

        enrich_report = enrich_official_gold_chunks(
            chunks_path,
            bm25_path=bm25_path,
            dry_run=bool(args.dry_run),
        )
    if args.dry_run:
        payload = build_official_gold_import_plan(chunks_path, limit=args.limit)
        if enrich_report is not None:
            payload["official_gold_enrichment"] = enrich_report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        result = import_official_gold_chunks(
            connection,
            chunks_path=chunks_path,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
            limit=args.limit,
        )
        payload = result.to_dict()
        if enrich_report is not None:
            payload["official_gold_enrichment"] = enrich_report
        if args.index:
            from play_book_studio.db.qdrant_indexer import index_pending_document_chunks

            index_limit = args.index_limit or max(result.imported_chunk_count, 1000)
            payload["qdrant_index"] = index_pending_document_chunks(
                settings,
                connection,
                collection=args.collection.strip() or None,
                source_scope="official_docs",
                limit=index_limit,
            )
        if args.refresh_qdrant_payloads:
            from play_book_studio.db.qdrant_indexer import refresh_stale_qdrant_payloads

            refresh_limit = args.refresh_limit or max(result.imported_chunk_count, 1000)
            payload["qdrant_refresh"] = refresh_stale_qdrant_payloads(
                settings,
                connection,
                collection=args.collection.strip() or None,
                source_scope="official_docs",
                limit=refresh_limit,
                batch_size=args.refresh_batch_size,
            )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _learning_seed_summary(seed, *, persisted=None) -> dict:
    step_count = len(seed.steps)
    lab_task_count = sum(len(step.lab_tasks) for step in seed.steps)
    command_check_count = sum(len(task.command_checks) for step in seed.steps for task in step.lab_tasks)
    return {
        "slug": seed.slug,
        "title": seed.title,
        "audience": seed.audience,
        "ocp_version": seed.ocp_version,
        "language": seed.language,
        "source_kind": seed.source_kind,
        "source_ref": seed.source_ref,
        "step_count": step_count,
        "lab_task_count": lab_task_count,
        "command_check_count": command_check_count,
        "persisted": None if persisted is None else {
            "learning_path_id": persisted.learning_path_id,
            "step_count": len(persisted.step_ids),
            "lab_task_count": len(persisted.lab_task_ids),
            "command_check_count": len(persisted.command_check_ids),
        },
    }


def _run_learning_seed_import(args: argparse.Namespace) -> int:
    from play_book_studio.course.learning_path_seed import load_ops_learning_guides_seed
    from play_book_studio.db.learning_repository import persist_learning_path

    root_dir = args.root_dir.resolve()
    guides_path = args.guides_path
    if not guides_path.is_absolute():
        guides_path = root_dir / guides_path
    guides_path = guides_path.resolve()
    if not guides_path.exists():
        print(f"learning guides seed does not exist: {guides_path}")
        return 1

    seed = load_ops_learning_guides_seed(guides_path)
    if args.dry_run:
        print(json.dumps(_learning_seed_summary(seed), ensure_ascii=False, indent=2))
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        persisted = persist_learning_path(
            connection,
            seed,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
        )
    print(json.dumps(_learning_seed_summary(seed, persisted=persisted), ensure_ascii=False, indent=2))
    return 0


def _run_course_chunk_import(args: argparse.Namespace) -> int:
    from play_book_studio.course.qdrant_course import load_course_chunks
    from play_book_studio.db.course_repository import (
        build_course_asset_record,
        import_course_manifest,
        import_course_assets,
        import_course_chunks,
    )

    root_dir = args.root_dir.resolve()
    course_dir = args.course_dir
    if not course_dir.is_absolute():
        course_dir = root_dir / course_dir
    course_dir = course_dir.resolve()
    chunks = load_course_chunks(course_dir)
    limit = max(0, int(args.limit or 0))
    if limit:
        chunks = chunks[:limit]
    source_ref = str(course_dir.relative_to(root_dir)) if course_dir.is_relative_to(root_dir) else str(course_dir)
    manifest_path = course_dir / "manifests" / "course_v1.json"
    manifest_payload: dict | None = None
    manifest_source_ref = ""
    if not args.skip_manifest and manifest_path.exists():
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_source_ref = str(manifest_path.relative_to(root_dir)) if manifest_path.is_relative_to(root_dir) else str(manifest_path)
    asset_records = []
    missing_assets: list[str] = []
    seen_asset_paths: set[str] = set()
    if not args.skip_assets:
        for chunk in chunks:
            attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                asset_path = str(attachment.get("asset_path") or "").strip().replace("\\", "/")
                if not asset_path or asset_path in seen_asset_paths:
                    continue
                seen_asset_paths.add(asset_path)
                resolved = _resolve_course_asset_file(root_dir, course_dir, asset_path)
                if resolved is None:
                    missing_assets.append(asset_path)
                    continue
                asset_records.append(
                    build_course_asset_record(
                        asset_key=asset_path,
                        asset_path=asset_path,
                        content=resolved.read_bytes(),
                        payload={
                            "asset_id": str(attachment.get("asset_id") or ""),
                            "attachment_id": str(attachment.get("attachment_id") or ""),
                            "chunk_id": str(chunk.get("chunk_id") or ""),
                            "slide_no": int(attachment.get("slide_no") or 0),
                            "visual_summary": str(attachment.get("visual_summary") or ""),
                            "ocr_text": str(attachment.get("ocr_text") or ""),
                            "instructional_role": str(attachment.get("instructional_role") or ""),
                        },
                        course_slug=args.course_slug,
                        source_ref=source_ref,
                    )
                )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "course_slug": args.course_slug,
                    "source_ref": source_ref,
                    "chunk_count": len(chunks),
                    "asset_count": len(asset_records),
                    "missing_asset_count": len(missing_assets),
                    "missing_assets": missing_assets[:10],
                    "manifest_loaded": manifest_payload is not None,
                    "manifest_stage_count": len(manifest_payload.get("stages") or []) if isinstance(manifest_payload, dict) else 0,
                    "first_chunk_id": str(chunks[0].get("chunk_id") or "") if chunks else "",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        chunk_result = import_course_chunks(
            connection,
            chunks,
            course_slug=args.course_slug,
            source_ref=source_ref,
        )
        asset_result = (
            {
                "course_slug": args.course_slug,
                "source_ref": source_ref,
                "scanned_count": 0,
                "imported_count": 0,
                "skipped_count": 0,
            }
            if args.skip_assets
            else import_course_assets(
                connection,
                asset_records,
                course_slug=args.course_slug,
                source_ref=source_ref,
            )
        )
        manifest_result = (
            {
                "course_slug": args.course_slug,
                "manifest_key": "course_v1",
                "stage_count": 0,
                "stop_count": 0,
                "source_ref": "",
            }
            if manifest_payload is None
            else import_course_manifest(
                connection,
                manifest_payload,
                course_slug=args.course_slug,
                manifest_key="course_v1",
                source_ref=manifest_source_ref,
            )
        )
    result = {
        "course_slug": args.course_slug,
        "source_ref": source_ref,
        "chunks": chunk_result,
        "assets": asset_result,
        "manifest": manifest_result,
        "missing_asset_count": len(missing_assets),
        "missing_assets": missing_assets[:10],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing_assets else 1


def _resolve_course_asset_file(root_dir: Path, course_dir: Path, asset_path: str) -> Path | None:
    normalized = str(asset_path or "").strip().replace("\\", "/")
    if not normalized:
        return None

    candidate = Path(normalized)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(root_dir / candidate)
        parts = candidate.parts
        if parts and parts[0] == "assets":
            candidates.append(course_dir / candidate)
        if len(parts) >= 4 and parts[0] == "data" and parts[2] == "assets":
            candidates.append(course_dir / "assets" / Path(*parts[3:]))

    for path in candidates:
        resolved = path.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _run_kmsc_course_import(args: argparse.Namespace) -> int:
    from play_book_studio.db.qdrant_indexer import index_pending_document_chunks
    from play_book_studio.ingestion.kmsc_course_import import (
        build_kmsc_course_import_plan,
        import_kmsc_course_chunks,
    )

    root_dir = args.root_dir.resolve()
    course_dir = args.course_dir
    if not course_dir.is_absolute():
        course_dir = root_dir / course_dir
    course_dir = course_dir.resolve()
    limit = max(0, int(args.limit or 0))
    if args.dry_run:
        print(json.dumps(build_kmsc_course_import_plan(course_dir, limit=limit), ensure_ascii=False, indent=2))
        return 0

    settings = load_settings(root_dir)
    database_url = (args.database_url or settings.database_url).strip()
    if not database_url:
        print("DATABASE_URL is required. Set it in .env or pass --database-url.")
        return 1

    import psycopg

    with psycopg.connect(database_url) as connection:
        summary = import_kmsc_course_chunks(
            connection,
            course_dir=course_dir,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
            limit=limit,
        ).to_dict()
        if args.index:
            summary["qdrant_index"] = index_pending_document_chunks(
                settings,
                connection,
                collection=args.collection.strip() or None,
                source_scope="study_docs",
                limit=max(100, int(summary.get("imported_chunk_count") or 0)),
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    force_utf8_stdio()
    args = build_parser().parse_args()
    if args.command == "ui":
        return _run_ui(args)
    if args.command == "ask":
        return _run_ask(args)
    if args.command == "eval":
        return _run_eval(args)
    if args.command == "retrieval-eval":
        return _run_retrieval_eval(args)
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
    if args.command == "db-migrate":
        return _run_db_migrate(args)
    if args.command == "upload-ingest":
        return _run_upload_ingest(args)
    if args.command == "corpus-ingest":
        return _run_corpus_ingest(args)
    if args.command == "corpus-quality-audit":
        from play_book_studio.ingestion.corpus_quality_audit import audit_runtime_corpus

        root_dir = args.root_dir.resolve()
        report = audit_runtime_corpus(root_dir, max_examples=max(0, int(args.max_examples or 0)))
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            output_path = (root_dir / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output + "\n", encoding="utf-8")
        print(output)
        threshold = args.fail_on_mojibake_ratio
        if threshold is not None:
            for target in report["targets"]:
                ratio = float(target.get("mojibake", {}).get("suspect_ratio") or 0.0)
                if ratio > float(threshold):
                    return 1
        return 0
    if args.command == "db-qdrant-index":
        return _run_db_qdrant_index(args)
    if args.command == "db-qdrant-backfill":
        return _run_db_qdrant_backfill(args)
    if args.command == "db-qdrant-refresh-payloads":
        return _run_db_qdrant_refresh_payloads(args)
    if args.command == "metadata-spine-backfill":
        return _run_metadata_spine_backfill(args)
    if args.command == "db-corpus-status":
        return _run_db_corpus_status(args)
    if args.command == "course-runtime-status":
        return _run_course_runtime_status(args)
    if args.command == "official-gold-import":
        return _run_official_gold_import(args)
    if args.command == "learning-seed-import":
        return _run_learning_seed_import(args)
    if args.command == "course-chunk-import":
        return _run_course_chunk_import(args)
    if args.command == "kmsc-course-import":
        return _run_kmsc_course_import(args)
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
