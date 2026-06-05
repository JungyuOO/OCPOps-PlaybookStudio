# SNO Declarative Layout

This directory is the v0.3.0 source-of-truth staging area for future SNO GitOps
and PBS Operator work. Phase 1 does not apply these manifests to a live cluster.

## Boundaries

- `pbs/base`: Operator-ready PBS app, MCP, BYOK, OLS integration, Service, Route, and RBAC manifests.
- `pbs-operator/config`: CRD and sample `PlaybookStudio` custom resource sketch for a future operator.
- `lightspeed/base`: PBS-owned `OLSConfig` integration preview only. The Lightspeed Operator remains owned by its own lifecycle.
- `openshift-ai/base`: Reserved boundary for OpenShift AI install/inference manifests owned outside PBS.
- `gitops/applications`: Reserved boundary for Argo CD/ApplicationSet wiring.

No passwords, kubeconfigs, registry credentials, admin credentials, or server-side `.env` values belong
in this tree. Use OpenShift Secrets, GitHub Actions secrets, or protected server runtime files later.

## Phase 1 Verification

Use local-only render checks such as:

```bash
kubectl kustomize deploy/sno/pbs/base
```

Do not run `oc apply`, `oc patch`, `oc delete`, or SSH-based live validation during Phase 1.
