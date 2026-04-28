from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from play_book_studio.course.quality_eval import read_jsonl
from play_book_studio.course.visual_audit import _extract_playwright_result, _run_playwright
from play_book_studio.course.visual_audit_server import build_handler


REPORT_SCHEMA = "course_frontend_smoke_report_v1"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return safe.strip("-")[:120] or "scenario"


def _pick_scenarios(cases: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    preferred_categories = [
        "guided_stage_route",
        "guided_route_sequence",
        "guided_route_step",
        "official_mapping",
        "image_state_evidence",
        "image_role_evidence",
        "chunk_drilldown",
        "official_mapping_broad",
    ]
    picked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for category in preferred_categories:
        for case in cases:
            case_id = str(case.get("id") or "")
            if case_id in seen_ids or str(case.get("category") or "") != category:
                continue
            stage_id = str(case.get("stage_id") or "")
            query = str(case.get("query") or "").strip()
            if not stage_id or not query:
                continue
            seen_ids.add(case_id)
            picked.append({"id": case_id, "category": category, "stage_id": stage_id, "query": query})
            break
        if len(picked) >= limit:
            return picked
    for case in cases:
        if len(picked) >= limit:
            break
        case_id = str(case.get("id") or "")
        if case_id in seen_ids:
            continue
        stage_id = str(case.get("stage_id") or "")
        query = str(case.get("query") or "").strip()
        if not stage_id or not query:
            continue
        seen_ids.add(case_id)
        picked.append({"id": case_id, "category": str(case.get("category") or ""), "stage_id": stage_id, "query": query})
    return picked


def _start_course_ui_server(root_dir: Path, *, host: str, port: int) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer((host, port), build_handler(root_dir))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_port}/"


def run_course_frontend_smoke(
    root_dir: Path,
    *,
    cases_path: Path,
    output_dir: Path,
    scenario_count: int = 12,
    host: str = "127.0.0.1",
    port: int = 0,
    session: str = "course-ui-smoke",
    playwright_cmd: str = "playwright-cli",
) -> dict[str, Any]:
    dist_index = root_dir / "presentation-ui" / "dist" / "index.html"
    if not dist_index.exists():
        raise FileNotFoundError("presentation-ui/dist/index.html not found; run npm run build in presentation-ui first")
    scenarios = _pick_scenarios(read_jsonl(cases_path), limit=scenario_count)
    if not scenarios:
        raise ValueError("no frontend smoke scenarios found")
    screenshots_dir = output_dir / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    for index, scenario in enumerate(scenarios, start=1):
        scenario["screenshot_path"] = str(screenshots_dir / f"{index:03d}-{_safe_filename(scenario['id'])}.png")

    server, base_url = _start_course_ui_server(root_dir, host=host, port=port)
    try:
        open_result = _run_playwright([playwright_cmd, "--session", session, "open", "about:blank"])
        if open_result.returncode != 0:
            raise RuntimeError(open_result.stderr or open_result.stdout or "failed to open Playwright session")
        script = f"""
async page => {{
  const base = {json.dumps(base_url)};
  const scenarios = {json.dumps(scenarios, ensure_ascii=False)};
  await page.setViewportSize({{width: 1440, height: 1100}});
  const results = [];
  for (const scenario of scenarios) {{
    await page.goto(base + 'course/stages/' + encodeURIComponent(scenario.stage_id) + '?t=' + Date.now(), {{ waitUntil: 'networkidle' }});
    const guidedAskButtons = page.locator('.course-recommendation-card .course-card-actions button, .course-official-check-card .course-card-actions button');
    const guidedAskButtonCount = await guidedAskButtons.count();
    let guidedAskAnswerText = '';
    let suggestedQueryCount = 0;
    if (guidedAskButtonCount > 0) {{
      await guidedAskButtons.first().click();
      await page.waitForSelector('.course-chat-answer', {{ timeout: 60000 }});
      await page.waitForFunction(() => !document.body.innerText.includes('Running...'), null, {{ timeout: 60000 }});
      await page.waitForFunction(() => {{
        const text = document.querySelector('.course-chat-answer')?.innerText || '';
        return text.includes('Study-docs') && text.includes('Guided Tour');
      }}, null, {{ timeout: 90000 }});
      guidedAskAnswerText = await page.locator('.course-chat-answer').innerText();
      suggestedQueryCount = await page.locator('.course-chat-suggested button').count();
    }}
    await page.locator('textarea').last().fill(scenario.query);
    await page.locator('.course-chat-box button').click();
    await page.waitForSelector('.course-chat-answer', {{ timeout: 60000 }});
    await page.waitForFunction(() => !document.body.innerText.includes('Running...'), null, {{ timeout: 60000 }});
    await page.waitForFunction(() => {{
      const text = document.querySelector('.course-chat-answer')?.innerText || '';
      return text.includes('Study-docs') && text.includes('Guided Tour') && (text.includes('공식문서') || text.includes('Official'));
    }}, null, {{ timeout: 90000 }});
    await page.waitForTimeout(250);
    const answerText = await page.locator('.course-chat-answer').innerText();
    const artifactCount = await page.locator('.course-chat-artifact').count();
    const routeCardCount = await page.locator('.course-chat-artifact-card.route').count();
    const officialCardCount = await page.locator('.course-chat-artifact-card.official').count();
    const imageCards = await page.locator('.course-chat-artifact-card.image').count();
    const images = await page.locator('.course-chat-artifact-card.image img').evaluateAll(imgs => imgs.map(img => ({{
      src: img.getAttribute('src'),
      complete: img.complete,
      nw: img.naturalWidth,
      nh: img.naturalHeight
    }})));
    const badImages = images.filter(i => !i.complete || !i.nw || !i.nh);
    await page.screenshot({{ path: scenario.screenshot_path.replace(/\\\\/g, '/'), fullPage: true }});
    const failures = [];
    if (guidedAskButtonCount < 1) failures.push('missing_guided_ask_card');
    if (!guidedAskAnswerText.includes('Study-docs')) failures.push('guided_card_click_missing_answer');
    if (!guidedAskAnswerText.includes('Guided Tour')) failures.push('guided_card_click_missing_route');
    if (suggestedQueryCount < 1) failures.push('missing_suggested_query_cards');
    if (!answerText.includes('Study-docs')) failures.push('missing_study_docs_section');
    if (!answerText.includes('공식문서') && !answerText.includes('Official')) failures.push('missing_official_section');
    if (!answerText.includes('Guided Tour')) failures.push('missing_guided_tour_answer');
    if (artifactCount < 2) failures.push('too_few_artifacts');
    if (badImages.length) failures.push('bad_images');
    results.push({{
      id: scenario.id,
      category: scenario.category,
      stage_id: scenario.stage_id,
      passed: failures.length === 0,
      failures,
      answerLength: answerText.length,
      artifactCount,
      routeCardCount,
      officialCardCount,
      guidedAskButtonCount,
      suggestedQueryCount,
      imageCards,
      imageCount: images.length,
      badImages: badImages.length,
      screenshot_path: scenario.screenshot_path
    }});
  }}
  const failed = results.filter(result => !result.passed);
  return {{
    schema: {json.dumps(REPORT_SCHEMA)},
    scenarioCount: results.length,
    passed: results.length - failed.length,
    failedCount: failed.length,
    totalImages: results.reduce((sum, result) => sum + result.imageCount, 0),
    totalBadImages: results.reduce((sum, result) => sum + result.badImages, 0),
    failed,
    results
  }};
}}
"""
        run_result = _run_playwright([playwright_cmd, "--session", session, "run-code", script])
        raw_log_path = output_dir / "course_ui_smoke_raw.log"
        raw_log_path.write_text(run_result.stdout + ("\n" + run_result.stderr if run_result.stderr else ""), encoding="utf-8")
        if run_result.returncode != 0:
            raise RuntimeError(run_result.stderr or run_result.stdout or "course UI smoke failed")
        report = _extract_playwright_result(run_result.stdout)
        (output_dir / "course_ui_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        server.shutdown()
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Playwright smoke checks against the built Course UI.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/playwright/course-ui-smoke"))
    parser.add_argument("--scenario-count", type=int, default=12)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session", default="course-ui-smoke")
    parser.add_argument("--playwright-cmd", default="playwright-cli")
    return parser


def main() -> int:
    args = build_parser().parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())
