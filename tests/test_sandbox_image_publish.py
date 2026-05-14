from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_defines_learner_sandbox_target() -> None:
    dockerfile = (REPO_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM registry.access.redhat.com/ubi9/ubi-minimal AS sandbox" in dockerfile
    assert "openshift-client-linux.tar.gz" in dockerfile
    assert "tar -xzf /tmp/openshift-client-linux.tar.gz -C /usr/local/bin oc kubectl" in dockerfile
    assert "learner:x:1001:0:learner:/home/learner:/bin/bash" in dockerfile
    assert "WORKDIR /home/learner" in dockerfile
    assert "USER 1001" in dockerfile
    assert 'CMD ["/bin/bash", "-lc", "sleep infinity"]' in dockerfile


def test_publish_workflow_pushes_sandbox_image() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "publish-images.yml").read_text(encoding="utf-8")

    assert "- target: sandbox" in workflow
    assert "image_name: ocpops-playbookstudio-sandbox" in workflow
    assert "target: ${{ matrix.target }}" in workflow
