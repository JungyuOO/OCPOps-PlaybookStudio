from __future__ import annotations

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


def _issue_sample(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "chunk_id": str(row.get("chunk_id") or ""),
        "book_slug": str(row.get("book_slug") or ""),
        "section": str(row.get("section") or ""),
        "chunk_type": str(row.get("chunk_type") or ""),
        "token_count": _safe_int(row.get("token_count")),
        "reason": reason,
        "preview": re.sub(r"\s+", " ", str(row.get("text") or ""))[:240],
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
        text = str(row.get("text") or "")
        cli_commands = [item for item in (row.get("cli_commands") or []) if str(item).strip()]
        token_count = _safe_int(row.get("token_count")) or len(text.split())
        token_counts.append(token_count)
        char_counts.append(len(text))
        command_counts.append(len(cli_commands))
        section_path = row.get("section_path") if isinstance(row.get("section_path"), list) else []
        section_depths.append(len(section_path))
        book_counts[str(row.get("book_slug") or "unknown")] += 1
        chunk_type_counts[str(row.get("chunk_type") or "unknown")] += 1
        language = _language_ratio(text)
        hangul_ratios.append(round(language["hangul_ratio"] * 10000))

        issues: list[str] = []
        if token_count > 260:
            issues.append("oversized_chunk")
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
        "# v0.0.4 Chunk Quality Audit",
        "",
        f"- Schema: `{payload.get('schema')}`",
        f"- Chunks: `{payload.get('chunk_count')}`",
        f"- Token count p50/p90/p95/max: `{token.get('p50')}` / `{token.get('p90')}` / `{token.get('p95')}` / `{token.get('max')}`",
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
