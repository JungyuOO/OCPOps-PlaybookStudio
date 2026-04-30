from __future__ import annotations

from play_book_studio.db.learning_repository import (
    CommandCheckSeed,
    LabTaskSeed,
    LearningPathSeed,
    LearningStepSeed,
    build_learning_path_rows,
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
