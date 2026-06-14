from __future__ import annotations

from play_book_studio.db.learning_repository import (
    CommandCheckSeed,
    LabTaskSeed,
    LearningPathSeed,
    LearningStepSeed,
    build_learning_path_rows,
    load_ops_learning_chunks_payload,
)


def test_build_learning_path_rows_preserves_labs_and_command_checks():
    seed = LearningPathSeed(
        slug="ocp-beginner",
        title="OCP Beginner Path",
        description="Guided OpenShift practice",
        audience="beginner",
        ocp_version="4.20",
        steps=(
            LearningStepSeed(
                step_key="project-basics",
                ordinal=1,
                title="Project basics",
                objective="Understand projects and namespaces",
                concept_slugs=("project", "namespace"),
                estimated_minutes=15,
                lesson_markdown="## Projects",
                lab_tasks=(
                    LabTaskSeed(
                        task_key="inspect-project",
                        ordinal=1,
                        title="Inspect the current project",
                        goal_markdown="Run the command that shows the active project.",
                        expected_outcome={"resource": "project"},
                        command_checks=(
                            CommandCheckSeed(
                                check_key="oc-project",
                                ordinal=1,
                                expected_command="oc project",
                                command_pattern=r"^oc\s+project$",
                                success_message="Active project displayed.",
                                failure_hint="Use oc project without extra arguments.",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    rows = build_learning_path_rows(seed)

    assert rows.path["slug"] == "ocp-beginner"
    assert rows.steps[0]["concept_slugs"] == ["project", "namespace"]
    assert rows.lab_tasks[0]["step_key"] == "project-basics"
    assert rows.lab_tasks[0]["expected_outcome"] == {"resource": "project"}
    assert rows.command_checks[0]["task_key"] == "inspect-project"
    assert rows.command_checks[0]["expected_command"] == "oc project"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_load_ops_learning_chunks_payload_rebuilds_runtime_learning_chunks():
    connection = FakeConnection(
        [
            (
                "ocp-guided-learning",
                "OCP Guided Learning",
                "beginner_operator",
                {"canonical_model": "ops_learning_guide_v1"},
                "route-basics",
                1,
                "Route basics",
                "Understand how Routes expose Services",
                "## Route basics\n\n- Check the Service first\n- Then inspect the Route",
                {
                    "guide_id": "networking",
                    "stage_id": "networking",
                    "user_query": "route와 service 차이",
                    "source_anchor_chunk_ids": ["source-1"],
                    "next_step_ids": ["ingress-basics"],
                    "quality": {"status": "seeded"},
                },
            )
        ]
    )

    chunks = load_ops_learning_chunks_payload(connection, workspace_slug="default")

    assert len(chunks) == 1
    assert chunks[0]["canonical_model"] == "ops_learning_chunk_v1"
    assert chunks[0]["learning_chunk_id"] == "networking::route-basics"
    assert chunks[0]["guide_id"] == "networking"
    assert chunks[0]["step_id"] == "route-basics"
    assert chunks[0]["stage_id"] == "networking"
    assert chunks[0]["learning_goal"] == "Understand how Routes expose Services"
    assert chunks[0]["source_chunk_ids"] == ["source-1"]
    assert chunks[0]["query_variants"] == ["route와 service 차이", "Route basics", "Understand how Routes expose Services"]
    assert chunks[0]["operational_sequence"] == ["Check the Service first", "Then inspect the Route"]
    assert chunks[0]["source"] == "postgres.learning_steps"
