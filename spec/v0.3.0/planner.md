# PBS v0.3.0 Lightspeed AIOps Workbench Planner

## Intent

PBS v0.3.0 turns Playbook Studio into an OpenShift Lightspeed-powered AIOps workbench.
The first implementation phase focuses on local feature completion and verification. Live OCP
redeployment validation and final Operator installation validation are intentionally deferred because
they depend on external cluster access and operational authority.

The target is an implementation that can score 90 or higher in local review against the acceptance
criteria in this plan before OCP-side deployment work begins.

## Branch

- Working branch: `v3.0.0/lightspeed`
- Version/spec folder: `spec/v0.3.0`

## Out Of Scope For Phase 1

- Rebuilding and redeploying the PBS image to the live OCP cluster.
- Installing, deleting, or reinstalling the OpenShift Lightspeed Operator on the live cluster.
- Final OLM bundle publication or OperatorHub/CatalogSource validation.
- Production-grade per-user OpenShift OAuth delegation.
- Direct mutation of the live SNO Linux server, remote `.env` files, cluster Secrets, registry
  credentials, or Operator lifecycle resources.

These are deferred, not rejected. The implementation must still keep Operator-ready boundaries so
the deferred work can be added without rewriting the core design.

## Current SNO Baseline

PBS is already deployed on the SNO OpenShift cluster and is reachable through the existing route:

```text
https://playbookstudio.192.168.119.8.nip.io
https://playbookstudio.192.168.119.8.nip.io/studio
https://playbookstudio.192.168.119.8.nip.io/playbook-library/repository
```

This deployment is the operational baseline for understanding the current route, namespace, image,
and service shape. It is not the final v0.3.0 target state.

The SNO Linux host used for later live work is:

```text
SNO_SERVER_HOST=192.168.119.27
```

Credentials, passwords, tokens, kubeconfigs, registry credentials, and `.env` contents must not be
committed to this repository or written into this planner. They must be supplied later through
OpenShift Secrets, GitHub Actions Secrets, SSH key material, or protected server-side environment
files.

Phase 1 must create code and manifests that are ready for this environment, but it must not claim
that the live route, live CLI, live Operator lifecycle, or live cluster reconciliation has been
verified.

## Product Goal

PBS should provide one primary workbench where an operator can:

- Ask Lightspeed-backed questions in the central chat.
- Upload customer documents into the PBS Library, process them into PBS private RAG context, and
  attach that context to Lightspeed requests.
- Browse OpenShift resources in a left navigation model similar to the OCP Console.
- Open resource lists and details without leaving the main Playbook Studio shell.
- Edit YAML for resources in-context and capture the resulting apply event.
- Use the right-side terminal for real `oc` and optional SSH workflows.
- Let PBS collect CLI, YAML, cluster event, and log context for Lightspeed analysis.
- Prepare the same components to be managed later by a PBS Operator.
- Support a later demo flow where OpenShift Lightspeed is removed, reinstalled, configured, and then
  reconnected to PBS without changing PBS application code.

## UI Direction

The current menu/modal-oriented layout should move toward a single AIOps workbench shell.

Target layout:

- Top bar: cluster connection, Lightspeed status, private-document context status, Operator-readiness
  status.
- Left rail: OCP Console-style navigation.
- Center: Lightspeed chat, resource lists, resource detail, YAML editor, analysis results.
- Right rail: terminal, event timeline, logs, apply output, context inspector.
- Library: separate large management page, but status and selected knowledge scope remain visible in
  the workbench.

Left navigation should include at least:

- Overview
- Workloads
- Pods
- Deployments
- Services
- Routes
- Storage
- PVCs
- StorageClasses
- Operators
- Installed Operators
- Library
- Customer Docs
- Private Context
- AIOps
- Events
- Apply History
- CLI Sessions
- Settings

Chat history should not be mixed with the resource navigation. It should be a separate drawer,
panel, or central chat-level control.

## Lightspeed Integration

PBS should not treat the existing internal chatbot as the primary answer-generation path for v0.3.0.
Lightspeed remains the primary source for OpenShift official documentation, built-in RAG, and cluster
analysis. PBS still keeps its internal retrieval path for user-uploaded/private customer documents and
uses those results as supplemental request context for Lightspeed.

It should introduce a provider boundary:

- `internal`: existing PBS RAG/chat path, retained for fallback and private uploaded document retrieval.
- `lightspeed`: OpenShift Lightspeed API path, primary for official OpenShift guidance and cluster
  reasoning.

Configuration shape:

```text
CHAT_PROVIDER=lightspeed
LIGHTSPEED_KNOWLEDGE_MODE=lightspeed-rag-with-pbs-private-context
OLS_BASE_URL=<lightspeed service or route>
OLS_AUTH_MODE=test-admin-secret|service-account|user-token
PBS_AUTO_CREATE_NAMESPACE=false
```

Phase 1 may support `test-admin-secret` and a stub or planned interface for `service-account`.
The implementation must avoid hardcoding `admin/admin123` in source code.

Expected backend responsibilities:

- Normalize PBS chat requests into Lightspeed query requests.
- Support non-streaming and streaming response paths when available.
- Attach relevant context from library scope, CLI events, YAML diffs, apply results, logs, and cluster
  snapshots.
- Attach PBS user-upload/private document excerpts as supplemental context, while leaving official
  OpenShift knowledge and cluster reasoning to Lightspeed.
- Preserve enough conversation metadata for later replay and troubleshooting.

## PBS Private Document Pipeline

PBS Library uploads should become operational Markdown and private PBS retrieval context that can be
injected into Lightspeed requests. v0.3.0 must not expose or execute an external knowledge-image path.

Pipeline:

1. Upload source document to PBS Library.
2. Extract raw text, tables, code blocks, YAML, shell commands, and source metadata.
3. Rewrite or normalize into detailed operational Markdown.
4. Add front matter metadata.
5. Run a quality gate.
6. Index the Markdown into PBS private retrieval for user/customer-document context.
7. Attach the best matching private excerpts to Lightspeed requests as supplemental context.
8. Record deterministic private-context metadata for search, audit, and traceability.

The output must be useful as operational context for Lightspeed, not merely converted to Markdown.
The transformer must produce operationally dense documents with enough explicit language for RAG
retrieval:

- Include the real user-facing symptom names and Korean/English operational variants.
- Include likely `oc` commands in fenced `bash` blocks.
- Preserve YAML snippets in fenced `yaml` blocks.
- Convert tables into Markdown tables or decision lists.
- Split vague source text into explicit situation, symptoms, checks, decision criteria, and remediation
  direction.
- Add internal source URLs that remain stable across PBS private indexing.
- Avoid dumping raw extracted text without operational rewrite.

Canonical Markdown shape:

```markdown
---
title: "KOSCOM PVC Pending Troubleshooting"
url: "internal://koscom/ocp/pvc-pending"
source_type: "troubleshooting"
customer: "koscom"
product: "openshift"
version: "4.x"
topic: "storage"
keywords:
  - pvc
  - pending
  - storageclass
  - provisioner
---

# KOSCOM PVC Pending Troubleshooting

## 상황

KOSCOM OpenShift 환경에서 PVC가 Pending 상태이면 스토리지 클래스, provisioner, namespace
event를 순서대로 확인한다.

## 증상

- PVC phase가 `Pending`으로 유지된다.
- Pod가 PVC mount 대기 상태에서 시작하지 못한다.
- Event에 provisioner 또는 StorageClass 관련 메시지가 남는다.

## 확인 순서

1. PVC event 확인

```bash
oc describe pvc <pvc-name> -n <namespace>
```

2. StorageClass 확인

```bash
oc get sc
```

## 판단 기준

StorageClass가 없거나 default StorageClass가 지정되지 않았으면 PVC가 Pending 상태로 남을 수 있다.

## 조치 방향

- default StorageClass가 필요한 환경이면 기본 StorageClass 지정 여부를 확인한다.
- provisioner 장애이면 provisioner Deployment/DaemonSet 로그와 image pull 상태를 확인한다.

## 관련 명령

```bash
oc get pvc -A
oc get events -n <namespace> --sort-by=.lastTimestamp
```
```

Quality gate:

- Valid front matter exists.
- H1 exists and matches the operational topic.
- Document has situation, symptoms, check steps, decision criteria, remediation direction, and related
  commands when the source supports them.
- `oc`, `kubectl`, shell, and YAML snippets are fenced correctly.
- Customer, product, topic, source type, and internal URL are present.
- Long documents are split into topic-specific Markdown files instead of one oversized file.
- The body contains likely user query terms, including Korean operational wording and important English
  resource names.
- Each troubleshooting document includes at least one observable signal, one command to inspect it, and
  one decision rule.
- The default PBS private export produces deterministic metadata that maps source document IDs to
  generated Markdown files and retrievable private context.

Qdrant/internal retrieval remains available for PBS user-upload/private documents. The Lightspeed path
must not use Qdrant to replace Lightspeed official OpenShift knowledge; it may use PBS private retrieval
only to attach customer-specific context.

### Private Context Artifact Model

The expected v0.3.0 design should produce artifacts that can be searched by PBS and attached to
Lightspeed requests without registering a knowledge image:

Suggested artifact layout:

```text
storage/private-rag/
  sources/
    <document-id>/
      original.<ext>
      extracted.txt
      metadata.json
  generated/
    <customer>/<topic>/<slug>.md
  manifests/
    private-context-manifest.json
```

The generated manifest should include:

- source document ID
- generated Markdown path
- title
- internal URL
- customer
- product/version
- topic
- source type
- quality gate result
- content hash
- private retrieval collection/scope

## Cluster And Action Context

PBS should collect operational context and pass it to Lightspeed for analysis.

Required event sources:

- CLI command input.
- CLI stdout, stderr, exit code, and timestamp.
- YAML editor diff.
- Apply result.
- Kubernetes events related to the touched resource.
- Pod logs when a related workload fails.
- Cluster resource snapshots for selected resources.

PBS is responsible for detection and context composition. Lightspeed is responsible for reasoning and
answer generation.

Event timeline example:

```text
10:31 user edited deployment/api replicas 1 -> 3
10:32 oc apply succeeded
10:33 pod/api-xxx ImagePullBackOff
10:34 user asked Lightspeed for analysis
10:34 Lightspeed answered with likely image pull secret failure
```

## Console And YAML Execution

The right-side console should be treated as an Operator-ready executor surface, not a simple browser
terminal mock.

Executor modes:

- `test-admin-secret`: phase 1 test mode using a secret-provided kubeconfig/token.
- `service-account`: future Operator-managed mode using PBS ServiceAccount/RBAC.
- `user-token`: future per-user delegated mode.

Phase 1 must:

- Keep namespace auto-creation disabled.
- Avoid IP/browser-derived namespace allocation.
- Route terminal events through backend logging.
- Allow command outputs to be attached to Lightspeed analysis.
- Keep destructive operations gated by explicit user action in the UI.

YAML editor flow:

1. User selects a resource from the OCP-style left navigation.
2. Center panel shows list/detail tabs.
3. YAML tab opens the resource YAML.
4. User edits YAML.
5. PBS computes diff and runs validation/dry-run where possible.
6. User applies.
7. PBS records apply event, related Kubernetes events, and terminal/apply output.
8. Lightspeed can analyze the result in the central chat.

## PBS MCP Server Path

PBS private document context is the customer-document path. MCP is the secondary integration path for
allowing OpenShift Console Lightspeed to call PBS capabilities directly.

PBS should prepare an MCP server boundary with tools such as:

- `search_pbs_library`
- `get_pbs_document`
- `list_recent_pbs_events`
- `get_cli_session_output`
- `get_yaml_apply_history`
- `get_cluster_snapshot`
- `generate_remediation_plan`

Future `OLSConfig` shape:

```yaml
apiVersion: ols.openshift.io/v1alpha1
kind: OLSConfig
metadata:
  name: cluster
spec:
  featureGates:
    - MCPServer
  mcpServers:
    - name: pbs-tools
      url: http://pbs-mcp.playbookstudio.svc.cluster.local:8080/mcp
      timeout: 30
      headers:
        - name: kubernetes-authorization
          valueFrom:
            type: kubernetes
```

The MCP path should be designed as Technology Preview-compatible and optional.

## Live SNO Server And GitOps Layout

Phase 2 and later should use a split between repository source-of-truth and server execution surfaces.

Repository source-of-truth:

```text
deploy/
  sno/
    openshift-ai/
      base/
      overlays/test/
      overlays/prod/
    lightspeed/
      base/
      overlays/test/
      overlays/prod/
    pbs/
      base/
      overlays/test/
      overlays/prod/
    pbs-operator/
      config/
      bundle/
      catalog/
    gitops/
      applications/
```

SNO Linux server operational layout:

```text
/srv/ocpops/
  git/
    OCPOps-PlaybookStudio/
  runtime/
    openshift-ai/
      manifests/
      logs/
      backups/
    lightspeed/
      manifests/
      logs/
      backups/
    playbookstudio/
      manifests/
      logs/
      backups/
    operators/
      pbs/
        bundle/
        catalog/
  scripts/
  runbooks/
```

The server folders are execution, recovery, and log surfaces. They must not become the only copy of
the desired cluster state. The GitHub repository remains the source of truth.

OpenShift AI, OpenShift Lightspeed, and PBS must be separated because their lifecycle differs:

- OpenShift AI owns model serving, LLM provider endpoints, inference services, and provider credentials.
- OpenShift Lightspeed owns `OLSConfig`, MCP server registration, telemetry/redaction, and the
  Lightspeed Operator lifecycle.
- PBS owns the workbench UI/backend, Library, private document context pipeline, console executor,
  event timeline, MCP tools, and future PBS Operator.

## Live Cluster Cleanup And Reinstall Plan Boundary

The live SNO cluster currently has resources that may have been created by direct `oc patch`,
manual `oc apply`, or previous test flows. Before final v0.3.0 validation, these must be inventoried
and either adopted into GitOps/Operator management or removed.

Phase 2 live cleanup plan must include:

- Inventory current OpenShift AI Operator, operands, model serving resources, routes, Secrets, and
  namespaces.
- Inventory current OpenShift Lightspeed Operator, `OLSConfig`, app server, MCP settings, routes,
  Secrets, and related namespaces.
- Inventory current PBS Deployment, Service, Route, ConfigMap, Secret references, image tag, and RBAC.
- Identify resources created only by temporary `oc patch` or manual test commands.
- Back up current YAML before deletion or replacement.
- Remove unused or conflicting resources only during an explicit live execution window.
- Reinstall OpenShift AI and Lightspeed from declarative manifests.
- Reconnect PBS to the reinstalled Lightspeed endpoint.
- Re-register PBS MCP server if the MCP path is enabled.

This planner does not authorize destructive cleanup. It defines the required future plan shape.

## CI/CD And GitOps Target

The current manual pattern is:

```text
PR merge
  -> GitHub Actions builds image
  -> GHCR image is pushed
  -> server operator runs oc apply or oc apply -k manually
```

The target v0.3.0+ pattern is:

```text
PR merge to dev or release branch
  -> GitHub Actions builds PBS app image
  -> GitHub Actions builds PBS Operator/bundle/catalog images when operator code exists
  -> GitHub Actions updates declarative image references or release manifests
  -> OpenShift GitOps/Argo CD watches the repository
  -> SNO cluster reconciles PBS, Lightspeed config, MCP registration, and PBS Operator resources
```

The implementation should prepare for this by keeping all deployable state declarative, reviewable,
and environment-specific through overlays. Direct server-side edits are acceptable only as temporary
break-glass operations and must be backported into the repository if they become desired state.

## Operator-Ready Architecture

Even though live Operator validation is deferred, v0.3.0 should shape the code and config so a PBS
Operator can later manage the deployment.

Future `PlaybookStudio` CR sketch:

```yaml
apiVersion: pbs.ocpops.io/v1alpha1
kind: PlaybookStudio
metadata:
  name: pbs
spec:
  image: registry.example.com/pbs:v0.3.0
  ui:
    shellMode: aiops-workbench
  route:
    enabled: true
  chat:
    provider: lightspeed
  lightspeed:
    detectOperator: true
    manageOLSConfig: true
    auth:
      mode: serviceAccount
    mcp:
      enabled: true
      registerWithOLS: true
      serverName: pbs-tools
  console:
    enabled: true
    executorMode: serviceAccount
  namespaceMode:
    autoCreate: false
  library:
    ingestion:
      outputFormat: pbs-private-context-markdown
      qdrantEnabled: true
```

Operator-managed resources expected later:

- PBS web/backend Deployment.
- Service and Route.
- ConfigMap for provider and feature flags.
- Secret references, not hardcoded credentials.
- ServiceAccount and RBAC.
- PBS MCP Server Deployment/Service.
- Optional OLSConfig patch/registration workflow.
- Optional OpenShift Lightspeed readiness checks and reconnection status.
- Optional GitOps application resources or generated manifests.

The future PBS Operator should not attempt to own the full lifecycle of OpenShift AI by default.
OpenShift AI and Lightspeed should be managed by their own Operators or GitOps manifests. PBS Operator
may detect and configure integration points, such as OLS endpoint and MCP registration, when explicitly
enabled.

## Implementation Milestones

### M1: Foundation

- Confirm branch and baseline structure.
- Add feature flags for Lightspeed, namespace behavior, console executor mode, and private document
  context.
- Disable namespace auto-create for v0.3.0 test mode.

### M2: UI Shell

- Convert Playbook Studio to a persistent AIOps workbench shell.
- Move resource navigation to a left OCP-style rail.
- Separate chat history from resource navigation.
- Keep top status bar and right terminal/event rail stable across resource pages.

### M3: Lightspeed Gateway

- Add provider boundary for internal vs Lightspeed chat.
- Implement Lightspeed request/response normalization.
- Add health/status checks.
- Add context composer for selected library scope, CLI events, YAML diffs, and cluster snapshots.

### M4: Private Document Context Pipeline

- Convert uploaded documents into detailed operational Markdown.
- Add front matter metadata and internal URLs.
- Add quality gate.
- Add deterministic private-context metadata and indexing.
- Attach matching private excerpts to Lightspeed requests.

### M5: Console And YAML Events

- Wire terminal command events into an event timeline.
- Record command output and exit status.
- Add YAML diff/apply event capture.
- Attach recent event context to Lightspeed chat.

### M6: Cluster Context

- Add resource list/detail surfaces for the main OCP-style navigation.
- Collect related events/logs/snapshots for selected resources.
- Use this context in troubleshooting prompts.

### M7: MCP Skeleton

- Add an optional PBS MCP server boundary.
- Expose initial read-only tools around Library, event timeline, CLI history, and cluster snapshots.
- Keep registration with OLSConfig as deferred or dry-run until OCP validation phase.

### M8: Operator Readiness

- Document required CRD spec, managed resources, and RBAC.
- Ensure runtime configuration maps to future CR fields.
- Avoid code paths that require manual cluster mutation outside configured providers.
- Add deploy/GitOps manifest structure or dry-run generation plan for PBS, MCP, and Lightspeed
  integration.
- Keep OpenShift AI and Lightspeed ownership boundaries explicit.

### M9: Verification And Score Loop

- Add focused unit tests for provider selection, namespace disabled behavior, private Markdown quality,
  event timeline capture, and context composition.
- Run available frontend/backend tests.
- Run static/type checks where available.
- Review implementation against the scoring rubric below.
- Iterate until score is at least 90.

## Scoring Rubric

Target: 90 or higher before marking v0.3.0 phase 1 complete.

- UI workbench coherence: 15
- Lightspeed provider architecture: 15
- Private document context quality: 20
- Console/YAML event capture: 15
- Cluster context composition: 10
- Operator-ready configuration boundaries: 10
- Test coverage and verification evidence: 10
- Backward compatibility and legacy path isolation: 5

Automatic fail conditions:

- Hardcoded OCP admin password in source code.
- Namespace auto-creation remains active in v0.3.0 test mode.
- Lightspeed path still depends on Qdrant as the primary knowledge source.
- CLI/YAML actions are not recorded as events.
- UI still requires modal/menu jumping for the main workbench flow.
- Private document output is only raw Markdown conversion and lacks operational rewrite, metadata,
  quality gates, and retrieval metadata.
- Live cluster success is claimed without evidence from actual SNO/OCP commands.

## Completion Criteria

Phase 1 is complete when:

- PBS can run with `CHAT_PROVIDER=lightspeed` and namespace auto-create disabled.
- Central chat, left resource navigation, right terminal/event rail, and Library/private context status have a
  coherent one-screen workbench design.
- Uploaded documents can be transformed into private operational Markdown with metadata and quality
  validation, then attached to Lightspeed as supplemental context.
- CLI and YAML actions produce structured events that can be included in Lightspeed analysis context.
- Operator-ready configuration and CR sketch are represented in docs and reflected in code boundaries.
- The planner includes a separate live SNO/GitOps/Operator validation path that does not blur local
  readiness with real cluster verification.
- Tests and static checks pass or any remaining gaps are explicitly documented.
- The implementation scores at least 90 using this planner's rubric.
