import { RUNTIME_ORIGIN } from './runtimeApi';

export type OpsRouteKey =
  | 'workspaces'
  | 'connections'
  | 'overview'
  | 'resources'
  | 'library'
  | 'chat'
  | 'actions'
  | 'scm';

export interface OpsWorkspace {
  workspace_id: string;
  name: string;
  slug: string;
  industry: string;
  environment: string;
  created_at: string;
  updated_at: string;
}

export interface OcpConnection {
  workspace_id: string;
  connection_id: string;
  display_name: string;
  cluster_url: string;
  auth_mode: string;
  verify_ssl: boolean;
  default_namespace: string;
  username_hint: string;
  secret_ref: string;
  save_profile: boolean;
  status: string;
  last_verified_at: string;
  expires_at: string;
}

export interface OcpConnectionTestResult {
  success: boolean;
  resolved_user: string;
  resolved_groups: string[];
  resolved_roles: string[];
  identity_source: string;
  permission_hints: string[];
  rbac_evidence: string[];
  secret_backend: string;
  secret_lease_ttl_seconds: number;
  secret_lease_expires_at: string;
  resolved_namespace: string;
  expires_at: string;
  message: string;
  error: string;
}

export interface LeaseSchedulerStatus {
  enabled: boolean;
  running: boolean;
  interval_seconds: number;
  last_run_at: string;
  last_success_at: string;
  last_failure_at: string;
  last_error: string;
  consecutive_failures: number;
  profiles_checked: number;
  renewals_applied: number;
  recent_failures: string[];
}

export interface RecommendationItem {
  recommendation_id: string;
  workspace_id: string;
  connection_id: string;
  namespace: string;
  resource_kind: string;
  resource_name: string;
  recommendation_type: string;
  risk_level: string;
  summary: string;
  rationale: string;
  created_at: string;
}

export interface OcpOverview {
  connection_id: string;
  cluster_url: string;
  default_namespace: string;
  namespace_count: number;
  namespace_sample: string[];
  resource_counts: Record<string, number>;
  message: string;
}

export interface OcpMetricPodRow {
  name: string;
  cpu_mcores?: number;
  memory_mib?: number;
}

export interface OcpMetricWorkloadRow {
  kind: string;
  name: string;
  ready_replicas: number;
  replicas: number;
  status: string;
}

export interface OcpMetricEventRow {
  name: string;
  phase: string;
}

export interface OcpMetricsResponse {
  connection_id: string;
  namespace: string;
  window: string;
  source: {
    provider: string;
    live: boolean;
  };
  summary: {
    warning_events: number;
    degraded_deployments: number;
    top_cpu_pod: OcpMetricPodRow | null;
    top_memory_pod: OcpMetricPodRow | null;
  };
  pod_cpu_top: OcpMetricPodRow[];
  pod_memory_top: OcpMetricPodRow[];
  workload_health: OcpMetricWorkloadRow[];
  event_summary: OcpMetricEventRow[];
}

export interface NamespaceListResponse {
  connection_id: string;
  cluster_url: string;
  count: number;
  items: string[];
}

export interface OcpResourceItem {
  name: string;
  namespace: string;
  kind: string;
  created_at: string;
  phase?: string;
  node_name?: string;
  ready_replicas?: number;
  replicas?: number;
  type?: string;
  cluster_ip?: string;
  host?: string;
  to?: string;
}

export interface ResourceListResponse {
  connection_id: string;
  cluster_url: string;
  resource: string;
  namespace: string;
  count: number;
  items: OcpResourceItem[];
}

export interface ResourceDetailResponse {
  connection_id: string;
  cluster_url: string;
  resource: string;
  namespace: string;
  name: string;
  kind: string;
  manifest_yaml: string;
  manifest_json: Record<string, unknown>;
}

export interface LibrarySummary {
  workspace_id: string;
  source_root: string;
  extract_root: string;
  corpus_files: number;
  manifest_entries: number;
  extracted_artifacts: number;
  indexed_documents: number;
  indexed_chunks: number;
  batch_jobs: number;
  latest_batch_status: string;
  source_breakdown: Record<string, number>;
  indexed_samples: string[];
  message: string;
}

export interface LibraryCatalogItem {
  document_key: string;
  title: string;
  relative_path: string;
  source_type: string;
  group: string;
  indexed: boolean;
  chunk_count: number;
  original_kind: string;
  original_key: string;
  description: string;
}

export interface LibraryChunk {
  chunk_id: string;
  chunk_order: number;
  page_number: number;
  section_title: string;
  block_types: string[];
  preview_text: string;
  viewer_path?: string;
  section_path?: string[];
}

export interface LibraryChunksResponse {
  document_key: string;
  title: string;
  chunk_count: number;
  chunks: LibraryChunk[];
}

export interface LibraryDocumentContent {
  workspace_id: string;
  document_key: string;
  title: string;
  content: string;
}

export interface BatchJob {
  job_id: string;
  task_type: string;
  status: string;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
  progress_pct: number;
  current_file: string;
  created_at: string;
  updated_at: string;
}

export interface DocsPreviewSnippet {
  source_path: string;
  relative_source_path: string;
  repo_relative_path: string;
  repo_locator: string;
  file_name: string;
  chunk_id: string;
  source_type: string;
  title: string;
  section_title: string;
  section_path: string[];
  page_number: number;
  line_start: number;
  line_end: number;
  snippet: string;
  lines: string[];
}

export interface OpsChatSource {
  index: number;
  source_path: string;
  title: string;
  section_title: string;
  viewer_path: string;
  chunk_id: string;
}

export interface OpsChatArtifact {
  kind: string;
  title: string;
  connection_id?: string;
  resource_type?: string;
  namespace?: string;
  name?: string;
  editable?: boolean;
  total_count?: number;
  summary?: Record<string, unknown>;
  manifest_preview?: string;
  items: Array<Record<string, unknown>>;
}

export interface OpsChatResponse {
  lane: string;
  mode: string;
  fallback_used: boolean;
  preview_ready: boolean;
  answer: string;
  sources: OpsChatSource[];
  artifacts: OpsChatArtifact[];
  citation_map: Record<string, OpsChatSource>;
}

export interface OpsChatStageEvent {
  type: 'stage';
  stage: {
    key: string;
    label: string;
    detail: string;
    status: string;
  };
}

export interface OpsChatDeltaEvent {
  type: 'answer_delta';
  delta: string;
}

export interface OpsChatResultEvent {
  type: 'result';
  response: OpsChatResponse;
}

export interface OpsChatErrorEvent {
  type: 'error';
  status_code?: number;
  message: string;
}

export type OpsChatStreamEvent =
  | OpsChatStageEvent
  | OpsChatDeltaEvent
  | OpsChatResultEvent
  | OpsChatErrorEvent;

export interface ActionPreview {
  allowed: boolean;
  risk_level: string;
  summary: string;
  preview_command: string;
  required_approvals: number;
  approval_strategy: string;
  approval_rules: string[];
  policy_checks: string[];
  blocked_reasons: string[];
  validation_messages: string[];
  diff_unified: string;
  dry_run_status: string;
  dry_run_messages: string[];
  next_step: string;
  action_type?: string;
}

export interface ActionRequest {
  request_id: string;
  status: string;
  preview: ActionPreview;
  requested_by: string;
  requested_roles: string[];
  required_approvals: number;
  approval_count: number;
  approver_ids: string[];
  approver_role_map: Record<string, string>;
  decision_note: string;
  connection_id: string;
  namespace: string;
  resource_name: string;
  replicas?: number;
  manifest_yaml?: string;
  created_at: string;
}

export interface ActionExecution {
  execution_id: string;
  request_id: string;
  status: string;
  execution_mode: string;
  simulated: boolean;
  summary: string;
  preflight_checks: string[];
  output_lines: string[];
  error: string;
  created_at: string;
  executed_by: string;
}

export interface ActionAuditItem {
  audit_id: string;
  request_id: string;
  execution_id: string;
  event_type: string;
  summary: string;
  created_at: string;
}

export interface OAuthStartResponse {
  provider: string;
  authorize_url: string;
  state: string;
}

export interface ScmProviderStatusItem {
  configured: boolean;
  client_id_present: boolean;
  client_secret_present: boolean;
}

export interface ScmProviderStatus {
  github: ScmProviderStatusItem;
  gitlab: ScmProviderStatusItem;
}

export interface ScmConnection {
  scm_connection_id: string;
  workspace_id: string;
  provider: string;
  host_url: string;
  auth_type: string;
  account_label: string;
  created_at: string;
  updated_at: string;
}

export interface ScmRepository {
  repository_id: string;
  workspace_id: string;
  scm_connection_id: string;
  repo_full_name: string;
  default_branch: string;
  config_path: string;
  delivery_mode: string;
  manifest_kind: string;
  target_cluster_url: string;
  target_namespace: string;
  auto_deploy_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface DeploymentPlanResponse {
  files_to_change: string[];
  suggested_updates: Array<Record<string, unknown>>;
  trigger_kind: string;
  summary: string;
  commit_title: string;
  commit_body: string;
  requires_pull_request: boolean;
  next_step: string;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  const hasBody = init?.body !== undefined && init?.body !== null;
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  if (hasBody && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${RUNTIME_ORIGIN}${path}`, {
    headers,
    ...init,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Keep default status text.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function requestResponse(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${RUNTIME_ORIGIN}${path}`, init);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Keep default status text.
    }
    throw new Error(message);
  }
  return response;
}

export async function listOpsWorkspaces(): Promise<OpsWorkspace[]> {
  const payload = await requestJson<{ items: OpsWorkspace[] }>('/api/v1/workspaces');
  return payload.items;
}

export async function createOpsWorkspace(payload: { name: string; environment: string }): Promise<OpsWorkspace> {
  return requestJson<OpsWorkspace>('/api/v1/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listRecommendations(workspaceId: string): Promise<RecommendationItem[]> {
  const payload = await requestJson<{ items: RecommendationItem[] }>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/recommendations?limit=10`);
  return payload.items;
}

export async function refreshRecommendations(workspaceId: string, connectionId: string): Promise<RecommendationItem[]> {
  const payload = await requestJson<{ items: RecommendationItem[] }>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/recommendations/refresh`, {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId }),
  });
  return payload.items;
}

export async function connectOcp(payload: Record<string, unknown>): Promise<{ connected: boolean; connection: OcpConnection; message: string }> {
  return requestJson('/api/v1/auth/ocp/connect', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function loadOcpStatus(connectionId: string): Promise<OcpConnection> {
  return requestJson(`/api/v1/auth/ocp/status/${encodeURIComponent(connectionId)}`);
}

export async function testOcpConnection(connectionId: string): Promise<OcpConnectionTestResult> {
  return requestJson('/api/v1/auth/ocp/test', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId }),
  });
}

export async function refreshOcpLease(connectionId: string): Promise<OcpConnectionTestResult> {
  return requestJson('/api/v1/auth/ocp/lease/refresh', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId }),
  });
}

export async function loadOcpLeaseStatus(): Promise<LeaseSchedulerStatus> {
  return requestJson('/api/v1/auth/ocp/lease/status');
}

export async function listOcpProfiles(workspaceId?: string): Promise<OcpConnection[]> {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  const payload = await requestJson<{ items: OcpConnection[] }>(`/api/v1/auth/ocp/profiles${query}`);
  return payload.items;
}

export async function disconnectOcp(connectionId: string): Promise<{ disconnected: boolean; connection_id: string }> {
  return requestJson('/api/v1/auth/ocp/disconnect', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId }),
  });
}

export async function loadOcpOverview(connectionId: string): Promise<OcpOverview> {
  return requestJson(`/api/v1/ocp/overview/${encodeURIComponent(connectionId)}`);
}

export async function loadOcpMetrics(connectionId: string, namespace: string): Promise<OcpMetricsResponse> {
  return requestJson(`/api/v1/ocp/metrics/${encodeURIComponent(connectionId)}?namespace=${encodeURIComponent(namespace)}`);
}

export async function loadNamespaces(connectionId: string): Promise<NamespaceListResponse> {
  return requestJson(`/api/v1/ocp/namespaces/${encodeURIComponent(connectionId)}`);
}

export async function loadResources(connectionId: string, resource: string, namespace: string): Promise<ResourceListResponse> {
  const params = new URLSearchParams({ resource, namespace });
  return requestJson(`/api/v1/ocp/resources/${encodeURIComponent(connectionId)}?${params.toString()}`);
}

export async function loadResourceDetail(connectionId: string, resource: string, namespace: string, name: string): Promise<ResourceDetailResponse> {
  const params = new URLSearchParams({ resource, namespace, name });
  return requestJson(`/api/v1/ocp/resource-detail/${encodeURIComponent(connectionId)}?${params.toString()}`);
}

export async function loadLibrarySummary(workspaceId: string): Promise<LibrarySummary> {
  return requestJson(`/api/v1/library/summary?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export async function loadLibraryCatalog(workspaceId: string): Promise<LibraryCatalogItem[]> {
  const payload = await requestJson<{ items: LibraryCatalogItem[] }>(`/api/v1/library/catalog?workspace_id=${encodeURIComponent(workspaceId)}`);
  return payload.items;
}

export async function loadLibraryChunks(workspaceId: string, documentKey: string): Promise<LibraryChunksResponse> {
  return requestJson(`/api/v1/library/chunks?workspace_id=${encodeURIComponent(workspaceId)}&document_key=${encodeURIComponent(documentKey)}`);
}

export async function loadLibraryDocumentContent(workspaceId: string, documentKey: string): Promise<LibraryDocumentContent> {
  return requestJson(`/api/v1/library/document-content?workspace_id=${encodeURIComponent(workspaceId)}&document_key=${encodeURIComponent(documentKey)}`);
}

export async function loadLibraryDocumentFile(workspaceId: string, documentKey: string): Promise<Blob> {
  const response = await requestResponse(`/api/v1/library/document-file?workspace_id=${encodeURIComponent(workspaceId)}&document_key=${encodeURIComponent(documentKey)}`);
  return response.blob();
}

export async function createBatchJob(payload: Record<string, unknown>): Promise<BatchJob> {
  return requestJson('/api/v1/index/batch/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listBatchJobs(limit = 10): Promise<BatchJob[]> {
  const payload = await requestJson<{ items: BatchJob[] }>(`/api/v1/index/batch/jobs?limit=${encodeURIComponent(String(limit))}`);
  return payload.items;
}

export async function loadBatchJob(jobId: string): Promise<BatchJob> {
  return requestJson(`/api/v1/index/batch/jobs/${encodeURIComponent(jobId)}`);
}

export async function retryBatchJob(jobId: string): Promise<BatchJob> {
  return requestJson(`/api/v1/index/batch/jobs/${encodeURIComponent(jobId)}/retry-failed`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function cancelBatchJob(jobId: string): Promise<BatchJob> {
  return requestJson(`/api/v1/index/batch/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function sendOpsChat(payload: {
  message: string;
  connection_id?: string;
  namespace?: string;
  history?: Array<Record<string, unknown>>;
}): Promise<OpsChatResponse> {
  return requestJson('/api/v1/chat/query', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function sendOpsChatStream(
  payload: {
    message: string;
    connection_id?: string;
    namespace?: string;
    history?: Array<Record<string, unknown>>;
  },
  onEvent: (event: OpsChatStreamEvent) => void,
): Promise<OpsChatResponse> {
  const response = await fetch(`${RUNTIME_ORIGIN}/api/v1/chat/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: OpsChatResponse | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        const event = JSON.parse(line) as OpsChatStreamEvent;
        onEvent(event);
        if (event.type === 'error') {
          throw new Error(event.message);
        }
        if (event.type === 'result') {
          finalResult = event.response;
        }
      }
      newlineIndex = buffer.indexOf('\n');
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer.trim()) as OpsChatStreamEvent;
    onEvent(event);
    if (event.type === 'error') {
      throw new Error(event.message);
    }
    if (event.type === 'result') {
      finalResult = event.response;
    }
  }
  if (!finalResult) {
    throw new Error('stream completed without final result');
  }
  return finalResult;
}

export async function loadDocsPreviewSnippet(sourcePath: string, chunkId: string): Promise<DocsPreviewSnippet> {
  const params = new URLSearchParams({
    source_path: sourcePath,
    chunk_id: chunkId,
  });
  return requestJson(`/api/v1/docs-preview/snippet?${params.toString()}`);
}

export async function previewAction(payload: Record<string, unknown>): Promise<ActionPreview> {
  return requestJson('/api/v1/actions/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function createActionRequest(payload: Record<string, unknown>): Promise<ActionRequest> {
  return requestJson('/api/v1/actions/requests', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listActionRequests(limit = 20): Promise<ActionRequest[]> {
  const payload = await requestJson<{ items: ActionRequest[] }>(`/api/v1/actions/requests?limit=${encodeURIComponent(String(limit))}`);
  return payload.items;
}

export async function approveActionRequest(requestId: string, payload: Record<string, unknown>): Promise<ActionRequest> {
  return requestJson(`/api/v1/actions/requests/${encodeURIComponent(requestId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function rejectActionRequest(requestId: string, payload: Record<string, unknown>): Promise<ActionRequest> {
  return requestJson(`/api/v1/actions/requests/${encodeURIComponent(requestId)}/reject`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function executeActionRequest(requestId: string, payload: Record<string, unknown>): Promise<ActionExecution> {
  return requestJson(`/api/v1/actions/requests/${encodeURIComponent(requestId)}/execute`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listActionExecutions(limit = 20): Promise<ActionExecution[]> {
  const payload = await requestJson<{ items: ActionExecution[] }>(`/api/v1/actions/executions?limit=${encodeURIComponent(String(limit))}`);
  return payload.items;
}

export async function listActionAudit(limit = 20): Promise<ActionAuditItem[]> {
  const payload = await requestJson<{ items: ActionAuditItem[] }>(`/api/v1/actions/audit?limit=${encodeURIComponent(String(limit))}`);
  return payload.items;
}

export async function startOAuth(provider: 'github' | 'gitlab', workspaceId: string): Promise<OAuthStartResponse> {
  return requestJson(`/api/v1/oauth/${provider}/start?workspace_id=${encodeURIComponent(workspaceId)}`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function loadScmProviderStatus(): Promise<ScmProviderStatus> {
  return requestJson('/api/v1/scm/providers/status');
}

export async function listScmConnections(workspaceId: string): Promise<ScmConnection[]> {
  const payload = await requestJson<{ items: ScmConnection[] }>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/connections`);
  return payload.items;
}

export async function createScmConnection(workspaceId: string, payload: Record<string, unknown>): Promise<ScmConnection> {
  return requestJson(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/connections`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listScmRepositories(workspaceId: string): Promise<ScmRepository[]> {
  const payload = await requestJson<{ items: ScmRepository[] }>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/repositories`);
  return payload.items;
}

export async function createScmRepository(workspaceId: string, payload: Record<string, unknown>): Promise<ScmRepository> {
  return requestJson(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/repositories`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateScmRepository(workspaceId: string, repositoryId: string, payload: Record<string, unknown>): Promise<ScmRepository> {
  return requestJson(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/repositories/${encodeURIComponent(repositoryId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function createDeploymentPlan(workspaceId: string, repositoryId: string, payload: Record<string, unknown>): Promise<DeploymentPlanResponse> {
  return requestJson(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/scm/repositories/${encodeURIComponent(repositoryId)}/deployment-plan`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
