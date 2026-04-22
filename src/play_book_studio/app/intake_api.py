"""customer-pack draft lifecycle API 보조 로직."""

from __future__ import annotations

import base64
import re
import uuid
import json
from pathlib import Path
from typing import Any

from play_book_studio.app.source_books_customer_pack import load_customer_pack_book
from play_book_studio.intake import (
    DocSourceRequest,
    CustomerPackDraftStore,
    CustomerPackPlanner,
    build_customer_pack_support_matrix as _build_customer_pack_support_matrix_model,
)
from play_book_studio.intake.capture.service import CustomerPackCaptureService
from play_book_studio.intake.normalization.service import CustomerPackNormalizeService
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.private_corpus import (
    customer_pack_private_manifest_path,
    delete_customer_pack_private_corpus,
)
from play_book_studio.config.settings import load_settings

SUPPORTED_CUSTOMER_PACK_SOURCE_TYPES = {
    "web",
    "pdf",
    "md",
    "asciidoc",
    "txt",
    "docx",
    "pptx",
    "xlsx",
    "image",
}


def _private_corpus_payload(root_dir: Path, draft_id: str) -> dict[str, Any] | None:
    settings = load_settings(root_dir)
    path = customer_pack_private_manifest_path(settings, draft_id)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    boundary_summary = summarize_private_runtime_boundary(manifest)
    return {
        "artifact_version": str(manifest.get("artifact_version") or "").strip(),
        "draft_id": str(manifest.get("draft_id") or "").strip(),
        "tenant_id": str(manifest.get("tenant_id") or "").strip(),
        "workspace_id": str(manifest.get("workspace_id") or "").strip(),
        "pack_id": str(manifest.get("pack_id") or "").strip(),
        "pack_version": str(manifest.get("pack_version") or "").strip(),
        "classification": str(manifest.get("classification") or "").strip(),
        "access_groups": list(manifest.get("access_groups") or []),
        "provider_egress_policy": str(manifest.get("provider_egress_policy") or "").strip(),
        "approval_state": str(manifest.get("approval_state") or "").strip(),
        "publication_state": str(manifest.get("publication_state") or "").strip(),
        "redaction_state": str(manifest.get("redaction_state") or "").strip(),
        "source_lane": str(manifest.get("source_lane") or "").strip(),
        "source_collection": str(manifest.get("source_collection") or "").strip(),
        "boundary_truth": str(manifest.get("boundary_truth") or "").strip(),
        "runtime_truth_label": str(manifest.get("runtime_truth_label") or "").strip(),
        "boundary_badge": str(manifest.get("boundary_badge") or "").strip(),
        "book_count": int(manifest.get("book_count") or 0),
        "section_count": int(manifest.get("section_count") or 0),
        "chunk_count": int(manifest.get("chunk_count") or 0),
        "bm25_ready": bool(manifest.get("bm25_ready")),
        "vector_status": str(manifest.get("vector_status") or "").strip(),
        "vector_chunk_count": int(manifest.get("vector_chunk_count") or 0),
        "runtime_eligible": bool(manifest.get("runtime_eligible") or False),
        "boundary_fail_reasons": list(
            manifest.get("boundary_fail_reasons")
            or boundary_summary.get("fail_reasons")
            or []
        ),
        "updated_at": str(manifest.get("updated_at") or "").strip(),
    }


def _normalized_access_groups(value: Any, *, tenant_id: str, workspace_id: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    else:
        items = [str(item).strip() for item in (value or [])]
    normalized = tuple(item for item in items if item)
    if normalized:
        return normalized
    fallback = (
        str(workspace_id or "").strip(),
        str(tenant_id or "").strip(),
    )
    return tuple(item for item in fallback if item)


def _apply_private_runtime_overrides(root_dir: Path, record, payload: dict[str, Any]):
    store = CustomerPackDraftStore(root_dir)
    changed = False
    for field_name in ("tenant_id", "workspace_id", "approval_state", "publication_state"):
        value = str(payload.get(field_name) or "").strip()
        if value and getattr(record, field_name, "") != value:
            setattr(record, field_name, value)
            changed = True
    for field_name in ("classification", "provider_egress_policy", "redaction_state"):
        value = str(payload.get(field_name) or "").strip()
        if value and getattr(record, field_name, "") != value:
            setattr(record, field_name, value)
            changed = True
    explicit_access_groups = "access_groups" in payload
    normalized_access_groups = _normalized_access_groups(
        payload.get("access_groups"),
        tenant_id=str(record.tenant_id or "").strip(),
        workspace_id=str(record.workspace_id or "").strip(),
    )
    if explicit_access_groups:
        if tuple(record.access_groups or ()) != normalized_access_groups:
            record.access_groups = normalized_access_groups
            changed = True
    elif changed and tuple(record.access_groups or ()) != normalized_access_groups:
        record.access_groups = normalized_access_groups
        changed = True
    if changed:
        store.save(record)
    return record


def _select_support_entry(matrix: dict[str, Any], source_type: str) -> dict[str, Any]:
    source_type = str(source_type or "").strip().lower()
    entries = [entry for entry in matrix.get("entries") or [] if isinstance(entry, dict)]
    candidates = [entry for entry in entries if str(entry.get("source_type") or "").strip().lower() == source_type]
    for status in ("supported", "staged"):
        for entry in candidates:
            if str(entry.get("support_status") or "").strip().lower() == status:
                return entry
    return candidates[0] if candidates else {}


def build_customer_pack_plan(payload: dict[str, Any]) -> dict[str, Any]:
    request = customer_pack_request_from_payload(payload)
    plan = CustomerPackPlanner().plan(request).to_dict()
    support_matrix = build_customer_pack_support_matrix()
    selected_support = _select_support_entry(support_matrix, request.source_type)
    support_review_rule = str(selected_support.get("review_rule") or "")
    ocr_metadata = dict(selected_support.get("ocr") or {})
    ocr_review_rule = str(ocr_metadata.get("review_rule") or "").strip()
    if ocr_review_rule and ocr_review_rule not in support_review_rule:
        if support_review_rule:
            support_review_rule = f"{support_review_rule} {ocr_review_rule}"
        else:
            support_review_rule = ocr_review_rule
    plan["support_status"] = str(selected_support.get("support_status") or "rejected")
    plan["support_route"] = selected_support
    plan["support_review_rule"] = support_review_rule
    plan["ocr_metadata"] = ocr_metadata
    plan["support_matrix"] = support_matrix
    return plan


def build_customer_pack_support_matrix() -> dict[str, Any]:
    return _build_customer_pack_support_matrix_model().to_dict()


def customer_pack_request_from_payload(payload: dict[str, Any]) -> DocSourceRequest:
    source_type = str(payload.get("source_type") or "").strip().lower()
    uri = str(payload.get("uri") or "").strip()
    title = str(payload.get("title") or "").strip()
    language_hint = str(payload.get("language_hint") or "ko").strip() or "ko"

    if source_type not in SUPPORTED_CUSTOMER_PACK_SOURCE_TYPES:
        raise ValueError(
            "source_type은 web, pdf, md, asciidoc, txt, docx, pptx, xlsx, image 중 하나여야 합니다."
        )
    if not uri:
        raise ValueError("uri가 필요합니다.")

    return DocSourceRequest(
        source_type=source_type,
        uri=uri,
        title=title,
        language_hint=language_hint,
    )


def create_customer_pack_draft(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    request = customer_pack_request_from_payload(payload)
    record = CustomerPackDraftStore(root_dir).create(request)
    record = _apply_private_runtime_overrides(root_dir, record, payload)
    return record.to_dict()


def upload_customer_pack_draft(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    request = customer_pack_request_from_payload(payload)
    file_name = str(payload.get("file_name") or "").strip()
    file_bytes = payload.get("file_bytes")
    if not file_name:
        raise ValueError("업로드할 file_name이 필요합니다.")
    if not isinstance(file_bytes, (bytes, bytearray)):
        content_base64 = str(payload.get("content_base64") or "").strip()
        if not content_base64:
            raise ValueError("업로드할 file_bytes가 필요합니다.")
        try:
            file_bytes = base64.b64decode(content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("content_base64가 올바른 base64 문자열이 아닙니다.") from exc

    content = bytes(file_bytes)
    if not content:
        raise ValueError("빈 파일은 업로드할 수 없습니다.")

    settings = load_settings(root_dir)
    upload_dir = settings.customer_pack_capture_dir / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    default_suffix = {
        "pdf": ".pdf",
        "md": ".md",
        "asciidoc": ".adoc",
        "txt": ".txt",
        "docx": ".docx",
        "pptx": ".pptx",
        "xlsx": ".xlsx",
        "image": ".png",
    }.get(request.source_type, ".html")
    source_suffix = Path(file_name).suffix or default_suffix
    safe_stem = re.sub(r"[^A-Za-z0-9가-힣._-]+", "-", Path(file_name).stem).strip("-") or "upload"
    target = upload_dir / f"{uuid.uuid4().hex[:10]}-{safe_stem}{source_suffix}"
    target.write_bytes(content)

    uploaded_request = DocSourceRequest(
        source_type=request.source_type,
        uri=str(target),
        title=request.title or Path(file_name).stem,
        language_hint=request.language_hint,
    )
    store = CustomerPackDraftStore(root_dir)
    record = store.create(uploaded_request)
    record.uploaded_file_name = file_name
    record.uploaded_file_path = str(target)
    record.uploaded_byte_size = len(content)
    store.save(record)
    record = _apply_private_runtime_overrides(root_dir, record, payload)
    return record.to_dict()


def load_customer_pack_draft(root_dir: Path, draft_id: str) -> dict[str, Any] | None:
    record = CustomerPackDraftStore(root_dir).get(draft_id)
    if record is None:
        return None
    payload = record.to_dict()
    canonical_payload = load_customer_pack_book(root_dir, record.draft_id)
    if canonical_payload is not None:
        payload["playable_asset_count"] = canonical_payload.get("playable_asset_count", 1)
        payload["derived_asset_count"] = canonical_payload.get("derived_asset_count", 0)
        payload["derived_assets"] = canonical_payload.get("derived_assets", [])
    private_corpus = _private_corpus_payload(root_dir, record.draft_id)
    if private_corpus is not None:
        payload["private_corpus"] = private_corpus
    return payload


def delete_customer_pack_draft(root_dir: Path, draft_id: str) -> bool:
    store = CustomerPackDraftStore(root_dir)
    record = store.get(draft_id)
    if record is None:
        return False
    settings = load_settings(root_dir)
    # Clean up canonical book and derived playbook JSONs
    books_dir = settings.customer_pack_books_dir
    if books_dir.is_dir():
        for path in books_dir.glob(f"{draft_id}*.json"):
            path.unlink(missing_ok=True)
    delete_customer_pack_private_corpus(root_dir, draft_id)
    # Clean up capture artifacts
    capture_dir = settings.customer_pack_capture_dir / draft_id
    if capture_dir.is_dir():
        import shutil
        shutil.rmtree(capture_dir, ignore_errors=True)
    return store.delete(draft_id)


def capture_customer_pack_draft(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(payload.get("draft_id") or "").strip()
    request = None if draft_id else customer_pack_request_from_payload(payload)
    record = CustomerPackCaptureService(root_dir).capture(draft_id=draft_id, request=request)
    record = _apply_private_runtime_overrides(root_dir, record, payload)
    return record.to_dict()


def normalize_customer_pack_draft(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(payload.get("draft_id") or "").strip()
    if not draft_id:
        raise ValueError("normalize할 draft_id가 필요합니다.")
    record = CustomerPackNormalizeService(root_dir).normalize(draft_id=draft_id)
    result = record.to_dict()
    canonical_payload = load_customer_pack_book(root_dir, record.draft_id)
    if canonical_payload is not None:
        result["playable_asset_count"] = canonical_payload.get("playable_asset_count", 1)
        result["derived_asset_count"] = canonical_payload.get("derived_asset_count", 0)
        result["derived_assets"] = canonical_payload.get("derived_assets", [])
    private_corpus = _private_corpus_payload(root_dir, record.draft_id)
    if private_corpus is not None:
        result["private_corpus"] = private_corpus
    return result


def ingest_customer_pack(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(payload.get("draft_id") or "").strip()
    if draft_id:
        captured = capture_customer_pack_draft(root_dir, {"draft_id": draft_id})
    elif isinstance(payload.get("file_bytes"), (bytes, bytearray)):
        uploaded = upload_customer_pack_draft(root_dir, payload)
        captured = capture_customer_pack_draft(root_dir, {"draft_id": str(uploaded["draft_id"])})
    else:
        captured = capture_customer_pack_draft(root_dir, payload)

    normalized = normalize_customer_pack_draft(
        root_dir,
        {"draft_id": str(captured["draft_id"])},
    )
    canonical_payload = load_customer_pack_book(root_dir, str(captured["draft_id"]))
    if canonical_payload is not None:
        normalized["book"] = canonical_payload
    private_corpus = _private_corpus_payload(root_dir, str(captured["draft_id"]))
    if private_corpus is not None:
        normalized["private_corpus"] = private_corpus
    return normalized


def load_customer_pack_capture(
    root_dir: Path,
    draft_id: str,
) -> tuple[bytes, str] | None:
    record = CustomerPackDraftStore(root_dir).get(draft_id)
    if record is None or not record.capture_artifact_path.strip():
        return None
    artifact_path = Path(record.capture_artifact_path)
    if not artifact_path.exists():
        return None
    return artifact_path.read_bytes(), record.capture_content_type or "application/octet-stream"


__all__ = [
    "build_customer_pack_plan",
    "build_customer_pack_support_matrix",
    "capture_customer_pack_draft",
    "create_customer_pack_draft",
    "customer_pack_request_from_payload",
    "ingest_customer_pack",
    "load_customer_pack_capture",
    "load_customer_pack_draft",
    "normalize_customer_pack_draft",
    "upload_customer_pack_draft",
]
