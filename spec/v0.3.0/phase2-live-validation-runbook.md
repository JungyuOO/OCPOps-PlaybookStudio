# PBS v0.3.0 Phase 2 Live Validation Runbook

## Purpose

Phase 2 moves from local readiness to controlled SNO/OCP validation. This runbook is intentionally
split into read-only preflight, explicit approval gates, and later mutation windows.

This document does not authorize destructive cleanup by itself. Live mutation requires an explicit
operator decision at the time of execution.

## Environment Targets

- OCP Console URL: `https://console-openshift-console.apps.ocp.cywell.local/dashboards`
- OCP API address: `https://api.ocp.cywell.local:6443`
- Current PBS route: `https://playbookstudio.192.168.119.8.nip.io`
- SNO Linux host: `192.168.119.27`

Credentials, passwords, tokens, kubeconfigs, registry credentials, and `.env` values must be supplied
through a protected operator shell, OpenShift Secrets, GitHub Actions Secrets, or protected server-side
files. Do not commit them to this repository.

## Phase 2 Stages

### Stage 0: Repository Cleanliness

1. Review the Phase 1 diff.
2. Commit or otherwise preserve Phase 1 before touching live environments.
3. Confirm local verification still passes:

```bash
.venv/Scripts/python.exe -m pytest tests/test_v030_config_boundaries.py tests/test_lightspeed_provider.py tests/test_aiops_event_timeline.py tests/test_ops_console_api.py tests/test_terminal_session.py tests/test_terminal_ws_learning_events.py tests/test_mcp_boundary.py tests/test_operator_ready_manifests.py tests/test_upload_api.py tests/test_app_server.py
cd apps/web && npm run build && npm test
kubectl kustomize deploy/sno/pbs/base
kubectl kustomize deploy/sno/pbs-operator/config
```

### Stage 1: Read-Only Live Inventory

Run only read-only inventory commands first. The script below must not patch, apply, delete, create,
scale, annotate, label, or mutate resources:

```bash
bash deploy/sno/scripts/phase2-readonly-inventory.sh ./artifacts/phase2-inventory
```

Collect:

- PBS namespace resources.
- OpenShift Lightspeed Operator and `OLSConfig` state.
- OpenShift AI Operator and operand state.
- Routes, Services, Deployments, Pods, Events, CSVs, Subscriptions, InstallPlans, and OperatorGroups.
- Secret names and metadata only, never secret data.

### Stage 2: Diff And Adoption Decision

Compare live inventory against repository desired state:

```bash
kubectl kustomize deploy/sno/pbs/base > ./artifacts/phase2-inventory/desired-pbs.yaml
kubectl kustomize deploy/sno/pbs-operator/config > ./artifacts/phase2-inventory/desired-pbs-operator.yaml
.venv/Scripts/python.exe -m play_book_studio.cluster.live_inventory \
  --inventory-dir ./artifacts/phase2-inventory \
  --desired ./artifacts/phase2-inventory/desired-pbs.yaml ./artifacts/phase2-inventory/desired-pbs-operator.yaml \
  --output ./artifacts/phase2-inventory/classification-report.json
```

Classify every live resource as:

- `adopt`: keep and bring under GitOps/Operator management.
- `replace`: back up, then replace during an approved mutation window.
- `remove`: back up, then delete only if confirmed unused and conflicting.
- `external-owner`: owned by OpenShift AI, OpenShift Lightspeed, OLM, or another platform operator.

### Stage 3: CI/CD And Image Readiness

1. Confirm GitHub Actions built the app/web/sandbox images for the intended branch or tag.
2. Confirm GHCR image tags and digests.
3. Update desired manifests or overlays to point to the approved immutable image tags.
4. Do not use mutable `dev` tags for final validation unless the validation is explicitly a dev smoke.

### Stage 4: Lightspeed And Private Context Readiness

1. Inventory installed OpenShift Lightspeed Operator resources.
2. Confirm the expected OLS app server service or route.
3. Validate PBS `OLS_BASE_URL` against that endpoint.
4. Upload a test private document and confirm PBS private retrieval can return it.
5. Prepare `OLSConfig` MCP patch from repository preview.
6. Register MCP only if the installed Lightspeed version supports the MCP feature gate.

### Stage 5: PBS Deployment Validation

Only after explicit live approval:

1. Back up current PBS resources to the inventory artifact directory.
2. Apply the approved manifest source.
3. Watch rollout status for PBS app, web, and optional MCP server.
4. Verify the route and `/api/health`.
5. Verify `CHAT_PROVIDER=lightspeed`, namespace auto-create disabled, and terminal event capture.
6. Upload a test document, confirm private retrieval, and verify it can be attached to Lightspeed context.
7. Ask Lightspeed a question using official docs, customer docs, and recent CLI/YAML context.

### Stage 6: Operator Demonstration Path

The PBS Operator demonstration is not complete until:

1. The `PlaybookStudio` CRD is installed.
2. A controller reconciles Deployment, Service, Route, ConfigMap, Secret references, RBAC, MCP,
   and OLS integration status.
3. Deleting/recreating the custom resource produces the expected PBS state.
4. OpenShift Lightspeed removal/reinstall/reconnect is demonstrated in a controlled window.

The current Phase 1/2 repository state includes a CRD/sample and Operator-ready manifests, not a
production controller.

## Approval Gates

Use these gates before mutation:

- Inventory reviewed and backed up.
- Desired manifests rendered and reviewed.
- Secrets available through protected channels.
- Rollback commands prepared.
- Maintenance/demo window approved.
- Live operator confirms which resources may be deleted or replaced.

## Non-Goals For Read-Only Preflight

- No SSH command execution.
- No `oc apply`, `oc patch`, `oc delete`, `oc create`, `oc adm policy`, `oc scale`, or equivalent mutation.
- No secret data export.
- No claim that Operator E2E succeeded.
