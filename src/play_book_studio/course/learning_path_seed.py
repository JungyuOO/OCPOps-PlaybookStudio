"""Convert existing course manifests into database learning path seeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from play_book_studio.db.learning_repository import LearningPathSeed, LearningStepSeed


def load_ops_learning_guides_seed(path: Path) -> LearningPathSeed:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ops_learning_guides_to_seed(payload, source_ref=path.as_posix())


def ops_learning_guides_to_seed(payload: dict[str, Any], *, source_ref: str = "") -> LearningPathSeed:
    guides = payload.get("guides") if isinstance(payload.get("guides"), list) else []
    steps: list[LearningStepSeed] = []
    ordinal = 1
    for guide in guides:
        if not isinstance(guide, dict):
            continue
        guide_id = str(guide.get("guide_id") or "").strip()
        guide_steps = guide.get("steps") if isinstance(guide.get("steps"), list) else []
        for step in guide_steps:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id") or "").strip()
            if not step_id:
                continue
            source_anchors = step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else []
            anchor_chunk_ids = [
                str(anchor.get("chunk_id") or "").strip()
                for anchor in source_anchors
                if isinstance(anchor, dict) and str(anchor.get("chunk_id") or "").strip()
            ]
            steps.append(
                LearningStepSeed(
                    step_key=step_id,
                    ordinal=ordinal,
                    title=str(step.get("card_text") or step.get("user_query") or step_id),
                    objective=str(step.get("learning_objective") or ""),
                    concept_slugs=tuple(_concepts_from_terms(step.get("expected_terms"))),
                    prerequisite_step_keys=tuple(str(item) for item in step.get("previous_step_ids", []) if str(item).strip())
                    if isinstance(step.get("previous_step_ids"), list)
                    else (),
                    estimated_minutes=10,
                    difficulty="beginner",
                    lesson_markdown=_lesson_markdown(step),
                    metadata={
                        "guide_id": guide_id,
                        "stage_id": str(step.get("stage_id") or guide.get("stage_id") or ""),
                        "user_query": str(step.get("user_query") or ""),
                        "next_step_ids": step.get("next_step_ids") if isinstance(step.get("next_step_ids"), list) else [],
                        "source_anchor_chunk_ids": anchor_chunk_ids,
                        "quality": step.get("quality") if isinstance(step.get("quality"), dict) else {},
                    },
                )
            )
            ordinal += 1
    return LearningPathSeed(
        slug=str(payload.get("course_slug") or "ocp-guided-learning"),
        title=str(payload.get("title") or "OCP Guided Learning"),
        description="Guided OCP learning path converted from ops learning guides.",
        audience="beginner",
        ocp_version=str(payload.get("ocp_version") or ""),
        language="ko",
        source_kind="ops_learning_guides",
        source_ref=source_ref or str(payload.get("source_manifest") or ""),
        metadata={
            "canonical_model": payload.get("canonical_model"),
            "guide_count": payload.get("guide_count"),
            "step_count": payload.get("step_count"),
        },
        steps=tuple(steps),
    )


def _lesson_markdown(step: dict[str, Any]) -> str:
    title = str(step.get("card_text") or step.get("step_id") or "").strip()
    objective = str(step.get("learning_objective") or "").strip()
    outline = step.get("answer_outline") if isinstance(step.get("answer_outline"), list) else []
    lines = [f"## {title}" if title else "## Learning step"]
    if objective:
        lines.extend(["", objective])
    outline_items = [str(item).strip() for item in outline if str(item).strip()]
    if outline_items:
        lines.append("")
        lines.extend(f"- {item}" for item in outline_items)
    return "\n".join(lines).strip()


def _concepts_from_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    concepts: list[str] = []
    for item in value:
        concept = str(item or "").strip().lower().replace(" ", "-")
        if concept and concept not in concepts:
            concepts.append(concept)
    return concepts


__all__ = ["load_ops_learning_guides_seed", "ops_learning_guides_to_seed"]
