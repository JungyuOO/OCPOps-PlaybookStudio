# Runtime Context ERD Draft

## Goal

Store namespace-scoped OCP runtime evidence for answer generation without leaking other users' resources or sensitive values.

## Candidate Tables

- `ocp_clusters`
- `ocp_user_workspaces`
- `ocp_namespace_bindings`
- `ocp_resource_snapshots`
- `ocp_pod_snapshots`
- `ocp_events`
- `ocp_log_segments`
- `ocp_alerts`
- `ocp_metric_summaries`
- `ocp_context_packs`

## Required Concepts

- tenant/workspace/user boundary
- namespace isolation
- collected_at
- expires_at
- stale/deleted state
- redaction status

## Sensitive Data Rules

Do not store:

- Secret raw values
- tokens/passwords
- kubeconfig raw content
- image pull credentials
- unbounded full logs

## Notes

Runtime evidence must be separate from official document citations in answer payloads.
