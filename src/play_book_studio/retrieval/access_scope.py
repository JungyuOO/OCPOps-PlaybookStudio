from __future__ import annotations

from .models import RetrievalHit, SessionContext


def hit_visible_to_session(hit: RetrievalHit, context: SessionContext | None) -> bool:
    active_document_id = str(getattr(context, "active_document_id", "") or "").strip()
    if active_document_id:
        hit_document_id = str(getattr(hit, "document_source_id", "") or getattr(hit, "source_id", "") or "").strip()
        if hit_document_id != active_document_id:
            return False

    active_repository_id = str(getattr(context, "active_repository_id", "") or "").strip()
    if active_repository_id:
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
    return bool(active_repository_id)


def filter_hits_by_session_scope(
    hits: list[RetrievalHit],
    *,
    context: SessionContext | None,
) -> list[RetrievalHit]:
    return [hit for hit in hits if hit_visible_to_session(hit, context)]


__all__ = [
    "filter_hits_by_session_scope",
    "hit_visible_to_session",
]
