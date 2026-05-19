"""Run the command-level retrieval recall probe for the Phase 1 baseline."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import load_settings
from play_book_studio.evals.recall_probe import probe_case, summarize_probe_results
from play_book_studio.retrieval.retriever import ChatRetriever

DEFAULT_EVAL_SET = ROOT / "tests" / "eval" / "retrieval_eval_set.jsonl"


def _load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _format_rank(value: object) -> str:
    return "-" if value is None else str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run stage-1 retrieval recall probe.")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--candidate-k", type=int, default=40)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--local-bm25", action="store_true", help="Ignore .env DATABASE_URL and load local BM25 JSONL.")
    parser.add_argument("--no-vector", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    eval_set = args.eval_set if args.eval_set.is_absolute() else ROOT / args.eval_set
    settings = load_settings(ROOT)
    if args.local_bm25:
        settings = replace(settings, database_url="")
    if args.database_url is not None:
        settings = replace(settings, database_url=args.database_url.strip())
    retriever = ChatRetriever.from_settings(settings, enable_vector=not args.no_vector, enable_reranker=False)
    cases = _load_cases(eval_set)

    results = [
        probe_case(
            bm25_index=retriever.bm25_index,
            vector_retriever=retriever.vector_retriever,
            case=case,
            candidate_k=args.candidate_k,
        )
        for case in cases
    ]

    print(f"{'case':<28}{'BM25':>6}{'VEC':>6}{'RRF':>6}  @8")
    for row in results:
        flag = "PASS" if row["pass_at_8"] else "FAIL"
        print(
            f"{str(row['id']):<28}"
            f"{_format_rank(row['bm25_rank']):>6}"
            f"{_format_rank(row['vector_rank']):>6}"
            f"{_format_rank(row['rrf_rank']):>6}  {flag}"
        )
        if row.get("vector_error"):
            print(f"  vector_error: {row['vector_error']}")

    summary = summarize_probe_results(results)
    print(
        f"\nrecall@8={summary['recall_at_8']}  "
        f"recall@20={summary['recall_at_20']}  "
        f"MRR={summary['mrr']}"
    )
    print(f"fail: {summary['fail_ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
