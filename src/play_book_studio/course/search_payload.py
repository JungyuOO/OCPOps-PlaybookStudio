from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from play_book_studio.ingestion.kmsc_beginner_narrative import derive_ops_learning_chunks

from .chunk_loader import load_course_chunks


def _attachment_index_text(chunk: dict[str, Any]) -> str:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    rows: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        parts = [
            str(attachment.get("instructional_role") or ""),
            " ".join(str(item) for item in attachment.get("instructional_roles", []) if str(item).strip())
            if isinstance(attachment.get("instructional_roles"), list)
            else "",
            str(attachment.get("state_signal") or ""),
            str(attachment.get("quality_label") or ""),
            str(attachment.get("visual_summary") or ""),
            str(attachment.get("caption_text") or ""),
            str(attachment.get("ocr_text") or ""),
        ]
        text = " ".join(part.strip() for part in parts if part.strip())
        if text:
            rows.append(text)
    return "\n".join(dict.fromkeys(rows))


def course_embedding_text(chunk: dict[str, Any]) -> str:
    index_texts = chunk.get("index_texts") if isinstance(chunk.get("index_texts"), dict) else {}
    dense_text = str(index_texts.get("dense_text") or chunk.get("search_text") or chunk.get("body_md") or chunk.get("title") or "")
    sparse_text = str(index_texts.get("sparse_text") or "")
    visual_text = str(index_texts.get("visual_text") or chunk.get("visual_text") or "")
    attachment_text = _attachment_index_text(chunk)
    return "\n".join(part for part in [dense_text, sparse_text, visual_text, attachment_text] if part)


def course_search_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    first_slide = slide_refs[0] if slide_refs else {}
    stage_id = str(chunk.get("stage_id") or "")
    index_texts = chunk.get("index_texts") if isinstance(chunk.get("index_texts"), dict) else {}
    dense_text = str(index_texts.get("dense_text") or chunk.get("search_text") or chunk.get("body_md") or "")
    sparse_text = str(index_texts.get("sparse_text") or "")
    visual_text = str(index_texts.get("visual_text") or chunk.get("visual_text") or "")
    attachment_text = _attachment_index_text(chunk)
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "bundle_id": str(chunk.get("bundle_id") or ""),
        "root_chunk_id": str(chunk.get("root_chunk_id") or ""),
        "source_kind": str(chunk.get("source_kind") or "project_artifact"),
        "book_slug": stage_id or "course",
        "chapter": stage_id,
        "section": str(chunk.get("title") or ""),
        "section_id": str(chunk.get("native_id") or ""),
        "anchor": str(chunk.get("native_id") or ""),
        "source_url": str(chunk.get("source_pptx") or ""),
        "viewer_path": f"/course/chunks/{chunk.get('chunk_id') or ''}",
        "text": "\n".join(part for part in [dense_text, sparse_text, visual_text, attachment_text] if part),
        "dense_text": dense_text,
        "sparse_text": sparse_text,
        "visual_text": visual_text,
        "image_text": attachment_text,
        "chunk_type": "course_chunk",
        "source_id": str(chunk.get("chunk_id") or ""),
        "source_lane": "course",
        "source_type": "project_artifact",
        "source_collection": "course_pbs",
        "review_status": str(chunk.get("review_status") or "unreviewed"),
        "trust_score": 0.95,
        "parsed_artifact_id": str(chunk.get("chunk_id") or ""),
        "semantic_role": stage_id or "course",
        "block_kinds": ["course_chunk"],
        "verification_hints": [str(chunk.get("native_id") or "")],
        "section_path": [stage_id, str(chunk.get("title") or "")],
        "slide_no": int(first_slide.get("slide_no") or 0),
    }


def load_ops_learning_chunks(course_dir: Path) -> list[dict[str, Any]]:
    path = course_dir / "manifests" / "ops_learning_chunks_v1.jsonl"
    course_chunks = load_course_chunks(course_dir)
    if not path.exists():
        return derive_ops_learning_chunks(course_chunks, existing_learning_chunks=[])
    chunks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict) and str(payload.get("learning_chunk_id") or "").strip():
            chunks.append(payload)
    return derive_ops_learning_chunks(course_chunks, existing_learning_chunks=chunks)


def ops_learning_embedding_text(chunk: dict[str, Any]) -> str:
    explicit = str(chunk.get("embedding_text") or "").strip()
    if explicit:
        return explicit
    rows: list[str] = []
    for key in (
        "title",
        "learning_goal",
        "beginner_explanation",
        "source_summary",
        "official_mapping_summary",
    ):
        value = str(chunk.get(key) or "").strip()
        if value:
            rows.append(value)
    for key in (
        "operational_sequence",
        "what_to_look_for",
        "normal_state",
        "failure_state",
        "visual_evidence_roles",
        "query_variants",
        "source_titles",
        "source_terms",
        "image_evidence_texts",
    ):
        value = chunk.get(key)
        if isinstance(value, list):
            rows.extend(str(item).strip() for item in value if str(item).strip())
    return "\n".join(dict.fromkeys(rows))


def ops_learning_search_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    learning_chunk_id = str(chunk.get("learning_chunk_id") or chunk.get("step_id") or "")
    stage_id = str(chunk.get("stage_id") or "")
    source_chunk_ids = [str(item) for item in chunk.get("source_chunk_ids", []) if str(item).strip()] if isinstance(chunk.get("source_chunk_ids"), list) else []
    return {
        "chunk_id": learning_chunk_id,
        "learning_chunk_id": learning_chunk_id,
        "chunk_type": str(chunk.get("chunk_type") or "ops_learning_step"),
        "guide_id": str(chunk.get("guide_id") or ""),
        "step_id": str(chunk.get("step_id") or ""),
        "stage_id": stage_id,
        "book_slug": stage_id or "course",
        "chapter": stage_id,
        "section": str(chunk.get("title") or ""),
        "section_id": str(chunk.get("step_id") or ""),
        "anchor": str(chunk.get("step_id") or ""),
        "viewer_path": f"/course/chunks/{source_chunk_ids[0]}" if source_chunk_ids else "",
        "text": ops_learning_embedding_text(chunk),
        "source_chunk_ids": source_chunk_ids,
        "hidden_native_ids": [str(item) for item in chunk.get("hidden_native_ids", []) if str(item).strip()] if isinstance(chunk.get("hidden_native_ids"), list) else [],
        "official_ref_ids": [str(item) for item in chunk.get("official_ref_ids", []) if str(item).strip()] if isinstance(chunk.get("official_ref_ids"), list) else [],
        "next_step_ids": [str(item) for item in chunk.get("next_step_ids", []) if str(item).strip()] if isinstance(chunk.get("next_step_ids"), list) else [],
        "query_variants": [str(item) for item in chunk.get("query_variants", []) if str(item).strip()] if isinstance(chunk.get("query_variants"), list) else [],
        "visual_evidence_roles": [str(item) for item in chunk.get("visual_evidence_roles", []) if str(item).strip()] if isinstance(chunk.get("visual_evidence_roles"), list) else [],
        "source_lane": "course_ops_learning",
        "source_type": "project_artifact",
        "source_collection": "course_ops_learning",
        "trust_score": 0.96,
        "semantic_role": "ops_learning_step",
        "block_kinds": ["ops_learning_step"],
        "section_path": [stage_id, str(chunk.get("title") or "")],
    }


__all__ = [
    "course_embedding_text",
    "course_search_payload",
    "load_ops_learning_chunks",
    "ops_learning_embedding_text",
    "ops_learning_search_payload",
]
