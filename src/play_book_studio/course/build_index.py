from __future__ import annotations

import argparse
import json
from pathlib import Path

from play_book_studio.config.settings import load_settings

from .ops_learning import DEFAULT_GOLDEN_PATH, DEFAULT_GUIDES_PATH, DEFAULT_LEARNING_CHUNKS_PATH, write_initial_guides_and_golden
from .qdrant_course import upsert_course_chunks, upsert_ops_learning_chunks
from .pipeline.canonical import attach_course_tour_metadata, build_course_manifest, write_course_outputs
from .pipeline.chunk_normalization import normalize_course_chunks
from .pipeline.image_annotation import annotate_slide_graph_attachments, summarize_attachment_coverage
from .pipeline.image_policy import apply_image_policy_to_chunks
from .pipeline.incremental import build_deck_checkpoint
from .pipeline.official_doc_matcher import match_official_docs
from .pipeline.official_routes import attach_stage_official_routes
from .pipeline.parsers.architecture import parse_architecture_deck, parse_architecture_graph
from .pipeline.parsers.completion_report import parse_completion_report_deck, parse_completion_report_graph
from .pipeline.parsers.integration_test import parse_integration_test_deck, parse_integration_test_graph
from .pipeline.parsers.perf_test import parse_perf_test_deck, parse_perf_test_graph
from .pipeline.pptx_structured import extract_pptx_shapes
from .pipeline.slide_graph import build_slide_graph, write_slide_graphs
from .pipeline.template_classifier import classify_template_family
from .pipeline.parsers.unit_test import parse_unit_test_graph


def _enrich_chunks_with_attachment_summaries(chunks: list[dict]) -> list[dict]:
    for chunk in chunks:
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        summaries = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            text = str(attachment.get("visual_summary") or attachment.get("caption_text") or "").strip()
            if text:
                summaries.append(text)
        if summaries:
            visual_text = "\n".join(dict.fromkeys(summaries))
            chunk["visual_text"] = visual_text
            search_text = str(chunk.get("search_text") or "").strip()
            if visual_text not in search_text:
                chunk["search_text"] = "\n".join(part for part in [search_text, visual_text] if part)
            index_texts = chunk.get("index_texts") if isinstance(chunk.get("index_texts"), dict) else {}
            index_texts["visual_text"] = visual_text
            dense_text = str(index_texts.get("dense_text") or chunk.get("body_md") or "").strip()
            if visual_text not in dense_text:
                index_texts["dense_text"] = "\n".join(part for part in [dense_text, visual_text] if part)
            chunk["index_texts"] = index_texts
    return chunks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build project-playbook course artifacts from study-docs PPTX files.")
    parser.add_argument("--source-dir", type=Path, default=Path("study-docs"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/course_pbs"))
    parser.add_argument(
        "--family",
        choices=("architecture", "unit_test", "integration_test", "perf_test", "completion_report", "all"),
        default="unit_test",
    )
    parser.add_argument("--limit", type=int, default=1, help="How many matching PPTX decks to process for the spike.")
    parser.add_argument("--skip-qdrant", action="store_true")
    return parser


def _iter_pptx(source_dir: Path) -> list[Path]:
    return sorted(path for path in source_dir.rglob("*.pptx") if path.is_file())


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    semantic_seen: dict[str, str] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        semantic_key = str(chunk.get("semantic_chunk_id") or "").strip()
        if semantic_key:
            winner = semantic_seen.get(semantic_key)
            if winner:
                existing = deduped.get(winner, {})
                existing_refs = len(existing.get("slide_refs") or []) if isinstance(existing.get("slide_refs"), list) else 0
                current_refs = len(chunk.get("slide_refs") or []) if isinstance(chunk.get("slide_refs"), list) else 0
                if current_refs > existing_refs:
                    deduped[winner] = chunk
                continue
            semantic_seen[semantic_key] = chunk_id
        deduped[chunk_id] = chunk
    existing_ids = set(deduped)
    for chunk in deduped.values():
        child_ids = chunk.get("child_chunk_ids") if isinstance(chunk.get("child_chunk_ids"), list) else []
        if child_ids:
            chunk["child_chunk_ids"] = [child_id for child_id in child_ids if child_id in existing_ids]
        parent_chunk_id = str(chunk.get("parent_chunk_id") or "").strip()
        if parent_chunk_id and parent_chunk_id not in existing_ids:
            chunk["parent_chunk_id"] = None
    return list(deduped.values())


def _load_review_overrides(source_root: Path) -> dict[str, dict]:
    path = source_root / "manifests" / "course_review_overrides.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _apply_review_status(chunks: list[dict], *, source_root: Path) -> list[dict]:
    overrides = _load_review_overrides(source_root)
    for chunk in chunks:
        notes: list[str] = []
        title = str(chunk.get("title") or "").strip()
        native_id = str(chunk.get("native_id") or "").strip().lower()
        body_md = str(chunk.get("body_md") or "").strip()
        stage_id = str(chunk.get("stage_id") or "").strip()
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        attachment_signal = any(
            isinstance(att, dict) and (str(att.get("ocr_text") or "").strip() or str(att.get("visual_summary") or "").strip())
            for att in attachments
        )
        missing_visual_summary = any(
            isinstance(att, dict) and not str(att.get("visual_summary") or "").strip()
            for att in attachments
        )
        if title.lower().startswith("slide "):
            notes.append("placeholder_title")
        if native_id.startswith("slide-") and stage_id in {"integration_test", "perf_test"}:
            notes.append("fallback_native_id")
        if not body_md and not attachment_signal:
            notes.append("thin_content")
        if attachments and not attachment_signal:
            notes.append("attachments_without_description")
        if missing_visual_summary:
            notes.append("attachments_without_visual_summary")
        if not chunk.get("parent_chunk_id") and len(str(chunk.get("search_text") or body_md)) > 60000:
            notes.append("oversized_parent_chunk")

        review_status = "needs_review" if notes else "approved"
        quality_score = max(0.35, 0.95 - (0.18 * len(notes))) if notes else 0.98
        review_notes = notes

        override = overrides.get(str(chunk.get("chunk_id") or ""))
        if override:
            review_status = str(override.get("review_status") or review_status)
            override_notes = override.get("review_notes")
            if isinstance(override_notes, list):
                review_notes = [str(item) for item in override_notes]
            if "quality_score" in override:
                try:
                    quality_score = float(override.get("quality_score"))
                except (TypeError, ValueError):
                    pass
            elif review_status == "approved" and not review_notes:
                quality_score = 0.98

        chunk["review_status"] = review_status
        chunk["review_notes"] = review_notes
        chunk["quality_score"] = round(quality_score, 2)
    return chunks


def _write_review_queue(output_dir: Path, chunks: list[dict]) -> None:
    rows: list[dict] = []
    reason_counts: dict[str, int] = {}
    for chunk in chunks:
        notes = [str(item) for item in (chunk.get("review_notes") or []) if str(item).strip()]
        if str(chunk.get("review_status") or "") != "needs_review" and not notes:
            continue
        for note in notes:
            reason_counts[note] = reason_counts.get(note, 0) + 1
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
        rows.append(
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "stage_id": str(chunk.get("stage_id") or ""),
                "native_id": str(chunk.get("native_id") or ""),
                "title": str(chunk.get("title") or ""),
                "review_status": str(chunk.get("review_status") or ""),
                "review_notes": notes,
                "quality_score": chunk.get("quality_score"),
                "slide_refs": [
                    {
                        "pptx": str(ref.get("pptx") or ""),
                        "slide_no": int(ref.get("slide_no") or 0),
                        "png_path": str(ref.get("png_path") or ""),
                    }
                    for ref in slide_refs
                    if isinstance(ref, dict)
                ],
                "missing_visual_summary_assets": [
                    {
                        "asset_id": str(att.get("asset_id") or ""),
                        "slide_no": int(att.get("slide_no") or 0),
                        "role": str(att.get("role") or ""),
                        "asset_path": str(att.get("asset_path") or ""),
                    }
                    for att in attachments
                    if isinstance(att, dict) and not str(att.get("visual_summary") or "").strip()
                ],
            }
        )
    payload = {
        "canonical_model": "course_review_queue_v1",
        "total": len(rows),
        "reason_counts": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "items": rows,
    }
    (output_dir / "manifests" / "review_queue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = build_parser().parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not source_dir.exists():
        raise SystemExit(f"source dir not found: {source_dir}")

    parsed_chunks: list[dict] = []
    deck_summaries: list[dict] = []
    checkpoints: list[dict] = []
    slide_graphs: list[dict] = []
    settings = load_settings(source_dir.parent)
    ocr_stats = {
        "attachments_total": 0,
        "attachments_ocr_ok": 0,
        "attachments_summary_ok": 0,
        "attachments_failed": 0,
    }

    for pptx_path in _iter_pptx(source_dir):
        slide_rows = extract_pptx_shapes(pptx_path)
        family = classify_template_family(slide_rows)
        if args.family != "all" and family != args.family:
            continue
        result = None
        slide_graph = build_slide_graph(pptx_path, family, slide_rows, source_dir=source_dir)
        per_graph_ocr = annotate_slide_graph_attachments([slide_graph], settings=settings)
        for key, value in per_graph_ocr.items():
            if key.endswith("_available"):
                ocr_stats[key] = max(int(ocr_stats.get(key, 0)), int(value or 0))
            else:
                ocr_stats[key] = int(ocr_stats.get(key, 0)) + int(value or 0)
        slide_graphs.append(slide_graph)
        if family == "unit_test":
            result = parse_unit_test_graph(pptx_path, slide_graph)
        elif family == "architecture":
            result = parse_architecture_graph(pptx_path, slide_graph)
        elif family == "integration_test":
            result = parse_integration_test_graph(pptx_path, slide_graph)
        elif family == "perf_test":
            result = parse_perf_test_graph(pptx_path, slide_graph)
        elif family == "completion_report":
            result = parse_completion_report_graph(pptx_path, slide_graph)
        if result is None:
            continue
        parsed_chunks.extend(result["chunks"])
        deck_summaries.append(result["deck"])
        checkpoints.append(
            build_deck_checkpoint(
                pptx_path=pptx_path,
                template_family=family,
                slide_rows=slide_rows,
                chunk_count=len(result["chunks"]),
            )
        )
        if len(deck_summaries) >= max(1, args.limit):
            break

    parsed_chunks = match_official_docs(source_dir.parent, parsed_chunks)
    parsed_chunks = _enrich_chunks_with_attachment_summaries(parsed_chunks)
    parsed_chunks = _dedupe_chunks(parsed_chunks)
    parsed_chunks = _apply_review_status(parsed_chunks, source_root=source_dir.parent)
    parsed_chunks = normalize_course_chunks(parsed_chunks)
    parsed_chunks = apply_image_policy_to_chunks(parsed_chunks, root_dir=source_dir.parent)
    manifest = build_course_manifest(parsed_chunks)
    manifest = attach_stage_official_routes(manifest, root_dir=source_dir.parent)
    parsed_chunks = attach_course_tour_metadata(parsed_chunks, manifest)
    write_course_outputs(output_dir=output_dir, manifest=manifest, chunks=parsed_chunks, decks=deck_summaries)
    ops_learning_result = write_initial_guides_and_golden(
        output_dir,
        DEFAULT_GUIDES_PATH,
        DEFAULT_GOLDEN_PATH,
        learning_chunks_path=DEFAULT_LEARNING_CHUNKS_PATH,
        root_dir=source_dir.parent,
    )
    written_chunks = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((output_dir / "chunks").glob("*.json"))
    ]
    _write_review_queue(output_dir, written_chunks)
    write_slide_graphs(output_dir=output_dir, slide_graphs=slide_graphs)
    (output_dir / "manifests" / "checkpoints.json").write_text(
        json.dumps(checkpoints, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    qdrant_upserted = 0
    qdrant_ops_learning_upserted = 0
    if not args.skip_qdrant:
        try:
            qdrant_upserted = upsert_course_chunks(settings, parsed_chunks)
            qdrant_ops_learning_upserted = upsert_ops_learning_chunks(settings, ops_learning_result.get("learning_chunks", []))
        except Exception as exc:  # noqa: BLE001
            qdrant_upserted = 0
            qdrant_ops_learning_upserted = 0
            print(json.dumps({"warning": f"course qdrant upsert skipped: {exc}"}, ensure_ascii=False))
    coverage = summarize_attachment_coverage(slide_graphs)

    print(
        json.dumps(
            {
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "deck_count": len(deck_summaries),
                "chunk_count": len(parsed_chunks),
                "qdrant_upserted": qdrant_upserted,
                "qdrant_ops_learning_upserted": qdrant_ops_learning_upserted,
                "ops_learning_chunk_count": len(ops_learning_result.get("learning_chunks", [])),
                "families": sorted({item.get("template_family") for item in deck_summaries}),
                "attachment_ocr": coverage,
                "attachment_ocr_runtime": ocr_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
