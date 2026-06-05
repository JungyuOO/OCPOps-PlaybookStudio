# PBS v0.3.0 Phase 2 Preparation Report

## Scope

Phase 2 preparation keeps live SNO/OCP mutation out of the repository workflow until an explicit
operator approval window exists. The work in this phase prepares the artifacts needed to inspect,
compare, and safely plan adoption of the currently running PBS, OpenShift Lightspeed, and OpenShift
AI resources.

## Added Artifacts

- `spec/v0.3.0/phase2-live-validation-runbook.md`
  - Defines the live validation sequence from read-only inventory through later approved mutation.
  - Records the known OCP API, Console, PBS route, and SNO host targets without committing secrets.
  - Separates PBS deployment validation from the future PBS Operator demonstration.
- `deploy/sno/scripts/phase2-readonly-inventory.sh`
  - Collects cluster, Operator, PBS, Lightspeed, and OpenShift AI resource state with read-only
    `oc get` and `oc whoami` commands.
  - Exports Secret metadata only, never Secret data.
  - Writes an artifact directory that can be compared against rendered repository manifests.
- `tests/test_phase2_live_readiness.py`
  - Guards the inventory script against mutating `oc` command patterns.
  - Guards the runbook against embedded credentials and premature live-success claims.
- `src/play_book_studio/cluster/live_inventory.py`
  - Classifies read-only live inventory against rendered repository desired state.
  - Produces `adopt`, `replace`, `remove`, and `external-owner` decisions matching the live cleanup
    boundary in `planner.md`.
- `tests/test_phase2_inventory_classification.py`
  - Covers PBS adoption, manual-test resource removal candidates, desired-but-missing replacements,
    and OpenShift Lightspeed/OLM external ownership.
- `deploy/sno/gitops/applications/*-application.yaml`
  - Adds approval-gated Argo CD Application previews for PBS base, PBS Operator config, and
    Lightspeed integration review.
  - Keeps automated sync, prune, and self-heal disabled until live inventory and mutation approval
    are complete.
- `tests/test_gitops_application_manifests.py`
  - Guards GitOps target paths, branch pinning, approval gating, and absence of embedded live
    credentials.
- `src/play_book_studio/pbs_operator/reconciler.py`
  - Renders Operator-managed desired resources from a `PlaybookStudio` CR without live mutation.
  - Maps CR fields to PBS runtime config, MCP, BYOK RBAC, Route, and OLSConfig preview resources.
- `src/play_book_studio/pbs_operator/runtime.py`
  - Provides a dry-run Operator process that can list/watch `PlaybookStudio` CRs through the
    in-cluster Kubernetes API and render desired state when changes are detected.
  - Includes gated server-side apply and status patch paths, disabled by default through
    `PBS_OPERATOR_APPLY_ENABLED=false`.
- `deploy/sno/pbs-operator/bundle/*` and `deploy/sno/pbs-operator/catalog/*`
  - Adds OLM bundle and CatalogSource preview structure without claiming OperatorHub validation.
  - Keeps the bundle CRD schema synchronized with `deploy/sno/pbs-operator/config/crd-playbookstudio.yaml`.
- `.github/workflows/publish-images.yml` and `deploy/Dockerfile`
  - Add `operator`, `operator-bundle`, and `operator-catalog` image targets to the GHCR publish
    pipeline.
  - Keep the Operator Deployment and CSV aligned to
    `ghcr.io/jungyuoo/ocpops-playbookstudio-operator:v0.3.0`.
- `tests/test_pbs_operator_runtime.py`, `tests/test_pbs_operator_reconciler.py`, and
  `tests/test_pbs_operator_bundle.py`
  - Guard in-cluster watch URL/config construction, CR event detection, CR-to-resource rendering,
    gated server-side apply requests, status patch requests, dry-run status claims, Operator
    Deployment/RBAC, bundle preview, and credential-free catalog preview.

## Verification Evidence

These checks were run locally without SSH, live `oc`, or cluster mutation:

```bash
.venv/Scripts/python.exe -m pytest tests/test_phase2_live_readiness.py tests/test_operator_ready_manifests.py
.venv/Scripts/python.exe -m pytest tests/test_phase2_inventory_classification.py
.venv/Scripts/python.exe -m pytest tests/test_gitops_application_manifests.py
.venv/Scripts/python.exe -m pytest tests/test_pbs_operator_runtime.py tests/test_pbs_operator_reconciler.py tests/test_pbs_operator_bundle.py
bash -n deploy/sno/scripts/phase2-readonly-inventory.sh
kubectl kustomize deploy/sno/pbs/base
kubectl kustomize deploy/sno/pbs-operator/config
kubectl kustomize deploy/sno/gitops/applications
.venv/Scripts/python.exe -m play_book_studio.pbs_operator.reconciler --help
docker build --target operator-bundle -f deploy/Dockerfile .
docker build --target operator-catalog -f deploy/Dockerfile .
```

Result:

- Phase 2 and Operator manifest tests: `6 passed`.
- Phase 2 inventory classification tests: `2 passed`.
- Phase 2 inventory classification CLI help: passed.
- GitOps Application manifest tests: `4 passed`.
- PBS Operator runtime/reconciler/bundle tests: `12 passed`.
- Operator image pipeline tests: `2 passed`.
- PBS Operator reconciler CLI help: passed.
- Operator bundle image target build: passed.
- Operator catalog image target build: passed.
- Read-only inventory script syntax: passed.
- PBS base manifest rendering: passed.
- PBS Operator config rendering: passed.
- GitOps Application manifest rendering: passed.

## Remaining Gaps

- Live read-only inventory has not been executed.
- Live SSH, `oc apply`, `oc patch`, `oc delete`, Operator reinstall, and PBS redeployment have not
  been authorized or performed.
- The PBS Operator now has reconcile core, in-cluster CR watch detection, gated server-side apply,
  status patch paths, Operator Deployment/RBAC, bundle preview, and catalog preview. Live validation
  against the SNO cluster remains future work.
- Lightspeed BYOK has repository-side document conversion/export/patch-preview support, but live
  BYOK ingestion must be validated against the installed OpenShift Lightspeed version later.
- SNO SSH read-only probe confirmed `oc` client availability on `192.168.119.27` and current server
  target `https://api.ocp.cywell.local:6443`; live mutation has not been executed.
