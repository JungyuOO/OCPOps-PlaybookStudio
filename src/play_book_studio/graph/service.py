from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from play_book_studio.db import graph_repository

from .extractor import EntityExtractor
from .models import ExtractedEntity, ExtractionResult

LIGHTSPEED_SOURCE_SCOPE = "lightspeed_answer"


def _entity_owner(owner_user_id: str, visibility: str) -> str:
    # Private uploads keep per-owner entities; shared lanes merge into the '' owner.
    return owner_user_id if visibility == "private_user" else ""


def _empty_summary() -> dict[str, Any]:
    return {"entity_count": 0, "mention_count": 0, "relation_count": 0}


class _GraphWriter:
    def __init__(self, cursor, *, extractor: EntityExtractor) -> None:
        self.cursor = cursor
        self.extractor = extractor
        self.entity_ids: dict[tuple[str, str, str], str] = {}
        self.mention_count = 0
        self.relation_count = 0

    def _entity_id(
        self,
        entity: ExtractedEntity,
        *,
        source_scope: str,
        owner_user_id: str,
    ) -> str:
        key = (entity.entity_key, source_scope, owner_user_id)
        entity_id = self.entity_ids.get(key)
        if entity_id is None:
            entity_id = graph_repository.upsert_entity(
                self.cursor,
                entity_kind=entity.entity_kind,
                name=entity.name,
                display_name=entity.display_name,
                label=entity.label,
                source_scope=source_scope,
                owner_user_id=owner_user_id,
            )
            self.entity_ids[key] = entity_id
        return entity_id

    def write(
        self,
        result: ExtractionResult,
        *,
        source_kind: str = "chunk",
        chunk_id: str | None = None,
        source_ref: str = "",
        document_source_id: str | None = None,
        parsed_document_id: str | None = None,
        source_scope: str,
        repository_id: str | None = None,
        owner_user_id: str = "",
        visibility: str = "workspace_shared",
    ) -> None:
        entity_owner = _entity_owner(owner_user_id, visibility)
        for mention in result.mentions:
            entity_id = self._entity_id(
                mention.entity,
                source_scope=source_scope,
                owner_user_id=entity_owner,
            )
            inserted = graph_repository.insert_mention(
                self.cursor,
                entity_id=entity_id,
                source_kind=source_kind,
                chunk_id=chunk_id,
                source_ref=source_ref,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                quote=mention.quote,
                locator=mention.locator,
                extraction_method=self.extractor.name,
                extractor_version=self.extractor.version,
                confidence=mention.confidence,
                source_scope=source_scope,
                repository_id=repository_id,
                owner_user_id=owner_user_id,
                visibility=visibility,
            )
            if inserted:
                self.mention_count += 1
        for relation in result.relations:
            subject_id = self._entity_id(
                relation.subject,
                source_scope=source_scope,
                owner_user_id=entity_owner,
            )
            object_id = self._entity_id(
                relation.object,
                source_scope=source_scope,
                owner_user_id=entity_owner,
            )
            inserted = graph_repository.insert_relation(
                self.cursor,
                subject_entity_id=subject_id,
                object_entity_id=object_id,
                relation_type=relation.relation_type,
                source_kind=source_kind,
                chunk_id=chunk_id,
                source_ref=source_ref,
                document_source_id=document_source_id,
                quote=relation.quote,
                locator=relation.locator,
                extraction_method=self.extractor.name,
                extractor_version=self.extractor.version,
                confidence=relation.confidence,
                source_scope=source_scope,
                repository_id=repository_id,
                owner_user_id=owner_user_id,
                visibility=visibility,
            )
            if inserted:
                self.relation_count += 1

    def summary(self) -> dict[str, Any]:
        return {
            "entity_count": len(self.entity_ids),
            "mention_count": self.mention_count,
            "relation_count": self.relation_count,
        }


def extract_graph_for_parsed_document(
    connection,
    *,
    parsed_document_id: str,
    document_source_id: str,
    extractor: EntityExtractor,
    replace: bool = True,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        if replace:
            graph_repository.delete_document_source_graph(
                cursor, document_source_id=document_source_id
            )
        cursor.execute(
            """
            SELECT
                id::text AS chunk_id,
                markdown,
                section_path,
                source_scope,
                repository_id::text AS repository_id,
                owner_user_id,
                visibility
            FROM document_chunks
            WHERE parsed_document_id = %s::uuid
            ORDER BY ordinal
            """,
            (parsed_document_id,),
        )
        columns = [column.name for column in cursor.description or []]
        chunk_rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

        writer = _GraphWriter(cursor, extractor=extractor)
        for row in chunk_rows:
            markdown = str(row.get("markdown") or "")
            if not markdown.strip():
                continue
            section_path = row.get("section_path") or []
            if not isinstance(section_path, (list, tuple)):
                section_path = []
            result = extractor.extract(
                markdown,
                section_path=tuple(str(part) for part in section_path),
            )
            if not result.mentions:
                continue
            writer.write(
                result,
                source_kind="chunk",
                chunk_id=str(row.get("chunk_id") or ""),
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
                source_scope=str(row.get("source_scope") or "user_upload"),
                repository_id=row.get("repository_id") or None,
                owner_user_id=str(row.get("owner_user_id") or ""),
                visibility=str(row.get("visibility") or "workspace_shared"),
            )
        summary = writer.summary()
    summary["parsed_document_id"] = parsed_document_id
    summary["document_source_id"] = document_source_id
    summary["chunk_count"] = len(chunk_rows)
    return summary


def extract_graph_for_lightspeed_artifact(
    connection,
    *,
    artifact_path: Path,
    extractor: EntityExtractor,
) -> dict[str, Any]:
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {**_empty_summary(), "status": "unreadable", "artifact_path": str(artifact_path)}
    if not isinstance(payload, dict):
        return {**_empty_summary(), "status": "invalid", "artifact_path": str(artifact_path)}

    artifact_id = str(payload.get("artifact_id") or artifact_path.stem).strip()
    texts = [str(payload.get("answer") or ""), str(payload.get("query") or "")]

    with connection.cursor() as cursor:
        writer = _GraphWriter(cursor, extractor=extractor)
        for text in texts:
            if not text.strip():
                continue
            result = extractor.extract(text)
            if not result.mentions:
                continue
            writer.write(
                result,
                source_kind="lightspeed_artifact",
                chunk_id=None,
                source_ref=artifact_id,
                source_scope=LIGHTSPEED_SOURCE_SCOPE,
                visibility="workspace_shared",
            )
        summary = writer.summary()
    summary["artifact_id"] = artifact_id
    summary["status"] = "ok"
    return summary
