from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import re
import time
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.db.document_repository import (
    bind_upload_pipeline_events,
    get_or_create_document_topology_snapshot_by_id,
    insert_upload_pipeline_event,
    list_upload_pipeline_events,
    load_document_quality_snapshot,
    load_document_topology_snapshot_summary,
    load_document_topology_source,
    load_parsed_document_for_repair,
    persist_parsed_upload_document,
    replace_parsed_document_content,
    update_document_source_gold_build_run,
    update_document_source_metadata,
    upsert_document_quality_snapshot,
)
from play_book_studio.db.qdrant_indexer import delete_qdrant_points, index_pending_document_chunks
from play_book_studio.document_quality import build_document_quality_snapshot, merge_quality_into_gold_run
from play_book_studio.ingestion.asset_storage import remove_stored_asset_files, store_parsed_asset_files
from play_book_studio.ingestion.code_block_repair import repair_unfenced_code_blocks
from play_book_studio.ingestion.document_parsing import (
    build_document_chunks,
    parse_upload_document,
    rebuild_parsed_document_from_markdown,
)
from play_book_studio.ingestion.page_stub_repair import repair_page_stub_headings
from play_book_studio.ingestion.pdf_text_repair import repair_pdf_text_artifacts
from play_book_studio.ingestion.vision import build_qwen_image_describer
from play_book_studio.wiki_gold_builder import prepare_upload_gold_build_candidate, with_index_verification


def _bool_payload(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_payload(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _required_uuid_payload(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError(f"{key} must be a valid UUID") from exc


def _payload_owner_user_id(payload: dict[str, Any]) -> str:
    return str(payload.get("created_by") or "").strip()


def _assert_loaded_document_owner(loaded: Any | None, owner_user_id: str) -> None:
    if loaded is None:
        return
    source_scope = str(getattr(loaded, "source_scope", "") or "").strip()
    visibility = str(getattr(loaded, "visibility", "") or "").strip()
    document_owner = str(getattr(loaded, "owner_user_id", "") or "").strip()
    if source_scope == "user_upload" or visibility == "private_user":
        if not owner_user_id or not document_owner or document_owner != owner_user_id:
            raise ValueError("document_source_id is not visible to the current user")


def _file_bytes_from_payload(payload: dict[str, Any]) -> bytes:
    file_bytes = payload.get("file_bytes")
    if isinstance(file_bytes, (bytes, bytearray)):
        return bytes(file_bytes)
    content_base64 = str(payload.get("content_base64") or "").strip()
    if not content_base64:
        raise ValueError("file_bytes or content_base64 is required")
    try:
        return base64.b64decode(content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("content_base64 is not valid base64") from exc


def _safe_upload_name(file_name: str) -> str:
    source = Path(str(file_name or "upload").strip()).name
    suffix = Path(source).suffix
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source).stem).strip("-._")
    return f"{safe_stem or 'upload'}{suffix or '.bin'}"


def _parsed_document_is_pdf(parsed: Any) -> bool:
    return (
        str(getattr(parsed, "document_format", "") or "").strip().lower() == "pdf"
        or str(getattr(parsed, "mime_type", "") or "").strip().lower() == "application/pdf"
        or str(getattr(parsed, "filename", "") or "").strip().lower().endswith(".pdf")
    )


def _store_uploaded_file(root_dir: Path, payload: dict[str, Any]) -> tuple[Path, str, int]:
    settings = load_settings(root_dir)
    content = _file_bytes_from_payload(payload)
    if not content:
        raise ValueError("uploaded file is empty")
    file_name = _safe_upload_name(str(payload.get("file_name") or "upload"))
    upload_id = uuid.uuid4().hex
    storage_key = f"uploads/sources/{upload_id}/{file_name}"
    target = (settings.object_storage_dir / storage_key).resolve()
    storage_root = settings.object_storage_dir.resolve()
    if storage_root not in target.parents:
        raise ValueError("invalid upload path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target, storage_key, len(content)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_contract(event: str, data: dict[str, Any] | None = None) -> tuple[str, str, str]:
    data = data or {}
    if event in {"received"}:
        return "bronze", event, "running"
    if event in {"source_stored", "dry_run_done"}:
        return "bronze", event, "completed"
    if event in {"parse_start", "parsed", "chunk_start", "chunked", "persist_start", "repair_start"}:
        return "silver", event, "running"
    if event in {"persisted", "pdf_text_repaired", "code_block_repaired", "page_stubs_repaired"}:
        return "silver", event, "completed"
    if event in {"index_start", "indexing"}:
        return "gold", "index_start", "running"
    if event == "reindex_start":
        return "gold", event, "running"
    if event == "indexed":
        return "gold", event, "completed"
    if event == "index_deferred":
        return "gold", event, "deferred"
    if event in {"gold_build", "judge_start"}:
        return "judge", "judge_start" if event == "gold_build" else event, "running"
    if event == "judge_completed":
        quality_state = str(data.get("quality_state") or data.get("state") or "").strip()
        status = "completed" if quality_state in {"", "gold_ready"} else "deferred"
        if quality_state == "blocked":
            status = "failed"
        return "judge", event, status
    if event in {"topology_start", "topology_build"}:
        return "topology", "topology_start", "running"
    if event == "topology_ready":
        return "topology", event, "completed"
    if event == "topology_deferred":
        return "topology", event, "deferred"
    if event == "topology_failed":
        return "topology", event, "failed"
    if event == "complete":
        summary = data.get("pipeline_summary") if isinstance(data.get("pipeline_summary"), dict) else {}
        return "pipeline", event, str(summary.get("overall_status") or data.get("status") or "completed")
    if event == "failed":
        return "bronze", event, "failed"
    return "bronze", event, "running"


class _UploadPipelineEventRecorder:
    def __init__(self, *, database_url: str = "") -> None:
        self.run_id = uuid.uuid4().hex
        self.database_url = database_url
        self.sequence = 0
        self.events: list[dict[str, Any]] = []
        self.document_source_id = ""
        self.parsed_document_id = ""
        self.ledger_error = ""

    def emit(self, event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(data or {})
        self.document_source_id = str(payload.get("document_source_id") or self.document_source_id)
        self.parsed_document_id = str(payload.get("parsed_document_id") or self.parsed_document_id)
        self.sequence += 1
        pipeline_stage, event_name, status = _event_contract(event, payload)
        event_id = f"{self.sequence:04d}-{event_name}"
        occurred_at = _utc_iso()
        enriched = {
            "type": "event",
            "run_id": self.run_id,
            "event_id": event_id,
            "stage": event,
            "event": event_name,
            "pipeline_stage": pipeline_stage,
            "status": status,
            "occurred_at": occurred_at,
            "document_source_id": self.document_source_id,
            "parsed_document_id": self.parsed_document_id,
            "data": payload,
            "payload": payload,
            "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        }
        if event == "persisted" and self.database_url:
            self._bind_previous_events()
        self._persist(enriched)
        self.events.append(enriched)
        return enriched

    def complete_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        return _pipeline_summary(result, events=self.events)

    def _bind_previous_events(self) -> None:
        try:
            import psycopg

            with psycopg.connect(self.database_url) as connection:
                bind_upload_pipeline_events(
                    connection,
                    run_id=self.run_id,
                    document_source_id=self.document_source_id,
                    parsed_document_id=self.parsed_document_id,
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001
            self.ledger_error = str(exc)

    def _persist(self, enriched: dict[str, Any]) -> None:
        if not self.database_url:
            return
        try:
            import psycopg

            with psycopg.connect(self.database_url) as connection:
                insert_upload_pipeline_event(
                    connection,
                    run_id=self.run_id,
                    event_id=str(enriched["event_id"]),
                    document_source_id=self.document_source_id,
                    parsed_document_id=self.parsed_document_id,
                    stage=str(enriched["pipeline_stage"]),
                    event=str(enriched["event"]),
                    status=str(enriched["status"]),
                    occurred_at=str(enriched["occurred_at"]),
                    payload=dict(enriched.get("payload") or {}),
                    evidence=dict(enriched.get("evidence") or {}),
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001
            self.ledger_error = str(exc)


def _deferred_index_result(
    settings: Any,
    payload: dict[str, Any],
    *,
    source_scope: str,
    document_source_id: str = "",
    chunk_count: int,
    error: Exception,
) -> dict[str, Any]:
    return {
        "collection": str(payload.get("collection") or "").strip() or settings.qdrant_collection,
        "source_scope": source_scope.strip(),
        "document_source_id": str(document_source_id or "").strip(),
        "candidate_count": chunk_count,
        "indexed_count": 0,
        "status": "deferred",
        "retryable": True,
        "error": str(error),
    }


def _index_pending_with_retry(
    settings: Any,
    connection: Any,
    payload: dict[str, Any],
    *,
    source_scope: str,
    document_source_id: str = "",
    chunk_count: int,
) -> dict[str, Any]:
    attempts = max(1, min(_int_payload(payload.get("index_retry_attempts"), default=3), 5))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = index_pending_document_chunks(
                settings,
                connection,
                collection=str(payload.get("collection") or "").strip() or None,
                source_scope=source_scope,
                document_source_id=document_source_id,
                limit=_int_payload(payload.get("index_limit"), default=max(100, chunk_count)),
            )
            if attempt > 1:
                result["retry_attempts"] = attempt
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts:
                time.sleep(min(0.4 * attempt, 1.2))
    return _deferred_index_result(
        settings,
        payload,
        source_scope=source_scope,
        document_source_id=document_source_id,
        chunk_count=chunk_count,
        error=last_error or RuntimeError("indexing failed"),
    )


def _topology_event_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {
            "status": "deferred",
            "state": "missing",
            "retryable": True,
            "error": "topology snapshot source was not found",
        }
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    storage = str(metadata.get("storage") or "").strip()
    state = str(snapshot.get("state") or summary.get("state") or "").strip()
    blockers = list(snapshot.get("blockers") or summary.get("blockers") or [])
    ready = (storage == "postgres" or bool(snapshot.get("snapshot_id"))) and state == "ready" and not blockers
    return {
        "status": "ready" if ready else "deferred",
        "state": state,
        "retryable": storage != "postgres",
        "document_source_id": str(snapshot.get("document_source_id") or ""),
        "parsed_document_id": str(snapshot.get("parsed_document_id") or ""),
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "schema_version": str(snapshot.get("schema_version") or ""),
        "node_count": int(snapshot.get("node_count") or summary.get("node_count") or 0),
        "edge_count": int(snapshot.get("edge_count") or summary.get("edge_count") or 0),
        "blockers": blockers,
        "storage": storage or ("postgres" if snapshot.get("snapshot_id") else "unknown"),
        "error": str(metadata.get("snapshot_error") or metadata.get("storage_reason") or ""),
    }


def _delete_qdrant_points_by_collection(
    settings: Any,
    points_by_collection: dict[str, tuple[str, ...]] | dict[str, list[str]],
) -> dict[str, Any]:
    collections: dict[str, Any] = {}
    requested_count = 0
    deleted_count = 0
    errors: list[str] = []
    for collection, point_ids in sorted(points_by_collection.items()):
        unique_ids = [point_id for point_id in dict.fromkeys(str(item) for item in point_ids) if point_id]
        if not collection or not unique_ids:
            continue
        requested_count += len(unique_ids)
        try:
            result = delete_qdrant_points(settings, collection=collection, point_ids=unique_ids)
            deleted = int(result.get("deleted_count") or 0)
            deleted_count += deleted
            collections[collection] = {
                **result,
                "point_ids": unique_ids,
                "status": "completed",
            }
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            errors.append(f"{collection}: {error}")
            collections[collection] = {
                "collection": collection,
                "requested_count": len(unique_ids),
                "deleted_count": 0,
                "point_ids": unique_ids,
                "status": "deferred",
                "retryable": True,
                "error": error,
            }
    return {
        "status": "deferred" if errors else "completed",
        "requested_count": requested_count,
        "deleted_count": deleted_count,
        "collections": collections,
        "errors": errors,
        "retryable": bool(errors),
    }


def _pending_cleanup_map(payload: Any) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        return {}
    collections = payload.get("collections")
    if not isinstance(collections, dict):
        return {}
    pending: dict[str, list[str]] = {}
    for collection, row in collections.items():
        if not isinstance(row, dict):
            continue
        point_ids = [str(item) for item in row.get("point_ids") or [] if str(item).strip()]
        if point_ids and str(row.get("status") or "") != "completed":
            pending[str(collection)] = point_ids
    return pending


def _pipeline_summary(result: dict[str, Any], *, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    stage_status: dict[str, str] = {
        "bronze": "pending",
        "silver": "pending",
        "gold": "pending",
        "judge": "pending",
        "topology": "pending",
    }
    for event in events or []:
        stage = str(event.get("pipeline_stage") or "")
        status = str(event.get("status") or "")
        if stage in stage_status and status:
            stage_status[stage] = status
    if result.get("storage_key"):
        stage_status["bronze"] = "completed"
    if result.get("persisted"):
        stage_status["silver"] = "completed"
    if str(result.get("repair_status") or "") in {"applied", "no_change"}:
        stage_status["bronze"] = "completed"
        stage_status["silver"] = "completed"
    index_result = result.get("index") if isinstance(result.get("index"), dict) else {}
    if index_result:
        stage_status["gold"] = "deferred" if index_result.get("status") == "deferred" else "completed"
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    if quality:
        if quality.get("state") == "gold_ready":
            stage_status["judge"] = "completed"
        elif quality.get("state") == "blocked":
            stage_status["judge"] = "failed"
        else:
            stage_status["judge"] = "deferred"
    topology = result.get("topology") if isinstance(result.get("topology"), dict) else {}
    topology_payload = _topology_event_payload(topology) if topology else {}
    if topology_payload:
        topology_status = str(topology_payload.get("status") or "pending")
        stage_status["topology"] = "completed" if topology_status == "ready" else topology_status
    if "failed" in stage_status.values():
        overall_status = "failed"
    elif "deferred" in stage_status.values():
        overall_status = "deferred"
    elif all(status == "completed" for status in stage_status.values()):
        overall_status = "completed"
    else:
        overall_status = "running"
    return {
        "overall_status": overall_status,
        "stages": stage_status,
        "missing_stages": [stage for stage, status in stage_status.items() if status == "pending"],
    }


def _refresh_gold_index_verification(
    connection: Any,
    settings: Any,
    *,
    source_scope: str,
    document_source_id: str = "",
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    collection = settings.qdrant_collection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              ds.id::text,
              ds.filename,
              ds.metadata,
              count(DISTINCT dc.id)::int AS chunk_count,
              count(DISTINCT qie.chunk_id)::int AS indexed_count
            FROM document_sources ds
            LEFT JOIN parsed_documents pd ON pd.document_source_id = ds.id
            LEFT JOIN document_chunks dc ON dc.parsed_document_id = pd.id
            LEFT JOIN qdrant_index_entries qie
              ON qie.chunk_id = dc.id AND qie.collection = %s
            WHERE ds.source_scope = %s
              AND (%s = '' OR ds.id = %s::uuid)
            GROUP BY ds.id, ds.filename, ds.metadata
            ORDER BY ds.created_at DESC
            """,
            (collection, source_scope, document_source_id, document_source_id or None),
        )
        rows = cursor.fetchall()
        for source_id, filename, metadata, chunk_count, indexed_count in rows:
            meta = dict(metadata or {})
            run = meta.get("gold_build_run")
            if not isinstance(run, dict):
                continue
            index_result = {
                "collection": collection,
                "source_scope": source_scope,
                "candidate_count": int(chunk_count or 0),
                "indexed_count": int(indexed_count or 0),
            }
            refreshed_run = with_index_verification(run, index_result=index_result)
            cursor.execute(
                """
                UPDATE document_sources
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                WHERE id = %s::uuid
                """,
                (json.dumps({"gold_build_run": refreshed_run}, ensure_ascii=False), source_id),
            )
            updated.append(
                {
                    "document_source_id": source_id,
                    "filename": str(filename or ""),
                    "chunk_count": int(chunk_count or 0),
                    "indexed_chunk_count": int(indexed_count or 0),
                    "gold_build_run": refreshed_run,
                }
            )
    return updated


def _index_gate_from_updated_documents(
    settings: Any,
    *,
    document_source_id: str,
    updated_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    document = next(
        (item for item in updated_documents if str(item.get("document_source_id") or "") == document_source_id),
        updated_documents[0] if updated_documents else {},
    )
    candidate_count = int(document.get("chunk_count") or 0)
    indexed_count = int(document.get("indexed_chunk_count") or 0)
    result: dict[str, Any] = {
        "collection": settings.qdrant_collection,
        "document_source_id": document_source_id,
        "candidate_count": candidate_count,
        "indexed_count": indexed_count,
    }
    if candidate_count <= 0 or indexed_count < candidate_count:
        result.update(
            {
                "status": "deferred",
                "retryable": True,
                "error": "Qdrant 색인이 chunk 수와 맞지 않습니다.",
            }
        )
    return result


def build_upload_ingest_response(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    emit_event: Any | None = None,
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    if emit_event:
        emit_event("received", {"filename": str(payload.get("file_name") or "")})
    source_path, storage_key, byte_size = _store_uploaded_file(root_dir, payload)
    if emit_event:
        emit_event("source_stored", {"storage_key": storage_key, "byte_size": byte_size})
        emit_event("parse_start", {"filename": str(payload.get("file_name") or "")})
    parsed = parse_upload_document(source_path, image_describer=build_qwen_image_describer(settings))
    if emit_event:
        emit_event(
            "parsed",
            {
                "filename": parsed.filename,
                "block_count": len(parsed.blocks),
                "asset_count": len(parsed.assets),
                "warning_count": len(parsed.warnings),
            },
        )
    dry_run = _bool_payload(payload.get("dry_run"), default=False)
    source_scope = str(payload.get("source_scope") or "user_upload").strip() or "user_upload"
    auto_repair = (
        _bool_payload(payload.get("auto_repair"), default=False)
        and not dry_run
        and source_scope == "user_upload"
    )
    auto_repairs: list[dict[str, Any]] = []
    if auto_repair:
        text_repair = repair_pdf_text_artifacts(parsed.markdown) if _parsed_document_is_pdf(parsed) else None
        if text_repair and text_repair.changed:
            if emit_event:
                emit_event(
                    "repair_start",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "pdf_text",
                        "changed_block_count": text_repair.changed_block_count,
                    },
                )
            parsed = rebuild_parsed_document_from_markdown(
                parsed,
                text_repair.repaired_markdown,
                metadata={
                    "pdf_text_repair": {
                        "source": "deterministic_v1",
                        "trigger": "upload_auto_repair",
                        "changed_block_count": text_repair.changed_block_count,
                        "applied_at": _utc_iso(),
                        "diff_summary": [block.to_dict() for block in text_repair.diff_summary],
                    }
                },
                warnings=tuple(dict.fromkeys((*parsed.warnings, "pdf_text_repair_applied"))),
            )
            auto_repairs.append(
                {
                    "kind": "pdf_text",
                    "changed_block_count": text_repair.changed_block_count,
                    "diff_summary": [block.to_dict() for block in text_repair.diff_summary],
                }
            )
            if emit_event:
                emit_event(
                    "pdf_text_repaired",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "pdf_text",
                        "changed_block_count": text_repair.changed_block_count,
                        "block_count": len(parsed.blocks),
                    },
                )
        code_repair = repair_unfenced_code_blocks(parsed.markdown)
        if code_repair.changed:
            if emit_event:
                emit_event(
                    "repair_start",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "code_block",
                        "changed_block_count": code_repair.changed_block_count,
                    },
                )
            parsed = rebuild_parsed_document_from_markdown(
                parsed,
                code_repair.repaired_markdown,
                metadata={
                    "code_block_repair": {
                        "source": "deterministic_v1",
                        "trigger": "upload_auto_repair",
                        "changed_block_count": code_repair.changed_block_count,
                        "applied_at": _utc_iso(),
                        "diff_summary": [block.to_dict() for block in code_repair.diff_summary],
                    }
                },
                warnings=tuple(dict.fromkeys((*parsed.warnings, "code_block_repair_applied"))),
            )
            auto_repairs.append(
                {
                    "kind": "code_block",
                    "changed_block_count": code_repair.changed_block_count,
                    "diff_summary": [block.to_dict() for block in code_repair.diff_summary],
                }
            )
            if emit_event:
                emit_event(
                    "code_block_repaired",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "code_block",
                        "changed_block_count": code_repair.changed_block_count,
                        "block_count": len(parsed.blocks),
                    },
                )
        page_repair = repair_page_stub_headings(parsed.markdown)
        if page_repair.changed:
            if emit_event:
                emit_event(
                    "repair_start",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "page_stub",
                        "changed_block_count": page_repair.changed_block_count,
                    },
                )
            parsed = rebuild_parsed_document_from_markdown(
                parsed,
                page_repair.repaired_markdown,
                metadata={
                    "page_stub_repair": {
                        "source": "deterministic_v1",
                        "trigger": "upload_auto_repair",
                        "changed_block_count": page_repair.changed_block_count,
                        "applied_at": _utc_iso(),
                        "diff_summary": [block.to_dict() for block in page_repair.diff_summary],
                    }
                },
                warnings=tuple(dict.fromkeys((*parsed.warnings, "page_stub_repair_applied"))),
            )
            auto_repairs.append(
                {
                    "kind": "page_stub",
                    "changed_block_count": page_repair.changed_block_count,
                    "diff_summary": [block.to_dict() for block in page_repair.diff_summary],
                }
            )
            if emit_event:
                emit_event(
                    "page_stubs_repaired",
                    {
                        "filename": parsed.filename,
                        "repair_kind": "page_stub",
                        "changed_block_count": page_repair.changed_block_count,
                        "block_count": len(parsed.blocks),
                    },
                )
    if emit_event:
        emit_event("chunk_start", {"block_count": len(parsed.blocks), "asset_count": len(parsed.assets)})
    chunks = build_document_chunks(
        parsed,
        max_chars=_int_payload(payload.get("chunk_max_chars"), default=1800),
        overlap_blocks=_int_payload(payload.get("chunk_overlap_blocks"), default=1),
    )
    if emit_event:
        emit_event("chunked", {"chunk_count": len(chunks)})
    created_by = str(payload.get("created_by") or "").strip()
    visibility = str(payload.get("visibility") or "").strip()
    gold_candidate = prepare_upload_gold_build_candidate(
        parsed,
        chunks,
        source_scope=source_scope,
        dry_run=dry_run,
    )
    parsed = gold_candidate.parsed
    chunks = gold_candidate.chunks
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "filename": parsed.filename,
        "storage_key": storage_key,
        "byte_size": byte_size,
        "document_format": parsed.document_format,
        "mime_type": parsed.mime_type,
        "sha256": parsed.sha256,
        "block_count": len(parsed.blocks),
        "asset_count": len(parsed.assets),
        "chunk_count": len(chunks),
        "owner_user_id": created_by,
        "repository_id": str(payload.get("repository_id") or "").strip(),
        "visibility": visibility or ("private_user" if created_by else "workspace_shared"),
        "source_scope": source_scope,
        "warnings": list(parsed.warnings),
        "auto_repairs": auto_repairs,
        "sections": [list(chunk.section_path) for chunk in chunks if chunk.section_path],
        "gold_build_run": gold_candidate.run,
    }
    if dry_run:
        if emit_event:
            emit_event("dry_run_done", {"chunk_count": len(chunks)})
        return result

    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for upload ingestion")

    import psycopg

    stored_asset_files = store_parsed_asset_files(settings.object_storage_dir, parsed)
    try:
        with psycopg.connect(database_url) as connection:
            if emit_event:
                emit_event("persist_start", {"chunk_count": len(chunks), "asset_file_count": len(stored_asset_files)})
            persisted = persist_parsed_upload_document(
                connection,
                parsed,
                chunks,
                tenant_slug=str(payload.get("tenant_slug") or "public"),
                tenant_name=str(payload.get("tenant_name") or "Public"),
                workspace_slug=str(payload.get("workspace_slug") or "default"),
                workspace_name=str(payload.get("workspace_name") or "Default"),
                storage_key=storage_key,
                created_by=created_by,
                repository_id=str(payload.get("repository_id") or ""),
                repository_slug=str(payload.get("repository_slug") or ""),
                repository_title=str(payload.get("repository_title") or ""),
                repository_kind=str(payload.get("repository_kind") or ""),
                visibility=visibility,
                source_scope=source_scope,
                gold_build_run=result["gold_build_run"],
            )
            result["repository_id"] = persisted.repository_id
            result["persisted"] = {
                "document_source_id": persisted.document_source_id,
                "document_version_id": persisted.document_version_id,
                "parse_job_id": persisted.parse_job_id,
                "parsed_document_id": persisted.parsed_document_id,
                "repository_id": persisted.repository_id,
                "block_count": len(persisted.block_ids),
                "asset_count": len(persisted.asset_ids),
                "chunk_count": len(persisted.chunk_ids),
                "asset_file_count": len(stored_asset_files),
            }
            if emit_event:
                emit_event(
                    "persisted",
                    {
                        "document_source_id": persisted.document_source_id,
                        "parsed_document_id": persisted.parsed_document_id,
                        "repository_id": persisted.repository_id,
                        "chunk_count": len(persisted.chunk_ids),
                        "asset_file_count": len(stored_asset_files),
                    },
                )
            if _bool_payload(payload.get("index"), default=False):
                if emit_event:
                    emit_event(
                        "index_start",
                        {
                            "chunk_count": len(chunks),
                            "source_scope": source_scope,
                            "document_source_id": persisted.document_source_id,
                        },
                    )
                result["index"] = _index_pending_with_retry(
                    settings,
                    connection,
                    payload,
                    source_scope=source_scope,
                    document_source_id=persisted.document_source_id,
                    chunk_count=len(chunks),
                )
                if result["index"].get("status") == "deferred":
                    if emit_event:
                        emit_event("index_deferred", result["index"])
                    result["warnings"].append(
                        "Qdrant 인덱싱이 보류되었습니다. 문서는 저장됐고 임베딩 서버 복구 후 재인덱싱하면 됩니다."
                    )
                elif emit_event:
                    emit_event("indexed", result["index"])
                result["gold_build_run"] = with_index_verification(
                    result["gold_build_run"],
                    index_result=result["index"],
                )
                update_document_source_gold_build_run(
                    connection,
                    document_source_id=persisted.document_source_id,
                    gold_build_run=result["gold_build_run"],
                )
    except Exception:
        remove_stored_asset_files(stored_asset_files)
        raise
    if result.get("persisted"):
        persisted = result["persisted"]
        if emit_event:
            emit_event(
                "topology_start",
                {
                    "document_source_id": persisted.get("document_source_id", ""),
                    "parsed_document_id": persisted.get("parsed_document_id", ""),
                    "source_scope": source_scope,
                },
            )
        try:
            with psycopg.connect(database_url) as topology_connection:
                topology = get_or_create_document_topology_snapshot_by_id(
                    topology_connection,
                    document_source_id=str(persisted.get("document_source_id") or ""),
                    parsed_document_id=str(persisted.get("parsed_document_id") or ""),
                    force_refresh=True,
                )
            topology_payload = _topology_event_payload(topology)
            result["topology"] = topology
            if topology_payload.get("status") == "ready":
                if emit_event:
                    emit_event("topology_ready", topology_payload)
            else:
                result["warnings"].append(
                    "Topology 생성이 보류되었습니다. 문서는 저장됐고 topology snapshot은 재시도할 수 있습니다."
                )
                if emit_event:
                    emit_event("topology_deferred", topology_payload)
        except Exception as exc:  # noqa: BLE001
            topology_payload = {
                "status": "failed",
                "state": "failed",
                "retryable": True,
                "document_source_id": str(persisted.get("document_source_id") or ""),
                "parsed_document_id": str(persisted.get("parsed_document_id") or ""),
                "error": str(exc),
            }
            result["topology"] = topology_payload
            result["warnings"].append(
                f"Topology 생성이 실패했습니다. 문서는 저장됐고 snapshot만 재시도하면 됩니다: {exc}"
            )
            if emit_event:
                emit_event("topology_failed", topology_payload)
        if emit_event:
            emit_event(
                "judge_start",
                {
                    "document_source_id": persisted.get("document_source_id", ""),
                    "parsed_document_id": persisted.get("parsed_document_id", ""),
                    "source_scope": source_scope,
                },
            )
        try:
            with psycopg.connect(database_url) as quality_connection:
                quality_document = load_document_topology_source(
                    quality_connection,
                    document_source_id=str(persisted.get("document_source_id") or ""),
                    parsed_document_id=str(persisted.get("parsed_document_id") or ""),
                )
                if quality_document is None:
                    raise RuntimeError("quality source document was not found")
                quality = build_document_quality_snapshot(
                    quality_document,
                    topology=result.get("topology") if isinstance(result.get("topology"), dict) else None,
                    gold_build_run=result.get("gold_build_run") if isinstance(result.get("gold_build_run"), dict) else None,
                )
                quality = upsert_document_quality_snapshot(quality_connection, quality=quality)
                result["quality"] = quality
                result["gold_build_run"] = merge_quality_into_gold_run(result["gold_build_run"], quality)
                update_document_source_gold_build_run(
                    quality_connection,
                    document_source_id=str(persisted.get("document_source_id") or ""),
                    gold_build_run=result["gold_build_run"],
                )
                quality_connection.commit()
            if emit_event:
                emit_event(
                    "judge_completed",
                    {
                        "document_source_id": persisted.get("document_source_id", ""),
                        "parsed_document_id": persisted.get("parsed_document_id", ""),
                        "quality_state": result.get("quality", {}).get("state", ""),
                        "quality_score": result.get("quality", {}).get("score", 0),
                        "blocker_count": len(result.get("quality", {}).get("blockers") or []),
                    },
                )
            if result.get("quality", {}).get("state") != "gold_ready":
                result["warnings"].append(str(result["gold_build_run"].get("blocking_message") or "품질 판정서 보류"))
        except Exception as exc:  # noqa: BLE001
            result["quality"] = {
                "state": "blocked",
                "score": 0,
                "blockers": [{"id": "quality_recheck_failed", "label": "품질 판정 실패", "summary": str(exc)}],
                "warnings": [],
                "error": str(exc),
            }
            result["gold_build_run"] = merge_quality_into_gold_run(result["gold_build_run"], result["quality"])
            result["warnings"].append(f"품질 판정서 생성이 실패했습니다: {exc}")
            if emit_event:
                emit_event(
                    "judge_completed",
                    {
                        "document_source_id": persisted.get("document_source_id", ""),
                        "parsed_document_id": persisted.get("parsed_document_id", ""),
                        "quality_state": "blocked",
                        "error": str(exc),
                    },
                )
    if emit_event:
        emit_event(
            "complete",
            {
                "filename": result["filename"],
                "status": result.get("gold_build_run", {}).get("status"),
                "pipeline_summary": _pipeline_summary(result),
            },
        )
    return result


def build_upload_index_retry_response(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for upload index retry")
    source_scope = str(payload.get("source_scope") or "user_upload").strip() or "user_upload"
    document_source_id = _required_uuid_payload(payload, "document_source_id")
    owner_user_id = _payload_owner_user_id(payload)

    import psycopg

    with psycopg.connect(database_url) as connection:
        loaded = load_parsed_document_for_repair(connection, document_source_id=document_source_id)
        _assert_loaded_document_owner(loaded, owner_user_id)
        if loaded is None:
            raise ValueError("document_source_id was not found")
        pending_cleanup = _pending_cleanup_map(
            loaded.parsed.metadata.get("pending_qdrant_cleanup")
        )
        cleanup_result: dict[str, Any] | None = None
        if pending_cleanup:
            cleanup_result = _delete_qdrant_points_by_collection(settings, pending_cleanup)
            update_document_source_metadata(
                connection,
                document_source_id=document_source_id,
                metadata_patch={
                    "pending_qdrant_cleanup": None if cleanup_result["status"] == "completed" else cleanup_result
                },
            )
            connection.commit()
            if cleanup_result["status"] == "deferred":
                index_result = _deferred_index_result(
                    settings,
                    payload,
                    source_scope=source_scope,
                    document_source_id=document_source_id,
                    chunk_count=_int_payload(payload.get("chunk_count"), default=100),
                    error=RuntimeError("stale Qdrant point cleanup is still pending"),
                )
                return {
                    "ok": False,
                    "source_scope": source_scope,
                    "document_source_id": document_source_id,
                    "index": index_result,
                    "qdrant_cleanup": cleanup_result,
                    "updated_documents": [],
                    "pending_documents": [
                        {
                            "document_source_id": document_source_id,
                            "filename": loaded.parsed.filename if loaded is not None else "",
                            "chunk_count": 0,
                            "indexed_chunk_count": 0,
                        }
                    ],
                }
        index_result = _index_pending_with_retry(
            settings,
            connection,
            payload,
            source_scope=source_scope,
            document_source_id=document_source_id,
            chunk_count=_int_payload(payload.get("chunk_count"), default=100),
        )
        updated_documents = _refresh_gold_index_verification(
            connection,
            settings,
            source_scope=source_scope,
            document_source_id=document_source_id,
        )
        topology = get_or_create_document_topology_snapshot_by_id(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=str(payload.get("parsed_document_id") or ""),
            force_refresh=True,
        )
        connection.commit()

    pending_documents = [
        item
        for item in updated_documents
        if int(item.get("chunk_count") or 0) > int(item.get("indexed_chunk_count") or 0)
    ]
    return {
        "ok": not pending_documents and index_result.get("status") != "deferred",
        "source_scope": source_scope,
        "document_source_id": document_source_id,
        "index": index_result,
        **({"qdrant_cleanup": cleanup_result} if cleanup_result else {}),
        "topology": topology,
        "updated_documents": updated_documents,
        "pending_documents": pending_documents,
    }


def _quality_recheck_for_document(
    connection: Any,
    *,
    document_source_id: str,
    parsed_document_id: str = "",
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = load_document_topology_source(
        connection,
        document_source_id=document_source_id,
        parsed_document_id=parsed_document_id,
    )
    if document is None:
        raise ValueError("document_source_id was not found")
    if topology is None:
        topology = get_or_create_document_topology_snapshot_by_id(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=str(document.get("parsed_document_id") or parsed_document_id),
            force_refresh=False,
        )
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    gold_build_run = metadata.get("gold_build_run") if isinstance(metadata.get("gold_build_run"), dict) else {}
    quality = build_document_quality_snapshot(document, topology=topology, gold_build_run=gold_build_run)
    quality = upsert_document_quality_snapshot(connection, quality=quality)
    updated_gold_run = merge_quality_into_gold_run(gold_build_run, quality)
    update_document_source_gold_build_run(
        connection,
        document_source_id=document_source_id,
        gold_build_run=updated_gold_run,
    )
    return {
        "document_source_id": document_source_id,
        "parsed_document_id": str(document.get("parsed_document_id") or parsed_document_id),
        "quality": quality,
        "gold_build_run": updated_gold_run,
    }


def build_upload_topology_retry_response(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for topology retry")
    document_source_id = _required_uuid_payload(payload, "document_source_id")
    parsed_document_id = str(payload.get("parsed_document_id") or "").strip()
    owner_user_id = _payload_owner_user_id(payload)

    import psycopg

    with psycopg.connect(database_url) as connection:
        loaded = load_parsed_document_for_repair(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        _assert_loaded_document_owner(loaded, owner_user_id)
        if loaded is None:
            raise ValueError("document_source_id was not found")
        parsed_document_id = loaded.parsed_document_id
        topology = get_or_create_document_topology_snapshot_by_id(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            force_refresh=True,
        )
        quality_result = _quality_recheck_for_document(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            topology=topology,
        )
        updated_documents = _refresh_gold_index_verification(
            connection,
            settings,
            source_scope=loaded.source_scope,
            document_source_id=document_source_id,
        )
        connection.commit()
    topology_payload = _topology_event_payload(topology)
    index_result = _index_gate_from_updated_documents(
        settings,
        document_source_id=document_source_id,
        updated_documents=updated_documents,
    )
    gold_build_run = next(
        (
            item.get("gold_build_run")
            for item in updated_documents
            if str(item.get("document_source_id") or "") == document_source_id and isinstance(item.get("gold_build_run"), dict)
        ),
        quality_result["gold_build_run"],
    )
    return {
        "ok": (
            topology_payload.get("status") == "ready"
            and quality_result["quality"].get("state") == "gold_ready"
            and index_result.get("status") != "deferred"
            and gold_build_run.get("status") == "gold"
        ),
        "document_source_id": document_source_id,
        "parsed_document_id": quality_result.get("parsed_document_id") or parsed_document_id,
        "topology": topology,
        "topology_status": topology_payload,
        "index": index_result,
        "quality": quality_result["quality"],
        "gold_build_run": gold_build_run,
    }


def build_upload_quality_recheck_response(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for quality recheck")
    document_source_id = _required_uuid_payload(payload, "document_source_id")
    parsed_document_id = str(payload.get("parsed_document_id") or "").strip()
    owner_user_id = _payload_owner_user_id(payload)

    import psycopg

    with psycopg.connect(database_url) as connection:
        loaded = load_parsed_document_for_repair(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        _assert_loaded_document_owner(loaded, owner_user_id)
        if loaded is None:
            raise ValueError("document_source_id was not found")
        parsed_document_id = loaded.parsed_document_id
        quality_result = _quality_recheck_for_document(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        updated_documents = _refresh_gold_index_verification(
            connection,
            settings,
            source_scope=loaded.source_scope,
            document_source_id=document_source_id,
        )
        connection.commit()
    index_result = _index_gate_from_updated_documents(
        settings,
        document_source_id=document_source_id,
        updated_documents=updated_documents,
    )
    gold_build_run = next(
        (
            item.get("gold_build_run")
            for item in updated_documents
            if str(item.get("document_source_id") or "") == document_source_id and isinstance(item.get("gold_build_run"), dict)
        ),
        quality_result["gold_build_run"],
    )
    return {
        "ok": (
            quality_result["quality"].get("state") == "gold_ready"
            and index_result.get("status") != "deferred"
            and gold_build_run.get("status") == "gold"
        ),
        **quality_result,
        "index": index_result,
        "gold_build_run": gold_build_run,
    }


def build_upload_code_block_repair_response(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    emit_event: Any | None = None,
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for code block repair")
    document_source_id = _required_uuid_payload(payload, "document_source_id")
    parsed_document_id = str(payload.get("parsed_document_id") or "").strip()
    dry_run = _bool_payload(payload.get("dry_run"), default=True)
    collection = str(payload.get("collection") or "").strip() or settings.qdrant_collection
    owner_user_id = _payload_owner_user_id(payload)

    import psycopg

    with psycopg.connect(database_url) as connection:
        loaded = load_parsed_document_for_repair(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        if loaded is None:
            raise ValueError("document_source_id was not found")
        _assert_loaded_document_owner(loaded, owner_user_id)
        if loaded.source_scope != "user_upload":
            raise ValueError("code block repair v1 is only available for user uploads")
        parsed_document_id = loaded.parsed_document_id
        text_repair = repair_pdf_text_artifacts(loaded.parsed.markdown) if _parsed_document_is_pdf(loaded.parsed) else None
        code_repair = repair_unfenced_code_blocks(
            text_repair.repaired_markdown if text_repair else loaded.parsed.markdown
        )
        text_repair_changed = bool(text_repair and text_repair.changed)
        text_changed_block_count = text_repair.changed_block_count if text_repair else 0
        repair_changed = text_repair_changed or code_repair.changed
        repair_changed_block_count = text_changed_block_count + code_repair.changed_block_count
        repair_diff_summary: list[dict[str, object]] = []
        if text_repair:
            repair_diff_summary.extend(block.to_dict() for block in text_repair.diff_summary)
        repair_diff_summary.extend(block.to_dict() for block in code_repair.diff_summary)
        repair_kind = (
            "pdf_text+code_block"
            if text_repair_changed and code_repair.changed
            else "pdf_text"
            if text_repair_changed
            else "code_block"
        )
        repair_metadata: dict[str, Any] = {}
        repair_warnings = list(loaded.parsed.warnings)
        if text_repair_changed and text_repair:
            repair_metadata["pdf_text_repair"] = {
                "source": "deterministic_v1",
                "changed_block_count": text_repair.changed_block_count,
                "applied_at": _utc_iso(),
                "diff_summary": [block.to_dict() for block in text_repair.diff_summary],
            }
            repair_warnings.append("pdf_text_repair_applied")
        if code_repair.changed:
            repair_metadata["code_block_repair"] = {
                "source": "deterministic_v1",
                "changed_block_count": code_repair.changed_block_count,
                "applied_at": _utc_iso(),
                "diff_summary": [block.to_dict() for block in code_repair.diff_summary],
            }
            repair_warnings.append("code_block_repair_applied")
        existing_quality = load_document_quality_snapshot(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        existing_topology = load_document_topology_snapshot_summary(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )

    base_result: dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "repair_status": "dry_run_changed" if dry_run and repair_changed else "no_change",
        "repair_kind": repair_kind,
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "source_scope": loaded.source_scope,
        "filename": loaded.parsed.filename,
        "changed_block_count": repair_changed_block_count,
        "diff_summary": repair_diff_summary,
        "quality": existing_quality,
        "topology": existing_topology,
    }
    if dry_run:
        base_result["ok"] = (
            bool(existing_quality and existing_quality.get("state") == "gold_ready")
            and _topology_event_payload(existing_topology if isinstance(existing_topology, dict) else None).get("status") == "ready"
            and bool(existing_quality.get("metadata", {}).get("gold_build_status") == "gold" if isinstance(existing_quality, dict) else False)
        )
        base_result["pipeline_summary"] = _pipeline_summary(base_result)
        return base_result
    if not repair_changed:
        with psycopg.connect(database_url) as connection:
            updated_documents = _refresh_gold_index_verification(
                connection,
                settings,
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
            )
            updated_document = updated_documents[0] if updated_documents else {}
            topology = get_or_create_document_topology_snapshot_by_id(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                force_refresh=False,
            )
            quality_result = _quality_recheck_for_document(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                topology=topology,
            )
            connection.commit()
        chunk_count = int(updated_document.get("chunk_count") or 0)
        indexed_count = int(updated_document.get("indexed_chunk_count") or 0)
        base_result["quality"] = quality_result["quality"]
        base_result["topology"] = topology
        base_result["gold_build_run"] = quality_result["gold_build_run"]
        base_result["index"] = {
            "collection": settings.qdrant_collection,
            "source_scope": loaded.source_scope,
            "document_source_id": document_source_id,
            "candidate_count": chunk_count,
            "indexed_count": indexed_count,
            **({"status": "deferred"} if chunk_count <= 0 or indexed_count < chunk_count else {}),
        }
        base_result["ok"] = (
            quality_result["quality"].get("state") == "gold_ready"
            and chunk_count > 0
            and indexed_count >= chunk_count
            and _topology_event_payload(topology).get("status") == "ready"
            and quality_result["gold_build_run"].get("status") == "gold"
        )
        base_result["pipeline_summary"] = _pipeline_summary(base_result)
        return base_result

    if emit_event:
        emit_event(
            "repair_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "filename": loaded.parsed.filename,
                "repair_kind": repair_kind,
                "changed_block_count": repair_changed_block_count,
            },
        )
    repaired = rebuild_parsed_document_from_markdown(
        loaded.parsed,
        code_repair.repaired_markdown,
        metadata=repair_metadata,
        warnings=tuple(dict.fromkeys(repair_warnings)),
    )
    chunks = build_document_chunks(
        repaired,
        max_chars=_int_payload(payload.get("chunk_max_chars"), default=1800),
        overlap_blocks=_int_payload(payload.get("chunk_overlap_blocks"), default=1),
    )
    gold_candidate = prepare_upload_gold_build_candidate(
        repaired,
        chunks,
        source_scope=loaded.source_scope,
        dry_run=False,
    )
    repaired = gold_candidate.parsed
    chunks = gold_candidate.chunks
    result: dict[str, Any] = {
        **base_result,
        "dry_run": False,
        "repair_status": "applied",
        "quality": {},
        "topology": {},
        "gold_build_run": gold_candidate.run,
        "block_count": len(repaired.blocks),
        "chunk_count": len(chunks),
    }

    with psycopg.connect(database_url) as connection:
        replaced = replace_parsed_document_content(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            parsed=repaired,
            chunks=chunks,
            storage_key=loaded.storage_key,
            owner_user_id=loaded.owner_user_id,
            repository_id=loaded.repository_id,
            visibility=loaded.visibility,
            source_scope=loaded.source_scope,
            gold_build_run=result["gold_build_run"],
            collection=collection,
        )
        connection.commit()
        if emit_event:
            event_payload = {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "block_count": len(replaced.block_ids),
                "chunk_count": len(replaced.chunk_ids),
                "old_qdrant_point_count": sum(
                    len(point_ids) for point_ids in replaced.old_qdrant_points_by_collection.values()
                ),
            }
            if text_repair_changed and text_repair:
                emit_event(
                    "pdf_text_repaired",
                    {
                        **event_payload,
                        "repair_kind": "pdf_text",
                        "changed_block_count": text_repair.changed_block_count,
                    },
                )
            if code_repair.changed:
                emit_event(
                    "code_block_repaired",
                    {
                        **event_payload,
                        "repair_kind": "code_block",
                        "changed_block_count": code_repair.changed_block_count,
                    },
                )
        cleanup_result = _delete_qdrant_points_by_collection(
            settings,
            replaced.old_qdrant_points_by_collection,
        )
        cleanup_failed = cleanup_result["status"] == "deferred"
        update_document_source_metadata(
            connection,
            document_source_id=document_source_id,
            metadata_patch={
                "pending_qdrant_cleanup": cleanup_result if cleanup_failed else None,
            },
        )
        result["qdrant_cleanup"] = cleanup_result
        if emit_event:
            emit_event(
                "reindex_start",
                {
                    "document_source_id": document_source_id,
                    "parsed_document_id": parsed_document_id,
                    "chunk_count": len(chunks),
                    "qdrant_cleanup": cleanup_result,
                },
            )
        if cleanup_failed:
            result["index"] = _deferred_index_result(
                settings,
                {"collection": collection},
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
                chunk_count=len(chunks),
                error=RuntimeError(f"stale Qdrant point cleanup failed: {cleanup_result.get('error') or ''}"),
            )
            if emit_event:
                emit_event("index_deferred", result["index"])
        else:
            result["index"] = _index_pending_with_retry(
                settings,
                connection,
                {**payload, "collection": collection},
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
                chunk_count=len(chunks),
            )
            if result["index"].get("status") == "deferred":
                if emit_event:
                    emit_event("index_deferred", result["index"])
            elif emit_event:
                emit_event("indexed", result["index"])
        result["gold_build_run"] = with_index_verification(
            result["gold_build_run"],
            index_result=result["index"],
        )
        update_document_source_gold_build_run(
            connection,
            document_source_id=document_source_id,
            gold_build_run=result["gold_build_run"],
        )
        connection.commit()

    if emit_event:
        emit_event(
            "topology_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "source_scope": loaded.source_scope,
            },
        )
    try:
        with psycopg.connect(database_url) as topology_connection:
            topology = get_or_create_document_topology_snapshot_by_id(
                topology_connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                force_refresh=True,
            )
            topology_connection.commit()
        result["topology"] = topology
        topology_payload = _topology_event_payload(topology)
        if topology_payload.get("status") == "ready":
            if emit_event:
                emit_event("topology_ready", topology_payload)
        elif emit_event:
            emit_event("topology_deferred", topology_payload)
    except Exception as exc:  # noqa: BLE001
        result["topology"] = {
            "status": "failed",
            "state": "failed",
            "retryable": True,
            "document_source_id": document_source_id,
            "parsed_document_id": parsed_document_id,
            "error": str(exc),
        }
        if emit_event:
            emit_event("topology_failed", result["topology"])

    if emit_event:
        emit_event(
            "judge_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "source_scope": loaded.source_scope,
            },
        )
    with psycopg.connect(database_url) as quality_connection:
        quality_result = _quality_recheck_for_document(
            quality_connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            topology=result.get("topology") if isinstance(result.get("topology"), dict) else None,
        )
        result["quality"] = quality_result["quality"]
        if isinstance(quality_result.get("gold_build_run"), dict):
            result["gold_build_run"] = quality_result["gold_build_run"]
        else:
            result["gold_build_run"] = merge_quality_into_gold_run(result["gold_build_run"], result["quality"])
        update_document_source_gold_build_run(
            quality_connection,
            document_source_id=document_source_id,
            gold_build_run=result["gold_build_run"],
        )
        quality_connection.commit()
    if emit_event:
        emit_event(
            "judge_completed",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "quality_state": result.get("quality", {}).get("state", ""),
                "quality_score": result.get("quality", {}).get("score", 0),
                "blocker_count": len(result.get("quality", {}).get("blockers") or []),
            },
        )
        emit_event(
            "complete",
            {
                "filename": loaded.parsed.filename,
                "status": result.get("gold_build_run", {}).get("status"),
                "pipeline_summary": _pipeline_summary(result),
            },
        )
    result["ok"] = (
        result.get("quality", {}).get("state") == "gold_ready"
        and result.get("index", {}).get("status") != "deferred"
        and _topology_event_payload(result.get("topology") if isinstance(result.get("topology"), dict) else None).get("status") == "ready"
        and result.get("gold_build_run", {}).get("status") == "gold"
    )
    result["pipeline_summary"] = _pipeline_summary(result)
    return result


def build_upload_page_stub_repair_response(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    emit_event: Any | None = None,
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for page stub repair")
    document_source_id = _required_uuid_payload(payload, "document_source_id")
    parsed_document_id = str(payload.get("parsed_document_id") or "").strip()
    dry_run = _bool_payload(payload.get("dry_run"), default=True)
    collection = str(payload.get("collection") or "").strip() or settings.qdrant_collection
    owner_user_id = _payload_owner_user_id(payload)

    import psycopg

    with psycopg.connect(database_url) as connection:
        loaded = load_parsed_document_for_repair(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        if loaded is None:
            raise ValueError("document_source_id was not found")
        _assert_loaded_document_owner(loaded, owner_user_id)
        if loaded.source_scope != "user_upload":
            raise ValueError("page stub repair v1 is only available for user uploads")
        parsed_document_id = loaded.parsed_document_id
        repair = repair_page_stub_headings(loaded.parsed.markdown)
        existing_quality = load_document_quality_snapshot(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        existing_topology = load_document_topology_snapshot_summary(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )

    base_result: dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "repair_status": "dry_run_changed" if dry_run and repair.changed else "no_change",
        "repair_kind": "page_stub",
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "source_scope": loaded.source_scope,
        "filename": loaded.parsed.filename,
        "changed_block_count": repair.changed_block_count,
        "diff_summary": [block.to_dict() for block in repair.diff_summary],
        "quality": existing_quality,
        "topology": existing_topology,
    }
    if dry_run:
        base_result["ok"] = (
            bool(existing_quality and existing_quality.get("state") == "gold_ready")
            and _topology_event_payload(existing_topology if isinstance(existing_topology, dict) else None).get("status") == "ready"
            and bool(existing_quality.get("metadata", {}).get("gold_build_status") == "gold" if isinstance(existing_quality, dict) else False)
        )
        base_result["pipeline_summary"] = _pipeline_summary(base_result)
        return base_result
    if not repair.changed:
        with psycopg.connect(database_url) as connection:
            updated_documents = _refresh_gold_index_verification(
                connection,
                settings,
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
            )
            updated_document = updated_documents[0] if updated_documents else {}
            topology = get_or_create_document_topology_snapshot_by_id(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                force_refresh=False,
            )
            quality_result = _quality_recheck_for_document(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                topology=topology,
            )
            connection.commit()
        chunk_count = int(updated_document.get("chunk_count") or 0)
        indexed_count = int(updated_document.get("indexed_chunk_count") or 0)
        base_result["quality"] = quality_result["quality"]
        base_result["topology"] = topology
        base_result["gold_build_run"] = quality_result["gold_build_run"]
        base_result["index"] = {
            "collection": settings.qdrant_collection,
            "source_scope": loaded.source_scope,
            "document_source_id": document_source_id,
            "candidate_count": chunk_count,
            "indexed_count": indexed_count,
            **({"status": "deferred"} if chunk_count <= 0 or indexed_count < chunk_count else {}),
        }
        base_result["ok"] = (
            quality_result["quality"].get("state") == "gold_ready"
            and chunk_count > 0
            and indexed_count >= chunk_count
            and _topology_event_payload(topology).get("status") == "ready"
            and quality_result["gold_build_run"].get("status") == "gold"
        )
        base_result["pipeline_summary"] = _pipeline_summary(base_result)
        return base_result

    if emit_event:
        emit_event(
            "repair_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "filename": loaded.parsed.filename,
                "changed_block_count": repair.changed_block_count,
                "repair_kind": "page_stub",
            },
        )
    repaired = rebuild_parsed_document_from_markdown(
        loaded.parsed,
        repair.repaired_markdown,
        metadata={
            "page_stub_repair": {
                "source": "deterministic_v1",
                "changed_block_count": repair.changed_block_count,
                "applied_at": _utc_iso(),
                "diff_summary": [block.to_dict() for block in repair.diff_summary],
            }
        },
        warnings=tuple(dict.fromkeys((*loaded.parsed.warnings, "page_stub_repair_applied"))),
    )
    chunks = build_document_chunks(
        repaired,
        max_chars=_int_payload(payload.get("chunk_max_chars"), default=1800),
        overlap_blocks=_int_payload(payload.get("chunk_overlap_blocks"), default=1),
    )
    gold_candidate = prepare_upload_gold_build_candidate(
        repaired,
        chunks,
        source_scope=loaded.source_scope,
        dry_run=False,
    )
    repaired = gold_candidate.parsed
    chunks = gold_candidate.chunks
    result: dict[str, Any] = {
        **base_result,
        "dry_run": False,
        "repair_status": "applied",
        "quality": {},
        "topology": {},
        "gold_build_run": gold_candidate.run,
        "block_count": len(repaired.blocks),
        "chunk_count": len(chunks),
    }

    with psycopg.connect(database_url) as connection:
        replaced = replace_parsed_document_content(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            parsed=repaired,
            chunks=chunks,
            storage_key=loaded.storage_key,
            owner_user_id=loaded.owner_user_id,
            repository_id=loaded.repository_id,
            visibility=loaded.visibility,
            source_scope=loaded.source_scope,
            gold_build_run=result["gold_build_run"],
            collection=collection,
        )
        connection.commit()
        if emit_event:
            emit_event(
                "page_stubs_repaired",
                {
                    "document_source_id": document_source_id,
                    "parsed_document_id": parsed_document_id,
                    "changed_block_count": repair.changed_block_count,
                    "block_count": len(replaced.block_ids),
                    "chunk_count": len(replaced.chunk_ids),
                    "old_qdrant_point_count": sum(
                        len(point_ids) for point_ids in replaced.old_qdrant_points_by_collection.values()
                    ),
                },
            )
        cleanup_result = _delete_qdrant_points_by_collection(
            settings,
            replaced.old_qdrant_points_by_collection,
        )
        cleanup_failed = cleanup_result["status"] == "deferred"
        update_document_source_metadata(
            connection,
            document_source_id=document_source_id,
            metadata_patch={
                "pending_qdrant_cleanup": cleanup_result if cleanup_failed else None,
            },
        )
        result["qdrant_cleanup"] = cleanup_result
        if emit_event:
            emit_event(
                "reindex_start",
                {
                    "document_source_id": document_source_id,
                    "parsed_document_id": parsed_document_id,
                    "chunk_count": len(chunks),
                    "qdrant_cleanup": cleanup_result,
                },
            )
        if cleanup_failed:
            result["index"] = _deferred_index_result(
                settings,
                {"collection": collection},
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
                chunk_count=len(chunks),
                error=RuntimeError(f"stale Qdrant point cleanup failed: {cleanup_result.get('error') or ''}"),
            )
            if emit_event:
                emit_event("index_deferred", result["index"])
        else:
            result["index"] = _index_pending_with_retry(
                settings,
                connection,
                {**payload, "collection": collection},
                source_scope=loaded.source_scope,
                document_source_id=document_source_id,
                chunk_count=len(chunks),
            )
            if result["index"].get("status") == "deferred":
                if emit_event:
                    emit_event("index_deferred", result["index"])
            elif emit_event:
                emit_event("indexed", result["index"])
        result["gold_build_run"] = with_index_verification(
            result["gold_build_run"],
            index_result=result["index"],
        )
        update_document_source_gold_build_run(
            connection,
            document_source_id=document_source_id,
            gold_build_run=result["gold_build_run"],
        )
        connection.commit()

    if emit_event:
        emit_event(
            "topology_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "source_scope": loaded.source_scope,
            },
        )
    try:
        with psycopg.connect(database_url) as topology_connection:
            topology = get_or_create_document_topology_snapshot_by_id(
                topology_connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                force_refresh=True,
            )
            topology_connection.commit()
        result["topology"] = topology
        topology_payload = _topology_event_payload(topology)
        if topology_payload.get("status") == "ready":
            if emit_event:
                emit_event("topology_ready", topology_payload)
        elif emit_event:
            emit_event("topology_deferred", topology_payload)
    except Exception as exc:  # noqa: BLE001
        result["topology"] = {
            "status": "failed",
            "state": "failed",
            "retryable": True,
            "document_source_id": document_source_id,
            "parsed_document_id": parsed_document_id,
            "error": str(exc),
        }
        if emit_event:
            emit_event("topology_failed", result["topology"])

    if emit_event:
        emit_event(
            "judge_start",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "source_scope": loaded.source_scope,
            },
        )
    with psycopg.connect(database_url) as quality_connection:
        quality_result = _quality_recheck_for_document(
            quality_connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            topology=result.get("topology") if isinstance(result.get("topology"), dict) else None,
        )
        result["quality"] = quality_result["quality"]
        if isinstance(quality_result.get("gold_build_run"), dict):
            result["gold_build_run"] = quality_result["gold_build_run"]
        else:
            result["gold_build_run"] = merge_quality_into_gold_run(result["gold_build_run"], result["quality"])
        update_document_source_gold_build_run(
            quality_connection,
            document_source_id=document_source_id,
            gold_build_run=result["gold_build_run"],
        )
        quality_connection.commit()
    if emit_event:
        emit_event(
            "judge_completed",
            {
                "document_source_id": document_source_id,
                "parsed_document_id": parsed_document_id,
                "quality_state": result.get("quality", {}).get("state", ""),
                "quality_score": result.get("quality", {}).get("score", 0),
                "blocker_count": len(result.get("quality", {}).get("blockers") or []),
            },
        )
        emit_event(
            "complete",
            {
                "filename": loaded.parsed.filename,
                "status": result.get("gold_build_run", {}).get("status"),
                "pipeline_summary": _pipeline_summary(result),
            },
        )
    result["ok"] = (
        result.get("quality", {}).get("state") == "gold_ready"
        and result.get("index", {}).get("status") != "deferred"
        and _topology_event_payload(result.get("topology") if isinstance(result.get("topology"), dict) else None).get("status") == "ready"
        and result.get("gold_build_run", {}).get("status") == "gold"
    )
    result["pipeline_summary"] = _pipeline_summary(result)
    return result


def build_upload_pipeline_status_response(root_dir: Path, query: str, *, owner_user_id: str = "") -> dict[str, Any]:
    from urllib.parse import parse_qs

    settings = load_settings(root_dir)
    database_url = str(settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for pipeline status")
    params = parse_qs(query or "")
    document_source_id = str((params.get("document_source_id") or [""])[0]).strip()
    parsed_document_id = str((params.get("parsed_document_id") or [""])[0]).strip()
    run_id = str((params.get("run_id") or [""])[0]).strip()
    if not document_source_id and not parsed_document_id and not run_id:
        raise ValueError("document_source_id, parsed_document_id, or run_id is required")

    import psycopg

    with psycopg.connect(database_url) as connection:
        events = list_upload_pipeline_events(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            run_id=run_id,
            limit=300,
        )
        resolved_document_source_id = document_source_id or next((event["document_source_id"] for event in events if event.get("document_source_id")), "")
        resolved_parsed_document_id = parsed_document_id or next((event["parsed_document_id"] for event in events if event.get("parsed_document_id")), "")
        if resolved_document_source_id:
            loaded = load_parsed_document_for_repair(
                connection,
                document_source_id=resolved_document_source_id,
                parsed_document_id=resolved_parsed_document_id,
            )
            _assert_loaded_document_owner(loaded, owner_user_id)
            if loaded is None:
                raise ValueError("document_source_id was not found")
            resolved_document_source_id = loaded.document_source_id
            resolved_parsed_document_id = loaded.parsed_document_id
        quality = (
            load_document_quality_snapshot(
                connection,
                document_source_id=resolved_document_source_id,
                parsed_document_id=resolved_parsed_document_id,
            )
            if resolved_document_source_id
            else None
        )
        if quality:
            resolved_document_source_id = resolved_document_source_id or str(quality.get("document_source_id") or "")
            resolved_parsed_document_id = resolved_parsed_document_id or str(quality.get("parsed_document_id") or "")
        topology = (
            load_document_topology_snapshot_summary(
                connection,
                document_source_id=resolved_document_source_id,
                parsed_document_id=resolved_parsed_document_id,
            )
            if resolved_document_source_id and resolved_parsed_document_id
            else None
        )
    summary = _pipeline_summary(
        {"quality": quality or {}, "topology": topology or {}},
        events=[{"pipeline_stage": event["stage"], "status": event["status"]} for event in events],
    )
    return {
        "ok": True,
        "document_source_id": resolved_document_source_id,
        "parsed_document_id": resolved_parsed_document_id,
        "run_id": run_id,
        "events": events,
        "pipeline_summary": summary,
        "quality": quality,
        "topology": topology,
    }


def handle_upload_ingest(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        result = build_upload_ingest_response(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload ingestion failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


def handle_upload_ingest_stream(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    handler._start_ndjson_stream()
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    recorder = _UploadPipelineEventRecorder(database_url=database_url)

    def emit(stage: str, data: dict[str, Any]) -> None:
        enriched = recorder.emit(stage, data)
        handler._stream_event(enriched)

    try:
        result = build_upload_ingest_response(root_dir, payload, emit_event=emit)
    except ValueError as exc:
        failed = recorder.emit("failed", {"error": str(exc)})
        handler._stream_event({**failed, "type": "error", "stage": "failed", "error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        message = f"upload ingestion failed: {exc}"
        failed = recorder.emit("failed", {"error": message})
        handler._stream_event({**failed, "type": "error", "stage": "failed", "error": message})
        return
    result["pipeline_summary"] = recorder.complete_payload(result)
    if recorder.ledger_error:
        result.setdefault("warnings", []).append(f"처리 이벤트 원장 기록 경고: {recorder.ledger_error}")
    handler._stream_event(
        {
            "type": "result",
            "stage": "complete",
            "event": "complete",
            "pipeline_stage": "pipeline",
            "status": result["pipeline_summary"]["overall_status"],
            "run_id": recorder.run_id,
            "event_id": f"{recorder.sequence + 1:04d}-result",
            "occurred_at": _utc_iso(),
            "payload": result,
        }
    )


def handle_upload_index_retry(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        result = build_upload_index_retry_response(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload index retry failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


def handle_upload_topology_retry(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        result = build_upload_topology_retry_response(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload topology retry failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


def handle_upload_quality_recheck(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        result = build_upload_quality_recheck_response(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload quality recheck failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


def handle_upload_code_block_repair(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    recorder = _UploadPipelineEventRecorder(database_url=database_url)
    try:
        result = build_upload_code_block_repair_response(root_dir, payload, emit_event=recorder.emit)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload code block repair failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    result["events"] = recorder.events
    result["pipeline_summary"] = recorder.complete_payload(result)
    if recorder.ledger_error:
        result.setdefault("warnings", []).append(f"처리 이벤트 원장 기록 경고: {recorder.ledger_error}")
    handler._send_json(result)


def handle_upload_page_stub_repair(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    recorder = _UploadPipelineEventRecorder(database_url=database_url)
    try:
        result = build_upload_page_stub_repair_response(root_dir, payload, emit_event=recorder.emit)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload page stub repair failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    result["events"] = recorder.events
    result["pipeline_summary"] = recorder.complete_payload(result)
    if recorder.ledger_error:
        result.setdefault("warnings", []).append(f"처리 이벤트 원장 기록 경고: {recorder.ledger_error}")
    handler._send_json(result)


def handle_upload_pipeline_status(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    try:
        result = build_upload_pipeline_status_response(root_dir, query, owner_user_id=owner_user_id)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload pipeline status failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


__all__ = [
    "build_upload_code_block_repair_response",
    "build_upload_page_stub_repair_response",
    "build_upload_index_retry_response",
    "build_upload_ingest_response",
    "build_upload_pipeline_status_response",
    "build_upload_quality_recheck_response",
    "build_upload_topology_retry_response",
    "handle_upload_ingest_stream",
    "handle_upload_index_retry",
    "handle_upload_ingest",
    "handle_upload_code_block_repair",
    "handle_upload_page_stub_repair",
    "handle_upload_pipeline_status",
    "handle_upload_quality_recheck",
    "handle_upload_topology_retry",
]
