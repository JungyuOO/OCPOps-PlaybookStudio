from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_seed_commands_do_not_run_runtime_starter_enrichment() -> None:
    for path in (
        "deploy/openshift/job-official-corpus-seed.yaml",
        "deploy/docker-compose.prod.yml",
        "deploy/docker-compose.image.yml",
    ):
        command = _text(path)
        assert "official-gold-import" in command
        assert "--enrich-runtime-metadata" not in command
