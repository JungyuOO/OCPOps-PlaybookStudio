from __future__ import annotations

from .models import RetrievalHit, SessionContext

SOURCE_GROUP_OFFICIAL_DOCS = "official_docs"
SOURCE_GROUP_CUSTOMER_DOCS = "customer_docs"
SOURCE_GROUP_USER_UPLOAD = "user_upload"
KNOWN_SOURCE_GROUPS = {
    SOURCE_GROUP_OFFICIAL_DOCS,
    SOURCE_GROUP_CUSTOMER_DOCS,
    SOURCE_GROUP_USER_UPLOAD,
}


def _candidate_value(candidate: RetrievalHit | dict[str, object], key: str) -> str:
    if isinstance(candidate, dict):
        return str(candidate.get(key) or "").strip()
    return str(getattr(candidate, key, "") or "").strip()


def enabled_source_scope_set(context: SessionContext | None) -> set[str]:
    scopes = getattr(context, "enabled_source_scopes", []) or []
    return {
        str(scope).strip()
        for scope in scopes
        if str(scope).strip() in KNOWN_SOURCE_GROUPS
    }


def _context_id_set(context: SessionContext | None, field_name: str) -> set[str]:
    values = getattr(context, field_name, []) or []
    return {str(value).strip() for value in values if str(value).strip()}


def _customer_draft_id(candidate: RetrievalHit | dict[str, object]) -> str:
    source_id = _candidate_value(candidate, "source_id")
    if source_id.startswith("customer_pack:"):
        return source_id.split(":", 1)[1].strip()
    viewer_path = _candidate_value(candidate, "viewer_path")
    marker = "/playbooks/customer-packs/"
    if marker in viewer_path:
        tail = viewer_path.split(marker, 1)[1]
        return tail.split("/", 1)[0].strip()
    chunk_id = _candidate_value(candidate, "chunk_id")
    if ":" in chunk_id:
        return chunk_id.split(":", 1)[0].strip()
    return ""


def _detail_scope_enabled(candidate: RetrievalHit | dict[str, object], context: SessionContext | None) -> bool:
    source_group = source_group_for_candidate(candidate)
    if source_group == SOURCE_GROUP_OFFICIAL_DOCS:
        allowed_book_slugs = _context_id_set(context, "enabled_official_book_slugs")
        return not allowed_book_slugs or _candidate_value(candidate, "book_slug") in allowed_book_slugs
    if source_group == SOURCE_GROUP_CUSTOMER_DOCS:
        allowed_draft_ids = _context_id_set(context, "enabled_customer_draft_ids")
        allowed_document_ids = _context_id_set(context, "enabled_customer_document_ids")
        if not allowed_draft_ids and not allowed_document_ids:
            return True
        document_id = _candidate_value(candidate, "document_source_id") or _candidate_value(candidate, "source_id")
        return (
            (_customer_draft_id(candidate) in allowed_draft_ids)
            or (document_id in allowed_document_ids)
        )
    if source_group == SOURCE_GROUP_USER_UPLOAD:
        allowed_document_ids = _context_id_set(context, "enabled_upload_document_ids")
        if not allowed_document_ids:
            return True
        document_id = _candidate_value(candidate, "document_source_id") or _candidate_value(candidate, "source_id")
        return document_id in allowed_document_ids
    return True


def source_group_for_candidate(candidate: RetrievalHit | dict[str, object]) -> str:
    source_scope = _candidate_value(candidate, "source_scope")
    if source_scope == "official_docs":
        return SOURCE_GROUP_OFFICIAL_DOCS
    if source_scope == "study_docs":
        return SOURCE_GROUP_CUSTOMER_DOCS
    if source_scope == "user_upload":
        return SOURCE_GROUP_USER_UPLOAD

    source_lane = _candidate_value(candidate, "source_lane")
    source_id = _candidate_value(candidate, "source_id")
    source_collection = _candidate_value(candidate, "source_collection")
    viewer_path = _candidate_value(candidate, "viewer_path")
    if (
        source_lane in {"customer_pack", "customer_source_first_pack"}
        or source_id.startswith("customer_pack:")
        or viewer_path.startswith("/playbooks/customer-packs/")
        or source_collection == "uploaded"
    ):
        return SOURCE_GROUP_CUSTOMER_DOCS

    return source_scope


def _source_scope_enabled(candidate: RetrievalHit | dict[str, object], context: SessionContext | None) -> bool:
    enabled = enabled_source_scope_set(context)
    if not enabled:
        return True
    return source_group_for_candidate(candidate) in enabled


def _active_upload_scope_applies(candidate: RetrievalHit | dict[str, object], context: SessionContext | None) -> bool:
    if not enabled_source_scope_set(context):
        return True
    return source_group_for_candidate(candidate) == SOURCE_GROUP_USER_UPLOAD


def hit_visible_to_session(hit: RetrievalHit, context: SessionContext | None) -> bool:
    if not _source_scope_enabled(hit, context):
        return False
    if not _detail_scope_enabled(hit, context):
        return False

    explicit_upload_document_ids = _context_id_set(context, "enabled_upload_document_ids")
    active_document_id = str(getattr(context, "active_document_id", "") or "").strip()
    if active_document_id and _active_upload_scope_applies(hit, context) and not explicit_upload_document_ids:
        hit_document_id = str(getattr(hit, "document_source_id", "") or getattr(hit, "source_id", "") or "").strip()
        if hit_document_id != active_document_id:
            return False

    active_repository_id = str(getattr(context, "active_repository_id", "") or "").strip()
    if active_repository_id and _active_upload_scope_applies(hit, context) and not explicit_upload_document_ids:
        hit_repository_id = str(getattr(hit, "repository_id", "") or "").strip()
        if hit_repository_id != active_repository_id:
            return False

    visibility = str(getattr(hit, "visibility", "") or "").strip()
    source_scope = str(getattr(hit, "source_scope", "") or "").strip()
    if not visibility and not source_scope:
        return True
    if visibility in {"global_shared", "workspace_shared"}:
        return True
    if visibility != "private_user":
        return False

    owner_user_id = str(getattr(context, "owner_user_id", "") or getattr(context, "user_id", "") or "").strip()
    if not owner_user_id or str(hit.owner_user_id or "").strip() != owner_user_id:
        return False
    return True


def filter_hits_by_session_scope(
    hits: list[RetrievalHit],
    *,
    context: SessionContext | None,
) -> list[RetrievalHit]:
    return [hit for hit in hits if hit_visible_to_session(hit, context)]


__all__ = [
    "SOURCE_GROUP_CUSTOMER_DOCS",
    "SOURCE_GROUP_OFFICIAL_DOCS",
    "SOURCE_GROUP_USER_UPLOAD",
    "enabled_source_scope_set",
    "filter_hits_by_session_scope",
    "hit_visible_to_session",
    "source_group_for_candidate",
]
