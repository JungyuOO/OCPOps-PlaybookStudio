from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_operator_config_includes_runtime_deployment_and_rbac() -> None:
    kustomization = read("deploy/sno/pbs-operator/config/kustomization.yaml")
    deployment = read("deploy/sno/pbs-operator/config/operator-deployment.yaml")
    rbac = read("deploy/sno/pbs-operator/config/operator-rbac.yaml")

    assert "operator-deployment.yaml" in kustomization
    assert "operator-rbac.yaml" in kustomization
    assert "play_book_studio.pbs_operator.runtime" in deployment
    assert "ghcr.io/jungyuoo/ocpops-playbookstudio-operator:v0.3.0" in deployment
    assert "PBS_OPERATOR_MODE" in deployment
    assert "PBS_OPERATOR_WATCH_ENABLED" in deployment
    assert "PBS_OPERATOR_APPLY_ENABLED" in deployment
    assert "value: \"false\"" in deployment
    assert "playbookstudios/status" in rbac
    assert "resources:" in rbac


def test_operator_bundle_and_catalog_preview_exist_without_live_credentials() -> None:
    csv = read("deploy/sno/pbs-operator/bundle/manifests/playbookstudio.clusterserviceversion.yaml")
    annotations = read("deploy/sno/pbs-operator/bundle/metadata/annotations.yaml")
    catalog = read("deploy/sno/pbs-operator/catalog/catalogsource-preview.yaml")
    combined = "\n".join([csv, annotations, catalog])

    assert "kind: ClusterServiceVersion" in csv
    assert "playbookstudio-operator.v0.3.0" in csv
    assert "play_book_studio.pbs_operator.runtime" in csv
    assert "ghcr.io/jungyuoo/ocpops-playbookstudio-operator:v0.3.0" in csv
    assert "PBS_OPERATOR_WATCH_ENABLED" in csv
    assert "PBS_OPERATOR_APPLY_ENABLED" in csv
    assert "operators.operatorframework.io.bundle.package.v1: playbookstudio-operator" in annotations
    assert "kind: CatalogSource" in catalog
    assert "pbs.ocpops.io/requires-approval: \"true\"" in catalog
    assert "admin123" not in combined
    assert "Cywell0415" not in combined
    assert "192.168.119.27" not in combined


def test_operator_bundle_crd_is_synced_with_config_crd() -> None:
    config_crd = read("deploy/sno/pbs-operator/config/crd-playbookstudio.yaml")
    bundle_crd = read("deploy/sno/pbs-operator/bundle/manifests/playbookstudio.crd.yaml")

    assert bundle_crd == config_crd
    assert "provider:" in bundle_crd
    assert "enum: [\"internal\", \"lightspeed\"]" in bundle_crd
    assert "manageOLSConfig:" in bundle_crd
    assert "mcpRegistered:" in bundle_crd


def test_operator_catalog_fbc_references_bundle_image() -> None:
    catalog = read("deploy/sno/pbs-operator/catalog/catalog.yaml")
    catalog_source = read("deploy/sno/pbs-operator/catalog/catalogsource-preview.yaml")

    assert "schema: olm.package" in catalog
    assert "name: playbookstudio-operator" in catalog
    assert "schema: olm.channel" in catalog
    assert "schema: olm.bundle" in catalog
    assert "playbookstudio-operator.v0.3.0" in catalog
    assert "ghcr.io/jungyuoo/ocpops-playbookstudio-operator-bundle:v0.3.0" in catalog
    assert "ghcr.io/jungyuoo/ocpops-playbookstudio-operator-catalog:v0.3.0" in catalog_source


def test_operator_olm_install_preview_is_manual_approval() -> None:
    kustomization = read("deploy/sno/pbs-operator/olm-install/kustomization.yaml")
    subscription = read("deploy/sno/pbs-operator/olm-install/subscription.yaml")
    operator_group = read("deploy/sno/pbs-operator/olm-install/operatorgroup.yaml")

    assert "catalogsource-preview.yaml" in kustomization
    assert "subscription.yaml" in kustomization
    assert "operatorgroup.yaml" in kustomization
    assert "installPlanApproval: Manual" in subscription
    assert "source: playbookstudio-operator-preview" in subscription
    assert "sourceNamespace: openshift-marketplace" in subscription
    assert "targetNamespaces:" in operator_group
    assert "pbs-ocpops" in operator_group
