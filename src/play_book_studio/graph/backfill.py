from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.db import graph_repository

from .extractor import build_entity_extractor
from .service import (
    extract_graph_for_lightspeed_artifact,
    extract_graph_for_parsed_document,
)

_CANDIDATE_DOCUMENTS_SQL = """
SELECT DISTINCT
    pd.id::text AS parsed_document_id,
    ds.id::text AS document_source_id,
    MIN(pd.created_at) AS created_at
FROM document_chunks c
JOIN parsed_documents pd ON pd.id = c.parsed_document_id
JOIN document_sources ds ON ds.id = pd.document_source_id
WHERE (%s = 'all' OR c.source_scope = %s)
  AND (
      c.source_scope <> 'user_upload'
      OR pd.id = (
          SELECT latest_pd.id
          FROM parsed_documents latest_pd
          WHERE latest_pd.document_source_id = ds.id
          ORDER BY latest_pd.created_at DESC, latest_pd.id DESC
          LIMIT 1
      )
  )
GROUP BY pd.id, ds.id
ORDER BY MIN(pd.created_at)
"""


def lightspeed_artifact_paths(settings: Settings) -> list[Path]:
    artifact_dir = settings.artifacts_dir / "external_answers" / "lightspeed"
    if not artifact_dir.is_dir():
        return []
    return sorted(artifact_dir.glob("*.json"))


def run_entity_graph_backfill(
    settings: Settings,
    *,
    database_url: str,
    source_scope: str = "all",
    include_lightspeed: bool = False,
    rebuild: bool = False,
    prune: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    import psycopg

    extractor = build_entity_extractor(settings)
    summary: dict[str, Any] = {
        "source_scope": source_scope,
        "extractor": f"{extractor.name}:{extractor.version}",
        "rebuild": rebuild,
        "document_count": 0,
        "entity_count": 0,
        "mention_count": 0,
        "relation_count": 0,
        "lightspeed_artifact_count": 0,
        "pruned_entity_count": 0,
    }

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            sql = _CANDIDATE_DOCUMENTS_SQL
            params: list[Any] = [source_scope, source_scope]
            if limit > 0:
                sql += " LIMIT %s"
                params.append(int(limit))
            cursor.execute(sql, tuple(params))
            documents = [(str(row[0]), str(row[1])) for row in cursor.fetchall()]

        for parsed_document_id, document_source_id in documents:
            document_summary = extract_graph_for_parsed_document(
                connection,
                parsed_document_id=parsed_document_id,
                document_source_id=document_source_id,
                extractor=extractor,
                replace=rebuild,
            )
            summary["document_count"] += 1
            summary["entity_count"] += int(document_summary.get("entity_count") or 0)
            summary["mention_count"] += int(document_summary.get("mention_count") or 0)
            summary["relation_count"] += int(document_summary.get("relation_count") or 0)
            connection.commit()

        if include_lightspeed:
            if rebuild:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM graph_entity_relations WHERE source_kind = 'lightspeed_artifact'"
                    )
                    cursor.execute(
                        "DELETE FROM graph_entity_mentions WHERE source_kind = 'lightspeed_artifact'"
                    )
                connection.commit()
            for artifact_path in lightspeed_artifact_paths(settings):
                artifact_summary = extract_graph_for_lightspeed_artifact(
                    connection,
                    artifact_path=artifact_path,
                    extractor=extractor,
                )
                summary["lightspeed_artifact_count"] += 1
                summary["entity_count"] += int(artifact_summary.get("entity_count") or 0)
                summary["mention_count"] += int(artifact_summary.get("mention_count") or 0)
                summary["relation_count"] += int(artifact_summary.get("relation_count") or 0)
                connection.commit()

        if prune:
            with connection.cursor() as cursor:
                summary["pruned_entity_count"] = graph_repository.prune_orphan_entities(cursor)
            connection.commit()

    return summary
