from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.app.server_routes_viewer import resolve_viewer_html
from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.localization_quality import build_official_ko_localization_audit
from play_book_studio.ingestion.official_figures import build_official_figure_relation_sidecars
from play_book_studio.source_provenance import source_fingerprint_for_entry, source_provenance_payload, source_ref_for_entry


PORTABLE_JSON_RELATIVE_PATHS = (
    "data/wiki_runtime_books/active_manifest.json",
    "data/wiki_runtime_books/full_rebuild_manifest.json",
    "data/gold_candidate_books/full_rebuild_manifest.json",
    "manifests/ocp420_source_first_full_rebuild_manifest.json",
    "data/wiki_relations/figure_assets.json",
)
ARTIFACT_MANIFEST_RELATIVE_PATH = "manifests/ocp420_gold_artifacts_manifest.json"
ONE_CLICK_REPORT_RELATIVE_PATH = "reports/build_logs/ocp420_one_click_runtime_report.json"
OFFICIAL_GOLD_REBUILD_COMMAND = "python -m play_book_studio.cli official-gold-rebuild"
MANIFEST_ONLY_LARGE_JSONL_RELATIVE_PATHS = frozenset(
    {
        "artifacts/official_lane/repo_wide_official_source/chunks.jsonl",
        "artifacts/official_lane/repo_wide_official_source/bm25_corpus.jsonl",
        "artifacts/official_lane/repo_wide_official_source/normalized_docs.jsonl",
        "data/gold_corpus_ko/chunks.jsonl",
        "data/gold_corpus_ko/bm25_corpus.jsonl",
    }
)
LOCAL_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
SECTION_CARD_RE = re.compile(r'class="[^"]*\bsection-card\b')
CODE_BLOCK_RE = re.compile(r'class="[^"]*\bcode-block\b')
FIGURE_RE = re.compile(r"<figure\b", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _repo_ref(root_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root_dir), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _git_refs(root_dir: Path) -> dict[str, str]:
    return {
        "branch": _repo_ref(root_dir, "branch", "--show-current"),
        "head": _repo_ref(root_dir, "rev-parse", "HEAD"),
        "base_ref": "origin/main",
        "base_sha": _repo_ref(root_dir, "merge-base", "HEAD", "origin/main"),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for _ in handle:
            count += 1
    return count


def _relative_path(root_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _artifact_entry(root_dir: Path, path: Path, *, producer_command: str) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    relative_path = _relative_path(root_dir, path)
    sha256 = _sha256_file(path) if exists else ""
    manifest_only = (
        relative_path in MANIFEST_ONLY_LARGE_JSONL_RELATIVE_PATHS
        or (
            relative_path.startswith("artifacts/official_lane/")
            and relative_path.endswith(".jsonl")
        )
    )
    return {
        "path": relative_path,
        "restore_path": relative_path,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "sha256": sha256,
        "line_count": _line_count(path) if exists and path.suffix == ".jsonl" else None,
        "producer_command": producer_command,
        "restore_command": producer_command,
        "artifact_ref": f"sha256:{sha256}" if sha256 else "",
        "storage_policy": "manifest_only_large_jsonl" if manifest_only else "tracked_or_small_artifact",
        "git_policy": "do_not_track_payload" if manifest_only else "track_or_ignore_by_size_policy",
    }


def _artifact_manifest(root_dir: Path) -> dict[str, Any]:
    settings = load_settings(root_dir)
    artifacts = [
        _artifact_entry(root_dir, settings.chunks_path, producer_command=OFFICIAL_GOLD_REBUILD_COMMAND),
        _artifact_entry(root_dir, settings.bm25_corpus_path, producer_command=OFFICIAL_GOLD_REBUILD_COMMAND),
        _artifact_entry(root_dir, settings.playbook_documents_path, producer_command=OFFICIAL_GOLD_REBUILD_COMMAND),
        _artifact_entry(root_dir, settings.normalized_docs_path, producer_command=OFFICIAL_GOLD_REBUILD_COMMAND),
        _artifact_entry(root_dir, settings.graph_sidecar_compact_path, producer_command="play-book-studio graph-compact"),
        _artifact_entry(root_dir, root_dir / "data/wiki_relations/figure_assets.json", producer_command="official source-first figure extraction"),
        _artifact_entry(root_dir, root_dir / "data/wiki_relations/figure_section_index.json", producer_command="official source-first figure extraction"),
        _artifact_entry(root_dir, root_dir / "data/wiki_runtime_books/active_manifest.json", producer_command="official runtime switch"),
        _artifact_entry(root_dir, root_dir / "data/wiki_runtime_books/full_rebuild_manifest.json", producer_command="official source-first runtime materialization"),
    ]
    return {
        "generated_at_utc": _utc_now(),
        "policy": {
            "large_jsonl": "do_not_commit_payload_without_lfs_or_external_artifact_store",
            "tracked_truth": "track manifests, hashes, and producer commands",
            "portable_paths": "repo-relative paths only in rebuild/runtime manifests",
            "manifest_only_paths": sorted(MANIFEST_ONLY_LARGE_JSONL_RELATIVE_PATHS),
        },
        "artifacts": artifacts,
    }


def write_artifact_manifest(root_dir: Path, output_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    target = output_path or root_dir / ARTIFACT_MANIFEST_RELATIVE_PATH
    payload = _artifact_manifest(root_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload


def _git_tracked_paths(root_dir: Path, relative_paths: set[str]) -> set[str]:
    if not relative_paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root_dir), "ls-files", "--", *sorted(relative_paths)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    return {
        line.strip().replace("\\", "/")
        for line in str(result.stdout or "").splitlines()
        if line.strip()
    }


def _large_jsonl_artifact_policy(
    root_dir: Path,
    artifact_manifest: dict[str, Any],
    *,
    tracked_paths: set[str] | None = None,
) -> dict[str, Any]:
    artifacts = [
        dict(item)
        for item in artifact_manifest.get("artifacts", [])
        if isinstance(item, dict)
    ]
    manifest_only_paths = {
        str(item.get("path") or "").replace("\\", "/")
        for item in artifacts
        if str(item.get("git_policy") or "") == "do_not_track_payload"
    }
    tracked = (
        {path.replace("\\", "/") for path in tracked_paths}
        if tracked_paths is not None
        else _git_tracked_paths(root_dir, manifest_only_paths)
    )
    tracked_manifest_only_paths = sorted(manifest_only_paths & tracked)
    missing_contract_paths = sorted(
        str(item.get("path") or "").replace("\\", "/")
        for item in artifacts
        if str(item.get("git_policy") or "") == "do_not_track_payload"
        and (
            not str(item.get("sha256") or "").strip()
            or not str(item.get("restore_path") or "").strip()
            or not str(item.get("producer_command") or "").strip()
            or not str(item.get("restore_command") or "").strip()
        )
    )
    return {
        "status": "ok" if not tracked_manifest_only_paths and not missing_contract_paths else "fail",
        "manifest_only_paths": sorted(manifest_only_paths),
        "tracked_manifest_only_paths": tracked_manifest_only_paths,
        "missing_contract_paths": missing_contract_paths,
    }


def _portable_path_value(root_dir: Path, value: str) -> str:
    raw = str(value or "")
    normalized = raw.replace("\\", "/")
    root_posix = root_dir.resolve().as_posix()
    if normalized.startswith(root_posix + "/"):
        return normalized[len(root_posix) + 1 :]
    markers = (
        "data/wiki_runtime_books",
        "data/gold_candidate_books",
        "data/wiki_assets",
        "data/wiki_relations",
        "manifests",
        "tmp_source/openshift-docs-enterprise-4.20",
    )
    for marker in markers:
        marker_root = marker.rstrip("/")
        if normalized.endswith(marker_root):
            return marker_root
        marker_prefix = marker_root + "/"
        if marker_prefix in normalized:
            tail = normalized.split(marker_prefix, 1)[1].strip("/")
            return marker_prefix + tail if tail else marker_root
    return raw


def _make_payload_portable(root_dir: Path, value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        changed = 0
        output: dict[str, Any] = {}
        for key, item in value.items():
            next_item, item_changed = _make_payload_portable(root_dir, item)
            output[key] = next_item
            changed += item_changed
        return output, changed
    if isinstance(value, list):
        changed = 0
        output_list = []
        for item in value:
            next_item, item_changed = _make_payload_portable(root_dir, item)
            output_list.append(next_item)
            changed += item_changed
        return output_list, changed
    if isinstance(value, str):
        portable = _portable_path_value(root_dir, value)
        return portable, 1 if portable != value else 0
    return value, 0


def repair_portable_json_paths(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for relative_path in PORTABLE_JSON_RELATIVE_PATHS:
        path = root_dir / relative_path
        if not path.exists():
            results.append({"path": relative_path, "status": "missing", "changed_count": 0})
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        repaired, changed_count = _make_payload_portable(root_dir, payload)
        if changed_count:
            path.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append({"path": relative_path, "status": "ok", "changed_count": changed_count})
    return results


def _walk_strings(value: Any, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        rows: list[tuple[str, str]] = []
        for key, item in value.items():
            rows.extend(_walk_strings(item, f"{path}.{key}"))
        return rows
    if isinstance(value, list):
        rows = []
        for index, item in enumerate(value):
            rows.extend(_walk_strings(item, f"{path}[{index}]"))
        return rows
    if isinstance(value, str):
        return [(path, value)]
    return []


def _portable_path_findings(root_dir: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for relative_path in PORTABLE_JSON_RELATIVE_PATHS:
        path = root_dir / relative_path
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for json_path, value in _walk_strings(payload):
            normalized = value.replace("\\", "/")
            if LOCAL_ABSOLUTE_PATH_RE.match(value) or "ocp-play-studio/ocp-play-studio/" in normalized:
                findings.append(
                    {
                        "file": relative_path,
                        "json_path": json_path,
                        "value": value,
                    }
                )
    return {
        "status": "ok" if not findings else "fail",
        "absolute_or_stale_path_count": len(findings),
        "examples": findings[:10],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_entries(path: Path) -> list[dict[str, Any]]:
    payload = _safe_read_json(path)
    entries = payload.get("entries")
    return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []


def _official_catalog_path(root_dir: Path) -> Path:
    settings = load_settings(root_dir)
    return root_dir / "manifests" / settings.active_pack.source_catalog_name


def _official_catalog_slugs(root_dir: Path) -> set[str]:
    return {
        str(item.get("book_slug") or "").strip()
        for item in _manifest_entries(_official_catalog_path(root_dir))
        if str(item.get("book_slug") or "").strip()
    }


def _row_source_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("source_metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _playbook_slugs(playbook_rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("book_slug") or "").strip()
        for row in playbook_rows
        if str(row.get("book_slug") or "").strip()
    }


def _chunk_slugs(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("book_slug") or "").strip()
        for row in rows
        if str(row.get("book_slug") or "").strip()
    }


def _runtime_manifest_slugs(root_dir: Path) -> set[str]:
    active_manifest_path = root_dir / "data/wiki_runtime_books/active_manifest.json"
    return {
        str(item.get("slug") or item.get("book_slug") or "").strip()
        for item in _manifest_entries(active_manifest_path)
        if str(item.get("slug") or item.get("book_slug") or "").strip()
    }


def _official_catalog_coverage(
    root_dir: Path,
    *,
    chunks_rows: list[dict[str, Any]],
    bm25_rows: list[dict[str, Any]],
    playbook_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    catalog_slugs = _official_catalog_slugs(root_dir)
    playbook_book_slugs = _playbook_slugs(playbook_rows)
    chunk_book_slugs = _chunk_slugs(chunks_rows)
    bm25_book_slugs = _chunk_slugs(bm25_rows)
    runtime_book_slugs = _runtime_manifest_slugs(root_dir)
    return {
        "catalog_count": len(catalog_slugs),
        "playbook_book_count": len(playbook_book_slugs),
        "chunk_book_count": len(chunk_book_slugs),
        "bm25_book_count": len(bm25_book_slugs),
        "active_runtime_book_count": len(runtime_book_slugs),
        "missing_playbook_slugs": sorted(catalog_slugs - playbook_book_slugs),
        "missing_chunk_slugs": sorted(catalog_slugs - chunk_book_slugs),
        "missing_bm25_slugs": sorted(catalog_slugs - bm25_book_slugs),
        "missing_active_runtime_slugs": sorted(catalog_slugs - runtime_book_slugs),
    }


def _runtime_entry_from_playbook(
    root_dir: Path,
    *,
    row: dict[str, Any],
    source_entry: dict[str, Any],
    source_manifest_path: Path,
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    slug = str(row.get("book_slug") or "").strip()
    title = str(row.get("title") or source_entry.get("title") or slug).strip()
    source_metadata = _row_source_metadata(row)
    combined = {**source_entry, **source_metadata}
    if not combined.get("source_url"):
        combined["source_url"] = str(row.get("source_uri") or "")
    if not combined.get("viewer_path"):
        combined["viewer_path"] = settings.viewer_path_template.format(slug=slug)
    provenance = source_provenance_payload(combined)
    runtime_path = f"data/wiki_runtime_books/full_rebuild/{slug}.md"
    source_candidate_path = f"data/gold_candidate_books/full_rebuild/{slug}.md"
    review_status = str(row.get("review_status") or source_metadata.get("review_status") or source_entry.get("review_status") or "").strip()
    translation_status = str(row.get("translation_status") or row.get("translation_stage") or source_entry.get("content_status") or "").strip()
    approval_state = str(source_metadata.get("approval_state") or source_entry.get("approval_state") or "").strip()
    publication_state = str(source_metadata.get("publication_state") or source_entry.get("publication_state") or "").strip()
    return {
        "slug": slug,
        "book_slug": slug,
        "title": title,
        "source_lane": str(source_metadata.get("source_lane") or source_entry.get("source_lane") or "official_ko").strip(),
        "source_type": str(source_metadata.get("source_type") or source_entry.get("source_type") or "official_doc").strip(),
        "source_ref": source_ref_for_entry(combined),
        "source_fingerprint": source_fingerprint_for_entry(combined),
        "source_repo": provenance.get("source_repo", ""),
        "source_branch": provenance.get("source_branch", ""),
        "source_binding_kind": provenance.get("source_binding_kind", ""),
        "source_relative_path": provenance.get("source_relative_path", ""),
        "source_relative_paths": provenance.get("source_relative_paths", []),
        "primary_input_kind": str(
            provenance.get("primary_input_kind")
            or source_entry.get("primary_input_kind")
            or row.get("primary_input_kind")
            or "html_single"
        ),
        "fallback_input_kind": str(
            provenance.get("fallback_input_kind")
            or source_entry.get("fallback_input_kind")
            or row.get("fallback_input_kind")
            or "html_single"
        ),
        "fallback_source_url": str(
            provenance.get("fallback_source_url")
            or source_entry.get("source_url")
            or row.get("source_uri")
            or ""
        ),
        "fallback_viewer_path": str(
            provenance.get("fallback_viewer_path")
            or source_entry.get("viewer_path")
            or settings.viewer_path_template.format(slug=slug)
        ),
        "source_candidate_path": source_candidate_path,
        "runtime_path": runtime_path,
        "promotion_strategy": "full_official_catalog_runtime",
        "source_manifest_path": _relative_path(root_dir, source_manifest_path),
        "parser_route": "canonical_playbook_document",
        "parser_backend": "playbook_ast_v1",
        "review_status": review_status,
        "approval_state": approval_state,
        "publication_state": publication_state,
        "translation_status": translation_status,
        "translation_stage": str(row.get("translation_stage") or translation_status),
        "quality_status": str(row.get("quality_status") or "").strip(),
        "quality_flags": list(row.get("quality_flags") or []),
        "updated_at": str(source_metadata.get("updated_at") or source_entry.get("updated_at") or ""),
        "rebuild_target_paths": {
            "wiki_runtime_md": runtime_path,
            "gold_candidate_md": source_candidate_path,
        },
    }


def publish_runtime_manifest_from_playbooks(
    root_dir: Path,
    *,
    source_manifest_path: Path | None = None,
    active_group: str = "full_rebuild",
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    playbook_rows = _read_jsonl(settings.playbook_documents_path)
    source_manifest = source_manifest_path or settings.source_manifest_path
    source_entries = {
        str(item.get("book_slug") or item.get("slug") or "").strip(): item
        for item in _manifest_entries(source_manifest)
        if str(item.get("book_slug") or item.get("slug") or "").strip()
    }
    entries = [
        _runtime_entry_from_playbook(
            root_dir,
            row=row,
            source_entry=source_entries.get(str(row.get("book_slug") or "").strip(), {}),
            source_manifest_path=source_manifest,
        )
        for row in playbook_rows
        if str(row.get("book_slug") or "").strip()
    ]
    entries.sort(key=lambda item: str(item.get("slug") or ""))
    generated_at = _utc_now()
    full_payload = {
        "generated_at_utc": generated_at,
        "runtime_count": len(entries),
        "promotion_group": "full_official_catalog_runtime",
        "source_strategy": "official-html-single-full-catalog",
        "source_manifest_path": _relative_path(root_dir, source_manifest),
        "entries": entries,
    }
    active_payload = {
        "generated_at_utc": generated_at,
        "active_group": active_group,
        "runtime_count": len(entries),
        "source_manifest_path": "data/wiki_runtime_books/full_rebuild_manifest.json",
        "entries": entries,
    }
    candidate_payload = {
        "generated_at_utc": generated_at,
        "candidate_count": len(entries),
        "promotion_group": "full_official_catalog_gold_candidates",
        "entries": entries,
    }
    source_first_payload = {
        "generated_at_utc": generated_at,
        "count": len(entries),
        "source_strategy": "official-html-single-full-catalog",
        "source_manifest_path": _relative_path(root_dir, source_manifest),
        "entries": entries,
    }
    targets = {
        "full_runtime_manifest": root_dir / "data/wiki_runtime_books/full_rebuild_manifest.json",
        "active_manifest": root_dir / "data/wiki_runtime_books/active_manifest.json",
        "gold_candidate_manifest": root_dir / "data/gold_candidate_books/full_rebuild_manifest.json",
        "source_first_manifest": root_dir / "manifests/ocp420_source_first_full_rebuild_manifest.json",
    }
    payloads = {
        "full_runtime_manifest": full_payload,
        "active_manifest": active_payload,
        "gold_candidate_manifest": candidate_payload,
        "source_first_manifest": source_first_payload,
    }
    for key, path in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payloads[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "runtime_count": len(entries),
        "source_manifest_path": _relative_path(root_dir, source_manifest),
        "targets": {key: _relative_path(root_dir, path) for key, path in targets.items()},
    }


def _markdown_block_text(block: dict[str, Any]) -> str:
    kind = str(block.get("kind") or "").strip().lower()
    if kind == "paragraph":
        return str(block.get("text") or "").strip()
    if kind == "code":
        language = str(block.get("language") or "text").strip() or "text"
        code = str(block.get("code") or "").rstrip()
        if not code.strip():
            return ""
        return f"```{language}\n{code}\n```"
    if kind == "table":
        headers = [str(item).strip() for item in (block.get("headers") or []) if str(item).strip()]
        rows = [
            [str(cell).strip() for cell in row]
            for row in (block.get("rows") or [])
            if isinstance(row, list)
        ]
        if not headers and rows:
            headers = rows[0]
            rows = rows[1:]
        if not headers:
            return str(block.get("caption") or "").strip()
        width = len(headers)
        output = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        for row in rows:
            cells = (row + [""] * width)[:width]
            output.append("| " + " | ".join(cells) + " |")
        return "\n".join(output)
    if kind == "figure":
        src = str(block.get("src") or block.get("asset_url") or "").strip()
        caption = str(block.get("caption") or block.get("alt") or Path(src).name).strip()
        if not src:
            return caption
        return f"![{caption}]({src})"
    if kind == "note":
        title = str(block.get("title") or "Note").strip()
        text = str(block.get("text") or "").strip()
        return f"> **{title}:** {text}".strip()
    if kind == "prerequisite":
        items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
        return "\n".join(f"- {item}" for item in items)
    if kind == "procedure":
        lines: list[str] = []
        for index, step in enumerate((block.get("steps") or []), start=1):
            if isinstance(step, dict):
                text = str(step.get("text") or "").strip()
            else:
                text = str(step or "").strip()
            if text:
                lines.append(f"{index}. {text}")
        return "\n".join(lines)
    parts = [
        str(block.get(key) or "").strip()
        for key in ("title", "text", "caption", "code")
        if str(block.get(key) or "").strip()
    ]
    return "\n\n".join(parts)


def _playbook_markdown(row: dict[str, Any]) -> str:
    title = str(row.get("title") or row.get("book_slug") or "Untitled").strip()
    lines = [f"# {title}", ""]
    source_uri = str(row.get("source_uri") or "").strip()
    if source_uri:
        lines.extend([f"Source: {source_uri}", ""])
    for section in row.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        if not heading:
            continue
        level = max(2, min(6, int(section.get("level") or 2)))
        lines.extend([f"{'#' * level} {heading}", ""])
        block_texts = [
            _markdown_block_text(block)
            for block in (section.get("blocks") or [])
            if isinstance(block, dict)
        ]
        body = "\n\n".join(text for text in block_texts if text.strip()).strip()
        if body:
            lines.extend([body, ""])
    return "\n".join(lines).rstrip() + "\n"


def materialize_runtime_markdown_from_playbooks(root_dir: Path) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    playbook_by_slug = {
        str(row.get("book_slug") or "").strip(): row
        for row in _read_jsonl(settings.playbook_documents_path)
        if str(row.get("book_slug") or "").strip()
    }
    active_manifest_path = root_dir / "data/wiki_runtime_books/active_manifest.json"
    active_manifest = json.loads(active_manifest_path.read_text(encoding="utf-8")) if active_manifest_path.exists() else {}
    results: list[dict[str, Any]] = []
    for entry in active_manifest.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        row = playbook_by_slug.get(slug)
        if not slug or row is None:
            results.append({"slug": slug, "status": "missing_playbook_document", "written": []})
            continue
        markdown = _playbook_markdown(row)
        written: list[str] = []
        for key in ("runtime_path", "source_candidate_path"):
            target_value = str(entry.get(key) or "").strip()
            if not target_value:
                continue
            target = Path(target_value)
            if not target.is_absolute():
                target = root_dir / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(markdown, encoding="utf-8")
            written.append(_relative_path(root_dir, target))
        results.append({"slug": slug, "status": "ok" if written else "no_target", "written": written})
    return results


def _block_counts(playbook_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in playbook_rows:
        for section in row.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for block in section.get("blocks") or []:
                if not isinstance(block, dict):
                    continue
                kind = str(block.get("kind") or "").strip()
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
    return counts


def _figure_sidecar_count(root_dir: Path) -> int:
    path = root_dir / "data/wiki_relations/figure_assets.json"
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    return sum(len(items) for items in entries.values() if isinstance(items, list)) if isinstance(entries, dict) else 0


def _count_payload_entries(payload: dict[str, Any], key: str) -> int:
    entries = payload.get(key) if isinstance(payload.get(key), dict) else {}
    return sum(len(items) for items in entries.values() if isinstance(items, list)) if isinstance(entries, dict) else 0


def _figure_relation_signatures(payload: dict[str, Any]) -> set[tuple[str, str, str]]:
    by_slug = payload.get("by_slug") if isinstance(payload.get("by_slug"), dict) else {}
    signatures: set[tuple[str, str, str]] = set()
    if not isinstance(by_slug, dict):
        return signatures
    for slug, records in by_slug.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            signatures.add(
                (
                    str(slug or "").strip(),
                    str(record.get("section_anchor") or "").strip(),
                    str(record.get("asset_name") or "").strip(),
                )
            )
    return {signature for signature in signatures if all(signature)}


def _figure_relation_coverage(root_dir: Path, playbook_rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = build_official_figure_relation_sidecars(playbook_rows)
    expected_section_index = expected["figure_section_index"]
    expected_signatures = _figure_relation_signatures(expected_section_index)
    figure_assets_path = root_dir / "data/wiki_relations/figure_assets.json"
    figure_section_path = root_dir / "data/wiki_relations/figure_section_index.json"
    actual_assets = _safe_read_json(figure_assets_path)
    actual_section_index = _safe_read_json(figure_section_path)
    actual_signatures = _figure_relation_signatures(actual_section_index)
    missing_signatures = sorted(expected_signatures - actual_signatures)
    expected_count = int(expected_section_index.get("figure_count") or 0)
    sidecar_count = _count_payload_entries(actual_assets, "entries")
    matched_section_count = _count_payload_entries(actual_section_index, "by_slug")
    ok = (
        expected_count == 0
        or (
            not missing_signatures
            and sidecar_count >= expected_count
            and matched_section_count >= expected_count
        )
    )
    return {
        "status": "ok" if ok else "fail",
        "expected_figure_blocks": expected_count,
        "figure_sidecar_count": sidecar_count,
        "matched_section_count": matched_section_count,
        "missing_relation_count": len(missing_signatures),
        "sample_missing_relations": [
            {
                "book_slug": slug,
                "section_anchor": section_anchor,
                "asset_name": asset_name,
            }
            for slug, section_anchor, asset_name in missing_signatures[:10]
        ],
    }


def _bm25_metadata_contract(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_fields = (
        "section_id",
        "surface_kind",
        "source_unit_kind",
        "source_unit_id",
        "source_unit_anchor",
        "origin_method",
        "ocr_status",
        "block_kinds",
        "citation_eligible",
    )
    missing_by_field = {field: 0 for field in required_fields}
    figure_rows = 0
    figure_rows_with_block_kind = 0
    for row in rows:
        for field in required_fields:
            value = row.get(field)
            if value is None or value == "" or value == []:
                missing_by_field[field] += 1
        block_kinds = [str(item) for item in (row.get("block_kinds") or [])]
        text = str(row.get("text") or "")
        if "figure" in block_kinds or "[FIGURE" in text:
            figure_rows += 1
            if "figure" in block_kinds:
                figure_rows_with_block_kind += 1
    missing_row_count = sum(1 for row in rows if any(row.get(field) in (None, "", []) for field in required_fields))
    ok = bool(rows) and missing_row_count == 0 and (figure_rows == 0 or figure_rows_with_block_kind == figure_rows)
    return {
        "status": "ok" if ok else "fail",
        "row_count": len(rows),
        "missing_row_count": missing_row_count,
        "missing_by_field": missing_by_field,
        "figure_rows": figure_rows,
        "figure_rows_with_block_kind": figure_rows_with_block_kind,
    }


def _first_figure_slug(root_dir: Path) -> str:
    path = root_dir / "data/wiki_relations/figure_assets.json"
    if not path.exists():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    for slug, items in entries.items():
        if isinstance(items, list) and items:
            return str(slug)
    return ""


def _first_figure_viewer_path(root_dir: Path) -> str:
    path = root_dir / "data/wiki_relations/figure_assets.json"
    if not path.exists():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    for _slug, items in entries.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            viewer_path = str(item.get("viewer_path") or "").strip()
            if viewer_path:
                return viewer_path
    return ""


def _viewer_probe(root_dir: Path, slug: str) -> dict[str, Any]:
    if not slug:
        return {
            "slug": "",
            "multi_section_cards": 0,
            "single_section_cards": 0,
            "multi_figures": 0,
            "multi_code_blocks": 0,
        }
    multi_path = f"/playbooks/wiki-runtime/active/{slug}/index.html?page_mode=multi"
    single_path = f"/playbooks/wiki-runtime/active/{slug}/index.html?page_mode=single"
    multi_html = resolve_viewer_html(root_dir, multi_path) or ""
    single_html = resolve_viewer_html(root_dir, single_path) or ""
    return {
        "slug": slug,
        "multi_path": multi_path,
        "single_path": single_path,
        "multi_section_cards": len(SECTION_CARD_RE.findall(multi_html)),
        "single_section_cards": len(SECTION_CARD_RE.findall(single_html)),
        "multi_figures": len(FIGURE_RE.findall(multi_html)),
        "multi_code_blocks": len(CODE_BLOCK_RE.findall(multi_html)),
        "multi_has_title": bool("<h1" in multi_html),
    }


def _smoke(root_dir: Path, sample_slug: str) -> dict[str, bool]:
    advanced_html = resolve_viewer_html(root_dir, "/playbooks/wiki-runtime/active/advanced_networking/index.html?page_mode=multi") or ""
    storage_html = resolve_viewer_html(root_dir, "/playbooks/wiki-runtime/active/storage/index.html?page_mode=multi") or ""
    proxy_html = resolve_viewer_html(root_dir, "/wiki/entities/cluster-wide-proxy/index.html") or ""
    nodes_html = resolve_viewer_html(root_dir, "/playbooks/wiki-runtime/active/nodes/index.html?page_mode=multi") or ""
    architecture_html = resolve_viewer_html(root_dir, "/playbooks/wiki-runtime/active/architecture/index.html?page_mode=multi") or ""
    sample_html = resolve_viewer_html(root_dir, f"/playbooks/wiki-runtime/active/{sample_slug}/index.html?page_mode=multi") or ""
    sample_figure_html = resolve_viewer_html(root_dir, _first_figure_viewer_path(root_dir)) or ""
    return {
        "runtime_viewer_has_title": "<h1" in sample_html,
        "runtime_viewer_has_networking_hub": "advanced" in advanced_html.lower() or "네트워킹" in advanced_html,
        "runtime_viewer_has_related_sections": "Related" in advanced_html or "관련" in advanced_html,
        "storage_viewer_has_topic_hub": "storage" in storage_html.lower() or "스토리지" in storage_html,
        "proxy_hub_has_related_figures": "<figure" in proxy_html or "Figures" in proxy_html,
        "proxy_hub_has_related_sections": "Related" in proxy_html or "관련" in proxy_html,
        "nodes_viewer_has_figure": "<figure" in nodes_html or "<figure" in sample_html,
        "architecture_viewer_has_figure": "<figure" in architecture_html or "<figure" in sample_html,
        "architecture_figure_viewer_has_parent_book": "Parent Book" in sample_figure_html,
        "architecture_figure_viewer_has_related_section": "Related Section" in sample_figure_html,
        "sample_viewer_has_figure": "<figure" in sample_html,
        "sample_figure_viewer_has_parent_book": "Parent Book" in sample_figure_html,
        "sample_figure_viewer_has_related_section": "Related Section" in sample_figure_html,
    }


def build_official_gold_gate_report(root_dir: Path) -> dict[str, Any]:
    settings = load_settings(root_dir)
    chunks_rows = _read_jsonl(settings.chunks_path)
    bm25_rows = _read_jsonl(settings.bm25_corpus_path)
    playbook_rows = _read_jsonl(settings.playbook_documents_path)
    block_counts = _block_counts(playbook_rows)
    figure_sidecar_count = _figure_sidecar_count(root_dir)
    official_catalog_coverage = _official_catalog_coverage(
        root_dir,
        chunks_rows=chunks_rows,
        bm25_rows=bm25_rows,
        playbook_rows=playbook_rows,
    )
    sample_slug = _first_figure_slug(root_dir) or "advanced_networking"
    viewer_probe = _viewer_probe(root_dir, sample_slug)
    portable_paths = _portable_path_findings(root_dir)
    artifact_manifest = _artifact_manifest(root_dir)
    large_jsonl_artifact_policy = _large_jsonl_artifact_policy(root_dir, artifact_manifest)
    ko_localization = build_official_ko_localization_audit(playbook_rows)
    figure_relation_coverage = _figure_relation_coverage(root_dir, playbook_rows)
    bm25_metadata_contract = _bm25_metadata_contract(bm25_rows)
    smoke = _smoke(root_dir, sample_slug)
    checks = {
        "portable_paths": portable_paths["status"] == "ok",
        "large_jsonl_artifacts_manifest_only": large_jsonl_artifact_policy["status"] == "ok",
        "chunks_and_bm25_match": bool(chunks_rows) and len(chunks_rows) == len(bm25_rows),
        "bm25_metadata_contract": bm25_metadata_contract["status"] == "ok",
        "code_blocks_present": int(block_counts.get("code", 0)) > 0,
        "ko_runtime_has_no_unlocalized_english_prose": ko_localization["status"] == "ok",
        "inline_figures_present_when_sidecar_has_figures": (
            figure_sidecar_count == 0
            or int(block_counts.get("figure", 0)) > 0
        ),
        "figure_sidecar_covers_playbook_figures": figure_relation_coverage["status"] == "ok",
        "multi_page_renders_multiple_sections": int(viewer_probe["multi_section_cards"]) > 1,
        "single_page_renders_one_section": int(viewer_probe["single_section_cards"]) == 1,
        "viewer_code_blocks_render": int(viewer_probe["multi_code_blocks"]) > 0,
        "smoke": all(smoke.values()),
        "full_official_catalog_coverage": (
            int(official_catalog_coverage["catalog_count"]) == 0
            or (
                not official_catalog_coverage["missing_playbook_slugs"]
                and not official_catalog_coverage["missing_chunk_slugs"]
                and not official_catalog_coverage["missing_bm25_slugs"]
                and not official_catalog_coverage["missing_active_runtime_slugs"]
            )
        ),
    }
    failures = [name for name, ok in checks.items() if not ok]
    status = "ok" if not failures else "fail"
    step_results = [
        {
            "name": name,
            "returncode": 0 if ok else 1,
        }
        for name, ok in checks.items()
    ]
    return {
        "status": status,
        "generated_at_utc": _utc_now(),
        "git": _git_refs(root_dir),
        "goal": "ocp_official_gold_book_pipeline",
        "checks": checks,
        "failures": failures,
        "step_results": step_results,
        "smoke": smoke,
        "metrics": {
            "chunks_count": len(chunks_rows),
            "bm25_count": len(bm25_rows),
            "playbook_document_count": len(playbook_rows),
            "playbook_block_counts": block_counts,
            "figure_sidecar_count": figure_sidecar_count,
            "viewer_probe": viewer_probe,
            "portable_paths": portable_paths,
            "large_jsonl_artifact_policy": large_jsonl_artifact_policy,
            "official_catalog_coverage": official_catalog_coverage,
            "ko_localization": ko_localization,
            "figure_relation_coverage": figure_relation_coverage,
            "bm25_metadata_contract": bm25_metadata_contract,
        },
        "artifact_manifest": artifact_manifest,
    }


def write_official_gold_gate_report(root_dir: Path, output_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    target = output_path or root_dir / ONE_CLICK_REPORT_RELATIVE_PATH
    payload = build_official_gold_gate_report(root_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload


__all__ = [
    "ARTIFACT_MANIFEST_RELATIVE_PATH",
    "MANIFEST_ONLY_LARGE_JSONL_RELATIVE_PATHS",
    "OFFICIAL_GOLD_REBUILD_COMMAND",
    "ONE_CLICK_REPORT_RELATIVE_PATH",
    "build_official_gold_gate_report",
    "materialize_runtime_markdown_from_playbooks",
    "publish_runtime_manifest_from_playbooks",
    "repair_portable_json_paths",
    "write_artifact_manifest",
    "write_official_gold_gate_report",
]
