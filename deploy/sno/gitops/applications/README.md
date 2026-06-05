# GitOps Application Boundary

Future v0.3.0+ live work should wire these SNO manifests through OpenShift GitOps or Argo CD rather
than direct server-only state.

Target flow:

1. Merge to the protected branch.
2. GitHub Actions builds PBS app/web images and future operator bundle/catalog images.
3. GitOps reconciles `deploy/sno/pbs/base`, Lightspeed integration previews, and PBS Operator config.
4. Live cluster cleanup, install, and validation happen only in an explicitly authorized phase.

This directory intentionally contains no live cluster credentials or destination server secrets.

## Phase 2 Preview Applications

- `pbs-base-application.yaml` points Argo CD at the Operator-ready PBS app, MCP, Route, Service,
  and RBAC base.
- `pbs-operator-application.yaml` points Argo CD at the future PBS Operator CRD/sample config.
- `pbs-lightspeed-integration-application.yaml` points Argo CD at the PBS-generated Lightspeed
  integration preview so `OLSConfig` changes remain reviewable before any live mutation.

These Applications intentionally omit automated sync, prune, and self-heal settings. Apply them only
after the live inventory has been reviewed, current resources have been classified as
`adopt`/`replace`/`remove`/`external-owner`, and the operator approves the mutation window.
