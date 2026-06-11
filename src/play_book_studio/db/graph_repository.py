from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

_LATEST_PARSED_DOCUMENT_GUARD = """
  AND (
      c.source_scope <> 'user_upload'
      OR pd.id = (
          SELECT latest_pd.id
          FROM parsed_documents latest_pd
          WHERE latest_pd.document_source_id = pd.document_source_id
          ORDER BY latest_pd.created_at DESC, latest_pd.id DESC
          LIMIT 1
      )
  )
"""


@dataclass(frozen=True, slots=True)
class GraphScopeFilter:
    owner_user_id: str = ""
    enabled_source_scopes: tuple[str, ...] = field(default_factory=tuple)


def quote_sha256(quote: str) -> str:
    return hashlib.sha256((quote or "").encode("utf-8")).hexdigest()


def _scope_clause(scope: GraphScopeFilter, *, alias: str) -> tuple[str, list[Any]]:
    clauses = [f"({alias}.visibility <> 'private_user' OR {alias}.owner_user_id = %s)"]
    params: list[Any] = [scope.owner_user_id]
    if scope.enabled_source_scopes:
        clauses.append(f"{alias}.source_scope = ANY(%s)")
        params.append(list(scope.enabled_source_scopes))
    return " AND " + " AND ".join(clauses), params


def _rows_as_dicts(cursor) -> list[dict[str, Any]]:
    columns = [column.name for column in cursor.description or []]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def upsert_entity(
    cursor,
    *,
    entity_kind: str,
    name: str,
    display_name: str = "",
    label: str = "",
    source_scope: str,
    owner_user_id: str = "",
) -> str:
    entity_key = f"{entity_kind}:{name}"
    aliases = json.dumps([label] if label else [])
    cursor.execute(
        """
        INSERT INTO graph_entities (
            entity_kind, name, display_name, entity_key, aliases, source_scope, owner_user_id
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (entity_key, source_scope, owner_user_id)
        DO UPDATE SET
            updated_at = now(),
            display_name = CASE
                WHEN graph_entities.display_name = '' THEN EXCLUDED.display_name
                ELSE graph_entities.display_name
            END,
            aliases = COALESCE(
                (
                    SELECT jsonb_agg(DISTINCT elem)
                    FROM jsonb_array_elements_text(graph_entities.aliases || EXCLUDED.aliases) AS t(elem)
                ),
                '[]'::jsonb
            )
        RETURNING id::text
        """,
        (entity_kind, name, display_name, entity_key, aliases, source_scope, owner_user_id),
    )
    row = cursor.fetchone()
    return str(row[0])


def insert_mention(
    cursor,
    *,
    entity_id: str,
    source_kind: str = "chunk",
    chunk_id: str | None = None,
    source_ref: str = "",
    document_source_id: str | None = None,
    parsed_document_id: str | None = None,
    quote: str,
    locator: dict[str, Any] | None = None,
    extraction_method: str = "rule",
    extractor_version: str = "rule-v1",
    confidence: float = 1.0,
    source_scope: str,
    repository_id: str | None = None,
    owner_user_id: str = "",
    visibility: str = "workspace_shared",
) -> bool:
    cursor.execute(
        """
        INSERT INTO graph_entity_mentions (
            entity_id, source_kind, chunk_id, source_ref, document_source_id,
            parsed_document_id, quote, quote_sha256, locator,
            extraction_method, extractor_version, confidence,
            source_scope, repository_id, owner_user_id, visibility
        )
        VALUES (
            %s::uuid, %s, %s::uuid, %s, %s::uuid,
            %s::uuid, %s, %s, %s::jsonb,
            %s, %s, %s,
            %s, %s::uuid, %s, %s
        )
        ON CONFLICT (
            entity_id, source_kind,
            COALESCE(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
            source_ref, quote_sha256
        ) DO NOTHING
        RETURNING id
        """,
        (
            entity_id,
            source_kind,
            chunk_id,
            source_ref,
            document_source_id,
            parsed_document_id,
            quote,
            quote_sha256(quote),
            json.dumps(locator or {}, ensure_ascii=False),
            extraction_method,
            extractor_version,
            confidence,
            source_scope,
            repository_id,
            owner_user_id,
            visibility,
        ),
    )
    inserted = cursor.fetchone() is not None
    if inserted:
        cursor.execute(
            "UPDATE graph_entities SET mention_count = mention_count + 1 WHERE id = %s::uuid",
            (entity_id,),
        )
    return inserted


def insert_relation(
    cursor,
    *,
    subject_entity_id: str,
    object_entity_id: str,
    relation_type: str,
    source_kind: str = "chunk",
    chunk_id: str | None = None,
    source_ref: str = "",
    document_source_id: str | None = None,
    quote: str = "",
    locator: dict[str, Any] | None = None,
    extraction_method: str = "rule",
    extractor_version: str = "rule-v1",
    confidence: float = 1.0,
    source_scope: str,
    repository_id: str | None = None,
    owner_user_id: str = "",
    visibility: str = "workspace_shared",
) -> bool:
    cursor.execute(
        """
        INSERT INTO graph_entity_relations (
            subject_entity_id, object_entity_id, relation_type,
            source_kind, chunk_id, source_ref, document_source_id,
            quote, quote_sha256, locator,
            extraction_method, extractor_version, confidence,
            source_scope, repository_id, owner_user_id, visibility
        )
        VALUES (
            %s::uuid, %s::uuid, %s,
            %s, %s::uuid, %s, %s::uuid,
            %s, %s, %s::jsonb,
            %s, %s, %s,
            %s, %s::uuid, %s, %s
        )
        ON CONFLICT (
            subject_entity_id, object_entity_id, relation_type, source_kind,
            COALESCE(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
            source_ref
        ) DO NOTHING
        RETURNING id
        """,
        (
            subject_entity_id,
            object_entity_id,
            relation_type,
            source_kind,
            chunk_id,
            source_ref,
            document_source_id,
            quote,
            quote_sha256(quote),
            json.dumps(locator or {}, ensure_ascii=False),
            extraction_method,
            extractor_version,
            confidence,
            source_scope,
            repository_id,
            owner_user_id,
            visibility,
        ),
    )
    return cursor.fetchone() is not None


def delete_document_source_graph(cursor, *, document_source_id: str) -> dict[str, int]:
    cursor.execute(
        "DELETE FROM graph_entity_relations WHERE document_source_id = %s::uuid",
        (document_source_id,),
    )
    relation_count = int(cursor.rowcount or 0)
    cursor.execute(
        "DELETE FROM graph_entity_mentions WHERE document_source_id = %s::uuid",
        (document_source_id,),
    )
    mention_count = int(cursor.rowcount or 0)
    return {"deleted_mentions": mention_count, "deleted_relations": relation_count}


def find_entities_by_names(
    cursor,
    names: list[str],
    *,
    scope: GraphScopeFilter,
) -> list[dict[str, Any]]:
    if not names:
        return []
    clauses = ["name = ANY(%s)", "(owner_user_id = '' OR owner_user_id = %s)"]
    params: list[Any] = [list(names), scope.owner_user_id]
    if scope.enabled_source_scopes:
        clauses.append("source_scope = ANY(%s)")
        params.append(list(scope.enabled_source_scopes))
    cursor.execute(
        f"""
        SELECT id::text AS entity_id, entity_kind, name, entity_key, display_name, aliases
        FROM graph_entities
        WHERE {" AND ".join(clauses)}
        ORDER BY mention_count DESC, entity_key
        """,
        tuple(params),
    )
    return _rows_as_dicts(cursor)


def find_entities_for_chunks(
    cursor,
    chunk_ids: list[str],
    *,
    scope: GraphScopeFilter,
) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []
    scope_sql, scope_params = _scope_clause(scope, alias="gem")
    cursor.execute(
        f"""
        SELECT DISTINCT
            ge.id::text AS entity_id,
            ge.entity_kind,
            ge.name,
            ge.entity_key,
            ge.display_name,
            ge.aliases,
            gem.chunk_id::text AS chunk_id
        FROM graph_entity_mentions gem
        JOIN graph_entities ge ON ge.id = gem.entity_id
        WHERE gem.chunk_id = ANY(%s::uuid[])
        {scope_sql}
        """,
        tuple([list(chunk_ids), *scope_params]),
    )
    return _rows_as_dicts(cursor)


def expand_relations(
    cursor,
    entity_ids: list[str],
    *,
    scope: GraphScopeFilter,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    scope_sql, scope_params = _scope_clause(scope, alias="r")
    cursor.execute(
        f"""
        SELECT
            r.id::text AS relation_id,
            r.relation_type,
            r.confidence,
            r.quote,
            r.source_kind,
            r.source_ref,
            r.chunk_id::text AS chunk_id,
            se.id::text AS subject_entity_id,
            se.entity_key AS subject_key,
            se.entity_kind AS subject_kind,
            se.name AS subject_name,
            oe.id::text AS object_entity_id,
            oe.entity_key AS object_key,
            oe.entity_kind AS object_kind,
            oe.name AS object_name
        FROM graph_entity_relations r
        JOIN graph_entities se ON se.id = r.subject_entity_id
        JOIN graph_entities oe ON oe.id = r.object_entity_id
        WHERE (r.subject_entity_id = ANY(%s::uuid[]) OR r.object_entity_id = ANY(%s::uuid[]))
        {scope_sql}
        ORDER BY r.confidence DESC, r.created_at DESC
        LIMIT %s
        """,
        tuple([list(entity_ids), list(entity_ids), *scope_params, int(limit)]),
    )
    return _rows_as_dicts(cursor)


def load_evidence_chunk_rows(
    cursor,
    entity_ids: list[str],
    *,
    scope: GraphScopeFilter,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    scope_sql, scope_params = _scope_clause(scope, alias="gem")
    cursor.execute(
        f"""
        SELECT
            gem.entity_id::text AS entity_id,
            ge.entity_key,
            ge.entity_kind,
            gem.chunk_id::text AS chunk_id,
            gem.quote,
            gem.confidence
        FROM graph_entity_mentions gem
        JOIN graph_entities ge ON ge.id = gem.entity_id
        JOIN document_chunks c ON c.id = gem.chunk_id
        JOIN parsed_documents pd ON pd.id = c.parsed_document_id
        WHERE gem.entity_id = ANY(%s::uuid[])
          AND gem.source_kind = 'chunk'
        {scope_sql}
        {_LATEST_PARSED_DOCUMENT_GUARD}
        ORDER BY gem.confidence DESC, gem.created_at DESC
        LIMIT %s
        """,
        tuple([list(entity_ids), *scope_params, int(limit)]),
    )
    return _rows_as_dicts(cursor)


def load_lightspeed_evidence_rows(
    cursor,
    entity_ids: list[str],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    cursor.execute(
        """
        SELECT
            gem.entity_id::text AS entity_id,
            ge.entity_key,
            gem.source_ref,
            gem.quote,
            gem.confidence
        FROM graph_entity_mentions gem
        JOIN graph_entities ge ON ge.id = gem.entity_id
        WHERE gem.entity_id = ANY(%s::uuid[])
          AND gem.source_kind = 'lightspeed_artifact'
        ORDER BY gem.confidence DESC, gem.created_at DESC
        LIMIT %s
        """,
        (list(entity_ids), int(limit)),
    )
    return _rows_as_dicts(cursor)


def prune_orphan_entities(cursor) -> int:
    cursor.execute(
        """
        DELETE FROM graph_entities ge
        WHERE NOT EXISTS (
            SELECT 1 FROM graph_entity_mentions gem WHERE gem.entity_id = ge.id
        )
        """
    )
    return int(cursor.rowcount or 0)
