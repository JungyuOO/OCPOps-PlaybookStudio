from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_declares_operator_bundle_and_catalog_targets() -> None:
    dockerfile = read("deploy/Dockerfile")

    assert "FROM python:3.11-slim AS operator" in dockerfile
    assert "PYTHONPATH=/app/src" in dockerfile
    assert "COPY src/play_book_studio /app/src/play_book_studio" in dockerfile
    assert "play_book_studio.pbs_operator.runtime" in dockerfile
    assert "FROM scratch AS operator-bundle" in dockerfile
    assert "COPY deploy/sno/pbs-operator/bundle/manifests /manifests" in dockerfile
    assert "FROM quay.io/operator-framework/opm:latest AS operator-catalog" in dockerfile
    assert "COPY deploy/sno/pbs-operator/catalog/catalog.yaml /configs/catalog.yaml" in dockerfile
    assert 'CMD ["serve", "/configs"]' in dockerfile


def test_publish_workflow_builds_operator_images() -> None:
    workflow = read(".github/workflows/publish-images.yml")

    assert "target: operator" in workflow
    assert "image_name: ocpops-playbookstudio-operator" in workflow
    assert "target: operator-bundle" in workflow
    assert "image_name: ocpops-playbookstudio-operator-bundle" in workflow
    assert "target: operator-catalog" in workflow
    assert "image_name: ocpops-playbookstudio-operator-catalog" in workflow
    assert "deploy/sno/pbs-operator/**" in workflow
