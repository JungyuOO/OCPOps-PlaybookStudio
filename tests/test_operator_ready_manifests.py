from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_sno_pbs_base_declares_v030_lightspeed_boundaries() -> None:
    config = read("deploy/sno/pbs/base/configmap.yaml")
    assert "CHAT_PROVIDER: lightspeed" in config
    assert 'PBS_AUTO_CREATE_NAMESPACE: "false"' in config
    assert "PBS_NAMESPACE_MODE: disabled" in config
    assert "CONSOLE_EXECUTOR_MODE: service-account" in config
    assert 'BYOK_PIPELINE_ENABLED: "true"' in config
    assert 'PBS_OPERATOR_READY_MODE: "true"' in config


def test_sno_pbs_base_includes_mcp_byok_and_ols_preview() -> None:
    kustomization = read("deploy/sno/pbs/base/kustomization.yaml")
    assert "mcp.yaml" in kustomization
    assert "byok-builder-rbac.yaml" in kustomization
    assert "olsconfig-patch-preview.yaml" in kustomization

    mcp = read("deploy/sno/pbs/base/mcp.yaml")
    assert "name: pbs-mcp" in mcp
    assert "play_book_studio.mcp.server" in mcp

    ols_preview = read("deploy/sno/pbs/base/olsconfig-patch-preview.yaml")
    assert "kind: OLSConfig" in ols_preview
    assert "MCPServer" in ols_preview
    assert "pbs-tools" in ols_preview
    assert "pbs-knowledge:v0.3.0" in ols_preview


def test_playbookstudio_crd_maps_phase1_operator_ready_spec() -> None:
    crd = read("deploy/sno/pbs-operator/config/crd-playbookstudio.yaml")
    sample = read("deploy/sno/pbs-operator/config/sample-playbookstudio.yaml")
    assert "kind: CustomResourceDefinition" in crd
    assert "playbookstudios.pbs.ocpops.io" in crd
    assert 'enum: ["internal", "lightspeed"]' in crd
    assert 'enum: ["dryRun", "manualApproval", "automatic"]' in crd
    assert "provider: lightspeed" in sample
    assert "autoCreate: false" in sample
    assert "qdrantEnabled: false" in sample
