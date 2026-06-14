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


def test_active_deploy_files_do_not_reference_qdrant() -> None:
    for path in (
        "docker-compose.yml",
        ".env.production.example",
        ".gitignore",
        "deploy/docker-compose.prod.yml",
        "deploy/docker-compose.image.yml",
        "deploy/DEPLOY.md",
        "deploy/openshift/README.md",
        "deploy/openshift/core.yaml",
        "deploy/openshift/kustomization.yaml",
        "deploy/openshift/job-official-corpus-seed.yaml",
        "deploy/openshift/job-kmsc-corpus-seed.yaml",
    ):
        assert "qdrant" not in _text(path).lower()


def test_deploy_database_url_uses_postgres_env_components() -> None:
    for path in (
        "docker-compose.yml",
        "deploy/docker-compose.prod.yml",
        "deploy/docker-compose.image.yml",
        "deploy/openshift/app.yaml",
        "deploy/openshift/job-db-migrate.yaml",
        "deploy/openshift/job-official-corpus-seed.yaml",
        "deploy/openshift/job-kmsc-corpus-seed.yaml",
        "deploy/openshift/job-learning-seed.yaml",
        "deploy/openshift/job-course-runtime-seed.yaml",
    ):
        text = _text(path)
        assert "postgresql://admin:" not in text
        assert "admin123" not in text
        assert "POSTGRES_USER" in text
        assert "POSTGRES_PASSWORD" in text
        assert "POSTGRES_DB" in text


def test_prod_kmsc_seed_build_context_points_to_repo_root() -> None:
    text = _text("deploy/docker-compose.prod.yml")
    assert "kmsc-corpus-seed:" in text
    assert "context: .." in text
    assert "dockerfile: deploy/Dockerfile" in text


def test_root_compose_allows_isolated_postgres_bind_port() -> None:
    text = _text("docker-compose.yml")
    assert "${POSTGRES_BIND:-127.0.0.1:5432}:5432" in text
