# pgvector 기반 의미 검색을 담당하는 최소 vector retriever다.
# hybrid retrieval에서는 이 모듈이 semantic 후보만 준비하고, 최종 결합은 retriever가 맡는다.
from __future__ import annotations

import time
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.embedding import EmbeddingClient
from play_book_studio.retrieval.payload import retrieval_payload_from_row, vector_literal

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
        section_number=str(payload.get("section_number", "")),
        heading_title=str(payload.get("heading_title", "")),
        source_anchor=str(payload.get("source_anchor", "")),
        toc_path=tuple(str(item) for item in (payload.get("toc_path") or []) if str(item).strip()),
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
        asset_ids=tuple(str(item) for item in (payload.get("asset_ids") or []) if str(item).strip()),
        chunk_role=str(payload.get("chunk_role", "leaf") or "leaf"),
        parent_chunk_id=str(payload.get("parent_chunk_id", "")),
        child_chunk_ids=tuple(str(item) for item in (payload.get("child_chunk_ids") or []) if str(item).strip()),
        navigation_only=bool(payload.get("navigation_only") or False),
        beginner_narrative=str(payload.get("beginner_narrative", "")),
        starter_question_candidates=tuple(
            str(item) for item in (payload.get("starter_question_candidates") or []) if str(item).strip()
        ),
        followup_question_candidates=tuple(
            str(item) for item in (payload.get("followup_question_candidates") or []) if str(item).strip()
        ),
        question_candidates_version=int(payload.get("question_candidates_version") or 0),
        repository_id=str(payload.get("repository_id", "")),
        document_source_id=str(payload.get("document_source_id", "") or payload.get("source_id", "")),
        owner_user_id=str(payload.get("owner_user_id", "")),
        visibility=str(payload.get("visibility", "")),
        source_scope=str(payload.get("source_scope", "")),
        learning=payload.get("learning") if isinstance(payload.get("learning"), dict) else {},
    )


class VectorRetriever:
    """hybrid retrieval의 한 신호로 쓰이는 PostgreSQL pgvector retriever."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedding_client = EmbeddingClient(settings)
        self.request_timeout_seconds = max(float(self.settings.request_timeout_seconds), 1.0)
        self.database_url = settings.database_url.strip()

    def search(
        self,
        query: str,
        top_k: int,
        *,
        query_filter: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        hits, _runtime = self.search_with_trace(query, top_k, query_filter=query_filter)
        return hits

    def search_with_trace(
        self,
        query: str,
        top_k: int,
        *,
        query_filter: dict[str, Any] | None = None,
    ) -> tuple[list[RetrievalHit], dict[str, Any]]:
        embedding_started_at = time.perf_counter()
        vector = self.embedding_client.embed_texts([query])[0]
        embedding_ms = round((time.perf_counter() - embedding_started_at) * 1000, 1)
        if not self.database_url:
            raise RuntimeError("database_url is required for pgvector search")
        import psycopg

        vector_started_at = time.perf_counter()
        with psycopg.connect(self.database_url) as connection:
            hits, filter_runtime = self._search_pgvector(
                connection,
                vector=vector,
                top_k=top_k,
                query_filter=query_filter,
            )
        vector_db_ms = round((time.perf_counter() - vector_started_at) * 1000, 1)
        return (
            hits,
            {
                "backend": "pgvector",
                "endpoint_used": "postgres",
                "attempted_endpoints": ["postgres"],
                "errors": [],
                "hit_count": len(hits),
                "top_score": hits[0].raw_score if hits else None,
                "hydration": {"status": "not_required", "requested_count": len(hits), "hydrated_count": 0},
                "embedding_ms": embedding_ms,
                "vector_db_ms": vector_db_ms,
                "pgvector_ms": vector_db_ms,
                "hydrate_ms": 0.0,
                "request_timeout_seconds": self.request_timeout_seconds,
                "metadata_filter_applied": bool(query_filter),
                "metadata_filter": query_filter or {},
                **filter_runtime,
            },
        )

    def _search_pgvector(
        self,
        connection,
        *,
        vector: list[float],
        top_k: int,
        query_filter: dict[str, Any] | None,
    ) -> tuple[list[RetrievalHit], dict[str, Any]]:
        filter_sql, filter_params, filter_runtime = _pgvector_filter_sql(query_filter)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    c.id::text AS chunk_id,
                    c.chunk_key,
                    c.ordinal,
                    c.chunk_type,
                    c.markdown,
                    c.embedding_text,
                    c.section_path,
                    c.section_number,
                    c.heading_title,
                    c.source_anchor,
                    c.toc_path,
                    c.asset_ids,
                    c.repository_id::text AS repository_id,
                    c.owner_user_id,
                    c.visibility,
                    c.source_scope,
                    c.chunk_role,
                    c.parent_chunk_id::text AS parent_chunk_id,
                    c.child_chunk_ids,
                    c.navigation_only,
                    c.beginner_narrative,
                    c.starter_question_candidates,
                    c.followup_question_candidates,
                    c.question_candidates_version,
                    c.metadata AS chunk_metadata,
                    pd.id::text AS parsed_document_id,
                    pd.title AS document_title,
                    pd.metadata AS parsed_metadata,
                    ds.id::text AS document_source_id,
                    ds.filename,
                    ds.storage_key,
                    ds.source_kind,
                    ds.metadata AS source_metadata,
                    ds.created_by,
                    (ce.embedding <=> %s::vector) AS vector_distance
                FROM chunk_embeddings ce
                JOIN document_chunks c ON c.id = ce.chunk_id
                JOIN parsed_documents pd ON pd.id = c.parsed_document_id
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE ce.model = %s
                  AND length(btrim(COALESCE(c.embedding_text, ''))) > 0
                  AND ce.embedding_text_hash = encode(digest(c.embedding_text, 'sha256'), 'hex')
                  {filter_sql}
                ORDER BY ce.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    vector_literal(vector),
                    self.settings.embedding_model,
                    *filter_params,
                    vector_literal(vector),
                    int(top_k),
                ),
            )
            rows = cursor.fetchall()
            columns = _cursor_column_names(cursor)
        hits: list[RetrievalHit] = []
        for row in rows:
            row_dict = dict(zip(columns, row, strict=True))
            distance = float(row_dict.get("vector_distance") or 0.0)
            hits.append(
                hit_from_payload(
                    retrieval_payload_from_row(row_dict),
                    source="vector",
                    score=1.0 - distance,
                )
            )
        return hits, filter_runtime

    def _hydrate_hits_from_database(self, hits: list[RetrievalHit]) -> tuple[list[RetrievalHit], dict[str, Any]]:
        hydration: dict[str, Any] = {
            "status": "disabled",
            "requested_count": len(hits),
            "hydrated_count": 0,
        }
        if not hits or not self.database_url:
            return hits, hydration
        import psycopg

        from play_book_studio.retrieval.chunk_hydration import hydrate_retrieval_hits

        with psycopg.connect(self.database_url) as connection:
            hydrated = hydrate_retrieval_hits(connection, hits)
        hydration["status"] = "ready"
        hydration["hydrated_count"] = sum(
            1 for original, canonical in zip(hits, hydrated, strict=True) if original is not canonical
        )
        return hydrated, hydration


def _pgvector_filter_sql(query_filter: dict[str, Any] | None) -> tuple[str, list[Any], dict[str, Any]]:
    if not query_filter:
        return "", [], {"sql_filter_applied": False, "sql_filter_keys": []}
    clauses: list[str] = []
    params: list[Any] = []
    keys: list[str] = []
    unsupported = 0

    def add_condition(item: Any) -> str | None:
        nonlocal unsupported
        if not isinstance(item, dict):
            unsupported += 1
            return None
        key = str(item.get("key") or "").strip()
        match = item.get("match") if isinstance(item.get("match"), dict) else {}
        value = match.get("value") if isinstance(match, dict) else None
        if value is None:
            unsupported += 1
            return None
        if key == "source_scope":
            params.append(str(value))
            keys.append(key)
            return "c.source_scope = %s"
        if key == "document_source_id":
            params.append(str(value))
            keys.append(key)
            return "ds.id = %s::uuid"
        if key == "repository_id":
            params.append(str(value))
            keys.append(key)
            return "c.repository_id = %s::uuid"
        if key == "owner_user_id":
            params.append(str(value))
            keys.append(key)
            return "c.owner_user_id = %s"
        if key == "visibility":
            params.append(str(value))
            keys.append(key)
            return "c.visibility = %s"
        if key == "source.enabled_for_chat":
            params.append("true" if bool(value) else "false")
            keys.append(key)
            return "COALESCE(NULLIF(c.metadata->>'enabled_for_chat', ''), 'true') = %s"
        if key == "classification.domain":
            params.append(str(value))
            keys.append(key)
            return "COALESCE(c.metadata->'classification'->>'domain', c.metadata->>'domain', ds.metadata->>'domain', '') = %s"
        unsupported += 1
        return None

    for item in query_filter.get("must") or []:
        condition = add_condition(item)
        if condition:
            clauses.append(condition)
    should_conditions: list[str] = []
    for item in query_filter.get("should") or []:
        condition = add_condition(item)
        if condition:
            should_conditions.append(condition)
    if should_conditions:
        clauses.append("(" + " OR ".join(should_conditions) + ")")
    if not clauses:
        return "", [], {"sql_filter_applied": False, "sql_filter_keys": [], "sql_filter_unsupported": unsupported}
    return (
        " AND " + " AND ".join(clauses),
        params,
        {"sql_filter_applied": True, "sql_filter_keys": keys, "sql_filter_unsupported": unsupported},
    )


def _cursor_column_names(cursor) -> list[str]:
    names: list[str] = []
    for item in cursor.description:
        name = getattr(item, "name", None)
        names.append(str(name if name is not None else item[0]))
    return names
