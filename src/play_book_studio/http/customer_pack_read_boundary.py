"""customer-pack read surface fail-close helpers."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary


CUSTOMER_PACK_CAPTURE_API_PREFIX = "/api/customer-packs/captured"
CUSTOMER_PACK_VIEWER_PREFIX = "/playbooks/customer-packs/"
PRIVATE_READ_PLACEHOLDER_VALUES = {
    "tenant_id": {"", "default-tenant"},
    "workspace_id": {"", "default-workspace"},
}
PRIVATE_READ_ALLOWED_APPROVAL_STATES = {"approved"}
LOCAL_CUSTOMER_PACK_TENANT_ID = "tenant-user-library-local"
LOCAL_CUSTOMER_PACK_WORKSPACE_ID = "workspace-user-library-local"

_DRAFT_ROUTE_DROP_FIELDS = {
    "request",
    "plan",
    "source_uri",
    "acquisition_uri",
    "uploaded_file_path",
    "canonical_book_path",
    "private_corpus_manifest_path",
    "source_fingerprint",
    "parser_route",
    "parser_version",
    "extraction_confidence",
    "degraded_pdf",
    "degraded_reason",
    "fallback_backend",
    "fallback_status",
    "fallback_reason",
    "quality_score",
    "quality_flags",
    "capture_error",
    "normalize_error",
}
_BOOK_ROUTE_DROP_FIELDS = {
    "source_uri",
    "source_fingerprint",
    "parser_route",
    "parser_version",
    "extraction_confidence",
    "degraded_pdf",
    "degraded_reason",
    "fallback_backend",
    "fallback_status",
    "fallback_reason",
    "quality_score",
    "quality_flags",
    "customer_pack_evidence",
}
_SOURCE_META_ALLOWED_FIELDS = {
    "book_slug",
    "book_title",
    "anchor",
    "section",
    "section_path",
    "section_path_label",
    "source_url",
    "viewer_path",
    "section_match_exact",
    "source_collection",
    "pack_label",
    "source_lane",
    "approval_state",
    "publication_state",
    "parser_backend",
    "boundary_truth",
    "runtime_truth_label",
    "boundary_badge",
    "quality_status",
    "fallback_used",
}
_DEBUG_RUNTIME_DROP_FIELDS = {
    "artifacts_dir",
    "source_manifest_path",
    "normalized_docs_path",
    "bm25_corpus_path",
    "customer_pack_books_dir",
}
_DEBUG_AUDIT_DROP_FIELDS = {
    "snapshot_path",
    "recent_session_path",
}
_PRIVATE_CORPUS_DROP_FIELDS = {
    "manifest_path",
    "vector_error",
    "materialization_error",
    "boundary_fail_reasons",
}


def customer_pack_draft_id_from_viewer_path(viewer_path: str) -> str | None:
    parsed = urlparse(str(viewer_path or "").strip())
    path = parsed.path.strip()
    if not path.startswith(CUSTOMER_PACK_VIEWER_PREFIX):
        return None
    remainder = path.removeprefix(CUSTOMER_PACK_VIEWER_PREFIX).strip("/")
    parts = [part for part in remainder.split("/") if part]
    if len(parts) >= 2 and parts[1] in {"index.html", "assets"}:
        return str(parts[0]).strip() or None
    if parts:
        return str(parts[0]).strip() or None
    return None


def customer_pack_draft_id_from_capture_url(source_url: str) -> str | None:
    parsed = urlparse(str(source_url or "").strip())
    if parsed.path.strip() != CUSTOMER_PACK_CAPTURE_API_PREFIX:
        return None
    values = parse_qs(parsed.query or "", keep_blank_values=False).get("draft_id") or []
    draft_id = str(values[0] if values else "").strip()
    return draft_id or None


def summarize_customer_pack_read_boundary(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {
            "ok": False,
            "read_allowed": False,
            "approval_ready": False,
            "placeholder_security_fields": [],
            "fail_reasons": ["draft_missing"],
            "draft_id": "",
            "tenant_id": "",
            "workspace_id": "",
            "approval_state": "",
            "publication_state": "",
            "manifest_present": False,
        }

    tenant_id = str(getattr(record, "tenant_id", "") or "").strip()
    workspace_id = str(getattr(record, "workspace_id", "") or "").strip()
    approval_state = str(getattr(record, "approval_state", "") or "").strip()
    publication_state = str(getattr(record, "publication_state", "") or "").strip()
    placeholder_security_fields = [
        field_name
        for field_name, placeholder_values in PRIVATE_READ_PLACEHOLDER_VALUES.items()
        if str(getattr(record, field_name, "") or "").strip() in placeholder_values
    ]
    approval_ready = approval_state in PRIVATE_READ_ALLOWED_APPROVAL_STATES
    fail_reasons: list[str] = []
    if placeholder_security_fields:
        fail_reasons.extend(
            f"placeholder_{field_name}" for field_name in placeholder_security_fields
        )
    if not approval_ready:
        fail_reasons.append(f"approval_not_read_ready:{approval_state or 'missing'}")
    if not publication_state:
        fail_reasons.append("publication_state_missing")

    manifest_present = False
    manifest_path = Path(str(getattr(record, "private_corpus_manifest_path", "") or "").strip())
    if manifest_path.as_posix() not in {"", "."} and manifest_path.exists():
        manifest_present = True
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_summary = summarize_private_runtime_boundary(manifest)
        if not bool(manifest_summary.get("runtime_eligible", False)):
            fail_reasons.extend(
                f"private_manifest:{reason}"
                for reason in (manifest_summary.get("fail_reasons") or [])
                if str(reason).strip()
            )

    deduped_fail_reasons: list[str] = []
    seen: set[str] = set()
    for reason in fail_reasons:
        normalized_reason = str(reason).strip()
        if not normalized_reason or normalized_reason in seen:
            continue
        seen.add(normalized_reason)
        deduped_fail_reasons.append(normalized_reason)

    read_allowed = not deduped_fail_reasons
    return {
        "ok": read_allowed,
        "read_allowed": read_allowed,
        "approval_ready": approval_ready,
        "placeholder_security_fields": placeholder_security_fields,
        "fail_reasons": deduped_fail_reasons,
        "draft_id": str(getattr(record, "draft_id", "") or "").strip(),
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "approval_state": approval_state,
        "publication_state": publication_state,
        "manifest_present": manifest_present,
    }


def _record_source_collection(record: Any) -> str:
    plan = getattr(record, "plan", None)
    return str(getattr(plan, "source_collection", "") or "").strip()


def _is_local_uploaded_customer_pack(record: Any | None) -> bool:
    if record is None:
        return False
    source_collection = _record_source_collection(record)
    source_lane = str(getattr(record, "source_lane", "") or "").strip()
    classification = str(getattr(record, "classification", "") or "").strip()
    provider_egress_policy = str(getattr(record, "provider_egress_policy", "") or "").strip()
    return (
        source_collection == "uploaded"
        and source_lane in {"", "customer_source_first_pack"}
        and classification in {"", "private"}
        and provider_egress_policy in {"", "local_only"}
    )


def _placeholder_field_names(record: Any) -> list[str]:
    return [
        field_name
        for field_name, placeholder_values in PRIVATE_READ_PLACEHOLDER_VALUES.items()
        if str(getattr(record, field_name, "") or "").strip() in placeholder_values
    ]


def _rewrite_private_manifest_runtime_boundary(
    manifest_path: Path,
    *,
    tenant_id: str,
    workspace_id: str,
    access_groups: tuple[str, ...],
    approval_state: str,
    publication_state: str,
) -> None:
    if manifest_path.as_posix() in {"", "."} or not manifest_path.exists():
        return
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if not isinstance(payload, dict):
        return
    payload["tenant_id"] = tenant_id
    payload["workspace_id"] = workspace_id
    payload["access_groups"] = list(access_groups)
    payload["approval_state"] = approval_state
    payload["publication_state"] = publication_state
    boundary_summary = summarize_private_runtime_boundary(payload)
    payload["runtime_eligible"] = bool(boundary_summary.get("runtime_eligible", False))
    payload["boundary_fail_reasons"] = list(boundary_summary.get("fail_reasons") or [])
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _repair_local_uploaded_customer_pack_record(root_dir: Path, record: Any | None) -> Any | None:
    if not _is_local_uploaded_customer_pack(record):
        return record
    placeholder_fields = set(_placeholder_field_names(record))
    approval_state = str(getattr(record, "approval_state", "") or "").strip()
    publication_state = str(getattr(record, "publication_state", "") or "").strip()
    needs_repair = bool(placeholder_fields) or approval_state in {"", "unreviewed"}
    if not needs_repair:
        return record

    tenant_id = (
        LOCAL_CUSTOMER_PACK_TENANT_ID
        if "tenant_id" in placeholder_fields
        else str(getattr(record, "tenant_id", "") or "").strip()
    )
    workspace_id = (
        LOCAL_CUSTOMER_PACK_WORKSPACE_ID
        if "workspace_id" in placeholder_fields
        else str(getattr(record, "workspace_id", "") or "").strip()
    )
    repaired_approval_state = approval_state if approval_state and approval_state != "unreviewed" else "approved"
    repaired_publication_state = publication_state or "draft"
    repaired_access_groups = tuple(
        item
        for item in (
            workspace_id,
            tenant_id,
        )
        if item
    )

    setattr(record, "tenant_id", tenant_id)
    setattr(record, "workspace_id", workspace_id)
    setattr(record, "access_groups", repaired_access_groups)
    setattr(record, "approval_state", repaired_approval_state)
    setattr(record, "publication_state", repaired_publication_state)
    CustomerPackDraftStore(root_dir).save(record)

    manifest_path = Path(str(getattr(record, "private_corpus_manifest_path", "") or "").strip())
    _rewrite_private_manifest_runtime_boundary(
        manifest_path,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        access_groups=repaired_access_groups,
        approval_state=repaired_approval_state,
        publication_state=repaired_publication_state,
    )
    return record


def load_customer_pack_read_boundary(root_dir: Path, draft_id: str) -> dict[str, Any]:
    record = CustomerPackDraftStore(root_dir).get(str(draft_id or "").strip())
    record = _repair_local_uploaded_customer_pack_record(root_dir, record)
    return summarize_customer_pack_read_boundary(record)


def sanitize_customer_pack_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        key: value
        for key, value in dict(payload).items()
        if key not in _DRAFT_ROUTE_DROP_FIELDS
    }
    draft_id = str(sanitized.get("draft_id") or "").strip()
    if draft_id and sanitized.get("capture_artifact_path"):
        sanitized["capture_artifact_path"] = f"{CUSTOMER_PACK_CAPTURE_API_PREFIX}?draft_id={draft_id}"
    elif "capture_artifact_path" in sanitized:
        sanitized["capture_artifact_path"] = ""
    if "private_corpus" in sanitized and isinstance(sanitized["private_corpus"], dict):
        sanitized["private_corpus"] = sanitize_customer_pack_private_corpus_payload(
            sanitized["private_corpus"]
        )
    return sanitized


def sanitize_customer_pack_private_corpus_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload).items()
        if key not in _PRIVATE_CORPUS_DROP_FIELDS
    }


def sanitize_customer_pack_mutation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_customer_pack_draft_payload(payload)
    if "book" in sanitized and isinstance(sanitized["book"], dict):
        sanitized["book"] = sanitize_customer_pack_book_payload(sanitized["book"])
    if "private_corpus" in sanitized and isinstance(sanitized["private_corpus"], dict):
        sanitized["private_corpus"] = sanitize_customer_pack_private_corpus_payload(
            sanitized["private_corpus"]
        )
    return sanitized


def sanitize_customer_pack_book_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        key: value
        for key, value in dict(payload).items()
        if key not in _BOOK_ROUTE_DROP_FIELDS
    }
    source_origin_url = str(sanitized.get("source_origin_url") or "").strip()
    sanitized["source_uri"] = source_origin_url
    sections = []
    for section in sanitized.get("sections") or []:
        if not isinstance(section, dict):
            continue
        normalized = dict(section)
        normalized["source_url"] = source_origin_url
        sections.append(normalized)
    sanitized["sections"] = sections
    return sanitized


def sanitize_customer_pack_source_meta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in dict(payload).items()
        if key in _SOURCE_META_ALLOWED_FIELDS
    }


def extract_customer_pack_draft_ids_from_payload(payload: Any) -> set[str]:
    draft_ids: set[str] = set()

    def _maybe_add_candidate(value: Any) -> None:
        candidate = str(value or "").strip()
        if not candidate:
            return
        from_viewer = customer_pack_draft_id_from_viewer_path(candidate)
        if from_viewer:
            draft_ids.add(from_viewer)
            return
        from_capture = customer_pack_draft_id_from_capture_url(candidate)
        if from_capture:
            draft_ids.add(from_capture)

    def _visit(node: Any) -> None:
        if isinstance(node, dict):
            direct_draft_id = str(node.get("draft_id") or "").strip()
            if direct_draft_id:
                draft_ids.add(direct_draft_id.split("::", 1)[0])
            for key, value in node.items():
                if key in {
                    "viewer_path",
                    "source_url",
                    "source_origin_url",
                    "href",
                }:
                    _maybe_add_candidate(value)
                elif key == "selected_draft_ids" and isinstance(value, list):
                    for item in value:
                        direct_value = str(item or "").strip()
                        if direct_value:
                            draft_ids.add(direct_value.split("::", 1)[0])
                _visit(value)
            return
        if isinstance(node, list):
            for item in node:
                _visit(item)
            return
        if isinstance(node, str):
            _maybe_add_candidate(node)

    _visit(payload)
    return draft_ids


def blocked_customer_pack_draft_ids_from_payload(root_dir: Path, payload: Any) -> tuple[str, ...]:
    blocked: list[str] = []
    for draft_id in sorted(extract_customer_pack_draft_ids_from_payload(payload)):
        summary = load_customer_pack_read_boundary(root_dir, draft_id)
        if not bool(summary.get("read_allowed", False)):
            blocked.append(draft_id)
    return tuple(blocked)


def sanitize_debug_chat_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(entry)
    sanitized.pop("path", None)
    audit_envelope = sanitized.get("audit_envelope")
    if isinstance(audit_envelope, dict):
        for field_name in _DEBUG_AUDIT_DROP_FIELDS:
            audit_envelope.pop(field_name, None)
    runtime = sanitized.get("runtime")
    if isinstance(runtime, dict):
        for field_name in _DEBUG_RUNTIME_DROP_FIELDS:
            runtime.pop(field_name, None)
    return sanitized


__all__ = [
    "blocked_customer_pack_draft_ids_from_payload",
    "customer_pack_draft_id_from_capture_url",
    "customer_pack_draft_id_from_viewer_path",
    "load_customer_pack_read_boundary",
    "sanitize_customer_pack_book_payload",
    "sanitize_customer_pack_draft_payload",
    "sanitize_customer_pack_mutation_payload",
    "sanitize_customer_pack_private_corpus_payload",
    "sanitize_customer_pack_source_meta_payload",
    "sanitize_debug_chat_log_entry",
    "summarize_customer_pack_read_boundary",
]
