from __future__ import annotations

from typing import Any


PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS = (
    "tenant_id",
    "workspace_id",
    "pack_id",
    "pack_version",
    "classification",
    "access_groups",
    "provider_egress_policy",
    "approval_state",
    "publication_state",
    "redaction_state",
)
PRIVATE_RUNTIME_REQUIRED_BOUNDARY_FIELDS = (
    "boundary_truth",
    "runtime_truth_label",
    "boundary_badge",
)
PRIVATE_RUNTIME_PLACEHOLDER_VALUES = {
    "tenant_id": {"default-tenant"},
    "workspace_id": {"default-workspace"},
}
PRIVATE_RUNTIME_PLACEHOLDER_ACCESS_GROUPS = {"default-tenant", "default-workspace"}
PRIVATE_REMOTE_OCR_ALLOWED_PROVIDER_EGRESS_POLICIES = {
    "allow_remote_ocr",
    "surya_remote_ocr",
    "trusted_private_ocr",
}


def summarize_private_runtime_boundary(payload: dict[str, Any] | None) -> dict[str, Any]:
    manifest = dict(payload or {})
    missing_security_fields = [
        field_name
        for field_name in PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS
        if not _has_value(manifest.get(field_name))
    ]
    missing_boundary_fields = [
        field_name
        for field_name in PRIVATE_RUNTIME_REQUIRED_BOUNDARY_FIELDS
        if not str(manifest.get(field_name) or "").strip()
    ]
    placeholder_security_fields = _placeholder_security_fields(manifest)
    boundary_truth = str(manifest.get("boundary_truth") or "").strip()
    runtime_truth_label = str(manifest.get("runtime_truth_label") or "").strip()
    boundary_badge = str(manifest.get("boundary_badge") or "").strip()
    approval_state = str(manifest.get("approval_state") or "").strip()
    boundary_truth_ok = boundary_truth == "private_customer_pack_runtime"
    runtime_truth_ok = runtime_truth_label == "Customer Source-First Pack"
    boundary_badge_ok = boundary_badge == "Private Pack Runtime"
    approval_ready = approval_state == "approved"
    runtime_eligible = (
        not missing_security_fields
        and not missing_boundary_fields
        and not placeholder_security_fields
        and boundary_truth_ok
        and runtime_truth_ok
        and boundary_badge_ok
        and approval_ready
    )
    fail_reasons: list[str] = []
    fail_reasons.extend(f"missing_security:{field_name}" for field_name in missing_security_fields)
    fail_reasons.extend(f"missing_boundary:{field_name}" for field_name in missing_boundary_fields)
    fail_reasons.extend(f"placeholder:{field_name}" for field_name in placeholder_security_fields)
    if not boundary_truth_ok:
        fail_reasons.append("invalid_boundary_truth")
    if not runtime_truth_ok:
        fail_reasons.append("invalid_runtime_truth_label")
    if not boundary_badge_ok:
        fail_reasons.append("invalid_boundary_badge")
    if not approval_ready:
        fail_reasons.append(f"approval_not_runtime_ready:{approval_state or 'missing'}")
    return {
        "ok": runtime_eligible,
        "runtime_eligible": runtime_eligible,
        "approval_ready": approval_ready,
        "missing_security_fields": missing_security_fields,
        "missing_boundary_fields": missing_boundary_fields,
        "placeholder_security_fields": placeholder_security_fields,
        "boundary_truth_ok": boundary_truth_ok,
        "runtime_truth_ok": runtime_truth_ok,
        "boundary_badge_ok": boundary_badge_ok,
        "fail_reasons": fail_reasons,
    }


def summarize_private_remote_ocr_boundary(payload: dict[str, Any] | None) -> dict[str, Any]:
    manifest = dict(payload or {})
    missing_security_fields = [
        field_name
        for field_name in PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS
        if not _has_value(manifest.get(field_name))
    ]
    placeholder_security_fields = _placeholder_security_fields(manifest)
    approval_state = str(manifest.get("approval_state") or "").strip()
    publication_state = str(manifest.get("publication_state") or "").strip()
    provider_egress_policy = str(manifest.get("provider_egress_policy") or "").strip()
    redaction_state = str(manifest.get("redaction_state") or "").strip()
    provider_policy_ok = provider_egress_policy in PRIVATE_REMOTE_OCR_ALLOWED_PROVIDER_EGRESS_POLICIES
    approval_ready = approval_state == "approved"
    publication_present = bool(publication_state)
    redaction_ok = bool(redaction_state) and redaction_state != "raw"
    remote_ocr_allowed = (
        not missing_security_fields
        and not placeholder_security_fields
        and provider_policy_ok
        and approval_ready
        and publication_present
        and redaction_ok
    )
    fail_reasons: list[str] = []
    fail_reasons.extend(f"missing_security:{field_name}" for field_name in missing_security_fields)
    fail_reasons.extend(f"placeholder:{field_name}" for field_name in placeholder_security_fields)
    if not provider_policy_ok:
        fail_reasons.append(f"provider_egress_not_allowed:{provider_egress_policy or 'missing'}")
    if not approval_ready:
        fail_reasons.append(f"approval_not_ready:{approval_state or 'missing'}")
    if not publication_present:
        fail_reasons.append("publication_state_missing")
    if not redaction_ok:
        fail_reasons.append(f"redaction_not_ready:{redaction_state or 'missing'}")
    return {
        "ok": remote_ocr_allowed,
        "remote_ocr_allowed": remote_ocr_allowed,
        "approval_ready": approval_ready,
        "publication_present": publication_present,
        "provider_policy_ok": provider_policy_ok,
        "redaction_ok": redaction_ok,
        "missing_security_fields": missing_security_fields,
        "placeholder_security_fields": placeholder_security_fields,
        "fail_reasons": fail_reasons,
    }


def _has_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return bool([item for item in value if str(item).strip()])
    return value is not None


def _placeholder_security_fields(manifest: dict[str, Any]) -> list[str]:
    placeholder_fields: list[str] = []
    for field_name, placeholders in PRIVATE_RUNTIME_PLACEHOLDER_VALUES.items():
        value = str(manifest.get(field_name) or "").strip()
        if value in placeholders:
            placeholder_fields.append(field_name)
    access_groups = [
        str(item).strip()
        for item in (manifest.get("access_groups") or [])
        if str(item).strip()
    ]
    if access_groups and any(item in PRIVATE_RUNTIME_PLACEHOLDER_ACCESS_GROUPS for item in access_groups):
        placeholder_fields.append("access_groups")
    return placeholder_fields


__all__ = [
    "PRIVATE_REMOTE_OCR_ALLOWED_PROVIDER_EGRESS_POLICIES",
    "PRIVATE_RUNTIME_REQUIRED_BOUNDARY_FIELDS",
    "PRIVATE_RUNTIME_REQUIRED_SECURITY_FIELDS",
    "summarize_private_remote_ocr_boundary",
    "summarize_private_runtime_boundary",
]
