from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.contextual_enrichment import (
    CONTEXTUAL_ENRICHMENT_VERSION,
    contextual_search_text,
    enrich_contextual_row,
    has_contextual_enrichment,
)
from play_book_studio.retrieval.bm25 import BM25Index, tokenize_text


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


def _iter_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _customer_bm25_paths(root_dir: Path) -> list[Path]:
    corpus_dir = root_dir / "artifacts" / "customer_packs" / "corpus"
    if not corpus_dir.exists():
        return []
    return sorted(corpus_dir.glob("*/bm25_corpus.jsonl"), key=lambda path: path.as_posix())


def _baseline_bm25_top(rows: list[dict[str, Any]], query: str) -> str:
    query_terms = set(tokenize_text(query))
    if not query_terms:
        return ""
    scored: list[tuple[float, str]] = []
    for row in rows:
        terms = Counter(tokenize_text(str(row.get("text") or "")))
        score = sum(float(terms.get(term, 0)) for term in query_terms)
        if score > 0:
            scored.append((score, str(row.get("chunk_id") or "")))
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def _contextual_recall_fixture() -> dict[str, Any]:
    rows = [
        {
            "chunk_id": "ambiguous-registry",
            "book_slug": "registry",
            "book_title": "Registry",
            "chapter": "Registry options",
            "section": "Mirror settings",
            "section_path": ["Registry options", "Mirror settings"],
            "text": "Mirror registry settings are configured before cluster installation.",
        },
        {
            "chunk_id": "disconnected-install",
            "book_slug": "installing_on_any_platform",
            "book_title": "Installing on any platform",
            "chapter": "Disconnected installation",
            "section": "Mirroring images for disconnected clusters",
            "section_path": ["Disconnected installation", "Mirroring images for disconnected clusters"],
            "text": "Prepare release images and registry credentials before installation.",
        },
    ]
    query = "disconnected cluster image mirroring"
    baseline_top = _baseline_bm25_top(rows, query)
    enriched_index = BM25Index.from_rows(rows)
    enriched_hits = enriched_index.search(query, top_k=2)
    enriched_top = enriched_hits[0].chunk_id if enriched_hits else ""
    return {
        "query": query,
        "expected_top": "disconnected-install",
        "baseline_top": baseline_top,
        "enriched_top": enriched_top,
        "improved": baseline_top != "disconnected-install" and enriched_top == "disconnected-install",
        "enriched_hit_count": len(enriched_hits),
    }


def _coverage_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    runtime_rows = [enrich_contextual_row(row) for row in rows]
    persisted_count = sum(1 for row in rows if has_contextual_enrichment(row))
    runtime_count = sum(1 for row in runtime_rows if has_contextual_enrichment(row))
    heading_count = sum(1 for row in runtime_rows if row.get("contextual_heading_path"))
    prefix_count = sum(1 for row in runtime_rows if str(row.get("contextual_prefix") or "").strip())
    search_text_changed_count = sum(
        1
        for original, enriched in zip(rows, runtime_rows, strict=True)
        if contextual_search_text(enriched) != str(original.get("text") or "")
    )
    source_collections = Counter(str(row.get("source_collection") or "unknown") for row in runtime_rows)
    source_lanes = Counter(str(row.get("source_lane") or "unknown") for row in runtime_rows)
    return {
        "row_count": len(rows),
        "persisted_contextual_count": persisted_count,
        "runtime_contextual_count": runtime_count,
        "contextual_heading_path_count": heading_count,
        "contextual_prefix_count": prefix_count,
        "contextual_search_text_changed_count": search_text_changed_count,
        "source_collections": dict(source_collections),
        "source_lanes": dict(source_lanes),
        "examples": [
            {
                "chunk_id": str(row.get("chunk_id") or ""),
                "contextual_parent_title": str(row.get("contextual_parent_title") or ""),
                "contextual_heading_path": row.get("contextual_heading_path") or [],
                "contextual_prefix": str(row.get("contextual_prefix") or "")[:360],
            }
            for row in runtime_rows[:3]
        ],
    }


def build_llmwiki_contextual_enrichment_gate(
    root_dir: str | Path,
    *,
    official_bm25_path: str | Path | None = None,
    customer_bm25_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    official_path = Path(official_bm25_path) if official_bm25_path is not None else settings.retrieval_bm25_corpus_path
    customer_paths = (
        [Path(path) for path in customer_bm25_paths]
        if customer_bm25_paths is not None
        else _customer_bm25_paths(root)
    )
    official_rows = _iter_jsonl_rows(official_path)
    customer_rows: list[dict[str, Any]] = []
    existing_customer_paths: list[Path] = []
    for path in customer_paths:
        rows = _iter_jsonl_rows(path)
        if rows:
            existing_customer_paths.append(path)
            customer_rows.extend(rows)
    all_rows = [*official_rows, *customer_rows]
    official_coverage = _coverage_for_rows(official_rows)
    customer_coverage = _coverage_for_rows(customer_rows)
    total_coverage = _coverage_for_rows(all_rows)
    recall_fixture = _contextual_recall_fixture()
    sampled_index = BM25Index.from_rows(all_rows[: min(len(all_rows), 5000)]) if all_rows else None
    checks = {
        "official_corpus_loaded": bool(official_rows),
        "customer_corpus_loaded": bool(customer_rows),
        "runtime_contextual_prefix_ready": total_coverage["runtime_contextual_count"] == total_coverage["row_count"]
        and total_coverage["row_count"] > 0,
        "runtime_contextual_heading_path_ready": total_coverage["contextual_heading_path_count"] == total_coverage["row_count"]
        and total_coverage["row_count"] > 0,
        "bm25_runtime_uses_contextual_search_text": bool(
            sampled_index
            and sampled_index.contextual_index_enabled
            and sampled_index.contextual_enriched_count == min(len(all_rows), 5000)
        ),
        "contextual_recall_fixture_improves": bool(recall_fixture.get("improved")),
        "contextual_search_text_materialized": total_coverage["contextual_search_text_changed_count"] > 0,
    }
    ready = all(checks.values())
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "generated_at": _iso_timestamp(),
        "git": _git_refs(root),
        "goal": "p1_contextual_chunk_enrichment_gate",
        "status": "ok" if ready else "fail",
        "ready": ready,
        "contextual_enrichment_version": CONTEXTUAL_ENRICHMENT_VERSION,
        "checks": checks,
        "failures": failures,
        "coverage": {
            "official": official_coverage,
            "customer": customer_coverage,
            "total": total_coverage,
        },
        "recall_fixture": recall_fixture,
        "evidence": {
            "official_bm25_corpus": str(official_path),
            "customer_bm25_corpus_paths": [str(path) for path in existing_customer_paths],
        },
    }


def write_llmwiki_contextual_enrichment_gate_report(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    official_bm25_path: str | Path | None = None,
    customer_bm25_paths: list[str | Path] | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir).resolve()
    payload = build_llmwiki_contextual_enrichment_gate(
        root,
        official_bm25_path=official_bm25_path,
        customer_bm25_paths=customer_bm25_paths,
    )
    output = (
        Path(output_path)
        if output_path is not None
        else _dated_report_path(root, "llmwiki-contextual-enrichment-gate")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, payload
