import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  Activity,
  ArrowRight,
  BookOpen,
  Cable,
  Database,
  Send,
  ShieldCheck,
  Sparkles,
  Workflow,
  X,
} from 'lucide-react';
import './OpsConsolePage.css';
import { ROUTES } from '../app/routes';
import {
  approveActionRequest,
  connectOcp,
  createActionRequest,
  createBatchJob,
  disconnectOcp,
  executeActionRequest,
  listActionAudit,
  listActionExecutions,
  listActionRequests,
  listOcpProfiles,
  listBatchJobs,
  listOpsWorkspaces,
  listRecommendations,
  loadDocsPreviewSnippet,
  loadLibraryCatalog,
  loadLibraryChunks,
  loadLibraryDocumentContent,
  loadLibraryDocumentFile,
  loadLibrarySummary,
  loadNamespaces,
  loadOcpLeaseStatus,
  loadOcpMetrics,
  loadOcpOverview,
  loadOcpStatus,
  loadResourceDetail,
  loadResources,
  previewAction,
  refreshOcpLease,
  rejectActionRequest,
  sendOpsChatStream,
  testOcpConnection,
  testOcpConnectionDraft,
  type ActionAuditItem,
  type ActionExecution,
  type ActionPreview,
  type ActionRequest,
  type BatchJob,
  type DocsPreviewSnippet,
  type LibraryCatalogItem,
  type LibraryChunksResponse,
  type LibraryDocumentContent,
  type LibrarySummary,
  type NamespaceListResponse,
  type OcpConnection,
  type OcpConnectionTestResult,
  type OcpMetricsResponse,
  type OcpOverview,
  type OpsChatResponse,
  type OpsRouteKey,
  type OpsWorkspace,
  type RecommendationItem,
  type ResourceDetailResponse,
  type ResourceListResponse,
} from '../lib/opsConsoleApi';

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: OpsChatResponse['sources'];
  artifacts?: OpsChatResponse['artifacts'];
};

type MarkdownBlock =
  | { type: 'markdown'; text: string }
  | { type: 'table'; header: string[]; rows: string[][] };

const ROUTE_SECTIONS: Array<{
  key: OpsRouteKey;
  label: string;
  path: string;
  icon: typeof Activity;
  description: string;
}> = [
  { key: 'overview', label: 'Overview', path: ROUTES.opsOverview, icon: Activity, description: 'cluster overview와 추천' },
  { key: 'resources', label: 'Resources', path: ROUTES.opsResources, icon: Database, description: 'namespace/resource 탐색 및 YAML' },
  { key: 'library', label: 'Docs', path: ROUTES.opsLibrary, icon: BookOpen, description: '문서 카탈로그와 batch indexing' },
  { key: 'chat', label: 'Chat', path: ROUTES.opsChat, icon: Workflow, description: '문서와 live 결과를 함께 보는 Copilot' },
  { key: 'actions', label: 'Actions', path: ROUTES.opsActions, icon: ShieldCheck, description: 'preview/request/approve/execute/audit' },
];

const RESOURCE_OPTIONS = ['pods', 'deployments', 'services', 'routes', 'events'] as const;
const OPS_FIXED_NAMESPACE = 'demo';
const EDITABLE_RESOURCE_TYPES = new Set(['deployments', 'services', 'routes']);
const ACTION_OPTIONS = ['scale_deployment', 'rollout_restart', 'log_bundle', 'yaml_apply'] as const;
const OPS_CHAT_STARTERS = [
  'demo namespace 배포 상태를 먼저 점검해줘',
  '문제 있는 Pod나 Deployment가 있는지 분석해줘',
  '현재 리소스 목록을 종류별로 정리해서 보여줘',
  'Route와 Service 연결을 볼 때 어떤 리소스를 같이 봐야 하는지 정리해줘',
] as const;
const CONNECT_GUIDE_STEPS = [
  {
    title: '1. Connect by MobaXterm',
    body: 'VPN 연결 후 bastion 또는 접속 가능한 호스트로 로그인합니다.',
    code: 'ssh <user>@<bastion-or-node>',
  },
  {
    title: '2. Login to OpenShift',
    body: 'API server URL과 현재 사용자 토큰을 확인합니다.',
    code: 'oc login <api-server>\noc whoami --show-server\noc whoami -t',
  },
  {
    title: '3. Service Account Option',
    body: 'read-only serviceaccount 토큰이 필요하면 demo namespace에서 발급합니다.',
    code: 'oc -n demo create token rag-reader',
  },
  {
    title: '4. Console Defaults',
    body: '이 Ops Console은 저장 프로필 기반으로 연결하고 demo namespace를 기본값으로 사용합니다.',
    code: 'namespace: demo\nSSL verify: false',
  },
] as const;
const OpsOverviewCharts = lazy(() => import('./ops/OpsOverviewCharts'));

function sectionFromPath(pathname: string): OpsRouteKey {
  if (pathname === ROUTES.opsConnections) {
    return 'overview';
  }
  if (pathname === ROUTES.opsWorkspaces) {
    return 'overview';
  }
  if (pathname === ROUTES.opsLibrary) {
    return 'overview';
  }
  return ROUTE_SECTIONS.find((item) => item.path === pathname)?.key ?? 'overview';
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function makeId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

function visibleChatArtifacts(artifacts?: OpsChatResponse['artifacts']): OpsChatResponse['artifacts'] | undefined {
  if (!artifacts?.length) {
    return artifacts;
  }
  const resourceListCount = artifacts.filter((artifact) => artifact.kind === 'resource_list').length;
  if (resourceListCount <= 1) {
    return artifacts;
  }
  return artifacts.filter((artifact) => artifact.kind !== 'resource_list');
}

function loadSavedChatMessages(): ChatMessage[] {
  try {
    const raw = window.localStorage.getItem('opsConsole.chatMessages');
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.slice(-20).map((message) => ({ ...message, artifacts: visibleChatArtifacts(message.artifacts) }))
      : [];
  } catch {
    return [];
  }
}

function isMarkdownTableSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitMarkdownTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = String(markdown || '').split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let markdownBuffer: string[] = [];
  let inFence = false;

  const flushMarkdown = () => {
    const text = markdownBuffer.join('\n').trim();
    if (text) {
      blocks.push({ type: 'markdown', text });
    }
    markdownBuffer = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    if (line.trim().startsWith('```')) {
      inFence = !inFence;
      markdownBuffer.push(line);
      continue;
    }
    if (!inFence && line.includes('|') && isMarkdownTableSeparator(lines[index + 1] ?? '')) {
      flushMarkdown();
      const tableLines = [line];
      index += 2;
      while (index < lines.length && (lines[index] ?? '').includes('|') && (lines[index] ?? '').trim()) {
        tableLines.push(lines[index] ?? '');
        index += 1;
      }
      index -= 1;
      const [headerLine, ...rowLines] = tableLines;
      blocks.push({
        type: 'table',
        header: splitMarkdownTableRow(headerLine ?? ''),
        rows: rowLines.map(splitMarkdownTableRow),
      });
      continue;
    }
    markdownBuffer.push(line);
  }
  flushMarkdown();
  return blocks;
}

function MarkdownMessage({ content }: { content: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(content), [content]);
  return (
    <div className="ops-chat-markdown">
      {blocks.map((block, index) => (
        block.type === 'table' ? (
          <div key={`table-${index}`} className="ops-chat-markdown-table-wrap">
            <table className="ops-chat-markdown-table">
              <thead>
                <tr>
                  {block.header.map((cell, cellIndex) => <th key={`head-${cellIndex}`}>{cell}</th>)}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={`row-${rowIndex}`}>
                    {block.header.map((_, cellIndex) => <td key={`cell-${cellIndex}`}>{row[cellIndex] ?? ''}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <ReactMarkdown key={`markdown-${index}`}>{block.text}</ReactMarkdown>
        )
      ))}
    </div>
  );
}

function AssistantProgress({ stages, compact = false }: { stages: Array<{ label: string; detail: string; status: string }>; compact?: boolean }) {
  const visibleStages = stages.length > 0
    ? stages.slice(-4)
    : [
      { label: 'Connect', detail: 'Preparing OpenShift context', status: 'running' },
      { label: 'Analyze', detail: 'Checking resources, metrics, and events', status: 'pending' },
    ];
  return (
    <div className={`ops-assistant-progress ${compact ? 'compact' : ''}`} aria-live="polite">
      <div className="ops-assistant-progress-head">
        <span className="ops-progress-pulse" />
        <strong>Working on cluster context</strong>
      </div>
      <div className="ops-assistant-progress-steps">
        {visibleStages.map((stage, index) => (
          <div key={`${stage.label}-${index}`} className={`ops-assistant-progress-step ${stage.status}`}>
            <span>{stage.label}</span>
            <small>{stage.detail}</small>
          </div>
        ))}
      </div>
    </div>
  );
}


export default function OpsConsolePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const section = useMemo(() => sectionFromPath(location.pathname), [location.pathname]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [workspaces, setWorkspaces] = useState<OpsWorkspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(() => window.localStorage.getItem('opsConsole.activeWorkspaceId') ?? '');

  const [connections, setConnections] = useState<OcpConnection[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState(() => window.localStorage.getItem('opsConsole.activeConnectionId') ?? '');
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [connectStep, setConnectStep] = useState<1 | 2>(1);
  const [modalProfileId, setModalProfileId] = useState('');
  const [deletingProfileId, setDeletingProfileId] = useState('');
  const [guideStepIndex, setGuideStepIndex] = useState(0);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
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
  const [connectionDraft, setConnectionDraft] = useState({
    cluster_url: '',
    display_name: '',
    token: '',
    username: '',
    password: '',
  });
  const [expandedCredentialField, setExpandedCredentialField] = useState<string | null>(null);
  const [connectionTest, setConnectionTest] = useState<OcpConnectionTestResult | null>(null);

  const [overview, setOverview] = useState<OcpOverview | null>(null);
  const [overviewMetrics, setOverviewMetrics] = useState<OcpMetricsResponse | null>(null);
  const [overviewRefreshing, setOverviewRefreshing] = useState(false);
  const [overviewLastUpdatedAt, setOverviewLastUpdatedAt] = useState('');
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);

  const [, setNamespaces] = useState<NamespaceListResponse | null>(null);
  const [selectedNamespace, setSelectedNamespace] = useState(OPS_FIXED_NAMESPACE);
  const [selectedResourceType, setSelectedResourceType] = useState<typeof RESOURCE_OPTIONS[number]>('deployments');
  const [resourceList, setResourceList] = useState<ResourceListResponse | null>(null);
  const [selectedResourceName, setSelectedResourceName] = useState('');
  const [resourceDetail, setResourceDetail] = useState<ResourceDetailResponse | null>(null);
  const [yamlEditor, setYamlEditor] = useState('');
  const [yamlPreview, setYamlPreview] = useState<ActionPreview | null>(null);
  const [yamlApplyRequest, setYamlApplyRequest] = useState<ActionRequest | null>(null);
  const [yamlApplyExecution, setYamlApplyExecution] = useState<ActionExecution | null>(null);
  const [yamlEditorOpen, setYamlEditorOpen] = useState(false);
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [resourceDetailLoading, setResourceDetailLoading] = useState(false);

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

  const [messages, setMessages] = useState<ChatMessage[]>(() => loadSavedChatMessages());
  const [chatDraft, setChatDraft] = useState('');
  const [chatStages, setChatStages] = useState<Array<{ label: string; detail: string; status: string }>>([]);
  const [chatSending, setChatSending] = useState(false);
  const [activeAssistantId, setActiveAssistantId] = useState('');
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

  const activeConnection = connections.find((item) => item.connection_id === activeConnectionId) ?? null;
  const savedProfiles = useMemo(
    () => connections.filter((item) => item.save_profile).sort((left, right) => right.last_verified_at.localeCompare(left.last_verified_at)),
    [connections],
  );
  const modalProfile = savedProfiles.find((item) => item.connection_id === modalProfileId) ?? savedProfiles[0] ?? null;
  const sectionMeta = ROUTE_SECTIONS.find((item) => item.key === section) ?? ROUTE_SECTIONS[0];
  const resourceEditable = EDITABLE_RESOURCE_TYPES.has(selectedResourceType);

  useEffect(() => {
    window.localStorage.setItem('opsConsole.activeWorkspaceId', activeWorkspaceId);
  }, [activeWorkspaceId]);

  useEffect(() => {
    window.localStorage.setItem('opsConsole.activeConnectionId', activeConnectionId);
  }, [activeConnectionId]);

  useEffect(() => {
    window.localStorage.setItem('opsConsole.selectedNamespace', selectedNamespace);
  }, [selectedNamespace]);

  useEffect(() => {
    window.localStorage.setItem('opsConsole.chatMessages', JSON.stringify(messages.slice(-20)));
  }, [messages]);

  useEffect(() => {
    if (!notice) {
      return;
    }
    const timeoutId = window.setTimeout(() => setNotice(''), 3200);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    if (location.pathname === ROUTES.opsWorkspaces || location.pathname === ROUTES.opsConnections) {
      navigate(ROUTES.opsOverview, { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    if (!activeConnectionId) {
      setShowConnectModal(true);
      setConnectStep(savedProfiles.length > 0 ? 1 : 2);
    }
  }, [activeConnectionId, savedProfiles.length]);

  useEffect(() => {
    if (!modalProfileId && savedProfiles.length > 0) {
      setModalProfileId(savedProfiles[0].connection_id);
    }
    if (modalProfileId && !savedProfiles.some((item) => item.connection_id === modalProfileId)) {
      setModalProfileId(savedProfiles[0]?.connection_id ?? '');
    }
  }, [modalProfileId, savedProfiles]);

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
    void refreshRecommendationsForWorkspace(activeWorkspaceId);
    void refreshLibrary(activeWorkspaceId);
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
    if (!activeConnectionId || !selectedNamespace) {
      return;
    }
    void refreshOverviewMetrics(activeConnectionId, selectedNamespace);
  }, [activeConnectionId, selectedNamespace]);

  useEffect(() => {
    if (section !== 'overview' || !activeConnectionId || !selectedNamespace) {
      return;
    }
    let cancelled = false;
    const runRefreshCycle = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return;
      }
      setOverviewRefreshing(true);
      try {
        await Promise.all([
          refreshOverview(activeConnectionId),
          refreshOverviewMetrics(activeConnectionId, selectedNamespace),
          activeWorkspaceId ? refreshRecommendationsForWorkspace(activeWorkspaceId) : Promise.resolve(),
        ]);
        if (!cancelled) {
          setOverviewLastUpdatedAt(
            new Date().toLocaleTimeString('ko-KR', {
              hour12: false,
            }),
          );
        }
      } finally {
        if (!cancelled) {
          setOverviewRefreshing(false);
        }
      }
    };
    void runRefreshCycle();
    const intervalId = window.setInterval(() => {
      void runRefreshCycle();
    }, 10000);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void runRefreshCycle();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [section, activeConnectionId, selectedNamespace, activeWorkspaceId]);

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
    setYamlPreview(null);
    setYamlApplyRequest(null);
    setYamlApplyExecution(null);
  }, [resourceDetail]);

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
      if (activeConnectionId && items.length > 0 && !items.some((item) => item.connection_id === activeConnectionId)) {
        setActiveConnectionId(items[0].connection_id);
      }
      if (items.length === 0) {
        setActiveConnectionId('');
      }
    });
  }

  async function refreshConnectionStatus(connectionId: string) {
    return run(async () => loadOcpStatus(connectionId), (value) => {
      setSelectedNamespace(OPS_FIXED_NAMESPACE);
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
    return run(async () => loadOcpLeaseStatus(), () => undefined);
  }

  async function refreshRecommendationsForWorkspace(workspaceId: string) {
    return run(async () => listRecommendations(workspaceId), (value) => setRecommendations(value));
  }

  async function refreshOverview(connectionId: string) {
    return run(async () => loadOcpOverview(connectionId), (value) => setOverview(value));
  }

  async function refreshOverviewMetrics(connectionId: string, namespace: string) {
    return run(async () => loadOcpMetrics(connectionId, namespace), (value) => setOverviewMetrics(value));
  }

  async function refreshNamespaces(connectionId: string) {
    return run(async () => loadNamespaces(connectionId), (value) => {
      setNamespaces({ ...value, items: [OPS_FIXED_NAMESPACE] });
      setSelectedNamespace(OPS_FIXED_NAMESPACE);
    });
  }

  async function refreshResources(connectionId: string, resourceType: string, namespace: string) {
    setResourcesLoading(true);
    setResourceDetailLoading(true);
    setResourceList(null);
    setResourceDetail(null);
    setYamlEditor('');
    setYamlPreview(null);
    setSelectedResourceName('');
    try {
      const value = await loadResources(connectionId, resourceType, namespace);
      setResourceList(value);
      const preferredName = value.items.some((item) => item.name === selectedResourceName)
        ? selectedResourceName
        : value.items[0]?.name ?? '';
      setSelectedResourceName(preferredName);
      if (preferredName) {
        await openResourceDetail(connectionId, resourceType, namespace, preferredName);
      } else {
        setResourceDetail(null);
        setYamlEditor('');
        setResourceDetailLoading(false);
      }
      return value;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '리소스를 불러오는 중 오류가 발생했습니다.');
      return null;
    } finally {
      setResourcesLoading(false);
    }
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

  function resetConnectionDraft() {
    setConnectionDraft({
      cluster_url: '',
      display_name: '',
      token: '',
      username: '',
      password: '',
    });
    setExpandedCredentialField(null);
  }

  function syncConnectionForm(connection: OcpConnection) {
    setConnectionForm((current) => ({
      ...current,
      cluster_url: connection.cluster_url,
      auth_mode: connection.auth_mode,
      verify_ssl: connection.verify_ssl,
      default_namespace: connection.default_namespace,
      display_name: connection.display_name,
      save_profile: connection.save_profile,
      token: current.token,
      username: connection.username_hint || current.username,
      password: '',
    }));
    resetConnectionDraft();
  }

  async function activateSavedProfile(connection: OcpConnection) {
    setActiveWorkspaceId(connection.workspace_id);
    setActiveConnectionId(connection.connection_id);
    setModalProfileId(connection.connection_id);
    setSelectedNamespace(OPS_FIXED_NAMESPACE);
    syncConnectionForm(connection);
    setProfileMenuOpen(false);
    setShowConnectModal(false);
    navigate(ROUTES.opsOverview);
    await refreshConnectionStatus(connection.connection_id);
  }

  function openConnectModal(step: 1 | 2 = 1) {
    setConnectStep(step);
    if (step === 1) {
      setGuideStepIndex(0);
    }
    resetConnectionDraft();
    setModalProfileId(activeConnectionId || savedProfiles[0]?.connection_id || '');
    setProfileMenuOpen(false);
    setShowConnectModal(true);
  }

  async function openResourceDetail(connectionId: string, resourceType: string, namespace: string, name: string) {
    setSelectedResourceName(name);
    setResourceDetailLoading(true);
    setResourceDetail(null);
    setYamlEditor('');
    setYamlPreview(null);
    setYamlApplyRequest(null);
    setYamlApplyExecution(null);
    try {
      const value = await loadResourceDetail(connectionId, resourceType, namespace, name);
      setResourceDetail(value);
      return value;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '리소스 상세를 불러오는 중 오류가 발생했습니다.');
      return null;
    } finally {
      setResourceDetailLoading(false);
    }
  }

  function openYamlEditor() {
    if (!resourceDetail) {
      setError('리소스를 먼저 선택하세요.');
      return;
    }
    if (!EDITABLE_RESOURCE_TYPES.has(selectedResourceType)) {
      setError('이 리소스는 YAML 편집을 지원하지 않습니다.');
      return;
    }
    setYamlEditor(resourceDetail.manifest_yaml);
    setYamlPreview(null);
    setYamlApplyRequest(null);
    setYamlApplyExecution(null);
    setYamlEditorOpen(true);
  }

  async function openChatArtifactResource(artifact: {
    connection_id?: string;
    resource_type?: string;
    namespace?: string;
    name?: string;
    open_editor?: boolean;
  }) {
    const connectionId = String(artifact.connection_id || activeConnectionId || '').trim();
    const resourceType = String(artifact.resource_type || '').trim();
    const namespace = OPS_FIXED_NAMESPACE;
    const name = String(artifact.name || '').trim();
    if (!connectionId || !resourceType || !namespace) {
      setError('Artifact에 필요한 리소스 정보가 부족합니다.');
      return;
    }
    setActiveConnectionId(connectionId);
    setSelectedNamespace(OPS_FIXED_NAMESPACE);
    if (RESOURCE_OPTIONS.includes(resourceType as typeof RESOURCE_OPTIONS[number])) {
      setSelectedResourceType(resourceType as typeof RESOURCE_OPTIONS[number]);
    }
    if (!artifact.open_editor) {
      navigate(ROUTES.opsResources);
    }
    if (name) {
      const detail = await openResourceDetail(connectionId, resourceType, namespace, name);
      if (detail && artifact.open_editor && EDITABLE_RESOURCE_TYPES.has(resourceType)) {
        setYamlEditor(detail.manifest_yaml);
        setYamlEditorOpen(true);
      }
    } else {
      await refreshResources(connectionId, resourceType, namespace);
    }
  }

  function buildConnectionPayload() {
    return {
      ...connectionForm,
      workspace_id: activeWorkspaceId || 'ws_default',
      cluster_url: connectionDraft.cluster_url.trim() || connectionForm.cluster_url,
      display_name: connectionDraft.display_name.trim() || connectionForm.display_name,
      token: connectionDraft.token.trim() || connectionForm.token,
      username: connectionDraft.username.trim() || connectionForm.username,
      password: connectionDraft.password || connectionForm.password,
    };
  }

  function hasConnectionDraftInput() {
    return Object.values(connectionDraft).some((value) => String(value || '').trim());
  }

  async function handleCreateConnection() {
    if (!activeWorkspaceId) {
      setError('기본 workspace를 불러오지 못했습니다. 잠시 후 다시 시도하세요.');
      return;
    }
    const payload = buildConnectionPayload();
    const created = await run(
      async () => connectOcp(payload),
      (value) => {
        setNotice(value.message);
        setConnections((current) => [value.connection, ...current.filter((item) => item.connection_id !== value.connection.connection_id)]);
        setActiveConnectionId(value.connection.connection_id);
        setModalProfileId(value.connection.connection_id);
        setSelectedNamespace(OPS_FIXED_NAMESPACE);
        setShowConnectModal(false);
        setConnectStep(1);
        setProfileMenuOpen(false);
        resetConnectionDraft();
      },
    );
    if (created) {
      await refreshConnectionStatus(created.connection.connection_id);
      await refreshRecommendationsForWorkspace(activeWorkspaceId);
      navigate(ROUTES.opsOverview);
    }
  }

  async function handleTestConnection() {
    const targetConnectionId = activeConnectionId || modalProfile?.connection_id || '';
    if (hasConnectionDraftInput() || !targetConnectionId) {
      setConnectionTest(null);
      await run(async () => testOcpConnectionDraft(buildConnectionPayload()), (value) => {
        setConnectionTest(value);
        setNotice(value.message);
      });
      return;
    }
    if (!targetConnectionId) {
      setError('저장된 프로필을 선택하거나 먼저 연결을 생성하세요.');
      return;
    }
    setConnectionTest(null);
    await run(async () => testOcpConnection(targetConnectionId), (value) => {
      setConnectionTest(value);
      setNotice(value.message);
    });
  }

  async function handleDeleteSavedProfile(profile: OcpConnection) {
    setDeletingProfileId(profile.connection_id);
    await run(
      async () => disconnectOcp(profile.connection_id),
      () => {
        setConnections((current) => current.filter((item) => item.connection_id !== profile.connection_id));
        if (activeConnectionId === profile.connection_id) {
          setActiveConnectionId('');
          setOverview(null);
          setOverviewMetrics(null);
          setNamespaces(null);
          setResourceList(null);
          setResourceDetail(null);
          setYamlEditor('');
          setYamlPreview(null);
          setSelectedResourceName('');
        }
        if (modalProfileId === profile.connection_id) {
          const nextProfile = savedProfiles.find((item) => item.connection_id !== profile.connection_id);
          setModalProfileId(nextProfile?.connection_id ?? '');
          if (nextProfile) {
            syncConnectionForm(nextProfile);
          } else {
            setConnectStep(2);
            resetConnectionDraft();
          }
        }
        setConnectionTest(null);
        setNotice(`Profile "${profile.display_name}" deleted.`);
      },
    );
    setDeletingProfileId('');
  }

  async function handleRefreshLease() {
    const targetConnectionId = activeConnectionId || modalProfile?.connection_id || '';
    if (!targetConnectionId) {
      setError('활성 프로필이 있을 때만 lease를 갱신할 수 있습니다.');
      return;
    }
    await run(async () => refreshOcpLease(targetConnectionId), (value) => {
      setConnectionTest(value);
      setNotice('Lease metadata refreshed.');
    });
    await refreshLeaseStatus();
  }

  async function handleDisconnect() {
    const previousConnectionId = activeConnectionId || savedProfiles[0]?.connection_id || '';
    setNotice('Active profile cleared. Reconnect to continue.');
    setActiveConnectionId('');
    setModalProfileId(previousConnectionId);
    setConnectionTest(null);
    setOverview(null);
    setOverviewMetrics(null);
    setResourceDetail(null);
    setYamlEditor('');
    setYamlPreview(null);
    setYamlApplyRequest(null);
    setYamlApplyExecution(null);
    setYamlEditorOpen(false);
    setProfileMenuOpen(false);
    setShowConnectModal(true);
    setConnectStep(savedProfiles.length > 0 ? 1 : 2);
  }

  async function handlePreviewYaml() {
    if (!activeConnectionId || !selectedResourceName) {
      setError('리소스를 먼저 선택하세요.');
      return;
    }
    setYamlApplyRequest(null);
    setYamlApplyExecution(null);
    await run(
      async () => previewAction({
        connection_id: activeConnectionId,
        actor_id: actionForm.actor_id,
        actor_roles: actionForm.actor_roles.split(',').map((item) => item.trim()).filter(Boolean),
        action_type: 'yaml_apply',
        resource_type: selectedResourceType,
        namespace: selectedNamespace,
        resource_name: selectedResourceName,
        reason: 'edit resource yaml',
        manifest_yaml: yamlEditor,
      }),
      (value) => setYamlPreview(value),
    );
  }

  async function handleCreateYamlApplyRequest() {
    if (!activeConnectionId || !selectedResourceName) {
      setError('리소스를 먼저 선택하세요.');
      return null;
    }
    const created = await run(
      async () => createActionRequest({
        connection_id: activeConnectionId,
        actor_id: actionForm.actor_id,
        actor_roles: actionForm.actor_roles.split(',').map((item) => item.trim()).filter(Boolean),
        action_type: 'yaml_apply',
        resource_type: selectedResourceType,
        namespace: selectedNamespace,
        resource_name: selectedResourceName,
        reason: 'apply YAML editor change',
        manifest_yaml: yamlEditor,
      }),
      (value) => {
        setYamlApplyRequest(value);
        setActionRequests((current) => [value, ...current]);
        setNotice('YAML apply request created.');
      },
    );
    await refreshActions();
    return created;
  }

  async function handleApplyYamlNow() {
    const request = yamlApplyRequest ?? await handleCreateYamlApplyRequest();
    if (!request) {
      return;
    }
    await run(async () => approveActionRequest(request.request_id, { actor_id: actionForm.actor_id, actor_roles: ['operator'], decision_note: 'approved from YAML editor' }));
    const execution = await run(
      async () => executeActionRequest(request.request_id, { actor_id: actionForm.actor_id, actor_roles: ['operator'], execution_note: 'applied from YAML editor', force: false }),
      (value) => {
        setYamlApplyExecution(value);
        setNotice(value.simulated ? 'YAML change applied to simulated inventory.' : 'YAML change applied to cluster.');
      },
    );
    await refreshActions();
    if (activeConnectionId) {
      await refreshResources(activeConnectionId, selectedResourceType, selectedNamespace);
      if (selectedResourceName) {
        await openResourceDetail(activeConnectionId, selectedResourceType, selectedNamespace, selectedResourceName);
      }
    }
    if (execution) {
      setYamlEditorOpen(false);
    }
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
    setActiveAssistantId(assistantId);
    setChatDraft('');
    setChatStages([]);
    setChatSending(true);
    setError('');
    let streamedAnswer = '';
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
            streamedAnswer += event.delta;
            setMessages((current) => current.map((item) => (item.id === assistantId ? { ...item, content: streamedAnswer } : item)));
            return;
          }
          if (event.type === 'result') {
            setMessages((current) => current.map((item) => (
              item.id === assistantId
                ? {
                  ...item,
                  content: event.response.answer,
                  sources: event.response.sources,
                  artifacts: visibleChatArtifacts(event.response.artifacts),
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
      setActiveAssistantId('');
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
        resource_type: selectedResourceType,
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
        resource_type: selectedResourceType,
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

  return (
    <div className="ops-console-page">
      <header className="ops-console-hero ops-console-hero-compact">
        <div className="ops-console-brand">
          <h1>Operations Console</h1>
          <p>{sectionMeta.description}</p>
        </div>
        <div className="ops-console-hero-actions">
          <Link to={ROUTES.pbsStudio} className="ops-nav-pill ops-nav-pill-utility">Studio</Link>
          {activeConnection ? (
            <div className="ops-profile-shell">
              <button type="button" className="ops-nav-pill ops-nav-pill-profile" onClick={() => setProfileMenuOpen((current) => !current)}>
                <Cable size={16} />
                <span>{activeConnection.display_name}</span>
              </button>
              {profileMenuOpen ? (
                <div className="ops-profile-menu">
                  <div className="ops-profile-menu-head">
                    <strong>{activeConnection.display_name}</strong>
                    <span>{activeConnection.default_namespace} · {activeConnection.status}</span>
                  </div>
                  {savedProfiles.length > 1 ? (
                    <div className="ops-profile-switch-list">
                      {savedProfiles
                        .filter((item) => item.connection_id !== activeConnection.connection_id)
                        .slice(0, 4)
                        .map((item) => (
                          <button key={item.connection_id} type="button" className="ops-profile-switch-item" onClick={() => { void activateSavedProfile(item); }}>
                            <strong>{item.display_name}</strong>
                            <span>{item.default_namespace}</span>
                          </button>
                        ))}
                    </div>
                  ) : null}
                  <div className="ops-inline-actions">
                    <button type="button" onClick={() => openConnectModal(1)}>Manage profiles</button>
                    <button type="button" onClick={() => { void handleDisconnect(); }}>Log out</button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <button type="button" className="ops-nav-pill ops-nav-pill-profile" onClick={() => openConnectModal(savedProfiles.length > 0 ? 1 : 2)}>
              <Cable size={16} />
              <span>Connect Cluster</span>
            </button>
          )}
        </div>
      </header>

      <nav className="ops-console-nav ops-console-nav-compact">
        {ROUTE_SECTIONS.filter((item) => item.key !== 'library').map((item) => {
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

      {showConnectModal ? (
        <div className="ops-modal-backdrop" onClick={() => { if (activeConnectionId) { setShowConnectModal(false); } }}>
          <section className="ops-connect-modal" role="dialog" aria-modal="true" aria-label="Connect OpenShift cluster" onClick={(event) => event.stopPropagation()}>
            <aside className="ops-connect-sidebar">
              <div className="ops-connect-sidebar-head">
                <strong>Saved Profiles</strong>
                <button type="button" className="ops-secondary-btn" onClick={() => {
                  setModalProfileId('');
                  setConnectStep(2);
                  setConnectionTest(null);
                  setConnectionForm((current) => ({
                    ...current,
                    cluster_url: 'https://api.cluster.example.com:6443',
                    auth_mode: 'token',
                    verify_ssl: false,
                    default_namespace: 'demo',
                    display_name: 'dev-cluster',
                    save_profile: true,
                    token: '',
                    username: '',
                    password: '',
                  }));
                  resetConnectionDraft();
                }}>
                  New
                </button>
              </div>
              <div className="ops-connect-profile-list">
                {savedProfiles.length > 0 ? savedProfiles.map((profile) => (
                  <div
                    key={profile.connection_id}
                    className={`ops-connect-profile-card ${modalProfile?.connection_id === profile.connection_id ? 'selected' : ''}`}
                  >
                    <button
                      type="button"
                      className="ops-connect-profile-select"
                      onClick={() => {
                        setModalProfileId(profile.connection_id);
                        syncConnectionForm(profile);
                        setActiveWorkspaceId(profile.workspace_id);
                        setConnectionTest(null);
                        setConnectStep(1);
                      }}
                    >
                      <strong>{profile.display_name}</strong>
                      <span>{profile.default_namespace}</span>
                      <span>{profile.status}</span>
                    </button>
                    <button
                      type="button"
                      className="ops-connect-profile-delete"
                      aria-label={`Delete ${profile.display_name}`}
                      title="Delete profile"
                      disabled={deletingProfileId === profile.connection_id}
                      onClick={() => { void handleDeleteSavedProfile(profile); }}
                    >
                      <X size={14} />
                    </button>
                  </div>
                )) : (
                  <div className="ops-connect-empty">
                    <strong>No saved profile</strong>
                    <span>Create your first cluster profile.</span>
                  </div>
                )}
              </div>
            </aside>
            <div className="ops-connect-main">
              <div className="ops-connect-main-head">
                <div>
                  <h2>Connect Cluster</h2>
                  <p>저장 프로필을 선택하거나 새 연결을 만들어 바로 Overview로 진입합니다.</p>
                </div>
                {activeConnectionId ? (
                  <button type="button" className="ops-secondary-btn" onClick={() => setShowConnectModal(false)}>
                    Close
                  </button>
                ) : null}
              </div>
              <div className="ops-connect-stepbar">
                <button type="button" className={`ops-step-chip ${connectStep === 1 ? 'active' : ''}`} onClick={() => setConnectStep(1)}>1. Guide</button>
                <button type="button" className={`ops-step-chip ${connectStep === 2 ? 'active' : ''}`} onClick={() => setConnectStep(2)}>2. Credentials</button>
              </div>
              {connectStep === 1 ? (
                <div className="ops-connect-step-layout">
                  <div className="ops-guide-carousel">
                    <div className="ops-guide-card ops-guide-card-focus">
                      <div className="ops-guide-card-meta">
                        <span>{guideStepIndex + 1} / {CONNECT_GUIDE_STEPS.length}</span>
                        <strong>{CONNECT_GUIDE_STEPS[guideStepIndex].title}</strong>
                      </div>
                      <p>{CONNECT_GUIDE_STEPS[guideStepIndex].body}</p>
                      <pre>{CONNECT_GUIDE_STEPS[guideStepIndex].code}</pre>
                    </div>
                    <div className="ops-connect-guide-nav">
                      <button
                        type="button"
                        className="ops-secondary-btn ops-guide-nav-prev-btn"
                        disabled={guideStepIndex === 0}
                        onClick={() => setGuideStepIndex((current) => Math.max(0, current - 1))}
                      >
                        ← Previous
                      </button>
                      <div className="ops-connect-guide-dots" aria-hidden="true">
                        {CONNECT_GUIDE_STEPS.map((_, index) => (
                          <span key={`guide-dot-${index}`} className={`ops-connect-guide-dot ${index === guideStepIndex ? 'active' : ''}`} />
                        ))}
                      </div>
                      {guideStepIndex < CONNECT_GUIDE_STEPS.length - 1 ? (
                        <button
                          type="button"
                          className="ops-primary-btn ops-guide-nav-next-btn"
                          onClick={() => setGuideStepIndex((current) => Math.min(CONNECT_GUIDE_STEPS.length - 1, current + 1))}
                        >
                          Next →
                        </button>
                      ) : (
                        <button type="button" className="ops-primary-btn ops-guide-nav-finish-btn" onClick={() => setConnectStep(2)}>
                          Go to credentials →
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="ops-guide-grid ops-guide-grid-legacy">
                    <div className="ops-guide-card">
                      <strong>1. Connect by MobaXterm</strong>
                      <p>VPN 연결 후 bastion 또는 접속 가능한 호스트로 로그인합니다.</p>
                      <pre>{`ssh <user>@<bastion-or-node>`}</pre>
                    </div>
                    <div className="ops-guide-card">
                      <strong>2. Login to OpenShift</strong>
                      <p>API server URL과 현재 사용자 토큰을 확인합니다.</p>
                      <pre>{`oc login <api-server>\noc whoami --show-server\noc whoami -t`}</pre>
                    </div>
                    <div className="ops-guide-card">
                      <strong>3. Service Account Option</strong>
                      <p>read-only serviceaccount 토큰이 필요하면 demo namespace에서 발급합니다.</p>
                      <pre>{`oc -n demo create token rag-reader`}</pre>
                    </div>
                    <div className="ops-guide-card">
                      <strong>4. Console Defaults</strong>
                      <p>이 Ops Console은 저장 프로필 기반으로 연결하고 demo namespace를 기본값으로 사용합니다.</p>
                      <pre>{`namespace: demo\nSSL verify: false`}</pre>
                    </div>
                  </div>
                  <div className="ops-connect-summary">
                    <h3>{modalProfile ? modalProfile.display_name : 'New cluster profile'}</h3>
                    <p>{modalProfile ? `${modalProfile.cluster_url} · ${modalProfile.default_namespace}` : '새 OpenShift 프로필을 만들고 저장할 수 있습니다.'}</p>
                    <div className="ops-inline-actions">
                      {modalProfile ? (
                        <button type="button" className="ops-primary-btn" onClick={() => { void activateSavedProfile(modalProfile); }}>
                          Use this profile
                        </button>
                      ) : null}
                      <button type="button" className="ops-secondary-btn" onClick={() => setConnectStep(2)}>
                        {modalProfile ? 'Edit credentials' : 'Enter credentials'}
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="ops-connect-step-layout">
                  <div className="ops-panel-subsection">
                    <h3>Connection Input</h3>
                    <div className="ops-form-grid three">
                      <div className={`ops-field ops-credential-field ${expandedCredentialField === 'cluster_url' ? 'expanded' : ''}`}>
                        <label>Cluster URL</label>
                        <input
                          className="ops-credential-input"
                          value={connectionDraft.cluster_url}
                          placeholder={connectionForm.cluster_url}
                          onFocus={() => setExpandedCredentialField('cluster_url')}
                          onBlur={() => setExpandedCredentialField((current) => (current === 'cluster_url' ? null : current))}
                          onChange={(event) => setConnectionDraft((current) => ({ ...current, cluster_url: event.target.value }))}
                        />
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
                        <input
                          className="ops-credential-input"
                          value={connectionDraft.display_name}
                          placeholder={connectionForm.display_name}
                          onChange={(event) => setConnectionDraft((current) => ({ ...current, display_name: event.target.value }))}
                        />
                      </div>
                      {connectionForm.auth_mode === 'token' ? (
                        <div className="ops-field ops-field-span-two">
                          <label>Token</label>
                          <input
                            className="ops-credential-input"
                            value={connectionDraft.token}
                            placeholder={connectionForm.token || 'Paste access token'}
                            onChange={(event) => setConnectionDraft((current) => ({ ...current, token: event.target.value }))}
                          />
                        </div>
                      ) : (
                        <>
                          <div className="ops-field">
                            <label>Username</label>
                            <input
                              className="ops-credential-input"
                              value={connectionDraft.username}
                              placeholder={connectionForm.username || 'Enter username'}
                              onChange={(event) => setConnectionDraft((current) => ({ ...current, username: event.target.value }))}
                            />
                          </div>
                          <div className="ops-field">
                            <label>Password</label>
                            <input
                              type="password"
                              className="ops-credential-input"
                              value={connectionDraft.password}
                              placeholder={connectionForm.password || 'Enter password'}
                              onChange={(event) => setConnectionDraft((current) => ({ ...current, password: event.target.value }))}
                            />
                          </div>
                        </>
                      )}
                    </div>
                    <div className="ops-actions-row">
                      <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateConnection(); }}>Connect & Save</button>
                      <button type="button" className="ops-secondary-btn" onClick={() => { void handleTestConnection(); }}>Test current profile</button>
                      <button type="button" className="ops-secondary-btn" onClick={() => { void handleRefreshLease(); }}>Refresh lease</button>
                    </div>
                    {connectionTest ? (
                      <div className="ops-guide-card ops-connection-test-card">
                        <strong>{connectionTest.success ? 'Connection verified' : 'Connection issue'}</strong>
                        <p>{connectionTest.message || connectionTest.error}</p>
                        <span>{connectionTest.resolved_user ? `user=${connectionTest.resolved_user}` : ''}</span>
                        <span>{connectionTest.resolved_namespace ? `namespace=${connectionTest.resolved_namespace}` : ''}</span>
                      </div>
                    ) : null}
                    <div className="ops-connect-guide-nav ops-connect-guide-nav-compact">
                      <button type="button" className="ops-secondary-btn" onClick={() => setConnectStep(1)}>
                        Back to guide
                      </button>
                      <button type="button" className="ops-primary-btn" onClick={() => { void handleCreateConnection(); }}>
                        {'Connect ->'}
                      </button>
                    </div>
                  </div>
                  <div className="ops-panel-subsection">
                    <h3>Connect Rules</h3>
                    <div className="ops-connect-rules">
                      <div className="ops-connect-rule">
                        <strong>Auto reconnect</strong>
                        <span>저장된 활성 프로필은 Studio에서 돌아와도 자동 연결됩니다.</span>
                      </div>
                      <div className="ops-connect-rule">
                        <strong>Saved profile</strong>
                        <span>연결 변경은 우측 상단 프로필 pill에서 바로 관리할 수 있습니다.</span>
                      </div>
                      <div className="ops-connect-rule">
                        <strong>Cluster defaults</strong>
                        <span>기본 namespace는 demo, SSL verify는 false로 고정됩니다.</span>
                      </div>
                    </div>
                    {connectionTest ? (
                      <div className="ops-guide-card">
                        <strong>{connectionTest.success ? 'Connection verified' : 'Connection issue'}</strong>
                        <p>{connectionTest.message || connectionTest.error}</p>
                      </div>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {yamlEditorOpen && resourceDetail ? (
        <div className="ops-modal-backdrop" onClick={() => setYamlEditorOpen(false)}>
          <section className="ops-yaml-modal" role="dialog" aria-modal="true" aria-label="YAML editor" onClick={(event) => event.stopPropagation()}>
            <div className="ops-yaml-modal-head">
              <div>
                <h2>YAML Editor</h2>
                <p>{resourceDetail.kind} · {resourceDetail.namespace} · {resourceDetail.name}</p>
              </div>
              <button type="button" className="ops-secondary-btn" onClick={() => setYamlEditorOpen(false)}>
                Close
              </button>
            </div>
            <textarea className="ops-yaml-editor" value={yamlEditor} onChange={(event) => setYamlEditor(event.target.value)} />
            <div className="ops-actions-row">
              <button type="button" className="ops-primary-btn" onClick={() => { void handlePreviewYaml(); }}>
                Preview
              </button>
              <button type="button" className="ops-secondary-btn" onClick={() => { void handleCreateYamlApplyRequest(); }}>
                Create request
              </button>
              <button type="button" className="ops-secondary-btn" onClick={() => { void handleApplyYamlNow(); }}>
                Apply now
              </button>
            </div>
            {yamlPreview ? (
              <div className="ops-yaml-preview">
                <strong>{yamlPreview.summary}</strong>
                <pre>{yamlPreview.diff_unified || yamlPreview.dry_run_messages.join('\n')}</pre>
              </div>
            ) : null}
            {yamlApplyRequest ? (
              <div className="ops-yaml-preview">
                <strong>Request {yamlApplyRequest.request_id}</strong>
                <span>{yamlApplyRequest.status}</span>
              </div>
            ) : null}
            {yamlApplyExecution ? (
              <div className="ops-yaml-preview">
                <strong>{yamlApplyExecution.simulated ? 'Simulated apply complete' : 'Cluster apply complete'}</strong>
                <pre>{yamlApplyExecution.output_lines.join('\n')}</pre>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      <main className="ops-main ops-main-full">

          {section === 'overview' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Cluster Overview</h2>
                <div className="ops-inline-actions">
                  <span className="ops-live-status">
                    {overviewRefreshing ? 'Refreshing' : overviewLastUpdatedAt ? `Updated ${overviewLastUpdatedAt}` : 'Waiting'}
                  </span>
                </div>
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
              {overviewMetrics ? (
                <Suspense fallback={<div className="ops-chart-loading">Loading charts</div>}>
                  <OpsOverviewCharts
                    overview={overview}
                    overviewMetrics={overviewMetrics}
                    activeConnectionId={activeConnectionId}
                    selectedNamespace={selectedNamespace}
                    onOpenResource={openChatArtifactResource}
                  />
                </Suspense>
              ) : null}
            </section>
          )}

          {section === 'resources' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Resource Explorer</h2>
              </div>
              <div className="ops-actions-row">
                <select value={OPS_FIXED_NAMESPACE} disabled aria-label="Namespace">
                  <option value={OPS_FIXED_NAMESPACE}>{OPS_FIXED_NAMESPACE}</option>
                </select>
                <div className="ops-chip-group">
                  {RESOURCE_OPTIONS.map((resourceType) => (
                    <button key={resourceType} type="button" className={`ops-chip ${selectedResourceType === resourceType ? 'active' : ''}`} onClick={() => setSelectedResourceType(resourceType)}>
                      {resourceType}
                    </button>
                  ))}
                </div>
              </div>
              {resourcesLoading ? (
                <div className="ops-resource-loading-shell">
                  <div className="ops-loading-state" aria-live="polite">
                    <span className="ops-loading-spinner" aria-hidden="true" />
                  </div>
                </div>
              ) : (
                <div className="ops-split-grid ops-resource-grid">
                  <div className="ops-list">
                    {(resourceList?.items ?? []).map((item) => (
                      <button key={item.name} type="button" className={`ops-list-row ${selectedResourceName === item.name ? 'selected' : ''}`} onClick={() => { if (activeConnectionId) { void openResourceDetail(activeConnectionId, selectedResourceType, selectedNamespace, item.name); } }}>
                        <strong>{item.name}</strong>
                        <span>{item.kind}</span>
                      </button>
                    ))}
                  </div>
                  <div className="ops-editor-column">
                    {resourceDetailLoading ? (
                      <div className="ops-loading-state ops-loading-state-inline" aria-live="polite">
                        <span className="ops-loading-spinner" aria-hidden="true" />
                      </div>
                    ) : resourceDetail ? (
                      <>
                        <div className="ops-yaml-viewer-head">
                          <div>
                            <strong>{resourceDetail.name}</strong>
                            <span>{resourceDetail.kind} · {resourceDetail.namespace}</span>
                          </div>
                          <div className="ops-actions-row">
                            <button type="button" className="ops-primary-btn" disabled={!resourceEditable} onClick={openYamlEditor}>
                              {resourceEditable ? 'Edit YAML' : 'Read-only'}
                            </button>
                            <button
                              type="button"
                              className="ops-secondary-btn"
                              onClick={() => {
                                const copyRequest = navigator.clipboard?.writeText?.(resourceDetail.manifest_yaml);
                                copyRequest?.catch(() => undefined);
                              }}
                            >
                              Copy YAML
                            </button>
                          </div>
                        </div>
                        <pre className="ops-yaml-viewer">{resourceDetail.manifest_yaml}</pre>
                      </>
                    ) : (
                      <div className="ops-empty-state">리소스를 선택하면 YAML을 읽기 전용으로 확인할 수 있습니다.</div>
                    )}
                  </div>
                </div>
              )}
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
              {(libraryChunks || libraryContent || batchJobs.length > 0) ? (
                <div className="ops-action-grid">
                  <div className="ops-panel-subsection">
                    <h3>Chunk Preview</h3>
                    {libraryChunks ? libraryChunks.chunks.slice(0, 8).map((chunk) => (
                      <div key={chunk.chunk_id} className="ops-table-row">
                        <div>
                          <strong>{chunk.section_title}</strong>
                          <span>{chunk.preview_text}</span>
                        </div>
                      </div>
                    )) : <p className="ops-muted">Select a document to inspect chunks.</p>}
                  </div>
                  <div className="ops-panel-subsection">
                    <h3>Document Content</h3>
                    {libraryContent ? <p className="ops-muted">{libraryContent.content.slice(0, 800)}...</p> : <p className="ops-muted">Open a document to read content.</p>}
                  </div>
                  <div className="ops-panel-subsection">
                    <h3>Batch Jobs</h3>
                    {batchJobs.length > 0 ? batchJobs.map((job) => (
                      <div key={job.job_id} className="ops-table-row">
                        <div>
                          <strong>{job.job_id}</strong>
                          <span>{job.status}</span>
                        </div>
                      </div>
                    )) : <p className="ops-muted">No batch jobs yet.</p>}
                  </div>
                </div>
              ) : null}
            </section>
          )}

          {section === 'chat' && (
            <section className="ops-panel">
              <div className="ops-panel-header">
                <h2>Copilot Chat</h2>
              </div>
              <div className="ops-chat-shell">
                <div className="ops-chat-transcript">
                  {messages.length === 0 && (
                    <div className="ops-chat-welcome">
                      <div className="ops-chat-welcome-icon">
                        <Sparkles size={30} />
                      </div>
                      <h3>Ask the OCP Console</h3>
                      <p>
                        PBS 채팅처럼 운영 흐름 중심으로 질문을 시작할 수 있게 구성했습니다.
                        문서 기반 질문과 현재 연결된 클러스터 확인을 한 화면에서 이어갈 수 있습니다.
                      </p>
                      <div className="ops-chat-starter-grid">
                        {OPS_CHAT_STARTERS.map((starter, index) => (
                          <button
                            key={`ops-starter-${index}`}
                            type="button"
                            className="ops-chat-starter-card"
                            onClick={() => setChatDraft(starter)}
                          >
                            <span className="ops-chat-starter-index">Step {index + 1}</span>
                            <strong>{starter}</strong>
                            <span className="ops-chat-starter-arrow">
                              <ArrowRight size={14} />
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {messages.map((message) => (
                    <div key={message.id} className={`ops-chat-row ${message.role}`}>
                      <article className={`ops-chat-bubble ${message.role}`}>
                        <div className="ops-chat-bubble-label">{message.role === 'user' ? 'User' : 'Assistant'}</div>
                        {message.content ? <MarkdownMessage content={message.content} /> : null}
                        {message.role === 'assistant' && message.id === activeAssistantId ? (
                          <AssistantProgress stages={chatStages} compact={Boolean(message.content)} />
                        ) : null}
                        {message.sources?.length ? (
                          <div className="ops-chat-chip-row">
                            {message.sources.map((source) => (
                              <button
                                key={`${message.id}-${source.index}`}
                                type="button"
                                className="ops-chat-chip"
                                onClick={() => { void handleOpenSnippet(source.source_path, source.chunk_id); }}
                              >
                                {source.title}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {message.artifacts?.length ? (
                          <div className="ops-chat-artifact-panel">
                            <div className="ops-chat-artifact-title">Artifacts</div>
                            <div className="ops-chat-artifact-list">
                              {message.artifacts.map((artifact, artifactIndex) => (
                                <div key={`${message.id}-artifact-${artifactIndex}`} className="ops-chat-artifact-card">
                                  <div className="ops-chat-artifact-head">
                                    <strong>{artifact.title}</strong>
                                    {artifact.resource_type ? <span>{artifact.resource_type}</span> : null}
                                  </div>
                                  {artifact.kind === 'resource_list' ? (
                                    <div className="ops-chat-artifact-items">
                                      {artifact.items.map((item, itemIndex) => {
                                        const itemName = String(item.name || '');
                                        const itemNamespace = String(item.namespace || artifact.namespace || '');
                                        const itemKind = String(item.kind || '');
                                        return (
                                          <div key={`${itemName}-${itemIndex}`} className="ops-chat-artifact-item-row">
                                            <div className="ops-chat-artifact-item-copy">
                                              <strong>{itemName}</strong>
                                              <span>{itemKind} · {itemNamespace}</span>
                                            </div>
                                            <div className="ops-inline-actions">
                                              <button
                                                type="button"
                                                onClick={() => {
                                                  void openChatArtifactResource({
                                                    connection_id: artifact.connection_id,
                                                    resource_type: String(artifact.resource_type || ''),
                                                    namespace: itemNamespace,
                                                    name: itemName,
                                                    open_editor: Boolean(artifact.editable),
                                                  });
                                                }}
                                              >
                                                {artifact.editable ? 'Edit YAML' : 'Open Detail'}
                                              </button>
                                            </div>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  ) : (
                                    <div className="ops-chat-artifact-items">
                                      {artifact.summary ? <pre>{formatJson(artifact.summary)}</pre> : null}
                                      {artifact.manifest_yaml ? <pre className="ops-chat-yaml-block">{artifact.manifest_yaml}</pre> : null}
                                      {!artifact.manifest_yaml && artifact.manifest_preview ? <pre>{artifact.manifest_preview}</pre> : null}
                                      <div className="ops-inline-actions">
                                        <button
                                          type="button"
                                          onClick={() => {
                                            void openChatArtifactResource({
                                              connection_id: artifact.connection_id,
                                              resource_type: String(artifact.resource_type || ''),
                                              namespace: String(artifact.namespace || ''),
                                              name: String(artifact.name || ''),
                                              open_editor: Boolean(artifact.editable),
                                            });
                                          }}
                                        >
                                          {artifact.editable ? 'Edit YAML' : 'Open Detail'}
                                        </button>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </article>
                    </div>
                  ))}
                </div>
                {chatStages.length ? (
                  <div className="ops-chat-stage-strip">
                    {chatStages.map((stage, index) => (
                      <div key={`${stage.label}-${index}`} className={`ops-chat-stage-card ${stage.status}`}>
                        <strong>{stage.label}</strong>
                        <span>{stage.detail}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="ops-chat-composer-wrap">
                <div className="ops-chat-composer">
                  <input value={chatDraft} onChange={(event) => setChatDraft(event.target.value)} placeholder="문서나 리소스 상태를 질문하세요" />
                  <button type="button" className="ops-chat-send-btn" disabled={chatSending} onClick={() => { void handleSendChat(); }}>
                    <Send size={16} />
                    <span>{chatSending ? 'Running' : 'Send'}</span>
                  </button>
                </div>
              </div>
              {snippet ? (
                <div className="ops-chat-snippet-panel">
                  <div className="ops-chat-artifact-title">Snippet</div>
                  <pre>{snippet.snippet}</pre>
                </div>
              ) : null}
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
                {actionExecutions.length > 0 ? <pre>{formatJson(actionExecutions)}</pre> : null}
                {actionAudit.length > 0 ? <pre>{formatJson(actionAudit)}</pre> : null}
              </div>
            </section>
          )}
        </main>
    </div>
  );
}
