from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.cli import _run_learning_seed_import, build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "learning_seed_cli_tests"


def test_learning_seed_import_parser_accepts_dry_run_args():
    args = build_parser().parse_args(
        [
            "learning-seed-import",
            "--root-dir",
            ".",
            "--guides-path",
            "data/course_pbs/manifests/ops_learning_guides_v1.json",
            "--tenant-slug",
            "ocp",
            "--workspace-slug",
            "training",
            "--dry-run",
        ]
    )

    assert args.command == "learning-seed-import"
    assert args.guides_path == Path("data/course_pbs/manifests/ops_learning_guides_v1.json")
    assert args.tenant_slug == "ocp"
    assert args.workspace_slug == "training"
    assert args.dry_run is True


def test_learning_seed_import_dry_run_outputs_summary(capsys):
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    guides_path = TEST_TMP / "ops_learning_guides_v1.json"
    guides_path.write_text(
        json.dumps(
            {
                "canonical_model": "ops_learning_guide_v1",
                "course_slug": "ocp-project-playbook",
                "title": "OCP guided course",
                "guides": [
                    {
                        "guide_id": "project_start",
                        "stage_id": "basics",
                        "steps": [
                            {
                                "step_id": "project-basics",
                                "card_text": "Project basics",
                                "learning_objective": "Understand projects.",
                                "answer_outline": ["Check the current project."],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        [
            "learning-seed-import",
            "--root-dir",
            str(REPO_ROOT),
            "--guides-path",
            str(guides_path),
            "--dry-run",
        ]
    )

    exit_code = _run_learning_seed_import(args)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["slug"] == "ocp-project-playbook"
    assert payload["step_count"] == 1
    assert payload["persisted"] is None
