from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .pipeline.canonical import attach_course_tour_metadata, build_course_manifest
from .pipeline.official_doc_matcher import match_official_docs
from .pipeline.official_routes import attach_stage_official_routes


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return payload


def _chunk_paths(course_dir: Path) -> list[Path]:
    return sorted((course_dir / "chunks").glob("*.json"))


def _load_chunks(course_dir: Path) -> list[dict[str, Any]]:
    return [_read_json(path) for path in _chunk_paths(course_dir)]


def _stage_report(chunks: list[dict[str, Any]], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if str(chunk.get("parent_chunk_id") or "").strip():
            continue
        stage_id = str(chunk.get("stage_id") or "unknown")
        stage = stages.setdefault(
            stage_id,
            {
                "parent_chunk_count": 0,
                "chunks_with_official_docs": 0,
                "official_doc_count": 0,
                "sample_mappings": [],
            },
        )
        docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
        stage["parent_chunk_count"] += 1
        if docs:
            stage["chunks_with_official_docs"] += 1
            stage["official_doc_count"] += len(docs)
            if len(stage["sample_mappings"]) < 5:
                first = docs[0] if isinstance(docs[0], dict) else {}
                stage["sample_mappings"].append(
                    {
                        "chunk_id": str(chunk.get("chunk_id") or ""),
                        "native_id": str(chunk.get("native_id") or ""),
                        "title": str(chunk.get("title") or ""),
                        "official_title": str(first.get("title") or first.get("book_slug") or ""),
                        "section_title": str(first.get("section_title") or ""),
                        "score": first.get("score"),
                        "match_reason": str(first.get("match_reason") or ""),
                    }
                )
    for stage in stages.values():
        count = int(stage["parent_chunk_count"] or 0)
        mapped = int(stage["chunks_with_official_docs"] or 0)
        stage["coverage_ratio"] = round(mapped / count, 3) if count else 0.0
    if isinstance(manifest, dict):
        for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("stage_id") or "unknown")
            refs = stage.get("official_route_refs") if isinstance(stage.get("official_route_refs"), list) else []
            stages.setdefault(
                stage_id,
                {
                    "parent_chunk_count": 0,
                    "chunks_with_official_docs": 0,
                    "official_doc_count": 0,
                    "sample_mappings": [],
                    "coverage_ratio": 0.0,
                },
            )
            stages[stage_id]["stage_official_route_count"] = len(refs)
            stages[stage_id]["stage_official_routes"] = [
                {
                    "title": str(ref.get("title") or ref.get("book_slug") or ""),
                    "section_title": str(ref.get("section_title") or ""),
                    "match_reason": str(ref.get("match_reason") or ""),
                }
                for ref in refs[:4]
                if isinstance(ref, dict)
            ]
    return dict(sorted(stages.items()))


def _write_chunks(course_dir: Path, chunks: list[dict[str, Any]]) -> None:
    chunks_dir = course_dir / "chunks"
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        (chunks_dir / f"{chunk_id}.json").write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh official-doc links for existing course chunks without rerunning OCR.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=0.65)
    parser.add_argument("--min-overlap", type=int, default=2)
    parser.add_argument("--apply", action="store_true", help="Write refreshed chunks and manifest. Without this, only the report is written.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root_dir = args.root_dir.resolve()
    course_dir = args.course_dir.resolve()
    chunks = _load_chunks(course_dir)
    refreshed = match_official_docs(
        root_dir,
        chunks,
        top_k=max(1, args.top_k),
        min_overlap=max(1, args.min_overlap),
        min_score=args.min_score,
    )
    manifest = build_course_manifest(refreshed)
    manifest = attach_stage_official_routes(manifest, root_dir=root_dir)
    refreshed = attach_course_tour_metadata(refreshed, manifest)
    report = {
        "canonical_model": "course_official_mapping_report_v1",
        "course_dir": str(course_dir),
        "chunk_count": len(refreshed),
        "applied": bool(args.apply),
        "min_score": args.min_score,
        "min_overlap": args.min_overlap,
        "top_k": args.top_k,
        "stages": _stage_report(refreshed, manifest),
    }
    manifests_dir = course_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "official_mapping_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        (manifests_dir / "course_v1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_chunks(course_dir, refreshed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
