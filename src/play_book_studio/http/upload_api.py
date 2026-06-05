from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings
from play_book_studio.db.document_repository import (
    delete_document_source,
    find_document_source_by_sha,
    persist_parsed_upload_document,
    scoped_document_sha256,
)
from play_book_studio.db.qdrant_indexer import index_pending_document_chunks
from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document, render_pdf_page_image_bytes
from play_book_studio.ingestion.vision import build_company_llm_image_describer


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
    safe_stem = re.sub(r"[^\w가-힣 .()[\]_-]+", "-", Path(source).stem, flags=re.UNICODE)
    safe_stem = re.sub(r"\s+", " ", safe_stem).strip(" -._")
    return f"{safe_stem or 'upload'}{suffix or '.bin'}"


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


def _discard_uploaded_source_copy(source_path: Path) -> None:
    try:
        source_path.unlink(missing_ok=True)
    except OSError:
        return
    try:
        source_path.parent.rmdir()
    except OSError:
        return


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _upload_report_storage_key(document_source_id: str) -> str:
    return f"uploads/reports/{document_source_id}/ingestion-report.json"


def _upload_report_path(settings, document_source_id: str) -> Path:
    return settings.object_storage_dir / _upload_report_storage_key(document_source_id)


def _storage_path_for_key(settings, storage_key: str) -> Path:
    normalized = str(storage_key or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        raise ValueError("storage_key is required")
    target = (settings.object_storage_dir / normalized).resolve()
    storage_root = settings.object_storage_dir.resolve()
    if target == storage_root or storage_root not in target.parents:
        raise ValueError(f"invalid storage_key outside object storage: {storage_key}")
    return target


def _asset_extension(asset: Any) -> str:
    suffix = Path(str(getattr(asset, "filename", "") or "")).suffix.lower()
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(str(getattr(asset, "mime_type", "") or ""))
    return guessed or ".bin"


def _extract_asset_bytes(source_path: Path, asset: Any) -> tuple[bytes, str]:
    metadata = getattr(asset, "metadata", {}) if isinstance(getattr(asset, "metadata", {}), dict) else {}
    rendered_pdf_page = _metadata_int(metadata.get("rendered_pdf_page"))
    if rendered_pdf_page:
        content = render_pdf_page_image_bytes(
            source_path,
            page_number=rendered_pdf_page,
            scale=_metadata_float(metadata.get("rendered_pdf_scale"), default=2.0),
        )
        return content, "pdfium_rendered_page"

    pdf_xref = str(metadata.get("pdf_xref") or "").strip()
    if pdf_xref:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(source_path))
            try:
                payload = doc.extract_image(int(pdf_xref))
                return bytes(payload.get("image") or b""), "pdf_xref"
            finally:
                doc.close()
        except Exception:  # noqa: BLE001
            return b"", "pdf_xref"

    source_member = str(metadata.get("source_member") or "").strip()
    if source_member and not source_member.startswith("pdf:"):
        try:
            with zipfile.ZipFile(source_path) as archive:
                return archive.read(source_member), "zip_member"
        except Exception:  # noqa: BLE001
            return b"", "zip_member"

    if source_path.is_file() and str(getattr(asset, "asset_type", "") or "") == "image":
        try:
            return source_path.read_bytes(), "source_file"
        except OSError:
            return b"", "source_file"

    return b"", "unknown"


def _metadata_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _metadata_float(value: Any, *, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _materialize_upload_assets(
    settings,
    *,
    source_path: Path,
    parsed: Any,
    persisted: Any,
    connection: Any,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    document_source_id = str(getattr(persisted, "document_source_id", "") or "").strip()
    parsed_document_id = str(getattr(persisted, "parsed_document_id", "") or "").strip()
    scoped_asset_ids = tuple(str(asset_id or "") for asset_id in getattr(persisted, "asset_ids", ()) or ())
    assets = tuple(getattr(parsed, "assets", ()) or ())
    manifest: dict[str, Any] = {
        "schema_version": "user_upload_asset_materialization_v1",
        "generated_at": _now_iso(),
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "asset_root_storage_key": f"uploads/assets/{document_source_id}",
        "image_count": sum(1 for asset in assets if str(getattr(asset, "asset_type", "") or "") == "image"),
        "written_count": 0,
        "assets": [],
        "warnings": [],
    }
    if not document_source_id or not assets:
        return manifest

    asset_root = (settings.object_storage_dir / "uploads" / "assets" / document_source_id).resolve()
    storage_root = settings.object_storage_dir.resolve()
    if storage_root in asset_root.parents and asset_root.is_dir():
        shutil.rmtree(asset_root)

    image_assets = [asset for asset in assets if str(getattr(asset, "asset_type", "") or "") == "image"]
    total_images = len(image_assets)
    image_position = 0
    with connection.cursor() as cursor:
        for index, asset in enumerate(assets):
            if str(getattr(asset, "asset_type", "") or "") != "image":
                continue
            image_position += 1
            scoped_asset_id = scoped_asset_ids[index] if index < len(scoped_asset_ids) and scoped_asset_ids[index] else str(getattr(asset, "asset_id", ""))
            if not scoped_asset_id:
                manifest["warnings"].append(f"asset index {index} has no scoped id")
                continue
            if progress is not None:
                progress({
                    "task_kind": "asset_write",
                    "progress_key": "asset_write",
                    "item_label": str(getattr(asset, "filename", "") or scoped_asset_id),
                    "progress_current": max(image_position - 1, 0),
                    "progress_total": total_images,
                    "progress_percent": round((max(image_position - 1, 0) / max(total_images, 1)) * 100),
                    "message": f"이미지 파일 저장 중: {getattr(asset, 'filename', scoped_asset_id)} ({image_position}/{total_images})",
                })
            content, source_kind = _extract_asset_bytes(source_path, asset)
            if not content:
                manifest["warnings"].append(f"{getattr(asset, 'filename', scoped_asset_id)} materialize failed from {source_kind}")
                continue
            metadata = getattr(asset, "metadata", {}) if isinstance(getattr(asset, "metadata", {}), dict) else {}
            extension = _asset_extension(asset)
            storage_key = f"uploads/assets/{document_source_id}/images/{scoped_asset_id}{extension}"
            target = _storage_path_for_key(settings, storage_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            actual_sha256 = hashlib.sha256(content).hexdigest()
            ocr_storage_key = f"uploads/assets/{document_source_id}/ocr/{scoped_asset_id}.json"
            ocr_target = _storage_path_for_key(settings, ocr_storage_key)
            ocr_target.parent.mkdir(parents=True, exist_ok=True)
            ocr_payload = {
                "schema_version": "user_upload_asset_ocr_v1",
                "generated_at": manifest["generated_at"],
                "asset_id": scoped_asset_id,
                "parser_asset_id": str(getattr(asset, "asset_id", "") or ""),
                "filename": str(getattr(asset, "filename", "") or target.name),
                "mime_type": str(getattr(asset, "mime_type", "") or mimetypes.guess_type(target.name)[0] or "application/octet-stream"),
                "image_storage_key": storage_key,
                "description": str(getattr(asset, "description", "") or ""),
                "ocr_text": str(getattr(asset, "ocr_text", "") or ""),
                "vision_model": str(metadata.get("vision_model") or metadata.get("qwen_model") or ""),
                "vision_provider": str(metadata.get("vision_provider") or ""),
                "vision_status": str(metadata.get("vision_status") or ""),
                "vision_error": str(metadata.get("vision_error") or ""),
            }
            ocr_target.write_text(json.dumps(ocr_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            entry = {
                "asset_id": scoped_asset_id,
                "parser_asset_id": str(getattr(asset, "asset_id", "") or ""),
                "filename": str(getattr(asset, "filename", "") or target.name),
                "mime_type": str(getattr(asset, "mime_type", "") or mimetypes.guess_type(target.name)[0] or "application/octet-stream"),
                "storage_key": storage_key,
                "ocr_storage_key": ocr_storage_key,
                "byte_size": len(content),
                "sha256": actual_sha256,
                "source": source_kind,
            }
            manifest["assets"].append(entry)
            manifest["written_count"] += 1
            metadata_patch = {
                "materialized_storage_key": storage_key,
                "ocr_storage_key": ocr_storage_key,
                "materialized_byte_size": len(content),
                "materialized_sha256": actual_sha256,
                "materialized_at": manifest["generated_at"],
                "materialized_from": source_kind,
            }
            cursor.execute(
                """
                UPDATE document_assets
                SET storage_key = %s,
                    metadata = metadata || %s::jsonb
                WHERE id = %s::uuid
                """,
                (storage_key, json.dumps(metadata_patch, ensure_ascii=False), scoped_asset_id),
            )
            if progress is not None:
                progress({
                    "task_kind": "asset_write",
                    "progress_key": "asset_write",
                    "item_label": str(getattr(asset, "filename", "") or scoped_asset_id),
                    "progress_current": image_position,
                    "progress_total": total_images,
                    "progress_percent": round((image_position / max(total_images, 1)) * 100),
                    "message": f"이미지 파일 저장 완료: {getattr(asset, 'filename', scoped_asset_id)} ({image_position}/{total_images})",
                })
    return manifest


def _write_upload_debug_artifacts(
    settings,
    *,
    document_source_id: str,
    parsed: Any,
    chunks: tuple[Any, ...],
    asset_manifest: dict[str, Any],
) -> dict[str, str]:
    if not document_source_id:
        return {}
    artifact_specs = {
        "parsed_markdown": (
            f"uploads/reports/{document_source_id}/parsed.md",
            str(getattr(parsed, "markdown", "") or ""),
        ),
        "chunks_json": (
            f"uploads/reports/{document_source_id}/chunks.json",
            json.dumps([chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        ),
        "assets_manifest": (
            f"uploads/reports/{document_source_id}/assets-manifest.json",
            json.dumps(asset_manifest, ensure_ascii=False, indent=2),
        ),
    }
    written: dict[str, str] = {}
    for key, (storage_key, content) in artifact_specs.items():
        target = _storage_path_for_key(settings, storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written[key] = storage_key
    return written


def _document_source_id_from_result(result: dict[str, Any]) -> str:
    persisted = result.get("persisted") if isinstance(result.get("persisted"), dict) else {}
    duplicate = result.get("duplicate") if isinstance(result.get("duplicate"), dict) else {}
    return str(persisted.get("document_source_id") or duplicate.get("document_source_id") or "").strip()


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _expected_chunk_count(result: dict[str, Any]) -> int:
    persisted = result.get("persisted") if isinstance(result.get("persisted"), dict) else {}
    duplicate = result.get("duplicate") if isinstance(result.get("duplicate"), dict) else {}
    return (
        _int_value(persisted.get("chunk_count"))
        or _int_value(duplicate.get("chunk_count"))
        or _int_value(result.get("chunk_count"))
    )


def _index_status_from_counts(index_payload: dict[str, Any], *, expected_chunks: int) -> str:
    raw_status = str(index_payload.get("status") or "").strip()
    if raw_status in {"failed", "not_requested"}:
        return raw_status
    if raw_status.startswith("duplicate_existing"):
        return raw_status
    if expected_chunks <= 0:
        return "no_chunks"
    indexed_count = _int_value(index_payload.get("indexed_count"))
    candidate_count = _int_value(index_payload.get("candidate_count"))
    if indexed_count >= expected_chunks:
        return "indexed"
    if indexed_count > 0:
        return "partial"
    if candidate_count <= 0:
        return "no_candidates"
    return "partial"


def _basic_index_ready(result: dict[str, Any]) -> bool:
    index_payload = result.get("index") if isinstance(result.get("index"), dict) else {}
    expected_chunks = _expected_chunk_count(result)
    return _index_status_from_counts(index_payload, expected_chunks=expected_chunks) in {
        "indexed",
        "duplicate_existing_indexed",
    }


def _answer_ready(result: dict[str, Any]) -> bool:
    quality_gate = result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {}
    return bool(quality_gate.get("verified_for_answer") is True)


def _apply_upload_readiness(result: dict[str, Any]) -> None:
    basic_ready = _basic_index_ready(result)
    quality_gate = dict(result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {})
    quality_gate["state"] = "basic_text_indexed" if basic_ready else "basic_text_index_incomplete"
    quality_gate["label"] = quality_gate.get("label") or "기본 텍스트 인덱싱"
    quality_gate["verified_for_answer"] = bool(quality_gate.get("verified_for_answer") is True and basic_ready)
    result["quality_gate"] = quality_gate
    result["basic_index_ready"] = basic_ready
    result["answer_ready"] = _answer_ready(result)
    result["ready_for_chat"] = result["answer_ready"]


def _write_upload_ingestion_report(settings, result: dict[str, Any], stage_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    _apply_upload_readiness(result)
    document_source_id = _document_source_id_from_result(result)
    if not document_source_id:
        return None
    report_storage_key = _upload_report_storage_key(document_source_id)
    report_path = _upload_report_path(settings, document_source_id).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    index_payload = result.get("index") if isinstance(result.get("index"), dict) else {}
    report = {
        "schema_version": "user_upload_ingestion_report_v1",
        "generated_at": _now_iso(),
        "report_reconstructed": False,
        "document_source_id": document_source_id,
        "repository_id": result.get("repository_id") or result.get("persisted", {}).get("repository_id", ""),
        "owner_user_id": result.get("owner_user_id") or "",
        "visibility": result.get("visibility") or "",
        "source_scope": result.get("source_scope") or "",
        "filename": result.get("filename") or "",
        "storage_key": result.get("storage_key") or "",
        "byte_size": result.get("byte_size") or 0,
        "mime_type": result.get("mime_type") or "",
        "document_format": result.get("document_format") or "",
        "sha256": result.get("sha256") or "",
        "counts": {
            "block_count": result.get("block_count") or 0,
            "asset_count": result.get("asset_count") or 0,
            "chunk_count": result.get("chunk_count") or 0,
            "candidate_count": index_payload.get("candidate_count") or 0,
            "indexed_count": index_payload.get("indexed_count") or 0,
        },
        "timings_ms": result.get("timings_ms") or {},
        "quality_gate": result.get("quality_gate") or {},
        "stages": stage_events,
        "index": index_payload,
        "asset_materialization": result.get("asset_materialization") or {},
        "artifacts": result.get("artifacts") or {},
        "warnings": result.get("warnings") or [],
        "ready_for_chat": result.get("ready_for_chat") is True,
        "answer_ready": result.get("answer_ready") is True,
        "basic_index_ready": result.get("basic_index_ready") is True,
        "scope": {
            "owner_user_id": result.get("owner_user_id") or "",
            "repository_id": result.get("repository_id") or result.get("persisted", {}).get("repository_id", ""),
            "document_source_id": document_source_id,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "document_source_id": document_source_id,
        "storage_key": report_storage_key,
        "available": True,
    }


def _read_upload_ingestion_report(settings, document_source_id: str) -> dict[str, Any] | None:
    report_path = _upload_report_path(settings, document_source_id)
    if not report_path.is_file():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def _upload_document_access_allowed(root_dir: Path, document_source_id: str, *, owner_user_id: str = "") -> bool:
    settings = load_settings(root_dir)
    database_url = str(settings.database_url or "").strip()
    if not database_url:
        return True
    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(owner_user_id, ''), COALESCE(visibility, '')
                FROM document_sources
                WHERE id = %s::uuid
                LIMIT 1
                """,
                (document_source_id,),
            )
            row = cursor.fetchone()
    if not row:
        return False
    owner = str(row[0] or "")
    visibility = str(row[1] or "")
    if visibility == "private_user":
        return bool(owner_user_id and owner == owner_user_id)
    return True


def _reconstruct_upload_ingestion_report(root_dir: Path, document_source_id: str, *, owner_user_id: str = "") -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = str(settings.database_url or "").strip()
    if not database_url:
        return {
            "schema_version": "user_upload_ingestion_report_v1",
            "generated_at": _now_iso(),
            "report_reconstructed": True,
            "document_source_id": document_source_id,
            "warnings": ["DATABASE_URL이 없어 기존 처리 이력을 재구성할 수 없습니다."],
            "stages": [],
        }
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ds.id::text AS document_source_id,
                    ds.repository_id::text AS repository_id,
                    COALESCE(ds.owner_user_id, '') AS owner_user_id,
                    COALESCE(ds.visibility, '') AS visibility,
                    COALESCE(ds.source_scope, '') AS source_scope,
                    COALESCE(ds.filename, '') AS filename,
                    COALESCE(ds.storage_key, '') AS storage_key,
                    COALESCE(ds.mime_type, '') AS mime_type,
                    COALESCE(ds.sha256, '') AS sha256,
                    COALESCE((
                        SELECT pj.status
                        FROM parse_jobs pj
                        WHERE pj.document_source_id = ds.id
                        ORDER BY pj.created_at DESC
                        LIMIT 1
                    ), '') AS parse_status,
                    COALESCE((
                        SELECT count(*)
                        FROM parsed_documents pd
                        JOIN document_blocks db ON db.parsed_document_id = pd.id
                        WHERE pd.document_source_id = ds.id
                    ), 0) AS block_count,
                    COALESCE((
                        SELECT count(*)
                        FROM parsed_documents pd
                        JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                        WHERE pd.document_source_id = ds.id
                    ), 0) AS chunk_count,
                    COALESCE((
                        SELECT COALESCE(sum(dc.token_count), 0)
                        FROM parsed_documents pd
                        JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                        WHERE pd.document_source_id = ds.id
                    ), 0) AS token_count,
                    COALESCE((
                        SELECT count(*)
                        FROM parsed_documents pd
                        JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                        JOIN qdrant_index_entries qie ON qie.chunk_id = dc.id
                        WHERE pd.document_source_id = ds.id
                    ), 0) AS indexed_count
                FROM document_sources ds
                WHERE ds.id = %s::uuid
                  AND (%s = '' OR COALESCE(ds.owner_user_id, '') = %s OR COALESCE(ds.visibility, '') <> 'private_user')
                LIMIT 1
                """,
                (document_source_id, owner_user_id, owner_user_id),
            )
            row = cursor.fetchone()
    if not row:
        return {
            "schema_version": "user_upload_ingestion_report_v1",
            "generated_at": _now_iso(),
            "report_reconstructed": True,
            "document_source_id": document_source_id,
            "warnings": ["문서를 찾을 수 없거나 현재 세션에서 접근할 수 없습니다."],
            "stages": [],
        }
    indexed_count = int(row.get("indexed_count") or 0)
    chunk_count = int(row.get("chunk_count") or 0)
    index_payload = {
        "candidate_count": chunk_count,
        "indexed_count": indexed_count,
        "status": "indexed" if chunk_count > 0 and indexed_count >= chunk_count else "partial_or_missing",
    }
    reconstructed = {
        "schema_version": "user_upload_ingestion_report_v1",
        "generated_at": _now_iso(),
        "report_reconstructed": True,
        "document_source_id": document_source_id,
        "repository_id": row.get("repository_id") or "",
        "owner_user_id": row.get("owner_user_id") or "",
        "visibility": row.get("visibility") or "",
        "source_scope": row.get("source_scope") or "",
        "filename": row.get("filename") or "",
        "storage_key": row.get("storage_key") or "",
        "mime_type": row.get("mime_type") or "",
        "sha256": row.get("sha256") or "",
        "counts": {
            "block_count": int(row.get("block_count") or 0),
            "chunk_count": chunk_count,
            "token_count": int(row.get("token_count") or 0),
            "candidate_count": chunk_count,
            "indexed_count": indexed_count,
        },
        "index": index_payload,
        "quality_gate": {
            "state": "basic_text_indexed" if chunk_count > 0 and indexed_count >= chunk_count else "basic_text_index_incomplete",
            "label": "기본 텍스트 인덱싱",
            "verified_for_answer": False,
        },
        "warnings": ["저장된 ingestion-report.json이 없어 DB/Qdrant 기록으로 재구성했습니다."],
        "ready_for_chat": False,
        "answer_ready": False,
        "basic_index_ready": chunk_count > 0 and indexed_count >= chunk_count,
        "scope": {
            "owner_user_id": row.get("owner_user_id") or "",
            "repository_id": row.get("repository_id") or "",
            "document_source_id": document_source_id,
        },
        "stages": [],
    }
    return reconstructed


def build_upload_ingest_response(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    stage_events: list[dict[str, Any]] = []
    stage_started_perf: dict[str, float] = {}
    stage_started_iso: dict[str, str] = {}

    def emit(stage: str, status: str, message: str, **extra: Any) -> None:
        now = _now_iso()
        if status == "running":
            stage_started_perf[stage] = time.perf_counter()
            stage_started_iso[stage] = now
        event = {
            "type": "stage",
            "stage": stage,
            "status": status,
            "message": message,
            "started_at": stage_started_iso.get(stage, now),
        }
        if status != "running":
            event["finished_at"] = now
            if "duration_ms" not in extra and stage in stage_started_perf:
                extra["duration_ms"] = int((time.perf_counter() - stage_started_perf[stage]) * 1000)
        count_keys = {
            "byte_size",
            "block_count",
            "asset_count",
            "chunk_count",
            "candidate_count",
            "indexed_count",
        }
        counts = {key: value for key, value in extra.items() if key in count_keys and isinstance(value, int)}
        if counts:
            event["counts"] = counts
        event.update(extra)
        stage_events.append(event)
        if progress_callback is not None:
            progress_callback(event)

    started_at = time.perf_counter()
    timings: dict[str, int] = {}
    settings = load_settings(root_dir)
    emit("received", "running", "업로드 요청을 접수하는 중입니다.")
    emit("received", "done", "업로드 요청을 접수했습니다.", duration_ms=0)
    emit("store", "running", "업로드 파일을 서버 저장소에 기록하는 중입니다.")
    source_path, storage_key, byte_size = _store_uploaded_file(root_dir, payload)
    timings["store_ms"] = int((time.perf_counter() - started_at) * 1000)
    emit("store", "done", "업로드 파일 저장이 완료되었습니다.", duration_ms=timings["store_ms"], byte_size=byte_size)
    dry_run = _bool_payload(payload.get("dry_run"), default=False)
    force_reingest_value = payload.get("force_reingest")
    if force_reingest_value is None:
        force_reingest_value = payload.get("force_duplicate")
    force_reingest = _bool_payload(force_reingest_value, default=True)
    created_by = str(payload.get("created_by") or "").strip()
    visibility = str(payload.get("visibility") or "").strip()
    source_scope = str(payload.get("source_scope") or "user_upload").strip() or "user_upload"
    effective_visibility = visibility or ("private_user" if created_by else "workspace_shared")
    uploaded_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    db_sha256 = scoped_document_sha256(
        uploaded_sha256,
        owner_user_id=created_by,
        visibility=effective_visibility,
        source_scope=source_scope,
    )
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not dry_run and database_url and not force_reingest:
        import psycopg

        with psycopg.connect(database_url) as connection:
            existing = find_document_source_by_sha(
                connection,
                tenant_slug=str(payload.get("tenant_slug") or "public"),
                workspace_slug=str(payload.get("workspace_slug") or "default"),
                sha256=db_sha256,
                owner_user_id=created_by,
            )
        if existing:
            _discard_uploaded_source_copy(source_path)
            existing_chunk_count = _int_value(existing.get("chunk_count"))
            existing_indexed_count = _int_value(existing.get("indexed_count"))
            duplicate_index_status = (
                "duplicate_existing_indexed"
                if existing_chunk_count > 0 and existing_indexed_count >= existing_chunk_count
                else "duplicate_existing_unindexed"
            )
            emit(
                "store",
                "duplicate",
                "같은 파일이 이미 있습니다. 기존 데이터를 유지할지 새 데이터로 덮어쓸지 선택이 필요합니다.",
                document_source_id=existing.get("document_source_id") or "",
                repository_id=existing.get("repository_id") or "",
                candidate_count=existing_chunk_count,
                indexed_count=existing_indexed_count,
            )
            timings["total_ms"] = int((time.perf_counter() - started_at) * 1000)
            result: dict[str, Any] = {
                "dry_run": dry_run,
                "filename": existing.get("filename") or str(payload.get("file_name") or ""),
                "storage_key": existing.get("storage_key") or "",
                "byte_size": byte_size,
                "document_format": "",
                "mime_type": "",
                "sha256": uploaded_sha256,
                "db_sha256": db_sha256,
                "block_count": 0,
                "asset_count": 0,
                "chunk_count": existing_chunk_count,
                "owner_user_id": created_by,
                "repository_id": existing.get("repository_id") or "",
                "visibility": existing.get("visibility") or effective_visibility,
                "source_scope": existing.get("source_scope") or source_scope,
                "force_reingest": force_reingest,
                "timings_ms": timings,
                "warnings": ["이미 업로드된 같은 파일입니다."],
                "sections": [],
                "stage_events": stage_events,
                "duplicate": {
                    "exists": True,
                    **existing,
                    "chunk_count": existing_chunk_count,
                    "indexed_count": existing_indexed_count,
                },
                "persisted": {
                    "document_source_id": existing.get("document_source_id") or "",
                    "document_version_id": "",
                    "parse_job_id": "",
                    "parsed_document_id": existing.get("parsed_document_id") or "",
                    "repository_id": existing.get("repository_id") or "",
                    "block_count": 0,
                    "asset_count": 0,
                    "chunk_count": existing_chunk_count,
                },
                "index": {
                    "collection": str(payload.get("collection") or settings.qdrant_collection),
                    "source_scope": existing.get("source_scope") or source_scope,
                    "document_source_id": existing.get("document_source_id") or "",
                    "candidate_count": existing_chunk_count,
                    "indexed_count": existing_indexed_count,
                    "status": duplicate_index_status,
                },
            }
            _apply_upload_readiness(result)
            emit(
                "ready",
                "duplicate",
                "업로드를 잠시 멈췄습니다. 기존 유지 또는 새 데이터 덮어쓰기를 선택하세요.",
                duration_ms=timings["total_ms"],
            )
            return result
    parse_started_at = time.perf_counter()
    emit("parse", "running", "문서에서 텍스트와 구조를 추출하는 중입니다.")

    def _parse_progress(_stage: str, status: str, detail: dict[str, Any]) -> None:
        note = str(detail.get("note") or "").strip() or status
        extra = {key: value for key, value in detail.items() if key != "note"}
        emit("parse", "progress" if status == "progress" else "info", note, **extra)

    parsed = parse_upload_document(
        source_path,
        image_describer=build_company_llm_image_describer(settings),
        progress=_parse_progress,
    )
    timings["parse_ms"] = int((time.perf_counter() - parse_started_at) * 1000)
    if not parsed.blocks:
        emit(
            "parse",
            "failed",
            "문서에서 텍스트를 추출하지 못했습니다 (스캔본/암호화/지원되지 않는 형식일 수 있음).",
            duration_ms=timings["parse_ms"],
            block_count=0,
            warnings=list(parsed.warnings),
        )
        raise ValueError(
            f"문서 파싱이 빈 결과를 만들었습니다: {parsed.filename}. "
            "스캔 PDF/이미지 기반/암호화된 문서이거나 지원되지 않는 형식일 수 있습니다. "
            f"파서 경고: {list(parsed.warnings) or 'none'}"
        )
    emit(
        "parse",
        "done",
        "문서 파싱이 완료되었습니다.",
        duration_ms=timings["parse_ms"],
        block_count=len(parsed.blocks),
        asset_count=len(parsed.assets),
    )
    chunk_started_at = time.perf_counter()
    emit("chunk", "running", "챗봇 검색에 사용할 청크를 생성하는 중입니다.")
    chunks = build_document_chunks(
        parsed,
        max_chars=_int_payload(payload.get("chunk_max_chars"), default=1800),
        overlap_blocks=_int_payload(payload.get("chunk_overlap_blocks"), default=1),
    )
    timings["chunk_ms"] = int((time.perf_counter() - chunk_started_at) * 1000)
    if not chunks:
        emit(
            "chunk",
            "failed",
            "검색용 청크를 만들지 못했습니다 (block은 있지만 모두 navigation-only 등으로 걸러짐).",
            duration_ms=timings["chunk_ms"],
            chunk_count=0,
        )
        raise ValueError(
            f"청크 생성이 0건이 되었습니다: {parsed.filename} (blocks={len(parsed.blocks)}). "
            "검색에 쓸 수 있는 의미 단위가 없어 적재를 거부합니다."
        )
    emit("chunk", "done", "청크 생성이 완료되었습니다.", duration_ms=timings["chunk_ms"], chunk_count=len(chunks))
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "filename": parsed.filename,
        "storage_key": storage_key,
        "byte_size": byte_size,
        "document_format": parsed.document_format,
        "mime_type": parsed.mime_type,
        "sha256": parsed.sha256,
        "db_sha256": db_sha256,
        "block_count": len(parsed.blocks),
        "asset_count": len(parsed.assets),
        "chunk_count": len(chunks),
        "owner_user_id": created_by,
        "repository_id": str(payload.get("repository_id") or "").strip(),
        "visibility": effective_visibility,
        "source_scope": source_scope,
        "force_reingest": force_reingest,
        "timings_ms": timings,
        "warnings": list(parsed.warnings),
        "quality_gate": {
            "state": "basic_text_indexed",
            "label": "기본 텍스트 인덱싱",
            "verified_for_answer": False,
            "included_checks": [
                "file_store",
                "basic_text_extract",
                "chunk_create",
                "postgres_persist",
                "qdrant_index",
                "session_scope_link",
            ],
            "excluded_checks": [
                "ocr_or_scanned_pdf_recovery",
                "image_or_diagram_understanding",
                "table_semantic_validation",
                "answer_quality_probe",
                "human_quality_review",
            ],
        },
        "sections": [list(chunk.section_path) for chunk in chunks if chunk.section_path],
        "stage_events": stage_events,
    }
    if dry_run:
        timings["total_ms"] = int((time.perf_counter() - started_at) * 1000)
        _apply_upload_readiness(result)
        return result

    if not database_url:
        raise ValueError("DATABASE_URL is required for upload ingestion")

    import psycopg

    with psycopg.connect(database_url) as connection:
        lookup_kwargs = {
            "tenant_slug": str(payload.get("tenant_slug") or "public"),
            "workspace_slug": str(payload.get("workspace_slug") or "default"),
            "sha256": db_sha256,
        }
        existing = find_document_source_by_sha(
            connection,
            **lookup_kwargs,
            owner_user_id=created_by,
        )
        if existing and not force_reingest:
            emit("persist", "skipped", "같은 파일이 이미 있어 기존 문서를 유지합니다.")
            existing_chunk_count = _int_value(existing.get("chunk_count"))
            existing_indexed_count = _int_value(existing.get("indexed_count"))
            duplicate_index_status = (
                "duplicate_existing_indexed"
                if existing_chunk_count > 0 and existing_indexed_count >= existing_chunk_count
                else "duplicate_existing_unindexed"
            )
            emit(
                "index",
                "skipped" if duplicate_index_status == "duplicate_existing_indexed" else "warning",
                "기존 문서의 인덱싱 기록을 재사용합니다."
                if duplicate_index_status == "duplicate_existing_indexed"
                else "기존 문서가 있지만 인덱싱 기록이 충분하지 않습니다.",
                candidate_count=existing_chunk_count,
                indexed_count=existing_indexed_count,
            )
            result["repository_id"] = existing.get("repository_id") or ""
            result["duplicate"] = {
                "exists": True,
                **existing,
            }
            result["persisted"] = {
                "document_source_id": existing.get("document_source_id") or "",
                "document_version_id": "",
                "parse_job_id": "",
                "parsed_document_id": existing.get("parsed_document_id") or "",
                "repository_id": existing.get("repository_id") or "",
                "block_count": 0,
                "asset_count": 0,
                "chunk_count": int(existing.get("chunk_count") or 0),
            }
            result["index"] = {
                "collection": str(payload.get("collection") or settings.qdrant_collection),
                "source_scope": existing.get("source_scope") or source_scope,
                "document_source_id": existing.get("document_source_id") or "",
                "candidate_count": existing_chunk_count,
                "indexed_count": existing_indexed_count,
                "status": duplicate_index_status,
            }
            result.setdefault("warnings", []).append("이미 업로드된 같은 파일입니다.")
            timings["total_ms"] = int((time.perf_counter() - started_at) * 1000)
            emit(
                "scope",
                "done",
                "기존 문서의 세션 검색 범위를 확인했습니다.",
                document_source_id=existing.get("document_source_id") or "",
                repository_id=existing.get("repository_id") or "",
            )
            if duplicate_index_status == "duplicate_existing_indexed":
                emit(
                    "ready",
                    "duplicate",
                    "기존 기본 인덱싱 결과를 재사용합니다. 답변 품질 검수는 별도입니다.",
                    duration_ms=timings["total_ms"],
                )
            else:
                emit(
                    "ready",
                    "warning",
                    "기존 문서는 있으나 검색 인덱싱 확인이 필요합니다.",
                    duration_ms=timings["total_ms"],
                )
            report = _write_upload_ingestion_report(settings, result, stage_events)
            if report:
                result["report"] = report
            return result

        persist_started_at = time.perf_counter()
        emit("persist", "running", "PostgreSQL에 문서, block, chunk를 저장하는 중입니다.")
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
        }
        asset_manifest = _materialize_upload_assets(
            settings,
            source_path=source_path,
            parsed=parsed,
            persisted=persisted,
            connection=connection,
            progress=lambda detail: emit(
                "persist",
                "progress",
                str(detail.get("message") or "이미지 에셋 파일을 저장하는 중입니다."),
                task_kind=detail.get("task_kind") or "asset_write",
                progress_key=detail.get("progress_key") or "asset_write",
                item_label=detail.get("item_label") or "",
                progress_current=int(detail.get("progress_current") or 0),
                progress_total=int(detail.get("progress_total") or 0),
                progress_percent=int(detail.get("progress_percent") or 0),
            ),
        )
        debug_artifacts = _write_upload_debug_artifacts(
            settings,
            document_source_id=persisted.document_source_id,
            parsed=parsed,
            chunks=chunks,
            asset_manifest=asset_manifest,
        )
        result["asset_materialization"] = asset_manifest
        result["artifacts"] = debug_artifacts
        if asset_manifest.get("warnings"):
            result.setdefault("warnings", []).extend(str(item) for item in asset_manifest.get("warnings") or [])
        if asset_manifest.get("image_count"):
            emit(
                "persist",
                "info",
                f"이미지 에셋 파일 저장: {asset_manifest.get('written_count', 0)}/{asset_manifest.get('image_count', 0)}개",
            )
        timings["persist_ms"] = int((time.perf_counter() - persist_started_at) * 1000)
        emit(
            "persist",
            "done",
            "PostgreSQL 및 이미지 파일 저장이 완료되었습니다.",
            duration_ms=timings["persist_ms"],
            document_source_id=persisted.document_source_id,
            block_count=len(persisted.block_ids),
            asset_count=len(persisted.asset_ids),
            chunk_count=len(persisted.chunk_ids),
        )
        if _bool_payload(payload.get("index"), default=False):
            index_started_at = time.perf_counter()
            emit("index", "running", "Qdrant 검색 인덱스를 생성하는 중입니다.")
            try:
                result["index"] = index_pending_document_chunks(
                    settings,
                    connection,
                    collection=str(payload.get("collection") or "").strip() or None,
                    source_scope=source_scope,
                    document_source_id=persisted.document_source_id,
                    limit=_int_payload(payload.get("index_limit"), default=max(100, len(chunks))),
                )
                result["index"]["status"] = _index_status_from_counts(
                    result["index"],
                    expected_chunks=len(persisted.chunk_ids),
                )
                index_event_status = "done" if result["index"]["status"] == "indexed" else "warning"
                index_message = (
                    "Qdrant 인덱싱이 완료되었습니다."
                    if result["index"]["status"] == "indexed"
                    else "Qdrant 인덱싱이 일부만 완료되었거나 후보 청크를 찾지 못했습니다."
                )
                emit(
                    "index",
                    index_event_status,
                    index_message,
                    duration_ms=int((time.perf_counter() - index_started_at) * 1000),
                    candidate_count=result["index"].get("candidate_count", 0),
                    indexed_count=result["index"].get("indexed_count", 0),
                )
            except Exception as exc:  # noqa: BLE001
                result["index"] = {
                    "collection": str(payload.get("collection") or settings.qdrant_collection),
                    "source_scope": source_scope,
                    "document_source_id": persisted.document_source_id,
                    "candidate_count": 0,
                    "indexed_count": 0,
                    "status": "failed",
                    "error": str(exc),
                }
                result.setdefault("warnings", []).append(f"검색 인덱싱 실패: {exc}")
                emit("index", "failed", f"Qdrant 인덱싱에 실패했습니다: {exc}")
            finally:
                timings["index_ms"] = int((time.perf_counter() - index_started_at) * 1000)
        else:
            result["index"] = {
                "collection": str(payload.get("collection") or settings.qdrant_collection),
                "source_scope": source_scope,
                "document_source_id": persisted.document_source_id,
                "candidate_count": len(chunks),
                "indexed_count": 0,
                "status": "not_requested",
            }
            emit("index", "skipped", "요청에서 Qdrant 인덱싱이 비활성화되어 있습니다.", candidate_count=len(chunks))
        index_status = str(result.get("index", {}).get("status") or "")
        scope_status = "done" if result.get("repository_id") and _document_source_id_from_result(result) else "warning"
        emit(
            "scope",
            scope_status,
            "문서, repository, owner 기준 검색 범위를 확인했습니다."
            if scope_status == "done"
            else "검색 범위 확인에 필요한 repository 또는 document id가 부족합니다.",
            document_source_id=persisted.document_source_id,
            repository_id=persisted.repository_id,
            owner_user_id=created_by,
        )
        if index_status == "indexed":
            emit("ready", "done", "기본 텍스트 인덱싱이 완료되었습니다. 답변 품질 검수는 별도입니다.")
        elif index_status == "failed":
            emit("ready", "warning", "문서 저장은 완료됐지만 Qdrant 인덱싱 실패로 검색에는 바로 사용할 수 없습니다.")
        else:
            emit("ready", "warning", "문서 저장은 완료됐지만 검색 인덱싱은 완료되지 않았습니다.")
    timings["total_ms"] = int((time.perf_counter() - started_at) * 1000)
    result["stage_events"] = stage_events
    report = _write_upload_ingestion_report(settings, result, stage_events)
    if report:
        result["report"] = report
    return result


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

    def emit(event: dict[str, Any]) -> None:
        handler._stream_event(event)

    try:
        result = build_upload_ingest_response(root_dir, payload, progress_callback=emit)
    except ValueError as exc:
        emit({"type": "error", "status_code": HTTPStatus.BAD_REQUEST, "error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "status_code": HTTPStatus.INTERNAL_SERVER_ERROR, "error": f"upload ingestion failed: {exc}"})
        return
    emit({"type": "result", "payload": result})


def handle_upload_delete(
    handler: Any,
    payload: dict[str, Any],
    *,
    root_dir: Path,
    owner_user_id: str = "",
) -> None:
    """업로드된 문서를 완전 삭제.

    PostgreSQL row(cascade) + Qdrant points + 디스크 원본 파일을 모두 정리한다.
    owner_user_id 가 비어있지 않으면 그 owner 의 문서만 삭제 가능.
    """
    document_source_id = str(payload.get("document_source_id") or payload.get("id") or "").strip()
    if not document_source_id:
        handler._send_json({"error": "document_source_id is required"}, HTTPStatus.BAD_REQUEST)
        return

    settings = load_settings(root_dir)
    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        handler._send_json({"error": "DATABASE_URL is required"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    import psycopg

    deleted_info: dict[str, Any] | None = None
    try:
        with psycopg.connect(database_url) as connection:
            with connection.transaction():
                deleted_info = delete_document_source(
                    connection,
                    document_source_id=document_source_id,
                    owner_user_id=owner_user_id,
                )
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"document delete failed: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return

    if deleted_info is None:
        handler._send_json(
            {"error": "document not found or not owned by this user"},
            HTTPStatus.NOT_FOUND,
        )
        return

    # Qdrant points 청소
    qdrant_deleted = 0
    qdrant_errors: list[str] = []
    points_by_collection: dict[str, list[str]] = {}
    for entry in deleted_info.get("qdrant_points", []):
        collection = str(entry.get("collection") or "").strip()
        point_id = str(entry.get("point_id") or "").strip()
        if not point_id:
            continue
        points_by_collection.setdefault(collection, []).append(point_id)

    if points_by_collection:
        try:
            from play_book_studio.db.qdrant_indexer import delete_qdrant_points  # type: ignore
        except Exception:
            delete_qdrant_points = None  # type: ignore[assignment]
        if delete_qdrant_points is not None:
            for collection, point_ids in points_by_collection.items():
                try:
                    delete_qdrant_points(settings, collection=collection or None, point_ids=point_ids)
                    qdrant_deleted += len(point_ids)
                except Exception as exc:  # noqa: BLE001
                    qdrant_errors.append(f"{collection}: {exc}")
        else:
            qdrant_errors.append("qdrant_indexer.delete_qdrant_points not available")

    # 디스크 원본 파일 청소
    storage_removed = False
    storage_error = ""
    storage_key = str(deleted_info.get("storage_key") or "").strip()
    if storage_key:
        try:
            target = (settings.object_storage_dir / storage_key).resolve()
            storage_root = settings.object_storage_dir.resolve()
            if storage_root in target.parents and target.is_file():
                target.unlink()
                storage_removed = True
                # 빈 디렉토리도 정리
                try:
                    target.parent.rmdir()
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            storage_error = str(exc)

    # ingestion-report.json 도 같이 정리
    report_removed = False
    try:
        report_dir = (settings.object_storage_dir / "uploads" / "reports" / deleted_info["document_source_id"]).resolve()
        storage_root = settings.object_storage_dir.resolve()
        if storage_root in report_dir.parents and report_dir.is_dir():
            shutil.rmtree(report_dir)
            report_removed = True
    except Exception:  # noqa: BLE001
        pass

    asset_dir_removed = False
    try:
        asset_dir = (settings.object_storage_dir / "uploads" / "assets" / deleted_info["document_source_id"]).resolve()
        storage_root = settings.object_storage_dir.resolve()
        if storage_root in asset_dir.parents and asset_dir.is_dir():
            shutil.rmtree(asset_dir)
            asset_dir_removed = True
    except Exception:  # noqa: BLE001
        pass

    handler._send_json({
        "deleted": True,
        "document_source_id": deleted_info["document_source_id"],
        "filename": deleted_info.get("filename", ""),
        "postgres_rows_deleted": deleted_info.get("deleted_rows", 0),
        "qdrant_points_deleted": qdrant_deleted,
        "qdrant_errors": qdrant_errors,
        "storage_file_removed": storage_removed,
        "storage_error": storage_error,
        "report_file_removed": report_removed,
        "asset_dir_removed": asset_dir_removed,
    })


def handle_upload_ingest_report(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    params = parse_qs(query)
    document_source_id = str((params.get("document_source_id") or params.get("id") or [""])[0] or "").strip()
    if not document_source_id:
        handler._send_json({"error": "document_source_id is required"}, HTTPStatus.BAD_REQUEST)
        return
    try:
        uuid.UUID(document_source_id)
    except ValueError:
        handler._send_json({"error": "document_source_id must be a valid UUID"}, HTTPStatus.BAD_REQUEST)
        return
    settings = load_settings(root_dir)
    try:
        if not _upload_document_access_allowed(root_dir, document_source_id, owner_user_id=owner_user_id):
            handler._send_json({"error": "upload report is not visible to this session"}, HTTPStatus.FORBIDDEN)
            return
        report = _read_upload_ingestion_report(settings, document_source_id)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"failed to read upload report: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    if report is None:
        report = _reconstruct_upload_ingestion_report(root_dir, document_source_id, owner_user_id=owner_user_id)
    handler._send_json(report)


__all__ = [
    "build_upload_ingest_response",
    "handle_upload_ingest",
    "handle_upload_ingest_report",
    "handle_upload_ingest_stream",
]
