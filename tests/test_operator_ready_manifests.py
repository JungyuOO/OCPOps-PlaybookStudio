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
    assert "LIGHTSPEED_KNOWLEDGE_MODE: lightspeed-rag-with-pbs-private-context" in config
    assert "BYOK" not in config
    assert 'QDRANT_ENABLED: "false"' in config
    assert 'TERMINAL_USER_WORKSPACE_ENABLED: "false"' in config
    assert 'PBS_OPERATOR_READY_MODE: "true"' in config


def test_sno_pbs_base_includes_mcp_and_ols_preview_without_byok() -> None:
    kustomization = read("deploy/sno/pbs/base/kustomization.yaml")
    assert "mcp.yaml" in kustomization
    assert "byok-builder-rbac.yaml" not in kustomization
    assert "olsconfig-patch-preview.yaml" in kustomization

    mcp = read("deploy/sno/pbs/base/mcp.yaml")
    assert "name: pbs-mcp" in mcp
    assert "play_book_studio.mcp.server" in mcp

    ols_preview = read("deploy/sno/pbs/base/olsconfig-patch-preview.yaml")
    assert "kind: OLSConfig" in ols_preview
    assert "MCPServer" in ols_preview
    assert "pbs-tools" in ols_preview
    assert "byoKnowledge" not in ols_preview
    assert "pbs-knowledge" not in ols_preview


def test_playbookstudio_crd_maps_phase1_operator_ready_spec() -> None:
    crd = read("deploy/sno/pbs-operator/config/crd-playbookstudio.yaml")
    sample = read("deploy/sno/pbs-operator/config/sample-playbookstudio.yaml")
    assert "kind: CustomResourceDefinition" in crd
    assert "playbookstudios.pbs.ocpops.io" in crd
    assert 'enum: ["internal", "lightspeed"]' in crd
    assert "lightspeed-rag-with-pbs-private-context" in crd
    assert "byoKnowledge" not in crd
    assert "byokLastBuild" not in crd
    assert "provider: lightspeed" in sample
    assert "knowledgeMode: lightspeed-rag-with-pbs-private-context" in sample
    assert "byoKnowledge" not in sample
    assert "autoCreate: false" in sample
    assert "qdrantEnabled: false" in sample
