from __future__ import annotations

import hashlib
import json
from typing import Any


def source_relative_paths_for_entry(entry: dict[str, Any]) -> list[str]:
    if not isinstance(entry, dict):
        return []
    paths = [
        str(item).strip()
        for item in (entry.get("source_relative_paths") or [])
        if str(item).strip()
    ]
    if paths:
        return paths
    relative_path = str(entry.get("source_relative_path") or "").strip()
    if relative_path:
        return [relative_path]
    return []


def source_ref_for_entry(entry: dict[str, Any]) -> str:
    if not isinstance(entry, dict):
        return ""
    explicit_ref = str(entry.get("source_ref") or "").strip()
    if explicit_ref:
        return explicit_ref

    source_repo = str(entry.get("source_repo") or "").strip()
    source_branch = str(entry.get("source_branch") or "").strip()
    source_relative_path = str(entry.get("source_relative_path") or "").strip()
    if source_repo:
        source_ref = source_repo
        if source_branch:
            source_ref = f"{source_ref}@{source_branch}"
        if source_relative_path:
            source_ref = f"{source_ref}:{source_relative_path}"
        return source_ref

    fallback_ref = str(
        entry.get("source_url")
        or entry.get("fallback_source_url")
        or source_relative_path
        or ""
    ).strip()
    return fallback_ref


def source_fingerprint_for_entry(entry: dict[str, Any]) -> str:
    if not isinstance(entry, dict):
        return ""
    explicit_fingerprint = str(entry.get("source_fingerprint") or "").strip()
    if explicit_fingerprint:
        return explicit_fingerprint
    payload = {
        "source_lane": str(entry.get("source_lane") or "").strip(),
        "primary_input_kind": str(entry.get("primary_input_kind") or "").strip(),
        "source_repo": str(entry.get("source_repo") or "").strip(),
        "source_branch": str(entry.get("source_branch") or "").strip(),
        "source_binding_kind": str(entry.get("source_binding_kind") or "").strip(),
        "source_relative_path": str(entry.get("source_relative_path") or "").strip(),
        "source_relative_paths": source_relative_paths_for_entry(entry),
        "fallback_source_url": str(entry.get("fallback_source_url") or "").strip(),
        "fallback_viewer_path": str(entry.get("fallback_viewer_path") or "").strip(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def source_provenance_payload(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return {
        "source_ref": source_ref_for_entry(entry),
        "source_fingerprint": source_fingerprint_for_entry(entry),
        "primary_input_kind": str(entry.get("primary_input_kind") or "").strip(),
        "source_repo": str(entry.get("source_repo") or "").strip(),
        "source_branch": str(entry.get("source_branch") or "").strip(),
        "source_binding_kind": str(entry.get("source_binding_kind") or "").strip(),
        "source_relative_path": str(entry.get("source_relative_path") or "").strip(),
        "source_relative_paths": source_relative_paths_for_entry(entry),
        "source_mirror_root": str(entry.get("source_mirror_root") or "").strip(),
        "fallback_input_kind": str(entry.get("fallback_input_kind") or "").strip(),
        "fallback_source_url": str(entry.get("fallback_source_url") or "").strip(),
        "fallback_viewer_path": str(entry.get("fallback_viewer_path") or "").strip(),
        "fallback_approved": bool(entry.get("fallback_approved", False)),
    }

