from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from play_book_studio.config.settings import load_settings
from play_book_studio.evals.chunk_quality_audit import audit_chunks_file
from play_book_studio.evals.retrieval_eval import summarize_case_results
from play_book_studio.retrieval import ChatRetriever
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.payload import text_hash


DEFAULT_OFFICIAL_CHUNKS = Path("corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl")
DEFAULT_KMSC_CHUNKS = Path("corpus/sources/kmsc/parsed-preview/course_pbs/chunks.jsonl")
DEFAULT_RETRIEVAL_CASES = (
    Path("corpus/manifests/eval/retrieval_sanity_v004_readable_cases.jsonl"),
    Path("corpus/manifests/eval/retrieval_benchmark_cases.jsonl"),
    Path("corpus/manifests/eval/retrieval_foundation_p0_cases.jsonl"),
)


@dataclass(slots=True)
class GateResult:
    name: str
    status: str
    detail: str

    def passed(self) -> bool:
        return self.status == "pass"


def _run_git(root_dir: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root_dir, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "not_run", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "path": str(path), "error": str(exc)}
    return payload if isinstance(payload, dict) else {"status": "error", "path": str(path), "error": "json root is not object"}


def _db_rows(database_url: str, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


def db_quality_snapshot(database_url: str, model: str) -> dict[str, Any]:
    queries = {
        "source_stats": """
            SELECT source_scope,
                   count(*)::int AS chunks,
                   sum((length(btrim(COALESCE(embedding_text, ''))) = 0)::int)::int AS empty_embedding,
                   sum((token_count = 0)::int)::int AS zero_token_count,
                   percentile_disc(0.5) WITHIN GROUP (ORDER BY token_count)::int AS token_p50,
                   percentile_disc(0.9) WITHIN GROUP (ORDER BY token_count)::int AS token_p90,
                   percentile_disc(0.95) WITHIN GROUP (ORDER BY token_count)::int AS token_p95,
                   max(token_count)::int AS token_max,
                   sum((embedding_text LIKE '%%[CODE%%' OR embedding_text LIKE '%%[/CODE]%%' OR embedding_text LIKE '%%[TABLE%%' OR embedding_text LIKE '%%[/TABLE]%%')::int)::int AS raw_markup_embedding,
                   sum((embedding_text LIKE '%%```%%')::int)::int AS fenced_embedding,
                   sum((length(btrim(COALESCE(source_anchor, ''))) = 0)::int)::int AS missing_source_anchor
            FROM document_chunks
            GROUP BY source_scope
            ORDER BY source_scope
        """,
        "role_stats": """
            SELECT source_scope, chunk_role, count(*)::int AS chunks,
                   percentile_disc(0.5) WITHIN GROUP (ORDER BY token_count)::int AS token_p50,
                   percentile_disc(0.9) WITHIN GROUP (ORDER BY token_count)::int AS token_p90,
                   percentile_disc(0.95) WITHIN GROUP (ORDER BY token_count)::int AS token_p95,
                   max(token_count)::int AS token_max
            FROM document_chunks
            GROUP BY source_scope, chunk_role
            ORDER BY source_scope, chunk_role
        """,
        "official_empty_embedding": """
            SELECT id::text, chunk_type, heading_title, source_anchor, left(markdown, 240) AS markdown_preview
            FROM document_chunks
            WHERE source_scope = 'official_docs'
              AND length(btrim(COALESCE(embedding_text, ''))) = 0
            ORDER BY heading_title, source_anchor, id
        """,
        "kmsc_large_chunks": """
            SELECT id::text, chunk_role, chunk_type, token_count, heading_title, source_anchor,
                   left(embedding_text, 240) AS preview
            FROM document_chunks
            WHERE source_scope = 'study_docs'
              AND token_count > 800
            ORDER BY token_count DESC
            LIMIT 50
        """,
        "embedding_entries": """
            SELECT c.source_scope,
                   count(*) FILTER (WHERE length(btrim(COALESCE(c.embedding_text, ''))) > 0)::int AS indexable_chunks,
                   count(e.chunk_id)::int AS embedding_entries,
                   sum((length(btrim(COALESCE(c.embedding_text, ''))) > 0 AND e.chunk_id IS NULL)::int)::int AS missing_indexable,
                   count(DISTINCT e.model)::int AS vector_model_count,
                   min(e.model) AS vector_model_min,
                   max(e.model) AS vector_model_max,
                   min(vector_dims(e.embedding)) AS vector_dim_min,
                   max(vector_dims(e.embedding)) AS vector_dim_max
            FROM document_chunks c
            LEFT JOIN chunk_embeddings e
                ON e.chunk_id = c.id AND e.model = %s
            GROUP BY c.source_scope
            ORDER BY c.source_scope
        """,
    }
    snapshot: dict[str, Any] = {}
    for name, query in queries.items():
        params = (model,) if "%s" in query else ()
        try:
            snapshot[name] = _db_rows(database_url, query, params)
        except Exception as exc:  # noqa: BLE001
            snapshot[name] = {"error": str(exc)}
    return snapshot


def pgvector_index_snapshot(database_url: str, model: str, *, expected_vector_size: int = 1024, sample_size: int = 20) -> dict[str, Any]:
    index_rows = _db_rows(
        database_url,
        """
        SELECT
            c.id::text AS chunk_id,
            c.source_scope,
            c.embedding_text,
            e.model,
            e.embedding_text_hash,
            vector_dims(e.embedding) AS vector_size
        FROM document_chunks c
        LEFT JOIN chunk_embeddings e
          ON e.chunk_id = c.id AND e.model = %s
        WHERE length(btrim(COALESCE(c.embedding_text, ''))) > 0
        ORDER BY c.source_scope, c.id
        """,
        (model,),
    )
    missing: list[str] = []
    stale: list[str] = []
    model_mismatch: list[str] = []
    bad_dimension: list[dict[str, Any]] = []
    dimension_counts: dict[str, int] = {}
    source_counts: dict[str, dict[str, int]] = {}
    for row in index_rows:
        source_scope = str(row.get("source_scope") or "")
        source = source_counts.setdefault(source_scope, {"indexable": 0, "entries": 0, "missing": 0, "stale": 0})
        source["indexable"] += 1
        chunk_id = str(row.get("chunk_id") or "")
        if not row.get("embedding_text_hash"):
            source["missing"] += 1
            if len(missing) < sample_size:
                missing.append(chunk_id)
            continue
        source["entries"] += 1
        if row.get("model") != model:
            if len(model_mismatch) < sample_size:
                model_mismatch.append(chunk_id)
        expected_hash = text_hash(str(row.get("embedding_text") or ""))
        if row.get("embedding_text_hash") != expected_hash:
            source["stale"] += 1
            if len(stale) < sample_size:
                stale.append(chunk_id)
        vector_size = int(row.get("vector_size") or 0)
        dimension_counts[str(vector_size)] = dimension_counts.get(str(vector_size), 0) + 1
        if vector_size != expected_vector_size and len(bad_dimension) < sample_size:
            bad_dimension.append({"chunk_id": chunk_id, "vector_size": vector_size})
    return {
        "backend": "pgvector",
        "model": model,
        "expected_vector_size": expected_vector_size,
        "indexable_count": len(index_rows),
        "embedding_entry_count": sum(item["entries"] for item in source_counts.values()),
        "missing_count": sum(item["missing"] for item in source_counts.values()),
        "stale_count": sum(item["stale"] for item in source_counts.values()),
        "model_mismatch_count": len(model_mismatch),
        "dimension_bad_count": len(bad_dimension),
        "dimension_counts": dimension_counts,
        "source_counts": source_counts,
        "missing_samples": missing,
        "stale_samples": stale,
        "model_mismatch_samples": model_mismatch,
        "bad_dimension_samples": bad_dimension,
    }


def retrieval_eval_snapshot(settings: Any, root_dir: Path, case_files: list[Path], *, top_k: int, candidate_k: int) -> dict[str, Any]:
    retriever = ChatRetriever.from_settings(settings)
    reports: dict[str, Any] = {}
    for path in case_files:
        full_path = path if path.is_absolute() else root_dir / path
        if not full_path.exists():
            reports[str(path)] = {"error": "case file missing"}
            continue
        details: list[dict[str, Any]] = []
        for case in _read_jsonl(full_path):
            context = SessionContext.from_dict(case.get("context") or case.get("session_context"))
            result = retriever.retrieve(str(case.get("query", "")), context=context, top_k=top_k, candidate_k=candidate_k)
            top_hits = [
                {
                    "chunk_id": hit.chunk_id,
                    "book_slug": hit.book_slug,
                    "section": hit.section,
                    "viewer_path": hit.viewer_path,
                    "source_scope": hit.source_scope,
                    "score": hit.fused_score or hit.raw_score,
                }
                for hit in result.hits
            ]
            trace = result.trace or {}
            details.append(
                {
                    "id": case.get("id", ""),
                    "query_type": case.get("query_type", case.get("category", "unknown")),
                    "query": case.get("query", ""),
                    "expected_book_slugs": list(case.get("expected_book_slugs", [])),
                    "expected_source_scopes": list(case.get("expected_source_scopes", [])),
                    "top_book_slugs": [hit["book_slug"] for hit in top_hits],
                    "top_source_scopes": [hit["source_scope"] for hit in top_hits],
                    "top_hits": top_hits,
                    "warnings": list(trace.get("warnings", [])),
                    "bm25_top_book_slugs": _trace_book_slugs(trace, "bm25"),
                    "vector_top_book_slugs": _trace_book_slugs(trace, "vector"),
                    "hybrid_top_book_slugs": _trace_book_slugs(trace, "hybrid"),
                    "reranked_top_book_slugs": _trace_book_slugs(trace, "reranked"),
                }
            )
        book_scored_details = [item for item in details if item.get("expected_book_slugs")]
        summary = summarize_case_results(book_scored_details)
        reports[full_path.name] = {
            "summary": {key: summary[key] for key in ("case_count", "overall", "graph_signal_counts") if key in summary},
            "total_case_count": len(details),
            "source_scope_summary": _score_source_scope_results(details),
            "misses_at5": _misses_at_k(details, 5),
            "details": details,
        }
    return reports


def _score_source_scope_results(details: list[dict[str, Any]], ks: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    scoped = [item for item in details if item.get("expected_source_scopes")]
    if not scoped:
        return {"case_count": 0, "overall": {f"hit@{k}": 0.0 for k in ks}}
    scores: dict[str, float] = {}
    for k in ks:
        hits = 0
        for item in scoped:
            expected = {str(value) for value in item.get("expected_source_scopes", []) if str(value)}
            actual = [str(value) for value in item.get("top_source_scopes", [])[:k] if str(value)]
            if expected and any(value in expected for value in actual):
                hits += 1
        scores[f"hit@{k}"] = round(hits / len(scoped), 4)
    return {"case_count": len(scoped), "overall": scores}


def _trace_book_slugs(trace: dict[str, Any], key: str) -> list[str]:
    rows = trace.get(key) if isinstance(trace.get(key), list) else []
    return [str(item.get("book_slug") or "") for item in rows[:5] if isinstance(item, dict)]


def _misses_at_k(details: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    misses: list[dict[str, Any]] = []
    for item in details:
        expected_books = {str(value) for value in item.get("expected_book_slugs", []) if str(value)}
        expected_scopes = {str(value) for value in item.get("expected_source_scopes", []) if str(value)}
        book_hit = not expected_books or any(slug in expected_books for slug in item.get("top_book_slugs", [])[:k])
        scope_hit = not expected_scopes or any(scope in expected_scopes for scope in item.get("top_source_scopes", [])[:k])
        if not (book_hit and scope_hit):
            misses.append(
                {
                    "id": item.get("id", ""),
                    "query": item.get("query", ""),
                    "expected_book_slugs": item.get("expected_book_slugs", []),
                    "expected_source_scopes": item.get("expected_source_scopes", []),
                    "top_book_slugs": item.get("top_book_slugs", [])[:k],
                    "top_source_scopes": item.get("top_source_scopes", [])[:k],
                }
            )
    return misses


def build_gates(payload: dict[str, Any], settings: Any) -> list[GateResult]:
    db_stats = {row["source_scope"]: row for row in payload.get("db", {}).get("source_stats", []) if isinstance(row, dict)}
    role_stats = {
        (row["source_scope"], row["chunk_role"]): row
        for row in payload.get("db", {}).get("role_stats", [])
        if isinstance(row, dict)
    }
    pgvector_index = payload.get("pgvector_index", {}) if isinstance(payload.get("pgvector_index"), dict) else {}
    retrieval = payload.get("retrieval_eval", {})
    answer_viewer = payload.get("answer_viewer_check", {}) if isinstance(payload.get("answer_viewer_check"), dict) else {}
    gates = [
        GateResult(
            "official_docs_present",
            "pass" if db_stats.get("official_docs", {}).get("chunks") == 27907 else "fail",
            f"official_docs chunks={db_stats.get('official_docs', {}).get('chunks')}",
        ),
        GateResult(
            "study_docs_present",
            "pass" if int(db_stats.get("study_docs", {}).get("chunks") or 0) > 0 else "fail",
            f"study_docs chunks={db_stats.get('study_docs', {}).get('chunks')}",
        ),
        GateResult(
            "clean_embedding_text",
            "pass"
            if all(int(row.get("raw_markup_embedding") or 0) == 0 for row in db_stats.values())
            else "fail",
            "DB embedding_text raw [CODE]/[TABLE] count must be 0",
        ),
        GateResult(
            "kmsc_parent_size",
            "pass" if int(role_stats.get(("study_docs", "parent"), {}).get("token_max") or 0) <= 800 else "fail",
            f"study_docs parent token max={role_stats.get(('study_docs', 'parent'), {}).get('token_max')}",
        ),
        GateResult(
            "pgvector_embedding_count",
            "pass" if int(pgvector_index.get("missing_count") or 0) == 0 else "fail",
            f"indexable={pgvector_index.get('indexable_count')} embedding_entries={pgvector_index.get('embedding_entry_count')} missing={pgvector_index.get('missing_count')}",
        ),
        GateResult(
            "pgvector_stale_embeddings",
            "pass" if int(pgvector_index.get("stale_count") or 0) == 0 else "fail",
            f"stale={pgvector_index.get('stale_count')}",
        ),
        GateResult(
            "pgvector_embedding_model",
            "pass" if int(pgvector_index.get("model_mismatch_count") or 0) == 0 else "fail",
            f"expected model={settings.embedding_model} mismatches={pgvector_index.get('model_mismatch_count')}",
        ),
        GateResult(
            "pgvector_vector_size",
            "pass" if int(pgvector_index.get("dimension_bad_count") or 0) == 0 else "fail",
            f"expected=1024 dimensions={pgvector_index.get('dimension_counts')}",
        ),
        GateResult(
            "answer_viewer_check",
            "pass" if answer_viewer.get("status") == "pass" else "fail",
            f"status={answer_viewer.get('status')} checks={len(answer_viewer.get('checks') or [])}",
        ),
    ]
    for name, report in retrieval.items():
        if not isinstance(report, dict) or "summary" not in report:
            continue
        overall = ((report.get("summary") or {}).get("overall") or {}) if isinstance(report.get("summary"), dict) else {}
        gates.append(
            GateResult(
                f"retrieval_{name}_hit5",
                "pass" if float(overall.get("hit@5") or 0.0) >= 1.0 else "fail",
                f"hit@1={overall.get('hit@1')} hit@3={overall.get('hit@3')} hit@5={overall.get('hit@5')}",
            )
        )
        scope_summary = report.get("source_scope_summary") if isinstance(report.get("source_scope_summary"), dict) else {}
        scope_case_count = int(scope_summary.get("case_count") or 0)
        if scope_case_count:
            scope_overall = scope_summary.get("overall") if isinstance(scope_summary.get("overall"), dict) else {}
            gates.append(
                GateResult(
                    f"retrieval_{name}_scope_hit1",
                    "pass" if float(scope_overall.get("hit@1") or 0.0) >= 1.0 else "fail",
                    f"scope_cases={scope_case_count} hit@1={scope_overall.get('hit@1')} hit@3={scope_overall.get('hit@3')} hit@5={scope_overall.get('hit@5')}",
                )
            )
    return gates


def write_reports(output_dir: Path, payload: dict[str, Any], gates: list[GateResult]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "00-baseline.md").write_text(_baseline_md(payload), encoding="utf-8")
    (output_dir / "01-chunk-audit.md").write_text(_chunk_md(payload), encoding="utf-8")
    (output_dir / "02-embedding-index-audit.md").write_text(_embedding_md(payload), encoding="utf-8")
    (output_dir / "03-retrieval-eval.md").write_text(_retrieval_md(payload), encoding="utf-8")
    (output_dir / "04-answer-viewer-check.md").write_text(_answer_viewer_md(payload), encoding="utf-8")
    (output_dir / "05-go-no-go.md").write_text(_gate_md(gates), encoding="utf-8")


def _baseline_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Baseline",
        "",
        f"- Branch: `{payload['git']['branch']}`",
        f"- Head: `{payload['git']['head']}`",
        f"- Dirty files: `{payload['git']['dirty_count']}`",
        f"- Vector backend: `{payload.get('vector_backend', 'pgvector')}`",
        f"- Embedding model: `{payload.get('embedding_model', '')}`",
        "",
        "## DB Source Stats",
        "",
        "| scope | chunks | empty embedding | token p50 | token p90 | token max | raw marker |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    source_stats = payload.get("db", {}).get("source_stats", [])
    if isinstance(source_stats, dict) and source_stats.get("error"):
        lines.extend(["", f"- DB source_stats error: `{source_stats.get('error')}`"])
        return "\n".join(lines).strip() + "\n"
    for row in source_stats if isinstance(source_stats, list) else []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| `{row.get('source_scope')}` | {row.get('chunks')} | {row.get('empty_embedding')} | {row.get('token_p50')} | {row.get('token_p90')} | {row.get('token_max')} | {row.get('raw_markup_embedding')} |"
        )
    return "\n".join(lines).strip() + "\n"


def _chunk_md(payload: dict[str, Any]) -> str:
    lines = ["# Chunk Audit", ""]
    for key in ("official_source_audit", "kmsc_source_audit"):
        audit = payload.get(key, {})
        decision = audit.get("decision") or {}
        token = audit.get("token_count") or {}
        lines.extend(
            [
                f"## {key}",
                "",
                f"- Chunks: `{audit.get('chunk_count')}`",
                f"- Token p50/p90/p95/max: `{token.get('p50')}` / `{token.get('p90')}` / `{token.get('p95')}` / `{token.get('max')}`",
                f"- Decision: `{decision.get('recommendation')}`",
                "",
                "| issue | count | rate |",
                "|---|---:|---:|",
            ]
        )
        rates = audit.get("issue_rates") or {}
        for issue, count in (audit.get("issue_counts") or {}).items():
            lines.append(f"| `{issue}` | {count} | {rates.get(issue)} |")
        lines.append("")
    lines.extend(["## DB Large/Empty Samples", "", "```json", json.dumps(payload.get("db", {}).get("kmsc_large_chunks", []), ensure_ascii=False, indent=2)[:6000], "```"])
    return "\n".join(lines).strip() + "\n"


def _embedding_md(payload: dict[str, Any]) -> str:
    return (
        "# Embedding / pgvector Audit\n\n"
        "## pgvector Index\n\n"
        f"```json\n{json.dumps(payload.get('pgvector_index', {}), ensure_ascii=False, indent=2)[:12000]}\n```\n\n"
        "## DB Index Entries\n\n"
        f"```json\n{json.dumps(payload.get('db', {}).get('embedding_entries', []), ensure_ascii=False, indent=2)}\n```\n"
    )


def _retrieval_md(payload: dict[str, Any]) -> str:
    lines = ["# Retrieval Eval", ""]
    for name, report in (payload.get("retrieval_eval") or {}).items():
        summary_payload = {
            "book_summary": report.get("summary", report) if isinstance(report, dict) else report,
            "source_scope_summary": report.get("source_scope_summary", {}) if isinstance(report, dict) else {},
            "total_case_count": report.get("total_case_count") if isinstance(report, dict) else None,
        }
        lines.extend([f"## {name}", "", "```json", json.dumps(summary_payload, ensure_ascii=False, indent=2), "```", ""])
        misses = report.get("misses_at5") if isinstance(report, dict) else None
        if misses:
            lines.extend(["### Misses at 5", "", "```json", json.dumps(misses, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines).strip() + "\n"


def _answer_viewer_md(payload: dict[str, Any]) -> str:
    check_payload = payload.get("answer_viewer_check", {}) if isinstance(payload.get("answer_viewer_check"), dict) else {}
    lines = [
        "# Answer / Viewer Check",
        "",
        f"- Status: `{check_payload.get('status')}`",
        "",
        "| check | status | detail |",
        "|---|---|---|",
    ]
    for check in check_payload.get("checks") or []:
        if isinstance(check, dict):
            lines.append(f"| `{check.get('name')}` | `{check.get('status')}` | {check.get('detail')} |")
    if not check_payload.get("checks"):
        lines.append("| `answer_viewer_check` | `fail` | check file missing or not run |")
    return "\n".join(lines).strip() + "\n"


def _gate_md(gates: list[GateResult]) -> str:
    passed = sum(1 for gate in gates if gate.passed())
    lines = [
        "# Go / No-Go",
        "",
        f"- Passed: `{passed}` / `{len(gates)}`",
        f"- Decision: `{'go' if passed == len(gates) else 'no-go'}`",
        "",
        "| gate | status | detail |",
        "|---|---|---|",
    ]
    for gate in gates:
        lines.append(f"| `{gate.name}` | `{gate.status}` | {gate.detail} |")
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PBS RAG foundation audit.")
    parser.add_argument("--root-dir", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path(".kugnus-plan/rag-foundation"))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--case-file", action="append", type=Path, default=[])
    parser.add_argument("--answer-viewer-check-path", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=20)
    args = parser.parse_args(argv)

    root_dir = args.root_dir.resolve()
    settings = load_settings(root_dir)
    if args.database_url.strip():
        settings.database_url = args.database_url.strip()
    embedding_model = args.embedding_model.strip() or settings.embedding_model
    output_dir = args.output_dir if args.output_dir.is_absolute() else root_dir / args.output_dir
    answer_viewer_check_path = (
        args.answer_viewer_check_path
        if args.answer_viewer_check_path is not None
        else output_dir / "answer_viewer_check.json"
    )
    if not answer_viewer_check_path.is_absolute():
        answer_viewer_check_path = root_dir / answer_viewer_check_path
    official_chunks = root_dir / DEFAULT_OFFICIAL_CHUNKS
    kmsc_chunks = root_dir / DEFAULT_KMSC_CHUNKS
    case_files = args.case_file or list(DEFAULT_RETRIEVAL_CASES)
    dirty = _run_git(root_dir, "status", "--short").splitlines()
    payload: dict[str, Any] = {
        "vector_backend": "pgvector",
        "embedding_model": embedding_model,
        "git": {
            "branch": _run_git(root_dir, "branch", "--show-current"),
            "head": _run_git(root_dir, "rev-parse", "HEAD"),
            "last_commit": _run_git(root_dir, "log", "-1", "--oneline"),
            "dirty_count": len(dirty),
        },
        "official_source_audit": audit_chunks_file(official_chunks) if official_chunks.exists() else {"error": "missing"},
        "kmsc_source_audit": audit_chunks_file(kmsc_chunks) if kmsc_chunks.exists() else {"error": "missing"},
        "db": db_quality_snapshot(settings.database_url, embedding_model),
        "pgvector_index": pgvector_index_snapshot(settings.database_url, embedding_model, expected_vector_size=1024),
        "retrieval_eval": {},
        "answer_viewer_check": _read_json(answer_viewer_check_path),
    }
    if not args.skip_retrieval:
        payload["retrieval_eval"] = retrieval_eval_snapshot(
            settings,
            root_dir,
            case_files,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
        )
    gates = build_gates(payload, settings)
    payload["gates"] = [asdict(gate) for gate in gates]
    write_reports(output_dir, payload, gates)
    print(json.dumps({"decision": "go" if all(gate.passed() for gate in gates) else "no-go", "gates": payload["gates"]}, ensure_ascii=False, indent=2))
    return 0 if all(gate.passed() for gate in gates) else 2


if __name__ == "__main__":
    raise SystemExit(main())
