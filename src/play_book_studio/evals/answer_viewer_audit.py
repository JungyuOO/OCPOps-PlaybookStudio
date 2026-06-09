from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


RAW_MARKERS = ("[CODE", "[/CODE]", "[TABLE", "[/TABLE]")


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    detail: str


DEFAULT_CASES = (
    {
        "id": "official-etcd-backup",
        "query": "etcd 백업 절차를 어디에서 확인해야 해?",
        "payload": {},
    },
    {
        "id": "study-kmsc-architecture",
        "query": "KMSC 테스트 결과에서 Pod 상태 확인 내용을 찾아줘",
        "payload": {"route_kind": "study_docs"},
    },
)


def _request_json(method: str, url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 180), **kwargs)
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": response.text[:500]}
    return response.status_code, payload if isinstance(payload, dict) else {"payload": payload}


def run_answer_viewer_audit(base_url: str, *, max_citations: int = 3) -> dict[str, Any]:
    base = base_url.rstrip("/")
    case_reports: list[dict[str, Any]] = []
    checks: list[CheckResult] = []
    for case in DEFAULT_CASES:
        payload = {"query": case["query"], **dict(case.get("payload") or {})}
        chat_status, chat_payload = _request_json("POST", f"{base}/api/chat", json=payload)
        answer = str(chat_payload.get("answer") or "")
        citations = [item for item in chat_payload.get("citations") or [] if isinstance(item, dict)]
        citation_reports: list[dict[str, Any]] = []

        checks.append(
            CheckResult(
                f"{case['id']}_chat",
                "pass" if chat_status == 200 and citations else "fail",
                f"status={chat_status} citations={len(citations)} response_kind={chat_payload.get('response_kind')}",
            )
        )
        checks.append(
            CheckResult(
                f"{case['id']}_raw_markers",
                "pass" if not any(marker in answer for marker in RAW_MARKERS) else "fail",
                "answer raw marker check",
            )
        )

        for citation in citations[:max_citations]:
            viewer_path = str(citation.get("viewer_path") or citation.get("href") or "").strip()
            citation_report: dict[str, Any] = {
                "index": citation.get("index"),
                "book_slug": citation.get("book_slug"),
                "section": citation.get("section"),
                "viewer_path": viewer_path,
            }
            if not viewer_path:
                citation_report["status"] = "fail"
                citation_report["detail"] = "missing viewer_path"
                citation_reports.append(citation_report)
                checks.append(CheckResult(f"{case['id']}_citation_{citation.get('index')}", "fail", "missing viewer_path"))
                continue

            meta_status, meta_payload = _request_json(
                "GET",
                f"{base}/api/source-meta",
                params={"viewer_path": viewer_path},
                timeout=90,
            )
            viewer_status, viewer_payload = _request_json(
                "GET",
                f"{base}/api/viewer-document",
                params={"viewer_path": viewer_path, "page_mode": "single"},
                timeout=90,
            )
            html = str(viewer_payload.get("html") or "")
            meta_viewer_path = str(meta_payload.get("viewer_path") or "").strip()
            citation_report.update(
                {
                    "source_meta_status": meta_status,
                    "viewer_status": viewer_status,
                    "source_meta_viewer_path": meta_viewer_path,
                    "viewer_html_length": len(html),
                    "source_meta_section": meta_payload.get("section"),
                    "source_meta_book_slug": meta_payload.get("book_slug"),
                    "viewer_body_class_name": viewer_payload.get("body_class_name"),
                }
            )
            passed = (
                meta_status == 200
                and viewer_status == 200
                and bool(meta_viewer_path)
                and meta_viewer_path.split("#", 1)[0] == viewer_path.split("#", 1)[0]
                and len(html) > 0
            )
            citation_report["status"] = "pass" if passed else "fail"
            citation_reports.append(citation_report)
            checks.append(
                CheckResult(
                    f"{case['id']}_citation_{citation.get('index')}",
                    "pass" if passed else "fail",
                    f"meta={meta_status} viewer={viewer_status} html_length={len(html)}",
                )
            )

        case_reports.append(
            {
                "id": case["id"],
                "query": case["query"],
                "chat_status": chat_status,
                "response_kind": chat_payload.get("response_kind"),
                "citation_count": len(citations),
                "answer_preview": answer[:400],
                "citations": citation_reports,
            }
        )

    failed = [check for check in checks if check.status != "pass"]
    return {
        "status": "pass" if not failed else "fail",
        "checks": [{"name": check.name, "status": check.status, "detail": check.detail} for check in checks],
        "cases": case_reports,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Answer / Viewer Check",
        "",
        f"- Status: `{payload.get('status')}`",
        "",
        "| check | status | detail |",
        "|---|---|---|",
    ]
    for check in payload.get("checks") or []:
        if isinstance(check, dict):
            lines.append(f"| `{check.get('name')}` | `{check.get('status')}` | {check.get('detail')} |")
    lines.extend(["", "## Cases", ""])
    for case in payload.get("cases") or []:
        if not isinstance(case, dict):
            continue
        lines.extend(
            [
                f"### {case.get('id')}",
                "",
                f"- response_kind: `{case.get('response_kind')}`",
                f"- citation_count: `{case.get('citation_count')}`",
                "",
                "| index | book | section | meta | viewer | html | status |",
                "|---:|---|---|---:|---:|---:|---|",
            ]
        )
        for citation in case.get("citations") or []:
            if isinstance(citation, dict):
                lines.append(
                    f"| {citation.get('index')} | `{citation.get('book_slug')}` | {citation.get('section')} | "
                    f"{citation.get('source_meta_status')} | {citation.get('viewer_status')} | "
                    f"{citation.get('viewer_html_length')} | `{citation.get('status')}` |"
                )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PBS answer citation and viewer audit.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output-dir", type=Path, default=Path(".kugnus-plan/rag-foundation"))
    parser.add_argument("--max-citations", type=int, default=3)
    args = parser.parse_args(argv)

    payload = run_answer_viewer_audit(args.base_url, max_citations=max(1, args.max_citations))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "answer_viewer_check.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "04-answer-viewer-check.md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload.get("status"), "check_count": len(payload.get("checks") or [])}, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
