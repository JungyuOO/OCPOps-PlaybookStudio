from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .common import relative_project_path


def _load_learning_route_overrides() -> dict[str, Any]:
    path = Path("manifests/course_learning_routes_overrides.json")
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _sort_key_for_stage(stage_id: str, chunk: dict[str, Any]) -> tuple[Any, ...]:
    native_id = str(chunk.get("native_id") or "")
    official_refs = len(chunk.get("related_official_docs") or []) if isinstance(chunk.get("related_official_docs"), list) else 0
    slide_refs = len(chunk.get("slide_refs") or []) if isinstance(chunk.get("slide_refs"), list) else 0
    if stage_id == "architecture":
        preferred = ["DSGN-005-001", "DSGN-005-202", "DSGN-005-209", "DSGN-005-030", "DSGN-005-401", "DSGN-005-402", "DSGN-005-403"]
        rank = preferred.index(native_id) if native_id in preferred else 999
        numeric = tuple(int(item) for item in re.findall(r"\d+", native_id))
        return (rank, numeric, -official_refs, -slide_refs, native_id)
    if stage_id == "unit_test":
        numeric = tuple(int(item) for item in re.findall(r"\d+", native_id))
        return (numeric, -official_refs, -slide_refs, native_id)
    if stage_id in {"integration_test", "perf_test"}:
        numeric = tuple(int(item) for item in re.findall(r"\d+", native_id))
        return (-official_refs, -slide_refs, numeric, native_id)
    if stage_id == "completion":
        numeric = tuple(int(item) for item in re.findall(r"\d+", native_id))
        return (numeric, -slide_refs, native_id)
    return (native_id,)


def _stage_route_reason(stage_id: str) -> str:
    reasons = {
        "architecture": "기반 아키텍처를 먼저 보고, 주요 흐름과 매핑 구성을 순서대로 따라가며 전체 설계를 이해합니다.",
        "unit_test": "개별 기능 검증부터 순차적으로 따라가며 모듈 단위의 기대 결과와 확인 포인트를 익힙니다.",
        "integration_test": "시나리오 단위로 서비스 간 연결을 먼저 잡고, 상세 결과는 그 다음에 열어 전체 흐름을 붙입니다.",
        "perf_test": "핵심 성능 구간을 먼저 보고, 그래프와 상세 결과를 이어서 열어 병목과 튜닝 포인트를 읽습니다.",
        "completion": "완료보고의 챕터 흐름을 먼저 따라가며 프로젝트 전체 맥락을 잡고, 필요한 상세 슬라이드만 뒤이어 봅니다.",
    }
    return reasons.get(stage_id, "핵심 산출물을 먼저 보고, 필요한 상세는 그 다음에 따라가며 학습합니다.")


def _build_learning_route(stage_id: str, stage_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not stage_chunks:
        return {
            "start_here": [],
            "then_open": [],
            "why_this_order": _stage_route_reason(stage_id),
        }
    ordered = sorted(stage_chunks, key=lambda chunk: _sort_key_for_stage(stage_id, chunk))
    start_here = [str(chunk.get("chunk_id") or "") for chunk in ordered[:3] if str(chunk.get("chunk_id") or "").strip()]
    then_open = [str(chunk.get("chunk_id") or "") for chunk in ordered[3:5] if str(chunk.get("chunk_id") or "").strip()]
    return {
        "start_here": start_here,
        "then_open": then_open,
        "why_this_order": _stage_route_reason(stage_id),
    }


def _merge_learning_route(stage_id: str, generated: dict[str, Any], *, overrides: dict[str, Any]) -> dict[str, Any]:
    stage_override = overrides.get(stage_id) if isinstance(overrides.get(stage_id), dict) else {}
    if not stage_override:
        return generated
    return {
        "start_here": list(stage_override.get("start_here") or generated.get("start_here") or []),
        "then_open": list(stage_override.get("then_open") or generated.get("then_open") or []),
        "why_this_order": str(stage_override.get("why_this_order") or generated.get("why_this_order") or ""),
    }


def _tour_ordered_chunk_ids(stage_id: str, stage_chunks: list[dict[str, Any]], learning_route: dict[str, Any]) -> list[str]:
    existing = {str(chunk.get("chunk_id") or "") for chunk in stage_chunks if str(chunk.get("chunk_id") or "").strip()}
    ordered: list[str] = []
    for key in ("start_here", "then_open"):
        for chunk_id in learning_route.get(key) if isinstance(learning_route.get(key), list) else []:
            normalized = str(chunk_id or "").strip()
            if normalized and normalized in existing and normalized not in ordered:
                ordered.append(normalized)
    for chunk in sorted(stage_chunks, key=lambda item: _sort_key_for_stage(stage_id, item)):
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in ordered:
            ordered.append(chunk_id)
    return ordered


def _tour_stop_record(
    *,
    chunk: dict[str, Any],
    stage_id: str,
    stage_order: int,
    stage_title: str,
    stop_order: int,
    total_stops: int,
    route_role: str,
    previous_chunk_id: str,
    next_chunk_id: str,
) -> dict[str, Any]:
    official_docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
    child_chunk_ids = chunk.get("child_chunk_ids") if isinstance(chunk.get("child_chunk_ids"), list) else []
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    return {
        "stop_id": str(chunk.get("chunk_id") or ""),
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "stage_id": stage_id,
        "stage_order": stage_order,
        "stage_title": stage_title,
        "stop_order": stop_order,
        "total_stops": total_stops,
        "route_role": route_role,
        "title": str(chunk.get("title") or ""),
        "native_id": str(chunk.get("native_id") or ""),
        "previous_stop_id": previous_chunk_id,
        "next_stop_id": next_chunk_id,
        "previous_chunk_id": previous_chunk_id,
        "next_chunk_id": next_chunk_id,
        "official_check_count": len(official_docs),
        "atlas_expand_refs": {
            "child_chunk_ids": [str(item) for item in child_chunk_ids if str(item).strip()],
            "asset_ids": [str(item.get("asset_id") or "") for item in attachments if isinstance(item, dict) and str(item.get("asset_id") or "").strip()],
            "zone_ids": [str(item.get("zone_id") or "") for item in attachments if isinstance(item, dict) and str(item.get("zone_id") or "").strip()],
        },
    }


def build_course_manifest(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[str]] = {}
    stage_parent_chunks: dict[str, list[dict[str, Any]]] = {}
    route_overrides = _load_learning_route_overrides()
    for chunk in chunks:
        if str(chunk.get("parent_chunk_id") or "").strip():
            continue
        stage_id = str(chunk.get("stage_id") or "unknown")
        grouped.setdefault(stage_id, []).append(str(chunk.get("chunk_id") or ""))
        stage_parent_chunks.setdefault(stage_id, []).append(chunk)
    def stage_review_summary(stage_id: str) -> dict[str, int]:
        rows = stage_parent_chunks.get(stage_id, [])
        approved = sum(1 for chunk in rows if str(chunk.get("review_status") or "") == "approved")
        needs_review = sum(1 for chunk in rows if str(chunk.get("review_status") or "") == "needs_review")
        return {
            "approved": approved,
            "needs_review": needs_review,
        }

    ordered_stages = [
        ("architecture", "아키텍처 설계"),
        ("unit_test", "단위 테스트"),
        ("integration_test", "통합 테스트"),
        ("perf_test", "성능 테스트"),
        ("completion", "완료"),
    ]
    stages: list[dict[str, Any]] = []
    tour_stage_records: list[dict[str, Any]] = []
    tour_stops: list[dict[str, Any]] = []
    for index, (stage_id, title) in enumerate(ordered_stages, start=1):
        if not grouped.get(stage_id):
            continue
        learning_route = _merge_learning_route(
            stage_id,
            _build_learning_route(stage_id, stage_parent_chunks.get(stage_id, [])),
            overrides=route_overrides,
        )
        ordered_stop_ids = _tour_ordered_chunk_ids(stage_id, stage_parent_chunks.get(stage_id, []), learning_route)
        stage = {
            "stage_id": stage_id,
            "order": index,
            "title": title,
            "summary_md": "",
            "chunk_refs": grouped.get(stage_id, []),
            "learning_route": learning_route,
            "tour": {
                "stop_refs": ordered_stop_ids,
                "start_stop_id": ordered_stop_ids[0] if ordered_stop_ids else "",
                "end_stop_id": ordered_stop_ids[-1] if ordered_stop_ids else "",
                "stop_count": len(ordered_stop_ids),
            },
            "review_summary": stage_review_summary(stage_id),
        }
        stages.append(stage)
        tour_stage_records.append(
            {
                "stage_id": stage_id,
                "stage_order": index,
                "title": title,
                "stop_refs": ordered_stop_ids,
                "start_stop_id": ordered_stop_ids[0] if ordered_stop_ids else "",
                "end_stop_id": ordered_stop_ids[-1] if ordered_stop_ids else "",
                "why_this_order": str(learning_route.get("why_this_order") or _stage_route_reason(stage_id)),
            }
        )
        stage_by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in stage_parent_chunks.get(stage_id, [])}
        start_ids = {str(item) for item in learning_route.get("start_here", []) if str(item).strip()}
        then_ids = {str(item) for item in learning_route.get("then_open", []) if str(item).strip()}
        for stop_index, chunk_id in enumerate(ordered_stop_ids, start=1):
            chunk = stage_by_id.get(chunk_id)
            if not isinstance(chunk, dict):
                continue
            if chunk_id in start_ids:
                route_role = "start_here"
            elif chunk_id in then_ids:
                route_role = "then_open"
            else:
                route_role = "standard"
            tour_stops.append(
                _tour_stop_record(
                    chunk=chunk,
                    stage_id=stage_id,
                    stage_order=index,
                    stage_title=title,
                    stop_order=stop_index,
                    total_stops=len(ordered_stop_ids),
                    route_role=route_role,
                    previous_chunk_id=ordered_stop_ids[stop_index - 2] if stop_index > 1 else "",
                    next_chunk_id=ordered_stop_ids[stop_index] if stop_index < len(ordered_stop_ids) else "",
                )
            )

    return {
        "canonical_model": "course_manifest_v1",
        "course_slug": "ocp-project-playbook",
        "title": "OCP 전환 프로젝트 실전 코스",
        "tour": {
            "canonical_model": "course_tour_v1",
            "entry_stage_id": stages[0]["stage_id"] if stages else "",
            "entry_stop_id": tour_stops[0]["stop_id"] if tour_stops else "",
            "stage_count": len(stages),
            "stop_count": len(tour_stops),
            "stages": tour_stage_records,
            "stops": tour_stops,
        },
        "stages": stages,
    }


def attach_course_tour_metadata(chunks: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    tour = manifest.get("tour") if isinstance(manifest.get("tour"), dict) else {}
    stops = tour.get("stops") if isinstance(tour.get("stops"), list) else []
    by_chunk_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in chunks if str(chunk.get("chunk_id") or "").strip()}
    stop_by_chunk_id = {str(stop.get("chunk_id") or ""): stop for stop in stops if isinstance(stop, dict)}
    for chunk_id, stop in stop_by_chunk_id.items():
        chunk = by_chunk_id.get(chunk_id)
        if not isinstance(chunk, dict):
            continue
        chunk["tour_stop"] = {
            "stop_id": str(stop.get("stop_id") or chunk_id),
            "stage_id": str(stop.get("stage_id") or chunk.get("stage_id") or ""),
            "stage_order": int(stop.get("stage_order") or 0),
            "stage_title": str(stop.get("stage_title") or ""),
            "stop_order": int(stop.get("stop_order") or 0),
            "total_stops": int(stop.get("total_stops") or 0),
            "route_role": str(stop.get("route_role") or "standard"),
            "previous_stop_id": str(stop.get("previous_stop_id") or ""),
            "next_stop_id": str(stop.get("next_stop_id") or ""),
            "previous_chunk_id": str(stop.get("previous_chunk_id") or ""),
            "next_chunk_id": str(stop.get("next_chunk_id") or ""),
            "official_check_count": int(stop.get("official_check_count") or 0),
            "atlas_expand_refs": stop.get("atlas_expand_refs") if isinstance(stop.get("atlas_expand_refs"), dict) else {},
        }
    return chunks


def write_course_outputs(*, output_dir: Path, manifest: dict[str, Any], chunks: list[dict[str, Any]], decks: list[dict[str, Any]]) -> None:
    manifests_dir = output_dir / "manifests"
    chunks_dir = output_dir / "chunks"
    decks_dir = output_dir / "decks"
    assets_dir = output_dir / "assets"
    if output_dir.exists():
        for child in (chunks_dir, decks_dir, assets_dir):
            if child.exists():
                shutil.rmtree(child)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    decks_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    project_root = output_dir.parent.parent.resolve()
    (manifests_dir / "course_v1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "unknown")
        semantic_zones = chunk.get("semantic_zones") if isinstance(chunk.get("semantic_zones"), list) else []
        zone_relations = chunk.get("zone_relations") if isinstance(chunk.get("zone_relations"), list) else []
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
        slide_refs_by_no = {
            int(slide_ref.get("slide_no") or 0): slide_ref
            for slide_ref in slide_refs
            if isinstance(slide_ref, dict) and int(slide_ref.get("slide_no") or 0)
        }
        single_slide_ref = next(iter(slide_refs_by_no.values()), None) if len(slide_refs_by_no) == 1 else None
        normalized_attachments: list[dict[str, Any]] = []
        for index, attachment in enumerate(attachments, start=1):
            if not isinstance(attachment, dict):
                continue
            blob = attachment.get("_blob")
            ext = str(attachment.get("ext") or "png").strip().lower() or "png"
            asset_path = ""
            if isinstance(blob, (bytes, bytearray)):
                asset_name = f"{chunk_id}__img_{index:02d}.{ext}"
                asset_file = assets_dir / asset_name
                asset_file.write_bytes(bytes(blob))
                asset_path = relative_project_path(asset_file, project_root=project_root)
            slide_no = int(attachment.get("slide_no") or attachment.get("_slide_no") or 0)
            source_ref = slide_refs_by_no.get(slide_no) or single_slide_ref
            source_pptx = str(attachment.get("source_pptx") or "")
            if not source_pptx and isinstance(source_ref, dict):
                source_pptx = str(source_ref.get("pptx") or "")
            if not source_pptx:
                source_pptx = str(chunk.get("source_pptx") or "")
            normalized_attachments.append(
                {
                    "asset_id": str(attachment.get("asset_id") or f"{chunk_id}::asset:{index:02d}"),
                    "attachment_id": str(attachment.get("attachment_id") or attachment.get("asset_id") or f"{chunk_id}::asset:{index:02d}"),
                    "source_pptx": relative_project_path(source_pptx, project_root=project_root),
                    "slide_no": slide_no,
                    "shape_index": int(attachment.get("shape_index") or 0),
                    "zone_id": str(attachment.get("zone_id") or ""),
                    "type": str(attachment.get("type") or attachment.get("kind") or "slide_image"),
                    "kind": str(attachment.get("kind") or "slide_image"),
                    "asset_path": asset_path or relative_project_path(str(attachment.get("asset_path") or ""), project_root=project_root),
                    "ext": ext,
                    "role": str(attachment.get("role") or ""),
                    "bbox_norm": attachment.get("bbox_norm") if isinstance(attachment.get("bbox_norm"), list) else [],
                    "caption_text": str(attachment.get("caption_text") or ""),
                    "visual_summary": str(attachment.get("visual_summary") or ""),
                    "ocr_text": str(attachment.get("ocr_text") or ""),
                    "searchable": bool(attachment.get("searchable", False)),
                    "confidence": float(attachment.get("confidence") or 0.0),
                    "quality_label": str(attachment.get("quality_label") or ""),
                    "instructional_role": str(attachment.get("instructional_role") or ""),
                    "instructional_roles": attachment.get("instructional_roles") if isinstance(attachment.get("instructional_roles"), list) else [],
                    "state_signal": str(attachment.get("state_signal") or ""),
                    "evidence_strength": float(attachment.get("evidence_strength") or 0.0),
                    "rank_profiles": attachment.get("rank_profiles") if isinstance(attachment.get("rank_profiles"), dict) else {},
                    "dedupe_group_id": str(attachment.get("dedupe_group_id") or ""),
                    "duplicate_of_asset_id": str(attachment.get("duplicate_of_asset_id") or ""),
                    "sha256": str(attachment.get("sha256") or ""),
                    "exclude_from_default": bool(attachment.get("exclude_from_default", False)),
                    "is_default_visible": bool(attachment.get("is_default_visible", True)),
                    "default_visible_order": int(attachment.get("default_visible_order") or 0),
                    "image_rank_order": int(attachment.get("image_rank_order") or 0),
                }
            )
        normalized_slide_refs: list[dict[str, Any]] = []
        for slide_ref in slide_refs:
            if not isinstance(slide_ref, dict):
                continue
            normalized_slide_refs.append(
                {
                    **slide_ref,
                    "pptx": relative_project_path(str(slide_ref.get("pptx") or ""), project_root=project_root),
                    "png_path": relative_project_path(str(slide_ref.get("png_path") or ""), project_root=project_root),
                }
            )
        provenance = chunk.get("provenance") if isinstance(chunk.get("provenance"), dict) else {}
        chunk = {
            **chunk,
            "schema_version": str(chunk.get("schema_version") or "ppt_chunk_v1"),
            "source_kind": str(chunk.get("source_kind") or "project_artifact"),
            "image_attachments": normalized_attachments,
            "slide_refs": normalized_slide_refs,
            "source_pptx": relative_project_path(str(chunk.get("source_pptx") or ""), project_root=project_root),
            "provenance": {
                **provenance,
                "semantic_zone_count": len(semantic_zones),
                "zone_relation_count": len(zone_relations),
            },
        }
        chunk.pop("semantic_zones", None)
        chunk.pop("zone_relations", None)
        (chunks_dir / f"{chunk_id}.json").write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")
    normalized_decks = []
    for deck in decks:
        if not isinstance(deck, dict):
            continue
        normalized_decks.append(
            {
                **deck,
                "source_pptx": relative_project_path(str(deck.get("source_pptx") or ""), project_root=project_root),
            }
        )
    (decks_dir / "spike_decks.json").write_text(json.dumps(normalized_decks, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["attach_course_tour_metadata", "build_course_manifest", "write_course_outputs"]
