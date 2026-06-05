from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATIONS_DIR = ROOT / "deploy" / "sno" / "gitops" / "applications"


def read(name: str) -> str:
    return (APPLICATIONS_DIR / name).read_text(encoding="utf-8")


def test_gitops_applications_cover_planner_targets() -> None:
    kustomization = read("kustomization.yaml")
    assert "pbs-base-application.yaml" in kustomization
    assert "pbs-operator-application.yaml" in kustomization
    assert "pbs-lightspeed-integration-application.yaml" in kustomization

    pbs = read("pbs-base-application.yaml")
    assert "path: deploy/sno/pbs/base" in pbs
    assert "namespace: pbs-ocpops" in pbs

    operator = read("pbs-operator-application.yaml")
    assert "path: deploy/sno/pbs-operator/config" in operator

    lightspeed = read("pbs-lightspeed-integration-application.yaml")
    assert "owner-boundary: openshift-lightspeed" in lightspeed
    assert "olsconfig-patch-preview.yaml" in lightspeed


def test_gitops_applications_are_approval_gated_not_automated() -> None:
    for path in APPLICATIONS_DIR.glob("*-application.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "pbs.ocpops.io/requires-approval: \"true\"" in text
        assert "automated:" not in text
        assert "prune:" not in text
        assert "selfHeal:" not in text
        assert "CreateNamespace=false" in text


def test_gitops_applications_do_not_embed_credentials_or_live_secrets() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in APPLICATIONS_DIR.glob("*.yaml"))
    forbidden = [
        "admin123",
        "Cywell0415",
        "password:",
        "token:",
        "ssh://",
        "192.168.119.27",
    ]
    for token in forbidden:
        assert token not in combined


def test_gitops_applications_pin_v030_lightspeed_branch() -> None:
    for path in APPLICATIONS_DIR.glob("*-application.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "repoURL: https://github.com/JungyuOO/OCPOps-PlaybookStudio.git" in text
        assert "targetRevision: v3.0.0/lightspeed" in text
