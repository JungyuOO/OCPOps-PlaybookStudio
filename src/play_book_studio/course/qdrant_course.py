from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
import uuid
import re

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.embedding import EmbeddingClient
COURSE_QDRANT_COLLECTION = "course_pbs_ko"
COURSE_OPS_LEARNING_QDRANT_COLLECTION = "course_ops_learning_ko"


def load_course_chunks(course_dir: Path) -> list[dict[str, Any]]:
    chunks_dir = course_dir / "chunks"
    if not chunks_dir.exists():
        raise FileNotFoundError(f"course chunks directory not found: {chunks_dir}")
    chunks: list[dict[str, Any]] = []
    for path in sorted(chunks_dir.glob("*.json")):
        chunk = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "").strip():
            chunks.append(chunk)
    return chunks


def _ensure_collection(settings: Settings, collection: str) -> None:
    url = f"{settings.qdrant_url}/collections/{collection}"
    response = requests.get(url, timeout=settings.request_timeout_seconds)
    if response.status_code == 200:
        return
    create = requests.put(
        url,
        json={
            "vectors": {
                "size": settings.qdrant_vector_size,
                "distance": settings.qdrant_distance,
            }
        },
        timeout=settings.request_timeout_seconds,
    )
    create.raise_for_status()


def ensure_course_collection(settings: Settings) -> None:
    _ensure_collection(settings, COURSE_QDRANT_COLLECTION)


def ensure_ops_learning_collection(settings: Settings) -> None:
    _ensure_collection(settings, COURSE_OPS_LEARNING_QDRANT_COLLECTION)


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


def course_point_payload(chunk: dict[str, Any]) -> dict[str, Any]:
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
    if not path.exists():
        return []
    chunks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict) and str(payload.get("learning_chunk_id") or "").strip():
            chunks.append(payload)
    return chunks


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


def ops_learning_point_payload(chunk: dict[str, Any]) -> dict[str, Any]:
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


def _upsert_points(settings: Settings, collection: str, points: list[dict[str, Any]]) -> None:
    response = requests.put(
        f"{settings.qdrant_url}/collections/{collection}/points?wait=true",
        json={"points": points},
        timeout=max(settings.request_timeout_seconds, 120),
    )
    response.raise_for_status()


def upsert_course_chunks(settings: Settings, chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    ensure_course_collection(settings)
    embedding_client = EmbeddingClient(settings)
    upserted = 0
    batch_size = max(1, int(settings.qdrant_upsert_batch_size or 128))
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embedding_client.embed_texts([course_embedding_text(chunk) for chunk in batch])
        points = [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"course:{chunk.get('chunk_id') or ''}")),
                "vector": vector,
                "payload": course_point_payload(chunk),
            }
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        _upsert_points(settings, COURSE_QDRANT_COLLECTION, points)
        upserted += len(points)
    return upserted


def upsert_ops_learning_chunks(settings: Settings, chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    ensure_ops_learning_collection(settings)
    embedding_client = EmbeddingClient(settings)
    upserted = 0
    batch_size = max(1, int(settings.qdrant_upsert_batch_size or 128))
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embedding_client.embed_texts([ops_learning_embedding_text(chunk) for chunk in batch])
        points = [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"course-ops-learning:{chunk.get('learning_chunk_id') or chunk.get('step_id') or ''}")),
                "vector": vector,
                "payload": ops_learning_point_payload(chunk),
            }
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        _upsert_points(settings, COURSE_OPS_LEARNING_QDRANT_COLLECTION, points)
        upserted += len(points)
    return upserted


def _query_collection(
    settings: Settings,
    *,
    collection: str,
    query: str,
    top_k: int,
    source: str,
    vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    if vector is None:
        embedding_client = EmbeddingClient(settings)
        vector = embedding_client.embed_texts([query])[0]
    candidate_limit = max(top_k, min(50, top_k * 10))
    response = requests.post(
        f"{settings.qdrant_url}/collections/{collection}/points/query",
        json={
            "query": vector,
            "limit": candidate_limit,
            "with_payload": True,
            "with_vector": False,
        },
        timeout=max(settings.request_timeout_seconds, 20),
    )
    response.raise_for_status()
    result = response.json().get("result") or {}
    points = result.get("points") if isinstance(result, dict) else result
    hits: list[dict[str, Any]] = []
    query_tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}|[가-힣]{2,}", query)}
    normalized_query = " ".join(str(query or "").lower().split())
    for point in points or []:
        payload = point.get("payload") if isinstance(point, dict) else None
        if not isinstance(payload, dict):
            continue
        text = str(payload.get("text") or "").lower()
        lexical_hits = sum(1 for token in query_tokens if token in text)
        exact_bonus = 3 if normalized_query and normalized_query in text else 0
        vector_score = float(point.get("score", 0.0))
        adjusted_score = vector_score + ((lexical_hits + exact_bonus) * 0.08)
        hits.append(
            {
                "chunk_id": str(payload.get("chunk_id") or ""),
                "book_slug": str(payload.get("book_slug") or ""),
                "section_id": str(payload.get("section_id") or ""),
                "section": str(payload.get("section") or ""),
                "text": str(payload.get("text") or ""),
                "source": source,
                "score": adjusted_score,
                "vector_score": vector_score,
                "lexical_hits": lexical_hits,
                "payload": payload,
            }
        )
    hits.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("chunk_id") or "")))
    return hits[:top_k]


def search_course_and_official(settings: Settings, *, query: str, top_k_course: int = 5, top_k_official: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    embedding_client = EmbeddingClient(settings)
    vector = embedding_client.embed_texts([query])[0]
    course_hits = _query_collection(
        settings,
        collection=COURSE_QDRANT_COLLECTION,
        query=query,
        top_k=top_k_course,
        source="course_vector",
        vector=vector,
    )
    official_hits = _query_collection(
        settings,
        collection=settings.qdrant_collection,
        query=query,
        top_k=top_k_official,
        source="official_vector",
        vector=vector,
    )
    return course_hits, official_hits


def search_ops_learning_chunks(settings: Settings, *, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    return _query_collection(
        settings,
        collection=COURSE_OPS_LEARNING_QDRANT_COLLECTION,
        query=query,
        top_k=top_k,
        source="ops_learning_vector",
    )


__all__ = [
    "COURSE_QDRANT_COLLECTION",
    "COURSE_OPS_LEARNING_QDRANT_COLLECTION",
    "course_embedding_text",
    "course_point_payload",
    "ensure_course_collection",
    "ensure_ops_learning_collection",
    "load_course_chunks",
    "load_ops_learning_chunks",
    "ops_learning_embedding_text",
    "ops_learning_point_payload",
    "search_course_and_official",
    "search_ops_learning_chunks",
    "upsert_course_chunks",
    "upsert_ops_learning_chunks",
]
