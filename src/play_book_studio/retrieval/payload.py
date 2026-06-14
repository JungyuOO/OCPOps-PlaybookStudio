"""Canonical retrieval payload builders shared by BM25 and vector search."""

from __future__ import annotations

import hashlib
import json
from typing import Any


RETRIEVAL_PAYLOAD_VERSION = 1


def retrieval_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    section_path = _json_list(row.get("section_path"))
    toc_path = _json_list(row.get("toc_path"))
    asset_ids = _json_list(row.get("asset_ids"))
    child_chunk_ids = _json_list(row.get("child_chunk_ids"))
    starter_question_candidates = _string_list(row.get("starter_question_candidates"))
    followup_question_candidates = _string_list(row.get("followup_question_candidates"))
    chunk_metadata = _safe_metadata(_json_dict(row.get("chunk_metadata")))
    parsed_metadata = _json_dict(row.get("parsed_metadata"))
    source_metadata = _json_dict(row.get("source_metadata"))
    title = str(row.get("document_title") or row.get("filename") or "Uploaded document")
    section = str(chunk_metadata.get("section") or (section_path[-1] if section_path else title))
    chapter = str(chunk_metadata.get("chapter") or (section_path[0] if section_path else title))
    document_source_id = str(row.get("document_source_id") or "")
    chunk_id = str(row.get("chunk_id") or "")
    filename = str(row.get("filename") or "")
    storage_key = str(row.get("storage_key") or "")
    source_scope = str(row.get("source_scope") or source_metadata.get("source_scope") or "user_upload")
    document_format = str(
        source_metadata.get("document_format")
        or parsed_metadata.get("document_format")
        or ""
    )
    book_slug = str(chunk_metadata.get("book_slug") or source_metadata.get("book_slug") or "")
    if not book_slug:
        book_slug = "uploaded-documents" if source_scope == "user_upload" else source_scope
    source_lane = str(
        chunk_metadata.get("source_lane")
        or source_metadata.get("source_lane")
        or ("uploads" if source_scope == "user_upload" else source_scope)
    )
    source_type = str(
        chunk_metadata.get("source_type")
        or source_metadata.get("source_type")
        or ("uploaded_document" if source_scope == "user_upload" else source_scope)
    )
    source_collection = str(
        chunk_metadata.get("source_collection")
        or source_metadata.get("source_collection")
        or ("uploads" if source_scope == "user_upload" else "core")
    )
    source_id = str(chunk_metadata.get("source_id") or source_metadata.get("source_id") or document_source_id)
    source_url = str(chunk_metadata.get("source_url") or source_metadata.get("source_url") or storage_key)
    viewer_path = str(
        chunk_metadata.get("viewer_path")
        or source_metadata.get("viewer_path")
        or f"/uploads/documents/{document_source_id}/index.html#{chunk_id}"
    )
    payload_text = _payload_text_from_row(row)
    payload = {
        "payload_version": RETRIEVAL_PAYLOAD_VERSION,
        "chunk_id": chunk_id,
        "book_slug": book_slug,
        "chapter": chapter,
        "section": section,
        "section_id": str(chunk_metadata.get("section_id") or row.get("chunk_key") or chunk_id),
        "anchor": str(chunk_metadata.get("anchor") or row.get("source_anchor") or row.get("chunk_key") or chunk_id),
        "source_url": source_url,
        "viewer_path": viewer_path,
        "text": payload_text,
        "markdown": str(row.get("markdown") or ""),
        "filename": filename,
        "document_format": document_format,
        "source_kind": str(row.get("source_kind") or "upload"),
        "chunk_type": str(row.get("chunk_type") or "document"),
        "source_id": source_id,
        "document_source_id": document_source_id,
        "source_lane": source_lane,
        "source_type": source_type,
        "source_collection": source_collection,
        "review_status": str(chunk_metadata.get("review_status") or source_metadata.get("review_status") or "unreviewed"),
        "trust_score": float(chunk_metadata.get("trust_score") or source_metadata.get("trust_score") or 0.8),
        "parsed_artifact_id": str(
            chunk_metadata.get("parsed_artifact_id")
            or source_metadata.get("parsed_artifact_id")
            or row.get("parsed_document_id")
            or ""
        ),
        "semantic_role": str(chunk_metadata.get("semantic_role") or "uploaded_document"),
        "block_kinds": _string_list(chunk_metadata.get("block_kinds")) or [str(row.get("chunk_type") or "document")],
        "section_path": section_path,
        "section_number": str(row.get("section_number") or ""),
        "heading_title": str(row.get("heading_title") or ""),
        "source_anchor": str(row.get("source_anchor") or ""),
        "toc_path": toc_path,
        "asset_ids": asset_ids,
        "chunk_role": str(row.get("chunk_role") or chunk_metadata.get("chunk_role") or "leaf"),
        "parent_chunk_id": str(row.get("parent_chunk_id") or chunk_metadata.get("parent_chunk_id") or ""),
        "child_chunk_ids": child_chunk_ids or _string_list(chunk_metadata.get("child_chunk_ids")),
        "navigation_only": bool(row.get("navigation_only") or chunk_metadata.get("navigation_only") or False),
        "beginner_narrative": str(row.get("beginner_narrative") or chunk_metadata.get("beginner_narrative") or ""),
        "starter_question_candidates": starter_question_candidates
        or _string_list(chunk_metadata.get("starter_question_candidates")),
        "followup_question_candidates": followup_question_candidates
        or _string_list(chunk_metadata.get("followup_question_candidates")),
        "question_candidates_version": int(
            row.get("question_candidates_version") or chunk_metadata.get("question_candidates_version") or 0
        ),
        "repository_id": str(row.get("repository_id") or ""),
        "visibility": str(row.get("visibility") or source_metadata.get("visibility") or "workspace_shared"),
        "owner_user_id": str(row.get("owner_user_id") or ""),
        "source_scope": source_scope,
        "created_by": str(row.get("created_by") or ""),
        "cli_commands": _string_list(chunk_metadata.get("cli_commands")),
        "error_strings": _string_list(chunk_metadata.get("error_strings")),
        "k8s_objects": _string_list(chunk_metadata.get("k8s_objects")),
        "operator_names": _string_list(chunk_metadata.get("operator_names")),
        "verification_hints": _string_list(chunk_metadata.get("verification_hints")),
        "learning": _learning_metadata(chunk_metadata, parsed_metadata, source_metadata),
        "chunk_metadata": chunk_metadata,
    }
    payload.update(_search_json_payload_from_payload(payload, row=row))
    return payload


def retrieval_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _search_json_payload_from_payload(payload: dict[str, Any], *, row: dict[str, Any]) -> dict[str, Any]:
    chunk_metadata = _json_dict(row.get("chunk_metadata"))
    source_metadata = _json_dict(row.get("source_metadata"))
    parsed_metadata = _json_dict(row.get("parsed_metadata"))
    search_signals = _json_dict(chunk_metadata.get("search_signals"))
    classification_metadata = _json_dict(chunk_metadata.get("classification"))
    source_scope = str(payload.get("source_scope") or source_metadata.get("source_scope") or "")
    source_lane = str(payload.get("source_lane") or "")
    source_type = str(payload.get("source_type") or "")
    doc_type = _doc_type_for_payload(source_type=source_type, source_scope=source_scope)
    review_status = str(payload.get("review_status") or "needs_review")
    locale = str(
        classification_metadata.get("locale")
        or chunk_metadata.get("locale")
        or source_metadata.get("locale")
        or parsed_metadata.get("locale")
        or "ko"
    )
    ocp_version = str(
        classification_metadata.get("ocp_version")
        or chunk_metadata.get("ocp_version")
        or chunk_metadata.get("version")
        or source_metadata.get("ocp_version")
        or source_metadata.get("version")
        or "4.20"
    )
    domain = str(
        classification_metadata.get("domain")
        or chunk_metadata.get("domain")
        or source_metadata.get("domain")
        or _domain_for_book_slug(str(payload.get("book_slug") or ""))
    )
    text_layers = _json_dict(chunk_metadata.get("text_layers"))
    normalized_text = str(
        text_layers.get("normalized_text")
        or chunk_metadata.get("normalized_text")
        or row.get("normalized_text")
        or payload.get("text")
        or ""
    )
    embedding_text = str(text_layers.get("embedding_text") or _payload_text_from_row(row) or payload.get("text") or "")
    commands = _string_list(search_signals.get("commands")) or _string_list(payload.get("cli_commands"))
    objects = _string_list(search_signals.get("objects")) or _string_list(payload.get("k8s_objects"))
    operators = _string_list(search_signals.get("operators")) or _string_list(payload.get("operator_names"))
    error_states = _string_list(search_signals.get("error_states")) or _string_list(payload.get("error_strings"))
    verification_hints = _string_list(search_signals.get("verification_hints")) or _string_list(
        payload.get("verification_hints")
    )
    return {
        "id": str(payload.get("chunk_id") or ""),
        "document_id": str(payload.get("document_source_id") or ""),
        "source": {
            "corpus_scope": source_scope or "official_docs",
            "doc_type": doc_type,
            "source_lane": source_lane,
            "visibility": str(payload.get("visibility") or "workspace_shared"),
            "review_status": review_status,
            "citation_eligible": bool(chunk_metadata.get("citation_eligible", review_status == "approved")),
            "enabled_for_chat": bool(chunk_metadata.get("enabled_for_chat", True)),
        },
        "classification": {
            "domain": domain,
            "subdomains": _string_list(classification_metadata.get("subdomains"))
            or _string_list(chunk_metadata.get("subdomains")),
            "platform": str(
                classification_metadata.get("platform")
                or chunk_metadata.get("platform")
                or source_metadata.get("platform")
                or "none"
            ),
            "ocp_version": ocp_version,
            "locale": locale,
            "book_slug": str(payload.get("book_slug") or ""),
        },
        "chunk": {
            "chunk_type": str(payload.get("chunk_type") or "reference"),
            "chunk_role": str(payload.get("chunk_role") or "leaf"),
            "navigation_only": bool(payload.get("navigation_only") or False),
            "ordinal": int(row.get("ordinal") or 0),
            "title": str(payload.get("heading_title") or payload.get("section") or payload.get("chapter") or ""),
            "section_path": _string_list(payload.get("section_path")),
            "section_anchor": str(payload.get("source_anchor") or payload.get("anchor") or ""),
            "viewer_path": str(payload.get("viewer_path") or ""),
            "source_url": str(payload.get("source_url") or ""),
        },
        "search_signals": {
            "primary_topics": _string_list(search_signals.get("primary_topics")),
            "secondary_topics": _string_list(search_signals.get("secondary_topics")),
            "objects": objects,
            "operators": operators,
            "components": _string_list(search_signals.get("components")),
            "commands": commands,
            "command_families": _string_list(search_signals.get("command_families")) or _command_families(commands),
            "error_states": error_states,
            "intent_labels": _string_list(search_signals.get("intent_labels")),
            "answer_shapes": _string_list(search_signals.get("answer_shapes")),
            "cluster_phase": _string_list(search_signals.get("cluster_phase")),
            "execution_target": _string_list(search_signals.get("execution_target")),
            "best_for_questions": _string_list(search_signals.get("best_for_questions")),
            "verification_hints": verification_hints,
        },
        "text_fields": {
            "normalized_text": normalized_text,
            "embedding_text": embedding_text,
        },
    }


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []
    return []


def _payload_text_from_row(row: dict[str, Any]) -> str:
    if "embedding_text" in row and row.get("embedding_text") is not None:
        return str(row.get("embedding_text") or "")
    return str(row.get("markdown") or "")


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(value or {})
    metadata.pop("raw_text", None)
    text_layers = metadata.get("text_layers")
    if isinstance(text_layers, dict):
        safe_layers = dict(text_layers)
        safe_layers.pop("raw_text", None)
        metadata["text_layers"] = safe_layers
    return metadata


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _json_list(value) if str(item).strip()]


def _doc_type_for_payload(*, source_type: str, source_scope: str) -> str:
    normalized_type = source_type.strip()
    normalized_scope = source_scope.strip()
    if normalized_type in {"official_doc", "manual_synthesis", "operations_doc", "user_upload"}:
        return normalized_type
    if normalized_scope == "user_upload" or normalized_type in {"uploaded_document", "upload"}:
        return "user_upload"
    if normalized_type == "applied_playbook":
        return "manual_synthesis"
    return "official_doc"


def _domain_for_book_slug(book_slug: str) -> str:
    normalized = book_slug.strip().lower()
    if normalized in {
        "installation_overview",
        "installing_on_any_platform",
        "disconnected_environments",
        "postinstallation_configuration",
    }:
        return "install"
    if normalized in {"backup_and_restore", "etcd"}:
        return "backup_restore" if normalized == "backup_and_restore" else "etcd"
    if normalized == "storage":
        return "storage"
    if normalized in {"advanced_networking", "ingress_and_load_balancing", "networking_overview"}:
        return "networking"
    if normalized in {"security_and_compliance", "authentication_and_authorization"}:
        return "security"
    if normalized in {"monitoring", "observability_overview"}:
        return "monitoring"
    if normalized == "logging":
        return "logging"
    if normalized == "operators":
        return "operators"
    if normalized in {"nodes", "machine_configuration", "machine_management"}:
        return "node_ops"
    if normalized in {"registry", "images"}:
        return "registry"
    if normalized in {"cli_tools", "web_console"}:
        return "ui_tooling"
    if normalized in {"architecture", "overview"}:
        return "architecture"
    if normalized == "release_notes":
        return "release_notes"
    if normalized in {"support", "validation_and_troubleshooting"}:
        return "troubleshooting"
    if normalized == "updating_clusters":
        return "upgrade"
    return ""


def _command_families(commands: list[str]) -> list[str]:
    families: list[str] = []
    for command in commands:
        normalized = " ".join(command.lower().split())
        family = ""
        if normalized.startswith("oc get"):
            family = "oc_get"
        elif normalized.startswith("oc describe"):
            family = "oc_describe"
        elif normalized.startswith("oc logs"):
            family = "oc_logs"
        elif normalized.startswith("oc debug"):
            family = "oc_debug"
        elif normalized.startswith("oc adm"):
            family = "oc_adm"
        elif normalized.startswith("oc patch"):
            family = "oc_patch"
        elif normalized.startswith("oc create"):
            family = "oc_create"
        elif normalized.startswith("oc apply"):
            family = "oc_apply"
        elif normalized.startswith("oc delete"):
            family = "oc_delete"
        if family and family not in families:
            families.append(family)
    return families


def _learning_metadata(
    chunk_metadata: dict[str, Any],
    parsed_metadata: dict[str, Any],
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    source_learning = source_metadata.get("learning")
    parsed_learning = parsed_metadata.get("learning")
    chunk_learning = chunk_metadata.get("learning")
    payload = {
        "document": source_learning if isinstance(source_learning, dict) else {},
        "parsed_document": parsed_learning if isinstance(parsed_learning, dict) else {},
        "chunk": chunk_learning if isinstance(chunk_learning, dict) else {},
    }
    refs: dict[str, Any] = {}
    for source in (payload["document"], payload["parsed_document"], payload["chunk"]):
        for key in ("prerequisite_refs", "next_refs", "related_refs", "lab_refs"):
            value = source.get(key)
            if isinstance(value, list) and value and key not in refs:
                refs[key] = value
    if refs:
        payload["refs"] = refs
    return payload


__all__ = [
    "RETRIEVAL_PAYLOAD_VERSION",
    "retrieval_payload_from_row",
    "retrieval_payload_hash",
    "text_hash",
    "vector_literal",
]
