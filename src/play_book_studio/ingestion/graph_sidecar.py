from __future__ import annotations

# graph_sidecar_v2

import json
from collections import Counter, defaultdict
from dataclasses import fields
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Iterator

from play_book_studio.config.settings import Settings

from .models import ChunkRecord

try:  # pragma: no cover - optional runtime dependency
    from neo4j import GraphDatabase
except Exception:  # noqa: BLE001
    GraphDatabase = None

_SIGNAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("k8s_objects", "shared_k8s_objects"),
    ("operator_names", "shared_operator_names"),
    ("error_strings", "shared_error_strings"),
    ("verification_hints", "shared_verification_hints"),
)
GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION = "graph_sidecar_compact_v1"
GRAPH_SIDECAR_SCHEMA_VERSION = "graph_sidecar_v1"


def _normalize_signal(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _render_signal(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _coerce_chunk_row(row: ChunkRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, ChunkRecord):
        return row.to_dict()
    return dict(row)


def _chunk_records_from_artifact_rows(rows: list[dict[str, Any]]) -> list[ChunkRecord]:
    allowed = {field.name for field in fields(ChunkRecord)}
    records: list[ChunkRecord] = []
    for row in rows:
        payload = {key: value for key, value in row.items() if key in allowed}
        payload["section_path"] = tuple(payload.get("section_path", []))
        payload["cli_commands"] = tuple(payload.get("cli_commands", []))
        payload["error_strings"] = tuple(payload.get("error_strings", []))
        payload["k8s_objects"] = tuple(payload.get("k8s_objects", []))
        payload["operator_names"] = tuple(payload.get("operator_names", []))
        payload["verification_hints"] = tuple(payload.get("verification_hints", []))
        records.append(ChunkRecord(**payload))
    return records


def _artifact_snapshot(path: Path) -> tuple[dict[str, Any], float | None]:
    exists = path.exists() and path.is_file()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if not exists:
        return payload, None
    stat = path.stat()
    mtime = float(stat.st_mtime)
    payload["size_bytes"] = int(stat.st_size)
    payload["mtime"] = datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")
    return payload, mtime


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _graph_artifact_status(
    *,
    artifact_path: Path,
    source_paths: tuple[Path, ...],
    expected_schema_version: str,
) -> dict[str, Any]:
    artifact, artifact_mtime = _artifact_snapshot(artifact_path)
    status: dict[str, Any] = {
        **artifact,
        "schema_version": "",
        "book_count": 0,
        "relation_count": 0,
        "state": "missing" if artifact_mtime is None else "freshness_unknown",
        "ready": False,
        "requires_refresh": artifact_mtime is None,
        "newest_source_mtime": "",
        "source_artifacts": {},
    }
    source_mtimes: list[float] = []
    source_snapshots: dict[str, Any] = {}
    for source_path in source_paths:
        snapshot, mtime = _artifact_snapshot(source_path)
        source_snapshots[source_path.stem] = snapshot
        if mtime is not None:
            source_mtimes.append(mtime)
    status["source_artifacts"] = source_snapshots
    if source_mtimes:
        newest_source_mtime = max(source_mtimes)
        status["newest_source_mtime"] = datetime.fromtimestamp(newest_source_mtime).astimezone().isoformat(
            timespec="seconds"
        )

    if artifact_mtime is None:
        return status

    payload = _safe_read_json(artifact_path)
    schema_version = str(payload.get("schema_version") or payload.get("schema") or "").strip()
    if not schema_version and expected_schema_version == GRAPH_SIDECAR_SCHEMA_VERSION and payload:
        schema_version = GRAPH_SIDECAR_SCHEMA_VERSION
    status["schema_version"] = schema_version
    status["book_count"] = int(payload.get("book_count") or 0)
    status["relation_count"] = int(payload.get("relation_count") or 0)
    if schema_version != expected_schema_version:
        status["state"] = "invalid"
        status["ready"] = False
        status["requires_refresh"] = True
        return status

    if source_mtimes and artifact_mtime + 1e-9 < max(source_mtimes):
        status["state"] = "stale"
        status["ready"] = False
        status["requires_refresh"] = True
        status["stale_by_seconds"] = round(max(source_mtimes) - artifact_mtime, 3)
        return status

    status["state"] = "fresh" if source_mtimes else "freshness_unknown"
    status["ready"] = True
    status["requires_refresh"] = False
    return status


def graph_sidecar_artifact_status(settings: Settings) -> dict[str, Any]:
    return _graph_artifact_status(
        artifact_path=settings.graph_sidecar_path,
        source_paths=(settings.chunks_path, settings.playbook_documents_path),
        expected_schema_version=GRAPH_SIDECAR_SCHEMA_VERSION,
    )


def graph_sidecar_compact_artifact_status(settings: Settings) -> dict[str, Any]:
    status = _graph_artifact_status(
        artifact_path=settings.graph_sidecar_compact_path,
        source_paths=(settings.chunks_path, settings.playbook_documents_path),
        expected_schema_version=GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
    )
    status["degrade_mode"] = (
        "compact_relations"
        if bool(status.get("ready"))
        else "playbook_documents_runtime_fallback"
    )
    return status


def _book_viewer_path(row: dict[str, Any]) -> str:
    anchor_map = row.get("anchor_map")
    if isinstance(anchor_map, dict) and anchor_map:
        return str(next(iter(anchor_map.values())) or "").strip()
    return str(row.get("viewer_path") or "").strip()


def _build_book_index(
    *,
    chunk_rows: list[dict[str, Any]],
    playbook_documents: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    book_index: dict[str, dict[str, Any]] = {}
    for row in playbook_documents:
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        source_metadata = row.get("source_metadata")
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        book_index[slug] = {
            "book_slug": slug,
            "title": str(row.get("title") or "").strip(),
            "source_uri": str(row.get("source_uri") or row.get("source_url") or "").strip(),
            "viewer_path": _book_viewer_path(row),
            "source_type": str(source_metadata.get("source_type") or "").strip(),
            "source_lane": str(source_metadata.get("source_lane") or "").strip(),
            "source_collection": str(source_metadata.get("source_collection") or "core").strip() or "core",
            "derived_from_book_slug": str(source_metadata.get("derived_from_book_slug") or "").strip(),
            "topic_key": str(source_metadata.get("topic_key") or "").strip(),
            "review_status": str(row.get("review_status") or source_metadata.get("review_status") or "").strip(),
            "quality_status": str(row.get("quality_status") or "").strip(),
        }

    for row in chunk_rows:
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        book_index.setdefault(
            slug,
            {
                "book_slug": slug,
                "title": str(row.get("book_title") or "").strip(),
                "source_uri": str(row.get("source_url") or "").strip(),
                "viewer_path": str(row.get("viewer_path") or "").strip(),
                "source_type": str(row.get("source_type") or "").strip(),
                "source_lane": str(row.get("source_lane") or "").strip(),
                "source_collection": str(row.get("source_collection") or "core").strip() or "core",
                "derived_from_book_slug": str(row.get("derived_from_book_slug") or "").strip(),
                "topic_key": str(row.get("topic_key") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "quality_status": str(row.get("quality_status") or "").strip(),
            },
        )
    return book_index


def _build_shared_signal_groups(
    chunk_rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, list[dict[str, Any]]]]]:
    signal_chunk_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    raw_value_index: dict[tuple[str, str], str] = {}
    for row in chunk_rows:
        for field_name, group_name in _SIGNAL_FIELDS:
            for raw_value in row.get(field_name) or []:
                normalized = _normalize_signal(raw_value)
                rendered = _render_signal(raw_value)
                if not normalized or not rendered:
                    continue
                signal_chunk_map[(group_name, normalized)].append(row)
                raw_value_index.setdefault((group_name, normalized), rendered)

    shared_groups: dict[tuple[str, str], dict[str, Any]] = {}
    relation_groups_by_chunk: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (group_name, normalized), rows in sorted(signal_chunk_map.items()):
        if len(rows) < 2:
            continue
        related_chunk_ids = sorted(
            {
                str(row.get("chunk_id") or "").strip()
                for row in rows
                if str(row.get("chunk_id") or "").strip()
            }
        )
        related_book_slugs = sorted(
            {
                str(row.get("book_slug") or "").strip()
                for row in rows
                if str(row.get("book_slug") or "").strip()
            }
        )
        shared_groups[(group_name, normalized)] = {
            "group_name": group_name,
            "value": raw_value_index[(group_name, normalized)],
            "related_chunk_ids": related_chunk_ids,
            "related_book_slugs": related_book_slugs,
        }
        for row in rows:
            chunk_id = str(row.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            relation_groups_by_chunk[chunk_id][group_name].append(
                {
                    "value": raw_value_index[(group_name, normalized)],
                    "related_chunk_ids": [value for value in related_chunk_ids if value != chunk_id],
                    "related_book_slugs": [
                        value
                        for value in related_book_slugs
                        if value != str(row.get("book_slug") or "").strip()
                    ],
                }
            )
    return shared_groups, relation_groups_by_chunk


def _append_book_relation(
    edge_map: dict[tuple[str, str], dict[str, Any]],
    *,
    source_book_slug: str,
    target_book_slug: str,
    relation_type: str,
    signal_value: str,
) -> None:
    if not source_book_slug or not target_book_slug or source_book_slug == target_book_slug:
        return
    key = tuple(sorted((source_book_slug, target_book_slug)))
    edge = edge_map.setdefault(
        key,
        {
            "source_book_slug": key[0],
            "target_book_slug": key[1],
            "relation_types": set(),
            "signal_values": set(),
            "weight": 0,
        },
    )
    edge["relation_types"].add(relation_type)
    if signal_value:
        edge["signal_values"].add(signal_value)
    edge["weight"] += 1


def _build_book_relations(
    *,
    book_index: dict[str, dict[str, Any]],
    shared_groups: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata in book_index.values():
        derived_from_book_slug = str(metadata.get("derived_from_book_slug") or "").strip()
        if not derived_from_book_slug:
            continue
        _append_book_relation(
            edge_map,
            source_book_slug=metadata["book_slug"],
            target_book_slug=derived_from_book_slug,
            relation_type="derived_from_book",
            signal_value=derived_from_book_slug,
        )
    for shared_group in shared_groups.values():
        related_book_slugs = list(shared_group["related_book_slugs"])
        if len(related_book_slugs) < 2:
            continue
        for index, source_book_slug in enumerate(related_book_slugs):
            for target_book_slug in related_book_slugs[index + 1 :]:
                _append_book_relation(
                    edge_map,
                    source_book_slug=source_book_slug,
                    target_book_slug=target_book_slug,
                    relation_type=shared_group["group_name"],
                    signal_value=str(shared_group["value"]),
                )
    return [
        {
            "source_book_slug": edge["source_book_slug"],
            "target_book_slug": edge["target_book_slug"],
            "relation_types": sorted(edge["relation_types"]),
            "signal_values": sorted(edge["signal_values"]),
            "weight": int(edge["weight"]),
        }
        for _, edge in sorted(edge_map.items())
    ]


def build_graph_sidecar_payload(
    *,
    chunk_rows: list[ChunkRecord | dict[str, Any]],
    playbook_documents: list[dict[str, Any]],
    graph_backend: str = "local",
    app_id: str = "",
    pack_id: str = "",
) -> dict[str, Any]:
    normalized_chunk_rows = [_coerce_chunk_row(row) for row in chunk_rows]
    book_index = _build_book_index(
        chunk_rows=normalized_chunk_rows,
        playbook_documents=playbook_documents,
    )
    shared_groups, relation_groups_by_chunk = _build_shared_signal_groups(normalized_chunk_rows)

    source_type_counts: Counter[str] = Counter()
    books: list[dict[str, Any]] = []
    for slug in sorted(book_index):
        metadata = dict(book_index[slug])
        metadata["chunk_count"] = sum(
            1 for row in normalized_chunk_rows if str(row.get("book_slug") or "").strip() == slug
        )
        source_type = str(metadata.get("source_type") or "").strip()
        if source_type:
            source_type_counts[source_type] += 1
        books.append(metadata)

    chunks: list[dict[str, Any]] = []
    for row in normalized_chunk_rows:
        chunk_id = str(row.get("chunk_id") or "").strip()
        book_slug = str(row.get("book_slug") or "").strip()
        book_metadata = book_index.get(book_slug, {})
        relation_groups = {
            group_name: groups
            for group_name, groups in sorted(relation_groups_by_chunk.get(chunk_id, {}).items())
        }
        chunks.append(
            {
                "chunk_id": chunk_id,
                "book_slug": book_slug,
                "chapter": str(row.get("chapter") or "").strip(),
                "section": str(row.get("section") or "").strip(),
                "anchor": str(row.get("anchor") or "").strip(),
                "viewer_path": str(row.get("viewer_path") or "").strip(),
                "source_url": str(row.get("source_url") or "").strip(),
                "source_collection": str(
                    row.get("source_collection") or book_metadata.get("source_collection") or "core"
                ).strip()
                or "core",
                "source_type": str(row.get("source_type") or book_metadata.get("source_type") or "").strip(),
                "source_lane": str(row.get("source_lane") or book_metadata.get("source_lane") or "").strip(),
                "derived_from_book_slug": str(book_metadata.get("derived_from_book_slug") or "").strip(),
                "topic_key": str(book_metadata.get("topic_key") or "").strip(),
                "k8s_objects": list(row.get("k8s_objects") or []),
                "operator_names": list(row.get("operator_names") or []),
                "error_strings": list(row.get("error_strings") or []),
                "verification_hints": list(row.get("verification_hints") or []),
                "relation_groups": relation_groups,
                "relation_count": sum(len(groups) for groups in relation_groups.values()),
            }
        )

    relation_group_counts = {
        group_name: sum(
            1 for group in shared_groups.values() if group["group_name"] == group_name
        )
        for _, group_name in _SIGNAL_FIELDS
    }
    relations = _build_book_relations(book_index=book_index, shared_groups=shared_groups)

    return {
        "schema": GRAPH_SIDECAR_SCHEMA_VERSION,
        "schema_version": GRAPH_SIDECAR_SCHEMA_VERSION,
        "app_id": app_id,
        "pack_id": pack_id,
        "pack_scope": {
            "app_id": app_id,
            "pack_id": pack_id,
        },
        "graph_backend": graph_backend,
        "book_count": len(books),
        "chunk_count": len(chunks),
        "relation_count": len(relations),
        "summary": {
            "book_count": len(books),
            "chunk_count": len(chunks),
            "relation_group_counts": relation_group_counts,
            "source_type_counts": dict(sorted(source_type_counts.items())),
        },
        "books": books,
        "chunks": chunks,
        "relations": relations,
    }


def build_graph_sidecar_compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    books = [book for book in payload.get("books") or [] if isinstance(book, dict)]
    relations = [relation for relation in payload.get("relations") or [] if isinstance(relation, dict)]
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    app_id = str(payload.get("app_id") or "").strip()
    pack_id = str(payload.get("pack_id") or "").strip()
    return {
        "schema": GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
        "schema_version": GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
        "app_id": app_id,
        "pack_id": pack_id,
        "pack_scope": payload.get("pack_scope")
        if isinstance(payload.get("pack_scope"), dict)
        else {"app_id": app_id, "pack_id": pack_id},
        "graph_backend": str(payload.get("graph_backend") or "").strip(),
        "book_count": len(books),
        "relation_count": len(relations),
        "summary": {
            **summary,
            "book_count": len(books),
            "relation_count": len(relations),
        },
        "books": books,
        "relations": relations,
    }


def _iter_jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict):
                yield payload


def build_graph_sidecar_compact_payload_from_artifacts(
    *,
    chunks_path: Path,
    playbook_documents_path: Path,
    graph_backend: str = "local",
    app_id: str = "",
    pack_id: str = "",
) -> dict[str, Any]:
    book_index: dict[str, dict[str, Any]] = {}
    source_type_counts: Counter[str] = Counter()
    for row in _iter_jsonl_rows(playbook_documents_path):
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        source_metadata = row.get("source_metadata")
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        metadata = {
            "book_slug": slug,
            "title": str(row.get("title") or "").strip(),
            "source_uri": str(row.get("source_uri") or row.get("source_url") or "").strip(),
            "viewer_path": _book_viewer_path(row),
            "source_type": str(source_metadata.get("source_type") or "").strip(),
            "source_lane": str(source_metadata.get("source_lane") or "").strip(),
            "source_collection": str(source_metadata.get("source_collection") or "core").strip() or "core",
            "derived_from_book_slug": str(source_metadata.get("derived_from_book_slug") or "").strip(),
            "topic_key": str(source_metadata.get("topic_key") or "").strip(),
            "review_status": str(row.get("review_status") or source_metadata.get("review_status") or "").strip(),
            "quality_status": str(row.get("quality_status") or "").strip(),
            "chunk_count": 0,
        }
        book_index[slug] = metadata
        source_type = str(metadata.get("source_type") or "").strip()
        if source_type:
            source_type_counts[source_type] += 1

    signal_book_map: dict[tuple[str, str], set[str]] = defaultdict(set)
    raw_value_index: dict[tuple[str, str], str] = {}
    for row in _iter_jsonl_rows(chunks_path):
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        metadata = book_index.get(slug)
        if metadata is None:
            metadata = {
                "book_slug": slug,
                "title": str(row.get("book_title") or "").strip(),
                "source_uri": str(row.get("source_url") or "").strip(),
                "viewer_path": str(row.get("viewer_path") or "").strip(),
                "source_type": str(row.get("source_type") or "").strip(),
                "source_lane": str(row.get("source_lane") or "").strip(),
                "source_collection": str(row.get("source_collection") or "core").strip() or "core",
                "derived_from_book_slug": str(row.get("derived_from_book_slug") or "").strip(),
                "topic_key": str(row.get("topic_key") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "quality_status": str(row.get("quality_status") or "").strip(),
                "chunk_count": 0,
            }
            book_index[slug] = metadata
            source_type = str(metadata.get("source_type") or "").strip()
            if source_type:
                source_type_counts[source_type] += 1
        metadata["chunk_count"] = int(metadata.get("chunk_count") or 0) + 1
        for field_name, group_name in _SIGNAL_FIELDS:
            for raw_value in row.get(field_name) or []:
                normalized = _normalize_signal(raw_value)
                rendered = _render_signal(raw_value)
                if not normalized or not rendered:
                    continue
                key = (group_name, normalized)
                signal_book_map[key].add(slug)
                raw_value_index.setdefault(key, rendered)

    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata in book_index.values():
        derived_from_book_slug = str(metadata.get("derived_from_book_slug") or "").strip()
        if not derived_from_book_slug:
            continue
        _append_book_relation(
            edge_map,
            source_book_slug=str(metadata.get("book_slug") or "").strip(),
            target_book_slug=derived_from_book_slug,
            relation_type="derived_from_book",
            signal_value=derived_from_book_slug,
        )
    relation_group_counts = {group_name: 0 for _, group_name in _SIGNAL_FIELDS}
    for (group_name, _normalized), related_book_slugs in sorted(signal_book_map.items()):
        if len(related_book_slugs) < 2:
            continue
        relation_group_counts[group_name] += 1
        signal_value = raw_value_index[(group_name, _normalized)]
        ordered_book_slugs = sorted(related_book_slugs)
        for index, source_book_slug in enumerate(ordered_book_slugs):
            for target_book_slug in ordered_book_slugs[index + 1 :]:
                _append_book_relation(
                    edge_map,
                    source_book_slug=source_book_slug,
                    target_book_slug=target_book_slug,
                    relation_type=group_name,
                    signal_value=signal_value,
                )

    books = [dict(book_index[slug]) for slug in sorted(book_index)]
    relations = [
        {
            "source_book_slug": edge["source_book_slug"],
            "target_book_slug": edge["target_book_slug"],
            "relation_types": sorted(edge["relation_types"]),
            "signal_values": sorted(edge["signal_values"]),
            "weight": int(edge["weight"]),
        }
        for _, edge in sorted(edge_map.items())
    ]
    return {
        "schema": GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
        "schema_version": GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
        "app_id": app_id,
        "pack_id": pack_id,
        "pack_scope": {
            "app_id": app_id,
            "pack_id": pack_id,
        },
        "graph_backend": graph_backend,
        "book_count": len(books),
        "relation_count": len(relations),
        "summary": {
            "book_count": len(books),
            "relation_count": len(relations),
            "relation_group_counts": relation_group_counts,
            "source_type_counts": dict(sorted(source_type_counts.items())),
        },
        "books": books,
        "relations": relations,
    }


def write_graph_sidecar_compact_from_artifacts(
    settings: Settings,
    *,
    output_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    payload = build_graph_sidecar_compact_payload_from_artifacts(
        chunks_path=settings.chunks_path,
        playbook_documents_path=settings.playbook_documents_path,
        graph_backend=settings.graph_backend,
        app_id=settings.app_id,
        pack_id=settings.active_pack_id,
    )
    target_path = output_path or settings.graph_sidecar_compact_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target_path, payload


def write_graph_sidecar_from_artifacts(
    settings: Settings,
    *,
    output_path: Path | None = None,
    compact_output_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    chunk_rows = list(_iter_jsonl_rows(settings.chunks_path))
    playbook_documents = list(_iter_jsonl_rows(settings.playbook_documents_path))
    payload = build_graph_sidecar_payload(
        chunk_rows=_chunk_records_from_artifact_rows(chunk_rows),
        playbook_documents=playbook_documents,
        graph_backend=settings.graph_backend,
        app_id=settings.app_id,
        pack_id=settings.active_pack_id,
    )
    compact_payload = build_graph_sidecar_compact_payload(payload)
    target_path = output_path or settings.graph_sidecar_path
    compact_target_path = compact_output_path or settings.graph_sidecar_compact_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact_target_path.write_text(
        json.dumps(compact_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if target_path == settings.graph_sidecar_path and compact_target_path == settings.graph_sidecar_compact_path:
        _write_neo4j_payload(settings, payload=payload)
    return target_path, payload


def refresh_active_runtime_graph_artifacts(
    settings: Settings,
    *,
    refresh_full_sidecar: bool,
    allow_compact_degrade: bool = False,
) -> dict[str, Any]:
    if refresh_full_sidecar:
        output_path, payload = write_graph_sidecar_from_artifacts(settings)
        compact_status = graph_sidecar_compact_artifact_status(settings)
        return {
            "status": "ok",
            "degrade_mode": "compact_relations",
            "full_sidecar": {
                "status": "ok",
                "output_path": str(output_path),
                "book_count": int(payload.get("book_count") or 0),
                "relation_count": int(payload.get("relation_count") or 0),
            },
            "compact_sidecar": {
                "status": "ok",
                "output_path": str(settings.graph_sidecar_compact_path),
                "book_count": int(compact_status.get("book_count") or 0),
                "relation_count": int(compact_status.get("relation_count") or 0),
                "artifact_status": compact_status,
            },
        }

    try:
        output_path, payload = write_graph_sidecar_compact_from_artifacts(settings)
    except Exception as exc:  # noqa: BLE001
        if not allow_compact_degrade:
            raise
        compact_status = graph_sidecar_compact_artifact_status(settings)
        return {
            "status": "degraded",
            "degrade_mode": "playbook_documents_runtime_fallback",
            "full_sidecar": {
                "status": "skipped",
                "reason": "policy_compact_only",
            },
            "compact_sidecar": {
                "status": "degraded",
                "error": str(exc),
                "degrade_mode": "playbook_documents_runtime_fallback",
                "artifact_status": compact_status,
            },
        }

    compact_status = graph_sidecar_compact_artifact_status(settings)
    return {
        "status": "ok",
        "degrade_mode": "compact_relations",
        "full_sidecar": {
            "status": "skipped",
            "reason": "policy_compact_only",
        },
        "compact_sidecar": {
            "status": "ok",
            "output_path": str(output_path),
            "book_count": int(payload.get("book_count") or 0),
            "relation_count": int(payload.get("relation_count") or 0),
            "artifact_status": compact_status,
        },
    }


def _neo4j_relation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relation in payload.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        source_book_slug = str(relation.get("source_book_slug") or "").strip()
        target_book_slug = str(relation.get("target_book_slug") or "").strip()
        if not source_book_slug or not target_book_slug:
            continue
        signal_values = [
            str(value).strip()
            for value in (relation.get("signal_values") or [])
            if str(value).strip()
        ]
        for relation_type in relation.get("relation_types") or []:
            relation_type = str(relation_type or "").strip()
            if not relation_type:
                continue
            rows.append(
                {
                    "source_book_slug": source_book_slug,
                    "target_book_slug": target_book_slug,
                    "relation_type": relation_type,
                    "signal_value": signal_values[0] if signal_values else "",
                    "weight": int(relation.get("weight") or 1),
                }
            )
    return rows


def _batched_rows(rows: list[dict[str, Any]], *, batch_size: int) -> list[list[dict[str, Any]]]:
    if batch_size <= 0:
        return [rows]
    iterator = iter(rows)
    batches: list[list[dict[str, Any]]] = []
    while True:
        batch = list(islice(iterator, batch_size))
        if not batch:
            break
        batches.append(batch)
    return batches


def _delete_existing_graph(session, *, app_id: str, pack_id: str, batch_size: int) -> None:
    while True:
        record = session.run(
            """
            MATCH (n {app_id: $app_id, pack_id: $pack_id})
            WITH n LIMIT $limit
            DETACH DELETE n
            RETURN count(*) AS deleted
            """,
            app_id=app_id,
            pack_id=pack_id,
            limit=batch_size,
        ).single()
        deleted_value = 0
        if isinstance(record, dict):
            deleted_value = record.get("deleted", 0)
        else:
            try:
                deleted_value = record["deleted"]
            except Exception:  # noqa: BLE001
                deleted_value = 0
        deleted_count = int(deleted_value) if isinstance(deleted_value, (int, float, str)) else 0
        if deleted_count <= 0:
            break


def _neo4j_chunk_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in payload.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        rows.append(
            {
                "chunk_id": str(chunk.get("chunk_id") or "").strip(),
                "book_slug": str(chunk.get("book_slug") or "").strip(),
                "chapter": str(chunk.get("chapter") or "").strip(),
                "section": str(chunk.get("section") or "").strip(),
                "anchor": str(chunk.get("anchor") or "").strip(),
                "viewer_path": str(chunk.get("viewer_path") or "").strip(),
                "source_url": str(chunk.get("source_url") or "").strip(),
                "source_collection": str(chunk.get("source_collection") or "core").strip() or "core",
                "source_type": str(chunk.get("source_type") or "").strip(),
                "source_lane": str(chunk.get("source_lane") or "").strip(),
                "derived_from_book_slug": str(chunk.get("derived_from_book_slug") or "").strip(),
                "topic_key": str(chunk.get("topic_key") or "").strip(),
                "relation_count": int(chunk.get("relation_count") or 0),
            }
        )
    return rows


def _write_neo4j_payload(settings: Settings, *, payload: dict[str, Any]) -> None:
    if str(settings.graph_backend or "").strip().lower() != "neo4j":
        return
    if GraphDatabase is None:
        raise RuntimeError("neo4j driver is not installed")
    if not settings.graph_uri:
        raise RuntimeError("graph uri is not configured")
    auth = None
    if settings.graph_username or settings.graph_password:
        auth = (settings.graph_username or "", settings.graph_password or "")
    driver = GraphDatabase.driver(settings.graph_uri, auth=auth)
    books = [book for book in payload.get("books") or [] if isinstance(book, dict)]
    chunk_rows = _neo4j_chunk_rows(payload)
    relation_rows = _neo4j_relation_rows(payload)
    batch_size = 250
    try:  # pragma: no cover - exercised via mocking in tests
        with driver.session(database=settings.graph_database or None) as session:
            session.run(
                """
                CREATE CONSTRAINT playbook_identity IF NOT EXISTS
                FOR (b:Playbook)
                REQUIRE (b.app_id, b.pack_id, b.book_slug) IS UNIQUE
                """
            )
            session.run(
                """
                CREATE CONSTRAINT chunk_identity IF NOT EXISTS
                FOR (c:Chunk)
                REQUIRE (c.app_id, c.pack_id, c.chunk_id) IS UNIQUE
                """
            )
            _delete_existing_graph(
                session,
                app_id=settings.app_id,
                pack_id=settings.active_pack_id,
                batch_size=1000,
            )
            for book_batch in _batched_rows(books, batch_size=batch_size):
                session.run(
                    """
                    UNWIND $books AS book
                    MERGE (b:Playbook {app_id: $app_id, pack_id: $pack_id, book_slug: book.book_slug})
                    SET b += book
                    """,
                    app_id=settings.app_id,
                    pack_id=settings.active_pack_id,
                    books=book_batch,
                )
            for chunk_batch in _batched_rows(chunk_rows, batch_size=batch_size):
                session.run(
                    """
                    UNWIND $chunks AS chunk
                    MERGE (b:Playbook {app_id: $app_id, pack_id: $pack_id, book_slug: chunk.book_slug})
                    MERGE (c:Chunk {app_id: $app_id, pack_id: $pack_id, chunk_id: chunk.chunk_id})
                    SET c += chunk
                    MERGE (b)-[:HAS_CHUNK]->(c)
                    """,
                    app_id=settings.app_id,
                    pack_id=settings.active_pack_id,
                    chunks=chunk_batch,
                )
            for relation_batch in _batched_rows(relation_rows, batch_size=batch_size):
                session.run(
                    """
                    UNWIND $relations AS relation
                    MATCH (source:Playbook {app_id: $app_id, pack_id: $pack_id, book_slug: relation.source_book_slug})
                    MATCH (target:Playbook {app_id: $app_id, pack_id: $pack_id, book_slug: relation.target_book_slug})
                    MERGE (source)-[r:RELATED {
                        app_id: $app_id,
                        pack_id: $pack_id,
                        source_book_slug: relation.source_book_slug,
                        target_book_slug: relation.target_book_slug,
                        relation_type: relation.relation_type,
                        signal_value: relation.signal_value
                    }]->(target)
                    SET r.weight = relation.weight
                    """,
                    app_id=settings.app_id,
                    pack_id=settings.active_pack_id,
                    relations=relation_batch,
                )
    finally:
        driver.close()


def write_graph_sidecar(
    settings: Settings,
    *,
    chunks: list[ChunkRecord],
    playbook_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = build_graph_sidecar_payload(
        chunk_rows=chunks,
        playbook_documents=playbook_documents,
        graph_backend=settings.graph_backend,
        app_id=settings.app_id,
        pack_id=settings.active_pack_id,
    )
    compact_payload = build_graph_sidecar_compact_payload(payload)
    settings.graph_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.graph_sidecar_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with settings.graph_sidecar_compact_path.open("w", encoding="utf-8") as handle:
        json.dump(compact_payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    _write_neo4j_payload(settings, payload=payload)
    return payload
