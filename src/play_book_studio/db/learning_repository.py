"""Persistence helpers for guided learning paths and labs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CommandCheckSeed:
    check_key: str
    ordinal: int
    command_pattern: str = ""
    expected_command: str = ""
    validation_kind: str = "command_pattern"
    validation_payload: dict[str, Any] = field(default_factory=dict)
    success_message: str = ""
    failure_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LabTaskSeed:
    task_key: str
    ordinal: int
    title: str
    goal_markdown: str = ""
    starter_context: dict[str, Any] = field(default_factory=dict)
    expected_outcome: dict[str, Any] = field(default_factory=dict)
    hint_markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    command_checks: tuple[CommandCheckSeed, ...] = ()


@dataclass(frozen=True, slots=True)
class LearningStepSeed:
    step_key: str
    ordinal: int
    title: str
    objective: str = ""
    concept_slugs: tuple[str, ...] = ()
    prerequisite_step_keys: tuple[str, ...] = ()
    estimated_minutes: int = 0
    difficulty: str = "beginner"
    lesson_markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    lab_tasks: tuple[LabTaskSeed, ...] = ()


@dataclass(frozen=True, slots=True)
class LearningPathSeed:
    slug: str
    title: str
    description: str = ""
    audience: str = "beginner"
    ocp_version: str = ""
    language: str = "ko"
    source_kind: str = "seed"
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    steps: tuple[LearningStepSeed, ...] = ()


@dataclass(frozen=True, slots=True)
class LearningPathRows:
    path: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    lab_tasks: tuple[dict[str, Any], ...]
    command_checks: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class StoredLearningPath:
    learning_path_id: str
    step_ids: tuple[str, ...]
    lab_task_ids: tuple[str, ...]
    command_check_ids: tuple[str, ...]


def build_learning_path_rows(seed: LearningPathSeed) -> LearningPathRows:
    path = {
        "slug": seed.slug,
        "title": seed.title,
        "description": seed.description,
        "audience": seed.audience,
        "ocp_version": seed.ocp_version,
        "language": seed.language,
        "source_kind": seed.source_kind,
        "source_ref": seed.source_ref,
        "metadata": dict(seed.metadata),
    }
    steps: list[dict[str, Any]] = []
    lab_tasks: list[dict[str, Any]] = []
    command_checks: list[dict[str, Any]] = []
    for step in seed.steps:
        steps.append(
            {
                "step_key": step.step_key,
                "ordinal": step.ordinal,
                "title": step.title,
                "objective": step.objective,
                "concept_slugs": list(step.concept_slugs),
                "prerequisite_step_keys": list(step.prerequisite_step_keys),
                "estimated_minutes": step.estimated_minutes,
                "difficulty": step.difficulty,
                "lesson_markdown": step.lesson_markdown,
                "metadata": dict(step.metadata),
            }
        )
        for task in step.lab_tasks:
            lab_tasks.append(
                {
                    "step_key": step.step_key,
                    "task_key": task.task_key,
                    "ordinal": task.ordinal,
                    "title": task.title,
                    "goal_markdown": task.goal_markdown,
                    "starter_context": dict(task.starter_context),
                    "expected_outcome": dict(task.expected_outcome),
                    "hint_markdown": task.hint_markdown,
                    "metadata": dict(task.metadata),
                }
            )
            for check in task.command_checks:
                command_checks.append(
                    {
                        "task_key": task.task_key,
                        "check_key": check.check_key,
                        "ordinal": check.ordinal,
                        "command_pattern": check.command_pattern,
                        "expected_command": check.expected_command,
                        "validation_kind": check.validation_kind,
                        "validation_payload": dict(check.validation_payload),
                        "success_message": check.success_message,
                        "failure_hint": check.failure_hint,
                        "metadata": dict(check.metadata),
                    }
                )
    return LearningPathRows(
        path=path,
        steps=tuple(steps),
        lab_tasks=tuple(lab_tasks),
        command_checks=tuple(command_checks),
    )


def persist_learning_path(
    connection,
    seed: LearningPathSeed,
    *,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
) -> StoredLearningPath:
    rows = build_learning_path_rows(seed)
    with connection.transaction():
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_slug=tenant_slug, tenant_name=tenant_name)
            workspace_id = _upsert_workspace(
                cursor,
                tenant_id=tenant_id,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
            )
            learning_path_id = _upsert_learning_path(
                cursor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                row=rows.path,
            )
            step_ids_by_key = {
                row["step_key"]: _upsert_learning_step(cursor, learning_path_id=learning_path_id, row=row)
                for row in rows.steps
            }
            lab_task_ids_by_key: dict[str, str] = {}
            for row in rows.lab_tasks:
                step_id = step_ids_by_key[row["step_key"]]
                lab_task_ids_by_key[row["task_key"]] = _upsert_lab_task(cursor, learning_step_id=step_id, row=row)
            command_check_ids = tuple(
                _upsert_command_check(
                    cursor,
                    lab_task_id=lab_task_ids_by_key[row["task_key"]],
                    row=row,
                )
                for row in rows.command_checks
            )
    return StoredLearningPath(
        learning_path_id=learning_path_id,
        step_ids=tuple(step_ids_by_key.values()),
        lab_task_ids=tuple(lab_task_ids_by_key.values()),
        command_check_ids=command_check_ids,
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _upsert_tenant(cursor, *, tenant_slug: str, tenant_name: str) -> str:
    cursor.execute(
        """
        INSERT INTO tenants (slug, name)
        VALUES (%s, %s)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (tenant_slug, tenant_name),
    )
    return str(cursor.fetchone()[0])


def _upsert_workspace(cursor, *, tenant_id: str, workspace_slug: str, workspace_name: str) -> str:
    cursor.execute(
        """
        INSERT INTO workspaces (tenant_id, slug, name)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (tenant_id, workspace_slug, workspace_name),
    )
    return str(cursor.fetchone()[0])


def _upsert_learning_path(cursor, *, tenant_id: str, workspace_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO learning_paths (
            tenant_id, workspace_id, slug, title, description, audience, ocp_version,
            language, source_kind, source_ref, metadata, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (workspace_id, slug) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            audience = EXCLUDED.audience,
            ocp_version = EXCLUDED.ocp_version,
            language = EXCLUDED.language,
            source_kind = EXCLUDED.source_kind,
            source_ref = EXCLUDED.source_ref,
            metadata = EXCLUDED.metadata,
            updated_at = now()
        RETURNING id
        """,
        (
            tenant_id,
            workspace_id,
            row["slug"],
            row["title"],
            row["description"],
            row["audience"],
            row["ocp_version"],
            row["language"],
            row["source_kind"],
            row["source_ref"],
            _json(row["metadata"]),
        ),
    )
    return str(cursor.fetchone()[0])


def _upsert_learning_step(cursor, *, learning_path_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO learning_steps (
            learning_path_id, step_key, ordinal, title, objective, concept_slugs,
            prerequisite_step_keys, estimated_minutes, difficulty, lesson_markdown,
            metadata, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (learning_path_id, step_key) DO UPDATE SET
            ordinal = EXCLUDED.ordinal,
            title = EXCLUDED.title,
            objective = EXCLUDED.objective,
            concept_slugs = EXCLUDED.concept_slugs,
            prerequisite_step_keys = EXCLUDED.prerequisite_step_keys,
            estimated_minutes = EXCLUDED.estimated_minutes,
            difficulty = EXCLUDED.difficulty,
            lesson_markdown = EXCLUDED.lesson_markdown,
            metadata = EXCLUDED.metadata,
            updated_at = now()
        RETURNING id
        """,
        (
            learning_path_id,
            row["step_key"],
            row["ordinal"],
            row["title"],
            row["objective"],
            _json(row["concept_slugs"]),
            _json(row["prerequisite_step_keys"]),
            row["estimated_minutes"],
            row["difficulty"],
            row["lesson_markdown"],
            _json(row["metadata"]),
        ),
    )
    return str(cursor.fetchone()[0])


def _upsert_lab_task(cursor, *, learning_step_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO lab_tasks (
            learning_step_id, task_key, ordinal, title, goal_markdown, starter_context,
            expected_outcome, hint_markdown, metadata, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, now())
        ON CONFLICT (learning_step_id, task_key) DO UPDATE SET
            ordinal = EXCLUDED.ordinal,
            title = EXCLUDED.title,
            goal_markdown = EXCLUDED.goal_markdown,
            starter_context = EXCLUDED.starter_context,
            expected_outcome = EXCLUDED.expected_outcome,
            hint_markdown = EXCLUDED.hint_markdown,
            metadata = EXCLUDED.metadata,
            updated_at = now()
        RETURNING id
        """,
        (
            learning_step_id,
            row["task_key"],
            row["ordinal"],
            row["title"],
            row["goal_markdown"],
            _json(row["starter_context"]),
            _json(row["expected_outcome"]),
            row["hint_markdown"],
            _json(row["metadata"]),
        ),
    )
    return str(cursor.fetchone()[0])


def _upsert_command_check(cursor, *, lab_task_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO command_checks (
            lab_task_id, check_key, ordinal, command_pattern, expected_command,
            validation_kind, validation_payload, success_message, failure_hint, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
        ON CONFLICT (lab_task_id, check_key) DO UPDATE SET
            ordinal = EXCLUDED.ordinal,
            command_pattern = EXCLUDED.command_pattern,
            expected_command = EXCLUDED.expected_command,
            validation_kind = EXCLUDED.validation_kind,
            validation_payload = EXCLUDED.validation_payload,
            success_message = EXCLUDED.success_message,
            failure_hint = EXCLUDED.failure_hint,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (
            lab_task_id,
            row["check_key"],
            row["ordinal"],
            row["command_pattern"],
            row["expected_command"],
            row["validation_kind"],
            _json(row["validation_payload"]),
            row["success_message"],
            row["failure_hint"],
            _json(row["metadata"]),
        ),
    )
    return str(cursor.fetchone()[0])


__all__ = [
    "CommandCheckSeed",
    "LabTaskSeed",
    "LearningPathRows",
    "LearningPathSeed",
    "LearningStepSeed",
    "StoredLearningPath",
    "build_learning_path_rows",
    "persist_learning_path",
]
