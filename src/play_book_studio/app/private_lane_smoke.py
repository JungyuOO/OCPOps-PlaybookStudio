from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL
from play_book_studio.config.settings import load_settings
from play_book_studio.intake.private_boundary import (
    PRIVATE_RUNTIME_REQUIRED_BOUNDARY_FIELDS,
    PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS,
    summarize_private_runtime_boundary,
)

PRIVATE_LANE_REQUIRED_SECURITY_FIELDS = PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS
PRIVATE_LANE_REQUIRED_BOUNDARY_FIELDS = PRIVATE_RUNTIME_REQUIRED_BOUNDARY_FIELDS

PRIVATE_LANE_QUERY_TEMPLATE = "{token} 문서를 보여줘"
PRIVATE_LANE_SOURCE_TITLE = "Private Lane Smoke"


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_json(response: requests.Response) -> dict[str, Any] | list[Any] | str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return response.text[:1000]
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return payload
    return str(payload)


def _default_source_markdown(token: str) -> str:
    return (
        "# Private Lane Smoke\n\n"
        "## ConfigMap Secret\n\n"
        f"{token} 는 user upload private lane smoke 검증용 고유 토큰입니다.\n\n"
        "ConfigMap Secret values must be synchronized before rollout.\n"
    )


def _write_source_markdown(
    root_dir: str | Path,
    *,
    token: str,
    source_markdown: str | None,
) -> Path:
    settings = load_settings(root_dir)
    smoke_dir = settings.root_dir / "reports" / "build_logs" / "_private_lane_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    path = smoke_dir / f"private_lane_smoke_{token}.md"
    path.write_text(
        str(source_markdown or _default_source_markdown(token)),
        encoding="utf-8",
    )
    return path


def summarize_private_lane_boundary(payload: dict[str, Any] | None) -> dict[str, Any]:
    return summarize_private_runtime_boundary(payload)


def _sanitize_private_corpus_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    manifest = dict(payload or {})
    return {
        "artifact_version": str(manifest.get("artifact_version") or "").strip(),
        "draft_id": str(manifest.get("draft_id") or "").strip(),
        "tenant_id": str(manifest.get("tenant_id") or "").strip(),
        "workspace_id": str(manifest.get("workspace_id") or "").strip(),
        "pack_id": str(manifest.get("pack_id") or "").strip(),
        "pack_version": str(manifest.get("pack_version") or "").strip(),
        "classification": str(manifest.get("classification") or "").strip(),
        "access_groups": list(manifest.get("access_groups") or []),
        "provider_egress_policy": str(manifest.get("provider_egress_policy") or "").strip(),
        "approval_state": str(manifest.get("approval_state") or "").strip(),
        "publication_state": str(manifest.get("publication_state") or "").strip(),
        "redaction_state": str(manifest.get("redaction_state") or "").strip(),
        "source_lane": str(manifest.get("source_lane") or "").strip(),
        "source_collection": str(manifest.get("source_collection") or "").strip(),
        "boundary_truth": str(manifest.get("boundary_truth") or "").strip(),
        "runtime_truth_label": str(manifest.get("runtime_truth_label") or "").strip(),
        "boundary_badge": str(manifest.get("boundary_badge") or "").strip(),
        "book_count": int(manifest.get("book_count") or 0),
        "section_count": int(manifest.get("section_count") or 0),
        "chunk_count": int(manifest.get("chunk_count") or 0),
        "bm25_ready": bool(manifest.get("bm25_ready")),
        "vector_status": str(manifest.get("vector_status") or "").strip(),
        "vector_chunk_count": int(manifest.get("vector_chunk_count") or 0),
        "runtime_eligible": bool(manifest.get("runtime_eligible") or False),
        "boundary_fail_reasons": list(manifest.get("boundary_fail_reasons") or []),
        "updated_at": str(manifest.get("updated_at") or "").strip(),
    }


def _sanitize_ingest_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    report_payload = dict(payload or {})
    private_corpus = (
        dict(report_payload.get("private_corpus", {}))
        if isinstance(report_payload.get("private_corpus"), dict)
        else {}
    )
    return {
        "draft_id": str(report_payload.get("draft_id") or "").strip(),
        "status": str(report_payload.get("status") or "").strip(),
        "source_type": str(report_payload.get("source_type") or "").strip(),
        "title": str(report_payload.get("title") or "").strip(),
        "source_collection": str(report_payload.get("source_collection") or "").strip(),
        "pack_id": str(report_payload.get("pack_id") or "").strip(),
        "pack_label": str(report_payload.get("pack_label") or "").strip(),
        "approval_state": str(report_payload.get("approval_state") or "").strip(),
        "publication_state": str(report_payload.get("publication_state") or "").strip(),
        "playable_asset_count": int(report_payload.get("playable_asset_count") or 0),
        "derived_asset_count": int(report_payload.get("derived_asset_count") or 0),
        "private_corpus": _sanitize_private_corpus_payload(private_corpus),
    }


def _private_citation_summary(
    payload: dict[str, Any] | None,
    *,
    draft_id: str,
) -> dict[str, Any]:
    response_payload = dict(payload or {})
    citations = [
        dict(item)
        for item in (response_payload.get("citations") or [])
        if isinstance(item, dict)
    ]
    draft_prefix = f"/playbooks/customer-packs/{draft_id}/"
    private_citations = [
        citation
        for citation in citations
        if str(citation.get("viewer_path") or "").strip().startswith(draft_prefix)
        or str(citation.get("boundary_truth") or "").strip() == "private_customer_pack_runtime"
    ]
    boundary_ok = any(
        str(citation.get("boundary_truth") or "").strip() == "private_customer_pack_runtime"
        and str(citation.get("runtime_truth_label") or "").strip() == "Customer Source-First Pack"
        and str(citation.get("boundary_badge") or "").strip() == "Private Pack Runtime"
        for citation in private_citations
    )
    return {
        "private_hit": bool(private_citations),
        "private_boundary_ok": boundary_ok,
        "private_citations": [
            {
                "book_slug": str(citation.get("book_slug") or "").strip(),
                "viewer_path": str(citation.get("viewer_path") or "").strip(),
                "boundary_truth": str(citation.get("boundary_truth") or "").strip(),
                "runtime_truth_label": str(citation.get("runtime_truth_label") or "").strip(),
                "boundary_badge": str(citation.get("boundary_badge") or "").strip(),
            }
            for citation in private_citations[:2]
        ],
    }


def build_private_lane_smoke(
    root_dir: str | Path,
    *,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    query_template: str = PRIVATE_LANE_QUERY_TEMPLATE,
    source_markdown: str | None = None,
) -> dict[str, Any]:
    base_url = ui_base_url.rstrip("/")
    token = f"private-lane-smoke-{uuid.uuid4().hex[:8]}"
    source_path = _write_source_markdown(root_dir, token=token, source_markdown=source_markdown)
    ingest_report: dict[str, Any] = {
        "base_url": base_url,
        "source_file_name": source_path.name,
        "title": PRIVATE_LANE_SOURCE_TITLE,
        "query": query_template.format(token=token),
    }
    book_report: dict[str, Any] = {}
    viewer_report: dict[str, Any] = {}
    selected_chat_report: dict[str, Any] = {}
    unselected_chat_report: dict[str, Any] = {}
    cleanup_report: dict[str, Any] = {}
    draft_id = ""
    private_corpus_payload: dict[str, Any] = {}
    boundary_summary: dict[str, Any] = {}

    try:
        ingest_response = requests.post(
            f"{base_url}/api/customer-packs/ingest",
            json={
                "source_type": "md",
                "uri": str(source_path),
                "title": PRIVATE_LANE_SOURCE_TITLE,
                "language_hint": "ko",
                "tenant_id": "tenant-private-lane-smoke",
                "workspace_id": "workspace-private-lane-smoke",
                "approval_state": "approved",
                "publication_state": "draft",
            },
            headers={"Content-Type": "application/json"},
            timeout=90,
        )
        ingest_report["status_code"] = ingest_response.status_code
        ingest_payload = _safe_json(ingest_response)
        if isinstance(ingest_payload, dict):
            ingest_report["payload"] = _sanitize_ingest_payload(ingest_payload)
            draft_id = str(ingest_payload.get("draft_id") or "").strip()
            private_corpus_payload = (
                dict(ingest_payload.get("private_corpus", {}))
                if isinstance(ingest_payload.get("private_corpus"), dict)
                else {}
            )
            boundary_summary = summarize_private_lane_boundary(private_corpus_payload)
            ingest_report["private_corpus_boundary"] = boundary_summary
        else:
            ingest_report["payload"] = ingest_payload
            ingest_report["private_corpus_boundary"] = summarize_private_lane_boundary(None)

        if draft_id:
            book_response = requests.get(
                f"{base_url}/api/customer-packs/book",
                params={"draft_id": draft_id},
                timeout=30,
            )
            book_report["status_code"] = book_response.status_code
            book_payload = _safe_json(book_response)
            if isinstance(book_payload, dict):
                book_report["payload"] = {
                    "draft_id": str(book_payload.get("draft_id") or "").strip(),
                    "target_viewer_path": str(book_payload.get("target_viewer_path") or "").strip(),
                    "boundary_truth": str(book_payload.get("boundary_truth") or "").strip(),
                    "runtime_truth_label": str(book_payload.get("runtime_truth_label") or "").strip(),
                    "boundary_badge": str(book_payload.get("boundary_badge") or "").strip(),
                    "section_count": len(book_payload.get("sections") or []),
                }
                target_viewer_path = str(book_payload.get("target_viewer_path") or "").strip()
            else:
                book_report["payload"] = book_payload
                target_viewer_path = ""

            if target_viewer_path:
                viewer_response = requests.get(
                    f"{base_url}/api/viewer-document",
                    params={"viewer_path": target_viewer_path},
                    timeout=30,
                )
                viewer_report["status_code"] = viewer_response.status_code
                viewer_payload = _safe_json(viewer_response)
                if isinstance(viewer_payload, dict):
                    viewer_report["payload"] = {
                        "viewer_path": str(viewer_payload.get("viewer_path") or "").strip(),
                        "html_length": len(str(viewer_payload.get("html") or "")),
                    }
                else:
                    viewer_report["payload"] = viewer_payload

            selected_chat_response = requests.post(
                f"{base_url}/api/chat",
                json={
                    "query": query_template.format(token=token),
                    "selected_draft_ids": [draft_id],
                    "restrict_uploaded_sources": True,
                },
                headers={"Content-Type": "application/json"},
                timeout=90,
            )
            selected_chat_report["status_code"] = selected_chat_response.status_code
            selected_chat_payload = _safe_json(selected_chat_response)
            if isinstance(selected_chat_payload, dict):
                selected_chat_report["payload"] = {
                    "response_kind": str(selected_chat_payload.get("response_kind") or "").strip(),
                    "warnings": list(selected_chat_payload.get("warnings") or []),
                    **_private_citation_summary(selected_chat_payload, draft_id=draft_id),
                }
            else:
                selected_chat_report["payload"] = selected_chat_payload

            unselected_chat_response = requests.post(
                f"{base_url}/api/chat",
                json={
                    "query": query_template.format(token=token),
                    "restrict_uploaded_sources": True,
                },
                headers={"Content-Type": "application/json"},
                timeout=90,
            )
            unselected_chat_report["status_code"] = unselected_chat_response.status_code
            unselected_chat_payload = _safe_json(unselected_chat_response)
            if isinstance(unselected_chat_payload, dict):
                unselected_chat_report["payload"] = {
                    "response_kind": str(unselected_chat_payload.get("response_kind") or "").strip(),
                    "warnings": list(unselected_chat_payload.get("warnings") or []),
                    **_private_citation_summary(unselected_chat_payload, draft_id=draft_id),
                }
            else:
                unselected_chat_report["payload"] = unselected_chat_payload
    finally:
        if draft_id:
            try:
                cleanup_response = requests.post(
                    f"{base_url}/api/customer-packs/delete-draft",
                    json={"draft_id": draft_id},
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )
                cleanup_report["status_code"] = cleanup_response.status_code
                cleanup_report["payload"] = _safe_json(cleanup_response)
            except Exception as exc:  # noqa: BLE001
                cleanup_report["error"] = str(exc)
        source_path.unlink(missing_ok=True)

    ingest_payload = dict(ingest_report.get("payload", {})) if isinstance(ingest_report.get("payload"), dict) else {}
    book_payload = dict(book_report.get("payload", {})) if isinstance(book_report.get("payload"), dict) else {}
    viewer_payload = dict(viewer_report.get("payload", {})) if isinstance(viewer_report.get("payload"), dict) else {}
    selected_chat_payload = (
        dict(selected_chat_report.get("payload", {}))
        if isinstance(selected_chat_report.get("payload"), dict)
        else {}
    )
    unselected_chat_payload = (
        dict(unselected_chat_report.get("payload", {}))
        if isinstance(unselected_chat_report.get("payload"), dict)
        else {}
    )
    cleanup_payload = (
        dict(cleanup_report.get("payload", {}))
        if isinstance(cleanup_report.get("payload"), dict)
        else {}
    )
    ingest_ok = int(ingest_report.get("status_code", 0) or 0) < 400 and bool(ingest_payload)
    private_corpus_ready = (
        bool(private_corpus_payload)
        and bool(private_corpus_payload.get("bm25_ready"))
        and int(private_corpus_payload.get("chunk_count") or 0) > 0
    )
    boundary_fields_complete = bool(boundary_summary.get("ok"))
    book_ok = (
        int(book_report.get("status_code", 0) or 0) < 400
        and bool(book_payload.get("target_viewer_path"))
        and str(book_payload.get("boundary_truth") or "").strip() == "private_customer_pack_runtime"
    )
    viewer_ok = (
        int(viewer_report.get("status_code", 0) or 0) < 400
        and int(viewer_payload.get("html_length") or 0) > 0
    )
    selected_chat_private_hit = bool(selected_chat_payload.get("private_hit"))
    selected_chat_private_boundary = bool(selected_chat_payload.get("private_boundary_ok"))
    no_leak_ok = not bool(unselected_chat_payload.get("private_hit"))
    cleanup_ok = (
        bool(draft_id)
        and int(cleanup_report.get("status_code", 0) or 0) < 400
        and bool(cleanup_payload.get("success"))
    )
    ok = all(
        (
            ingest_ok,
            private_corpus_ready,
            boundary_fields_complete,
            book_ok,
            viewer_ok,
            selected_chat_private_hit,
            selected_chat_private_boundary,
            no_leak_ok,
            cleanup_ok,
        )
    )
    return {
        "generated_at": _iso_timestamp(),
        "smoke": {
            "token": token,
            "source_file_name": source_path.name,
            "draft_id": draft_id,
            "private_corpus_boundary": boundary_summary,
            "private_corpus": _sanitize_private_corpus_payload(private_corpus_payload),
        },
        "probes": {
            "ingest": ingest_report,
            "book": book_report,
            "viewer": viewer_report,
            "selected_chat": selected_chat_report,
            "unselected_chat": unselected_chat_report,
            "cleanup": cleanup_report,
        },
        "summary": {
            "ok": ok,
            "ingest_ok": ingest_ok,
            "private_corpus_ready": private_corpus_ready,
            "boundary_fields_complete": boundary_fields_complete,
            "book_ok": book_ok,
            "viewer_ok": viewer_ok,
            "selected_chat_private_hit": selected_chat_private_hit,
            "selected_chat_private_boundary": selected_chat_private_boundary,
            "no_leak_ok": no_leak_ok,
            "cleanup_ok": cleanup_ok,
        },
    }


def write_private_lane_smoke(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    query_template: str = PRIVATE_LANE_QUERY_TEMPLATE,
    source_markdown: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    settings = load_settings(root_dir)
    payload = build_private_lane_smoke(
        root_dir,
        ui_base_url=ui_base_url,
        query_template=query_template,
        source_markdown=source_markdown,
    )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else settings.root_dir / "reports" / "build_logs" / "private_lane_smoke.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target, payload


__all__ = [
    "PRIVATE_LANE_QUERY_TEMPLATE",
    "PRIVATE_LANE_REQUIRED_BOUNDARY_FIELDS",
    "PRIVATE_LANE_REQUIRED_SECURITY_FIELDS",
    "build_private_lane_smoke",
    "summarize_private_lane_boundary",
    "write_private_lane_smoke",
]
