import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Activity,
  BookOpen,
  Bot,
  Cable,
  Database,
  GitBranch,
  Layers3,
  Play,
  ShieldCheck,
  Workflow,
} from 'lucide-react';
import './OpsConsolePage.css';
import { ROUTES } from '../app/routes';
import {
  approveActionRequest,
  connectOcp,
  createActionRequest,
  createBatchJob,
  createDeploymentPlan,
  createOpsWorkspace,
  createScmConnection,
  createScmRepository,
  disconnectOcp,
  executeActionRequest,
  listActionAudit,
  listActionExecutions,
  listActionRequests,
  listOcpProfiles,
  listBatchJobs,
  listOpsWorkspaces,
  listRecommendations,
  listScmConnections,
  listScmRepositories,
  loadDocsPreviewSnippet,
  loadLibraryCatalog,
  loadLibraryChunks,
  loadLibraryDocumentContent,
  loadLibraryDocumentFile,
  loadLibrarySummary,
  loadNamespaces,
  loadOcpLeaseStatus,
  loadOcpOverview,
  loadOcpStatus,
  loadOpsModels,
  loadResourceDetail,
  loadResources,
  previewAction,
  refreshOcpLease,
  refreshRecommendations,
  rejectActionRequest,
  saveOpsModels,
  sendOpsChatStream,
  startOAuth,
  testOcpConnection,
  updateScmRepository,
  type ActionAuditItem,
  type ActionExecution,
  type ActionPreview,
  type ActionRequest,
  type BatchJob,
  type DeploymentPlanResponse,
  type DocsPreviewSnippet,
  type LibraryCatalogItem,
  type LibraryChunksResponse,
  type LibraryDocumentContent,
  type LibrarySummary,
  type NamespaceListResponse,
  type OcpConnection,
  type OcpConnectionTestResult,
  type OcpOverview,
  type OpsChatResponse,
  type OpsModelProfile,
  type OpsRouteKey,
  type OpsWorkspace,
  type RecommendationItem,
  type ResourceDetailResponse,
  type ResourceListResponse,
  type ScmConnection,
  type ScmRepository,
} from '../lib/opsConsoleApi';

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: OpsChatResponse['sources'];
  artifacts?: OpsChatResponse['artifacts'];
};

const ROUTE_SECTIONS: Array<{
  key: OpsRouteKey;
  label: string;
  path: string;
  icon: typeof Layers3;
  description: string;
}> = [
  { key: 'workspaces', label: 'Workspaces', path: ROUTES.opsWorkspaces, icon: Layers3, description: '작업 컨텍스트 생성과 active 선택' },
  { key: 'connections', label: 'Connections', path: ROUTES.opsConnections, icon: Cable, description: 'OCP 연결 프로필 생성과 검증' },
  { key: 'models', label: 'Models', path: ROUTES.opsModels, icon: Bot, description: 'workspace 기본 모델 설정' },
  { key: 'overview', label: 'Overview', path: ROUTES.opsOverview, icon: Activity, description: 'cluster overview와 추천' },
  { key: 'resources', label: 'Resources', path: ROUTES.opsResources, icon: Database, description: 'namespace/resource 탐색 및 YAML' },
  { key: 'library', label: 'Library', path: ROUTES.opsLibrary, icon: BookOpen, description: '문서 카탈로그와 batch indexing' },
  { key: 'chat', label: 'Chat', path: ROUTES.opsChat, icon: Workflow, description: '문서와 live 결과를 함께 보는 Copilot' },
  { key: 'actions', label: 'Actions', path: ROUTES.opsActions, icon: ShieldCheck, description: 'preview/request/approve/execute/audit' },
  { key: 'scm', label: 'SCM', path: ROUTES.opsScm, icon: GitBranch, description: 'OAuth, repo profile, deployment plan' },
];

const RESOURCE_OPTIONS = ['pods', 'deployments', 'services', 'routes', 'events'] as const;
const ACTION_OPTIONS = ['scale_deployment', 'rollout_restart', 'log_bundle', 'yaml_apply'] as const;

function sectionFromPath(pathname: string): OpsRouteKey {
  return ROUTE_SECTIONS.find((item) => item.path === pathname)?.key ?? 'workspaces';
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function makeId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function OpsConsolePage() {
  const location = useLocation();
  const section = useMemo(() => sectionFromPath(location.pathname), [location.pathname]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [workspaces, setWorkspaces] = useState<OpsWorkspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(() => window.localStorage.getItem('opsConsole.activeWorkspaceId') ?? '');
  const [workspaceForm, setWorkspaceForm] = useState({ name: '', environment: 'dev' });

  const [modelProfile, setModelProfile] = useState<OpsModelProfile | null>(null);
  const [modelDraft, setModelDraft] = useState({
    chat_provider: 'openai-compatible',
    chat_base_url: '',
    chat_model: '',
    chat_api_key_mode: 'managed',
    embedding_provider: 'tei',
    embedding_base_url: '',
    embedding_model: 'bge-m3',
    embedding_api_key_mode: 'managed',
  });

  const [connections, setConnections] = useState<OcpConnection[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState(() => window.localStorage.getItem('opsConsole.activeConnectionId') ?? '');
  const [connectionForm, setConnectionForm] = useState({
    cluster_url: 'https://api.cluster.example.com:6443',
    auth_mode: 'token',
    verify_ssl: false,
    default_namespace: 'demo',
    display_name: 'dev-cluster',
    save_profile: true,
    token: 'sha256~demo-token',
    username: '',
    password: '',
  });
  const [connectionStatus, setConnectionStatus] = useState<OcpConnection | null>(null);
  const [connectionTest, setConnectionTest] = useState<OcpConnectionTestResult | null>(null);
  const [leaseStatus, setLeaseStatus] = useState<any | null>(null);

  const [overview, setOverview] = useState<OcpOverview | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);

  const [namespaces, setNamespaces] = useState<NamespaceListResponse | null>(null);
  const [selectedNamespace, setSelectedNamespace] = useState('default');
  const [selectedResourceType, setSelectedResourceType] = useState<typeof RESOURCE_OPTIONS[number]>('deployments');
  const [resourceList, setResourceList] = useState<ResourceListResponse | null>(null);
  const [selectedResourceName, setSelectedResourceName] = useState('');
  const [resourceDetail, setResourceDetail] = useState<ResourceDetailResponse | null>(null);
  const [yamlEditor, setYamlEditor] = useState('');
  const [yamlPreview, setYamlPreview] = useState<ActionPreview | null>(null);

  const [librarySummary, setLibrarySummary] = useState<LibrarySummary | null>(null);
  const [libraryCatalog, setLibraryCatalog] = useState<LibraryCatalogItem[]>([]);
  const [libraryChunks, setLibraryChunks] = useState<LibraryChunksResponse | null>(null);
  const [libraryContent, setLibraryContent] = useState<LibraryDocumentContent | null>(null);
  const [batchJobs, setBatchJobs] = useState<BatchJob[]>([]);
  const [batchForm, setBatchForm] = useState({
    root_path: 'data',
    source_type: 'generated-manual',
    document_group: 'official_ocp',
    locale: 'ko',
    max_files: 5,
    include_subdirectories: true,
  });

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatDraft, setChatDraft] = useState('');
  const [chatStages, setChatStages] = useState<Array<{ label: string; detail: string; status: string }>>([]);
  const [chatSending, setChatSending] = useState(false);
  const [snippet, setSnippet] = useState<DocsPreviewSnippet | null>(null);

  const [actionForm, setActionForm] = useState({
    actor_id: 'alice',
    actor_roles: 'operator',
    action_type: 'scale_deployment',
    resource_name: 'payments-api',
    replicas: 3,
    reason: 'scale out',
  });
  const [actionPreviewData, setActionPreviewData] = useState<ActionPreview | null>(null);
  const [actionRequests, setActionRequests] = useState<ActionRequest[]>([]);
  const [actionExecutions, setActionExecutions] = useState<ActionExecution[]>([]);
  const [actionAudit, setActionAudit] = useState<ActionAuditItem[]>([]);

  const [scmConnections, setScmConnections] = useState<ScmConnection[]>([]);
  const [scmRepositories, setScmRepositories] = useState<ScmRepository[]>([]);
  const [scmConnectionForm, setScmConnectionForm] = useState({
    provider: 'github',
    host_url: 'https://github.com',
    auth_type: 'token',
    account_label: 'customer-admin',
  });
  const [repositoryForm, setRepositoryForm] = useState({
    scm_connection_id: '',
    repo_full_name: 'org/project',
    default_branch: 'main',
    config_path: 'kustomization.yaml',
    delivery_mode: 'gitops_commit',
    manifest_kind: 'config_yaml',
    target_cluster_url: 'https://api.cluster.example.com:6443',
    target_namespace: 'payments',
    auto_deploy_enabled: true,
  });
  const [deploymentPlan, setDeploymentPlan] = useState<DeploymentPlanResponse | null>(null);

  const activeWorkspace = workspaces.find((item) => item.workspace_id === activeWorkspaceId) ?? null;
  const activeConnection = connections.find((item) => item.connection_id === activeConnectionId) ?? null;
  const sectionMeta = ROUTE_SECTIONS.find((item) => item.key === section) ?? ROUTE_SECTIONS[0];

  useEffect(() => {
    window.localStorage.setItem('opsConsole.activeWorkspaceId', activeWorkspaceId);
  }, [activeWorkspaceId]);

  useEffect(() => {
    window.localStorage.setItem('opsConsole.activeConnectionId', activeConnectionId);
  }, [activeConnectionId]);

  useEffect(() => {
    void refreshWorkspaces();
    void refreshConnections();
    void refreshLeaseStatus();
    void refreshActions();
  }, []);

  useEffect(() => {
    if (!activeWorkspaceId && workspaces.length > 0) {
      setActiveWorkspaceId(workspaces[0].workspace_id);
    }
  }, [workspaces, activeWorkspaceId]);

  useEffect(() => {
    if (!activeWorkspaceId) {
      return;
    }
    void refreshConnections(activeWorkspaceId);
    void refreshModels(activeWorkspaceId);
    void refreshRecommendationsForWorkspace(activeWorkspaceId);
    void refreshLibrary(activeWorkspaceId);
    void refreshScm(activeWorkspaceId);
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (!activeConnectionId) {
      return;
    }
    void refreshConnectionStatus(activeConnectionId);
    void refreshOverview(activeConnectionId);
    void refreshNamespaces(activeConnectionId);
  }, [activeConnectionId]);

  useEffect(() => {
    if (!activeConnectionId || !selectedNamespace || !selectedResourceType) {
      return;
    }
    void refreshResources(activeConnectionId, selectedResourceType, selectedNamespace);
  }, [activeConnectionId, selectedNamespace, selectedResourceType]);

  useEffect(() => {
    if (!resourceDetail) {
      return;
    }
    setYamlEditor(resourceDetail.manifest_yaml);
  }, [resourceDetail]);

  useEffect(() => {
    if (!repositoryForm.scm_connection_id && scmConnections.length > 0) {
      setRepositoryForm((current) => ({ ...current, scm_connection_id: scmConnections[0].scm_connection_id }));
    }
  }, [repositoryForm.scm_connection_id, scmConnections]);

  async function run<T>(callback: () => Promise<T>, onSuccess?: (value: T) => void) {
    setError('');
    try {
      const value = await callback();
      onSuccess?.(value);
      return value;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '요청 처리 중 오류가 발생했습니다.');
      return null;
    }
  }

  async function refreshWorkspaces() {
    return run(async () => listOpsWorkspaces(), (items) => setWorkspaces(items));
  }

  async function refreshConnections(workspaceId?: string) {
    return run(async () => listOcpProfiles(workspaceId), (items) => {
      setConnections(items);
      if (items.length > 0 && !items.some((item) => item.connection_id === activeConnectionId)) {
        setActiveConnectionId(items[0].connection_id);
      }
      if (items.length === 0) {
        setActiveConnectionId('');
      }
    });
  }

  async function refreshConnectionStatus(connectionId: string) {
    return run(async () => loadOcpStatus(connectionId), (value) => {
      setConnectionStatus(value);
      setConnections((current) => {
        const exists = current.some((item) => item.connection_id === value.connection_id);
        if (exists) {
          return current.map((item) => (item.connection_id === value.connection_id ? value : item));
        }
        return [value, ...current];
      });
    });
  }

  async function refreshLeaseStatus() {
    return run(async () => loadOcpLeaseStatus(), (value) => setLeaseStatus(value));
  }

  async function refreshModels(workspaceId: string) {
    return run(async () => loadOpsModels(workspaceId), (value) => {
      setModelProfile(value);
      setModelDraft({
        chat_provider: value.chat_provider,
        chat_base_url: value.chat_base_url,
        chat_model: value.chat_model,
        chat_api_key_mode: value.chat_api_key_mode,
        embedding_provider: value.embedding_provider,
        embedding_base_url: value.embedding_base_url,
        embedding_model: value.embedding_model,
        embedding_api_key_mode: value.embedding_api_key_mode,
      });
    });
  }

  async function refreshRecommendationsForWorkspace(workspaceId: string) {
    return run(async () => listRecommendations(workspaceId), (value) => setRecommendations(value));
  }

  async function refreshOverview(connectionId: string) {
    return run(async () => loadOcpOverview(connectionId), (value) => setOverview(value));
  }

  async function refreshNamespaces(connectionId: string) {
    return run(async () => loadNamespaces(connectionId), (value) => {
      setNamespaces(value);
      if (!value.items.includes(selectedNamespace)) {
        setSelectedNamespace(value.items[0] ?? 'default');
      }
    });
  }

  async function refreshResources(connectionId: string, resourceType: string, namespace: string) {
    return run(async () => loadResources(connectionId, resourceType, namespace), (value) => {
      setResourceList(value);
      const preferredName = value.items.some((item) => item.name === selectedResourceName)
        ? selectedResourceName
        : value.items[0]?.name ?? '';
      setSelectedResourceName(preferredName);
      if (preferredName) {
        void openResourceDetail(connectionId, resourceType, namespace, preferredName);
      } else {
        setResourceDetail(null);
        setYamlEditor('');
      }
    });
  }

  async function refreshLibrary(workspaceId: string) {
    await run(async () => loadLibrarySummary(workspaceId), (value) => setLibrarySummary(value));
    await run(async () => loadLibraryCatalog(workspaceId), (value) => setLibraryCatalog(value));
    await run(async () => listBatchJobs(), (value) => setBatchJobs(value));
  }

  async function refreshActions() {
    await run(async () => listActionRequests(), (value) => setActionRequests(value));
    await run(async () => listActionExecutions(), (value) => setActionExecutions(value));
    await run(async () => listActionAudit(), (value) => setActionAudit(value));
  }

  async function refreshScm(workspaceId: string) {
    await run(async () => listScmConnections(workspaceId), (value) => setScmConnections(value));
    await run(async () => listScmRepositories(workspaceId), (value) => setScmRepositories(value));
  }

  async function openResourceDetail(connectionId: string, resourceType: string, namespace: string, name: string) {
    setSelectedResourceName(name);
    await run(async () => loadResourceDetail(connectionId, resourceType, namespace, name), (value) => setResourceDetail(value));
  }

  async function handleCreateWorkspace() {
    const created = await run(
      async () => createOpsWorkspace(workspaceForm),
      (value) => {
        setNotice(`Workspace "${value.name}" created.`);
        setWorkspaceForm({ name: '', environment: 'dev' });
        setWorkspaces((current) => [value, ...current]);
        setActiveWorkspaceId(value.workspace_id);
      },
    );
    if (created) {
      await refreshWorkspaces();
    }
  }

  async function handleCreateConnection() {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    const created = await run(
      async () => connectOcp({ workspace_id: activeWorkspaceId, ...connectionForm }),
      (value) => {
        setNotice(value.message);
        setConnections((current) => [value.connection, ...current.filter((item) => item.connection_id !== value.connection.connection_id)]);
        setActiveConnectionId(value.connection.connection_id);
      },
    );
    if (created) {
      await refreshConnectionStatus(created.connection.connection_id);
      await refreshRecommendationsForWorkspace(activeWorkspaceId);
    }
  }

  async function handleTestConnection() {
    if (!activeConnectionId) {
      setError('먼저 연결을 선택하세요.');
      return;
    }
    await run(async () => testOcpConnection(activeConnectionId), (value) => {
      setConnectionTest(value);
      setNotice(value.message);
    });
  }

  async function handleRefreshLease() {
    if (!activeConnectionId) {
      setError('먼저 연결을 선택하세요.');
      return;
    }
    await run(async () => refreshOcpLease(activeConnectionId), (value) => {
      setConnectionTest(value);
      setNotice('Lease metadata refreshed.');
    });
    await refreshLeaseStatus();
  }

  async function handleDisconnect() {
    if (!activeConnectionId) {
      setError('먼저 연결을 선택하세요.');
      return;
    }
    const disconnectedId = activeConnectionId;
    const result = await run(async () => disconnectOcp(disconnectedId), () => {
      setNotice('Connection disconnected.');
      setConnections((current) => current.filter((item) => item.connection_id !== disconnectedId));
      setActiveConnectionId('');
      setConnectionStatus(null);
      setConnectionTest(null);
      setOverview(null);
    });
    if (result) {
      await refreshLeaseStatus();
    }
  }

  async function handleSaveModels() {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    await run(async () => saveOpsModels(activeWorkspaceId, modelDraft), (value) => {
      setModelProfile(value);
      setNotice('Model profile saved.');
    });
  }

  async function handleRefreshRecommendations() {
    if (!activeWorkspaceId || !activeConnectionId) {
      setError('workspace와 connection이 모두 필요합니다.');
      return;
    }
    await run(async () => refreshRecommendations(activeWorkspaceId, activeConnectionId), (value) => {
      setRecommendations(value);
      setNotice('Recommendations refreshed.');
    });
  }

  async function handlePreviewYaml() {
    if (!activeConnectionId || !selectedResourceName) {
      setError('리소스를 먼저 선택하세요.');
      return;
    }
    await run(
      async () => previewAction({
        connection_id: activeConnectionId,
        actor_id: actionForm.actor_id,
        actor_roles: actionForm.actor_roles.split(',').map((item) => item.trim()).filter(Boolean),
        action_type: 'yaml_apply',
        namespace: selectedNamespace,
        resource_name: selectedResourceName,
        reason: 'edit resource yaml',
        manifest_yaml: yamlEditor,
      }),
      (value) => setYamlPreview(value),
    );
  }

  async function handleCreateBatchJob() {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    await run(
      async () => createBatchJob({ workspace_id: activeWorkspaceId, ...batchForm }),
      (value) => {
        setBatchJobs((current) => [value, ...current]);
        setNotice('Batch indexing job created.');
      },
    );
  }

  async function handleOpenChunks(documentKey: string) {
    if (!activeWorkspaceId) {
      return;
    }
    await run(async () => loadLibraryChunks(activeWorkspaceId, documentKey), (value) => setLibraryChunks(value));
  }

  async function handleOpenContent(documentKey: string) {
    if (!activeWorkspaceId) {
      return;
    }
    await run(async () => loadLibraryDocumentContent(activeWorkspaceId, documentKey), (value) => setLibraryContent(value));
  }

  async function handleDownloadDocument(documentKey: string) {
    if (!activeWorkspaceId) {
      return;
    }
    const blob = await run(async () => loadLibraryDocumentFile(activeWorkspaceId, documentKey));
    if (!blob) {
      return;
    }
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${documentKey}.json`;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

  async function handleSendChat() {
    const message = chatDraft.trim();
    if (!message) {
      return;
    }
    const userMessage: ChatMessage = { id: makeId('user'), role: 'user', content: message };
    const assistantId = makeId('assistant');
    setMessages((current) => [...current, userMessage, { id: assistantId, role: 'assistant', content: '' }]);
    setChatDraft('');
    setChatStages([]);
    setChatSending(true);
    setError('');
    try {
      const result = await sendOpsChatStream(
        {
          message,
          connection_id: activeConnectionId || undefined,
          namespace: selectedNamespace || undefined,
          history: messages.slice(-6).map((item) => ({ role: item.role, text: item.content })),
        },
        (event) => {
          if (event.type === 'stage') {
            setChatStages((current) => [...current, event.stage]);
            return;
          }
          if (event.type === 'answer_delta') {
            setMessages((current) => current.map((item) => (item.id === assistantId ? { ...item, content: item.content + event.delta } : item)));
            return;
          }
          if (event.type === 'result') {
            setMessages((current) => current.map((item) => (
              item.id === assistantId
                ? {
                  ...item,
                  content: event.response.answer,
                  sources: event.response.sources,
                  artifacts: event.response.artifacts,
                }
                : item
            )));
          }
        },
      );
      setNotice(`Chat completed in ${result.mode} mode.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '채팅 처리 중 오류가 발생했습니다.');
    } finally {
      setChatSending(false);
    }
  }

  async function handleOpenSnippet(sourcePath: string, chunkId: string) {
    await run(async () => loadDocsPreviewSnippet(sourcePath, chunkId), (value) => setSnippet(value));
  }

  async function handlePreviewAction() {
    if (!activeConnectionId) {
      setError('먼저 연결을 선택하세요.');
      return;
    }
    await run(
      async () => previewAction({
        connection_id: activeConnectionId,
        actor_id: actionForm.actor_id,
        actor_roles: actionForm.actor_roles.split(',').map((item) => item.trim()).filter(Boolean),
        action_type: actionForm.action_type,
        namespace: selectedNamespace,
        resource_name: actionForm.resource_name,
        replicas: actionForm.replicas,
        reason: actionForm.reason,
        manifest_yaml: yamlEditor,
      }),
      (value) => setActionPreviewData(value),
    );
  }

  async function handleCreateActionRequest() {
    if (!activeConnectionId) {
      setError('먼저 연결을 선택하세요.');
      return;
    }
    await run(
      async () => createActionRequest({
        connection_id: activeConnectionId,
        actor_id: actionForm.actor_id,
        actor_roles: actionForm.actor_roles.split(',').map((item) => item.trim()).filter(Boolean),
        action_type: actionForm.action_type,
        namespace: selectedNamespace,
        resource_name: actionForm.resource_name,
        replicas: actionForm.replicas,
        reason: actionForm.reason,
        manifest_yaml: yamlEditor,
      }),
      (value) => {
        setActionRequests((current) => [value, ...current]);
        setNotice('Action request created.');
      },
    );
    await refreshActions();
  }

  async function handleApproveRequest(requestId: string) {
    await run(async () => approveActionRequest(requestId, { actor_id: 'alice', actor_roles: ['operator'], decision_note: 'approved from UI' }));
    await refreshActions();
  }

  async function handleRejectRequest(requestId: string) {
    await run(async () => rejectActionRequest(requestId, { actor_id: 'alice', actor_roles: ['operator'], decision_note: 'rejected from UI' }));
    await refreshActions();
  }

  async function handleExecuteRequest(requestId: string) {
    await run(async () => executeActionRequest(requestId, { actor_id: 'alice', actor_roles: ['operator'], execution_note: 'requested from UI', force: false }));
    await refreshActions();
    if (activeConnectionId) {
      await refreshOverview(activeConnectionId);
      await refreshResources(activeConnectionId, selectedResourceType, selectedNamespace);
    }
  }

  async function handleStartOAuth(provider: 'github' | 'gitlab') {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    await run(async () => startOAuth(provider, activeWorkspaceId), (value) => {
      setNotice(`OAuth start created. Redirect URL: ${value.authorize_url}`);
      window.open(value.authorize_url, '_blank', 'noopener,noreferrer');
    });
  }

  async function handleCreateScmConnection() {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    await run(async () => createScmConnection(activeWorkspaceId, scmConnectionForm), () => {
      setNotice('SCM connection created.');
    });
    await refreshScm(activeWorkspaceId);
  }

  async function handleCreateRepository() {
    if (!activeWorkspaceId) {
      setError('먼저 active workspace를 선택하세요.');
      return;
    }
    await run(async () => createScmRepository(activeWorkspaceId, repositoryForm), () => {
      setNotice('Repository delivery profile created.');
    });
    await refreshScm(activeWorkspaceId);
  }

  async function handleUpdateRepository(repositoryId: string) {
    if (!activeWorkspaceId) {
      return;
    }
    await run(async () => updateScmRepository(activeWorkspaceId, repositoryId, { auto_deploy_enabled: false }), () => {
      setNotice('Repository profile updated.');
    });
    await refreshScm(activeWorkspaceId);
  }

  async function handleCreateDeploymentPlan(repositoryId: string) {
    if (!activeWorkspaceId) {
      return;
    }
    await run(
      async () => createDeploymentPlan(activeWorkspaceId, repositoryId, {
        resource_kind: 'Deployment',
        resource_name: actionForm.resource_name,
        target_namespace: repositoryForm.target_namespace,
        replicas: actionForm.replicas,
        config_key: 'replicas',
        reason: actionForm.reason,
      }),
      (value) => setDeploymentPlan(value),
    );
  }

  const contextCards = [
    { label: 'Active workspace', value: activeWorkspace?.name || 'Not selected' },
    { label: 'Active connection', value: activeConnection?.display_name || 'Not connected' },
    { label: 'Current section', value: sectionMeta.label },
  ];

  return (
    <div className="ops-console-page">
      <header className="ops-console-hero">
        <div>
          <div className="ops-console-kicker">Current Spec Console</div>
          <div className="ops-console-return-row">
            <Link to={ROUTES.sharedHome} className="ops-return-link">Landing</Link>
            <Link to={ROUTES.pbsStudio} className="ops-return-link">Studio</Link>
            <Link to={ROUTES.pbsPlaybookLibrary} className="ops-return-link">Library</Link>
          </div>
          <h1>Operations Console</h1>
          <p>{sectionMeta.description}</p>
        </div>
        <div className="ops-console-context-grid">
          {contextCards.map((card) => (
            <div key={card.label} className="ops-context-card">
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </div>
          ))}
        </div>
      </header>

      <nav className="ops-console-nav">
        {ROUTE_SECTIONS.map((item) => {
          const Icon = item.icon;
          return (
            <Link key={item.key} to={item.path} className={`ops-nav-pill ${item.key === section ? 'active' : ''}`}>
              <Icon size={16} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {notice ? <div className="ops-banner success">{notice}</div> : null}
      {error ? <div className="ops-banner error">{error}</div> : null}

      <div className="ops-console-layout">
        <aside className="ops-sidebar">
          <section className="ops-panel">
            <div className="ops-panel-header">
              <h3>Workspace Context</h3>
            </div>
            <div className="ops-field">
              <label>Active workspace</label>
              <select value={activeWorkspaceId} onChange={(event) => setActiveWorkspaceId(event.target.value)}>
                {workspaces.map((workspace) => (
                  <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>
                ))}
              </select>
            </div>
            <div className="ops-field">
              <label>Active connection</label>
              <select value={activeConnectionId} onChange={(event) => setActiveConnectionId(event.target.value)}>
                <option value="">Select connection</option>
                {connections.map((connection) => (
                  <option key={connection.connection_id} value={connection.connection_id}>{connection.display_name}</option>
                ))}
              </select>
            </div>
          </section>

          <section className="ops-panel">
            <div className="ops-panel-header">
              <h3>Section Intent</h3>
            </div>
            <p className="ops-muted">{sectionMeta.description}</p>
            <ul className="ops-compact-list">
              <li>문서 스펙 경로를 그대로 유지합니다.</li>
              <li>기존 PBS 셸과 충돌 없이 병행 동작합니다.</li>
              <li>상태는 로컬 JSON 저장소를 사용합니다.</li>
            </ul>
          </section>
        </aside>

        <main className="ops-main">
          {section === 'workspaces' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Workspace Management</h2>
              </div>
              <div className="ops-form-grid">
                <div className="ops-field">
                  <label>Name</label>
                  <input value={workspaceForm.name} onChange={(event) => setWorkspaceForm((current) => ({ ...current, name: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Environment</label>
                  <input value={workspaceForm.environment} onChange={(event) => setWorkspaceForm((current) => ({ ...current, environment: event.target.value }))} />
                </div>
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateWorkspace(); }}>Create workspace</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void refreshWorkspaces(); }}>Refresh list</button>
              </div>
              <div className="ops-card-grid">
                {workspaces.map((workspace) => (
                  <button key={workspace.workspace_id} type="button" className={`ops-record-card ${workspace.workspace_id === activeWorkspaceId ? 'selected' : ''}`} onClick={() => setActiveWorkspaceId(workspace.workspace_id)}>
                    <strong>{workspace.name}</strong>
                    <span>{workspace.environment}</span>
                    <span>{workspace.slug}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {section === 'connections' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>OpenShift Connections</h2>
              </div>
              <div className="ops-form-grid three">
                <div className="ops-field">
                  <label>Cluster URL</label>
                  <input value={connectionForm.cluster_url} onChange={(event) => setConnectionForm((current) => ({ ...current, cluster_url: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Auth mode</label>
                  <select value={connectionForm.auth_mode} onChange={(event) => setConnectionForm((current) => ({ ...current, auth_mode: event.target.value }))}>
                    <option value="token">token</option>
                    <option value="password">password</option>
                  </select>
                </div>
                <div className="ops-field">
                  <label>Default namespace</label>
                  <input value={connectionForm.default_namespace} disabled />
                </div>
                <div className="ops-field">
                  <label>Display name</label>
                  <input value={connectionForm.display_name} onChange={(event) => setConnectionForm((current) => ({ ...current, display_name: event.target.value }))} />
                </div>
                {connectionForm.auth_mode === 'token' ? (
                  <div className="ops-field">
                    <label>Token</label>
                    <input value={connectionForm.token} onChange={(event) => setConnectionForm((current) => ({ ...current, token: event.target.value }))} />
                  </div>
                ) : (
                  <>
                    <div className="ops-field">
                      <label>Username</label>
                      <input value={connectionForm.username} onChange={(event) => setConnectionForm((current) => ({ ...current, username: event.target.value }))} />
                    </div>
                    <div className="ops-field">
                      <label>Password</label>
                      <input type="password" value={connectionForm.password} onChange={(event) => setConnectionForm((current) => ({ ...current, password: event.target.value }))} />
                    </div>
                  </>
                )}
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateConnection(); }}>Create connection</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleTestConnection(); }}>Test connection</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleRefreshLease(); }}>Refresh lease</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleDisconnect(); }}>Disconnect</button>
              </div>
              <div className="ops-card-grid">
                {connections.map((connection) => (
                  <button key={connection.connection_id} type="button" className={`ops-record-card ${connection.connection_id === activeConnectionId ? 'selected' : ''}`} onClick={() => setActiveConnectionId(connection.connection_id)}>
                    <strong>{connection.display_name}</strong>
                    <span>{connection.cluster_url}</span>
                    <span>{connection.default_namespace}</span>
                  </button>
                ))}
              </div>
              <div className="ops-detail-grid">
                <pre>{formatJson(connectionStatus)}</pre>
                <pre>{formatJson(connectionTest)}</pre>
                <pre>{formatJson(leaseStatus)}</pre>
              </div>
            </section>
          )}

          {section === 'models' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Workspace Models</h2>
              </div>
              <div className="ops-form-grid two">
                {Object.entries(modelDraft).map(([key, value]) => (
                  <div key={key} className="ops-field">
                    <label>{key}</label>
                    <input value={value} onChange={(event) => setModelDraft((current) => ({ ...current, [key]: event.target.value }))} />
                  </div>
                ))}
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleSaveModels(); }}>Save models</button>
              </div>
              <pre>{formatJson(modelProfile)}</pre>
            </section>
          )}

          {section === 'overview' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Cluster Overview</h2>
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleRefreshRecommendations(); }}>Refresh recommendations</button>
              </div>
              <div className="ops-metric-grid">
                <div className="ops-metric-card">
                  <span>Namespaces</span>
                  <strong>{overview?.namespace_count ?? 0}</strong>
                </div>
                {Object.entries(overview?.resource_counts ?? {}).map(([key, value]) => (
                  <div key={key} className="ops-metric-card">
                    <span>{key}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <div className="ops-card-grid">
                {recommendations.map((item) => (
                  <article key={item.recommendation_id} className="ops-record-card static">
                    <strong>{item.summary}</strong>
                    <span>{item.risk_level}</span>
                    <span>{item.rationale}</span>
                  </article>
                ))}
              </div>
            </section>
          )}

          {section === 'resources' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Resource Explorer</h2>
              </div>
              <div className="ops-actions-row">
                <select value={selectedNamespace} onChange={(event) => setSelectedNamespace(event.target.value)}>
                  {(namespaces?.items ?? []).map((namespace) => (
                    <option key={namespace} value={namespace}>{namespace}</option>
                  ))}
                </select>
                <div className="ops-chip-group">
                  {RESOURCE_OPTIONS.map((resourceType) => (
                    <button key={resourceType} type="button" className={`ops-chip ${selectedResourceType === resourceType ? 'active' : ''}`} onClick={() => setSelectedResourceType(resourceType)}>
                      {resourceType}
                    </button>
                  ))}
                </div>
              </div>
              <div className="ops-split-grid">
                <div className="ops-list">
                  {(resourceList?.items ?? []).map((item) => (
                    <button key={item.name} type="button" className={`ops-list-row ${selectedResourceName === item.name ? 'selected' : ''}`} onClick={() => { if (activeConnectionId) { void openResourceDetail(activeConnectionId, selectedResourceType, selectedNamespace, item.name); } }}>
                      <strong>{item.name}</strong>
                      <span>{item.kind}</span>
                    </button>
                  ))}
                </div>
                <div className="ops-editor-column">
                  <textarea value={yamlEditor} onChange={(event) => setYamlEditor(event.target.value)} />
                  <div className="ops-actions-row">
                    <button type="button" className="ops-primary-btn" onClick={() => { void handlePreviewYaml(); }}>Preview apply</button>
                    <button
                      type="button"
                      className="ops-secondary-btn"
                      onClick={() => {
                        const copyRequest = navigator.clipboard?.writeText?.(yamlEditor);
                        copyRequest?.catch(() => undefined);
                      }}
                    >
                      Copy YAML
                    </button>
                  </div>
                  {yamlPreview ? <pre>{yamlPreview.diff_unified || yamlPreview.summary}</pre> : null}
                </div>
              </div>
            </section>
          )}

          {section === 'library' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Library & Batch Indexing</h2>
              </div>
              <div className="ops-metric-grid">
                <div className="ops-metric-card">
                  <span>Indexed docs</span>
                  <strong>{librarySummary?.indexed_documents ?? 0}</strong>
                </div>
                <div className="ops-metric-card">
                  <span>Indexed chunks</span>
                  <strong>{librarySummary?.indexed_chunks ?? 0}</strong>
                </div>
                <div className="ops-metric-card">
                  <span>Corpus files</span>
                  <strong>{librarySummary?.corpus_files ?? 0}</strong>
                </div>
              </div>
              <div className="ops-form-grid three">
                <div className="ops-field">
                  <label>Root path</label>
                  <input value={batchForm.root_path} onChange={(event) => setBatchForm((current) => ({ ...current, root_path: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Source type</label>
                  <input value={batchForm.source_type} onChange={(event) => setBatchForm((current) => ({ ...current, source_type: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Max files</label>
                  <input type="number" value={batchForm.max_files} onChange={(event) => setBatchForm((current) => ({ ...current, max_files: Number(event.target.value) || 1 }))} />
                </div>
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateBatchJob(); }}>Create batch job</button>
              </div>
              <div className="ops-table">
                {libraryCatalog.map((item) => (
                  <div key={item.document_key} className="ops-table-row">
                    <div>
                      <strong>{item.title}</strong>
                      <span>{item.relative_path}</span>
                    </div>
                    <div className="ops-inline-actions">
                      <button type="button" onClick={() => { void handleOpenChunks(item.document_key); }}>Chunks</button>
                      <button type="button" onClick={() => { void handleOpenContent(item.document_key); }}>Content</button>
                      <button type="button" onClick={() => { void handleDownloadDocument(item.document_key); }}>File</button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="ops-detail-grid">
                <pre>{formatJson(libraryChunks)}</pre>
                <pre>{libraryContent?.content || ''}</pre>
                <pre>{formatJson(batchJobs)}</pre>
              </div>
            </section>
          )}

          {section === 'chat' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Copilot Chat</h2>
              </div>
              <div className="ops-chat-transcript">
                {messages.map((message) => (
                  <article key={message.id} className={`ops-chat-bubble ${message.role}`}>
                    <strong>{message.role === 'user' ? 'User' : 'Assistant'}</strong>
                    <p>{message.content}</p>
                    {message.sources?.length ? (
                      <div className="ops-inline-actions">
                        {message.sources.map((source) => (
                          <button key={`${message.id}-${source.index}`} type="button" onClick={() => { void handleOpenSnippet(source.source_path, source.chunk_id); }}>
                            {source.title}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {message.artifacts?.length ? <pre>{formatJson(message.artifacts)}</pre> : null}
                  </article>
                ))}
              </div>
              {chatStages.length ? <pre>{formatJson(chatStages)}</pre> : null}
              <div className="ops-chat-composer">
                <input value={chatDraft} onChange={(event) => setChatDraft(event.target.value)} placeholder="문서나 리소스 상태를 질문하세요" />
                <button type="button" className="ops-primary-btn" disabled={chatSending} onClick={() => { void handleSendChat(); }}>
                  <Play size={14} />
                  <span>{chatSending ? 'Running' : 'Send'}</span>
                </button>
              </div>
              {snippet ? <pre>{snippet.snippet}</pre> : null}
            </section>
          )}

          {section === 'actions' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Guarded Actions</h2>
              </div>
              <div className="ops-form-grid three">
                <div className="ops-field">
                  <label>Actor ID</label>
                  <input value={actionForm.actor_id} onChange={(event) => setActionForm((current) => ({ ...current, actor_id: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Actor roles</label>
                  <input value={actionForm.actor_roles} onChange={(event) => setActionForm((current) => ({ ...current, actor_roles: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Action type</label>
                  <select value={actionForm.action_type} onChange={(event) => setActionForm((current) => ({ ...current, action_type: event.target.value }))}>
                    {ACTION_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </div>
                <div className="ops-field">
                  <label>Resource name</label>
                  <input value={actionForm.resource_name} onChange={(event) => setActionForm((current) => ({ ...current, resource_name: event.target.value }))} />
                </div>
                <div className="ops-field">
                  <label>Replicas</label>
                  <input type="number" value={actionForm.replicas} onChange={(event) => setActionForm((current) => ({ ...current, replicas: Number(event.target.value) || 1 }))} />
                </div>
                <div className="ops-field">
                  <label>Reason</label>
                  <input value={actionForm.reason} onChange={(event) => setActionForm((current) => ({ ...current, reason: event.target.value }))} />
                </div>
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handlePreviewAction(); }}>Preview</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleCreateActionRequest(); }}>Create request</button>
              </div>
              {actionPreviewData ? <pre>{formatJson(actionPreviewData)}</pre> : null}
              <div className="ops-detail-grid">
                <div>
                  <h3>Requests</h3>
                  {actionRequests.map((item) => (
                    <div key={item.request_id} className="ops-table-row">
                      <div>
                        <strong>{item.request_id}</strong>
                        <span>{item.status}</span>
                      </div>
                      <div className="ops-inline-actions">
                        <button type="button" onClick={() => { void handleApproveRequest(item.request_id); }}>Approve</button>
                        <button type="button" onClick={() => { void handleRejectRequest(item.request_id); }}>Reject</button>
                        <button type="button" onClick={() => { void handleExecuteRequest(item.request_id); }}>Execute</button>
                      </div>
                    </div>
                  ))}
                </div>
                <pre>{formatJson(actionExecutions)}</pre>
                <pre>{formatJson(actionAudit)}</pre>
              </div>
            </section>
          )}

          {section === 'scm' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>SCM & Deployment Plan</h2>
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleStartOAuth('github'); }}>OAuth GitHub</button>
                <button type="button" className="ops-secondary-btn" onClick={() => { void handleStartOAuth('gitlab'); }}>OAuth GitLab</button>
              </div>
              <div className="ops-form-grid four">
                {Object.entries(scmConnectionForm).map(([key, value]) => (
                  <div key={key} className="ops-field">
                    <label>{key}</label>
                    <input value={value} onChange={(event) => setScmConnectionForm((current) => ({ ...current, [key]: event.target.value }))} />
                  </div>
                ))}
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateScmConnection(); }}>Create SCM connection</button>
              </div>
              <div className="ops-form-grid four">
                {Object.entries(repositoryForm).map(([key, value]) => (
                  <div key={key} className="ops-field">
                    <label>{key}</label>
                    {typeof value === 'boolean' ? (
                      <select value={String(value)} onChange={(event) => setRepositoryForm((current) => ({ ...current, [key]: event.target.value === 'true' }))}>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      <input value={String(value)} onChange={(event) => setRepositoryForm((current) => ({ ...current, [key]: event.target.value }))} />
                    )}
                  </div>
                ))}
              </div>
              <div className="ops-actions-row">
                <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateRepository(); }}>Create repository profile</button>
              </div>
              <div className="ops-detail-grid">
                <div>
                  <h3>Connections</h3>
                  <pre>{formatJson(scmConnections)}</pre>
                </div>
                <div>
                  <h3>Repositories</h3>
                  {scmRepositories.map((repository) => (
                    <div key={repository.repository_id} className="ops-table-row">
                      <div>
                        <strong>{repository.repo_full_name}</strong>
                        <span>{repository.default_branch}</span>
                      </div>
                      <div className="ops-inline-actions">
                        <button type="button" onClick={() => { void handleUpdateRepository(repository.repository_id); }}>Disable auto deploy</button>
                        <button type="button" onClick={() => { void handleCreateDeploymentPlan(repository.repository_id); }}>Plan</button>
                      </div>
                    </div>
                  ))}
                </div>
                <pre>{formatJson(deploymentPlan)}</pre>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
