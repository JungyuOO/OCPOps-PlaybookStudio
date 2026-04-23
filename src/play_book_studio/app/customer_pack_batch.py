from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.app.intake_api import ingest_customer_pack, normalize_customer_pack_draft
from play_book_studio.intake import CustomerPackDraftStore


_MATERIAL_FOLDER_MARKER = "01_검토대기_플레이북재료"
_EXCLUDED_FOLDER_MARKERS = {"99_검토대기_비재료"}
_LOCKFILE_PREFIX = "~$"
_SUPPORTED_EXTENSIONS = {".ppt", ".pptx"}


@dataclass(slots=True)
class CustomerPackBatchSource:
    source_path: Path
    source_name: str
    title: str
    fingerprint: str
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "source_name": self.source_name,
            "title": self.title,
            "fingerprint": self.fingerprint,
            "aliases": list(self.aliases),
        }


def _compute_file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _is_supported_customer_pack_material(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith(_LOCKFILE_PREFIX):
        return False
    if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        return False
    parts = set(path.parts)
    if any(marker in parts for marker in _EXCLUDED_FOLDER_MARKERS):
        return False
    return _MATERIAL_FOLDER_MARKER in parts


def discover_customer_pack_batch_sources(materials_root: Path) -> list[CustomerPackBatchSource]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(materials_root.rglob("*")):
        if not _is_supported_customer_pack_material(path):
            continue
        fingerprint = _compute_file_fingerprint(path)
        grouped.setdefault(fingerprint, []).append(path)

    sources: list[CustomerPackBatchSource] = []
    for fingerprint, paths in sorted(grouped.items(), key=lambda item: str(item[1][0]).lower()):
        primary = sorted(paths, key=lambda candidate: str(candidate).lower())[0]
        aliases = tuple(str(path) for path in sorted(paths, key=lambda candidate: str(candidate).lower())[1:])
        sources.append(
            CustomerPackBatchSource(
                source_path=primary,
                source_name=primary.name,
                title=primary.stem,
                fingerprint=fingerprint,
                aliases=aliases,
            )
        )
    return sources


def _normalized_path_text(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve())
    except Exception:  # noqa: BLE001
        return raw


def find_existing_customer_pack_draft(
    root_dir: Path,
    *,
    source_path: Path,
    fingerprint: str,
) -> dict[str, Any] | None:
    normalized_source_path = _normalized_path_text(str(source_path))
    for record in CustomerPackDraftStore(root_dir).list():
        record_fingerprint = str(getattr(record, "source_fingerprint", "") or "").strip()
        if fingerprint and record_fingerprint == fingerprint:
            return {"record": record, "match_reason": "source_fingerprint"}
        request_uri = _normalized_path_text(str(getattr(record.request, "uri", "") or ""))
        if normalized_source_path and request_uri == normalized_source_path:
            return {"record": record, "match_reason": "request_uri"}
    return None


def _ready_status(value: bool) -> str:
    return "ready" if value else "blocked"


def _surface_gate_ready(
    surface_gates: dict[str, Any],
    *,
    gate_key: str,
    fallback: bool,
) -> bool:
    explicit = surface_gates.get(gate_key)
    if explicit is None:
        return fallback
    return bool(explicit)


def _surface_gate_status(
    surface_gates: dict[str, Any],
    *,
    status_key: str,
    fallback_ready: bool,
) -> str:
    explicit = str(surface_gates.get(status_key) or "").strip()
    if explicit:
        return explicit
    return _ready_status(fallback_ready)


def _material_scope(materials_root: Path, sources: list[CustomerPackBatchSource]) -> dict[str, Any]:
    alias_file_count = sum(len(source.aliases) for source in sources)
    material_file_count = len(sources) + alias_file_count
    return {
        "scope_kind": "customer_pack_material_only_batch",
        "materials_root": str(materials_root),
        "material_only": True,
        "material_folder_marker": _MATERIAL_FOLDER_MARKER,
        "excluded_folder_markers": sorted(_EXCLUDED_FOLDER_MARKERS),
        "supported_extensions": sorted(_SUPPORTED_EXTENSIONS),
        "deduplicated_source_count": len(sources),
        "material_file_count": material_file_count,
        "alias_file_count": alias_file_count,
    }


def _result_summary(
    *,
    draft_id: str,
    source: CustomerPackBatchSource,
    match_reason: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    private_corpus = dict(result.get("private_corpus") or {})
    grade_gate = dict(private_corpus.get("grade_gate") or {})
    surface_gates = dict(grade_gate.get("surface_gates") or {})
    read_ready = bool(private_corpus.get("read_ready"))
    publish_ready = bool(private_corpus.get("publish_ready"))
    retrieval_ready = bool(private_corpus.get("retrieval_ready"))
    wikibook_ready = _surface_gate_ready(
        surface_gates,
        gate_key="wikibook_ready",
        fallback=read_ready and publish_ready,
    )
    llmwiki_ready = _surface_gate_ready(
        surface_gates,
        gate_key="llmwiki_ready",
        fallback=retrieval_ready,
    )
    chat_ready = retrieval_ready and str(result.get("private_corpus_status") or "").strip() == "ready"
    return {
        "draft_id": draft_id,
        "source_path": str(source.source_path),
        "source_name": source.source_name,
        "title": source.title,
        "fingerprint": source.fingerprint,
        "aliases": list(source.aliases),
        "match_reason": match_reason,
        "status": str(result.get("status") or ""),
        "publication_state": str(result.get("publication_state") or ""),
        "surface_kind": str(result.get("surface_kind") or ""),
        "source_unit_count": int(result.get("source_unit_count") or 0),
        "slide_packet_count": int(result.get("slide_packet_count") or 0),
        "private_corpus_status": str(result.get("private_corpus_status") or ""),
        "private_corpus_publication_state": str(private_corpus.get("publication_state") or ""),
        "quality_status": str(private_corpus.get("quality_status") or ""),
        "shared_grade": str(private_corpus.get("shared_grade") or ""),
        "read_ready": read_ready,
        "publish_ready": publish_ready,
        "retrieval_ready": retrieval_ready,
        "wikibook_ready": wikibook_ready,
        "wikibook_status": _surface_gate_status(
            surface_gates,
            status_key="wikibook_status",
            fallback_ready=wikibook_ready,
        ),
        "llmwiki_ready": llmwiki_ready,
        "llmwiki_status": _surface_gate_status(
            surface_gates,
            status_key="llmwiki_status",
            fallback_ready=llmwiki_ready,
        ),
        "chat_ready": chat_ready,
        "chat_status": _ready_status(chat_ready),
    }


def run_customer_pack_material_batch(
    root_dir: Path,
    *,
    materials_root: Path,
    approval_state: str = "approved",
    publication_state: str = "active",
) -> dict[str, Any]:
    sources = discover_customer_pack_batch_sources(materials_root)
    scope = _material_scope(materials_root, sources)
    processed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for source in sources:
        existing = find_existing_customer_pack_draft(
            root_dir,
            source_path=source.source_path,
            fingerprint=source.fingerprint,
        )
        try:
            if existing is not None:
                record = existing["record"]
                result = normalize_customer_pack_draft(
                    root_dir,
                    {
                        "draft_id": str(record.draft_id),
                        "approval_state": approval_state,
                        "publication_state": publication_state,
                    },
                )
                match_reason = str(existing["match_reason"])
                draft_id = str(record.draft_id)
            else:
                result = ingest_customer_pack(
                    root_dir,
                    {
                        "source_type": "pptx",
                        "uri": str(source.source_path),
                        "title": source.title,
                        "approval_state": approval_state,
                        "publication_state": publication_state,
                    },
                )
                match_reason = "new_ingest"
                draft_id = str(result["draft_id"])
            processed.append(
                _result_summary(
                    draft_id=draft_id,
                    source=source,
                    match_reason=match_reason,
                    result=result,
                )
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {
                    **source.to_dict(),
                    "error": str(exc),
                }
            )

    summary = {
        "source_count": len(sources),
        "material_file_count": int(scope["material_file_count"]),
        "alias_file_count": int(scope["alias_file_count"]),
        "processed_count": len(processed),
        "failed_count": len(failures),
        "ready_count": sum(1 for item in processed if item["status"] == "normalized"),
        "publish_ready_count": sum(1 for item in processed if item["publish_ready"]),
        "retrieval_ready_count": sum(1 for item in processed if item["retrieval_ready"]),
        "wikibook_ready_count": sum(1 for item in processed if item["wikibook_ready"]),
        "llmwiki_ready_count": sum(1 for item in processed if item["llmwiki_ready"]),
        "chat_ready_count": sum(1 for item in processed if item["chat_ready"]),
        "customer_llmwiki_ready": bool(processed) and not failures and all(
            item["status"] == "normalized" and item["llmwiki_ready"] and item["chat_ready"]
            for item in processed
        ),
    }
    return {
        "materials_root": str(materials_root),
        "scope": scope,
        "sources": [source.to_dict() for source in sources],
        "processed": processed,
        "failures": failures,
        "summary": summary,
    }


def write_customer_pack_material_batch_report(
    root_dir: Path,
    *,
    materials_root: Path,
    output_path: Path,
    approval_state: str = "approved",
    publication_state: str = "active",
) -> tuple[Path, dict[str, Any]]:
    report = run_customer_pack_material_batch(
        root_dir,
        materials_root=materials_root,
        approval_state=approval_state,
        publication_state=publication_state,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, report


__all__ = [
    "CustomerPackBatchSource",
    "discover_customer_pack_batch_sources",
    "find_existing_customer_pack_draft",
    "run_customer_pack_material_batch",
    "write_customer_pack_material_batch_report",
]
