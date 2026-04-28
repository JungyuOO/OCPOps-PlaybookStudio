"""data_control_room library aggregation functions."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.topic_playbooks import (
    DERIVED_PLAYBOOK_SOURCE_TYPES,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
)
from play_book_studio.source_authority import COMMUNITY_AUTHORITY, source_authority_payload

from .data_control_room_helpers import _grade_label

POLICY_OVERLAY_BOOK_SOURCE_TYPE = "policy_overlay_book"
SYNTHESIZED_PLAYBOOK_SOURCE_TYPE = "synthesized_playbook"
DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES = (
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
)
DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET = frozenset(
    set(DERIVED_PLAYBOOK_SOURCE_TYPES) | {POLICY_OVERLAY_BOOK_SOURCE_TYPE, SYNTHESIZED_PLAYBOOK_SOURCE_TYPE}
)
PLAYBOOK_LIBRARY_FAMILY_LABELS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "토픽 플레이북",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "운용 플레이북",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "트러블슈팅 플레이북",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "정책 오버레이",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "종합 플레이북",
}
CUSTOM_DOCUMENT_SOURCE_LANE = "customer_custom_materials_only"
CUSTOM_DOCUMENT_SOURCE_COLLECTION = "custom_documents"
CUSTOM_DOCUMENT_SOURCE_KIND = "customer_custom_document_slot"
CUSTOM_DOCUMENT_SOURCE_KIND_LABEL = "커스텀 슬롯"
CUSTOM_DOCUMENT_PROMOTION_STAGE = "material_catalog"
CUSTOM_DOCUMENT_PROMOTION_STAGE_LABEL = "북팩토리 재료"
CUSTOM_DOCUMENT_PIPELINE_TARGET = "custom_playbook_pipeline"
CUSTOM_DOCUMENT_PIPELINE_TARGET_LABEL = "커스텀 플레이북 라인"
CUSTOM_DOCUMENT_KIND_LABELS = {
    "guide": "아키텍처 개선 가이드",
    "architecture": "아키텍처 설계",
    "unit_test": "단위 테스트",
    "integration_test": "통합 테스트",
    "performance_test": "성능 테스트",
    "custom": "커스텀 문서",
}
CUSTOM_DOCUMENT_KIND_DESCRIPTIONS = {
    "guide": "개선 사업 전체 맥락과 가이드 산출물을 담을 슬롯",
    "architecture": "시스템 구조, 운영 설계, 연계 구조를 학습용 위키로 전환할 슬롯",
    "unit_test": "단위 테스트 계획과 결과를 학습·검증 appendix로 전환할 슬롯",
    "integration_test": "통합 테스트 계획과 결과를 운영 절차와 검증 흐름으로 전환할 슬롯",
    "performance_test": "성능 테스트 결과를 운영 기준과 검증 지표로 전환할 슬롯",
    "custom": "분류 대기 중인 커스텀 문서 슬롯",
}
CUSTOM_DOCUMENT_KIND_RANK = {
    "guide": 0,
    "architecture": 1,
    "unit_test": 2,
    "integration_test": 3,
    "performance_test": 4,
    "custom": 5,
}


def _copy_source_options(*candidates: Any) -> list[dict[str, Any]]:
    for candidate in candidates:
        if isinstance(candidate, list):
            return [dict(item) for item in candidate if isinstance(item, dict)]
    return []


def _custom_document_manifest_lookup(root: Path) -> dict[str, dict[str, Any]]:
    manifest_path = root / ".P_docs" / "_review_bucket_manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {}
    items: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("bucket") or "").strip() != "material":
            continue
        relative_path = str(entry.get("relative_path") or "").strip()
        if not relative_path:
            continue
        normalized = relative_path.replace("\\", "/").strip()
        items[normalized] = dict(entry)
    return items


def _custom_document_kind(relative_path: Path, family: str) -> str:
    haystack = " ".join([*relative_path.parts, family]).lower()
    if "완료보고" in haystack or "guide" in haystack:
        return "guide"
    if "pd-arch" in haystack or "아키텍처" in haystack:
        return "architecture"
    if "pd-ut" in haystack or "단위" in haystack:
        return "unit_test"
    if "pd-it" in haystack or "통합" in haystack:
        return "integration_test"
    if "pd-perf" in haystack or "성능" in haystack:
        return "performance_test"
    return "custom"


def _custom_document_fallback_family(relative_path: Path) -> str:
    parent_name = str(relative_path.parent.name or "").strip()
    if parent_name and parent_name not in {".", "..", "01_검토대기_플레이북재료"}:
        return parent_name
    return "커스텀 문서"


def _build_custom_document_bucket(root: Path) -> dict[str, Any]:
    material_dir = (root / ".P_docs" / "01_검토대기_플레이북재료").resolve()
    if not material_dir.exists() or not material_dir.is_dir():
        return {"selected_dir": "custom_documents/materials_only", "source_count": 0, "books": []}

    manifest_lookup = _custom_document_manifest_lookup(root)
    grouped: dict[str, dict[str, Any]] = {}
    total_source_count = 0
    for path in sorted(material_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative_path_from_p_docs = path.resolve().relative_to((root / ".P_docs").resolve())
        except ValueError:
            continue
        relative_path_from_p_docs_str = relative_path_from_p_docs.as_posix()
        manifest_entry = manifest_lookup.get(relative_path_from_p_docs_str, {})
        family = str(manifest_entry.get("family") or "").strip() or _custom_document_fallback_family(relative_path_from_p_docs)
        document_kind = _custom_document_kind(relative_path_from_p_docs, family)
        if family == "01_검토대기_플레이북재료" and document_kind == "guide":
            family = "아키텍처 개선 가이드"
        stat = path.stat()
        del relative_path_from_p_docs_str
        total_source_count += 1
        bucket = grouped.setdefault(
            document_kind,
            {
                "book_slug": f"custom_doc_slot_{document_kind}",
                "title": CUSTOM_DOCUMENT_KIND_LABELS.get(document_kind, CUSTOM_DOCUMENT_KIND_LABELS["custom"]),
                "grade": "",
                "review_status": "source_material",
                "source_type": "custom_document",
                "source_lane": CUSTOM_DOCUMENT_SOURCE_LANE,
                "source_kind": CUSTOM_DOCUMENT_SOURCE_KIND,
                "source_kind_label": CUSTOM_DOCUMENT_SOURCE_KIND_LABEL,
                "section_count": 0,
                "code_block_count": 0,
                "viewer_path": "",
                "source_url": "",
                "updated_at": "",
                "source_collection": CUSTOM_DOCUMENT_SOURCE_COLLECTION,
                "source_collection_label": "커스텀 문서",
                "source_origin_label": CUSTOM_DOCUMENT_KIND_LABELS.get(document_kind, CUSTOM_DOCUMENT_KIND_LABELS["custom"]),
                "source_origin_url": "",
                "materialized": False,
                "promotion_stage": CUSTOM_DOCUMENT_PROMOTION_STAGE,
                "promotion_stage_label": CUSTOM_DOCUMENT_PROMOTION_STAGE_LABEL,
                "pipeline_target": CUSTOM_DOCUMENT_PIPELINE_TARGET,
                "pipeline_target_label": CUSTOM_DOCUMENT_PIPELINE_TARGET_LABEL,
                "custom_document_kind": document_kind,
                "custom_document_kind_label": CUSTOM_DOCUMENT_KIND_LABELS.get(document_kind, CUSTOM_DOCUMENT_KIND_LABELS["custom"]),
                "custom_document_family": family,
                "custom_document_description": CUSTOM_DOCUMENT_KIND_DESCRIPTIONS.get(document_kind, CUSTOM_DOCUMENT_KIND_DESCRIPTIONS["custom"]),
                "custom_document_source_count": 0,
                "custom_document_total_size_bytes": 0,
                "custom_document_ext_breakdown": Counter(),
                "custom_document_status": "ui_ready_source_hidden",
            },
        )
        bucket["custom_document_source_count"] = int(bucket.get("custom_document_source_count") or 0) + 1
        bucket["custom_document_total_size_bytes"] = int(bucket.get("custom_document_total_size_bytes") or 0) + int(stat.st_size)
        ext = path.suffix.lower().lstrip(".") or "file"
        bucket["custom_document_ext_breakdown"][ext] += 1
        bucket["section_count"] = int(bucket.get("custom_document_source_count") or 0)
        updated_at = str(bucket.get("updated_at") or "")
        path_updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        if not updated_at or path_updated_at > updated_at:
            bucket["updated_at"] = path_updated_at

    books = list(grouped.values())
    for book in books:
        ext_counter = book.get("custom_document_ext_breakdown")
        book["custom_document_ext_breakdown"] = dict(sorted(ext_counter.items())) if isinstance(ext_counter, Counter) else {}
    books.sort(
        key=lambda item: (
            int(CUSTOM_DOCUMENT_KIND_RANK.get(str(item.get("custom_document_kind") or "custom"), 99)),
            str(item.get("title") or "").lower(),
        )
    )
    return {
        "selected_dir": "custom_documents/materials_only",
        "source_count": total_source_count,
        "slot_count": len(books),
        "source_kind": CUSTOM_DOCUMENT_SOURCE_KIND,
        "source_kind_label": CUSTOM_DOCUMENT_SOURCE_KIND_LABEL,
        "promotion_stage": CUSTOM_DOCUMENT_PROMOTION_STAGE,
        "promotion_stage_label": CUSTOM_DOCUMENT_PROMOTION_STAGE_LABEL,
        "pipeline_target": CUSTOM_DOCUMENT_PIPELINE_TARGET,
        "pipeline_target_label": CUSTOM_DOCUMENT_PIPELINE_TARGET_LABEL,
        "books": books,
    }


def _customer_pack_source_origin_label(record: Any, fallback_title: str = "") -> str:
    uploaded_file_name = str(getattr(record, "uploaded_file_name", "") or "").strip()
    if uploaded_file_name:
        return uploaded_file_name
    request = getattr(record, "request", None)
    request_uri = str(getattr(request, "uri", "") or "").strip()
    if request_uri:
        if "://" not in request_uri:
            name = Path(request_uri).name.strip()
            if name:
                return name
        tail = request_uri.rstrip("/").rsplit("/", 1)[-1].strip()
        if tail:
            return tail
        return request_uri
    plan = getattr(record, "plan", None)
    title = str(getattr(plan, "title", "") or fallback_title).strip()
    return title or fallback_title


def _customer_pack_draft_id_from_book(book: dict[str, Any]) -> str:
    viewer_path = str(book.get("viewer_path") or "").strip()
    prefix = "/playbooks/customer-packs/"
    if viewer_path.startswith(prefix):
        remainder = viewer_path[len(prefix) :]
        parts = [part for part in remainder.split("/") if part]
        if parts:
            return str(parts[0]).strip()
    slug = str(book.get("book_slug") or "").strip()
    return slug.split("--", 1)[0].strip() if "--" in slug else ""


def _customer_pack_capture_url(draft_id: str) -> str:
    normalized = str(draft_id or "").strip()
    return f"/api/customer-packs/captured?draft_id={normalized}" if normalized else ""


def _customer_pack_surface_payload(record: Any) -> dict[str, Any]:
    manifest_path = Path(str(getattr(record, "private_corpus_manifest_path", "") or "").strip())
    if manifest_path.as_posix() in {"", "."} or not manifest_path.exists() or not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _authoritative_value(primary: dict[str, Any], secondary: dict[str, Any], key: str, fallback: Any = "") -> Any:
    if key in primary:
        return primary.get(key)
    if key in secondary:
        return secondary.get(key)
    return fallback


def _apply_source_authority_surface(entry: dict[str, Any], *sources: dict[str, Any]) -> dict[str, Any]:
    authority_input: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, dict):
            authority_input.update(source)
    authority_input.update(entry)
    entry.update(source_authority_payload(authority_input))
    if entry.get("source_authority") == COMMUNITY_AUTHORITY:
        entry["boundary_truth"] = "community_source_pack_runtime"
        entry["runtime_truth_label"] = "Community Source Pack"
        entry["boundary_badge"] = "Community Source"
    return entry


def _apply_customer_pack_runtime_truth(
    books: list[dict[str, Any]],
    *,
    draft_records_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for book in books:
        entry = dict(book)
        draft_id = _customer_pack_draft_id_from_book(entry)
        record = draft_records_by_id.get(draft_id) if draft_id else None
        if record is not None:
            surface_payload = _customer_pack_surface_payload(record)
            grade_gate = dict(
                _authoritative_value(surface_payload, entry, "grade_gate", {})
                or {}
            )
            citation_gate = dict(grade_gate.get("citation_gate") or {})
            retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
            promotion_gate = dict(grade_gate.get("promotion_gate") or {})
            source_origin_label = _customer_pack_source_origin_label(
                record,
                fallback_title=str(entry.get("title") or getattr(getattr(record, "plan", None), "title", "") or "").strip(),
            )
            entry["source_lane"] = str(getattr(record, "source_lane", "") or entry.get("source_lane") or "customer_source_first_pack")
            entry["approval_state"] = str(getattr(record, "approval_state", "") or entry.get("approval_state") or "unreviewed")
            entry["publication_state"] = str(getattr(record, "publication_state", "") or entry.get("publication_state") or "draft")
            entry["parser_backend"] = str(getattr(record, "parser_backend", "") or entry.get("parser_backend") or "customer_pack_normalize_service")
            entry["boundary_truth"] = str(entry.get("boundary_truth") or "private_customer_pack_runtime")
            entry["runtime_truth_label"] = str(entry.get("runtime_truth_label") or "Customer Source-First Pack")
            entry["boundary_badge"] = str(entry.get("boundary_badge") or "Private Pack Runtime")
            entry["source_collection"] = str(
                getattr(getattr(record, "plan", None), "source_collection", "")
                or entry.get("source_collection")
                or "uploaded"
            )
            entry["draft_id"] = draft_id
            entry["source_origin_label"] = str(entry.get("source_origin_label") or source_origin_label)
            entry["source_origin_url"] = _customer_pack_capture_url(draft_id)
            entry["delete_target_kind"] = str(entry.get("delete_target_kind") or "customer_pack_draft")
            entry["delete_target_id"] = str(entry.get("delete_target_id") or draft_id)
            entry["delete_target_label"] = str(entry.get("delete_target_label") or source_origin_label or draft_id)
            entry["chunk_scope"] = "customer_pack"
            entry["corpus_runtime_eligible"] = bool(
                str(getattr(record, "private_corpus_status", "") or "").strip() == "ready"
                or entry.get("corpus_runtime_eligible")
            )
            entry["corpus_vector_status"] = str(
                getattr(record, "private_corpus_vector_status", "")
                or entry.get("corpus_vector_status")
                or ""
            )
            entry["quality_status"] = str(_authoritative_value(surface_payload, entry, "quality_status", "") or "")
            entry["quality_summary"] = str(_authoritative_value(surface_payload, entry, "quality_summary", "") or "")
            entry["shared_grade"] = str(_authoritative_value(surface_payload, entry, "shared_grade", "") or "")
            entry["grade_gate"] = grade_gate
            entry["citation_landing_status"] = str(
                _authoritative_value(
                    surface_payload,
                    entry,
                    "citation_landing_status",
                    citation_gate.get("status") or "",
                )
                or ""
            )
            entry["retrieval_ready"] = bool(
                _authoritative_value(
                    surface_payload,
                    entry,
                    "retrieval_ready",
                    retrieval_gate.get("ready"),
                )
            )
            entry["read_ready"] = bool(
                _authoritative_value(
                    surface_payload,
                    entry,
                    "read_ready",
                    promotion_gate.get("read_ready"),
                )
            )
            entry["publish_ready"] = bool(
                _authoritative_value(
                    surface_payload,
                    entry,
                    "publish_ready",
                    promotion_gate.get("publish_ready"),
                )
            )
            _apply_source_authority_surface(entry, surface_payload)
            entry["grade"] = _grade_label(entry)
        items.append(entry)
    return items


def _aggregate_corpus_books(
    rows: list[dict[str, Any]],
    *,
    manifest_by_slug: dict[str, dict[str, Any]],
    known_books: dict[str, dict[str, Any]],
    grade_label: Any,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        grade_source = {
            **manifest_by_slug.get(slug, {}),
            **known_books.get(slug, {}),
            **row,
        }
        row_grade_gate = dict(row.get("grade_gate") or {})
        row_citation_gate = dict(row_grade_gate.get("citation_gate") or {})
        row_retrieval_gate = dict(row_grade_gate.get("retrieval_gate") or {})
        row_promotion_gate = dict(row_grade_gate.get("promotion_gate") or {})
        title = str(row.get("book_title") or "") or str(known_books.get(slug, {}).get("title") or "") or str(manifest_by_slug.get(slug, {}).get("title") or "") or slug
        bucket = grouped.setdefault(
            slug,
            {
                "book_slug": slug,
                "title": title,
                "grade": grade_label(grade_source) if grade_source else ("Gold" if slug in manifest_by_slug else "Bronze"),
                "chunk_count": 0,
                "token_total": 0,
                "command_chunk_count": 0,
                "error_chunk_count": 0,
                "anchors": set(),
                "chunk_types": Counter(),
                "source_type": str(row.get("source_type") or manifest_by_slug.get(slug, {}).get("source_type") or ""),
                "source_lane": str(row.get("source_lane") or manifest_by_slug.get(slug, {}).get("source_lane") or ""),
                "review_status": str(row.get("review_status") or manifest_by_slug.get(slug, {}).get("review_status") or ""),
                "updated_at": str(row.get("updated_at") or manifest_by_slug.get(slug, {}).get("updated_at") or ""),
                "viewer_path": str(row.get("viewer_path") or manifest_by_slug.get(slug, {}).get("viewer_path") or ""),
                "source_url": str(row.get("source_url") or known_books.get(slug, {}).get("source_url") or manifest_by_slug.get(slug, {}).get("source_url") or ""),
                "source_collection": str(row.get("source_collection") or manifest_by_slug.get(slug, {}).get("source_collection") or ""),
                "approval_state": str(row.get("approval_state") or known_books.get(slug, {}).get("approval_state") or manifest_by_slug.get(slug, {}).get("approval_state") or ""),
                "publication_state": str(row.get("publication_state") or known_books.get(slug, {}).get("publication_state") or manifest_by_slug.get(slug, {}).get("publication_state") or ""),
                "parser_backend": str(row.get("parser_backend") or known_books.get(slug, {}).get("parser_backend") or manifest_by_slug.get(slug, {}).get("parser_backend") or ""),
                "boundary_truth": str(row.get("boundary_truth") or known_books.get(slug, {}).get("boundary_truth") or manifest_by_slug.get(slug, {}).get("boundary_truth") or ""),
                "runtime_truth_label": str(row.get("runtime_truth_label") or known_books.get(slug, {}).get("runtime_truth_label") or manifest_by_slug.get(slug, {}).get("runtime_truth_label") or ""),
                "boundary_badge": str(row.get("boundary_badge") or known_books.get(slug, {}).get("boundary_badge") or manifest_by_slug.get(slug, {}).get("boundary_badge") or ""),
                "current_source_basis": str(row.get("current_source_basis") or known_books.get(slug, {}).get("current_source_basis") or manifest_by_slug.get(slug, {}).get("current_source_basis") or ""),
                "current_source_label": str(row.get("current_source_label") or known_books.get(slug, {}).get("current_source_label") or manifest_by_slug.get(slug, {}).get("current_source_label") or ""),
                "source_options": _copy_source_options(row.get("source_options"), known_books.get(slug, {}).get("source_options"), manifest_by_slug.get(slug, {}).get("source_options")),
                "source_origin_label": str(row.get("source_origin_label") or known_books.get(slug, {}).get("current_source_label") or manifest_by_slug.get(slug, {}).get("current_source_label") or ""),
                "source_origin_url": str(row.get("source_origin_url") or row.get("source_url") or known_books.get(slug, {}).get("source_url") or manifest_by_slug.get(slug, {}).get("source_url") or ""),
                "draft_id": str(row.get("draft_id") or ""),
                "delete_target_kind": str(row.get("delete_target_kind") or ""),
                "delete_target_id": str(row.get("delete_target_id") or ""),
                "delete_target_label": str(row.get("delete_target_label") or ""),
                "chunk_scope": str(row.get("chunk_scope") or "runtime"),
                "quality_status": str(row.get("quality_status") or ""),
                "quality_summary": str(row.get("quality_summary") or ""),
                "shared_grade": str(row.get("shared_grade") or ""),
                "grade_gate": row_grade_gate,
                "citation_landing_status": str(row.get("citation_landing_status") or row_citation_gate.get("status") or ""),
                "retrieval_ready": bool(row.get("retrieval_ready") or row_retrieval_gate.get("ready")),
                "read_ready": bool(row.get("read_ready") or row_promotion_gate.get("read_ready")),
                "publish_ready": bool(row.get("publish_ready") or row_promotion_gate.get("publish_ready")),
                "materialized": True,
            },
        )
        bucket["chunk_count"] += 1
        bucket["token_total"] += int(row.get("token_count") or 0)
        if row.get("cli_commands"):
            bucket["command_chunk_count"] += 1
        if row.get("error_strings"):
            bucket["error_chunk_count"] += 1
        anchor_id = str(row.get("anchor_id") or row.get("anchor") or "").strip()
        if anchor_id:
            bucket["anchors"].add(anchor_id)
        bucket["chunk_types"][str(row.get("chunk_type") or "unknown").strip() or "unknown"] += 1
    for slug, entry in manifest_by_slug.items():
        grade_source = {
            **entry,
            **known_books.get(slug, {}),
        }
        grouped.setdefault(
            slug,
            {
                "book_slug": slug,
                "title": str(entry.get("title") or slug),
                "grade": grade_label(grade_source) if grade_source else "Gold",
                "chunk_count": 0,
                "token_total": 0,
                "command_chunk_count": 0,
                "error_chunk_count": 0,
                "anchors": set(),
                "chunk_types": Counter(),
                "source_type": str(entry.get("source_type") or ""),
                "source_lane": str(entry.get("source_lane") or ""),
                "review_status": str(entry.get("review_status") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
                "viewer_path": str(entry.get("viewer_path") or ""),
                "source_url": str(known_books.get(slug, {}).get("source_url") or entry.get("source_url") or ""),
                "source_collection": str(entry.get("source_collection") or ""),
                "approval_state": str(known_books.get(slug, {}).get("approval_state") or entry.get("approval_state") or ""),
                "publication_state": str(known_books.get(slug, {}).get("publication_state") or entry.get("publication_state") or ""),
                "parser_backend": str(known_books.get(slug, {}).get("parser_backend") or entry.get("parser_backend") or ""),
                "boundary_truth": str(known_books.get(slug, {}).get("boundary_truth") or entry.get("boundary_truth") or ""),
                "runtime_truth_label": str(known_books.get(slug, {}).get("runtime_truth_label") or entry.get("runtime_truth_label") or ""),
                "boundary_badge": str(known_books.get(slug, {}).get("boundary_badge") or entry.get("boundary_badge") or ""),
                "current_source_basis": str(known_books.get(slug, {}).get("current_source_basis") or entry.get("current_source_basis") or ""),
                "current_source_label": str(known_books.get(slug, {}).get("current_source_label") or entry.get("current_source_label") or ""),
                "source_options": _copy_source_options(known_books.get(slug, {}).get("source_options"), entry.get("source_options")),
                "source_origin_label": str(known_books.get(slug, {}).get("current_source_label") or entry.get("current_source_label") or ""),
                "source_origin_url": str(known_books.get(slug, {}).get("source_url") or entry.get("source_url") or ""),
                "draft_id": "",
                "delete_target_kind": "",
                "delete_target_id": "",
                "delete_target_label": "",
                "chunk_scope": "runtime",
                "quality_status": "",
                "quality_summary": "",
                "shared_grade": "",
                "grade_gate": {},
                "citation_landing_status": "",
                "retrieval_ready": False,
                "read_ready": False,
                "publish_ready": False,
                "materialized": False,
            },
        )
    items: list[dict[str, Any]] = []
    for entry in grouped.values():
        chunk_types = entry.pop("chunk_types")
        anchors = entry.pop("anchors")
        items.append({**entry, "anchor_count": len(anchors), "chunk_type_breakdown": dict(sorted(chunk_types.items()))})
    return sorted(items, key=lambda item: (-int(item["chunk_count"]), str(item["book_slug"])))


def _aggregate_playbooks(
    files: list[Path],
    *,
    manifest_by_slug: dict[str, dict[str, Any]],
    known_books: dict[str, dict[str, Any]],
    grade_label: Any,
    safe_read_json: Any,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for path in files:
        payload = safe_read_json(path)
        slug = str(payload.get("asset_slug") or payload.get("book_slug") or path.stem).strip()
        if not slug:
            continue
        sections = payload.get("sections")
        if not isinstance(sections, list):
            sections = []
        section_roles = Counter()
        block_kinds = Counter()
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_roles[str(section.get("semantic_role") or "unknown").strip() or "unknown"] += 1
            for block in section.get("blocks") or []:
                if isinstance(block, dict):
                    block_kinds[str(block.get("kind") or "unknown").strip() or "unknown"] += 1
        source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), dict) else {}
        playbook_family = str(payload.get("playbook_family") or "").strip()
        source_type = str((playbook_family if playbook_family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET else (source_metadata.get("source_type") or payload.get("source_type") or "")) or "")
        known = known_books.get(slug, {})
        manifest = manifest_by_slug.get(slug, {})
        grade_gate = dict(payload.get("grade_gate") or {})
        citation_gate = dict(grade_gate.get("citation_gate") or {})
        retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
        promotion_gate = dict(grade_gate.get("promotion_gate") or {})
        grade_source = {
            **manifest,
            **known,
            **payload,
        }
        entry = {
            "book_slug": slug,
            "title": str(payload.get("title") or payload.get("book_title") or slug),
            "grade": grade_label(grade_source) if grade_source else ("Gold" if manifest else "Bronze"),
            "translation_status": str(payload.get("translation_status") or known.get("content_status") or ""),
            "review_status": str(payload.get("review_status") or known.get("review_status") or ""),
            "source_type": source_type or str(known.get("source_type") or manifest.get("source_type") or ""),
            "source_lane": str(source_metadata.get("source_lane") or known.get("source_lane") or manifest.get("source_lane") or ""),
            "source_collection": str(payload.get("source_collection") or source_metadata.get("source_collection") or ""),
            "section_count": len(sections),
            "anchor_count": len(payload.get("anchor_map") or {}),
            "code_block_count": int(block_kinds.get("code", 0)),
            "procedure_block_count": int(block_kinds.get("procedure", 0)),
            "paragraph_block_count": int(block_kinds.get("paragraph", 0)),
            "semantic_role_breakdown": dict(sorted(section_roles.items())),
            "block_kind_breakdown": dict(sorted(block_kinds.items())),
            "legal_notice_url": str(payload.get("legal_notice_url") or source_metadata.get("legal_notice_url") or ""),
            "viewer_path": str(payload.get("target_viewer_path") or payload.get("viewer_path") or manifest.get("viewer_path") or known.get("viewer_path") or ""),
            "source_url": str(payload.get("source_origin_url") or payload.get("source_uri") or payload.get("source_url") or ""),
            "updated_at": str(source_metadata.get("updated_at") or known.get("updated_at") or manifest.get("updated_at") or ""),
            "approval_state": str(payload.get("approval_state") or source_metadata.get("approval_state") or known.get("approval_state") or manifest.get("approval_state") or ""),
            "publication_state": str(payload.get("publication_state") or source_metadata.get("publication_state") or known.get("publication_state") or manifest.get("publication_state") or ""),
            "parser_backend": str(payload.get("parser_backend") or source_metadata.get("parser_backend") or ""),
            "boundary_truth": str(payload.get("boundary_truth") or source_metadata.get("boundary_truth") or known.get("boundary_truth") or manifest.get("boundary_truth") or ""),
            "runtime_truth_label": str(payload.get("runtime_truth_label") or source_metadata.get("runtime_truth_label") or known.get("runtime_truth_label") or manifest.get("runtime_truth_label") or ""),
            "boundary_badge": str(payload.get("boundary_badge") or source_metadata.get("boundary_badge") or known.get("boundary_badge") or manifest.get("boundary_badge") or ""),
            "current_source_basis": str(payload.get("current_source_basis") or known.get("current_source_basis") or manifest.get("current_source_basis") or ""),
            "current_source_label": str(payload.get("current_source_label") or known.get("current_source_label") or manifest.get("current_source_label") or ""),
            "source_options": _copy_source_options(payload.get("source_options"), known.get("source_options"), manifest.get("source_options")),
            "source_origin_label": str(payload.get("source_origin_label") or source_metadata.get("source_origin_label") or payload.get("current_source_label") or known.get("current_source_label") or manifest.get("current_source_label") or ""),
            "source_origin_url": str(payload.get("source_origin_url") or payload.get("source_origin_href") or payload.get("source_uri") or payload.get("source_url") or ""),
            "draft_id": str(payload.get("draft_id") or payload.get("derived_from_draft_id") or ""),
            "delete_target_kind": str(payload.get("delete_target_kind") or ""),
            "delete_target_id": str(payload.get("delete_target_id") or ""),
            "delete_target_label": str(payload.get("delete_target_label") or ""),
            "chunk_scope": str(payload.get("chunk_scope") or "runtime"),
            "quality_status": str(payload.get("quality_status") or ""),
            "quality_summary": str(payload.get("quality_summary") or ""),
            "shared_grade": str(payload.get("shared_grade") or ""),
            "grade_gate": grade_gate,
            "citation_landing_status": str(payload.get("citation_landing_status") or citation_gate.get("status") or ""),
            "retrieval_ready": bool(payload.get("retrieval_ready") or retrieval_gate.get("ready")),
            "read_ready": bool(payload.get("read_ready") or promotion_gate.get("read_ready")),
            "publish_ready": bool(payload.get("publish_ready") or promotion_gate.get("publish_ready")),
            "materialized": True,
        }
        grouped[slug] = _apply_source_authority_surface(entry, manifest, known, source_metadata, payload)
    for slug, entry in manifest_by_slug.items():
        grade_source = {
            **entry,
            **known_books.get(slug, {}),
        }
        grouped.setdefault(
            slug,
            {
                "book_slug": slug,
                "title": str(entry.get("title") or slug),
                "grade": grade_label(grade_source) if grade_source else "Gold",
                "translation_status": str(entry.get("content_status") or ""),
                "review_status": str(entry.get("review_status") or ""),
                "source_type": str(entry.get("source_type") or ""),
                "source_lane": str(entry.get("source_lane") or ""),
                "section_count": 0,
                "anchor_count": 0,
                "code_block_count": 0,
                "procedure_block_count": 0,
                "paragraph_block_count": 0,
                "semantic_role_breakdown": {},
                "block_kind_breakdown": {},
                "legal_notice_url": str(entry.get("legal_notice_url") or ""),
                "viewer_path": str(entry.get("viewer_path") or ""),
                "source_url": str(known_books.get(slug, {}).get("source_url") or entry.get("source_url") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
                "approval_state": str(known_books.get(slug, {}).get("approval_state") or entry.get("approval_state") or ""),
                "publication_state": str(known_books.get(slug, {}).get("publication_state") or entry.get("publication_state") or ""),
                "parser_backend": str(known_books.get(slug, {}).get("parser_backend") or entry.get("parser_backend") or ""),
                "boundary_truth": str(known_books.get(slug, {}).get("boundary_truth") or entry.get("boundary_truth") or ""),
                "runtime_truth_label": str(known_books.get(slug, {}).get("runtime_truth_label") or entry.get("runtime_truth_label") or ""),
                "boundary_badge": str(known_books.get(slug, {}).get("boundary_badge") or entry.get("boundary_badge") or ""),
                "current_source_basis": str(known_books.get(slug, {}).get("current_source_basis") or entry.get("current_source_basis") or ""),
                "current_source_label": str(known_books.get(slug, {}).get("current_source_label") or entry.get("current_source_label") or ""),
                "source_options": _copy_source_options(known_books.get(slug, {}).get("source_options"), entry.get("source_options")),
                "source_origin_label": str(known_books.get(slug, {}).get("current_source_label") or entry.get("current_source_label") or ""),
                "source_origin_url": str(known_books.get(slug, {}).get("source_url") or entry.get("source_url") or ""),
                "draft_id": "",
                "delete_target_kind": "",
                "delete_target_id": "",
                "delete_target_label": "",
                "chunk_scope": "runtime",
                "quality_status": "",
                "quality_summary": "",
                "shared_grade": "",
                "grade_gate": {},
                "citation_landing_status": "",
                "retrieval_ready": False,
                "read_ready": False,
                "publish_ready": False,
                "materialized": False,
            },
        )
    return sorted(grouped.values(), key=lambda item: (-int(item["section_count"]), str(item["book_slug"])))


def _derived_family_status(family: str, books: list[dict[str, Any]]) -> dict[str, Any]:
    slugs = sorted(str(book.get("book_slug") or "").strip() for book in books if str(book.get("book_slug") or "").strip())
    return {"family": family, "count": len(books), "slugs": slugs, "status": "materialized" if books else "not_emitted", "books": books}


def _library_breakdown(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"key": key, "count": count} for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def _build_manual_book_library(core_manualbooks: list[dict[str, Any]], extra_manualbooks: list[dict[str, Any]]) -> dict[str, Any]:
    books: list[dict[str, Any]] = []
    source_type_counter: Counter[str] = Counter()
    for group_key, group_label, group_books in (("runtime_core", "런타임 팩", core_manualbooks), ("extra", "확장 북", extra_manualbooks)):
        for book in group_books:
            item = dict(book)
            item["library_group"] = group_key
            item["library_group_label"] = group_label
            books.append(item)
            source_type_counter[str(item.get("source_type") or "unknown").strip() or "unknown"] += 1
    return {
        "total_count": len(books),
        "core_count": len(core_manualbooks),
        "extra_count": len(extra_manualbooks),
        "books": books,
        "group_breakdown": [
            {"key": "runtime_core", "label": "런타임 팩", "count": len(core_manualbooks)},
            {"key": "extra", "label": "확장 북", "count": len(extra_manualbooks)},
        ],
        "source_type_breakdown": _library_breakdown(source_type_counter),
    }


def _build_playbook_library(derived_playbook_family_statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    families: list[dict[str, Any]] = []
    books: list[dict[str, Any]] = []
    for family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES:
        status = derived_playbook_family_statuses.get(family, {})
        family_books: list[dict[str, Any]] = []
        for book in status.get("books") or []:
            if isinstance(book, dict):
                item = dict(book)
                item["family"] = family
                item["family_label"] = PLAYBOOK_LIBRARY_FAMILY_LABELS.get(family, family)
                family_books.append(item)
        families.append(
            {
                "family": family,
                "family_label": PLAYBOOK_LIBRARY_FAMILY_LABELS.get(family, family),
                "count": len(family_books),
                "status": str(status.get("status") or "not_emitted"),
                "books": family_books,
            }
        )
        books.extend(family_books)
    return {"total_count": len(books), "family_count": sum(1 for family in families if int(family.get("count") or 0) > 0), "families": families, "books": books}


def _apply_viewer_path_fallback(books: list[dict[str, Any]], *, root: Path) -> list[dict[str, Any]]:
    settings = load_settings(root)
    playbook_dir = settings.playbook_books_dir.resolve()
    for book in books:
        if str(book.get("viewer_path") or "").strip():
            continue
        slug = str(book.get("book_slug") or "").strip()
        if slug and (playbook_dir / f"{slug}.json").exists():
            book["viewer_path"] = settings.viewer_path_template.format(slug=slug)
    return books


def _attach_corpus_status(
    books: list[dict[str, Any]],
    *,
    corpus_by_slug: dict[str, dict[str, Any]],
    default_chunk_scope: str = "runtime",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for book in books:
        entry = dict(book)
        slug = str(entry.get("book_slug") or "").strip()
        corpus = corpus_by_slug.get(slug)
        if corpus is not None:
            entry["corpus_chunk_count"] = int(entry.get("corpus_chunk_count") or corpus.get("chunk_count") or 0)
            entry["corpus_token_total"] = int(entry.get("corpus_token_total") or corpus.get("token_total") or 0)
            entry["corpus_materialized"] = bool(corpus.get("materialized"))
            entry["chunk_scope"] = str(entry.get("chunk_scope") or corpus.get("chunk_scope") or default_chunk_scope)
            if not str(entry.get("draft_id") or "").strip():
                entry["draft_id"] = str(corpus.get("draft_id") or "")
            for key in ("source_origin_label", "source_origin_url", "delete_target_kind", "delete_target_id", "delete_target_label"):
                if not str(entry.get(key) or "").strip():
                    entry[key] = str(corpus.get(key) or "")
            if "corpus_runtime_eligible" not in entry:
                entry["corpus_runtime_eligible"] = bool(corpus.get("corpus_runtime_eligible"))
            if not str(entry.get("corpus_vector_status") or "").strip():
                entry["corpus_vector_status"] = str(corpus.get("corpus_vector_status") or "")
            entry["quality_status"] = str(_authoritative_value(corpus, entry, "quality_status", "") or "")
            entry["quality_summary"] = str(_authoritative_value(corpus, entry, "quality_summary", "") or "")
            entry["shared_grade"] = str(_authoritative_value(corpus, entry, "shared_grade", "") or "")
            entry["citation_landing_status"] = str(
                _authoritative_value(corpus, entry, "citation_landing_status", "") or ""
            )
            entry["grade_gate"] = dict(_authoritative_value(corpus, entry, "grade_gate", {}) or {})
            entry["retrieval_ready"] = bool(_authoritative_value(corpus, entry, "retrieval_ready", False))
            entry["read_ready"] = bool(_authoritative_value(corpus, entry, "read_ready", False))
            entry["publish_ready"] = bool(_authoritative_value(corpus, entry, "publish_ready", False))
        else:
            entry["corpus_chunk_count"] = int(entry.get("corpus_chunk_count") or 0)
            entry["corpus_token_total"] = int(entry.get("corpus_token_total") or 0)
            entry["corpus_materialized"] = bool(entry.get("corpus_materialized", False))
            entry["chunk_scope"] = str(entry.get("chunk_scope") or default_chunk_scope)
        entry["grade"] = _grade_label(entry)
        items.append(entry)
    return items


__all__ = [
    "CUSTOM_DOCUMENT_SOURCE_COLLECTION",
    "CUSTOM_DOCUMENT_SOURCE_LANE",
    "DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES",
    "DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET",
    "OPERATION_PLAYBOOK_SOURCE_TYPE",
    "PLAYBOOK_LIBRARY_FAMILY_LABELS",
    "POLICY_OVERLAY_BOOK_SOURCE_TYPE",
    "SYNTHESIZED_PLAYBOOK_SOURCE_TYPE",
    "TOPIC_PLAYBOOK_SOURCE_TYPE",
    "TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE",
    "_aggregate_corpus_books",
    "_aggregate_playbooks",
    "_attach_corpus_status",
    "_apply_customer_pack_runtime_truth",
    "_apply_viewer_path_fallback",
    "_build_custom_document_bucket",
    "_build_manual_book_library",
    "_build_playbook_library",
    "_derived_family_status",
]
