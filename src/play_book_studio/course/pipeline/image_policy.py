from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .common import normalize_text

SUCCESS_STATES = [
    "Running",
    "Ready",
    "Succeeded",
    "Success",
    "Successful",
    "Available",
    "Completed",
    "Complete",
    "Healthy",
    "Bound",
]

FAILURE_STATES = [
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "Failed",
    "Error",
    "Degraded",
    "Unavailable",
    "Exception",
    "Back-off",
]

PROGRESS_STATES = [
    "Running",
    "Progressing",
    "Pending",
    "Waiting",
    "Deploying",
    "Syncing",
    "PipelineRun",
    "PLR",
]

DASHBOARD_TERMS = ["Grafana", "Jennifer", "Prometheus", "Monitoring", "Metrics", "dashboard", "chart", "graph", "latency", "throughput"]
CONSOLE_TERMS = ["oc ", "kubectl", "pod", "deployment", "namespace", "CLI", "Web Console", "Workloads", "Pipelines", "ArgoCD", "GitLab"]
COMMAND_TERMS = ["# oc", " oc ", "kubectl", "curl", "ssh ", "sudo ", "apply -f", "get pod", "get node", "patch deployment"]
UI_TERMS = ["Web Console", "Workloads", "Administrator", "Developer", "Topology", "YAML", "메뉴", "화면", "클릭"]
EMPTY_VISUAL_TERMS = [
    "no text",
    "no visible",
    "blank",
    "solid color",
    "텍스트가 없",
    "시각적 요소를 확인할 수 없",
    "가시적인 객체가 전혀 보이지",
]
EVIDENCE_TEXT_TERMS = [
    "terminal",
    "console",
    "log",
    "error",
    "failed",
    "exception",
    "build failed",
    "cannot find",
    "oc ",
    "kubectl",
    "pod",
    "status",
    "ready",
    "running",
    "succeeded",
    "crashloopbackoff",
    "로그",
    "터미널",
    "콘솔",
    "오류",
    "실패",
    "상태",
]


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _has_evidence_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return _contains_any(normalized, EVIDENCE_TEXT_TERMS)


def _first_state_signal(text: str) -> str:
    for state in [*FAILURE_STATES, *SUCCESS_STATES, *PROGRESS_STATES]:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(state)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
            return state
    return ""


def _chunk_context_text(chunk: dict[str, Any]) -> str:
    structured = chunk.get("structured") if isinstance(chunk.get("structured"), dict) else {}
    structured_parts: list[str] = []
    for key in ("method", "expected", "verification", "steps", "commands", "result", "summary"):
        value = structured.get(key)
        if isinstance(value, list):
            structured_parts.extend(str(item) for item in value)
        elif value is not None:
            structured_parts.append(str(value))
    return "\n".join(
        part
        for part in [
            str(chunk.get("title") or ""),
            str(chunk.get("body_md") or ""),
            str(chunk.get("search_text") or ""),
            str(chunk.get("visual_text") or ""),
            "\n".join(structured_parts),
            str(chunk.get("chunk_kind") or ""),
            str(chunk.get("stage_id") or ""),
        ]
        if normalize_text(part)
    )


def _attachment_text(attachment: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            str(attachment.get("ocr_text") or ""),
            str(attachment.get("caption_text") or ""),
            str(attachment.get("visual_summary") or ""),
            str(attachment.get("role") or ""),
            str(attachment.get("kind") or ""),
        ]
        if normalize_text(part)
    )


def _bbox_quality_label(attachment: dict[str, Any], text: str) -> str:
    if normalize_text(text) and _contains_any(text, EMPTY_VISUAL_TERMS) and not _first_state_signal(text) and not _has_evidence_text(text):
        return "blank_or_solid"
    bbox = attachment.get("bbox_norm") if isinstance(attachment.get("bbox_norm"), list) else []
    if len(bbox) == 4:
        try:
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
        except (TypeError, ValueError):
            width = 0.0
            height = 0.0
        area = width * height
        if area <= 0.0005 and not normalize_text(text):
            return "blank_or_solid"
        if area < 0.01:
            return "tiny_strip_or_icon"
        if width > 0.65 and height < 0.12:
            return "very_wide_strip"
    if not normalize_text(text):
        return "low_signal_image"
    return "informative"


def _asset_sha256(attachment: dict[str, Any], root_dir: Path | None) -> str:
    blob = attachment.get("_blob")
    if isinstance(blob, (bytes, bytearray)):
        return hashlib.sha256(bytes(blob)).hexdigest()
    asset_path = normalize_text(str(attachment.get("asset_path") or ""))
    if not asset_path or root_dir is None:
        return ""
    path = Path(asset_path)
    if not path.is_absolute():
        path = root_dir / path
    try:
        if path.exists() and path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    return ""


def _instructional_roles(*, chunk: dict[str, Any], attachment: dict[str, Any], state_signal: str, quality_label: str) -> list[str]:
    attachment_text = _attachment_text(attachment)
    context_text = _chunk_context_text(chunk)
    combined = f"{context_text}\n{attachment_text}"
    roles: list[str] = []
    raw_role = normalize_text(str(attachment.get("role") or ""))

    if quality_label == "blank_or_solid":
        return ["decorative_or_empty"]

    if raw_role in {"main_diagram", "sub_diagram", "diagram"} or _contains_any(attachment_text, ["아키텍처", "구성도", "흐름도", "diagram"]):
        roles.append("diagram")
    if _contains_any(attachment_text, ["|", "Table", "표", "Name", "Status", "Ready", "Restarts"]):
        roles.append("table")
    if _contains_any(attachment_text, DASHBOARD_TERMS):
        roles.append("dashboard_metric")
    if _contains_any(combined, CONSOLE_TERMS) or re.search(r"\b(?:INFO|WARN|ERROR|DEBUG)\b", attachment_text):
        roles.append("console_output")
    if _contains_any(combined, COMMAND_TERMS) or _contains_any(context_text, ["CLI", "명령", "확인", "검증"]):
        if normalize_text(attachment_text):
            roles.append("command_result_evidence")
    if state_signal:
        roles.append("expected_state_indicator")
        if state_signal in FAILURE_STATES:
            roles.append("failure_state")
        if state_signal in SUCCESS_STATES:
            roles.append("success_state")
        if state_signal in PROGRESS_STATES:
            roles.append("progress_state")
    if _contains_any(combined, UI_TERMS):
        roles.append("ui_navigation_evidence")
    if quality_label in {"blank_or_solid", "low_signal_image"} and not roles:
        roles.append("decorative_or_empty")

    ordered: list[str] = []
    for role in roles:
        if role not in ordered:
            ordered.append(role)
    return ordered or ["evidence_image"]


def _primary_role(roles: list[str]) -> str:
    priority = [
        "failure_state",
        "command_result_evidence",
        "expected_state_indicator",
        "success_state",
        "progress_state",
        "console_output",
        "dashboard_metric",
        "diagram",
        "table",
        "ui_navigation_evidence",
        "decorative_or_empty",
    ]
    for role in priority:
        if role in roles:
            return role
    return roles[0] if roles else "evidence_image"


def _rank_profiles(roles: list[str], quality_label: str, evidence_strength: float) -> dict[str, float]:
    concept = 0.25
    procedure = 0.25
    troubleshooting = 0.25
    if "diagram" in roles:
        concept = max(concept, 0.9)
    if "table" in roles:
        concept = max(concept, 0.72)
        procedure = max(procedure, 0.55)
    if "dashboard_metric" in roles:
        concept = max(concept, 0.65)
        procedure = max(procedure, 0.7)
        troubleshooting = max(troubleshooting, 0.8)
    if "command_result_evidence" in roles:
        procedure = max(procedure, 0.88)
    if "expected_state_indicator" in roles or "success_state" in roles or "progress_state" in roles:
        procedure = max(procedure, 0.9)
    if "failure_state" in roles or "console_output" in roles:
        troubleshooting = max(troubleshooting, 0.9)
    if "ui_navigation_evidence" in roles:
        procedure = max(procedure, 0.78)
    if quality_label in {"tiny_strip_or_icon", "very_wide_strip"} and not {"command_result_evidence", "expected_state_indicator", "failure_state"} & set(roles):
        concept *= 0.55
    if "decorative_or_empty" in roles:
        concept = procedure = troubleshooting = 0.05
    return {
        "concept": round(min(max(concept, evidence_strength * 0.25), 1.0), 2),
        "procedure": round(min(max(procedure, evidence_strength * 0.35), 1.0), 2),
        "troubleshooting": round(min(max(troubleshooting, evidence_strength * 0.35), 1.0), 2),
    }


def _evidence_strength(chunk: dict[str, Any], attachment: dict[str, Any], roles: list[str], quality_label: str) -> float:
    text = normalize_text(_attachment_text(attachment))
    context = normalize_text(_chunk_context_text(chunk))
    score = 0.35
    if text:
        score += 0.18
    if len(text) > 80:
        score += 0.1
    if _contains_any(context, ["확인", "검증", "기대", "expected", "verification", "CLI", "Web Console", "명령"]):
        score += 0.14
    if {"command_result_evidence", "expected_state_indicator", "failure_state", "dashboard_metric"} & set(roles):
        score += 0.2
    if "diagram" in roles:
        score += 0.12
    if quality_label == "blank_or_solid":
        score = min(score, 0.1)
    if quality_label == "low_signal_image":
        score = min(score, 0.28)
    return round(min(score, 0.98), 2)


def apply_image_policy_to_chunk(chunk: dict[str, Any], *, root_dir: Path | None = None) -> dict[str, Any]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    sha_seen: dict[str, str] = {}
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            continue
        text = _attachment_text(attachment)
        state_signal = _first_state_signal(text)
        quality_label = _bbox_quality_label(attachment, text)
        roles = _instructional_roles(chunk=chunk, attachment=attachment, state_signal=state_signal, quality_label=quality_label)
        primary = _primary_role(roles)
        evidence_strength = _evidence_strength(chunk, attachment, roles, quality_label)
        rank_profiles = _rank_profiles(roles, quality_label, evidence_strength)
        sha256 = _asset_sha256(attachment, root_dir)
        dedupe_group_id = f"sha256:{sha256}" if sha256 else ""
        duplicate_of = sha_seen.get(dedupe_group_id, "") if dedupe_group_id else ""
        if dedupe_group_id and dedupe_group_id not in sha_seen:
            sha_seen[dedupe_group_id] = str(attachment.get("asset_id") or "")

        attachment["quality_label"] = quality_label
        attachment["instructional_role"] = primary
        attachment["instructional_roles"] = roles
        attachment["state_signal"] = state_signal
        attachment["evidence_strength"] = evidence_strength
        attachment["rank_profiles"] = rank_profiles
        attachment["dedupe_group_id"] = dedupe_group_id
        attachment["duplicate_of_asset_id"] = duplicate_of
        attachment["sha256"] = sha256
        attachment["exclude_from_default"] = quality_label == "blank_or_solid" or primary == "decorative_or_empty" or bool(duplicate_of)
        priority = max(rank_profiles.values()) + evidence_strength
        scored.append((priority, index, attachment))

    scored.sort(key=lambda item: (-item[0], item[1]))
    visible_count = 0
    for order, (_, _, attachment) in enumerate(scored, start=1):
        if attachment.get("exclude_from_default"):
            attachment["is_default_visible"] = False
            attachment["default_visible_order"] = 0
            continue
        visible_count += 1
        attachment["is_default_visible"] = visible_count <= 5
        attachment["default_visible_order"] = visible_count if visible_count <= 5 else 0
        attachment["image_rank_order"] = order
    chunk["image_attachments"] = attachments
    return chunk


def apply_image_policy_to_chunks(chunks: list[dict[str, Any]], *, root_dir: Path | None = None) -> list[dict[str, Any]]:
    return [apply_image_policy_to_chunk(chunk, root_dir=root_dir) for chunk in chunks]


__all__ = ["apply_image_policy_to_chunk", "apply_image_policy_to_chunks"]
