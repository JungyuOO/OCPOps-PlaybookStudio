from __future__ import annotations

from play_book_studio.course.learning_path_seed import ops_learning_guides_to_seed


def test_ops_learning_guides_to_seed_converts_guides_to_ordered_steps():
    payload = {
        "canonical_model": "ops_learning_guide_v1",
        "course_slug": "ocp-project-playbook",
        "title": "OCP guided course",
        "guide_count": 1,
        "step_count": 1,
        "guides": [
            {
                "guide_id": "project_start",
                "stage_id": "basics",
                "steps": [
                    {
                        "step_id": "project-basics",
                        "card_text": "Project basics",
                        "user_query": "What should I check first?",
                        "learning_objective": "Understand the current project.",
                        "answer_outline": ["Check the active project.", "List workloads."],
                        "expected_terms": ["Project", "Namespace"],
                        "source_anchors": [{"chunk_id": "chunk-1"}],
                        "next_step_ids": ["pods"],
                    },
                ],
            },
        ],
    }

    seed = ops_learning_guides_to_seed(payload, source_ref="data/course_pbs/manifests/ops_learning_guides_v1.json")

    assert seed.slug == "ocp-project-playbook"
    assert seed.source_kind == "ops_learning_guides"
    assert len(seed.steps) == 1
    assert seed.steps[0].step_key == "project-basics"
    assert seed.steps[0].concept_slugs == ("project", "namespace")
    assert "Check the active project." in seed.steps[0].lesson_markdown
    assert seed.steps[0].metadata["source_anchor_chunk_ids"] == ["chunk-1"]
