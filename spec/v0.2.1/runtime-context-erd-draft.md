# v0.2.1 Runtime Context ERD Boundary Draft

## Purpose

Define the boundary for future OCP runtime context storage before v0.2.5 produces the detailed ERD and migration plan.

This is only a boundary draft. v0.2.1 must not implement collectors, migrations, terminal analysis, or answer prompt changes.

## Why Runtime Context Matters

OpenShift Lightspeed-style answers become more useful when official docs are combined with current cluster state.

PlaybookStudio should eventually answer questions such as:

- 지금 내 namespace에서 Pod가 왜 Pending이야?
- 방금 터미널에서 실행한 명령 결과를 보고 다음 확인 단계 알려줘.
- dashboard에 Warning 이벤트가 있는데 원인이 뭐야?
- Deployment rollout이 실패했는지 계속 봐줘.

That requires data that changes over time. It cannot be stored like static documentation.

## Boundary

### In Scope for Future ERD

```text
ocp_clusters
ocp_user_workspaces
ocp_namespace_bindings
ocp_resource_snapshots
ocp_pod_snapshots
ocp_events
ocp_log_segments
ocp_alerts
ocp_metric_summaries
ocp_context_collection_runs
ocp_context_packs
```

### Out of Scope

- raw Secret values
- raw tokens
- raw kubeconfig
- password values
- other users' namespace data
- indefinite full log archives
- cluster-wide admin data without explicit permission
- uncontrolled watch streams

## Entity Boundaries

### ocp_clusters

Represents a configured OCP API target, not a full credential store.

Candidate fields:

```text
id
tenant_id
cluster_key
display_name
api_server_hash
version
connection_status
last_seen_at
created_at
updated_at
```

Do not store raw token or kubeconfig here.

### ocp_user_workspaces

Maps app user/session to OCP runtime identity.

Candidate fields:

```text
id
tenant_id
workspace_id
user_id
cluster_id
runtime_identity_key
status
created_at
updated_at
```

### ocp_namespace_bindings

Defines which namespace a user may inspect.

Candidate fields:

```text
id
tenant_id
workspace_id
user_id
cluster_id
namespace
role
status
bound_at
archived_at
```

Rules:

- user-scoped collection must filter by namespace binding.
- deleted namespace should become archived, not silently removed from history.
- other user namespaces must not be visible.

### ocp_resource_snapshots

Generic snapshot for Kubernetes/OpenShift resources.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
api_group
kind
name
uid
resource_version
status_phase
summary_json
conditions_json
collected_at
expires_at
redaction_status
```

### ocp_pod_snapshots

Pod-specific derived snapshot for common operations questions.

Candidate fields:

```text
id
resource_snapshot_id
namespace
pod_name
phase
ready
restart_count
node_name
owner_kind
owner_name
waiting_reasons
container_statuses_json
collected_at
expires_at
```

### ocp_events

Stores bounded Kubernetes Event history.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
involved_kind
involved_name
reason
type
message
count
first_timestamp
last_timestamp
collected_at
expires_at
```

### ocp_log_segments

Stores short, redacted log tails or command output excerpts.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
pod_name
container_name
source
text_excerpt
line_count
byte_count
collected_at
expires_at
redaction_status
```

Rules:

- store excerpts, not unbounded full logs.
- redact tokens, bearer strings, passwords, kubeconfigs.
- retention must be short by default.

### ocp_alerts

Represents monitoring alert snapshots.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
alert_name
severity
state
labels_json
annotations_json
starts_at
ends_at
collected_at
expires_at
```

### ocp_metric_summaries

Stores small summaries, not full time-series metrics.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
resource_kind
resource_name
metric_name
window
summary_json
collected_at
expires_at
```

### ocp_context_collection_runs

Tracks collector execution.

Candidate fields:

```text
id
tenant_id
workspace_id
cluster_id
namespace
trigger_type
status
started_at
finished_at
error_summary
collector_version
```

### ocp_context_packs

Materialized context bundle for answer generation.

Candidate fields:

```text
id
tenant_id
workspace_id
user_id
cluster_id
namespace
question_id
pack_json
source_counts_json
created_at
expires_at
```

## Retention Draft

Default retention candidates:

| Data | Suggested Retention |
| --- | --- |
| resource snapshots | 1-7 days |
| pod snapshots | 1-7 days |
| events | 7-14 days |
| log segments | 1-3 days |
| alerts | 7-30 days |
| metric summaries | 1-7 days |
| context packs | session scoped or 1-3 days |

Final retention belongs to v0.2.5.

## Redaction Draft

Redact before storage:

- bearer tokens
- kubeconfig content
- passwords
- private keys
- Secret `.data` and `.stringData`
- Docker config auth blocks
- cloud credentials

Store redaction status:

```text
not_required
redacted
blocked
failed
```

If redaction fails, the record should not be stored.

## Isolation Rules

- Every runtime row must carry tenant/workspace/user or namespace binding context.
- Collector must be namespace-scoped by default.
- Cluster-wide list/watch requires explicit admin mode and separate audit.
- Runtime context must never broaden the user's view beyond their assigned namespace.
- Answer generation must cite whether evidence came from official docs or runtime context.

## v0.2.5 Handoff

v0.2.5 should turn this boundary into:

- detailed ERD
- exact columns and indexes
- migration sequence
- retention policy
- redaction policy
- update/upsert/delete behavior
- data access repositories

