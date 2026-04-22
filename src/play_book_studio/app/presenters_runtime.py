from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.ingestion.graph_sidecar import graph_sidecar_compact_artifact_status


def _llm_runtime_signature(settings: Settings) -> tuple[Any, ...]:
    return (
        settings.ocp_version,
        settings.docs_language,
        settings.llm_endpoint,
        settings.llm_model,
        settings.llm_api_key,
        settings.llm_temperature,
        settings.llm_max_tokens,
        settings.embedding_base_url,
        settings.embedding_model,
        settings.embedding_device,
        settings.embedding_api_key,
        settings.embedding_batch_size,
        settings.embedding_timeout_seconds,
        settings.reranker_enabled,
        settings.reranker_model,
        settings.reranker_top_n,
        settings.reranker_batch_size,
        settings.reranker_device,
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.qdrant_vector_size,
        settings.qdrant_distance,
        settings.request_timeout_seconds,
        str(settings.artifacts_dir),
        str(settings.source_manifest_path),
        str(settings.retrieval_normalized_docs_path),
        str(settings.retrieval_chunks_path),
        str(settings.retrieval_bm25_corpus_path),
        str(settings.customer_pack_books_dir),
        settings.request_timeout_seconds,
    )


def _runtime_fingerprint(settings: Settings) -> str:
    raw = "|".join(str(item) for item in _llm_runtime_signature(settings))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _refresh_answerer_llm_settings(
    answerer: ChatAnswerer,
    *,
    root_dir: Path,
    current_signature: tuple[Any, ...] | None,
) -> tuple[ChatAnswerer, tuple[Any, ...]]:
    settings = load_settings(root_dir)
    signature = _llm_runtime_signature(settings)
    if signature == current_signature:
        return answerer, signature
    factory = getattr(answerer.__class__, "from_settings", None)
    if callable(factory):
        return factory(settings), signature
    answerer.settings = settings
    if hasattr(answerer, "llm_client") and hasattr(answerer.llm_client.__class__, "__call__"):
        answerer.llm_client = answerer.llm_client.__class__(settings)
    return answerer, signature


def _build_health_payload(answerer: ChatAnswerer) -> dict[str, Any]:
    settings = answerer.settings
    pack = settings.active_pack
    embedding_mode = "remote" if settings.embedding_base_url else "local"
    compact_graph_artifact = graph_sidecar_compact_artifact_status(settings)
    llm_runtime = (
        answerer.llm_client.runtime_metadata()
        if hasattr(answerer.llm_client, "runtime_metadata")
        else {}
    )
    return {
        "ok": True,
        "runtime": {
            "app_id": settings.app_id,
            "app_label": settings.app_label,
            "config_fingerprint": _runtime_fingerprint(settings),
            "runtime_refresh_strategy": "rebuild_answerer_on_signature_change",
            "ocp_version": settings.ocp_version,
            "docs_language": settings.docs_language,
            "active_pack_id": pack.pack_id,
            "active_pack_label": pack.pack_label,
            "active_pack_product": pack.product_label,
            "viewer_path_prefix": pack.viewer_path_prefix,
            "llm_endpoint": settings.llm_endpoint,
            "llm_model": settings.llm_model,
            "llm_provider_hint": llm_runtime.get("preferred_provider", "unknown"),
            "llm_fallback_enabled": bool(llm_runtime.get("fallback_enabled", False)),
            "llm_last_provider": llm_runtime.get("last_provider"),
            "llm_last_fallback_used": bool(llm_runtime.get("last_fallback_used", False)),
            "llm_attempted_providers": list(llm_runtime.get("last_attempted_providers", [])),
            "embedding_mode": embedding_mode,
            "embedding_base_url": settings.embedding_base_url,
            "embedding_model": settings.embedding_model,
            "embedding_device": settings.embedding_device,
            "reranker_enabled": bool(settings.reranker_enabled),
            "reranker_model": settings.reranker_model,
            "reranker_top_n": settings.reranker_top_n,
            "reranker_batch_size": settings.reranker_batch_size,
            "reranker_device": settings.reranker_device,
            "qdrant_url": settings.qdrant_url,
            "qdrant_collection": settings.qdrant_collection,
            "graph_backend": settings.graph_backend,
            "graph_runtime_mode": settings.graph_runtime_mode,
            "graph_compact_artifact": compact_graph_artifact,
            "artifacts_dir": str(settings.artifacts_dir),
            "source_manifest_path": str(settings.source_manifest_path),
            "normalized_docs_path": str(settings.retrieval_normalized_docs_path),
            "bm25_corpus_path": str(settings.retrieval_bm25_corpus_path),
            "customer_pack_books_dir": str(settings.customer_pack_books_dir),
        },
    }


__all__ = [
    "_build_health_payload",
    "_llm_runtime_signature",
    "_refresh_answerer_llm_settings",
    "_runtime_fingerprint",
]
