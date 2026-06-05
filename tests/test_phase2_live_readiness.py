from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_phase2_readonly_inventory_script_uses_no_mutating_oc_commands() -> None:
    script = read("deploy/sno/scripts/phase2-readonly-inventory.sh")
    forbidden = [
        "oc apply",
        "oc patch",
        "oc delete",
        "oc create",
        "oc adm",
        "oc scale",
        "oc replace",
        "oc edit",
        "oc label",
        "oc annotate",
    ]
    for token in forbidden:
        assert token not in script
    assert "oc get secrets" in script
    assert "secrets-metadata" in script
    assert "-o yaml | oc" not in script


def test_phase2_runbook_keeps_live_mutation_behind_approval_gate() -> None:
    runbook = read("spec/v0.3.0/phase2-live-validation-runbook.md")
    assert "This document does not authorize destructive cleanup by itself" in runbook
    assert "Only after explicit live approval" in runbook
    assert "No secret data export" in runbook
    assert "admin123" not in runbook
    assert "Cywell0415" not in runbook


def test_phase2_runbook_names_expected_targets_without_credentials() -> None:
    runbook = read("spec/v0.3.0/phase2-live-validation-runbook.md")
    assert "https://api.ocp.cywell.local:6443" in runbook
    assert "https://playbookstudio.192.168.119.8.nip.io" in runbook
    assert "192.168.119.27" in runbook
    assert "password" in runbook.lower()
    assert "must be supplied" in runbook
