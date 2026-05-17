from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CASES = Path("corpus/manifests/eval/retrieval_official_data_validation_cases.jsonl")
DEFAULT_OUTPUT = Path("spec/v0.1.4/260518-retrieval-auto-audit.html")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def _git_diff_changed_case_ids(root: Path, path: Path, base_ref: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", f"{base_ref}..HEAD", "--", str(path)],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    changed: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.startswith(("+{", "-{")):
            continue
        match = re.search(r'"id":"([^"]+)"', line)
        if match:
            changed.add(match.group(1))
    return changed


def _fetch_qdrant_payloads(
    *,
    qdrant_url: str,
    collection: str,
    ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    payloads: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 64):
        batch = ids[start : start + 64]
        body = {
            "ids": batch,
            "with_payload": True,
            "with_vector": False,
        }
        req = urllib.request.Request(
            f"{qdrant_url.rstrip('/')}/collections/{collection}/points",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        for point in data.get("result", []):
            payload = point.get("payload") or {}
            chunk_id = payload.get("chunk_id") or str(point.get("id"))
            payloads[chunk_id] = payload
    return payloads


def _scope_from_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "unknown"
    source = payload.get("source") or {}
    scope = payload.get("source_scope") or source.get("corpus_scope") or source.get("source_scope")
    if scope:
        return str(scope)
    viewer = str(payload.get("viewer_path") or "")
    source_url = str(payload.get("source_url") or "")
    source_type = str(payload.get("source_type") or "")
    if "/uploads/" in viewer or "kmsc" in source_url:
        return "study_docs"
    if source_type == "official_doc" or "/docs/ocp/" in viewer or "docs.redhat.com" in source_url:
        return "official_docs"
    return "unknown"


def _payload_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    text_fields = payload.get("text_fields") or {}
    parts = [
        str(payload.get("text") or ""),
        str(text_fields.get("embedding_text") or ""),
        str(text_fields.get("normalized_text") or ""),
        str(payload.get("section") or ""),
        " ".join(str(item) for item in (payload.get("section_path") or [])),
    ]
    return "\n".join(part for part in parts if part)


def _loose(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).lower()


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    lowered_text = text.lower()
    lowered_term = term.lower()
    if lowered_term in lowered_text:
        return True
    loose_term = _loose(term)
    return bool(loose_term and loose_term in _loose(text))


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _contains_term(text, term)]


def _preview(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _directness_label(
    *,
    hit1: bool,
    hit5: bool,
    top1_term_count: int,
    top5_term_count: int,
    top1_text_len: int,
) -> str:
    if not hit5:
        return "fail"
    if hit1 and top1_term_count > 0 and top1_text_len >= 100:
        return "direct"
    if hit1 and (top1_term_count > 0 or top5_term_count > 0):
        return "partial"
    if hit5 and top5_term_count > 0:
        return "partial"
    return "weak"


def _make_row(
    *,
    detail: dict[str, Any],
    before_detail: dict[str, Any] | None,
    changed_expected_ids: set[str],
    payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    case_id = detail["id"]
    expected = list(detail.get("expected_book_slugs") or [])
    landing_terms = list(detail.get("expected_landing_terms") or [])
    top_hits = list(detail.get("top_hits") or [])
    top_books = list(detail.get("top_book_slugs") or [])
    top1 = top_hits[0] if top_hits else {}
    top1_chunk_id = str(top1.get("chunk_id") or "")
    top1_payload = payloads.get(top1_chunk_id, {})
    top1_text = _payload_text(top1_payload)
    top5_text = "\n".join(_payload_text(payloads.get(str(hit.get("chunk_id") or ""), {})) for hit in top_hits[:5])
    top1_matched = _matched_terms(top1_text, landing_terms)
    top5_matched = _matched_terms(top5_text, landing_terms)
    missing_landing_terms = [term for term in landing_terms if term not in top5_matched]
    hit1 = bool(top_books[:1] and top_books[0] in expected)
    hit3 = any(book in expected for book in top_books[:3])
    hit5 = any(book in expected for book in top_books[:5])
    source_counts = Counter(_scope_from_payload(payloads.get(str(hit.get("chunk_id") or ""))) for hit in top_hits[:5])
    directness = _directness_label(
        hit1=hit1,
        hit5=hit5,
        top1_term_count=len(top1_matched),
        top5_term_count=len(top5_matched),
        top1_text_len=len(re.sub(r"\s+", "", top1_text)),
    )
    risk_flags: list[str] = []
    if not hit5:
        risk_flags.append("hit5_false")
    if hit5 and not top5_matched:
        risk_flags.append("hit5_true_but_no_landing_terms")
    if not hit1:
        risk_flags.append("top1_not_expected")
    if source_counts.get("study_docs", 0) > 0:
        risk_flags.append("study_docs_in_top5")
    if case_id in changed_expected_ids:
        risk_flags.append("expected_changed_in_diff")
    before_score = None
    if before_detail and before_detail.get("top_hits"):
        before_score = _score(before_detail["top_hits"][0].get("score"))
    top1_score = _score(top1.get("score"))
    if before_score is not None and top1_score > before_score and directness in {"partial", "weak", "fail"}:
        risk_flags.append("score_up_but_not_direct")
    if len(re.sub(r"\s+", "", top1_text)) < 100:
        risk_flags.append("short_top1_preview")
    if landing_terms and not top1_matched:
        risk_flags.append("top1_missing_core_terms")
    return {
        "case_id": case_id,
        "question": detail.get("query") or "",
        "expected_book_slugs": expected,
        "top1_book": top1.get("book_slug") or "",
        "top1_chunk_id": top1_chunk_id,
        "top1_section": top1.get("section") or "",
        "top1_score": top1_score,
        "hit1": hit1,
        "hit3": hit3,
        "hit5": hit5,
        "landing_terms_hit_count": len(top5_matched),
        "missing_landing_terms": missing_landing_terms,
        "source_scope_counts": dict(source_counts),
        "top1_directness_label": directness,
        "risk_flags": risk_flags,
        "top1_text_preview": _preview(top1_text),
    }


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def _render_badges(items: list[str]) -> str:
    if not items:
        return '<span class="ok">none</span>'
    return " ".join(f'<span class="risk">{html.escape(item)}</span>' for item in items)


def _render_table(rows: list[dict[str, Any]], *, review_only: bool = False) -> str:
    filtered = [
        row
        for row in rows
        if not review_only or row["risk_flags"] or row["top1_directness_label"] != "direct"
    ]
    body: list[str] = []
    for row in filtered:
        flags = _render_badges(row["risk_flags"])
        directness = html.escape(row["top1_directness_label"])
        direct_class = {
            "direct": "ok",
            "partial": "warn",
            "weak": "warn",
            "fail": "bad",
        }.get(row["top1_directness_label"], "warn")
        body.append(
            "<tr>"
            f"<td><code>{html.escape(row['case_id'])}</code></td>"
            f"<td>{html.escape(row['question'])}</td>"
            f"<td>{html.escape(', '.join(row['expected_book_slugs']))}</td>"
            f"<td>{html.escape(row['top1_book'])}</td>"
            f"<td><code>{html.escape(row['top1_chunk_id'])}</code></td>"
            f"<td>{html.escape(row['top1_section'])}</td>"
            f"<td>{row['top1_score']:.6f}</td>"
            f"<td>{_render_bool(row['hit1'])} / {_render_bool(row['hit3'])} / {_render_bool(row['hit5'])}</td>"
            f"<td>{row['landing_terms_hit_count']}</td>"
            f"<td>{html.escape(', '.join(row['missing_landing_terms']) or '-')}</td>"
            f"<td>{html.escape(json.dumps(row['source_scope_counts'], ensure_ascii=False))}</td>"
            f'<td><span class="{direct_class}">{directness}</span></td>'
            f"<td>{flags}</td>"
            f"<td>{html.escape(row['top1_text_preview'])}</td>"
            "</tr>"
        )
    if not body:
        return "<p>사람이 추가로 봐야 할 case가 없습니다.</p>"
    return (
        "<table>"
        "<tr>"
        "<th>case_id</th><th>question</th><th>expected_book_slugs</th><th>top1_book</th>"
        "<th>top1_chunk_id</th><th>top1_section</th><th>top1_score</th><th>hit@1 / hit@3 / hit@5</th>"
        "<th>landing_terms_hit_count</th><th>missing_landing_terms</th><th>source_scope_counts</th>"
        "<th>top1_directness_label</th><th>risk_flags</th><th>top1 text preview</th>"
        "</tr>"
        + "\n".join(body)
        + "</table>"
    )


def _render_html(
    *,
    rows: list[dict[str, Any]],
    output: Path,
    after_path: Path,
    before_path: Path,
    cases_path: Path,
    changed_expected_ids: set[str],
) -> str:
    total = len(rows)
    risk_rows = [row for row in rows if row["risk_flags"]]
    review_rows = [row for row in rows if row["risk_flags"] or row["top1_directness_label"] != "direct"]
    labels = Counter(row["top1_directness_label"] for row in rows)
    risk_counts = Counter(flag for row in rows for flag in row["risk_flags"])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>260518 Retrieval 자동 검수 리포트</title>
<style>
body{{font-family:Arial,'Malgun Gothic',sans-serif;line-height:1.55;margin:28px;max-width:1500px;color:#172033}}
h1,h2{{color:#0f3563}} code{{background:#f5f7fb;border:1px solid #d8e0ef;border-radius:5px;padding:1px 4px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 24px}}
th,td{{border:1px solid #d8e0ef;padding:7px;vertical-align:top}} th{{background:#edf3ff}}
.note{{background:#eef8f2;border-left:4px solid #12b76a;padding:12px;margin:16px 0}}
.warnbox{{background:#fff8e6;border-left:4px solid #f79009;padding:12px;margin:16px 0}}
.ok{{color:#067647;font-weight:700}} .warn{{color:#b54708;font-weight:700}} .bad{{color:#b42318;font-weight:700}}
.risk{{display:inline-block;background:#fff1f3;color:#b42318;border:1px solid #ffccd5;border-radius:999px;padding:1px 7px;margin:1px;font-size:11px}}
.muted{{color:#667085;font-size:12px}}
</style>
</head>
<body>
<h1>260518 Retrieval 자동 검수 리포트</h1>
<div class="note">
사람이 30건을 모두 읽지 않도록, after retrieval 결과와 Qdrant payload를 결합해 위험 조건을 자동 표시한 리포트입니다.
이 리포트는 answer LLM 품질 평가가 아니라 retrieval source/top chunk 검수용입니다.
</div>
<table>
<tr><th>생성 시각</th><td>{html.escape(generated_at)}</td></tr>
<tr><th>cases</th><td><code>{html.escape(str(cases_path))}</code></td></tr>
<tr><th>before JSON</th><td><code>{html.escape(str(before_path))}</code></td></tr>
<tr><th>after JSON</th><td><code>{html.escape(str(after_path))}</code></td></tr>
<tr><th>output</th><td><code>{html.escape(str(output))}</code></td></tr>
<tr><th>expected 변경 case</th><td>{html.escape(', '.join(sorted(changed_expected_ids)) or 'none')}</td></tr>
</table>
<h2>1. 요약</h2>
<table>
<tr><th>전체 case</th><td>{total}</td></tr>
<tr><th>directness 분포</th><td>{html.escape(json.dumps(dict(labels), ensure_ascii=False))}</td></tr>
<tr><th>risk flag 있는 case</th><td>{len(risk_rows)}</td></tr>
<tr><th>사람 검토 대상</th><td>{len(review_rows)}</td></tr>
<tr><th>risk flag 분포</th><td>{html.escape(json.dumps(dict(risk_counts), ensure_ascii=False))}</td></tr>
</table>
<div class="warnbox">
<strong>risk flag 기준</strong>: hit@5=false, hit@5=true지만 landing term 0건, top1이 expected 아님,
top5 안 study_docs 포함, expected가 이번 diff에서 변경됨, score는 올랐지만 direct가 아님,
top1 text가 100자 미만, top1에 expected landing/core term이 없음.
</div>
<h2>2. 사람이 봐야 할 case</h2>
{_render_table(rows, review_only=True)}
<h2>3. 전체 case 자동 검수 표</h2>
{_render_table(rows, review_only=False)}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build retrieval automatic audit HTML report.")
    parser.add_argument("--before", type=Path, default=Path(os.environ.get("TEMP", ".")) / "pbs-official-data-validation-before-realfix.json")
    parser.add_argument("--after", type=Path, default=Path(os.environ.get("TEMP", ".")) / "pbs-official-data-validation-after-partialfix4.json")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6335")
    parser.add_argument("--collection", default="openshift_docs")
    parser.add_argument("--base-ref", default="HEAD^")
    args = parser.parse_args(argv)

    root = _repo_root()
    before_path = (root / args.before).resolve() if not args.before.is_absolute() else args.before
    after_path = (root / args.after).resolve() if not args.after.is_absolute() else args.after
    cases_path = (root / args.cases).resolve() if not args.cases.is_absolute() else args.cases
    output_path = (root / args.output).resolve() if not args.output.is_absolute() else args.output

    before_data = _read_json(before_path)
    after_data = _read_json(after_path)
    _load_cases(cases_path)
    before_by_id = {row["id"]: row for row in before_data.get("details", [])}
    details = list(after_data.get("details", []))
    chunk_ids = sorted({str(hit.get("chunk_id")) for row in details for hit in row.get("top_hits", [])[:5] if hit.get("chunk_id")})
    payloads = _fetch_qdrant_payloads(qdrant_url=args.qdrant_url, collection=args.collection, ids=chunk_ids)
    changed_expected_ids = _git_diff_changed_case_ids(root, args.cases, args.base_ref)
    rows = [
        _make_row(
            detail=detail,
            before_detail=before_by_id.get(detail["id"]),
            changed_expected_ids=changed_expected_ids,
            payloads=payloads,
        )
        for detail in details
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_html(
            rows=rows,
            output=output_path,
            after_path=after_path,
            before_path=before_path,
            cases_path=cases_path,
            changed_expected_ids=changed_expected_ids,
        ),
        encoding="utf-8",
    )
    risk_count = sum(1 for row in rows if row["risk_flags"])
    review_count = sum(1 for row in rows if row["risk_flags"] or row["top1_directness_label"] != "direct")
    print(f"wrote {output_path}")
    print(f"cases={len(rows)} risk_cases={risk_count} review_cases={review_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
