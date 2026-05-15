"""Corpus handoff report for chat/retrieval integration."""

from __future__ import annotations

from typing import Any


CORPUS_HANDOFF_SCHEMA = "corpus_handoff_report_v1"


def _ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 4)


def _visible_source_filter(owner_user_id: str) -> tuple[str, tuple[str, str]]:
    owner = str(owner_user_id or "").strip()
    return (
        "(ds.visibility IN ('workspace_shared', 'global_shared') OR (%s <> '' AND ds.owner_user_id = %s))",
        (owner, owner),
    )


def build_corpus_handoff_report(connection, *, question_limit: int = 20, owner_user_id: str = "") -> dict[str, Any]:
    visible_source_sql, visible_source_params = _visible_source_filter(owner_user_id)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ds.source_scope,
                count(DISTINCT ds.id)::int AS documents,
                count(c.id)::int AS chunks,
                count(c.id) FILTER (WHERE COALESCE(c.metadata->>'topic', '') <> '')::int AS topic_chunks,
                count(c.id) FILTER (WHERE COALESCE(c.metadata->>'semantic_role', '') NOT IN ('', 'unknown', 'uploaded_document'))::int AS role_chunks,
                count(c.id) FILTER (WHERE jsonb_typeof(c.metadata->'cli_commands') = 'array' AND jsonb_array_length(c.metadata->'cli_commands') > 0)::int AS command_chunks,
                count(c.id) FILTER (WHERE jsonb_typeof(c.metadata->'k8s_objects') = 'array' AND jsonb_array_length(c.metadata->'k8s_objects') > 0)::int AS object_chunks,
                count(c.id) FILTER (WHERE jsonb_typeof(c.metadata->'error_strings') = 'array' AND jsonb_array_length(c.metadata->'error_strings') > 0)::int AS error_chunks,
                count(c.id) FILTER (WHERE jsonb_typeof(c.metadata->'verification_hints') = 'array' AND jsonb_array_length(c.metadata->'verification_hints') > 0)::int AS verification_chunks,
                count(c.id) FILTER (WHERE jsonb_typeof(c.metadata->'answerable_questions') = 'array' AND jsonb_array_length(c.metadata->'answerable_questions') > 0)::int AS answerable_chunks,
                count(c.id) FILTER (WHERE COALESCE(c.metadata->>'metadata_confidence', '') = 'low')::int AS low_confidence_chunks
            FROM document_sources ds
            LEFT JOIN parsed_documents pd ON pd.document_source_id = ds.id
            LEFT JOIN document_chunks c ON c.parsed_document_id = pd.id
            WHERE {visible_source_sql}
            GROUP BY ds.source_scope
            ORDER BY ds.source_scope
            """,
            visible_source_params,
        )
        scope_rows = cursor.fetchall()

        cursor.execute(
            f"""
            WITH latest_quality AS (
                SELECT DISTINCT ON (document_source_id)
                    document_source_id,
                    state
                FROM document_quality_snapshots
                ORDER BY document_source_id, created_at DESC
            )
            SELECT ds.source_scope, lq.state, count(*)::int
            FROM document_sources ds
            JOIN latest_quality lq ON lq.document_source_id = ds.id
            WHERE {visible_source_sql}
            GROUP BY ds.source_scope, lq.state
            """,
            visible_source_params,
        )
        quality_rows = cursor.fetchall()

        cursor.execute(
            f"""
            WITH latest_topology AS (
                SELECT DISTINCT ON (document_source_id)
                    document_source_id,
                    state,
                    node_count,
                    edge_count
                FROM document_topology_snapshots
                ORDER BY document_source_id, created_at DESC
            )
            SELECT
                ds.source_scope,
                lt.state,
                count(*)::int,
                COALESCE(sum(lt.node_count), 0)::int,
                COALESCE(sum(lt.edge_count), 0)::int
            FROM document_sources ds
            JOIN latest_topology lt ON lt.document_source_id = ds.id
            WHERE {visible_source_sql}
            GROUP BY ds.source_scope, lt.state
            """,
            visible_source_params,
        )
        topology_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT
                c.id::text,
                ds.id::text AS document_source_id,
                ds.filename,
                c.source_scope,
                c.metadata->'answerable_questions',
                c.metadata,
                c.section_path
            FROM document_chunks c
            JOIN parsed_documents pd ON pd.id = c.parsed_document_id
            JOIN document_sources ds ON ds.id = pd.document_source_id
            WHERE jsonb_typeof(c.metadata->'answerable_questions') = 'array'
              AND jsonb_array_length(c.metadata->'answerable_questions') > 0
              AND {visible_source_sql}
            ORDER BY
                CASE COALESCE(c.metadata->>'metadata_confidence', '')
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                c.source_scope ASC,
                ds.filename ASC,
                c.ordinal ASC
            LIMIT %s
            """,
            (*visible_source_params, max(1, min(int(question_limit), 100))),
        )
        question_rows = cursor.fetchall()

    quality_by_scope: dict[str, dict[str, int]] = {}
    for scope, state, count in quality_rows:
        quality_by_scope.setdefault(str(scope or ""), {})[str(state or "")] = int(count or 0)

    topology_by_scope: dict[str, dict[str, Any]] = {}
    for scope, state, count, nodes, edges in topology_rows:
        item = topology_by_scope.setdefault(str(scope or ""), {"states": {}, "nodes": 0, "edges": 0})
        item["states"][str(state or "")] = int(count or 0)
        item["nodes"] += int(nodes or 0)
        item["edges"] += int(edges or 0)

    scopes: dict[str, Any] = {}
    known_blockers: list[dict[str, Any]] = []
    for row in scope_rows:
        (
            source_scope,
            document_count,
            chunk_count,
            topic_chunks,
            role_chunks,
            command_chunks,
            object_chunks,
            error_chunks,
            verification_chunks,
            answerable_chunks,
            low_confidence_chunks,
        ) = row
        scope = str(source_scope or "")
        chunks = int(chunk_count or 0)
        coverage = {
            "topic": _ratio(int(topic_chunks or 0), chunks),
            "semantic_role": _ratio(int(role_chunks or 0), chunks),
            "cli_commands": _ratio(int(command_chunks or 0), chunks),
            "k8s_objects": _ratio(int(object_chunks or 0), chunks),
            "error_strings": _ratio(int(error_chunks or 0), chunks),
            "verification_hints": _ratio(int(verification_chunks or 0), chunks),
            "answerable_questions": _ratio(int(answerable_chunks or 0), chunks),
            "low_confidence": _ratio(int(low_confidence_chunks or 0), chunks),
        }
        quality = quality_by_scope.get(scope, {})
        topology = topology_by_scope.get(scope, {"states": {}, "nodes": 0, "edges": 0})
        scopes[scope] = {
            "documents": int(document_count or 0),
            "chunks": chunks,
            "metadata_coverage": coverage,
            "gold_ready_count": int(quality.get("gold_ready", 0)),
            "quality_states": quality,
            "topology_states": topology["states"],
            "topology_nodes": int(topology["nodes"]),
            "topology_edges": int(topology["edges"]),
        }
        if chunks and coverage["answerable_questions"] < 0.5:
            known_blockers.append(
                {
                    "scope": scope,
                    "kind": "metadata_coverage",
                    "summary": "answerable_questions coverage below 50%",
                    "metric": coverage["answerable_questions"],
                }
            )
        if int(low_confidence_chunks or 0) > 0:
            known_blockers.append(
                {
                    "scope": scope,
                    "kind": "metadata_confidence",
                    "summary": f"{int(low_confidence_chunks or 0)} low-confidence chunks",
                }
            )

    golden_questions: list[dict[str, Any]] = []
    for chunk_id, document_source_id, filename, source_scope, questions, metadata, section_path in question_rows:
        question_list = [str(item).strip() for item in (questions or []) if str(item).strip()]
        if not question_list:
            continue
        golden_questions.append(
            {
                "question": question_list[0],
                "expected_document": str(filename or ""),
                "expected_chunk_ids": [str(chunk_id or "")],
                "required_metadata": {
                    "topic": str((metadata or {}).get("topic") or ""),
                    "semantic_role": str((metadata or {}).get("semantic_role") or ""),
                    "k8s_objects": list((metadata or {}).get("k8s_objects") or []),
                    "cli_commands": list((metadata or {}).get("cli_commands") or []),
                },
                "expected_answer_shape": "근거 chunk를 인용하고 확인/조치 순서를 짧게 답변",
                "citation_required": True,
                "source_scope": str(source_scope or ""),
                "document_source_id": str(document_source_id or ""),
                "section_path": list(section_path or []),
            }
        )

    return {
        "schema": CORPUS_HANDOFF_SCHEMA,
        "corpus_version": "postgres-runtime",
        "scopes": scopes,
        "golden_questions": golden_questions,
        "known_blockers": known_blockers,
        "acceptance": {
            "minimum_golden_questions": 20,
            "retrieval_hit_at_3": 0.95,
            "answer_pass_rate": 0.95,
            "citation_precision": 0.8,
        },
    }


__all__ = ["CORPUS_HANDOFF_SCHEMA", "build_corpus_handoff_report"]
