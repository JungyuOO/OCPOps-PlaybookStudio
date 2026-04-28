from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .pipeline.image_policy import apply_image_policy_to_chunk


def _load_chunks(course_dir: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted((course_dir / "chunks").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["_chunk_path"] = path
            chunks.append(payload)
    return chunks


def _write_chunks(chunks: list[dict[str, Any]]) -> None:
    for chunk in chunks:
        path = chunk.pop("_chunk_path", None)
        if isinstance(path, Path):
            path.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(chunks: list[dict[str, Any]], *, applied: bool) -> dict[str, Any]:
    quality = Counter()
    roles = Counter()
    states = Counter()
    visible = 0
    duplicates = 0
    blank = 0
    total = 0
    low_confidence_samples: list[dict[str, Any]] = []
    for chunk in chunks:
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            total += 1
            quality_label = str(attachment.get("quality_label") or "")
            role = str(attachment.get("instructional_role") or "")
            state = str(attachment.get("state_signal") or "")
            quality[quality_label] += 1
            roles[role] += 1
            if state:
                states[state] += 1
            if attachment.get("is_default_visible"):
                visible += 1
            if attachment.get("duplicate_of_asset_id"):
                duplicates += 1
            if quality_label == "blank_or_solid":
                blank += 1
            if len(low_confidence_samples) < 20 and quality_label in {"blank_or_solid", "low_signal_image"}:
                low_confidence_samples.append(
                    {
                        "chunk_id": str(chunk.get("chunk_id") or ""),
                        "asset_id": str(attachment.get("asset_id") or ""),
                        "quality_label": quality_label,
                        "instructional_role": role,
                        "asset_path": str(attachment.get("asset_path") or ""),
                    }
                )
    return {
        "canonical_model": "course_image_policy_report_v1",
        "applied": applied,
        "attachment_count": total,
        "default_visible_count": visible,
        "duplicate_count": duplicates,
        "blank_or_solid_count": blank,
        "quality_counts": dict(sorted(quality.items())),
        "instructional_role_counts": dict(sorted(roles.items())),
        "state_signal_counts": dict(states.most_common()),
        "low_confidence_samples": low_confidence_samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply chunk-context-aware image policy metadata to generated course chunks.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root_dir = args.root_dir.resolve()
    course_dir = (root_dir / args.course_dir).resolve() if not args.course_dir.is_absolute() else args.course_dir.resolve()
    chunks = _load_chunks(course_dir)
    for chunk in chunks:
        apply_image_policy_to_chunk(chunk, root_dir=root_dir)
    report = _report(chunks, applied=not args.dry_run)
    manifests_dir = course_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "image_policy_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.dry_run:
        _write_chunks(chunks)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
