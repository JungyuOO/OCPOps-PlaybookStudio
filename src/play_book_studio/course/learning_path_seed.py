"""Convert existing course manifests into database learning path seeds."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from play_book_studio.db.learning_repository import CommandCheckSeed, LabTaskSeed, LearningPathSeed, LearningStepSeed


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
                    lab_tasks=_lab_tasks_for_step(step, step_id=step_id, guide_id=guide_id),
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


def _lab_tasks_for_step(step: dict[str, Any], *, step_id: str, guide_id: str) -> tuple[LabTaskSeed, ...]:
    explicit_tasks = step.get("lab_tasks") if isinstance(step.get("lab_tasks"), list) else []
    if explicit_tasks:
        return tuple(
            task
            for index, item in enumerate(explicit_tasks, start=1)
            if isinstance(item, dict)
            if (task := _explicit_lab_task(item, step_id=step_id, ordinal=index)) is not None
        )
    stage_id = str(step.get("stage_id") or "").strip()
    command = _starter_command_for_step(stage_id=stage_id, expected_terms=step.get("expected_terms"))
    check_key = f"{step_id}-starter-command"
    return (
        LabTaskSeed(
            task_key=f"{step_id}-starter-lab",
            ordinal=1,
            title="Run the starter OCP inspection command",
            goal_markdown="Open the terminal and run the suggested command so the platform state is connected to this learning step.",
            starter_context={
                "guide_id": guide_id,
                "stage_id": stage_id,
                "suggested_command": command,
            },
            expected_outcome={"command_submitted": command},
            hint_markdown=f"Run `{command}` in the terminal.",
            metadata={"generated": True, "source": "ops_learning_guides_to_seed"},
            command_checks=(
                CommandCheckSeed(
                    check_key=check_key,
                    ordinal=1,
                    command_pattern=_command_regex(command),
                    expected_command=command,
                    validation_kind="command_pattern",
                    validation_payload={"expected_command": command},
                    success_message="Starter command captured.",
                    failure_hint=f"Run `{command}` before moving to the next step.",
                    metadata={"generated": True},
                ),
            ),
        ),
    )


def _explicit_lab_task(item: dict[str, Any], *, step_id: str, ordinal: int) -> LabTaskSeed | None:
    task_key = str(item.get("task_key") or item.get("id") or f"{step_id}-lab-{ordinal}").strip()
    if not task_key:
        return None
    checks = item.get("command_checks") if isinstance(item.get("command_checks"), list) else []
    return LabTaskSeed(
        task_key=task_key,
        ordinal=int(item.get("ordinal") or ordinal),
        title=str(item.get("title") or task_key),
        goal_markdown=str(item.get("goal_markdown") or item.get("goal") or ""),
        starter_context=item.get("starter_context") if isinstance(item.get("starter_context"), dict) else {},
        expected_outcome=item.get("expected_outcome") if isinstance(item.get("expected_outcome"), dict) else {},
        hint_markdown=str(item.get("hint_markdown") or item.get("hint") or ""),
        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        command_checks=tuple(
            CommandCheckSeed(
                check_key=str(check.get("check_key") or check.get("id") or f"{task_key}-check-{index}"),
                ordinal=int(check.get("ordinal") or index),
                command_pattern=str(check.get("command_pattern") or ""),
                expected_command=str(check.get("expected_command") or ""),
                validation_kind=str(check.get("validation_kind") or "command_pattern"),
                validation_payload=check.get("validation_payload") if isinstance(check.get("validation_payload"), dict) else {},
                success_message=str(check.get("success_message") or ""),
                failure_hint=str(check.get("failure_hint") or ""),
                metadata=check.get("metadata") if isinstance(check.get("metadata"), dict) else {},
            )
            for index, check in enumerate(checks, start=1)
            if isinstance(check, dict)
        ),
    )


def _starter_command_for_step(*, stage_id: str, expected_terms: Any) -> str:
    stage = stage_id.strip().lower()
    terms = " ".join(str(item or "").lower() for item in expected_terms if str(item or "").strip()) if isinstance(expected_terms, list) else ""
    basis = f"{stage} {terms}"
    if "perf" in basis or "hpa" in basis:
        return "oc adm top nodes"
    if "route" in basis or "haproxy" in basis or "ingress" in basis:
        return "oc get routes -A"
    if "pod" in basis or "service" in basis or "deploy" in basis:
        return "oc get pods -A"
    if "node" in basis:
        return "oc get nodes"
    if "version" in basis or "completion" in basis:
        return "oc get clusterversion"
    return "oc get co"


def _command_regex(command: str) -> str:
    return r"^" + r"\s+".join(re.escape(part) for part in command.split()) + r"\b"


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
