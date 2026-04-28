from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from play_book_studio.app.course_api import _course_chat_payload
from play_book_studio.course.quality_eval import read_jsonl


REPORT_SCHEMA = "course_chat_visual_audit_manifest_v1"
CAPTURE_REPORT_SCHEMA = "course_chat_visual_capture_report_v1"
BROWSER_IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
BROWSER_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")[:120] or "case"


def _text(value: Any) -> str:
    return html.escape(str(value or ""))


def _card(title: str, body: str, *, class_name: str = "") -> str:
    return f'<section class="card {class_name}"><h2>{_text(title)}</h2>{body}</section>'


def _asset_web_path(asset_path: str, *, assets_dir: Path, asset_index: dict[str, str]) -> str:
    image_path = Path(asset_path)
    if not image_path.is_absolute():
        image_path = Path.cwd() / image_path
    image_path = image_path.resolve()
    key = str(image_path)
    if key in asset_index:
        return asset_index[key]
    if not image_path.exists() or not image_path.is_file():
        return ""
    target_suffix = image_path.suffix.lower()
    image_to_save = None
    try:
        from PIL import Image

        image = Image.open(image_path)
        image.load()
        source_format = str(image.format or "").upper()
        if source_format in BROWSER_IMAGE_FORMATS:
            target_suffix = BROWSER_IMAGE_FORMATS[source_format]
            image.close()
        else:
            target_suffix = ".png"
            image_to_save = image.convert("RGBA") if image.mode not in {"RGB", "RGBA"} else image
    except Exception:
        if target_suffix not in BROWSER_IMAGE_SUFFIXES:
            target_suffix = ".bin"
    asset_name = f"{len(asset_index) + 1:04d}-{_safe_filename(image_path.stem)}{target_suffix}"
    target = assets_dir / asset_name
    if image_to_save is None:
        shutil.copy2(image_path, target)
    else:
        image_to_save.save(target, format="PNG")
        image_to_save.close()
    web_path = f"../assets/{asset_name}?v={target.stat().st_mtime_ns}"
    asset_index[key] = web_path
    return web_path


def _artifact_html(artifacts: list[dict[str, Any]], *, assets_dir: Path, asset_index: dict[str, str]) -> str:
    sections: list[str] = []
    for artifact in artifacts:
        kind = str(artifact.get("kind") or "")
        title = str(artifact.get("title") or kind)
        items = artifact.get("items") if isinstance(artifact.get("items"), list) else []
        item_cards: list[str] = []
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            lines = [
                f"<strong>{_text(item.get('native_id') or item.get('title') or item.get('section_title') or item.get('chunk_id'))}</strong>",
                f"<p>{_text(item.get('title') or item.get('section_title') or item.get('summary') or item.get('match_reason'))}</p>",
                f"<small>{_text(item.get('instructional_role') or item.get('role') or item.get('book_slug'))} {_text(item.get('state_signal') or '')}</small>",
            ]
            asset_path = str(item.get("asset_path") or "")
            if asset_path:
                web_path = _asset_web_path(asset_path, assets_dir=assets_dir, asset_index=asset_index)
                if web_path:
                    lines.insert(0, f'<img src="{_text(web_path)}" alt="{_text(item.get("summary") or item.get("asset_id"))}">')
            item_cards.append(f'<article class="artifact-item {kind}">{"".join(lines)}</article>')
        sections.append(_card(title, f'<div class="artifact-grid">{"".join(item_cards)}</div>', class_name=kind))
    return "".join(sections)


def _sources_html(sources: list[dict[str, Any]]) -> str:
    rows = []
    for source in sources:
        rows.append(
            "<li>"
            f"<strong>{_text(source.get('source_kind'))}</strong> "
            f"{_text(source.get('title'))} "
            f"<span>{_text(source.get('section_title'))}</span>"
            "</li>"
        )
    return "<ul class=\"sources\">" + "".join(rows) + "</ul>"


def _case_html(
    case: dict[str, Any],
    response: dict[str, Any],
    verdict: dict[str, Any],
    *,
    assets_dir: Path,
    asset_index: dict[str, str],
) -> str:
    answer = str(response.get("answer") or "")
    passed = bool(verdict.get("passed"))
    status = "PASS" if passed else "FAIL"
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_text(case.get('id'))} - {status}</title>
  <style>
    body {{ margin: 0; font-family: Arial, 'Malgun Gothic', sans-serif; background: #f5f7f9; color: #17202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 24px; }}
    h2 {{ margin: 0 0 10px; font-size: 16px; }}
    .badge {{ padding: 8px 12px; border-radius: 6px; font-weight: 700; color: white; background: {'#137a43' if passed else '#b42318'}; }}
    .meta {{ color: #53616f; margin-top: 8px; }}
    .card {{ background: white; border: 1px solid #d8e0e8; border-radius: 8px; padding: 16px; margin: 12px 0; box-shadow: 0 1px 2px rgba(16,24,40,.04); }}
    .answer {{ white-space: pre-wrap; line-height: 1.58; font-size: 14px; }}
    .sources {{ margin: 0; padding-left: 20px; line-height: 1.8; }}
    .sources span {{ color: #657484; margin-left: 8px; }}
    .artifact-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .artifact-item {{ border: 1px solid #e2e8ef; border-radius: 7px; padding: 10px; background: #fbfcfe; min-height: 92px; }}
    .artifact-item img {{ width: 100%; max-height: 180px; object-fit: contain; background: #101418; border-radius: 4px; margin-bottom: 8px; }}
    .artifact-item p {{ margin: 7px 0; color: #344054; }}
    .artifact-item small {{ color: #667085; }}
    .failures {{ color: #b42318; font-weight: 700; }}
  </style>
</head>
<body>
  <main data-audit-status="{status}" data-case-id="{_text(case.get('id'))}">
    <header>
      <div>
        <h1>{_text(case.get('id'))}</h1>
        <div class="meta">{_text(case.get('category'))} / stage: {_text(case.get('stage_id'))}</div>
        <div class="meta">Q. {_text(case.get('query'))}</div>
      </div>
      <div class="badge">{status}</div>
    </header>
    {_card('Answer', f'<div class="answer">{_text(answer)}</div>', class_name='answer-card')}
    {_card('Sources', _sources_html(response.get('sources') if isinstance(response.get('sources'), list) else []))}
    {_artifact_html(response.get('artifacts') if isinstance(response.get('artifacts'), list) else [], assets_dir=assets_dir, asset_index=asset_index)}
    {_card('Audit Verdict', f"<p class='failures'>{_text(', '.join(verdict.get('failures') or []))}</p><p>answer chars: {_text(verdict.get('answer_char_count'))}</p>")}
  </main>
</body>
</html>
"""


def generate_visual_audit(root_dir: Path, *, cases_path: Path, output_dir: Path) -> dict[str, Any]:
    cases = read_jsonl(cases_path)
    pages_dir = output_dir / "pages"
    screenshots_dir = output_dir / "screenshots"
    assets_dir = output_dir / "assets"
    pages_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_index: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        response = _course_chat_payload(root_dir, {"message": case["query"], "stage_id": case.get("stage_id") or ""})
        answer = str(response.get("answer") or "")
        required = {
            "has_answer": bool(answer.strip()),
            "has_study_docs": "실운영 Study-docs 기준" in answer,
            "has_sources": bool(response.get("sources")),
            "has_artifacts": bool(response.get("artifacts")),
        }
        failures = [name for name, ok in required.items() if not ok]
        row = {
            "index": index,
            "id": case.get("id"),
            "category": case.get("category"),
            "query": case.get("query"),
            "stage_id": case.get("stage_id"),
            "passed": not failures,
            "failures": failures,
            "answer_char_count": len(answer),
            "artifact_kinds": [artifact.get("kind") for artifact in response.get("artifacts", []) if isinstance(artifact, dict)],
            "source_count": len(response.get("sources") if isinstance(response.get("sources"), list) else []),
        }
        page_name = f"{index:03d}-{_safe_filename(str(case.get('id') or index))}.html"
        page_path = pages_dir / page_name
        page_path.write_text(_case_html(case, response, row, assets_dir=assets_dir, asset_index=asset_index), encoding="utf-8")
        row["page_path"] = str(page_path)
        row["page_url"] = page_path.resolve().as_uri()
        row["screenshot_path"] = str(screenshots_dir / f"{page_path.stem}.png")
        rows.append(row)
    report = {
        "schema": REPORT_SCHEMA,
        "case_count": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "pages_dir": str(pages_dir),
        "screenshots_dir": str(screenshots_dir),
        "items": rows,
    }
    (output_dir / "visual_audit_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _extract_playwright_result(stdout: str) -> dict[str, Any]:
    match = re.search(r"### Result\s*\n(\{.*?\})\s*\n### Ran Playwright code", stdout, re.S)
    if not match:
        raise RuntimeError("Playwright result JSON was not found in stdout")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise RuntimeError("Playwright result was not an object")
    return payload


def _resolve_playwright_args(args: list[str]) -> list[str]:
    if os.name == "nt" and args and args[0] == "playwright-cli":
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@playwright" / "cli" / "playwright-cli.js",
            Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@playwright" / "cli" / "playwright-cli.js",
        ]
        for candidate in candidates:
            if candidate.exists():
                return ["node", str(candidate), *args[1:]]
    return args


def _run_playwright(args: list[str]) -> subprocess.CompletedProcess[str]:
    args = _resolve_playwright_args(args)
    try:
        return subprocess.run(args, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    except FileNotFoundError:
        if os.name != "nt":
            raise
        command = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )


def _start_static_server(directory: Path, *, host: str, port: int) -> tuple[ThreadingHTTPServer, str]:
    class QuietStaticHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

    handler = partial(QuietStaticHandler, directory=str(directory))
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_port}/"


def capture_visual_audit(
    *,
    output_dir: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    session: str = "course-visual-audit",
    playwright_cmd: str = "playwright-cli",
    viewport_width: int = 1440,
    viewport_height: int = 1100,
) -> dict[str, Any]:
    manifest_path = output_dir / "visual_audit_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"visual audit manifest not found: {manifest_path}")
    server, base_url = _start_static_server(output_dir, host=host, port=port)
    try:
        open_result = _run_playwright([playwright_cmd, "--session", session, "open", "about:blank"])
        if open_result.returncode != 0:
            raise RuntimeError(open_result.stderr or open_result.stdout or "failed to open Playwright session")
        script = f"""
async page => {{
  const base = {json.dumps(base_url)};
  await page.setViewportSize({{width: {viewport_width}, height: {viewport_height}}});
  await page.goto(base + 'pages/001-exact-architecture-001.html?t=' + Date.now());
  const manifest = await page.evaluate(async url => await (await fetch(url)).json(), base + 'visual_audit_manifest.json?t=' + Date.now());
  const results = [];
  for (const item of manifest.items) {{
    const pageName = item.page_path.split(/[\\\\/]/).pop();
    await page.goto(base + 'pages/' + pageName + '?t=' + Date.now(), {{ waitUntil: 'load' }});
    const bodyText = await page.locator('body').innerText();
    const images = await page.locator('img').evaluateAll(imgs => imgs.map(img => ({{
      src: img.getAttribute('src'),
      complete: img.complete,
      nw: img.naturalWidth,
      nh: img.naturalHeight
    }})));
    const badImages = images.filter(i => !i.complete || !i.nw || !i.nh);
    const auditFailures = await page.locator('[data-audit-status=FAIL]').count();
    const result = {{
      id: item.id,
      category: item.category,
      stage_id: item.stage_id,
      title: await page.title(),
      auditFailures,
      textLength: bodyText.length,
      hasStudyDocs: bodyText.includes('실운영 Study-docs 기준'),
      hasOfficialDocs: bodyText.includes('공식문서 확인'),
      hasGuidedTour: bodyText.includes('Guided Tour'),
      hasImageEvidence: bodyText.includes('Image Evidence'),
      imageCount: images.length,
      badImages: badImages.length,
      screenshot_path: item.screenshot_path
    }};
    await page.screenshot({{ path: item.screenshot_path.replace(/\\\\/g, '/'), fullPage: true }});
    results.push(result);
  }}
  const failed = results.filter(r => r.auditFailures || !r.hasStudyDocs || r.badImages || r.textLength < 800);
  return {{
    schema: {json.dumps(CAPTURE_REPORT_SCHEMA)},
    caseCount: results.length,
    failedCount: failed.length,
    screenshotCount: results.length,
    totalImages: results.reduce((n, r) => n + r.imageCount, 0),
    totalBadImages: results.reduce((n, r) => n + r.badImages, 0),
    noImageCases: results.filter(r => r.imageCount === 0).length,
    failed,
    results
  }};
}}
"""
        run_result = _run_playwright([playwright_cmd, "--session", session, "run-code", script])
        raw_log_path = output_dir / "playwright_capture_raw.log"
        raw_log_path.write_text(run_result.stdout + ("\n" + run_result.stderr if run_result.stderr else ""), encoding="utf-8")
        if run_result.returncode != 0:
            raise RuntimeError(run_result.stderr or run_result.stdout or "Playwright capture failed")
        report = _extract_playwright_result(run_result.stdout)
        report_path = output_dir / "playwright_capture_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        server.shutdown()
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate static browser pages for course QA visual audits.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/playwright/course-qa-audit"))
    parser.add_argument("--capture", action="store_true", help="Capture generated audit pages with playwright-cli.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session", default="course-visual-audit")
    parser.add_argument("--playwright-cmd", default="playwright-cli")
    return parser


def main() -> int:
    args = build_parser().parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())
