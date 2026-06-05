# PBS v0.3.0 Phase 1 Implementation Report

## Scope

This report covers local Phase 1 readiness for the PBS v0.3.0 Lightspeed AIOps Workbench.
It does not claim live SNO/OCP deployment, live SSH, live `oc apply`, live Lightspeed Operator,
live BYOK image build, or Operator E2E success.

## Changed Files

### Backend

- `src/play_book_studio/config/settings.py`
- `src/play_book_studio/answering/lightspeed_provider.py`
- `src/play_book_studio/http/server_chat.py`
- `src/play_book_studio/http/upload_api.py`
- `src/play_book_studio/http/terminal_ws.py`
- `src/play_book_studio/http/ops_console_api.py`
- `src/play_book_studio/aiops/__init__.py`
- `src/play_book_studio/aiops/event_timeline.py`
- `src/play_book_studio/byok/__init__.py`
- `src/play_book_studio/byok/operational_markdown.py`
- `src/play_book_studio/mcp/__init__.py`
- `src/play_book_studio/mcp/boundary.py`
- `src/play_book_studio/mcp/server.py`
- `src/play_book_studio/pbs_operator/__init__.py`
- `src/play_book_studio/pbs_operator/reconciler.py`
- `src/play_book_studio/pbs_operator/runtime.py`

### Frontend

- `apps/web/src/lib/opsConsoleApi.ts`
- `apps/web/src/pages/WorkspacePage.tsx`
- `apps/web/src/pages/WorkspacePage.css`

### Deploy And Specs

- `spec/v0.3.0/planner.md`
- `spec/v0.3.0/implementation-report.md`
- `deploy/sno/README.md`
- `deploy/sno/pbs/base/*`
- `deploy/sno/pbs-operator/config/*`
- `deploy/sno/pbs-operator/bundle/*`
- `deploy/sno/pbs-operator/catalog/*`
- `.github/workflows/publish-images.yml`
- `deploy/Dockerfile`
- `deploy/sno/lightspeed/base/README.md`
- `deploy/sno/openshift-ai/base/README.md`
- `deploy/sno/gitops/applications/README.md`

### Tests

- `tests/test_v030_config_boundaries.py`
- `tests/test_lightspeed_provider.py`
- `tests/test_byok_operational_markdown.py`
- `tests/test_aiops_event_timeline.py`
- `tests/test_mcp_boundary.py`
- `tests/test_operator_ready_manifests.py`
- `tests/test_pbs_operator_reconciler.py`
- `tests/test_pbs_operator_bundle.py`
- `tests/test_ops_console_api.py`

## Requirement Evidence

1. Feature/config boundaries
   - Added `CHAT_PROVIDER`, OLS auth settings, namespace auto-create disablement, console executor mode, BYOK flags, and Operator-ready settings.
   - Terminal namespace provisioning is gated by both `TERMINAL_USER_WORKSPACE_ENABLED` and `PBS_AUTO_CREATE_NAMESPACE`.

2. Lightspeed provider architecture
   - Added `lightspeed_provider.py` and routed chat/stream paths through Lightspeed when `CHAT_PROVIDER=lightspeed`.
   - Internal PBS chat remains the legacy/fallback provider.

3. BYOK document pipeline
   - PBS Library uploads can produce operational Markdown, front matter, quality gate result, export manifest, build request, and OLSConfig patch preview.
   - Qdrant indexing remains in the legacy/internal path and is not required for Lightspeed BYOK export.

4. CLI/YAML event timeline
   - Added structured JSONL timeline capture for terminal command input/output/exit/error.
   - Ops Console action execution records YAML diff, apply result, related events, and resource snapshot.
   - Added `/api/v1/aiops/events` for UI and MCP consumers.

5. AIOps Workbench UI shell
   - Added top AIOps status bar, central context strip, and right terminal/event/log rail to `WorkspacePage`.
   - Left panel already contains OCP-style cluster resource navigation and opens YAML detail from the workbench.
   - Chat history remains a left panel mode and is not mixed into the resource event rail.

6. PBS MCP boundary
   - Added dependency-free read-only tool catalog and local handlers for library search, document read, BYOK builds, events, CLI output, YAML apply history, snapshots, and remediation plan generation.
   - Added minimal HTTP wrapper for future transport replacement.

7. Operator-ready manifests
   - Added `deploy/sno/pbs/base` kustomize with app/web, MCP service, BYOK builder RBAC, config boundaries, route, and OLSConfig patch preview.
   - Added `deploy/sno/pbs-operator/config` CRD and sample `PlaybookStudio` custom resource sketch.
   - Added dependency-free PBS Operator reconcile core that renders desired PBS resources from a `PlaybookStudio` CR and reports dry-run status without claiming live reconciliation.
   - Added Operator runtime with in-cluster `PlaybookStudio` list/watch detection, gated server-side apply, gated status patching, Operator Deployment/RBAC, synchronized OLM bundle preview, and CatalogSource preview.
   - Added lifecycle boundary docs for PBS, Lightspeed, OpenShift AI, and GitOps.

## Verification

- Backend targeted suite:
  - `.venv/Scripts/python.exe -m pytest tests/test_v030_config_boundaries.py tests/test_lightspeed_provider.py tests/test_byok_operational_markdown.py tests/test_aiops_event_timeline.py tests/test_ops_console_api.py tests/test_terminal_session.py tests/test_terminal_ws_learning_events.py tests/test_mcp_boundary.py tests/test_operator_ready_manifests.py tests/test_upload_api.py tests/test_app_server.py`
  - Result: 56 passed, 1 skipped.
- Frontend build:
  - `npm run build` in `apps/web`
  - Result: passed. Vite reported a chunk-size warning only.
- Frontend tests:
  - `npm test` in `apps/web`
  - Result: 7 test files passed, 16 tests passed.
- Local manifest render:
  - `kubectl kustomize deploy/sno/pbs/base`
  - `kubectl kustomize deploy/sno/pbs-operator/config`
  - Result: both rendered locally.
- Operator dry-run checks:
  - `.venv/Scripts/python.exe -m pytest tests/test_pbs_operator_runtime.py tests/test_pbs_operator_reconciler.py tests/test_pbs_operator_bundle.py tests/test_operator_ready_manifests.py`
  - Result: 15 passed.
  - `.venv/Scripts/python.exe -m play_book_studio.pbs_operator.reconciler --help`
  - Result: passed.
- Operator image pipeline checks:
  - `.venv/Scripts/python.exe -m pytest tests/test_operator_image_pipeline.py tests/test_pbs_operator_bundle.py tests/test_pbs_operator_runtime.py tests/test_pbs_operator_reconciler.py tests/test_operator_ready_manifests.py`
  - Result: 18 passed.
  - `docker build --target operator-bundle -f deploy/Dockerfile .`
  - Result: passed.
  - `docker build --target operator-catalog -f deploy/Dockerfile .`
  - Result: passed.

## Rubric Score

Target: 90 or higher.

| Area | Max | Score | Evidence |
| --- | ---: | ---: | --- |
| UI workbench coherence | 15 | 13 | One-screen Workspace shell now has status bar, central context, left resources, right terminal/event rail. Full OCP Console parity is still future work. |
| Lightspeed provider architecture | 15 | 14 | Provider boundary and request normalization are implemented. Live OLS API compatibility remains deferred. |
| BYOK document pipeline quality | 20 | 18 | Operational Markdown, metadata, quality gates, manifest, build request, and OLS patch preview are implemented. Live image build is deferred. |
| Console/YAML event capture | 15 | 14 | CLI and YAML/apply events are structured and exposed. Live cluster event richness depends on future live validation. |
| Cluster context composition | 10 | 8 | Resource snapshots, related events, terminal output, and YAML diff are captured. Deeper log collection can expand later. |
| Operator-ready configuration boundaries | 10 | 9 | Config flags, kustomize base, RBAC, MCP, BYOK, OLS preview, CRD sketch, reconcile core, in-cluster CR watch detection, gated server-side apply/status patch path, bundle preview, and catalog preview exist. Live validation is deferred. |
| Test coverage and verification evidence | 10 | 10 | Focused backend, frontend, and kustomize checks pass. |
| Backward compatibility and legacy path isolation | 5 | 5 | Internal chat and Qdrant paths remain available without making Lightspeed depend on Qdrant. |

Total: 91 / 100.

## Remaining Gaps

- Live SNO deployment, SSH validation, `oc login`, `oc apply`, OLS Operator install/delete/reinstall, and BYOK image build were not executed by design.
- The MCP server is a Phase 1 read-only boundary and minimal HTTP wrapper, not a full production MCP transport.
- The PBS Operator now has reconcile core, in-cluster CR watch detection, gated server-side apply, and status patch paths. Live validation against the SNO cluster has not been executed.
- OLS API request/response shape may need adjustment against the actual installed Lightspeed version during a later live phase.
- UI workbench is prepared inside the existing `WorkspacePage`; deeper OCP Console parity and editable YAML center-panel workflow remain follow-up refinement.
