from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CODE_MARKUP_RE = re.compile(r"\[/?CODE[^\]]*\]", re.IGNORECASE)
CODE_BLOCK_RE = re.compile(r"\[CODE[^\]]*\]|```", re.IGNORECASE)
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
LATIN_RE = re.compile(r"[A-Za-z]")
NAVIGATION_RE = re.compile(
    r"(additional resources|related information|next steps|추가 리소스|관련 정보|다음 단계)",
    re.IGNORECASE,
)
PROCEDURE_RE = re.compile(r"(procedure|절차|프로세스|다음 명령|run the following|다음을 실행)", re.IGNORECASE)
CLI_COMMAND_RE = re.compile(r"(?:^|\s)(?:\$?\s*)\b(?:oc|kubectl|helm|podman|docker)\s+[A-Za-z0-9_.:/=-]+", re.MULTILINE)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[max(0, min(index, len(ordered) - 1))]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _language_ratio(text: str) -> dict[str, float]:
    hangul = len(HANGUL_RE.findall(text or ""))
    latin = len(LATIN_RE.findall(text or ""))
    total = hangul + latin
    return {
        "hangul_ratio": _ratio(hangul, total),
        "latin_ratio": _ratio(latin, total),
    }


def _row_text(row: dict[str, Any]) -> str:
    for key in ("text", "embedding_text", "search_text", "body_md", "markdown", "content"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    index_texts = row.get("index_texts")
    if isinstance(index_texts, dict):
        for key in ("dense_text", "sparse_text", "title_text", "visual_text"):
            value = index_texts.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _row_chunk_type(row: dict[str, Any]) -> str:
    for key in ("chunk_type", "chunk_kind", "canonical_model"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "unknown"


def _row_cli_commands(row: dict[str, Any], text: str) -> list[str]:
    explicit = [item for item in (row.get("cli_commands") or []) if str(item).strip()]
    if explicit:
        return [str(item).strip() for item in explicit]
    return [match.group(0).strip() for match in CLI_COMMAND_RE.finditer(text)]


def _issue_sample(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    text = _row_text(row)
    return {
        "chunk_id": str(row.get("chunk_id") or ""),
        "book_slug": str(row.get("book_slug") or ""),
        "section": str(row.get("section") or ""),
        "chunk_type": _row_chunk_type(row),
        "token_count": _safe_int(row.get("token_count")),
        "reason": reason,
        "preview": re.sub(r"\s+", " ", text)[:240],
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def build_chunk_quality_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    token_counts: list[int] = []
    char_counts: list[int] = []
    section_depths: list[int] = []
    command_counts: list[int] = []
    book_counts: Counter[str] = Counter()
    chunk_type_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    issue_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hangul_ratios: list[int] = []

    for row in rows:
        text = _row_text(row)
        cli_commands = _row_cli_commands(row, text)
        token_count = _safe_int(row.get("token_count")) or len(text.split())
        token_counts.append(token_count)
        char_counts.append(len(text))
        command_counts.append(len(cli_commands))
        section_path = row.get("section_path") if isinstance(row.get("section_path"), list) else []
        section_depths.append(len(section_path))
        book_counts[str(row.get("book_slug") or "unknown")] += 1
        chunk_type_counts[_row_chunk_type(row)] += 1
        language = _language_ratio(text)
        hangul_ratios.append(round(language["hangul_ratio"] * 10000))

        issues: list[str] = []
        if token_count > 260:
            issues.append("oversized_chunk")
        if len(text) > 2600:
            issues.append("oversized_char_chunk")
        if token_count < 18 and len(text.strip()) < 120:
            issues.append("undersized_chunk")
        if CODE_MARKUP_RE.search(text):
            issues.append("raw_code_markup")
        if len(cli_commands) >= 4:
            issues.append("command_dense_chunk")
        if CODE_BLOCK_RE.search(text) and NAVIGATION_RE.search(text):
            issues.append("code_plus_navigation")
        if CODE_BLOCK_RE.search(text) and PROCEDURE_RE.search(text) and NAVIGATION_RE.search(text):
            issues.append("mixed_procedure_navigation")
        if language["latin_ratio"] > 0.78 and str(row.get("display_language") or "").lower() == "ko":
            issues.append("high_latin_ratio_ko_chunk")

        for issue in issues:
            issue_counts[issue] += 1
            if len(issue_samples[issue]) < 8:
                issue_samples[issue].append(_issue_sample(row, reason=issue))

    total = len(rows)
    command_chunk_count = sum(1 for count in command_counts if count > 0)
    raw_markup_count = issue_counts.get("raw_code_markup", 0)
    oversized_count = issue_counts.get("oversized_chunk", 0)
    mixed_count = issue_counts.get("mixed_procedure_navigation", 0)

    recommendation = "keep_chunking_stable"
    if total and (raw_markup_count / total > 0.08 or oversized_count / total > 0.12 or mixed_count / total > 0.04):
        recommendation = "audit_before_rechunking"

    return {
        "schema": "pbs_chunk_quality_audit_v1",
        "chunk_count": total,
        "token_count": {
            "p50": _percentile(token_counts, 0.50),
            "p75": _percentile(token_counts, 0.75),
            "p90": _percentile(token_counts, 0.90),
            "p95": _percentile(token_counts, 0.95),
            "max": max(token_counts or [0]),
        },
        "char_count": {
            "p50": _percentile(char_counts, 0.50),
            "p90": _percentile(char_counts, 0.90),
            "max": max(char_counts or [0]),
        },
        "section_depth": {
            "p50": _percentile(section_depths, 0.50),
            "p90": _percentile(section_depths, 0.90),
            "max": max(section_depths or [0]),
        },
        "command_chunks": {
            "count": command_chunk_count,
            "ratio": _ratio(command_chunk_count, total),
            "command_count_p90": _percentile(command_counts, 0.90),
            "command_count_max": max(command_counts or [0]),
        },
        "language": {
            "hangul_ratio_p50": round(_percentile(hangul_ratios, 0.50) / 10000, 4),
            "hangul_ratio_p10": round(_percentile(hangul_ratios, 0.10) / 10000, 4),
        },
        "chunk_type_counts": dict(sorted(chunk_type_counts.items())),
        "top_books": dict(book_counts.most_common(12)),
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_rates": {
            issue: _ratio(count, total)
            for issue, count in sorted(issue_counts.items())
        },
        "issue_samples": dict(issue_samples),
        "decision": {
            "recommendation": recommendation,
            "reason": (
                "Use retrieval/eval failures to target metadata or child chunk changes; do not reimport the corpus "
                "until raw markup, oversized, or mixed-procedure evidence crosses the threshold."
            ),
        },
    }


def audit_chunks_file(chunks_path: Path) -> dict[str, Any]:
    return build_chunk_quality_audit(read_jsonl(chunks_path))


def write_markdown_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    token = payload.get("token_count", {})
    command = payload.get("command_chunks", {})
    issue_counts = payload.get("issue_counts", {})
    lines = [
        "# Chunk Quality Audit",
        "",
        f"- Schema: `{payload.get('schema')}`",
        f"- Source: `{payload.get('source_label') or payload.get('source_path') or 'unknown'}`",
        f"- Chunks: `{payload.get('chunk_count')}`",
        f"- Token count p50/p90/p95/max: `{token.get('p50')}` / `{token.get('p90')}` / `{token.get('p95')}` / `{token.get('max')}`",
        f"- Char count p50/p90/max: `{(payload.get('char_count') or {}).get('p50')}` / `{(payload.get('char_count') or {}).get('p90')}` / `{(payload.get('char_count') or {}).get('max')}`",
        f"- Command chunks: `{command.get('count')}` (`{command.get('ratio')}`)",
        f"- Decision: `{(payload.get('decision') or {}).get('recommendation')}`",
        "",
        "## Issue Counts",
        "",
    ]
    for issue, count in sorted(issue_counts.items()):
        lines.append(f"- `{issue}`: `{count}`")
    lines.extend(["", "## Decision", "", str((payload.get("decision") or {}).get("reason") or "")])
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _with_source_metadata(payload: dict[str, Any], *, path: Path, label: str = "") -> dict[str, Any]:
    enriched = dict(payload)
    enriched["source_path"] = str(path)
    if label:
        enriched["source_label"] = label
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit corpus chunk quality.")
    parser.add_argument("--chunks", required=True, type=Path, help="Path to chunks.jsonl")
    parser.add_argument("--output-json", type=Path, default=None, help="Write JSON audit report")
    parser.add_argument("--output-md", type=Path, default=None, help="Write Markdown audit report")
    parser.add_argument("--label", default="", help="Human-readable source label")
    args = parser.parse_args(argv)

    payload = _with_source_metadata(
        audit_chunks_file(args.chunks),
        path=args.chunks,
        label=args.label,
    )
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.output_md is not None:
        write_markdown_report(payload, args.output_md)
    if args.output_json is None and args.output_md is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
