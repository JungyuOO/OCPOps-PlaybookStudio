from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


OFFICIAL_AUTHORITY = "official"
CUSTOMER_PRIVATE_AUTHORITY = "customer_private"
COMMUNITY_AUTHORITY = "community"
UNVERIFIED_AUTHORITY = "unverified_candidate"
UNKNOWN_AUTHORITY = "unknown"

OFFICIAL_HOSTS = {
    "docs.redhat.com",
    "access.redhat.com",
    "docs.openshift.com",
}
OFFICIAL_REPO_HINTS = {
    "github.com/openshift/openshift-docs",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _host(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.netloc or parsed.path.split("/", maxsplit=1)[0]).lower()


def _entry_text(entry: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = entry.get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(_clean(item) for item in value)
        else:
            parts.append(_clean(value))
    return " ".join(part for part in parts if part).lower()


def _explicit_authority(value: Any) -> str:
    normalized = _lower(value).replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    if normalized in {"official", "official_redhat", "redhat_official", "vendor_official"}:
        return OFFICIAL_AUTHORITY
    if normalized in {"customer", "customer_private", "private_customer", "private"}:
        return CUSTOMER_PRIVATE_AUTHORITY
    if normalized in {"community", "unofficial", "public_community"}:
        return COMMUNITY_AUTHORITY
    if normalized in {"candidate", "unverified", "unverified_candidate", "unknown_candidate"}:
        return UNVERIFIED_AUTHORITY
    return ""


def canonical_source_authority(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return UNKNOWN_AUTHORITY

    source_collection = _lower(entry.get("source_collection"))
    source_lane = _lower(entry.get("source_lane"))
    boundary_truth = _lower(entry.get("boundary_truth"))
    source_type = _lower(entry.get("source_type"))
    source_kind = _lower(entry.get("source_kind"))
    current_source_basis = _lower(entry.get("current_source_basis"))
    classification = _lower(entry.get("classification"))
    approval_state = _lower(entry.get("approval_state") or entry.get("approval_status"))

    if (
        "community" in source_lane
        or "community" in boundary_truth
        or classification in {"community", "public_community"}
    ):
        return COMMUNITY_AUTHORITY

    for key in ("source_authority", "authority_tier", "source_trust_tier", "authority"):
        explicit = _explicit_authority(entry.get(key))
        if explicit:
            return explicit

    if (
        source_collection == "uploaded"
        or "customer" in source_lane
        or "customer" in boundary_truth
        or classification in {"private", "customer_private", "confidential"}
    ):
        return CUSTOMER_PRIVATE_AUTHORITY

    haystack = _entry_text(
        entry,
        "source_url",
        "uri",
        "source_uri",
        "acquisition_uri",
        "resolved_source_url",
        "fallback_source_url",
        "source_repo",
        "source_ref",
        "viewer_path",
        "source_relative_path",
        "source_relative_paths",
        "primary_input_kind",
    )
    urls = [
        _clean(entry.get("source_url")),
        _clean(entry.get("uri")),
        _clean(entry.get("source_uri")),
        _clean(entry.get("acquisition_uri")),
        _clean(entry.get("resolved_source_url")),
        _clean(entry.get("fallback_source_url")),
        _clean(entry.get("source_repo")),
        _clean(entry.get("source_ref")),
    ]
    hosts = {_host(url) for url in urls if _clean(url)}

    if (
        boundary_truth.startswith("official_")
        or source_lane.startswith("official")
        or source_collection == "core"
        or current_source_basis.startswith("official")
        or any(host in OFFICIAL_HOSTS for host in hosts)
        or any(hint in haystack for hint in OFFICIAL_REPO_HINTS)
    ):
        return OFFICIAL_AUTHORITY

    community_markers = (
        "community",
        "unofficial",
        "github.com",
        "gitlab.com",
        "stackoverflow.com",
        "medium.com",
        "blog",
    )
    if any(marker in haystack for marker in community_markers):
        return COMMUNITY_AUTHORITY

    if (
        "candidate" in source_lane
        or "candidate" in boundary_truth
        or "candidate" in source_type
        or approval_state in {"", "draft", "unreviewed", "pending"}
        or source_kind in {"", "candidate"}
    ):
        return UNVERIFIED_AUTHORITY

    return UNKNOWN_AUTHORITY


def source_authority_payload(entry: dict[str, Any] | None) -> dict[str, Any]:
    authority = canonical_source_authority(entry)
    specs = {
        OFFICIAL_AUTHORITY: {
            "label": "Official Source",
            "badge": "Official",
            "warning": "",
            "requires_review": False,
        },
        CUSTOMER_PRIVATE_AUTHORITY: {
            "label": "Private Customer Source",
            "badge": "Private",
            "warning": "Customer/internal material; keep within the approved project boundary.",
            "requires_review": False,
        },
        COMMUNITY_AUTHORITY: {
            "label": "Community Source",
            "badge": "Community",
            "warning": "Not an official vendor source; verify before operational use.",
            "requires_review": True,
        },
        UNVERIFIED_AUTHORITY: {
            "label": "Unverified Candidate",
            "badge": "Candidate",
            "warning": "Source candidate is not reviewed or materialized yet.",
            "requires_review": True,
        },
    }
    spec = specs.get(
        authority,
        {
            "label": "Unverified Source",
            "badge": "Unverified",
            "warning": "Source authority is unknown; verify before operational use.",
            "requires_review": True,
        },
    )
    return {
        "source_authority": authority,
        "source_authority_label": spec["label"],
        "source_authority_badge": spec["badge"],
        "source_authority_warning": spec["warning"],
        "source_requires_review": bool(spec["requires_review"]),
    }
