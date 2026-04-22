from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.graph_sidecar import (
    graph_sidecar_artifact_status,
    graph_sidecar_compact_artifact_status,
)

from .models import RetrievalHit, SessionContext
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event

try:  # pragma: no cover - optional runtime dependency
    from neo4j import GraphDatabase
except Exception:  # noqa: BLE001
    GraphDatabase = None

GARBAGE_RELATION_SLUGS = {
    "release_notes",
    "support",
    "validation_and_troubleshooting",
    "cli_tools",
    "disconnected_environments",
}
GRAPH_HEALTH_CACHE_TTL_SECONDS = 15.0
GRAPH_PROBE_MAX_TIMEOUT_SECONDS = 1.0
GRAPH_PROBE_MIN_TIMEOUT_SECONDS = 0.2
LOCAL_SIDECAR_EAGER_LOAD_MAX_BYTES = 64 * 1024 * 1024

def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _serialize_hit(hit: RetrievalHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "book_slug": hit.book_slug,
        "chapter": hit.chapter,
        "section": hit.section,
        "anchor": hit.anchor,
        "viewer_path": hit.viewer_path,
        "source_url": hit.source_url,
        "source_collection": hit.source_collection,
        "semantic_role": hit.semantic_role,
        "section_path": list(hit.section_path),
        "block_kinds": list(hit.block_kinds),
    }


def _book_index_from_sidecar_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    books = payload.get("books")
    if not isinstance(books, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in books:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("book_slug") or "").strip()
        if not slug:
            continue
        index[slug] = {
            "book_slug": slug,
            "title": str(item.get("title") or "").strip(),
            "source_type": str(item.get("source_type") or "").strip(),
            "source_lane": str(item.get("source_lane") or "").strip(),
            "source_collection": str(item.get("source_collection") or "core").strip() or "core",
            "derived_from_book_slug": str(item.get("derived_from_book_slug") or "").strip(),
            "topic_key": str(item.get("topic_key") or "").strip(),
            "quality_status": str(item.get("quality_status") or "").strip(),
            "review_status": str(item.get("review_status") or "").strip(),
        }
    return index


def _book_index_from_playbook_documents(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _safe_read_jsonl(path):
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        source_metadata = row.get("source_metadata")
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        index[slug] = {
            "book_slug": slug,
            "title": str(row.get("title") or "").strip(),
            "source_type": str(source_metadata.get("source_type") or "").strip(),
            "source_lane": str(source_metadata.get("source_lane") or "").strip(),
            "source_collection": str(source_metadata.get("source_collection") or "core").strip() or "core",
            "derived_from_book_slug": str(source_metadata.get("derived_from_book_slug") or "").strip(),
            "topic_key": str(source_metadata.get("topic_key") or "").strip(),
            "quality_status": str(row.get("quality_status") or "").strip(),
            "review_status": str(row.get("review_status") or source_metadata.get("review_status") or "").strip(),
        }
    return index


def _relation_index_from_sidecar_payload(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    relation_index: dict[str, list[dict[str, Any]]] = {}
    relations = payload.get("relations")
    if not isinstance(relations, list):
        return relation_index
    for item in relations:
        if not isinstance(item, dict):
            continue
        source_book_slug = str(item.get("source_book_slug") or "").strip()
        target_book_slug = str(item.get("target_book_slug") or "").strip()
        if not source_book_slug or not target_book_slug:
            continue
        relation_types = [
            str(value).strip()
            for value in (item.get("relation_types") or [])
            if str(value).strip()
        ]
        signal_values = [
            str(value).strip()
            for value in (item.get("signal_values") or [])
            if str(value).strip()
        ]
        weight = int(item.get("weight") or 1)
        
        if target_book_slug not in GARBAGE_RELATION_SLUGS:
            relation_index.setdefault(source_book_slug, []).append(
                {
                    "type": relation_types[0] if relation_types else "related",
                    "relation_types": relation_types,
                    "signal_values": signal_values,
                    "target_book_slug": target_book_slug,
                    "weight": weight,
                }
            )
        if source_book_slug not in GARBAGE_RELATION_SLUGS:
            relation_index.setdefault(target_book_slug, []).append(
                {
                    "type": relation_types[0] if relation_types else "related",
                    "relation_types": relation_types,
                    "signal_values": signal_values,
                    "target_book_slug": source_book_slug,
                    "weight": weight,
                }
            )
    return relation_index


def _graph_enabled(settings: Settings) -> bool:
    return bool(settings.graph_enabled)


def _payload_graph_flags(*, enabled: bool, adapter_mode: str) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "graph_enabled": enabled,
        "adapter_mode": adapter_mode,
    }


def _join_fallback_reasons(*reasons: str) -> str:
    joined: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        normalized = str(reason or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        joined.append(normalized)
    return "|".join(joined)


def _resolved_mode(settings: Settings) -> str:
    explicit = (settings.graph_runtime_mode or "").strip().lower()
    if explicit in {"local", "local_sidecar", "remote", "endpoint", "neo4j"}:
        if explicit == "endpoint":
            return "remote"
        if explicit == "local_sidecar":
            return "local"
        return explicit
    backend = (settings.graph_backend or "").strip().lower()
    if backend == "neo4j" and settings.graph_uri:
        return "neo4j"
    if settings.graph_endpoint:
        return "remote"
    return "local"


def _graph_probe_timeout_seconds(settings: Settings) -> float:
    return max(
        GRAPH_PROBE_MIN_TIMEOUT_SECONDS,
        min(float(settings.graph_timeout_seconds or 0.0), GRAPH_PROBE_MAX_TIMEOUT_SECONDS),
    )


def _neo4j_host_port(graph_uri: str) -> tuple[str, int] | None:
    parsed = urlparse(str(graph_uri or "").strip())
    host = parsed.hostname
    if not host:
        return None
    return host, int(parsed.port or 7687)


def _probe_tcp_endpoint(host: str, port: int, *, timeout_seconds: float) -> tuple[bool, str]:
    deadline = time.monotonic() + max(timeout_seconds, GRAPH_PROBE_MIN_TIMEOUT_SECONDS)
    last_error: OSError | None = None
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"resolve failed: {exc}"

    seen: set[tuple[int, int, int, str]] = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        target = (family, socktype, proto, str(sockaddr))
        if target in seen:
            continue
        seen.add(target)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(remaining)
                sock.connect(sockaddr)
            return True, ""
        except OSError as exc:
            last_error = exc
            continue

    if last_error is None:
        return False, "connect failed: probe timeout"
    return False, f"connect failed: {last_error}"


def _apply_graph_payload(
    settings: Settings,
    *,
    hits: list[RetrievalHit],
    payload: dict[str, Any],
) -> list[RetrievalHit]:
    graph_hits = payload.get("hits")
    if not isinstance(graph_hits, list) or not hits:
        return hits

    boost_window = max(1, int(settings.graph_boost_top_n))
    seed_books = {hit.book_slug for hit in hits[:boost_window]}
    graph_hit_index = {
        str(item.get("chunk_id") or ""): item
        for item in graph_hits
        if isinstance(item, dict) and str(item.get("chunk_id") or "").strip()
    }
    enriched_hits = list(hits)
    for hit in enriched_hits:
        graph_hit = graph_hit_index.get(hit.chunk_id)
        if not isinstance(graph_hit, dict):
            continue
        relations = graph_hit.get("relations")
        if not isinstance(relations, list):
            relations = []
        provenance = graph_hit.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        relation_labels = sorted(
            {
                str(relation.get("type") or "").strip()
                for relation in relations
                if isinstance(relation, dict) and str(relation.get("type") or "").strip()
            }
        )
        support_targets = {
            str(relation.get("target_book_slug") or "").strip()
            for relation in relations
            if isinstance(relation, dict)
            and str(relation.get("target_book_slug") or "").strip() in seed_books
            and str(relation.get("target_book_slug") or "").strip() != hit.book_slug
        }
        boost = 0.0
        if support_targets:
            boost += min(0.18, 0.05 * len(support_targets))
        if relation_labels:
            boost += min(0.12, 0.02 * len(relation_labels))
        derived_from_book_slug = str(provenance.get("derived_from_book_slug") or "").strip()
        if derived_from_book_slug and derived_from_book_slug in seed_books:
            boost += 0.05
        boost = round(min(boost, 0.35), 4)
        hit.component_scores["graph_relation_count"] = float(len(relations))
        hit.component_scores["graph_provenance_count"] = 1.0 if provenance else 0.0
        hit.component_scores["graph_boost"] = boost
        if relation_labels:
            hit.graph_relations = tuple(relation_labels)
        if derived_from_book_slug:
            hit.component_scores["graph_has_derivation"] = 1.0
        if boost > 0.0:
            hit.fused_score = round(float(hit.fused_score or hit.raw_score) + boost, 6)

    return sorted(
        enriched_hits,
        key=lambda hit: (-float(hit.fused_score), hit.book_slug, hit.chunk_id),
    )


class LocalGraphSidecar:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._payload: dict[str, Any] | None = None
        self._compact_payload: dict[str, Any] | None = None
        self._book_index: dict[str, dict[str, Any]] | None = None
        self._relation_index: dict[str, list[dict[str, Any]]] | None = None
        self._allow_full_payload_load: bool | None = None
        self._payload_skip_reason = ""
        self._payload_status: dict[str, Any] | None = None
        self._compact_status: dict[str, Any] | None = None

    def _should_allow_full_payload_load(self) -> bool:
        if self._allow_full_payload_load is not None:
            return self._allow_full_payload_load
        try:
            sidecar_size = self.settings.graph_sidecar_path.stat().st_size
        except OSError:
            self._allow_full_payload_load = True
            self._payload_skip_reason = ""
            return True
        if sidecar_size > LOCAL_SIDECAR_EAGER_LOAD_MAX_BYTES:
            self._allow_full_payload_load = False
            self._payload_skip_reason = f"sidecar_eager_load_skipped:file_too_large:{sidecar_size}"
            return False
        self._allow_full_payload_load = True
        self._payload_skip_reason = ""
        return True

    def _payload_bypass_reason(self) -> str:
        self._should_allow_full_payload_load()
        return self._payload_skip_reason

    def _load_payload(self) -> dict[str, Any]:
        if not self._should_allow_full_payload_load():
            return {}
        if not bool(self._load_payload_status().get("ready")):
            return {}
        if self._payload is None:
            self._payload = _safe_read_json(self.settings.graph_sidecar_path)
        return self._payload

    def _load_compact_payload(self) -> dict[str, Any]:
        if not bool(self._load_compact_status().get("ready")):
            return {}
        if self._compact_payload is None:
            self._compact_payload = _safe_read_json(self.settings.graph_sidecar_compact_path)
        return self._compact_payload

    def _load_payload_status(self) -> dict[str, Any]:
        if self._payload_status is None:
            self._payload_status = graph_sidecar_artifact_status(self.settings)
        return self._payload_status

    def _load_compact_status(self) -> dict[str, Any]:
        if self._compact_status is None:
            self._compact_status = graph_sidecar_compact_artifact_status(self.settings)
        return self._compact_status

    def _relation_summary_payload(self) -> dict[str, Any]:
        compact_payload = self._load_compact_payload()
        if compact_payload:
            return compact_payload
        return self._load_payload()

    def _load_book_index(self) -> dict[str, dict[str, Any]]:
        if self._book_index is not None:
            return self._book_index
        index = _book_index_from_playbook_documents(self.settings.retrieval_playbook_documents_path)
        if not index:
            index = _book_index_from_sidecar_payload(self._load_compact_payload())
        if not index:
            index = _book_index_from_sidecar_payload(self._load_payload())
        self._book_index = index
        return index

    def _load_relation_index(self) -> dict[str, list[dict[str, Any]]]:
        if self._relation_index is not None:
            return self._relation_index
        self._relation_index = _relation_index_from_sidecar_payload(self._load_compact_payload())
        if self._relation_index:
            return self._relation_index
        if not self._should_allow_full_payload_load():
            self._relation_index = {}
            return self._relation_index
        self._relation_index = _relation_index_from_sidecar_payload(self._load_payload())
        return self._relation_index

    def _fallback_relations(
        self,
        *,
        hit: RetrievalHit,
        hits: list[RetrievalHit],
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        derived_from_book_slug = str(metadata.get("derived_from_book_slug") or "").strip()
        if derived_from_book_slug:
            relations.append(
                {
                    "type": "derived_from_book",
                    "target_book_slug": derived_from_book_slug,
                    "signal_values": [derived_from_book_slug],
                    "weight": 1,
                }
            )
        for other in hits:
            if other.chunk_id == hit.chunk_id:
                continue
            if other.book_slug in GARBAGE_RELATION_SLUGS:
                continue
            if other.book_slug == hit.book_slug:
                relations.append(
                    {
                        "type": "same_book",
                        "target_book_slug": other.book_slug,
                        "target_chunk_id": other.chunk_id,
                        "signal_values": [],
                        "weight": 1,
                    }
                )
            elif other.source_collection == hit.source_collection and hit.source_collection:
                relations.append(
                    {
                        "type": "shared_collection",
                        "target_book_slug": other.book_slug,
                        "target_chunk_id": other.chunk_id,
                        "source_collection": hit.source_collection,
                        "signal_values": [hit.source_collection],
                        "weight": 1,
                    }
                )
        return relations

    def build_payload(
        self,
        *,
        query: str,
        hits: list[RetrievalHit],
        context: SessionContext | None,
        fallback_reason: str = "",
    ) -> dict[str, Any]:
        del query, context
        relation_summary_payload = self._relation_summary_payload()
        book_index = self._load_book_index()
        relation_index = self._load_relation_index()
        resolved_fallback_reason = _join_fallback_reasons(fallback_reason, self._payload_bypass_reason())
        graph_hits: list[dict[str, Any]] = []
        relation_count = 0
        for hit in hits:
            metadata = book_index.get(hit.book_slug, {})
            relations = list(relation_index.get(hit.book_slug, []))
            if not relations:
                relations = self._fallback_relations(hit=hit, hits=hits, metadata=metadata)
            provenance = {
                "viewer_path": hit.viewer_path,
                "source_url": hit.source_url,
                "section_path": list(hit.section_path),
                "source_collection": hit.source_collection,
                "semantic_role": hit.semantic_role,
                "block_kinds": list(hit.block_kinds),
                "source_type": str(metadata.get("source_type") or hit.source_type),
                "source_lane": str(metadata.get("source_lane") or hit.source_lane),
                "derived_from_book_slug": str(metadata.get("derived_from_book_slug") or ""),
                "topic_key": str(metadata.get("topic_key") or ""),
            }
            graph_hits.append(
                {
                    "chunk_id": hit.chunk_id,
                    "book_slug": hit.book_slug,
                    "relations": relations,
                    "provenance": provenance,
                }
            )
            relation_count += len(relations)
        return {
            **_payload_graph_flags(enabled=True, adapter_mode="local_sidecar"),
            "configured_mode": _resolved_mode(self.settings),
            "endpoint": self.settings.graph_endpoint or self.settings.graph_uri,
            "sidecar_path": str(self.settings.graph_sidecar_path),
            "fallback_reason": resolved_fallback_reason,
            "summary": {
                "hit_count": len(graph_hits),
                "relation_count": relation_count,
                "provenance_count": len(graph_hits),
                "sidecar_relation_count": int(relation_summary_payload.get("relation_count", 0) or 0),
            },
            "hits": graph_hits,
        }


class RetrievalGraphRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.local_sidecar = LocalGraphSidecar(settings)
        self._backend_health_cache: dict[str, tuple[float, bool, str]] = {}

    def _disabled_payload(self) -> dict[str, Any]:
        return {
            **_payload_graph_flags(enabled=False, adapter_mode="disabled"),
            "configured_mode": _resolved_mode(self.settings),
            "endpoint": self.settings.graph_endpoint or self.settings.graph_uri,
            "sidecar_path": str(self.settings.graph_sidecar_path),
            "fallback_reason": "graph_disabled",
            "summary": {
                "hit_count": 0,
                "relation_count": 0,
                "provenance_count": 0,
            },
            "hits": [],
        }

    def skipped_payload(self, *, reason: str) -> dict[str, Any]:
        graph_enabled = _graph_enabled(self.settings)
        adapter_mode = "skipped" if graph_enabled else "disabled"
        fallback_reason = reason if graph_enabled else "graph_disabled"
        return {
            **_payload_graph_flags(enabled=graph_enabled, adapter_mode=adapter_mode),
            "configured_mode": _resolved_mode(self.settings),
            "endpoint": self.settings.graph_endpoint or self.settings.graph_uri,
            "sidecar_path": str(self.settings.graph_sidecar_path),
            "fallback_reason": fallback_reason,
            "summary": {
                "hit_count": 0,
                "relation_count": 0,
                "provenance_count": 0,
            },
            "hits": [],
        }

    def _backend_cache_key(self, mode: str) -> str:
        if mode == "neo4j":
            return "|".join(
                (
                    mode,
                    self.settings.graph_uri,
                    self.settings.graph_database,
                    self.settings.graph_username,
                )
            )
        if mode == "remote":
            return f"{mode}|{self.settings.graph_endpoint}"
        return mode

    def _cached_backend_health(self, mode: str) -> tuple[bool, str] | None:
        cache_key = self._backend_cache_key(mode)
        cached = self._backend_health_cache.get(cache_key)
        if cached is None:
            return None
        checked_at, healthy, reason = cached
        if (time.monotonic() - checked_at) > GRAPH_HEALTH_CACHE_TTL_SECONDS:
            self._backend_health_cache.pop(cache_key, None)
            return None
        return healthy, reason

    def _remember_backend_health(self, mode: str, *, healthy: bool, reason: str = "") -> tuple[bool, str]:
        self._backend_health_cache[self._backend_cache_key(mode)] = (
            time.monotonic(),
            healthy,
            reason,
        )
        return healthy, reason

    def _neo4j_backend_health(self) -> tuple[bool, str]:
        cached = self._cached_backend_health("neo4j")
        if cached is not None:
            return cached
        if GraphDatabase is None:
            return self._remember_backend_health(
                "neo4j",
                healthy=False,
                reason="neo4j driver is not installed",
            )
        host_port = _neo4j_host_port(self.settings.graph_uri)
        if host_port is None:
            return self._remember_backend_health(
                "neo4j",
                healthy=False,
                reason="graph uri is invalid",
            )
        healthy, reason = _probe_tcp_endpoint(
            host_port[0],
            host_port[1],
            timeout_seconds=_graph_probe_timeout_seconds(self.settings),
        )
        if not healthy:
            return self._remember_backend_health(
                "neo4j",
                healthy=False,
                reason=reason,
            )
        return self._remember_backend_health("neo4j", healthy=True, reason="")

    def _remote_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.graph_api_key:
            headers["Authorization"] = f"Bearer {self.settings.graph_api_key}"
        return headers

    def _remote_payload(
        self,
        *,
        query: str,
        hits: list[RetrievalHit],
        context: SessionContext | None,
    ) -> dict[str, Any]:
        endpoint = self.settings.graph_endpoint.rstrip("/")
        if not endpoint:
            raise RuntimeError("graph endpoint is not configured")
        response = requests.post(
            f"{endpoint}/expand",
            json={
                "query": query,
                "context": context.to_dict() if context is not None else {},
                "hits": [_serialize_hit(hit) for hit in hits],
            },
            headers=self._remote_headers(),
            timeout=max(self.settings.graph_timeout_seconds, 1.0),
        )
        if not response.ok:
            raise RuntimeError(f"graph endpoint returned {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("graph endpoint returned non-object payload")
        graph_hits = payload.get("hits")
        if not isinstance(graph_hits, list):
            raise RuntimeError("graph endpoint payload is missing hits")
        return {
            **_payload_graph_flags(enabled=True, adapter_mode="remote_endpoint"),
            "configured_mode": _resolved_mode(self.settings),
            "endpoint": endpoint,
            "sidecar_path": str(self.settings.graph_sidecar_path),
            "fallback_reason": "",
            "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {"hit_count": len(graph_hits)},
            "hits": graph_hits,
        }

    def _neo4j_payload(
        self,
        *,
        query: str,
        hits: list[RetrievalHit],
        context: SessionContext | None,
    ) -> dict[str, Any]:
        del query, context
        if GraphDatabase is None:
            raise RuntimeError("neo4j driver is not installed")
        if not self.settings.graph_uri:
            raise RuntimeError("graph uri is not configured")
        book_slugs = sorted({hit.book_slug for hit in hits if hit.book_slug})
        if not book_slugs:
            return {
                **_payload_graph_flags(enabled=True, adapter_mode="neo4j"),
                "configured_mode": _resolved_mode(self.settings),
                "endpoint": self.settings.graph_uri,
                "sidecar_path": str(self.settings.graph_sidecar_path),
                "fallback_reason": "",
                "summary": {"hit_count": 0, "relation_count": 0, "provenance_count": 0},
                "hits": [],
            }
        driver = GraphDatabase.driver(
            self.settings.graph_uri,
            auth=(
                self.settings.graph_username or None,
                self.settings.graph_password or None,
            ),
        )
        relation_rows: list[dict[str, Any]] = []
        try:  # pragma: no cover - exercised only when neo4j is configured
            with driver.session(database=self.settings.graph_database or None) as session:
                cursor = session.run(
                    """
                    UNWIND $book_slugs AS slug
                    MATCH (source:Playbook {app_id: $app_id, pack_id: $pack_id, book_slug: slug})-[rel:RELATED]-(target:Playbook {app_id: $app_id, pack_id: $pack_id})
                    RETURN source.book_slug AS source_book_slug,
                           target.book_slug AS target_book_slug,
                           coalesce(rel.relation_type, type(rel)) AS relation_type,
                           coalesce(rel.signal_value, '') AS signal_value,
                           coalesce(rel.weight, 1) AS weight
                    """,
                    app_id=self.settings.app_id,
                    pack_id=self.settings.active_pack_id,
                    book_slugs=book_slugs,
                )
                for row in cursor:
                    relation_rows.append(
                        {
                            "source_book_slug": str(row.get("source_book_slug") or "").strip(),
                            "target_book_slug": str(row.get("target_book_slug") or "").strip(),
                            "relation_types": [str(row.get("relation_type") or "related").strip()],
                            "signal_values": [
                                str(row.get("signal_value") or "").strip()
                            ]
                            if str(row.get("signal_value") or "").strip()
                            else [],
                            "weight": int(row.get("weight") or 1),
                        }
                    )
        finally:
            driver.close()

        local_book_index = self.local_sidecar._load_book_index()
        relation_index = _relation_index_from_sidecar_payload({"relations": relation_rows})
        graph_hits: list[dict[str, Any]] = []
        relation_count = 0
        for hit in hits:
            metadata = local_book_index.get(hit.book_slug, {})
            relations = list(relation_index.get(hit.book_slug, []))
            if not relations:
                relations = self.local_sidecar._fallback_relations(hit=hit, hits=hits, metadata=metadata)
            graph_hits.append(
                {
                    "chunk_id": hit.chunk_id,
                    "book_slug": hit.book_slug,
                    "relations": relations,
                    "provenance": {
                        "viewer_path": hit.viewer_path,
                        "source_url": hit.source_url,
                        "section_path": list(hit.section_path),
                        "source_collection": hit.source_collection,
                        "semantic_role": hit.semantic_role,
                        "block_kinds": list(hit.block_kinds),
                        "source_type": str(metadata.get("source_type") or hit.source_type),
                        "source_lane": str(metadata.get("source_lane") or hit.source_lane),
                        "derived_from_book_slug": str(metadata.get("derived_from_book_slug") or ""),
                        "topic_key": str(metadata.get("topic_key") or ""),
                    },
                }
            )
            relation_count += len(relations)
        return {
            **_payload_graph_flags(enabled=True, adapter_mode="neo4j"),
            "configured_mode": _resolved_mode(self.settings),
            "endpoint": self.settings.graph_uri,
            "sidecar_path": str(self.settings.graph_sidecar_path),
            "fallback_reason": "",
            "summary": {
                "hit_count": len(graph_hits),
                "relation_count": relation_count,
                "provenance_count": len(graph_hits),
            },
            "hits": graph_hits,
        }

    def enrich_hits(
        self,
        *,
        query: str,
        hits: list[RetrievalHit],
        context: SessionContext | None,
        trace_callback=None,
    ) -> tuple[list[RetrievalHit], dict[str, Any]]:
        if not _graph_enabled(self.settings):
            return hits, self._disabled_payload()

        _emit_trace_event(
            trace_callback,
            step="graph_expand",
            label="관계/근거 그래프 조회 중",
            status="running",
        )
        started_at = time.perf_counter()
        mode = _resolved_mode(self.settings)
        fallback_reason = ""
        try:
            if mode == "neo4j":
                neo4j_ready, neo4j_reason = self._neo4j_backend_health()
                if not neo4j_ready:
                    payload = self.local_sidecar.build_payload(
                        query=query,
                        hits=hits,
                        context=context,
                        fallback_reason=f"neo4j_unhealthy:{neo4j_reason}",
                    )
                else:
                    payload = self._neo4j_payload(query=query, hits=hits, context=context)
                    self._remember_backend_health("neo4j", healthy=True, reason="")
            elif mode == "remote":
                payload = self._remote_payload(query=query, hits=hits, context=context)
            else:
                payload = self.local_sidecar.build_payload(query=query, hits=hits, context=context)
        except Exception as exc:  # noqa: BLE001
            fallback_label = {
                "remote": "remote_endpoint_failed",
                "neo4j": "neo4j_failed",
            }.get(mode, f"{mode}_failed")
            fallback_reason = f"{fallback_label}:{exc}"
            if mode == "neo4j":
                self._remember_backend_health("neo4j", healthy=False, reason=str(exc))
            payload = self.local_sidecar.build_payload(
                query=query,
                hits=hits,
                context=context,
                fallback_reason=fallback_reason,
            )
        duration_ms = _duration_ms(started_at)
        payload["duration_ms"] = duration_ms
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        _emit_trace_event(
            trace_callback,
            step="graph_expand",
            label="관계/근거 그래프 조회 완료",
            status="done",
            detail=f"{payload.get('adapter_mode', 'unknown')} · relation {int(summary.get('relation_count') or 0)}",
            duration_ms=duration_ms,
            meta={
                "adapter_mode": payload.get("adapter_mode", ""),
                "fallback_reason": payload.get("fallback_reason", ""),
                "hit_count": int(summary.get("hit_count") or 0),
            },
        )
        return _apply_graph_payload(self.settings, hits=hits, payload=payload), payload

    def expand(
        self,
        *,
        query: str,
        hits: list[RetrievalHit],
        context: SessionContext | None,
        trace_callback=None,
    ) -> dict[str, Any]:
        _, payload = self.enrich_hits(
            query=query,
            hits=hits,
            context=context,
            trace_callback=trace_callback,
        )
        return payload
