# Qdrant 기반 의미 검색을 담당하는 최소 vector retriever다.
# hybrid retrieval에서는 이 모듈이 semantic 후보만 준비하고, 최종 결합은 retriever가 맡는다.
from __future__ import annotations

from typing import Any

import requests

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.embedding import EmbeddingClient

from .models import RetrievalHit


def hit_from_payload(payload: dict[str, Any], *, source: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=str(payload["chunk_id"]),
        book_slug=str(payload["book_slug"]),
        chapter=str(payload.get("chapter", "")),
        section=str(payload.get("section", "")),
        section_id=str(payload.get("section_id", "")),
        anchor=str(payload.get("anchor", "")),
        source_url=str(payload.get("source_url", "")),
        viewer_path=str(payload.get("viewer_path", "")),
        text=str(payload.get("text", "")),
        source=source,
        raw_score=float(score),
        fused_score=float(score),
        section_path=tuple(str(item) for item in (payload.get("section_path") or []) if str(item).strip()),
        chunk_type=str(payload.get("chunk_type", "reference")),
        source_id=str(payload.get("source_id", "")),
        source_lane=str(payload.get("source_lane", "official_ko")),
        source_type=str(payload.get("source_type", "official_doc")),
        source_collection=str(payload.get("source_collection", "core")),
        review_status=str(payload.get("review_status", "unreviewed")),
        trust_score=float(payload.get("trust_score", 1.0) or 1.0),
        parsed_artifact_id=str(payload.get("parsed_artifact_id", "")),
        semantic_role=str(payload.get("semantic_role", "unknown")),
        block_kinds=tuple(str(item) for item in (payload.get("block_kinds") or []) if str(item).strip()),
        cli_commands=tuple(str(item) for item in (payload.get("cli_commands") or []) if str(item).strip()),
        error_strings=tuple(str(item) for item in (payload.get("error_strings") or []) if str(item).strip()),
        k8s_objects=tuple(str(item) for item in (payload.get("k8s_objects") or []) if str(item).strip()),
        operator_names=tuple(str(item) for item in (payload.get("operator_names") or []) if str(item).strip()),
        verification_hints=tuple(
            str(item) for item in (payload.get("verification_hints") or []) if str(item).strip()
        ),
    )


class VectorRetriever:
    """hybrid retrieval의 한 신호로 쓰이는 최소 Qdrant vector retriever."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedding_client = EmbeddingClient(settings)
        self.request_timeout_seconds = max(float(self.settings.request_timeout_seconds), 1.0)

    def search(self, query: str, top_k: int) -> list[RetrievalHit]:
        hits, _runtime = self.search_with_trace(query, top_k)
        return hits

    def search_with_trace(self, query: str, top_k: int) -> tuple[list[RetrievalHit], dict[str, Any]]:
        vector = self.embedding_client.embed_texts([query])[0]
        payloads = [
            (
                f"{self.settings.qdrant_url}/collections/{self.settings.qdrant_collection}/points/search",
                {
                    "vector": vector,
                    "limit": top_k,
                    "with_payload": True,
                    "with_vector": False,
                },
            ),
            (
                f"{self.settings.qdrant_url}/collections/{self.settings.qdrant_collection}/points/query",
                {
                    "query": vector,
                    "limit": top_k,
                    "with_payload": True,
                    "with_vector": False,
                },
            ),
        ]

        last_error = "vector search failed"
        attempted_endpoints: list[str] = []
        errors: list[dict[str, str]] = []
        for url, payload in payloads:
            endpoint_name = url.rsplit("/", maxsplit=1)[-1]
            attempted_endpoints.append(endpoint_name)
            response = requests.post(
                url,
                json=payload,
                timeout=self.request_timeout_seconds,
            )
            if not response.ok:
                last_error = response.text[:500]
                errors.append({"endpoint": endpoint_name, "error": last_error})
                continue
            result = response.json()["result"]
            points = result["points"] if isinstance(result, dict) and "points" in result else result
            hits: list[RetrievalHit] = []
            for point in points:
                payload_row = point.get("payload") or {}
                if not payload_row:
                    continue
                hits.append(
                    hit_from_payload(
                        payload_row,
                        source="vector",
                        score=float(point.get("score", 0.0)),
                    )
                )
            return (
                hits,
                {
                    "endpoint_used": endpoint_name,
                    "attempted_endpoints": attempted_endpoints,
                    "errors": errors,
                    "hit_count": len(hits),
                    "top_score": float(points[0].get("score", 0.0)) if points else None,
                },
            )

        raise ValueError(last_error)
