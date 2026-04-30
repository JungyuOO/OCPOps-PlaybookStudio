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


@dataclass(frozen=True, slots=True)
class LearningPathSummary:
    learning_path_id: str
    slug: str
    title: str
    audience: str
    ocp_version: str
    language: str
    step_count: int
    lab_task_count: int
    command_check_count: int


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


def list_learning_path_summaries(
    connection,
    *,
    workspace_slug: str = "default",
    limit: int = 50,
) -> tuple[LearningPathSummary, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                lp.id,
                lp.slug,
                lp.title,
                lp.audience,
                lp.ocp_version,
                lp.language,
                COUNT(DISTINCT ls.id) AS step_count,
                COUNT(DISTINCT lt.id) AS lab_task_count,
                COUNT(DISTINCT cc.id) AS command_check_count
            FROM learning_paths lp
            LEFT JOIN workspaces w ON w.id = lp.workspace_id
            LEFT JOIN learning_steps ls ON ls.learning_path_id = lp.id
            LEFT JOIN lab_tasks lt ON lt.learning_step_id = ls.id
            LEFT JOIN command_checks cc ON cc.lab_task_id = lt.id
            WHERE w.slug = %s OR lp.workspace_id IS NULL
            GROUP BY lp.id
            ORDER BY lp.updated_at DESC, lp.created_at DESC
            LIMIT %s
            """,
            (workspace_slug, int(limit)),
        )
        return tuple(
            LearningPathSummary(
                learning_path_id=str(row[0]),
                slug=str(row[1]),
                title=str(row[2]),
                audience=str(row[3]),
                ocp_version=str(row[4]),
                language=str(row[5]),
                step_count=int(row[6] or 0),
                lab_task_count=int(row[7] or 0),
                command_check_count=int(row[8] or 0),
            )
            for row in cursor.fetchall()
        )


def load_ops_learning_guides_payload(
    connection,
    *,
    workspace_slug: str = "default",
    path_slug: str = "",
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                lp.slug,
                lp.title,
                lp.source_ref,
                ls.step_key,
                ls.ordinal,
                ls.title,
                ls.objective,
                ls.lesson_markdown,
                ls.metadata
            FROM learning_paths lp
            LEFT JOIN workspaces w ON w.id = lp.workspace_id
            JOIN learning_steps ls ON ls.learning_path_id = lp.id
            WHERE (w.slug = %s OR lp.workspace_id IS NULL)
              AND (%s = '' OR lp.slug = %s)
            ORDER BY lp.updated_at DESC, lp.created_at DESC, ls.ordinal ASC
            """,
            (workspace_slug, path_slug, path_slug),
        )
        rows = cursor.fetchall()
    if not rows:
        return {"canonical_model": "ops_learning_guide_v1", "guides": []}

    path_slug_value = str(rows[0][0] or "")
    path_title = str(rows[0][1] or "")
    source_ref = str(rows[0][2] or "")
    guides_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = row[8] if isinstance(row[8], dict) else {}
        guide_id = str(metadata.get("guide_id") or "guided_learning").strip() or "guided_learning"
        guide = guides_by_id.setdefault(
            guide_id,
            {
                "guide_id": guide_id,
                "stage_id": str(metadata.get("stage_id") or ""),
                "title": path_title,
                "audience": "beginner",
                "learning_goal": "",
                "steps": [],
            },
        )
        guide["steps"].append(
            {
                "step_id": str(row[3] or ""),
                "guide_id": guide_id,
                "stage_id": str(metadata.get("stage_id") or ""),
                "card_text": str(row[5] or ""),
                "user_query": str(metadata.get("user_query") or ""),
                "learning_objective": str(row[6] or ""),
                "answer_outline": _outline_from_lesson_markdown(str(row[7] or "")),
                "source_anchors": [
                    {"chunk_id": chunk_id, "anchor_role": "primary"}
                    for chunk_id in metadata.get("source_anchor_chunk_ids", [])
                    if str(chunk_id).strip()
                ],
                "next_step_ids": metadata.get("next_step_ids") if isinstance(metadata.get("next_step_ids"), list) else [],
                "quality": metadata.get("quality") if isinstance(metadata.get("quality"), dict) else {},
            }
        )
    guides = list(guides_by_id.values())
    return {
        "canonical_model": "ops_learning_guide_v1",
        "course_slug": path_slug_value,
        "title": path_title,
        "source_manifest": source_ref,
        "guide_count": len(guides),
        "step_count": sum(len(guide["steps"]) for guide in guides),
        "guides": guides,
    }


def load_learning_path_catalog(
    connection,
    *,
    workspace_slug: str = "default",
    slug: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                lp.id,
                lp.slug,
                lp.title,
                lp.description,
                lp.audience,
                lp.ocp_version,
                lp.language,
                lp.source_kind,
                lp.source_ref,
                lp.metadata,
                ls.id,
                ls.step_key,
                ls.ordinal,
                ls.title,
                ls.objective,
                ls.concept_slugs,
                ls.prerequisite_step_keys,
                ls.estimated_minutes,
                ls.difficulty,
                ls.lesson_markdown,
                ls.metadata,
                lt.id,
                lt.task_key,
                lt.ordinal,
                lt.title,
                lt.goal_markdown,
                lt.starter_context,
                lt.expected_outcome,
                lt.hint_markdown,
                lt.metadata,
                cc.id,
                cc.check_key,
                cc.ordinal,
                cc.command_pattern,
                cc.expected_command,
                cc.validation_kind,
                cc.validation_payload,
                cc.success_message,
                cc.failure_hint,
                cc.metadata
            FROM learning_paths lp
            LEFT JOIN workspaces w ON w.id = lp.workspace_id
            LEFT JOIN learning_steps ls ON ls.learning_path_id = lp.id
            LEFT JOIN lab_tasks lt ON lt.learning_step_id = ls.id
            LEFT JOIN command_checks cc ON cc.lab_task_id = lt.id
            WHERE (w.slug = %s OR lp.workspace_id IS NULL)
              AND (%s = '' OR lp.slug = %s)
            ORDER BY lp.updated_at DESC, lp.created_at DESC, ls.ordinal ASC, lt.ordinal ASC, cc.ordinal ASC
            LIMIT %s
            """,
            (workspace_slug, slug, slug, max(1, int(limit)) * 1000),
        )
        rows = cursor.fetchall()

    paths: dict[str, dict[str, Any]] = {}
    steps_by_path: dict[str, dict[str, dict[str, Any]]] = {}
    tasks_by_step: dict[str, dict[str, dict[str, Any]]] = {}
    checks_by_task: dict[str, set[str]] = {}
    for row in rows:
        path_id = str(row[0] or "")
        if not path_id:
            continue
        path = paths.setdefault(
            path_id,
            {
                "id": path_id,
                "slug": str(row[1] or ""),
                "title": str(row[2] or ""),
                "description": str(row[3] or ""),
                "audience": str(row[4] or ""),
                "ocp_version": str(row[5] or ""),
                "language": str(row[6] or ""),
                "source_kind": str(row[7] or ""),
                "source_ref": str(row[8] or ""),
                "metadata": _json_value(row[9], {}),
                "steps": [],
            },
        )
        step_id = str(row[10] or "")
        if not step_id:
            continue
        path_steps = steps_by_path.setdefault(path_id, {})
        step = path_steps.get(step_id)
        if step is None:
            step = {
                "id": step_id,
                "step_key": str(row[11] or ""),
                "ordinal": int(row[12] or 0),
                "title": str(row[13] or ""),
                "objective": str(row[14] or ""),
                "concept_slugs": _json_value(row[15], []),
                "prerequisite_step_keys": _json_value(row[16], []),
                "estimated_minutes": int(row[17] or 0),
                "difficulty": str(row[18] or ""),
                "lesson_markdown": str(row[19] or ""),
                "metadata": _json_value(row[20], {}),
                "lab_tasks": [],
            }
            path_steps[step_id] = step
            path["steps"].append(step)

        task_id = str(row[21] or "")
        if not task_id:
            continue
        step_tasks = tasks_by_step.setdefault(step_id, {})
        task = step_tasks.get(task_id)
        if task is None:
            task = {
                "id": task_id,
                "task_key": str(row[22] or ""),
                "ordinal": int(row[23] or 0),
                "title": str(row[24] or ""),
                "goal_markdown": str(row[25] or ""),
                "starter_context": _json_value(row[26], {}),
                "expected_outcome": _json_value(row[27], {}),
                "hint_markdown": str(row[28] or ""),
                "metadata": _json_value(row[29], {}),
                "command_checks": [],
            }
            step_tasks[task_id] = task
            step["lab_tasks"].append(task)

        check_id = str(row[30] or "")
        if not check_id:
            continue
        task_checks = checks_by_task.setdefault(task_id, set())
        if check_id in task_checks:
            continue
        task_checks.add(check_id)
        task["command_checks"].append(
            {
                "id": check_id,
                "check_key": str(row[31] or ""),
                "ordinal": int(row[32] or 0),
                "command_pattern": str(row[33] or ""),
                "expected_command": str(row[34] or ""),
                "validation_kind": str(row[35] or ""),
                "validation_payload": _json_value(row[36], {}),
                "success_message": str(row[37] or ""),
                "failure_hint": str(row[38] or ""),
                "metadata": _json_value(row[39], {}),
            }
        )
    return {
        "schema": "learning_path_catalog_v1",
        "source": "postgres.learning_paths",
        "count": len(paths),
        "paths": list(paths.values())[: max(1, int(limit))],
    }


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


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _outline_from_lesson_markdown(markdown: str) -> list[str]:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
    return lines


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
    "LearningPathSummary",
    "LearningStepSeed",
    "StoredLearningPath",
    "build_learning_path_rows",
    "list_learning_path_summaries",
    "load_learning_path_catalog",
    "load_ops_learning_guides_payload",
    "persist_learning_path",
]
