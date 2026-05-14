import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { Group, Panel, Separator, usePanelRef, useDefaultLayout } from 'react-resizable-panels';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  ChevronDown,
  ChevronRight,
  Send,
  BookOpen,
  Cpu,
  ArrowRight,
  ArrowDown,
  Sparkles,
  Link as LinkIcon,
  Plus,
  MessageSquare,
  Trash2,
  PanelLeftClose,
  PanelRightClose,
  Check,
  Star,
  Clock3,
  Compass,
  Terminal as TerminalIcon,
  X,
} from 'lucide-react';
import gsap from 'gsap';
import './WorkspacePage.css';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import {
  DOCUMENT_INGEST_UPLOAD_ACCEPT,
  type ChatResponse,
  type ChatCitation,
  type ChatRelatedLink,
  type CustomerPackBook,
  type CustomerPackDraft,
  type DocumentRepository,
  type DocumentRepositoryDocument,
  type DerivedAsset,
  type LibraryBook,
  type SessionSummary,
  type StudioStarterQuestion,
  type StudioStarterQuestionGroup,
  type WikiOverlayRecommendedPlay,
  type WikiOverlaySignalsResponse,
  type SourceMetaResponse,
  type WikiAnnotationTool,
  type WikiEditedTextStyle,
  type WikiInkColorId,
  type WikiInkStroke,
  type WikiOverlayRecord,
  type WikiOverlayTargetKind,
  type WikiTextAnnotation,
  type WikiTextAnnotationMode,
  type ViewerPageMode,
  archiveDbChatSession,
  captureCustomerPackDraft,
  formatBytes,
  listCustomerPackDrafts,
  listDbChatSessions,
  listSessions,
  loadCustomerPackBook,
  loadCustomerPackDraft,
  loadDataControlRoom,
  loadDbChatMessages,
  loadDocumentIngestStatus,
  loadDocumentRepositories,
  loadSignals,
  loadWikiOverlaySignals,
  loadWikiOverlays,
  loadSession,
  loadStudioStarterQuestions,
  deleteAllSessions,
  deleteSession,
  loadSourceMeta,
  loadViewerDocument,
  normalizeViewerPath,
  normalizeCustomerPackDraft,
  removeWikiOverlay,
  saveWikiOverlay,
  sendChatStream,
  toRuntimeUrl,
  uploadDocumentIngestion,
} from '../lib/runtimeApi';
import {
  loadOcpStatus,
  loadOcpMetrics,
  loadOcpOverview,
  loadResourceDetail,
  loadResources,
  listOcpProfiles,
  sendOpsChatStream,
  type OcpResourceItem,
  type OcpMetricsResponse,
  type OcpOverview,
  type ResourceDetailResponse,
  type OcpConnection,
  type OpsChatResponse,
  type OpsChatSource,
} from '../lib/opsConsoleApi';
import { ROUTES } from '../routing/routes';
import { sendCourseChatStream } from '../lib/courseApi';
import { loadStoredVisionMode, type VisionMode } from '../lib/wikiVision';
import { resolveWorkspaceSourceBooks } from '../lib/workspaceSourceCatalog';
import WorkspaceTracePanel from '../components/WorkspaceTracePanel';
import WorkspaceHeader from './workspace/WorkspaceHeader';
import {
  AssistantAnswer,
  CitationTag,
  ThinkingIndicator,
  TruthBadgeBlock,
  truthSurfaceCopy,
} from './workspace/WorkspaceAnswer';
import WorkspaceViewerPanel from './workspace/WorkspaceViewerPanel';
import TerminalSessionPanel, { type TerminalConnectionState, type TerminalLearningContext } from './workspace/TerminalSessionPanel';
import CourseChatArtifacts from './CourseChatArtifacts';
import type {
  Message,
  SourceEntry,
  WorkspaceManualBook,
  WorkspaceTestTrace,
} from './workspaceTypes';
import { buildOutlineBookFamilies, describeOutlineVariant } from './workspaceOutline';

interface OverlayTargetDescriptor {
  kind: WikiOverlayTargetKind;
  ref: string;
  title: string;
  viewerPath: string;
  payload: Record<string, unknown>;
}

interface ViewerActiveSection {
  anchor: string;
  title: string;
}

const WORKSPACE_ACTIVE_SOURCE_STORAGE_KEY = 'workspace.activeSourceId';
const WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY = 'workspace.activeDocumentId';
const WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY = 'workspace.activeDocumentTitle';
const WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY = 'workspace.activeCategoryKey';
const WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY = 'workspace.activeCategoryLabel';
const WORKSPACE_INGESTION_STATUS_STORAGE_KEY = 'workspace.ingestionStatus';

function workspaceMetadataRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function workspaceMetadataString(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

function loadStoredActiveSourceId(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const value = window.localStorage.getItem(WORKSPACE_ACTIVE_SOURCE_STORAGE_KEY);
  return value && value.trim() ? value : null;
}

function loadStoredIngestionStatus(): IngestionStatusBanner | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY);
    return raw ? JSON.parse(raw) as IngestionStatusBanner : null;
  } catch {
    return null;
  }
}

function citationEvidenceTitle(citation: ChatCitation): string {
  return citation.source_label || citation.book_title || citation.section || citation.book_slug || `Citation ${citation.index}`;
}

function citationEvidenceMeta(citation: ChatCitation): string {
  return [
    citation.runtime_truth_label || citation.boundary_badge || citation.source_lane || '',
    citation.section_path || citation.section || '',
    citation.viewer_path || '',
  ].filter(Boolean).join(' · ');
}

function opsSourceToChatCitation(source: OpsChatSource, fallbackIndex: number): ChatCitation {
  const index = Number.isFinite(source.index) && source.index > 0 ? source.index : fallbackIndex;
  return {
    index,
    book_slug: 'live_cluster',
    book_title: 'Live Cluster',
    section: source.section_title || source.title || 'Cluster evidence',
    section_path_label: source.source_path || source.viewer_path || '',
    viewer_path: source.viewer_path || source.source_path || '',
    excerpt: source.source_path ? `Live cluster source: ${source.source_path}` : undefined,
    source_label: source.title || source.section_title || 'Live cluster',
    source_lane: 'live_cluster',
    runtime_truth_label: 'Live cluster',
    boundary_badge: 'Live',
  };
}

function opsChatResponseToChatResponse(response: OpsChatResponse, sessionId: string): ChatResponse & { artifacts?: Array<Record<string, unknown>> } {
  return {
    answer: response.answer,
    citations: response.sources.map((source, index) => opsSourceToChatCitation(source, index + 1)),
    warnings: [],
    session_id: sessionId,
    response_kind: response.mode || response.lane || 'live_cluster',
    suggested_queries: [],
    related_links: [],
    related_sections: [],
    artifacts: response.artifacts.map((artifact) => ({ ...artifact })),
    pipeline_trace: {
      live_cluster: {
        lane: response.lane,
        mode: response.mode,
        fallback_used: response.fallback_used,
        preview_ready: response.preview_ready,
      },
    },
  };
}

type LeftPanelMode = 'history' | 'outline' | 'signals';
type RightPanelMode = 'viewer' | 'terminal';
type WorkspaceChatMode = 'document' | 'live_cluster';
type ClusterConnectionStatus = 'not_connected' | 'connecting' | 'connected' | 'error';
type SignalsFavoriteFilter = 'favorites' | 'edited';
const CLUSTER_RESOURCE_OPTIONS = ['pods', 'deployments', 'services', 'routes', 'events'] as const;
type ClusterResourceKind = typeof CLUSTER_RESOURCE_OPTIONS[number];

interface ClusterSignalEvent {
  id: string;
  timestamp: string;
  operationType: string;
  resourceKind: string;
  resourceName: string;
  namespace: string;
  status: string;
  sourceCommand: string;
}

interface RecentTerminalAction {
  command: string;
  timestamp: string;
}

interface IngestionStatusBanner {
  status: 'recognizing' | 'parsing' | 'embedding' | 'indexing' | 'ready' | 'failed';
  message: string;
  filename?: string;
  repositoryId?: string;
  documentSourceId?: string;
  updatedAt: string;
}
interface OutlineLinkItem {
  id: string;
  label: string;
  meta?: string;
  action: () => void;
  tone?: 'default' | 'muted';
}

interface OutlineTocNode {
  id: string;
  heading: string;
  depth: number;
  viewerPath: string;
  sectionPathLabel: string;
}

interface OutlineCategoryGroup {
  key: string;
  label: string;
  description: string;
  books: WorkspaceManualBook[];
}

const OUTLINE_CATEGORY_RULES: Array<{
  key: string;
  label: string;
  description: string;
  patterns: string[];
}> = [
    { key: 'install', label: 'Install', description: '클러스터 설치와 Day-1 경로', patterns: ['install', 'installation', 'day-1', 'day 1', 'cluster installation'] },
    { key: 'day2', label: 'Day-2', description: '운영 전환과 후속 구성', patterns: ['day-2', 'day 2', 'postinstall', 'post-install', 'day two'] },
    { key: 'operations', label: 'Operations', description: '일상 운영과 변경 관리', patterns: ['machine config', 'operator', 'control plane', 'node', 'proxy', 'configuration', 'operations'] },
    { key: 'storage', label: 'Storage', description: '스토리지, 백업, 복구', patterns: ['storage', 'backup', 'restore', 'etcd', 'registry', 'image'] },
    { key: 'observability', label: 'Observability', description: '모니터링과 진단', patterns: ['monitor', 'observab', 'alert', 'logging', 'telemetry'] },
    { key: 'security', label: 'Security', description: '권한, 인증, 보안 운영', patterns: ['security', 'auth', 'authorization', 'rbac', 'certificate', 'compliance'] },
    { key: 'networking', label: 'Networking', description: '네트워크와 연결 경로', patterns: ['network', 'ingress', 'egress', 'dns', 'route'] },
    { key: 'troubleshooting', label: 'Troubleshooting', description: '문제 해결과 복구 경로', patterns: ['troubleshoot', 'issue', 'failure', 'debug', 'problem'] },
    { key: 'reference', label: 'Reference', description: '기타 참조 문서', patterns: [] },
  ];

const OUTLINE_CATEGORY_COLLAPSED = '__collapsed__';
const DEFAULT_EDITED_TEXT_STYLE: WikiEditedTextStyle = {
  tone: 'amber',
  size: 'md',
  weight: 'regular',
};

function normalizeEditedTextStyle(value?: Partial<WikiEditedTextStyle> | null): WikiEditedTextStyle {
  const tone = String(value?.tone || '').trim().toLowerCase();
  const size = String(value?.size || '').trim().toLowerCase();
  const weight = String(value?.weight || '').trim().toLowerCase();
  return {
    tone:
      tone === 'ink'
      || tone === 'teal'
      || tone === 'amber'
      || tone === 'cyan'
      || tone === 'rose'
      || tone === 'violet'
      || tone === 'lime'
        ? tone
        : DEFAULT_EDITED_TEXT_STYLE.tone,
    size: size === 'sm' || size === 'lg' || size === 'md' ? size : DEFAULT_EDITED_TEXT_STYLE.size,
    weight: weight === 'strong' || weight === 'regular' ? weight : DEFAULT_EDITED_TEXT_STYLE.weight,
  };
}

function normalizeAnnotationRatio(value: unknown, fallback: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(0, Math.min(1, numeric));
}

function createTextAnnotationId(): string {
  if (typeof globalThis !== 'undefined' && 'crypto' in globalThis && typeof globalThis.crypto?.randomUUID === 'function') {
    return `ant-${globalThis.crypto.randomUUID().slice(0, 8)}`;
  }
  return `ant-${Math.random().toString(36).slice(2, 10)}`;
}

function overlayAnchorFromTargetRef(targetRef: string): string {
  const normalized = String(targetRef || '').trim();
  if (!normalized.startsWith('section:') || !normalized.includes('#')) {
    return '';
  }
  return normalized.split('#').slice(1).join('#').trim();
}

function annotationColorIdToTone(colorId: WikiInkColorId): WikiEditedTextStyle['tone'] {
  const normalized = String(colorId || '').trim().toLowerCase();
  if (
    normalized === 'amber'
    || normalized === 'ink'
    || normalized === 'teal'
    || normalized === 'cyan'
    || normalized === 'rose'
    || normalized === 'violet'
    || normalized === 'lime'
  ) {
    return normalized;
  }
  return DEFAULT_EDITED_TEXT_STYLE.tone;
}

function normalizeTextAnnotation(
  value: Partial<WikiTextAnnotation> | null | undefined,
  fallbackAnchor: string,
): WikiTextAnnotation | null {
  const kind = String(value?.kind || '').trim().toLowerCase();
  if (kind !== 'add' && kind !== 'edit') {
    return null;
  }
  const text = String(value?.text || '').trim();
  if (!text) {
    return null;
  }
  const anchor = String(value?.anchor || fallbackAnchor || '').trim();
  if (!anchor) {
    return null;
  }
  const annotationId = String(value?.annotation_id || '').trim() || createTextAnnotationId();
  const blockPath = String(value?.block_path || '').trim();
  if (kind === 'edit' && !blockPath) {
    return null;
  }
  return {
    annotation_id: annotationId,
    kind,
    anchor,
    text,
    style: normalizeEditedTextStyle(value?.style),
    x_ratio: normalizeAnnotationRatio(value?.x_ratio, 0.08),
    y_ratio: normalizeAnnotationRatio(value?.y_ratio, 0.12),
    block_path: blockPath,
  };
}

function extractTextAnnotations(
  value?: Pick<WikiOverlayRecord, 'text_annotations' | 'payload' | 'body' | 'text_style' | 'target_ref'> | null,
  fallbackAnchor = '',
): WikiTextAnnotation[] {
  if (!value) {
    return [];
  }
  const anchor = String(fallbackAnchor || overlayAnchorFromTargetRef(value.target_ref || '')).trim();
  const payload = value.payload && typeof value.payload === 'object'
    ? value.payload as Record<string, unknown>
    : {};
  const rawAnnotations = Array.isArray(value.text_annotations)
    ? value.text_annotations
    : Array.isArray(payload.text_annotations)
      ? payload.text_annotations as Partial<WikiTextAnnotation>[]
      : [];
  const normalized = rawAnnotations
    .map((item) => normalizeTextAnnotation(item, anchor))
    .filter((item): item is WikiTextAnnotation => Boolean(item));
  if (normalized.length > 0) {
    return normalized;
  }
  const legacyBody = String(value.body || '').trim();
  if (!legacyBody || !anchor) {
    return [];
  }
  return [
    {
      annotation_id: `legacy-${anchor}`,
      kind: 'add',
      anchor,
      text: legacyBody,
      style: normalizeEditedTextStyle(value.text_style),
      x_ratio: 0.08,
      y_ratio: 0.12,
      block_path: '',
    },
  ];
}

type WelcomeQuestion = {
  lane: 'faq' | 'learning' | 'operations';
  question: string;
  routeKind?: Message['routeKind'];
  learningIndex?: number;
  categoryKey?: string;
  categoryLabel?: string;
  targetBookSlug?: string;
  targetTitle?: string;
  targetViewerPath?: string;
  learningPathId?: string;
  learningStepId?: string;
  labTaskId?: string;
};

type WelcomeQuestionGroup = {
  key: WelcomeQuestion['lane'];
  title: string;
  description: string;
  questions: WelcomeQuestion[];
};

type SendOptions = {
  forceCourseMode?: boolean;
  routeKind?: Message['routeKind'];
  learningIndex?: number;
  categoryKey?: string;
  categoryLabel?: string;
  targetBookSlug?: string;
  targetTitle?: string;
  targetViewerPath?: string;
  learningPathId?: string;
  learningStepId?: string;
  labTaskId?: string;
};

const EMPTY_WELCOME_QUESTION_GROUPS: WelcomeQuestionGroup[] = [];

function normalizeWelcomeLane(value: string): WelcomeQuestion['lane'] {
  if (value === 'faq' || value === 'learning' || value === 'operations') {
    return value;
  }
  return 'faq';
}

function normalizeWelcomeRouteKind(value?: string): Message['routeKind'] {
  if (value === 'learning' || value === 'course' || value === 'official') {
    return value;
  }
  return undefined;
}

function normalizeWelcomeQuestion(item: StudioStarterQuestion): WelcomeQuestion | null {
  const question = String(item.question || '').trim();
  if (!question) {
    return null;
  }
  return {
    lane: normalizeWelcomeLane(String(item.lane || 'faq')),
    question,
    routeKind: normalizeWelcomeRouteKind(item.route_kind),
    learningIndex: typeof item.learning_index === 'number' ? item.learning_index : undefined,
    categoryKey: typeof item.category_key === 'string' ? item.category_key : undefined,
    categoryLabel: typeof item.category_label === 'string' ? item.category_label : undefined,
    targetBookSlug: typeof item.target_book_slug === 'string' ? item.target_book_slug : undefined,
    targetTitle: typeof item.target_title === 'string' ? item.target_title : undefined,
    targetViewerPath: typeof item.target_viewer_path === 'string' ? item.target_viewer_path : undefined,
    learningPathId: typeof item.learning_path_id === 'string' ? item.learning_path_id : undefined,
    learningStepId: typeof item.learning_step_id === 'string' ? item.learning_step_id : undefined,
    labTaskId: typeof item.lab_task_id === 'string' ? item.lab_task_id : undefined,
  };
}

function normalizeWelcomeQuestionGroup(group: StudioStarterQuestionGroup): WelcomeQuestionGroup | null {
  const key = normalizeWelcomeLane(String(group.key || 'faq'));
  const questions = (group.questions || [])
    .map(normalizeWelcomeQuestion)
    .filter((item): item is WelcomeQuestion => Boolean(item));
  if (!questions.length) {
    return null;
  }
  return {
    key,
    title: String(group.title || key).trim() || key,
    description: String(group.description || '').trim(),
    questions,
  };
}

function mergeLearningFollowUps(
  serverSuggestions: string[],
  learningIndex?: number,
  learningSequence: WelcomeQuestion[] = [],
): string[] {
  if (learningIndex === undefined) {
    return serverSuggestions;
  }
  const nextLearningQuestions = learningSequence
    .filter((item) => typeof item.learningIndex === 'number' && item.learningIndex > learningIndex)
    .slice(0, 2)
    .map((item) => item.question);
  return [...nextLearningQuestions, ...serverSuggestions]
    .map((item) => item.trim())
    .filter((item, index, items) => item && items.indexOf(item) === index)
    .slice(0, 4);
}

const CONTINUATION_QUERY_RE = /^(응|네|예|ㅇㅇ|좋아|안내해줘|계속|다음|이어줘|이어 줘|진행해줘|해줘|알려줘)[\s.!?。]*$/i;

function isContinuationQuery(value: string): boolean {
  return CONTINUATION_QUERY_RE.test(value.trim());
}

function resolveContinuationQuestion(
  value: string,
  messages: Message[],
  learningQuestionByText: Map<string, WelcomeQuestion>,
): { query: string; routeKind?: Message['routeKind']; learningIndex?: number; questionMeta?: WelcomeQuestion } {
  if (!isContinuationQuery(value)) {
    return { query: value };
  }
  const lastAssistantWithSuggestions = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant' && (message.suggestedQueries?.length ?? 0) > 0);
  const nextQuestion = lastAssistantWithSuggestions?.suggestedQueries?.[0]?.trim();
  if (!nextQuestion) {
    return { query: value };
  }
  const routeKind = lastAssistantWithSuggestions?.routeKind;
  const questionMeta = learningQuestionByText.get(nextQuestion);
  return {
    query: nextQuestion,
    routeKind,
    learningIndex: routeKind === 'learning'
      ? questionMeta?.learningIndex
      : undefined,
    questionMeta,
  };
}

type PreviewState =
  | { kind: 'empty' }
  | { kind: 'loading'; title: string }
  | {
    kind: 'viewer';
    title: string;
    subtitle: string;
    meta?: SourceMetaResponse;
    viewerUrl: string;
    viewerDocument?: ViewerDocumentPayload;
    scrollTargetText?: string;
  }
  | {
    kind: 'draft';
    title: string;
    subtitle: string;
    draft: CustomerPackDraft;
    book?: CustomerPackBook;
    viewerUrl: string;
    derivedAssets: DerivedAsset[];
    viewerDocument?: ViewerDocumentPayload;
  };

type EvidenceDrawerState =
  | { kind: 'closed' }
  | { kind: 'loading'; title: string }
  | {
    kind: 'viewer';
    title: string;
    subtitle: string;
    viewerPath: string;
    viewerDocument: ViewerDocumentPayload;
    scrollTargetText?: string;
  }
  | { kind: 'error'; title: string; message: string };

function makeId(prefix: string): string {
  const shortPart = Math.random().toString(36).substring(2, 8).toUpperCase();
  return `${prefix}-${shortPart}`;
}

function normalizePlaybookGrade(grade?: string | null): 'Gold' | 'Silver' | 'Bronze' {
  const normalized = String(grade || '').trim().toLowerCase();
  if (normalized === 'gold') {
    return 'Gold';
  }
  if (normalized === 'silver' || normalized === 'silver draft' || normalized === 'mixed review') {
    return 'Silver';
  }
  return 'Bronze';
}

function playbookGradeBadgeClass(grade?: string | null): string {
  const normalized = normalizePlaybookGrade(grade).toLowerCase();
  return `playbook-grade-badge playbook-grade-badge--${normalized}`;
}

function summarizeBookMeta(book: WorkspaceManualBook): string {
  const parts = [
    book.library_group_label,
    book.family_label,
    book.source_type,
    Number.isFinite(book.section_count) && book.section_count > 0 ? `${book.section_count} sections` : '',
  ].filter(Boolean);
  return parts.join(' · ');
}


function inferOutlineCategory(book: WorkspaceManualBook): OutlineCategoryGroup {
  const haystack = [
    book.book_slug,
    book.title,
    book.source_type,
    book.source_lane,
    book.family,
    book.family_label,
  ].join(' ').toLowerCase();

  const matchedRule = OUTLINE_CATEGORY_RULES.find((rule) => rule.patterns.some((pattern) => haystack.includes(pattern)));
  if (matchedRule) {
    return {
      key: matchedRule.key,
      label: matchedRule.label,
      description: matchedRule.description,
      books: [],
    };
  }

  const fallbackRule = OUTLINE_CATEGORY_RULES[OUTLINE_CATEGORY_RULES.length - 1];
  return {
    key: fallbackRule.key,
    label: fallbackRule.label,
    description: fallbackRule.description,
    books: [],
  };
}

function formatDraftMeta(draft: CustomerPackDraft): string {
  const size = formatBytes(draft.uploaded_byte_size);
  const pieces = [draft.status, draft.source_type.toUpperCase()];
  if (size) {
    pieces.push(size);
  }
  return pieces.filter(Boolean).join(' · ');
}

function primaryCitationTruth(citations?: ChatCitation[] | null): {
  sourceLane?: string;
  boundaryTruth?: string;
  runtimeTruthLabel?: string;
  boundaryBadge?: string;
  publicationState?: string;
  approvalState?: string;
} | null {
  if (!citations || citations.length === 0) {
    return null;
  }
  const primary = pickPrimaryPlaybookCitation(citations);
  if (!primary) {
    return null;
  }
  return {
    sourceLane: primary.source_lane,
    boundaryTruth: primary.boundary_truth,
    runtimeTruthLabel: primary.runtime_truth_label,
    boundaryBadge: primary.boundary_badge,
    publicationState: primary.publication_state,
    approvalState: primary.approval_state,
  };
}

function isCourseSourceLane(sourceLane?: string): boolean {
  const normalized = String(sourceLane || '').trim().toLowerCase();
  return normalized === 'course' || normalized === 'operations' || normalized === 'study_docs';
}

function scorePrimaryPlaybookCitation(citation: ChatCitation, index: number): number {
  const slug = String(citation.book_slug || '').trim().toLowerCase();
  const title = String(citation.book_title || citation.source_label || citation.section || '').trim().toLowerCase();
  const sourceLane = String(citation.source_lane || '').trim().toLowerCase();
  const boundaryTruth = String(citation.boundary_truth || '').trim().toLowerCase();
  const viewerPath = String(citation.viewer_path || '').trim().toLowerCase();

  let score = 0;

  if (boundaryTruth === 'official_validated_runtime') score += 40;
  if (sourceLane.includes('wiki_runtime') || sourceLane.includes('approved')) score += 24;
  if (viewerPath.includes('/playbooks/wiki-runtime/active/')) score += 20;
  if (viewerPath.includes('/docs/ocp/')) score += 12;

  if (slug === 'support' || slug === 'release_notes') score -= 120;
  if (title.includes('지원') || title.includes('release note') || title.includes('릴리스 노트')) score -= 80;

  // Prefer earlier citations when scores are otherwise equal.
  score -= index;

  return score;
}

function pickPrimaryPlaybookCitation(citations?: ChatCitation[] | null): ChatCitation | null {
  if (!citations || citations.length === 0) {
    return null;
  }

  return citations
    .map((citation, index) => ({ citation, score: scorePrimaryPlaybookCitation(citation, index), index }))
    .sort((left, right) => right.score - left.score || left.index - right.index)[0]?.citation ?? null;
}

function NoAnswerAcquisitionCard({
  acquisition,
  onConfirm,
}: {
  acquisition: NonNullable<Message['acquisition']>;
  onConfirm: () => void;
}) {
  const [checked, setChecked] = useState(true);

  return (
    <div className="no-answer-acquisition-card">
      <div className="no-answer-acquisition-title">{acquisition.title}</div>
      <p className="no-answer-acquisition-body">{acquisition.body}</p>
      <label className="no-answer-acquisition-check">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => setChecked(event.target.checked)}
        />
        <span>{acquisition.checkbox_label}</span>
      </label>
      <button
        type="button"
        className="suggested-query-chip acquisition-confirm-btn"
        disabled={!checked}
        onClick={() => onConfirm()}
      >
        {acquisition.confirm_label}
      </button>
    </div>
  );
}

const FALLBACK_CLUSTER_USER_LABEL = 'Undefined';

function normalizeClusterConnectionStatus(connection?: OcpConnection | null): ClusterConnectionStatus {
  const status = connection?.status?.toLowerCase().trim();
  if (!connection || !status || status === 'disconnected' || status === 'not_connected') {
    return 'not_connected';
  }
  if (status === 'connected' || status === 'ready' || status === 'active') {
    return 'connected';
  }
  if (status === 'connecting' || status === 'pending' || status === 'testing') {
    return 'connecting';
  }
  return 'error';
}

function detectClusterSignal(command: string): Omit<ClusterSignalEvent, 'id' | 'timestamp' | 'status'> | null {
  const normalized = command.trim().replace(/\s+/g, ' ');
  const match = normalized.match(/^(oc|kubectl)\s+(create|apply|delete|edit|patch|rollout|scale|expose|adm|set\s+image)\b/i);
  if (!match) {
    return null;
  }
  const operationType = match[2].toLowerCase();
  const namespaceMatch = normalized.match(/(?:^|\s)(?:-n|--namespace)\s+([^\s]+)/i);
  const namespace = namespaceMatch?.[1] ?? 'default';
  const afterOperation = normalized.slice(match[0].length).trim();
  const tokens = afterOperation.split(/\s+/).filter(Boolean);
  const resourceKind = tokens.find((token) => !token.startsWith('-') && !token.includes('=')) ?? 'resource';
  const resourceName = tokens.find((token, index) => index > 0 && !token.startsWith('-') && !token.includes('=')) ?? '';
  return {
    operationType,
    resourceKind,
    resourceName,
    namespace,
    sourceCommand: command,
  };
}

function signalEventFromApi(item: {
  signal_id: string;
  timestamp: string;
  operation_type: string;
  resource_kind: string;
  resource_name: string;
  namespace: string;
  status: string;
  source_command: string;
}): ClusterSignalEvent {
  return {
    id: item.signal_id,
    timestamp: item.timestamp,
    operationType: item.operation_type,
    resourceKind: item.resource_kind,
    resourceName: item.resource_name,
    namespace: item.namespace,
    status: item.status,
    sourceCommand: item.source_command,
  };
}

function runtimePathFromUrl(viewerUrl: string): string {
  try {
    const parsed = new URL(viewerUrl, window.location.origin);
    return normalizeViewerPath(`${parsed.pathname}${parsed.search || ''}${parsed.hash || ''}`);
  } catch {
    return normalizeViewerPath(viewerUrl);
  }
}

function normalizeViewerDocumentPayload(viewerDocument: Awaited<ReturnType<typeof loadViewerDocument>>): ViewerDocumentPayload {
  return {
    html: viewerDocument.html,
    inlineStyles: viewerDocument.inline_styles,
    bodyClassName: viewerDocument.body_class_name,
    interactionPolicy: {
      codeCopy: viewerDocument.interaction_policy.code_copy,
      codeWrapToggle: viewerDocument.interaction_policy.code_wrap_toggle,
      recentPositionTracking: viewerDocument.interaction_policy.recent_position_tracking,
      anchorNavigation: viewerDocument.interaction_policy.anchor_navigation,
    },
  };
}

function firstCitationCommand(citation: ChatCitation): string {
  return (citation.cli_commands ?? [])
    .map((command) => String(command || '').trim())
    .find(Boolean) ?? '';
}

function answerCodeBlocks(answer: string): string[] {
  const blocks: string[] = [];
  const fenceRe = /```[^\n`]*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  while ((match = fenceRe.exec(answer)) !== null) {
    const block = String(match[1] || '').trim();
    if (block) {
      blocks.push(block);
    }
  }
  return blocks;
}

function citationScrollTarget(citation: ChatCitation, answerContent = ''): string {
  const codeBlocks = answerCodeBlocks(answerContent);
  const citationCommands = (citation.cli_commands ?? [])
    .map((command) => String(command || '').trim())
    .filter(Boolean);
  const excerpt = String(citation.excerpt || '').toLowerCase();
  const backupBlock = codeBlocks.find((block) => /cluster-backup\.sh|etcdctl|snapshot/i.test(block));

  const excerptMatchedBlock = codeBlocks.find((block) => excerpt.includes(block.toLowerCase()));
  if (excerptMatchedBlock) {
    return excerptMatchedBlock;
  }

  const citationHasBackupSignal = /cluster-backup\.sh|etcdctl|snapshot/i.test(
    `${citationCommands.join('\n')}\n${citation.excerpt || ''}\n${citation.section || ''}`,
  );
  if (citationHasBackupSignal && backupBlock) {
    return backupBlock;
  }

  for (const command of citationCommands) {
    const matchedAnswerBlock = codeBlocks.find((block) => block.trim() === command || block.includes(command));
    if (matchedAnswerBlock) {
      return matchedAnswerBlock;
    }
  }

  if (backupBlock) {
    return backupBlock;
  }

  return codeBlocks[0] || citationCommands[0] || '';
}

type MessageStateUpdater = (updater: (current: Message[]) => Message[]) => void;

function createThrottledMessageContentUpdater(
  messageId: string,
  updateMessages: MessageStateUpdater,
  delayMs = 90,
): { push: (content: string) => void; flush: () => void; cancel: () => void } {
  let latestContent = '';
  let timerId = 0;
  let frameId = 0;

  const applyLatest = (): void => {
    updateMessages((current) => current.map((message) => (
      message.id === messageId
        ? { ...message, content: latestContent }
        : message
    )));
  };

  const clearScheduled = (): void => {
    if (timerId) {
      window.clearTimeout(timerId);
      timerId = 0;
    }
    if (frameId) {
      window.cancelAnimationFrame(frameId);
      frameId = 0;
    }
  };

  return {
    push(content: string): void {
      latestContent = content;
      if (typeof window === 'undefined') {
        applyLatest();
        return;
      }
      if (timerId || frameId) {
        return;
      }
      timerId = window.setTimeout(() => {
        timerId = 0;
        frameId = window.requestAnimationFrame(() => {
          frameId = 0;
          applyLatest();
        });
      }, delayMs);
    },
    flush(): void {
      if (typeof window !== 'undefined') {
        clearScheduled();
      }
      applyLatest();
    },
    cancel(): void {
      if (typeof window !== 'undefined') {
        clearScheduled();
      }
    },
  };
}

function parseViewerHtml(viewerHtml: string): Document | null {
  if (typeof DOMParser === 'undefined') {
    return null;
  }
  try {
    return new DOMParser().parseFromString(viewerHtml, 'text/html');
  } catch {
    return null;
  }
}

function extractVisibleViewerSection(viewerHtml: string): { anchor: string; title: string } | null {
  const documentRoot = parseViewerHtml(viewerHtml);
  const section = documentRoot?.querySelector('section.section-card[id], section.embedded-section[id]');
  if (!(section instanceof HTMLElement)) {
    return null;
  }
  const anchor = String(section.id || '').trim();
  if (!anchor) {
    return null;
  }
  const title = section.querySelector('h2')?.textContent?.trim() || section.querySelector('.section-meta')?.textContent?.trim() || anchor;
  return { anchor, title };
}

function extractViewerQuickNavItems(viewerHtml: string, viewerPath: string): OutlineTocNode[] {
  const documentRoot = parseViewerHtml(viewerHtml);
  if (!documentRoot) {
    return [];
  }
  const baseViewerPath = normalizeViewerPath(viewerPath.split('#', 1)[0] || viewerPath);
  const nodes: OutlineTocNode[] = [];
  const seen = new Set<string>();

  documentRoot.querySelectorAll('.document-nav-link[href]').forEach((node) => {
    if (!(node instanceof HTMLAnchorElement)) {
      return;
    }
    const rawHref = String(node.getAttribute('href') || '').trim();
    const label = node.textContent?.trim() || '';
    if (!rawHref || !label) {
      return;
    }
    const anchor = rawHref.startsWith('#') ? rawHref.slice(1) : rawHref.split('#', 2)[1] || '';
    if (!anchor || seen.has(anchor)) {
      return;
    }
    seen.add(anchor);
    nodes.push({
      id: anchor,
      heading: label,
      depth: 1,
      viewerPath: rawHref.startsWith('#') ? `${baseViewerPath}#${anchor}` : normalizeViewerPath(rawHref),
      sectionPathLabel: String(node.getAttribute('title') || label).trim(),
    });
  });

  if (nodes.length > 0) {
    return nodes;
  }

  documentRoot.querySelectorAll('section.section-card[id], section.embedded-section[id]').forEach((node) => {
    if (!(node instanceof HTMLElement)) {
      return;
    }
    const anchor = String(node.id || '').trim();
    const heading = node.querySelector('h2')?.textContent?.trim() || node.querySelector('.section-meta')?.textContent?.trim() || anchor;
    const sectionPathLabel = node.querySelector('.section-meta')?.textContent?.trim() || heading;
    if (!anchor || !heading || seen.has(anchor)) {
      return;
    }
    seen.add(anchor);
    nodes.push({
      id: anchor,
      heading,
      depth: 1,
      viewerPath: `${baseViewerPath}#${anchor}`,
      sectionPathLabel,
    });
  });

  return nodes;
}

async function loadViewerDocumentPayload(viewerPath: string, pageMode: ViewerPageMode): Promise<ViewerDocumentPayload> {
  return normalizeViewerDocumentPayload(await loadViewerDocument(viewerPath, pageMode));
}

function normalizePreviewNavigationTarget(viewerPath: string): string | null {
  const raw = String(viewerPath || '').trim();
  if (!raw) {
    return null;
  }
  try {
    const parsed = new URL(raw, window.location.origin);
    const runtimePath = `${parsed.pathname}${parsed.search || ''}${parsed.hash || ''}`;
    if (
      parsed.pathname.startsWith('/playbooks/')
      || parsed.pathname.startsWith('/docs/ocp/')
      || parsed.pathname.startsWith('/wiki/entities/')
      || parsed.pathname.startsWith('/wiki/figures/')
      || parsed.pathname.startsWith('/api/customer-packs/captured')
    ) {
      return normalizeViewerPath(runtimePath);
    }
    if (/^https?:\/\//i.test(raw)) {
      window.open(raw, '_blank', 'noopener,noreferrer');
      return null;
    }
    return normalizeViewerPath(runtimePath);
  } catch {
    return normalizeViewerPath(raw);
  }
}

function buildOverlayTargetFromViewerPath(
  viewerUrl: string,
  fallbackTitle: string,
  userId: string,
): OverlayTargetDescriptor | null {
  const runtimePath = runtimePathFromUrl(viewerUrl);
  const [pathWithQuery, anchorPart] = runtimePath.split('#', 2);
  const [pathOnly, searchPart] = pathWithQuery.split('?', 2);
  const searchParams = new URLSearchParams(searchPart ?? '');
  const anchor = anchorPart?.trim() ?? '';

  const entityMatch = pathOnly.match(/^\/wiki\/entities\/([^/]+)\/index\.html$/);
  if (entityMatch) {
    const entitySlug = entityMatch[1];
    return {
      kind: 'entity_hub',
      ref: `entity:${entitySlug}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: userId,
        target_kind: 'entity_hub',
        entity_slug: entitySlug,
        viewer_path: runtimePath,
      },
    };
  }

  const figureMatch = pathOnly.match(/^\/wiki\/figures\/([^/]+)\/([^/]+)\/index\.html$/);
  if (figureMatch) {
    const [, bookSlug, assetName] = figureMatch;
    return {
      kind: 'figure',
      ref: `figure:${bookSlug}:${assetName}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: userId,
        target_kind: 'figure',
        book_slug: bookSlug,
        asset_name: assetName,
        viewer_path: runtimePath,
      },
    };
  }

  const runtimeBookMatch = pathOnly.match(/^\/playbooks\/wiki-runtime\/active\/([^/]+)\/index\.html$/);
  const officialBookMatch = pathOnly.match(/^\/docs\/ocp\/[^/]+\/[^/]+\/([^/]+)\/index\.html$/);
  const customerPackMatch = pathOnly.match(/^\/playbooks\/customer-packs\/([^/]+)\/index\.html$/);
  const capturedDraftId = pathOnly === '/api/customer-packs/captured'
    ? String(searchParams.get('draft_id') || '').trim()
    : '';
  const bookSlug = runtimeBookMatch?.[1] ?? officialBookMatch?.[1] ?? customerPackMatch?.[1] ?? capturedDraftId;
  if (bookSlug) {
    if (anchor) {
      return {
        kind: 'section',
        ref: `section:${bookSlug}#${anchor}`,
        title: fallbackTitle,
        viewerPath: runtimePath,
        payload: {
          user_id: userId,
          target_kind: 'section',
          book_slug: bookSlug,
          anchor,
          viewer_path: runtimePath,
        },
      };
    }
    return {
      kind: 'book',
      ref: `book:${bookSlug}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: userId,
        target_kind: 'book',
        book_slug: bookSlug,
        viewer_path: runtimePath,
      },
    };
  }

  return null;
}

export default function WorkspacePage() {
  const [manualBooks, setManualBooks] = useState<WorkspaceManualBook[]>([]);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [documentRepositories, setDocumentRepositories] = useState<DocumentRepository[]>([]);
  const [isBootstrapLoading, setIsBootstrapLoading] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState('');
  const [sessionId, setSessionId] = useState(() => makeId('ID'));
  const [testMode, setTestMode] = useState(false);
  const [rightPanelMode, setRightPanelMode] = useState<RightPanelMode>('terminal');
  const [activeTestTrace, setActiveTestTrace] = useState<WorkspaceTestTrace | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<string | null>(() => loadStoredActiveSourceId());
  const [activeDocumentId, setActiveDocumentId] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem(WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY) || '';
  });
  const [activeDocumentTitle, setActiveDocumentTitle] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem(WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY) || '';
  });
  const [activeCategoryKey, setActiveCategoryKey] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY) || '';
  });
  const [activeCategoryLabel, setActiveCategoryLabel] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY) || '';
  });
  const [preview, setPreview] = useState<PreviewState>({ kind: 'empty' });
  const [evidenceDrawer, setEvidenceDrawer] = useState<EvidenceDrawerState>({ kind: 'closed' });
  const [viewerPageMode, setViewerPageMode] = useState<ViewerPageMode>('single');
  const [isPanelResizing, setIsPanelResizing] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isNormalizing, setIsNormalizing] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    manuals: true,
    drafts: true,
    repositories: false,
  });

  // Session history
  const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
  const [isSessionListLoading, setIsSessionListLoading] = useState(true);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [leftPanelMode, setLeftPanelMode] = useState<LeftPanelMode>(() => {
    if (typeof window === 'undefined') return 'history';
    const saved = window.localStorage.getItem('workspace.leftPanelMode');
    if (saved === 'history' || saved === 'outline' || saved === 'signals') {
      return saved;
    }
    return 'history';
  });
  const [visionMode] = useState<VisionMode>(() => loadStoredVisionMode());
  const isGuidedSurface = visionMode === 'guided_tour' || visionMode === 'course_study';
  const isCourseMode = visionMode === 'course_study';

  useEffect(() => {
    if (isCourseMode && testMode) {
      setTestMode(false);
    }
  }, [isCourseMode, testMode]);

  // Scroll + welcome
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const [welcomeQuestionGroups, setWelcomeQuestionGroups] = useState<WelcomeQuestionGroup[]>(EMPTY_WELCOME_QUESTION_GROUPS);
  const [welcomeLearningSequence, setWelcomeLearningSequence] = useState<WelcomeQuestion[]>([]);
  const [isWelcomeQuestionLoading, setIsWelcomeQuestionLoading] = useState(true);
  const [terminalLearningContext, setTerminalLearningContext] = useState<TerminalLearningContext | undefined>(undefined);

  // Collapsible panels
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [sourcesDrawerOpen, setSourcesDrawerOpen] = useState(false);
  const [outlineCategoryKey, setOutlineCategoryKey] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem('workspace.outlineCategoryKey') ?? '';
  });
  const [wikiOverlays, setWikiOverlays] = useState<WikiOverlayRecord[]>([]);
  const [wikiOverlaySignals, setWikiOverlaySignals] = useState<WikiOverlaySignalsResponse | null>(null);
  const [isOverlayLoading, setIsOverlayLoading] = useState(false);
  const [isOverlaySaving, setIsOverlaySaving] = useState(false);
  const [annotationEnabled, setAnnotationEnabled] = useState(false);
  const [annotationTool, setAnnotationTool] = useState<WikiAnnotationTool>('text');
  const [annotationColorId, setAnnotationColorId] = useState<WikiInkColorId>('amber');
  const [textAnnotationMode, setTextAnnotationMode] = useState<WikiTextAnnotationMode>('add');
  const [annotationTextStyle, setAnnotationTextStyle] = useState<WikiEditedTextStyle>(DEFAULT_EDITED_TEXT_STYLE);
  const [quickNavOpen, setQuickNavOpen] = useState(false);
  const [viewerActiveSection, setViewerActiveSection] = useState<ViewerActiveSection | null>(null);
  const [signalsFavoriteFilter, setSignalsFavoriteFilter] = useState<SignalsFavoriteFilter>('favorites');

  const [globalTheme, setGlobalTheme] = useState<'dark' | 'light'>(() => {
    if (typeof window === 'undefined') return 'dark';
    return (window.localStorage.getItem('pbs.globalTheme') as 'dark' | 'light') || 'dark';
  });
  const [opsWorkspaceId, setOpsWorkspaceId] = useState(() => {
    if (typeof window === 'undefined') {
      return 'ws_default';
    }
    return window.localStorage.getItem('opsConsole.activeWorkspaceId') || 'ws_default';
  });
  const [opsConnectionId, setOpsConnectionId] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem('opsConsole.activeConnectionId') || '';
  });
  const [footerConnections, setFooterConnections] = useState<OcpConnection[]>([]);
  const [isFooterProfileLoading, setIsFooterProfileLoading] = useState(false);
  const [currentMode, setCurrentMode] = useState<WorkspaceChatMode>('document');
  const [clusterConnectionStatus, setClusterConnectionStatus] = useState<ClusterConnectionStatus>('not_connected');
  const [terminalConnectionState, setTerminalConnectionState] = useState<TerminalConnectionState>('closed');
  const [selectedResourceKind, setSelectedResourceKind] = useState<ClusterResourceKind>('pods');
  const [selectedResourceNamespace, setSelectedResourceNamespace] = useState('default');
  const [clusterResources, setClusterResources] = useState<OcpResourceItem[]>([]);
  const [isClusterResourceLoading, setIsClusterResourceLoading] = useState(false);
  const [clusterResourceError, setClusterResourceError] = useState('');
  const [resourceYamlDetail, setResourceYamlDetail] = useState<ResourceDetailResponse | null>(null);
  const [isResourceYamlLoading, setIsResourceYamlLoading] = useState(false);
  const [signalEvents, setSignalEvents] = useState<ClusterSignalEvent[]>([]);
  const [recentTerminalActions, setRecentTerminalActions] = useState<RecentTerminalAction[]>([]);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [dashboardOverview, setDashboardOverview] = useState<OcpOverview | null>(null);
  const [dashboardMetrics, setDashboardMetrics] = useState<OcpMetricsResponse | null>(null);
  const [isDashboardLoading, setIsDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState('');
  const [ingestionStatusBanner, setIngestionStatusBanner] = useState<IngestionStatusBanner | null>(() => loadStoredIngestionStatus());

  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const quickNavRef = useRef<HTMLDivElement>(null);
  const leftPanelRef = usePanelRef();
  const rightPanelRef = usePanelRef();

  // Persist + restore panel sizes across reloads.
  const { defaultLayout: savedLayout, onLayoutChanged: handlePanelLayoutChanged } = useDefaultLayout({
    id: 'workspace.panelLayout.v2',
    panelIds: ['workspace-left', 'workspace-center', 'workspace-right'],
    storage: typeof window !== 'undefined' ? window.localStorage : undefined,
  });

  const refreshSessionList = useCallback(async () => {
    setIsSessionListLoading(true);
    try {
      const dbResult = await listDbChatSessions();
      if (dbResult.database === 'postgres') {
        setSessionList(dbResult.sessions.map((session) => ({
          session_id: session.client_session_id,
          session_name: session.title || `Session ${session.client_session_id.slice(0, 8)}`,
          turn_count: Math.ceil(session.message_count / 2),
          updated_at: session.updated_at,
          first_query: session.title,
          history_source: 'db',
        })));
        return;
      }
      const result = await listSessions();
      setSessionList(result.sessions.map((session) => ({ ...session, history_source: 'file' as const })));
    } catch (error) {
      console.error(error);
      try {
        const result = await listSessions();
        setSessionList(result.sessions.map((session) => ({ ...session, history_source: 'file' as const })));
      } catch (fallbackError) {
        console.error(fallbackError);
      }
    } finally {
      setIsSessionListLoading(false);
    }
  }, []);

  const activeFooterConnection = useMemo(
    () => footerConnections.find((item) => item.connection_id === opsConnectionId) ?? footerConnections[0] ?? null,
    [footerConnections, opsConnectionId],
  );
  const footerProfileName = useMemo(() => {
    const username = activeFooterConnection?.username_hint?.trim();
    const displayName = activeFooterConnection?.display_name?.trim();
    return username || displayName || FALLBACK_CLUSTER_USER_LABEL;
  }, [activeFooterConnection]);
  const wikiOverlayUserId = footerProfileName;
  const isClusterConnected = clusterConnectionStatus === 'connected';
  const isTerminalConnected = terminalConnectionState === 'connected';
  const isLiveClusterAvailable = isClusterConnected && isTerminalConnected;
  const clusterStatusLabel =
    clusterConnectionStatus === 'connected'
      ? 'Connected'
      : clusterConnectionStatus === 'connecting'
        ? 'Connecting'
        : clusterConnectionStatus === 'error'
          ? 'Error'
          : 'Not connected';

  const refreshFooterProfile = useCallback(async () => {
    setIsFooterProfileLoading(true);
    try {
      const connections = await listOcpProfiles(opsWorkspaceId);
      setFooterConnections(connections);
      setClusterConnectionStatus(normalizeClusterConnectionStatus(
        connections.find((item) => item.connection_id === opsConnectionId) ?? connections[0] ?? null,
      ));
    } catch (error) {
      console.error(error);
      setClusterConnectionStatus('error');
    } finally {
      setIsFooterProfileLoading(false);
    }
  }, [opsConnectionId, opsWorkspaceId]);

  useEffect(() => {
    if (!activeFooterConnection) {
      setClusterConnectionStatus('not_connected');
      return;
    }
    setClusterConnectionStatus(normalizeClusterConnectionStatus(activeFooterConnection));
    let cancelled = false;
    loadOcpStatus(activeFooterConnection.connection_id)
      .then((connection) => {
        if (cancelled) {
          return;
        }
        setClusterConnectionStatus(normalizeClusterConnectionStatus(connection));
        setFooterConnections((current) => current.map((item) => (
          item.connection_id === connection.connection_id ? { ...item, ...connection } : item
        )));
      })
      .catch((error) => {
        if (!cancelled) {
          console.error(error);
          setClusterConnectionStatus('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeFooterConnection?.connection_id]);

  useEffect(() => {
    if (currentMode === 'live_cluster' && !isLiveClusterAvailable) {
      setCurrentMode('document');
    }
  }, [currentMode, isLiveClusterAvailable]);

  useEffect(() => {
    if (activeFooterConnection?.default_namespace && selectedResourceNamespace === 'default') {
      setSelectedResourceNamespace(activeFooterConnection.default_namespace);
    }
  }, [activeFooterConnection?.default_namespace, selectedResourceNamespace]);

  const refreshClusterResources = useCallback(async () => {
    if (!isClusterConnected || !activeFooterConnection) {
      setClusterResources([]);
      setClusterResourceError('');
      return;
    }
    const namespace = selectedResourceNamespace.trim() || activeFooterConnection.default_namespace || 'default';
    setIsClusterResourceLoading(true);
    setClusterResourceError('');
    try {
      const response = await loadResources(activeFooterConnection.connection_id, selectedResourceKind, namespace);
      setClusterResources(response.items ?? []);
    } catch (error) {
      console.error(error);
      setClusterResources([]);
      setClusterResourceError('Cluster resource list is unavailable.');
    } finally {
      setIsClusterResourceLoading(false);
    }
  }, [
    activeFooterConnection,
    isClusterConnected,
    selectedResourceKind,
    selectedResourceNamespace,
  ]);

  useEffect(() => {
    if (leftPanelMode === 'outline') {
      void refreshClusterResources();
    }
  }, [leftPanelMode, refreshClusterResources]);

  async function openClusterResourceYaml(resource: OcpResourceItem): Promise<void> {
    if (!activeFooterConnection || !isClusterConnected) {
      return;
    }
    const namespace = resource.namespace || selectedResourceNamespace.trim() || activeFooterConnection.default_namespace || 'default';
    setIsResourceYamlLoading(true);
    setClusterResourceError('');
    try {
      const detail = await loadResourceDetail(
        activeFooterConnection.connection_id,
        selectedResourceKind,
        namespace,
        resource.name,
      );
      setResourceYamlDetail(detail);
    } catch (error) {
      console.error(error);
      setClusterResourceError('Resource YAML is unavailable.');
    } finally {
      setIsResourceYamlLoading(false);
    }
  }

  const refreshSignalEvents = useCallback(async () => {
    try {
      const payload = await loadSignals(50);
      if (payload.database === 'postgres') {
        setSignalEvents(payload.items.map(signalEventFromApi));
      }
    } catch (error) {
      console.error(error);
    }
  }, []);

  const handleTerminalCommandSubmitted = useCallback((command: string) => {
    setRecentTerminalActions((current) => [
      { command, timestamp: new Date().toISOString() },
      ...current.filter((item) => item.command !== command),
    ].slice(0, 6));
    const signal = detectClusterSignal(command);
    if (!signal) {
      return;
    }
    setSignalEvents((current) => [{
      ...signal,
      id: makeId('signal'),
      timestamp: new Date().toISOString(),
      status: isClusterConnected ? 'observed' : 'cluster_unverified',
    }, ...current].slice(0, 40));
    setLeftPanelMode('signals');
    window.setTimeout(() => { void refreshSignalEvents(); }, 800);
    if (isClusterConnected) {
      void refreshClusterResources();
    }
  }, [isClusterConnected, refreshClusterResources, refreshSignalEvents]);

  const refreshDashboard = useCallback(async () => {
    if (!activeFooterConnection || !isClusterConnected) {
      setDashboardOverview(null);
      setDashboardMetrics(null);
      setDashboardError('Cluster가 연결되어 있지 않습니다.');
      return;
    }
    const namespace = selectedResourceNamespace.trim() || activeFooterConnection.default_namespace || 'default';
    setIsDashboardLoading(true);
    setDashboardError('');
    try {
      const [overview, metrics] = await Promise.all([
        loadOcpOverview(activeFooterConnection.connection_id),
        loadOcpMetrics(activeFooterConnection.connection_id, namespace),
      ]);
      setDashboardOverview(overview);
      setDashboardMetrics(metrics);
    } catch (error) {
      console.error(error);
      setDashboardOverview(null);
      setDashboardMetrics(null);
      setDashboardError('Cluster dashboard data is unavailable.');
    } finally {
      setIsDashboardLoading(false);
    }
  }, [activeFooterConnection, isClusterConnected, selectedResourceNamespace]);

  useEffect(() => {
    if (dashboardOpen) {
      void refreshDashboard();
    }
  }, [dashboardOpen, refreshDashboard]);

  useEffect(() => {
    void refreshSignalEvents();
  }, [refreshSignalEvents]);

  useEffect(() => {
    if (!ingestionStatusBanner?.repositoryId && !ingestionStatusBanner?.documentSourceId) {
      return;
    }
    let cancelled = false;
    const refreshStatus = async () => {
      try {
        const payload = await loadDocumentIngestStatus({
          repositoryId: ingestionStatusBanner.repositoryId,
          documentSourceId: ingestionStatusBanner.documentSourceId,
        });
        const latest = payload.latest;
        if (!latest || cancelled) {
          return;
        }
        const nextBanner: IngestionStatusBanner = {
          status: latest.ready ? 'ready' : latest.status === 'failed' ? 'failed' : 'indexing',
          message: latest.message,
          filename: latest.original_filename || latest.title,
          repositoryId: latest.repository_id,
          documentSourceId: latest.document_source_id,
          updatedAt: latest.updated_at,
        };
        setIngestionStatusBanner(nextBanner);
        window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify(nextBanner));
      } catch (error) {
        console.error(error);
      }
    };
    void refreshStatus();
    return () => {
      cancelled = true;
    };
  }, [ingestionStatusBanner?.documentSourceId, ingestionStatusBanner?.repositoryId]);

  const refreshWikiOverlays = useCallback(async () => {
    setIsOverlayLoading(true);
    try {
      const [overlayResult, signalResult] = await Promise.all([
        loadWikiOverlays(wikiOverlayUserId),
        loadWikiOverlaySignals(wikiOverlayUserId),
      ]);
      setWikiOverlays(overlayResult.items ?? []);
      setWikiOverlaySignals(signalResult);
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlayLoading(false);
    }
  }, [wikiOverlayUserId]);

  const learningQuestionByText = useMemo(() => {
    const pairs = welcomeLearningSequence
      .filter((item) => typeof item.learningIndex === 'number')
      .map((item) => [item.question, item] as const);
    return new Map<string, WelcomeQuestion>(pairs);
  }, [welcomeLearningSequence]);
  const leftPanelLabels = useMemo(() => ({
    history: isGuidedSurface ? 'Journey' : 'History',
    outline: isGuidedSurface ? 'Route Map' : 'Outline',
    signals: isGuidedSurface ? 'Signals' : 'Signals',
    historyTitle: isGuidedSurface ? 'Tour Journey' : 'Chat History',
    outlineTitle: isGuidedSurface ? 'Tour Map' : 'Document Outline',
    signalsTitle: isGuidedSurface ? 'Tour Signals' : 'Reader Signals',
  }), [isGuidedSurface]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('workspace.leftPanelMode', leftPanelMode);
  }, [leftPanelMode]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('workspace.outlineCategoryKey', outlineCategoryKey);
  }, [outlineCategoryKey]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (activeSourceId) {
      window.localStorage.setItem(WORKSPACE_ACTIVE_SOURCE_STORAGE_KEY, activeSourceId);
    } else {
      window.localStorage.removeItem(WORKSPACE_ACTIVE_SOURCE_STORAGE_KEY);
    }
  }, [activeSourceId]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (activeDocumentId) {
      window.localStorage.setItem(WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY, activeDocumentId);
    } else {
      window.localStorage.removeItem(WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY);
    }
  }, [activeDocumentId]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (activeDocumentTitle) {
      window.localStorage.setItem(WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY, activeDocumentTitle);
    } else {
      window.localStorage.removeItem(WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY);
    }
  }, [activeDocumentTitle]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (activeCategoryKey) {
      window.localStorage.setItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY, activeCategoryKey);
    } else {
      window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY);
    }
  }, [activeCategoryKey]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (activeCategoryLabel) {
      window.localStorage.setItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY, activeCategoryLabel);
    } else {
      window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY);
    }
  }, [activeCategoryLabel]);

  useEffect(() => {
    let cancelled = false;
    async function loadWelcomeQuestions(): Promise<void> {
      setIsWelcomeQuestionLoading(true);
      try {
        const payload = await loadStudioStarterQuestions();
        if (cancelled) {
          return;
        }
        const groups = (payload.groups || [])
          .map(normalizeWelcomeQuestionGroup)
          .filter((item): item is WelcomeQuestionGroup => Boolean(item));
        const learningSequence = (payload.learning_sequence || [])
          .map(normalizeWelcomeQuestion)
          .filter((item): item is WelcomeQuestion => Boolean(item));
        setWelcomeQuestionGroups(groups);
        setWelcomeLearningSequence(learningSequence);
      } catch (error) {
        console.error(error);
        if (!cancelled) {
          setWelcomeQuestionGroups(EMPTY_WELCOME_QUESTION_GROUPS);
          setWelcomeLearningSequence([]);
        }
      } finally {
        if (!cancelled) {
          setIsWelcomeQuestionLoading(false);
        }
      }
    }
    void loadWelcomeQuestions();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }
    let resizePointerId: number | null = null;
    let releaseTimer = 0;

    const finishResize = (): void => {
      resizePointerId = null;
      window.clearTimeout(releaseTimer);
      releaseTimer = window.setTimeout(() => setIsPanelResizing(false), 80);
    };

    const handlePointerDown = (event: PointerEvent): void => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest('.custom-resize-handle')) {
        return;
      }
      resizePointerId = event.pointerId;
      window.clearTimeout(releaseTimer);
      setIsPanelResizing(true);
    };

    const handlePointerUp = (event: PointerEvent): void => {
      if (resizePointerId === null || event.pointerId === resizePointerId) {
        finishResize();
      }
    };

    const handleWindowBlur = (): void => finishResize();

    window.addEventListener('pointerdown', handlePointerDown, true);
    window.addEventListener('pointerup', handlePointerUp, true);
    window.addEventListener('pointercancel', handlePointerUp, true);
    window.addEventListener('blur', handleWindowBlur);

    return () => {
      window.clearTimeout(releaseTimer);
      window.removeEventListener('pointerdown', handlePointerDown, true);
      window.removeEventListener('pointerup', handlePointerUp, true);
      window.removeEventListener('pointercancel', handlePointerUp, true);
      window.removeEventListener('blur', handleWindowBlur);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }
    const syncOpsContext = () => {
      setOpsWorkspaceId(window.localStorage.getItem('opsConsole.activeWorkspaceId') || 'ws_default');
      setOpsConnectionId(window.localStorage.getItem('opsConsole.activeConnectionId') || '');
    };
    syncOpsContext();
    window.addEventListener('focus', syncOpsContext);
    window.addEventListener('storage', syncOpsContext);
    return () => {
      window.removeEventListener('focus', syncOpsContext);
      window.removeEventListener('storage', syncOpsContext);
    };
  }, []);

  // Track user scroll-up via wheel only (not programmatic scroll)
  useEffect(() => {
    if (isCourseMode) {
      return;
    }
    void refreshWikiOverlays();
  }, [isCourseMode, refreshWikiOverlays]);

  useEffect(() => {
    if (isCourseMode) {
      return;
    }
    void refreshFooterProfile();
  }, [isCourseMode, refreshFooterProfile]);

  useEffect(() => {
    const el = chatMessagesRef.current;
    if (!el) return;

    let frameId = 0;
    let lastLocked = userScrolledUp;
    function syncScrollLock(): void {
      frameId = 0;
      if (!el) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      const nextLocked = !atBottom;
      if (nextLocked !== lastLocked) {
        lastLocked = nextLocked;
        setUserScrolledUp(nextLocked);
      }
      el.classList.toggle('scroll-locked', nextLocked);
    }

    function handleScroll(): void {
      if (frameId) {
        return;
      }
      frameId = requestAnimationFrame(syncScrollLock);
    }

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      el.removeEventListener('scroll', handleScroll);
    };
  }, [userScrolledUp]);

  function scrollToBottom(): void {
    const el = chatMessagesRef.current;
    if (el) {
      el.classList.remove('scroll-locked');
      setUserScrolledUp(false);
      el.scrollTo({ top: el.scrollHeight, behavior: 'auto' });
    }
  }

  function resetSession() {
    setSessionId(makeId('ID'));
    setMessages([]);
    setUserScrolledUp(false);
    void refreshSessionList();
  }

  async function handleSessionResume(targetSessionId: string): Promise<void> {
    if (isLoadingSession) return;
    setIsLoadingSession(true);
    try {
      const summary = sessionList.find((session) => session.session_id === targetSessionId);
      if (summary?.history_source === 'db') {
        const history = await loadDbChatMessages(targetSessionId);
        setSessionId(targetSessionId);
        setMessages(history.messages.map((message) => {
          const metadata = message.metadata || {};
          const citations = Array.isArray(metadata.citations)
            ? metadata.citations.filter((item): item is ChatCitation => typeof item === 'object' && item !== null)
            : [];
          return {
            id: message.message_id || makeId(message.role === 'user' ? 'u' : 'a'),
            role: message.role === 'assistant' ? 'assistant' as const : 'user' as const,
            content: message.content,
            citations,
            responseKind: typeof metadata.response_kind === 'string' ? metadata.response_kind : undefined,
            rewrittenQuery: typeof metadata.rewritten_query === 'string' ? metadata.rewritten_query : undefined,
          };
        }));
        return;
      }
      const snapshot = await loadSession(targetSessionId);
      setSessionId(snapshot.session_id);
      setMessages(
        (snapshot.turns ?? []).flatMap((turn) => [
          { id: makeId('u'), role: 'user' as const, content: turn.query },
          {
            id: makeId('a'),
            role: 'assistant' as const,
            content: turn.answer,
            primarySourceLane: turn.primary_source_lane,
            primaryBoundaryTruth: turn.primary_boundary_truth,
            primaryRuntimeTruthLabel: turn.primary_runtime_truth_label,
            primaryBoundaryBadge: turn.primary_boundary_badge,
            primaryPublicationState: turn.primary_publication_state,
            primaryApprovalState: turn.primary_approval_state,
          },
        ]),
      );
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoadingSession(false);
    }
  }

  async function handleSessionDelete(targetSessionId: string): Promise<void> {
    if (deletingSessionId || isLoadingSession) {
      return;
    }
    const summary = sessionList.find((session) => session.session_id === targetSessionId);
    const confirmed = window.confirm('이 대화 기록을 삭제할까요?');
    if (!confirmed) {
      return;
    }
    setDeletingSessionId(targetSessionId);
    try {
      if (summary?.history_source === 'db') {
        await archiveDbChatSession(targetSessionId);
      } else {
        await deleteSession(targetSessionId);
      }
      setSessionList((current) => current.filter((session) => session.session_id !== targetSessionId));
      if (targetSessionId === sessionId) {
        setSessionId(makeId('ID'));
        setMessages([]);
      }
      await refreshSessionList();
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '대화 기록 삭제 중 오류가 발생했습니다.');
    } finally {
      setDeletingSessionId(null);
    }
  }

  async function handleDeleteAllSessions(): Promise<void> {
    if (deletingSessionId || isLoadingSession || sessionList.length === 0) {
      return;
    }
    const confirmed = window.confirm('대화 기록을 전체 삭제할까요?');
    if (!confirmed) {
      return;
    }
    setDeletingSessionId('__all__');
    try {
      await deleteAllSessions();
      setSessionList([]);
      setSessionId(makeId('ID'));
      setMessages([]);
      await refreshSessionList();
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '전체 대화 기록 삭제 중 오류가 발생했습니다.');
    } finally {
      setDeletingSessionId(null);
    }
  }

  function toggleLeftPanel(): void {
    const panel = leftPanelRef.current;
    if (!panel) return;
    if (leftCollapsed) {
      panel.expand();
      setLeftCollapsed(false);
    } else {
      panel.collapse();
      setLeftCollapsed(true);
    }
  }

  function toggleRightPanel(): void {
    const panel = rightPanelRef.current;
    if (!panel) return;
    if (rightCollapsed) {
      panel.expand();
      setRightCollapsed(false);
    } else {
      panel.collapse();
      setRightCollapsed(true);
    }
  }

  // Close the Sources overlay with Esc
  useEffect(() => {
    if (!sourcesDrawerOpen) return undefined;
    const handleKey = (event: globalThis.KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setSourcesDrawerOpen(false);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [sourcesDrawerOpen]);

  useEffect(() => {
    const container = chatMessagesRef.current;
    if (messages.length > 0 && container && !userScrolledUp) {
      requestAnimationFrame(() => {
        try {
          container.scrollTo({
            top: container.scrollHeight,
            behavior: 'auto'
          });
        } catch {
          // ignore
        }
      });
    }
  }, [messages, userScrolledUp]);

  useEffect(() => {
    if (!testMode || userScrolledUp) {
      return;
    }
    const container = chatMessagesRef.current;
    if (!container) {
      return;
    }
    requestAnimationFrame(() => {
      try {
        container.scrollTo({
          top: container.scrollHeight,
          behavior: 'auto',
        });
      } catch {
        container.scrollTop = container.scrollHeight;
      }
    });
  }, [testMode, activeTestTrace?.events.length, activeTestTrace?.result?.answer, userScrolledUp]);

  useEffect(() => {
    let animated = false;
    const ctx = gsap.context(() => {
      if (animated) return;

      const panels = containerRef.current?.querySelectorAll('.workspace-panel-item');
      if (panels && panels.length > 0) {
        gsap.from(panels, {
          opacity: 0,
          y: 20,
          stagger: 0.1,
          duration: 0.8,
          ease: 'power3.out',
          delay: 0.3,
        });
        animated = true;
      }
    }, containerRef);
    return () => ctx.revert();
  }, []);

  function toggleSection(sectionId: string): void {
    setCollapsedSections((prev) => ({
      ...prev,
      [sectionId]: !prev[sectionId],
    }));
  }

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      if (isCourseMode) {
        setManualBooks([]);
        setDrafts([]);
        setIsBootstrapLoading(false);
        return;
      }
      setIsBootstrapLoading(true);
      try {
        void refreshSessionList();
        const [room, draftPayload, repositoryPayload] = await Promise.all([
          loadDataControlRoom(),
          listCustomerPackDrafts(),
          loadDocumentRepositories().catch(() => ({ repositories: [] })),
        ]);
        if (cancelled) {
          return;
        }

        const sourceBooks = resolveWorkspaceSourceBooks(room) as WorkspaceManualBook[];
        const nextDrafts = draftPayload.drafts ?? [];

        setManualBooks(sourceBooks);
        setDrafts(nextDrafts);
        setDocumentRepositories(repositoryPayload.repositories ?? []);
      } catch (error) {
        console.error(error);
      } finally {
        if (!cancelled) {
          setIsBootstrapLoading(false);
        }
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [isCourseMode, refreshSessionList]);

  const manualSources = useMemo<SourceEntry[]>(
    () =>
      manualBooks.map((book) => ({
        id: `manual:${book.book_slug}`,
        kind: 'manual',
        name: book.title,
        meta: summarizeBookMeta(book),
        grade: book.grade,
        viewerPath: book.viewer_path,
        book,
      })),
    [manualBooks],
  );

  const draftSources = useMemo<SourceEntry[]>(
    () =>
      drafts.map((draft) => ({
        id: `draft:${draft.draft_id}`,
        kind: 'draft',
        name: draft.title,
        meta: formatDraftMeta(draft),
        draft,
      })),
    [drafts],
  );

  const repositorySources = useMemo<SourceEntry[]>(
    () =>
      documentRepositories.map((repository) => ({
        id: `repository:${repository.repository_id}`,
        kind: 'repository',
        name: repository.title || repository.slug || 'Document Repository',
        meta: `${repository.visibility || 'repository'} · ${repository.document_count} docs`,
        repository,
      })),
    [documentRepositories],
  );

  const activeDraft = useMemo(
    () => drafts.find((draft) => activeSourceId === `draft:${draft.draft_id}`) ?? null,
    [activeSourceId, drafts],
  );

  const activeRepository = useMemo(
    () => documentRepositories.find((repository) => activeSourceId === `repository:${repository.repository_id}`) ?? null,
    [activeSourceId, documentRepositories],
  );

  const activeRepositoryDocument = useMemo(
    () => activeRepository?.documents?.find((document) => document.document_source_id === activeDocumentId) ?? null,
    [activeDocumentId, activeRepository],
  );

  const activeNextLearningDocuments = useMemo(() => {
    if (!activeRepository || !activeRepositoryDocument) {
      return [] as DocumentRepositoryDocument[];
    }
    const learning = workspaceMetadataRecord(activeRepositoryDocument.metadata?.learning);
    const nextRefs = Array.isArray(learning.next_refs) ? learning.next_refs : [];
    const documents = activeRepository.documents ?? [];
    return nextRefs
      .map((ref) => {
        const record = workspaceMetadataRecord(ref);
        const bookSlug = workspaceMetadataString(record, 'book_slug');
        const documentSourceId = workspaceMetadataString(record, 'document_source_id');
        return documents.find((document) => {
          const metadata = document.metadata ?? {};
          return (
            (documentSourceId && document.document_source_id === documentSourceId)
            || (bookSlug && workspaceMetadataString(metadata, 'book_slug') === bookSlug)
          );
        }) ?? null;
      })
      .filter((document): document is DocumentRepositoryDocument => Boolean(document))
      .slice(0, 3);
  }, [activeRepository, activeRepositoryDocument]);

  const activeDocumentScopeLabel = activeDocumentId
    ? activeRepositoryDocument?.title || activeRepositoryDocument?.filename || activeDocumentTitle || 'Scoped document'
    : '';

  const selectActiveDocumentScope = useCallback((document: DocumentRepositoryDocument) => {
    setActiveDocumentId(document.document_source_id);
    setActiveDocumentTitle(document.title || document.filename || 'Scoped document');
    const categoryKey = workspaceMetadataString(document.metadata, 'category_key');
    const categoryLabel = workspaceMetadataString(document.metadata, 'category_label');
    setActiveCategoryKey(categoryKey);
    setActiveCategoryLabel(categoryLabel || categoryKey);
  }, []);

  const clearActiveDocumentScope = useCallback(() => {
    setActiveDocumentId('');
    setActiveDocumentTitle('');
    setActiveCategoryKey('');
    setActiveCategoryLabel('');
  }, []);

  const clearActiveRepositoryScope = useCallback(() => {
    setActiveSourceId(null);
    setActiveDocumentId('');
    setActiveDocumentTitle('');
    setActiveCategoryKey('');
    setActiveCategoryLabel('');
  }, []);

  const currentViewerPath = useMemo(
    () => {
      if (preview.kind === 'viewer') {
        return preview.meta?.viewer_path || runtimePathFromUrl(preview.viewerUrl);
      }
      if (preview.kind === 'draft' && preview.viewerUrl) {
        return runtimePathFromUrl(preview.viewerUrl);
      }
      return '';
    },
    [preview],
  );

  const viewerOriginalSourceHref = useMemo(() => {
    if (preview.kind !== 'viewer') {
      return '';
    }
    const sourceUrl = String(preview.meta?.source_url || '').trim();
    return sourceUrl ? toRuntimeUrl(sourceUrl) : '';
  }, [preview]);

  const quickNavItems = useMemo(
    () => (preview.kind === 'viewer' && preview.viewerDocument?.html && currentViewerPath
      ? extractViewerQuickNavItems(preview.viewerDocument.html, currentViewerPath)
      : []),
    [currentViewerPath, preview],
  );

  const currentOverlayTarget = useMemo<OverlayTargetDescriptor | null>(() => {
    if ((preview.kind !== 'viewer' && preview.kind !== 'draft') || !preview.viewerUrl) {
      return null;
    }
    if (preview.kind === 'viewer' && viewerPageMode === 'multi' && preview.viewerDocument?.html) {
      const visibleSection = viewerActiveSection ?? extractVisibleViewerSection(preview.viewerDocument.html);
      if (visibleSection && currentViewerPath) {
        const sectionViewerPath = `${currentViewerPath.split('#', 1)[0]}#${visibleSection.anchor}`;
        return buildOverlayTargetFromViewerPath(sectionViewerPath, visibleSection.title, wikiOverlayUserId);
      }
    }
    return buildOverlayTargetFromViewerPath(preview.viewerUrl, preview.title, wikiOverlayUserId);
  }, [currentViewerPath, preview, viewerActiveSection, viewerPageMode, wikiOverlayUserId]);

  const favoriteOverlays = useMemo(
    () => wikiOverlays.filter((item) => item.kind === 'favorite'),
    [wikiOverlays],
  );
  const recentPositionOverlays = useMemo(
    () => wikiOverlays.filter((item) => item.kind === 'recent_position'),
    [wikiOverlays],
  );
  const noteOverlays = useMemo(
    () => wikiOverlays.filter((item) => item.kind === 'note'),
    [wikiOverlays],
  );
  const inkOverlays = useMemo(
    () => wikiOverlays.filter((item) => item.kind === 'ink'),
    [wikiOverlays],
  );
  const editedCardOverlays = useMemo(
    () => wikiOverlays.filter((item) => item.kind === 'edited_card'),
    [wikiOverlays],
  );
  const editedCardOverlayByTarget = useMemo(
    () => new Map(editedCardOverlays.map((item) => [item.target_ref, item])),
    [editedCardOverlays],
  );
  const noteOverlayByTarget = useMemo(
    () => new Map(noteOverlays.map((item) => [item.target_ref, item])),
    [noteOverlays],
  );
  const inkOverlayByTarget = useMemo(
    () => new Map(inkOverlays.map((item) => [item.target_ref, item])),
    [inkOverlays],
  );
  const currentPreviewBookSlug = useMemo(() => {
    if (preview.kind === 'viewer') {
      return String(preview.meta?.book_slug || '').trim();
    }
    return '';
  }, [preview]);
  const sectionTextAnnotationsByAnchor = useMemo<Record<string, WikiTextAnnotation[]>>(() => {
    if (!currentPreviewBookSlug) {
      return {};
    }
    const next: Record<string, WikiTextAnnotation[]> = {};
    editedCardOverlays.forEach((item) => {
      if (item.target_kind !== 'section' || item.book_slug !== currentPreviewBookSlug) {
        return;
      }
      const anchor = String(item.source_anchor || overlayAnchorFromTargetRef(item.target_ref)).trim();
      const annotations = extractTextAnnotations(item, anchor);
      if (anchor && annotations.length > 0) {
        next[anchor] = annotations;
      }
    });
    noteOverlays.forEach((item) => {
      if (item.target_kind !== 'section' || item.book_slug !== currentPreviewBookSlug) {
        return;
      }
      const anchor = overlayAnchorFromTargetRef(item.target_ref);
      if (!anchor || next[anchor]?.length) {
        return;
      }
      const annotations = extractTextAnnotations(item, anchor);
      if (annotations.length > 0) {
        next[anchor] = annotations;
      }
    });
    return next;
  }, [currentPreviewBookSlug, editedCardOverlays, noteOverlays]);
  const personalizedNextPlays = useMemo<WikiOverlayRecommendedPlay[]>(
    () => wikiOverlaySignals?.user_focus?.recommended_next_plays ?? [],
    [wikiOverlaySignals],
  );

  const currentFavorite = useMemo(
    () => favoriteOverlays.find((item) => item.target_ref === currentOverlayTarget?.ref) ?? null,
    [currentOverlayTarget, favoriteOverlays],
  );
  const currentSectionCheck = useMemo(
    () =>
      wikiOverlays.find(
        (item) => item.kind === 'check' && item.target_ref === currentOverlayTarget?.ref,
      ) ?? null,
    [currentOverlayTarget, wikiOverlays],
  );
  const currentLegacyInk = useMemo(
    () => (currentOverlayTarget ? inkOverlayByTarget.get(currentOverlayTarget.ref) ?? null : null),
    [currentOverlayTarget, inkOverlayByTarget],
  );
  const currentEditedCard = useMemo(
    () => (currentOverlayTarget ? editedCardOverlayByTarget.get(currentOverlayTarget.ref) ?? null : null),
    [currentOverlayTarget, editedCardOverlayByTarget],
  );
  const currentInkStrokes = useMemo<WikiInkStroke[]>(
    () => currentEditedCard?.strokes ?? currentLegacyInk?.strokes ?? [],
    [currentEditedCard?.strokes, currentLegacyInk?.strokes],
  );

  function mergeDraft(nextDraft: CustomerPackDraft, currentDrafts: CustomerPackDraft[] = drafts): CustomerPackDraft[] {
    return [nextDraft, ...currentDrafts.filter((draft) => draft.draft_id !== nextDraft.draft_id)];
  }

  async function openViewerPreview(
    viewerPath: string,
    title: string,
    sourceId?: string,
    pageMode: ViewerPageMode = viewerPageMode,
    scrollTargetText = '',
  ): Promise<void> {
    const normalizedViewerPath = normalizePreviewNavigationTarget(viewerPath);
    if (!normalizedViewerPath) {
      setPreview({ kind: 'empty' });
      return;
    }
    setActiveSourceId(sourceId ?? `viewer:${normalizedViewerPath}`);
    setPreview({ kind: 'loading', title });
    try {
      const meta = await loadSourceMeta(normalizedViewerPath);
      const resolvedViewerPath = meta.viewer_path || normalizedViewerPath;
      const viewerUrl = toRuntimeUrl(resolvedViewerPath);
      const viewerDocument = await loadViewerDocumentPayload(resolvedViewerPath, pageMode);
      setPreview({
        kind: 'viewer',
        title: meta.book_title || title,
        subtitle: meta.section_path_label || meta.section || meta.source_url || '',
        meta,
        viewerUrl,
        viewerDocument,
        scrollTargetText,
      });
    } catch (error) {
      console.error('viewer-preview-failed', {
        viewerPath: normalizedViewerPath,
        error,
      });
      setPreview({
        kind: 'viewer',
        title,
        subtitle: '',
        viewerUrl: toRuntimeUrl(normalizedViewerPath),
        scrollTargetText,
      });
    }
  }

  async function handleViewerPageModeChange(nextMode: ViewerPageMode): Promise<void> {
    if (nextMode === viewerPageMode) {
      return;
    }
    setViewerPageMode(nextMode);
    if (preview.kind !== 'viewer') {
      return;
    }
    const targetViewerPath = preview.meta?.viewer_path || runtimePathFromUrl(preview.viewerUrl);
    await openViewerPreview(targetViewerPath, preview.title, activeSourceId ?? undefined, nextMode, preview.scrollTargetText);
  }

  async function openManualPreview(book: LibraryBook): Promise<void> {
    await openViewerPreview(book.viewer_path, book.title, `manual:${book.book_slug}`);
  }

  async function openDraftPreview(
    draftId: string,
    currentDrafts: CustomerPackDraft[] = drafts,
    preferredViewerPath = '',
  ): Promise<void> {
    setActiveSourceId(`draft:${draftId}`);
    setPreview({ kind: 'loading', title: 'Customer Pack' });

    const loadedDraft = await loadCustomerPackDraft(draftId);
    const mergedDrafts = mergeDraft(loadedDraft, currentDrafts);
    setDrafts(mergedDrafts);

    let loadedBook: CustomerPackBook | undefined;
    let viewerUrl = '';

    if (loadedDraft.status === 'normalized') {
      loadedBook = await loadCustomerPackBook(draftId);
      viewerUrl = toRuntimeUrl(preferredViewerPath || loadedBook.target_viewer_path);
    } else if (loadedDraft.capture_artifact_path) {
      viewerUrl = toRuntimeUrl(`/api/customer-packs/captured?draft_id=${encodeURIComponent(draftId)}`);
    }

    const viewerDocument = viewerUrl
      ? await loadViewerDocumentPayload(runtimePathFromUrl(viewerUrl), 'single')
      : undefined;

    setPreview({
      kind: 'draft',
      title: loadedDraft.title,
      subtitle: `${loadedDraft.pack_label} · ${truthSurfaceCopy(loadedBook ?? loadedDraft).label} · ${loadedDraft.quality_status}`,
      draft: loadedDraft,
      book: loadedBook,
      viewerUrl,
      derivedAssets: loadedBook?.derived_assets ?? loadedDraft.derived_assets ?? [],
      viewerDocument,
    });
  }

  useEffect(() => {
    const nextTone = annotationColorIdToTone(annotationColorId);
    setAnnotationTextStyle((current) => (
      current.tone === nextTone
        ? current
        : { ...current, tone: nextTone }
    ));
  }, [annotationColorId]);

  useEffect(() => {
    if (preview.kind !== 'viewer' || viewerPageMode !== 'multi') {
      setViewerActiveSection(null);
      setAnnotationEnabled(false);
      return;
    }
    setViewerActiveSection((current) => {
      if (currentViewerPath.includes('#')) {
        const anchor = currentViewerPath.split('#').slice(1).join('#').trim();
        if (anchor && current?.anchor !== anchor) {
          return { anchor, title: current?.title || anchor };
        }
      }
      return current;
    });
  }, [currentViewerPath, preview.kind, viewerPageMode]);

  useEffect(() => {
    setQuickNavOpen(false);
  }, [currentViewerPath, viewerPageMode]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    document.documentElement.setAttribute('data-theme', globalTheme);
    window.localStorage.setItem('pbs.globalTheme', globalTheme);
  }, [globalTheme]);

  const handleToggleGlobalTheme = useCallback(() => {
    setGlobalTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  useEffect(() => {
    if (!quickNavOpen) {
      return undefined;
    }
    function handleWindowPointerDown(event: MouseEvent): void {
      const target = event.target as HTMLElement | null;
      if (!target?.closest('.viewer-quick-nav')) {
        setQuickNavOpen(false);
      }
    }
    window.addEventListener('mousedown', handleWindowPointerDown);
    return () => {
      window.removeEventListener('mousedown', handleWindowPointerDown);
    };
  }, [quickNavOpen]);

  useEffect(() => {
    if (!currentOverlayTarget) {
      return;
    }
    if (currentOverlayTarget.kind === 'entity_hub' || currentOverlayTarget.kind === 'book' || currentOverlayTarget.kind === 'section' || currentOverlayTarget.kind === 'figure') {
      const timer = window.setTimeout(() => {
        void saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'recent_position',
          ...currentOverlayTarget.payload,
        })
          .catch((error) => console.error(error));
      }, 1500);
      return () => window.clearTimeout(timer);
    }
    return;
  }, [currentOverlayTarget, wikiOverlayUserId]);

  function resetParentScroll(): void {
    requestAnimationFrame(() => {
      containerRef.current?.scrollTo(0, 0);
      const content = containerRef.current?.querySelector('.workspace-content');
      if (content) { content.scrollTop = 0; content.scrollLeft = 0; }
      const group = containerRef.current?.querySelector('.main-panel-group');
      if (group) { (group as HTMLElement).scrollTop = 0; }
    });
  }

  function animatePreviewPanel(): void {
    resetParentScroll();
    gsap.fromTo(
      '.source-viewer-content',
      { backgroundColor: 'rgba(0, 209, 255, 0.08)' },
      { backgroundColor: 'transparent', duration: 0.8 },
    );
  }

  async function handleSourceClick(source: SourceEntry): Promise<void> {
    try {
      if (source.kind === 'manual' && source.book) {
        await openManualPreview(source.book);
      }
      if (source.kind === 'draft' && source.draft) {
        await openDraftPreview(source.draft.draft_id);
      }
      if (source.kind === 'repository' && source.repository) {
        setActiveSourceId(source.id);
        setPreview({ kind: 'empty' });
      }
      animatePreviewPanel();
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '문서를 여는 중 오류가 발생했습니다.');
    }
  }

  async function openEvidenceDrawerPath(title: string, rawViewerPath: string, scrollTargetText = ''): Promise<void> {
    const viewerPath = normalizeViewerPath(rawViewerPath);
    if (!viewerPath) {
      setEvidenceDrawer({ kind: 'error', title, message: 'No viewer path is available for this citation.' });
      return;
    }
    setEvidenceDrawer({ kind: 'loading', title });
    try {
      const [meta, viewerDocument] = await Promise.all([
        loadSourceMeta(viewerPath).catch(() => null),
        loadViewerDocumentPayload(viewerPath, 'single'),
      ]);
      setEvidenceDrawer({
        kind: 'viewer',
        title,
        subtitle: meta?.section_path_label || meta?.section || viewerPath,
        viewerPath,
        viewerDocument,
        scrollTargetText,
      });
    } catch (error) {
      console.error(error);
      setEvidenceDrawer({
        kind: 'error',
        title,
        message: error instanceof Error ? error.message : 'Failed to load citation evidence.',
      });
    }
  }

  async function openCitationEvidenceDrawer(citation: ChatCitation, answerContent = ''): Promise<void> {
    await openEvidenceDrawerPath(
      citationEvidenceTitle(citation),
      citation.viewer_path,
      citationScrollTarget(citation, answerContent) || firstCitationCommand(citation),
    );
  }

  function handleCitationEvidenceToggle(messageId: string, citation: ChatCitation): void {
    setMessages((current) => current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      const nextIndex = message.activeCitationIndex === citation.index ? undefined : citation.index;
      return { ...message, activeCitationIndex: nextIndex };
    }));
  }

  async function handleRelatedLinkClick(link: ChatRelatedLink): Promise<void> {
    try {
      if (rightCollapsed) {
        rightPanelRef.current?.expand();
        setRightCollapsed(false);
      }
      await openViewerPreview(link.href, link.label);
      if (!isCourseMode) {
        animatePreviewPanel();
      }
    } catch (error) {
      console.error(error);
    }
  }

  function overlayTargetFromLink(link: ChatRelatedLink): OverlayTargetDescriptor | null {
    return buildOverlayTargetFromViewerPath(toRuntimeUrl(link.href), link.label, wikiOverlayUserId);
  }

  function overlayExists(kind: 'favorite' | 'check', targetRef: string): WikiOverlayRecord | null {
    return wikiOverlays.find((item) => item.kind === kind && item.target_ref === targetRef) ?? null;
  }

  async function handleToggleFavoriteCurrent(): Promise<void> {
    if (!currentOverlayTarget) {
      return;
    }
    setIsOverlaySaving(true);
    try {
      if (currentFavorite) {
        await removeWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'favorite',
          target_ref: currentFavorite.target_ref,
        });
      } else {
        await saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'favorite',
          title: currentOverlayTarget.title,
          summary: preview.kind === 'viewer' ? preview.subtitle : '',
          ...currentOverlayTarget.payload,
        });
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleToggleFavoriteLink(link: ChatRelatedLink): Promise<void> {
    const target = overlayTargetFromLink(link);
    if (!target) {
      return;
    }
    setIsOverlaySaving(true);
    try {
      const existing = overlayExists('favorite', target.ref);
      if (existing) {
        await removeWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'favorite',
          target_ref: existing.target_ref,
        });
      } else {
        await saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'favorite',
          title: link.label,
          summary: link.summary ?? '',
          ...target.payload,
        });
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleToggleSectionCheckCurrent(): Promise<void> {
    if (!currentOverlayTarget || currentOverlayTarget.kind !== 'section') {
      return;
    }
    setIsOverlaySaving(true);
    try {
      if (currentSectionCheck) {
        await removeWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'check',
          target_ref: currentSectionCheck.target_ref,
        });
      } else {
        await saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'check',
          status: 'checked',
          ...currentOverlayTarget.payload,
        });
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleToggleSectionCheckLink(link: ChatRelatedLink): Promise<void> {
    const target = overlayTargetFromLink(link);
    if (!target || target.kind !== 'section') {
      return;
    }
    setIsOverlaySaving(true);
    try {
      const existing = overlayExists('check', target.ref);
      if (existing) {
        await removeWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'check',
          target_ref: existing.target_ref,
        });
      } else {
        await saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'check',
          status: 'checked',
          ...target.payload,
        });
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  function buildSectionOverlayTarget(anchor: string, title: string): OverlayTargetDescriptor | null {
    const normalizedAnchor = String(anchor || '').trim();
    if (!normalizedAnchor) {
      return null;
    }
    const baseViewerPath = currentViewerPath
      ? currentViewerPath.split('#', 1)[0]
      : preview.kind === 'viewer' || preview.kind === 'draft'
        ? runtimePathFromUrl(preview.viewerUrl).split('#', 1)[0]
        : '';
    if (!baseViewerPath) {
      return null;
    }
    return buildOverlayTargetFromViewerPath(`${baseViewerPath}#${normalizedAnchor}`, title, wikiOverlayUserId);
  }

  async function cleanupLegacyEditOverlaysForTarget(targetRef: string): Promise<void> {
    const removals: Promise<unknown>[] = [];
    const legacyNote = noteOverlayByTarget.get(targetRef);
    const legacyInk = inkOverlayByTarget.get(targetRef);
    if (legacyNote) {
      removals.push(removeWikiOverlay({
        user_id: wikiOverlayUserId,
        overlay_id: legacyNote.overlay_id,
      }));
    }
    if (legacyInk) {
      removals.push(removeWikiOverlay({
        user_id: wikiOverlayUserId,
        overlay_id: legacyInk.overlay_id,
      }));
    }
    if (removals.length > 0) {
      await Promise.all(removals);
    }
  }

  async function saveEditedCardBundleForTarget(target: OverlayTargetDescriptor, options?: {
    strokes?: WikiInkStroke[];
    textAnnotations?: WikiTextAnnotation[];
    textStyle?: WikiEditedTextStyle;
  }): Promise<void> {
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const legacyNote = noteOverlayByTarget.get(target.ref) ?? null;
    const legacyInk = inkOverlayByTarget.get(target.ref) ?? null;
    const strokes = Array.isArray(options?.strokes)
      ? options.strokes.filter((stroke) => String(stroke.path || '').trim())
      : existingEditedCard?.strokes ?? legacyInk?.strokes ?? [];
    const anchor = target.kind === 'section'
      ? overlayAnchorFromTargetRef(target.ref)
      : '';
    const textAnnotations = Array.isArray(options?.textAnnotations)
      ? options.textAnnotations
        .map((item) => normalizeTextAnnotation(item, anchor))
        .filter((item): item is WikiTextAnnotation => Boolean(item))
      : extractTextAnnotations(existingEditedCard ?? legacyNote, anchor);
    const textStyle = normalizeEditedTextStyle(
      options?.textStyle
      ?? existingEditedCard?.text_style
      ?? legacyNote?.text_style
      ?? annotationTextStyle,
    );
    setIsOverlaySaving(true);
    try {
      if (textAnnotations.length === 0 && strokes.length === 0) {
        if (existingEditedCard) {
          await removeWikiOverlay({
            user_id: wikiOverlayUserId,
            overlay_id: existingEditedCard.overlay_id,
          });
        }
        await cleanupLegacyEditOverlaysForTarget(target.ref);
      } else {
        await saveWikiOverlay({
          user_id: wikiOverlayUserId,
          kind: 'edited_card',
          overlay_id: existingEditedCard?.overlay_id ?? '',
          title: target.title,
          card_title: target.title,
          summary: preview.kind === 'viewer' || preview.kind === 'draft' ? preview.subtitle : '',
          body: '',
          strokes,
          text_style: textStyle,
          text_annotations: textAnnotations,
          source_anchor: anchor,
          source_viewer_path: target.viewerPath,
          document_title: `${target.title} 수정본`,
          document_label: target.kind === 'section' ? 'card_edit_snapshot' : 'book_edit_snapshot',
          pinned: true,
          ...target.payload,
        });
        await cleanupLegacyEditOverlaysForTarget(target.ref);
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleUpsertSectionTextAnnotation(
    section: { anchor: string; title: string },
    annotation: WikiTextAnnotation,
  ): Promise<void> {
    const target = buildSectionOverlayTarget(section.anchor, section.title);
    if (!target) {
      return;
    }
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const existingAnnotations = extractTextAnnotations(existingEditedCard ?? noteOverlayByTarget.get(target.ref) ?? null, section.anchor);
    const nextAnnotation = normalizeTextAnnotation(annotation, section.anchor);
    if (!nextAnnotation) {
      return;
    }
    const nextAnnotations = [
      ...existingAnnotations.filter((item) => (
        item.annotation_id !== nextAnnotation.annotation_id
        && !(nextAnnotation.kind === 'edit' && item.kind === 'edit' && item.block_path === nextAnnotation.block_path)
      )),
      nextAnnotation,
    ].sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === 'edit' ? -1 : 1;
      }
      if (left.kind === 'edit') {
        return String(left.block_path || '').localeCompare(String(right.block_path || ''));
      }
      return Number(left.y_ratio || 0) - Number(right.y_ratio || 0);
    });
    await saveEditedCardBundleForTarget(target, {
      textAnnotations: nextAnnotations,
      textStyle: nextAnnotation.style,
    });
  }

  async function handleRemoveSectionTextAnnotation(section: { anchor: string; title: string }, annotationId: string): Promise<void> {
    const target = buildSectionOverlayTarget(section.anchor, section.title);
    if (!target) {
      return;
    }
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const existingAnnotations = extractTextAnnotations(existingEditedCard ?? noteOverlayByTarget.get(target.ref) ?? null, section.anchor);
    const nextAnnotations = existingAnnotations.filter((item) => item.annotation_id !== annotationId);
    await saveEditedCardBundleForTarget(target, {
      textAnnotations: nextAnnotations,
      textStyle: existingEditedCard?.text_style ?? annotationTextStyle,
    });
  }

  async function handleSaveCurrentInk(strokes: WikiInkStroke[]): Promise<void> {
    if (!currentOverlayTarget) {
      return;
    }
    const normalizedStrokes = strokes.filter((stroke) => String(stroke.path || '').trim());
    await saveEditedCardBundleForTarget(currentOverlayTarget, {
      strokes: normalizedStrokes,
      textStyle: currentEditedCard?.text_style ?? annotationTextStyle,
    });
  }

  function getSignalDisplayTitle(item: WikiOverlayRecord): string {
    if (item.resolved_target?.title) return item.resolved_target.title;
    const fallback = item.title;
    if (fallback) return fallback;
    const ref = item.target_ref || '';
    try {
      const cleanRef = ref.replace(/^section:/, '').replace(/^book:/, '');
      const parts = cleanRef.split('#');
      if (parts.length > 1) {
        return `${parts[0]} > ${decodeURIComponent(parts[1])}`;
      }
      return decodeURIComponent(cleanRef);
    } catch {
      return ref;
    }
  }

  function getSignalHref(item: WikiOverlayRecord): string | undefined {
    if (item.resolved_target?.viewer_path) return item.resolved_target.viewer_path;
    const fallbackPath = typeof item.payload.viewer_path === 'string' ? item.payload.viewer_path : undefined;
    if (fallbackPath) return fallbackPath;
    if (item.target_ref) {
      if (item.target_ref.startsWith('section:')) {
        const split = item.target_ref.replace('section:', '').split('#');
        return `/wiki-runtime/active/${split[0]}/index.html${split[1] ? '#' + split[1] : ''}`;
      }
      if (item.target_ref.startsWith('book:')) {
        return `/wiki-runtime/active/${item.target_ref.replace('book:', '')}/index.html`;
      }
    }
    return undefined;
  }

  async function handleOverlayJump(item: WikiOverlayRecord): Promise<void> {
    const href = getSignalHref(item);
    if (!href) {
      return;
    }
    await handleRelatedLinkClick({
      label: getSignalDisplayTitle(item),
      href,
      kind: item.target_kind === 'entity_hub' ? 'entity' : 'book',
      summary: item.resolved_target?.summary || item.summary || '',
    });
  }

  async function handleUploadSelection(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      setIngestionStatusBanner({
        status: 'parsing',
        message: '문서 파싱중입니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      });
      const uploaded = await uploadDocumentIngestion(file, {
        index: true,
        repositoryId: activeRepository?.repository_id,
      });
      const repositoryPayload = await loadDocumentRepositories().catch(() => ({ repositories: [] }));
      const repositoryId = uploaded.repository_id || uploaded.persisted?.repository_id || activeRepository?.repository_id || '';
      const documentSourceId = uploaded.persisted?.document_source_id || '';
      setDocumentRepositories(repositoryPayload.repositories ?? []);
      if (repositoryId) {
        setActiveSourceId(`repository:${repositoryId}`);
      }
      const nextBanner: IngestionStatusBanner = {
        status: 'ready',
        message: '문서 준비가 완료되었습니다.',
        filename: uploaded.filename || file.name,
        repositoryId,
        documentSourceId,
        updatedAt: new Date().toISOString(),
      };
      setIngestionStatusBanner(nextBanner);
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify(nextBanner));
      setPreview({ kind: 'empty' });
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '업로드 중 오류가 발생했습니다.');
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }

  async function handleCapture(): Promise<void> {
    if (!activeDraft || isCapturing) {
      return;
    }
    setIsCapturing(true);
    try {
      const captured = await captureCustomerPackDraft(activeDraft.draft_id);
      setDrafts((current) => mergeDraft(captured, current));
      await openDraftPreview(captured.draft_id, mergeDraft(captured));
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : 'Prepare Pack failed.');
    } finally {
      setIsCapturing(false);
    }
  }

  async function handleNormalize(): Promise<void> {
    if (!activeDraft || isNormalizing) {
      return;
    }
    setIsNormalizing(true);
    try {
      const normalized = await normalizeCustomerPackDraft(activeDraft.draft_id);
      setDrafts((current) => mergeDraft(normalized, current));
      await openDraftPreview(normalized.draft_id, mergeDraft(normalized));
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : 'Save to Wiki failed.');
    } finally {
      setIsNormalizing(false);
    }
  }

  async function handleSend(queryOverride?: string, options: SendOptions = {}): Promise<void> {
    const visibleQuery = (queryOverride ?? query).trim();
    if (!visibleQuery || isSending) {
      return;
    }
    const continuation = queryOverride
      ? { query: visibleQuery, routeKind: options.routeKind, learningIndex: options.learningIndex, questionMeta: undefined }
      : resolveContinuationQuestion(visibleQuery, messages, learningQuestionByText);
    const trimmed = continuation.query.trim();
    const questionMeta = continuation.questionMeta || learningQuestionByText.get(trimmed);
    const resolvedRouteKind = continuation.routeKind || options.routeKind;
    const resolvedLearningIndex = continuation.learningIndex ?? options.learningIndex;
    const resolvedCategoryKey = options.categoryKey ?? questionMeta?.categoryKey;
    const resolvedCategoryLabel = options.categoryLabel ?? questionMeta?.categoryLabel;
    const resolvedTargetBookSlug = options.targetBookSlug ?? questionMeta?.targetBookSlug;
    const resolvedTargetTitle = options.targetTitle ?? questionMeta?.targetTitle;
    const resolvedTargetViewerPath = options.targetViewerPath ?? questionMeta?.targetViewerPath;
    const resolvedLearningPathId = options.learningPathId ?? questionMeta?.learningPathId;
    const resolvedLearningStepId = options.learningStepId ?? questionMeta?.learningStepId;
    const resolvedLabTaskId = options.labTaskId ?? questionMeta?.labTaskId;
    const shouldUseCourseMode = options.forceCourseMode || resolvedRouteKind === 'course' || isCourseMode;
    const shouldUseLiveClusterMode = !shouldUseCourseMode && currentMode === 'live_cluster' && isLiveClusterAvailable;
    const messageRouteKind: Message['routeKind'] = shouldUseCourseMode
      ? 'course'
      : resolvedRouteKind || 'official';
    if (messageRouteKind === 'learning' && resolvedLabTaskId) {
      setTerminalLearningContext({
        learnerId: wikiOverlayUserId,
        learningPathId: resolvedLearningPathId,
        learningStepId: resolvedLearningStepId,
        labTaskId: resolvedLabTaskId,
      });
    }

    const nextUserMessage: Message = {
      id: makeId('user'),
      role: 'user',
      content: visibleQuery,
      routeKind: messageRouteKind,
      learningIndex: resolvedLearningIndex,
      rewrittenQuery: trimmed !== visibleQuery ? trimmed : undefined,
    };
    setMessages((current) => [...current, nextUserMessage]);
    if (!queryOverride) {
      setQuery('');
    }
    setIsSending(true);

    try {
      const requestPayload = {
        query: trimmed,
        sessionId,
        mode: 'ops',
        userId: wikiOverlayUserId,
        selectedDraftIds: activeDraft ? [activeDraft.draft_id] : [],
        restrictUploadedSources: Boolean(activeDraft),
        routeKind: messageRouteKind,
        activeRepositoryId: activeRepository?.repository_id,
        activeDocumentId,
        learningIndex: resolvedLearningIndex,
        learningCategoryKey: resolvedCategoryKey,
        learningCategoryLabel: resolvedCategoryLabel,
        learningTargetBookSlug: resolvedTargetBookSlug,
        learningTargetTitle: resolvedTargetTitle,
        learningTargetViewerPath: resolvedTargetViewerPath,
      };
      let response: ChatResponse;
      let courseAssistantMessageId = '';
      let courseStreamUpdater: ReturnType<typeof createThrottledMessageContentUpdater> | null = null;
      let assistantStreamMessageId = '';
      let assistantStreamUpdater: ReturnType<typeof createThrottledMessageContentUpdater> | null = null;
      if (shouldUseCourseMode) {
        courseAssistantMessageId = makeId('assistant');
        let streamedAnswer = '';
        setMessages((current) => [
          ...current,
          {
            id: courseAssistantMessageId,
            role: 'assistant',
            content: '',
            citations: [],
            suggestedQueries: [],
            relatedLinks: [],
            relatedSections: [],
            artifacts: [],
            responseKind: 'rag',
            routeKind: 'course',
          },
        ]);
        courseStreamUpdater = createThrottledMessageContentUpdater(courseAssistantMessageId, setMessages, 90);
        response = await sendCourseChatStream({
          message: trimmed,
          sessionId,
          userId: wikiOverlayUserId,
        }, (event) => {
          if (event.type === 'answer_delta') {
            streamedAnswer += event.delta;
            courseStreamUpdater?.push(streamedAnswer);
          }
        });
        courseStreamUpdater.flush();
      } else {
        assistantStreamMessageId = makeId('assistant');
        let streamedAnswer = '';
        setMessages((current) => [
          ...current,
          {
            id: assistantStreamMessageId,
            role: 'assistant',
            content: '',
            citations: [],
            suggestedQueries: [],
            relatedLinks: [],
            relatedSections: [],
            artifacts: [],
            responseKind: 'rag',
            routeKind: messageRouteKind,
            learningIndex: resolvedLearningIndex,
          },
        ]);
        assistantStreamUpdater = createThrottledMessageContentUpdater(assistantStreamMessageId, setMessages, 70);
        if (testMode) {
          setActiveTestTrace({
            query: trimmed,
            sessionId,
            events: [],
            result: null,
          });
        }
        if (shouldUseLiveClusterMode) {
          const namespace = selectedResourceNamespace.trim() || activeFooterConnection?.default_namespace || 'default';
          const liveResponse = await sendOpsChatStream({
            message: trimmed,
            connection_id: activeFooterConnection?.connection_id || undefined,
            namespace,
            history: messages.slice(-6).map((item) => ({ role: item.role, text: item.content })),
            recent_terminal_actions: recentTerminalActions.map((item) => ({
              command: item.command,
              timestamp: item.timestamp,
            })),
          }, (event) => {
            if (event.type === 'answer_delta') {
              streamedAnswer += event.delta;
              assistantStreamUpdater?.push(streamedAnswer);
            }
            if (testMode && event.type === 'stage') {
              setActiveTestTrace((current) => ({
                query: current?.query ?? trimmed,
                sessionId: current?.sessionId ?? sessionId,
                events: [
                  ...(current?.events ?? []),
                  {
                    type: 'trace',
                    step: `live_cluster:${event.stage.key}`,
                    label: event.stage.label,
                    status: event.stage.status,
                    detail: event.stage.detail,
                  },
                ],
                result: current?.result ?? null,
              }));
            }
            if (testMode && event.type === 'result') {
              setActiveTestTrace((current) => ({
                query: current?.query ?? trimmed,
                sessionId: current?.sessionId ?? sessionId,
                events: current?.events ?? [],
                result: opsChatResponseToChatResponse(event.response, sessionId),
              }));
            }
          });
          response = opsChatResponseToChatResponse(liveResponse, sessionId);
        } else {
          response = await sendChatStream(requestPayload, (event) => {
            if (event.type === 'answer_delta') {
              streamedAnswer += event.delta;
              assistantStreamUpdater?.push(streamedAnswer);
            }
            if (testMode && event.type === 'trace') {
              setActiveTestTrace((current) => ({
                query: current?.query ?? trimmed,
                sessionId: current?.sessionId ?? sessionId,
                events: [...(current?.events ?? []), event],
                result: current?.result ?? null,
              }));
            }
            if (testMode && event.type === 'result') {
              setActiveTestTrace((current) => ({
                query: current?.query ?? trimmed,
                sessionId: event.payload.session_id || current?.sessionId || sessionId,
                events: current?.events ?? [],
                result: event.payload,
              }));
            }
          });
        }
        assistantStreamUpdater.flush();
      }
      const primaryTruth = primaryCitationTruth(response.citations);

      setSessionId(response.session_id || sessionId);
      const assistantMessage = {
          id: makeId('assistant'),
          role: 'assistant',
          content: response.answer,
          citations: response.citations ?? [],
          suggestedQueries: messageRouteKind === 'learning'
            ? mergeLearningFollowUps(response.suggested_queries ?? [], resolvedLearningIndex, welcomeLearningSequence)
            : response.suggested_queries ?? [],
          relatedLinks: response.related_links ?? [],
          relatedSections: response.related_sections ?? [],
          artifacts: Array.isArray((response as { artifacts?: unknown }).artifacts)
            ? ((response as { artifacts?: Array<Record<string, unknown>> }).artifacts ?? [])
            : [],
          responseKind: response.response_kind,
          acquisition: response.acquisition,
          primarySourceLane: primaryTruth?.sourceLane,
          primaryBoundaryTruth: primaryTruth?.boundaryTruth,
          primaryRuntimeTruthLabel: primaryTruth?.runtimeTruthLabel,
          primaryBoundaryBadge: primaryTruth?.boundaryBadge,
          primaryPublicationState: primaryTruth?.publicationState,
          primaryApprovalState: primaryTruth?.approvalState,
          routeKind: messageRouteKind,
          learningIndex: resolvedLearningIndex,
          rewrittenQuery: response.rewritten_query,
          retrievalTrace: response.retrieval_trace,
          pipelineTrace: response.pipeline_trace,
          traceEvents: response.pipeline_trace?.events ?? (testMode ? activeTestTrace?.events ?? [] : []),
        } satisfies Message;
      if (courseAssistantMessageId) {
        setMessages((current) => current.map((message) => (
          message.id === courseAssistantMessageId
            ? { ...assistantMessage, id: courseAssistantMessageId }
            : message
        )));
      } else if (assistantStreamMessageId) {
        setMessages((current) => current.map((message) => (
          message.id === assistantStreamMessageId
            ? { ...assistantMessage, id: assistantStreamMessageId }
            : message
        )));
      } else {
        setMessages((current) => [...current, assistantMessage]);
      }
      if (testMode && !shouldUseCourseMode) {
        setActiveTestTrace((current) => ({
          query: current?.query ?? trimmed,
          sessionId: response.session_id || current?.sessionId || sessionId,
          events: response.pipeline_trace?.events ?? current?.events ?? [],
          result: response,
        }));
      }

      const primaryCitation = pickPrimaryPlaybookCitation(response.citations);
      if (primaryCitation && !shouldUseCourseMode) {
        const targetAssistantMessageId = assistantStreamMessageId || assistantMessage.id;
        setMessages((current) => current.map((message) => (
          message.id === targetAssistantMessageId
            ? { ...message, activeCitationIndex: primaryCitation.index }
            : message
        )));
      }
    } catch (error) {
      console.error(error);
      if (testMode && error instanceof Error) {
        setActiveTestTrace((current) => ({
          query: current?.query ?? trimmed,
          sessionId: current?.sessionId ?? sessionId,
          events: [
            ...(current?.events ?? []),
            {
              type: 'trace',
              step: 'stream_error',
              label: 'Stream Error',
              status: 'error',
              detail: error.message,
            },
          ],
          result: current?.result ?? null,
        }));
      }
      window.alert(error instanceof Error ? error.message : '질문 처리 중 오류가 발생했습니다.');
    } finally {
      setIsSending(false);
      void refreshSessionList();
    }
  }

  function handleAcquisitionConfirm(): void {
    navigate('/playbook-library?view=repository');
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  function handleDerivedAssetOpen(asset: DerivedAsset): void {
    if (preview.kind !== 'draft') {
      return;
    }
    setPreview({
      ...preview,
      subtitle: `${preview.draft.pack_label} · ${asset.family_label}`,
      viewerUrl: toRuntimeUrl(asset.viewer_path),
    });
    animatePreviewPanel();
  }

  const canCapture = Boolean(activeDraft) && !isCapturing;
  const canNormalize = Boolean(activeDraft) && !isNormalizing;

  const recentOverlayItems = recentPositionOverlays.slice(0, 4);
  const editedOverlayItems = editedCardOverlays.slice(0, 6);
  const favoriteOverlayItems = (
    signalsFavoriteFilter === 'edited'
      ? editedOverlayItems
      : favoriteOverlays
  ).slice(0, 6);
  const nextPlayItems = personalizedNextPlays.slice(0, 4);
  const activeAssistantMessage = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant') ?? null,
    [messages],
  );
  const visibleMessages = useMemo(
    () => messages.filter((message) => (
      message.role !== 'assistant'
      || message.content.trim()
      || !isSending
    )),
    [isSending, messages],
  );
  const showThinkingIndicator = useMemo(() => {
    if (!isSending) {
      return false;
    }
    const lastMessage = messages[messages.length - 1];
    return !lastMessage || lastMessage.role !== 'assistant' || !lastMessage.content.trim();
  }, [isSending, messages]);
  const activeBookSlug = useMemo(() => {
    if (preview.kind === 'viewer' && preview.meta?.book_slug) {
      return preview.meta.book_slug;
    }
    if (activeSourceId && activeSourceId.startsWith('manual:')) {
      return activeSourceId.replace('manual:', '');
    }
    return '';
  }, [activeSourceId, preview]);
  const outlineCategoryGroups = useMemo<OutlineCategoryGroup[]>(() => {
    const grouped = new Map<string, OutlineCategoryGroup>();
    for (const book of manualBooks) {
      const inferred = inferOutlineCategory(book);
      const existing = grouped.get(inferred.key) ?? { ...inferred, books: [] };
      existing.books.push(book);
      grouped.set(inferred.key, existing);
    }
    return Array.from(grouped.values())
      .map((group) => ({
        ...group,
        books: [...group.books].sort((left, right) => left.title.localeCompare(right.title, 'ko')),
      }))
      .sort((left, right) => {
        const leftIndex = OUTLINE_CATEGORY_RULES.findIndex((rule) => rule.key === left.key);
        const rightIndex = OUTLINE_CATEGORY_RULES.findIndex((rule) => rule.key === right.key);
        return leftIndex - rightIndex;
      });
  }, [manualBooks]);
  const outlineCategoryFamilies = useMemo(
    () =>
      new Map(
        outlineCategoryGroups.map((group) => [group.key, buildOutlineBookFamilies(group.books)]),
      ),
    [outlineCategoryGroups],
  );
  const autoOutlineCategoryKey = useMemo(() => {
    if (activeBookSlug) {
      const matched = outlineCategoryGroups.find((group) => group.books.some((book) => book.book_slug === activeBookSlug));
      if (matched) {
        return matched.key;
      }
    }
    return outlineCategoryGroups[0]?.key ?? '';
  }, [activeBookSlug, outlineCategoryGroups]);
  const resolvedOutlineCategoryKey = outlineCategoryKey === OUTLINE_CATEGORY_COLLAPSED
    ? ''
    : outlineCategoryGroups.some((group) => group.key === outlineCategoryKey)
      ? outlineCategoryKey
      : autoOutlineCategoryKey;
  useEffect(() => {
    if (
      !resolvedOutlineCategoryKey
      || resolvedOutlineCategoryKey === outlineCategoryKey
      || outlineCategoryKey === OUTLINE_CATEGORY_COLLAPSED
    ) {
      return;
    }
    setOutlineCategoryKey(resolvedOutlineCategoryKey);
  }, [outlineCategoryKey, resolvedOutlineCategoryKey]);
  // Breadcrumb path for the currently focused section (used as a header line above the TOC)
  const outlineBreadcrumb = useMemo<string[]>(() => {
    if (preview.kind === 'viewer' && preview.meta?.section_path?.length) {
      return preview.meta.section_path;
    }
    return [];
  }, [preview]);

  // Hierarchical TOC derived from the currently open document's sections
  const outlineTocNodes = useMemo<OutlineTocNode[]>(() => {
    if (preview.kind === 'draft' && preview.book?.sections?.length) {
      return preview.book.sections.map((section, index) => {
        const segments = (section.section_path_label || '')
          .split(/\s*[>/]\s*/)
          .map((part) => part.trim())
          .filter(Boolean);
        const rawDepth = Math.max(0, segments.length - 1);
        return {
          id: `toc-draft:${section.viewer_path}:${index}`,
          heading: section.heading || segments[segments.length - 1] || 'Untitled section',
          depth: Math.min(rawDepth, 3),
          viewerPath: section.viewer_path,
          sectionPathLabel: section.section_path_label || '',
        };
      });
    }

    if (preview.kind === 'viewer' && preview.meta?.section_path?.length) {
      const sectionPath = preview.meta.section_path;
      return sectionPath.map((section, index) => ({
        id: `toc-viewer:${index}:${section}`,
        heading: section,
        depth: Math.min(index, 3),
        viewerPath: preview.meta?.viewer_path || '',
        sectionPathLabel: sectionPath.slice(0, index + 1).join(' > '),
      }));
    }

    return [];
  }, [preview]);

  // Active TOC node identifier — best-effort match by viewerPath / section label
  const activeTocNodeId = useMemo<string | null>(() => {
    if (!outlineTocNodes.length) return null;
    if (preview.kind === 'viewer') {
      const currentPath = preview.meta?.viewer_path;
      const lastSection = preview.meta?.section_path?.[preview.meta.section_path.length - 1];
      const match = outlineTocNodes.find((node) => {
        if (currentPath && node.viewerPath === currentPath) return true;
        if (lastSection && node.heading === lastSection) return true;
        return false;
      });
      return match?.id ?? null;
    }
    if (preview.kind === 'draft') {
      // No persistent "active section" in draft mode — highlight the first node as a reading anchor
      return outlineTocNodes[0]?.id ?? null;
    }
    return null;
  }, [outlineTocNodes, preview]);
  const outlineProcedureItems: OutlineLinkItem[] = (activeAssistantMessage?.relatedSections ?? [])
    .slice(0, 6)
    .map((link, index) => ({
      id: `procedure:${link.href}:${index}`,
      label: link.label,
      meta: link.summary || '',
      action: () => {
        void handleRelatedLinkClick(link);
      },
    }));
  const outlineRuntimeItems: OutlineLinkItem[] = manualSources.map((source) => ({
    id: source.id,
    label: source.name,
    meta: source.meta,
    action: () => {
      void handleSourceClick(source);
    },
    tone: activeSourceId === source.id ? 'default' : 'muted',
  }));
  const outlineCustomerItems: OutlineLinkItem[] = draftSources.slice(0, 4).map((source) => ({
    id: source.id,
    label: source.name,
    meta: source.meta,
    action: () => {
      void handleSourceClick(source);
    },
    tone: activeSourceId === source.id ? 'default' : 'muted',
  }));
  const previewTitle = preview.kind === 'empty' ? '' : preview.title;
  const viewerSurfaceTitle = rightPanelMode === 'terminal' ? 'Terminal Session' : 'Wiki Viewer';
  const viewerDocumentToolbar = !testMode && currentOverlayTarget ? (
    <div className="viewer-header-toolbar" role="toolbar" aria-label="위키 뷰어 액션">
      {preview.kind === 'viewer' && viewerOriginalSourceHref && (
        <a
          href={viewerOriginalSourceHref}
          className="viewer-header-icon-btn viewer-header-link"
          target="_blank"
          rel="noreferrer"
          title="원문 열기"
          aria-label="원문 열기"
        >
          <FileText size={15} />
        </a>
      )}
      {preview.kind === 'viewer' && (
        <label className="viewer-header-mode" title="형식">
          <BookOpen size={14} aria-hidden="true" />
          <select
            className="viewer-header-mode-select"
            value={viewerPageMode}
            aria-label="형식"
            onChange={(event) => { void handleViewerPageModeChange(event.target.value as ViewerPageMode); }}
          >
            <option value="single">단일</option>
            <option value="multi">멀티</option>
          </select>
        </label>
      )}
      <button
        type="button"
        className={`viewer-header-icon-btn ${currentFavorite ? 'active' : ''}`}
        onClick={() => { void handleToggleFavoriteCurrent(); }}
        disabled={isOverlaySaving}
        title={currentFavorite ? '즐겨찾기 해제' : '즐겨찾기'}
        aria-label={currentFavorite ? '즐겨찾기 해제' : '즐겨찾기'}
      >
        <Star size={15} />
      </button>
      {currentOverlayTarget.kind === 'section' && (
        <button
          type="button"
          className={`viewer-header-icon-btn ${currentSectionCheck ? 'active' : ''}`}
          onClick={() => { void handleToggleSectionCheckCurrent(); }}
          disabled={isOverlaySaving}
          title={currentSectionCheck ? '완료 해제' : '완료 표시'}
          aria-label={currentSectionCheck ? '완료 해제' : '완료 표시'}
        >
          <Check size={15} />
        </button>
      )}
      {preview.kind === 'viewer' && quickNavItems.length > 0 && (
        <div ref={quickNavRef} className={`viewer-quick-nav ${quickNavOpen ? 'open' : ''}`}>
          <button
            type="button"
            className="viewer-header-icon-btn viewer-quick-nav-trigger"
            aria-expanded={quickNavOpen}
            title="퀵 네비게이션"
            aria-label="퀵 네비게이션"
            onClick={() => setQuickNavOpen((value) => !value)}
          >
            <Compass size={15} />
          </button>
          {quickNavOpen && (
            <div className="viewer-quick-nav-popover">
              <div className="viewer-quick-nav-header">퀵 네비게이션</div>
              <div className="viewer-quick-nav-list">
                {quickNavItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="viewer-quick-nav-item"
                    onClick={() => {
                      setQuickNavOpen(false);
                      void openViewerPreview(item.viewerPath, preview.title, undefined, viewerPageMode);
                    }}
                  >
                    <span className="viewer-quick-nav-item-heading">{item.heading}</span>
                    <span className="viewer-quick-nav-item-meta">{item.sectionPathLabel}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  ) : null;
  const viewerHeaderToolbar = (
    <>
      <div className="viewer-panel-mode-switch" role="tablist" aria-label="Right panel mode">
        <button
          type="button"
          className={`viewer-panel-mode-btn ${rightPanelMode === 'viewer' ? 'active' : ''}`}
          onClick={() => setRightPanelMode('viewer')}
          title="Wiki Viewer"
          aria-label="Wiki Viewer"
        >
          <BookOpen size={14} />
        </button>
        <button
          type="button"
          className={`viewer-panel-mode-btn ${rightPanelMode === 'terminal' ? 'active' : ''}`}
          onClick={() => setRightPanelMode('terminal')}
          title="Terminal Session"
          aria-label="Terminal Session"
        >
          <TerminalIcon size={14} />
        </button>
      </div>
      {rightPanelMode === 'viewer' ? viewerDocumentToolbar : null}
    </>
  );
  return (
    <div className={`workspace-wrapper ${isPanelResizing ? 'is-resizing-panels' : ''}`} ref={containerRef} data-lenis-prevent>
      <div className="bokeh-bg bokeh-1"></div>
      <div className="bokeh-bg bokeh-2"></div>

      <WorkspaceHeader
        globalTheme={globalTheme}
        onOpenDashboard={() => setDashboardOpen(true)}
        onOpenLibrary={() => navigate('/playbook-library')}
        onToggleGlobalTheme={handleToggleGlobalTheme}
      />

      <main className="workspace-content">
        <Group
          orientation="horizontal"
          className="main-panel-group"
          defaultLayout={savedLayout}
          onLayoutChanged={handlePanelLayoutChanged}
        >

          {/* ── Left Panel: Chat History ── */}
          <Panel
            id="workspace-left"
            panelRef={leftPanelRef}
            defaultSize={14}
            minSize={12}
            collapsible={true}
            collapsedSize={0}
            onResize={(panelSize) => setLeftCollapsed(panelSize.asPercentage <= 0.5)}
            className="workspace-panel-item"
          >
            <div className={`panel-inner glass-panel no-border-radius-right ${leftCollapsed ? 'panel-collapsed-inner' : ''}`}>
              <div className="panel-header panel-header-stacked">
                <div className="header-icon"><MessageSquare size={18} /></div>
                <div className="panel-header-main">
                  <div className="panel-header-copy">
                    <h3>
                      {leftPanelMode === 'history' && leftPanelLabels.historyTitle}
                      {leftPanelMode === 'outline' && leftPanelLabels.outlineTitle}
                      {leftPanelMode === 'signals' && leftPanelLabels.signalsTitle}
                    </h3>
                  </div>
                  <div className="session-header-actions">
                    <button className="header-action-btn" type="button" onClick={resetSession} title="New Chat">
                      <Plus size={14} />
                    </button>
                    <button
                      className="header-action-btn header-action-danger"
                      type="button"
                      onClick={() => { void handleDeleteAllSessions(); }}
                      title="Delete All Chat History"
                      disabled={Boolean(deletingSessionId) || isLoadingSession || sessionList.length === 0}
                    >
                      <Trash2 size={14} />
                    </button>
                    <button className="header-action-btn" type="button" onClick={toggleLeftPanel} title="Close sidebar">
                      <PanelLeftClose size={14} />
                    </button>
                  </div>
                </div>
              </div>
              <div className="panel-mode-strip">
                <div className="panel-mode-switch" role="tablist" aria-label="Left panel mode">
                  <button
                    type="button"
                    className={`panel-mode-btn ${leftPanelMode === 'history' ? 'active' : ''}`}
                    onClick={() => setLeftPanelMode('history')}
                    title={leftPanelLabels.history}
                  >
                    {leftPanelLabels.history}
                  </button>
                  <button
                    type="button"
                    className={`panel-mode-btn ${leftPanelMode === 'outline' ? 'active' : ''}`}
                    onClick={() => setLeftPanelMode('outline')}
                    title={leftPanelLabels.outline}
                  >
                    {leftPanelLabels.outline}
                  </button>
                  <button
                    type="button"
                    className={`panel-mode-btn ${leftPanelMode === 'signals' ? 'active' : ''}`}
                    onClick={() => setLeftPanelMode('signals')}
                    title={leftPanelLabels.signalsTitle}
                  >
                    {leftPanelLabels.signals}
                  </button>
                </div>
              </div>

              {leftPanelMode === 'history' ? (
                <div className="session-list">
                  {isSessionListLoading ? (
                    <div className="session-list-empty loading">
                      <div className="loading-spinner-small"></div>
                      <p>대화 기록 불러오는 중</p>
                    </div>
                  ) : sessionList.length === 0 && (
                    <div className="session-list-empty">
                      <MessageSquare size={24} className="text-dim" />
                      <p>아직 대화 기록이 없습니다</p>
                    </div>
                  )}
                  {sessionList.map((session) => (
                    <button
                      key={session.session_id}
                      type="button"
                      className={`session-item ${session.session_id === sessionId ? 'active' : ''}`}
                      onClick={() => { void handleSessionResume(session.session_id); }}
                      disabled={isLoadingSession || deletingSessionId === session.session_id}
                    >
                      <div className="session-title">{session.session_name || session.first_query || `세션 ${session.session_id.slice(0, 8)}`}</div>
                      {(session.primary_boundary_badge || session.primary_runtime_truth_label || session.primary_source_lane) && (
                        <div className="session-truth-row">
                          <TruthBadgeBlock
                            payload={{
                              boundary_truth: session.primary_boundary_truth,
                              runtime_truth_label: session.primary_runtime_truth_label,
                              boundary_badge: session.primary_boundary_badge,
                              source_lane: session.primary_source_lane,
                              approval_state: session.primary_approval_state,
                              publication_state: session.primary_publication_state,
                            }}
                            badgeClassName="session-truth-chip"
                            metaClassName="session-truth-meta"
                            showMeta={false}
                          />
                        </div>
                      )}
                      <div className="session-meta">
                        <span>{session.turn_count} turns</span>
                        {session.updated_at && <span>{session.updated_at.slice(0, 10)}</span>}
                      </div>
                      <button
                        type="button"
                        className="session-delete-inline"
                        title="삭제"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleSessionDelete(session.session_id);
                        }}
                        disabled={Boolean(deletingSessionId) || isLoadingSession}
                      >
                        <Trash2 size={13} />
                      </button>
                    </button>
                  ))}
                </div>
              ) : leftPanelMode === 'outline' ? (
                <div className="outline-panel">
                  <section className="outline-surface-card outline-surface-card--document cluster-resource-explorer">
                    <div className="outline-section-head">
                      <div className="outline-section-copy">
                        <strong>Cluster Resources</strong>
                        <span>{isClusterConnected ? activeFooterConnection?.display_name || activeFooterConnection?.cluster_url : 'Cluster is not connected'}</span>
                      </div>
                      <button
                        type="button"
                        className="cluster-resource-refresh"
                        onClick={() => { void refreshClusterResources(); }}
                        disabled={!isClusterConnected || isClusterResourceLoading}
                      >
                        {isClusterResourceLoading ? 'Loading' : 'Refresh'}
                      </button>
                    </div>
                    <div className="cluster-resource-controls">
                      <label>
                        <span>Kind</span>
                        <select
                          value={selectedResourceKind}
                          onChange={(event) => setSelectedResourceKind(event.target.value as ClusterResourceKind)}
                          disabled={!isClusterConnected}
                        >
                          {CLUSTER_RESOURCE_OPTIONS.map((kind) => (
                            <option key={kind} value={kind}>{kind}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Namespace</span>
                        <input
                          type="text"
                          value={selectedResourceNamespace}
                          onChange={(event) => setSelectedResourceNamespace(event.target.value)}
                          disabled={!isClusterConnected}
                          placeholder={activeFooterConnection?.default_namespace || 'default'}
                        />
                      </label>
                    </div>
                    {!isClusterConnected ? (
                      <div className="outline-empty">
                        <p>Cluster가 연결되어 있지 않습니다.</p>
                      </div>
                    ) : clusterResourceError ? (
                      <div className="outline-empty">
                        <p>{clusterResourceError}</p>
                      </div>
                    ) : isClusterResourceLoading ? (
                      <div className="outline-empty">
                        <div className="loading-spinner-small"></div>
                        <p>Loading cluster resources</p>
                      </div>
                    ) : clusterResources.length === 0 ? (
                      <div className="outline-empty">
                        <p>No {selectedResourceKind} found.</p>
                      </div>
                    ) : (
                      <div className="cluster-resource-list">
                        {clusterResources.map((resource) => (
                          <button
                            key={`${resource.kind}:${resource.namespace}:${resource.name}`}
                            type="button"
                            className="cluster-resource-item"
                            onClick={() => { void openClusterResourceYaml(resource); }}
                          >
                            <span className="cluster-resource-title">{resource.name}</span>
                            <span className="cluster-resource-meta">
                              {resource.kind} · {resource.namespace || selectedResourceNamespace}
                              {resource.phase ? ` · ${resource.phase}` : ''}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </section>
                  {false && (
                    <>
                  {outlineCategoryGroups.length > 0 && (
                    <section className="outline-category-board outline-surface-card outline-surface-card--catalog">
                      <div className="outline-section-head">
                        <strong>{isGuidedSurface ? 'Tour Routes' : 'Categories'}</strong>
                        <span>{outlineCategoryGroups.length}</span>
                      </div>
                      <div className="outline-category-list">
                        {outlineCategoryGroups.map((group) => {
                          const isActive = group.key === resolvedOutlineCategoryKey;
                          const groupFamilies = (outlineCategoryFamilies.get(group.key) ?? []).slice(0, 14);
                          return (
                            <div key={group.key} className={`outline-category-card${isActive ? ' active' : ''}`}>
                              <button
                                type="button"
                                className={`outline-category-item${isActive ? ' active' : ''}`}
                                onClick={() => setOutlineCategoryKey(isActive ? OUTLINE_CATEGORY_COLLAPSED : group.key)}
                              >
                                <div className="outline-category-main">
                                  <span className="outline-category-label">{group.label}</span>
                                  <span className="outline-category-description">{group.description}</span>
                                </div>
                                <div className="outline-category-side">
                                  <span className="outline-category-count">{groupFamilies.length}</span>
                                  {isActive ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                </div>
                              </button>
                              {isActive && (
                                <div className="outline-category-expand">
                                  {groupFamilies.map((family) => {
                                    const familyActive = [family.primary, ...family.variants].some(
                                      (book) => book.book_slug === activeBookSlug,
                                    );
                                    return (
                                      <div
                                        key={family.key}
                                        className={`outline-library-family${familyActive ? ' active' : ''}`}
                                      >
                                        <button
                                          type="button"
                                          className={`outline-library-item ${family.primary.book_slug === activeBookSlug ? 'active' : 'muted'}`}
                                          onClick={() => {
                                            void openManualPreview(family.primary);
                                          }}
                                        >
                                          <div className="outline-library-title-row">
                                            <div className="outline-library-title-group">
                                              <span className="outline-library-title">{family.primary.title}</span>
                                              <span className={playbookGradeBadgeClass(family.primary.grade)}>
                                                {normalizePlaybookGrade(family.primary.grade)}
                                              </span>
                                            </div>
                                            {family.variants.length > 0 && (
                                              <span className="outline-library-variant-count">+{family.variants.length}</span>
                                            )}
                                          </div>
                                          <span className="outline-library-meta">{summarizeBookMeta(family.primary)}</span>
                                        </button>
                                        {family.variants.length > 0 && (
                                          <div className="outline-library-variants">
                                            {family.variants.map((variant) => (
                                              <button
                                                key={`outline-book:${variant.book_slug}`}
                                                type="button"
                                                className={`outline-library-variant ${variant.book_slug === activeBookSlug ? 'active' : ''}`}
                                                onClick={() => {
                                                  void openManualPreview(variant);
                                                }}
                                              >
                                                <div className="outline-library-variant-header">
                                                  <span className="outline-library-variant-label">{describeOutlineVariant(variant)}</span>
                                                  <span className={playbookGradeBadgeClass(variant.grade)}>
                                                    {normalizePlaybookGrade(variant.grade)}
                                                  </span>
                                                </div>
                                                <span className="outline-library-variant-meta">{summarizeBookMeta(variant)}</span>
                                              </button>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  )}

                  <nav className="outline-toc outline-surface-card outline-surface-card--document" aria-label="Document outline">
                    <div className="outline-section-head">
                      <div className="outline-section-copy">
                        <strong>{isGuidedSurface ? 'Current Stop' : 'Current Document'}</strong>
                        {previewTitle && <span>{previewTitle}</span>}
                      </div>
                      {outlineTocNodes.length > 0 && <span>{outlineTocNodes.length}</span>}
                    </div>
                    {outlineTocNodes.length === 0 ? (
                      <div className="outline-empty">
                        <p>목차 없음</p>
                      </div>
                    ) : (
                      <>
                        <div className="outline-toc-header">
                          <strong className="outline-toc-title">{previewTitle}</strong>
                          {outlineBreadcrumb.length > 0 && (
                            <span className="outline-toc-breadcrumb">{outlineBreadcrumb.join(' › ')}</span>
                          )}
                          <span className="outline-toc-meta">{outlineTocNodes.length} sections</span>
                        </div>
                        <ul className="outline-toc-tree">
                          {outlineTocNodes.map((node) => {
                            const isActive = activeTocNodeId === node.id;
                            return (
                              <li
                                key={node.id}
                                className={`outline-toc-item${isActive ? ' active' : ''}`}
                                style={{ ['--depth' as string]: node.depth } as React.CSSProperties}
                              >
                                <button
                                  type="button"
                                  aria-current={isActive ? 'location' : undefined}
                                  onClick={() => { void openViewerPreview(node.viewerPath, node.heading); }}
                                  title={node.sectionPathLabel || node.heading}
                                >
                                  <span className="outline-toc-heading">{node.heading}</span>
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      </>
                    )}
                    {outlineProcedureItems.length > 0 && (
                      <div className="outline-toc-suggested">
                        <div className="outline-toc-suggested-title">{isGuidedSurface ? 'Then Open' : 'Suggested next'}</div>
                        <div className="outline-toc-suggested-chips">
                          {outlineProcedureItems.slice(0, 3).map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              className="outline-toc-chip"
                              onClick={item.action}
                              title={item.meta}
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </nav>

                  {!isGuidedSurface && (outlineRuntimeItems.length > 0 || outlineCustomerItems.length > 0) && (
                    <details className="outline-more outline-surface-card outline-surface-card--sources">
                      <summary>More sources</summary>
                      {outlineRuntimeItems.length > 0 && (
                        <div className="outline-group">
                          <div className="outline-group-title">All Runtime Books</div>
                          {outlineRuntimeItems.slice(0, 10).map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              className={`outline-item ${item.tone === 'muted' ? 'muted' : ''}`}
                              onClick={item.action}
                            >
                              <span className="outline-item-label">{item.label}</span>
                              {item.meta && <span className="outline-item-meta">{item.meta}</span>}
                            </button>
                          ))}
                        </div>
                      )}
                      {outlineCustomerItems.length > 0 && (
                        <div className="outline-group">
                          <div className="outline-group-title">Customer Packs</div>
                          {outlineCustomerItems.map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              className={`outline-item ${item.tone === 'muted' ? 'muted' : ''}`}
                              onClick={item.action}
                            >
                              <span className="outline-item-label">{item.label}</span>
                              {item.meta && <span className="outline-item-meta">{item.meta}</span>}
                            </button>
                          ))}
                        </div>
                      )}
                    </details>
                  )}
                    </>
                  )}
                </div>
              ) : (
                <div className="signals-panel">
                  <section className="signals-card cluster-signals-card">
                    <div className="signals-card-title">
                      <TerminalIcon size={14} />
                      <span>Cluster Operations</span>
                    </div>
                    {signalEvents.length === 0 ? (
                      <span className="signals-empty">CLI operation signal이 아직 없습니다.</span>
                    ) : (
                      <div className="cluster-signal-list">
                        {signalEvents.map((signal) => (
                          <article key={signal.id} className="cluster-signal-item">
                            <div className="cluster-signal-head">
                              <strong>{signal.operationType}</strong>
                              <span>{signal.status}</span>
                            </div>
                            <div className="cluster-signal-meta">
                              {signal.resourceKind}
                              {signal.resourceName ? ` · ${signal.resourceName}` : ''}
                              {signal.namespace ? ` · ${signal.namespace}` : ''}
                            </div>
                            <code>{signal.sourceCommand}</code>
                            <time>{new Date(signal.timestamp).toLocaleTimeString()}</time>
                          </article>
                        ))}
                      </div>
                    )}
                  </section>
                  {false && (
                    <>
                  {(isOverlayLoading || isOverlaySaving) && <div className="signals-status">syncing</div>}
                  <div className="signals-card">
                    <div className="signals-card-title">
                      <Clock3 size={14} />
                      <span>Recent Position</span>
                    </div>
                    <div className="signals-chip-list">
                      {isOverlayLoading ? <span className="signals-empty">불러오는 중</span> : recentOverlayItems.length > 0 ? recentOverlayItems.map((item) => (
                        <button
                          key={item.overlay_id}
                          type="button"
                          className="signals-chip"
                          onClick={() => { void handleOverlayJump(item); }}
                          title={item.target_ref}
                        >
                          {getSignalDisplayTitle(item)}
                        </button>
                      )) : <span className="signals-empty">아직 기록이 없습니다.</span>}
                    </div>
                  </div>
                  <div className="signals-card">
                    <div className="signals-card-title">
                      <Star size={14} />
                      <span>Favorites</span>
                    </div>
                    <div className="signals-card-filters">
                      <button
                        type="button"
                        className={`signals-filter-btn ${signalsFavoriteFilter === 'favorites' ? 'active' : ''}`}
                        onClick={() => setSignalsFavoriteFilter('favorites')}
                      >
                        즐겨찾기
                      </button>
                      <button
                        type="button"
                        className={`signals-filter-btn ${signalsFavoriteFilter === 'edited' ? 'active' : ''}`}
                        onClick={() => setSignalsFavoriteFilter('edited')}
                      >
                        수정한 것
                      </button>
                    </div>
                    <div className="signals-chip-list">
                      {isOverlayLoading ? <span className="signals-empty">불러오는 중</span> : favoriteOverlayItems.length > 0 ? favoriteOverlayItems.map((item) => (
                        <button
                          key={item.overlay_id}
                          type="button"
                          className="signals-chip"
                          onClick={() => { void handleOverlayJump(item); }}
                          title={item.target_ref}
                        >
                          {getSignalDisplayTitle(item)}
                        </button>
                      )) : <span className="signals-empty">{signalsFavoriteFilter === 'edited' ? '수정본이 없습니다.' : '즐겨찾기가 없습니다.'}</span>}
                    </div>
                  </div>
                  <div className="signals-card">
                    <div className="signals-card-title">
                      <ArrowRight size={14} />
                      <span>Next</span>
                    </div>
                    <div className="signals-chip-list">
                      {isOverlayLoading ? <span className="signals-empty">불러오는 중</span> : nextPlayItems.length > 0 ? nextPlayItems.map((item, index) => (
                        <button
                          key={`${item.source_target_ref}-${item.href}-${index}`}
                          type="button"
                          className="signals-chip"
                          title={item.reason}
                          onClick={() => { void handleRelatedLinkClick(item); }}
                        >
                          {item.label}
                        </button>
                      )) : <span className="signals-empty">없음</span>}
                    </div>
                  </div>
                    </>
                  )}
                </div>
              )}

              <div className="user-profile-section">
                <div className="profile-container profile-container-ops">
                  <div className="profile-avatar profile-avatar-ops">
                    <Cpu size={18} />
                    <div className={`status-dot-online ${isClusterConnected ? '' : 'status-dot-idle'}`}></div>
                  </div>
                  <div className="profile-ops-summary">
                    <button
                      className={`profile-ops-name-btn ${activeFooterConnection ? '' : 'is-undefined'}`}
                      type="button"
                      onClick={() => setDashboardOpen(true)}
                      title={activeFooterConnection ? 'Open cluster dashboard' : 'Cluster is not connected'}
                    >
                      {isFooterProfileLoading ? 'Syncing' : footerProfileName}
                    </button>
                    <span className={`profile-cluster-status profile-cluster-status--${clusterConnectionStatus}`}>
                      {clusterStatusLabel}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </Panel>

          <Separator className="custom-resize-handle">
            <div className="handle-visual" />
          </Separator>

          {/* ── Center Panel: Chat ── */}
          <Panel id="workspace-center" defaultSize={46} minSize={30} className="workspace-panel-item">
            <div className="panel-inner chat-area">
              {(leftCollapsed || rightCollapsed) && (
                <div className="chat-panel-toolbar">
                  {leftCollapsed && (
                    <button className="panel-reopen-btn" type="button" onClick={toggleLeftPanel} title="Open sidebar">
                      <PanelLeftClose size={16} />
                    </button>
                  )}
                  <div className="chat-panel-toolbar-spacer" />
                  {rightCollapsed && (
                    <button className="panel-reopen-btn" type="button" onClick={toggleRightPanel} title="Open panel">
                      <PanelRightClose size={16} />
                    </button>
                  )}
                </div>
              )}
              {ingestionStatusBanner && (
                <div className={`ingestion-status-banner ingestion-status-banner--${ingestionStatusBanner.status}`}>
                  <div>
                    <strong>{ingestionStatusBanner.message}</strong>
                    {ingestionStatusBanner.filename ? <span>{ingestionStatusBanner.filename}</span> : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setIngestionStatusBanner(null);
                      window.localStorage.removeItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY);
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              )}
              <div className="chat-mode-switch chat-mode-switch--top" role="tablist" aria-label="Chat mode">
                <button
                  type="button"
                  className={`chat-mode-btn ${currentMode === 'document' ? 'active' : ''}`}
                  onClick={() => setCurrentMode('document')}
                  aria-selected={currentMode === 'document'}
                >
                  <BookOpen size={14} />
                  Docs
                </button>
                <button
                  type="button"
                  className={`chat-mode-btn ${currentMode === 'live_cluster' ? 'active' : ''}`}
                  onClick={() => {
                    if (isLiveClusterAvailable) {
                      setCurrentMode('live_cluster');
                    }
                  }}
                  aria-selected={currentMode === 'live_cluster'}
                  disabled={!isLiveClusterAvailable}
                  title={
                    !isClusterConnected
                      ? 'Cluster is not connected'
                      : !isTerminalConnected
                        ? 'Terminal session is not connected'
                        : 'Live Cluster Mode'
                  }
                >
                  <Cpu size={14} />
                  Live
                </button>
                <span className={`chat-mode-status chat-mode-status--${clusterConnectionStatus}`}>
                  {isTerminalConnected ? clusterStatusLabel : 'Terminal offline'}
                </span>
              </div>
              <div className="chat-messages" ref={chatMessagesRef}>
                {messages.length === 0 && (
                  <div className="chat-welcome">
                    <div className="welcome-icon">
                      <Sparkles size={36} />
                    </div>
                    <h2 className="welcome-title">질문을 시작하세요</h2>
                    <p className="welcome-vision-copy">
                      공식 문서와 실운영 기준을 한 채팅에서 함께 확인합니다.
                    </p>
                    <div className="suggested-query-label welcome-route-label">시작 질문</div>
                    <div className="welcome-question-groups">
                      {welcomeQuestionGroups.map((group) => (
                        <section key={group.key} className={`welcome-question-group welcome-question-group--${group.key}`}>
                          <div className="welcome-question-group-heading">
                            <span>{group.title}</span>
                            <small>{group.description}</small>
                          </div>
                          <div className="welcome-question-stack">
                            {group.questions.map((item, i) => (
                              <button
                                key={`welcome-q-${group.key}-${i}`}
                                type="button"
                                className="welcome-question-card glass-panel"
                                onClick={() => {
                                  void handleSend(item.question, {
                                    forceCourseMode: item.lane === 'operations',
                                    routeKind: item.routeKind || (item.lane === 'learning' ? 'learning' : item.lane === 'operations' ? 'course' : 'official'),
                                    learningIndex: item.learningIndex,
                                    categoryKey: item.categoryKey,
                                    categoryLabel: item.categoryLabel,
                                    targetBookSlug: item.targetBookSlug,
                                    targetTitle: item.targetTitle,
                                    targetViewerPath: item.targetViewerPath,
                                    learningPathId: item.learningPathId,
                                    learningStepId: item.learningStepId,
                                    labTaskId: item.labTaskId,
                                  });
                                }}
                                disabled={isSending}
                              >
                                <span className={`welcome-question-lane welcome-question-lane--${item.lane}`}>
                                  {group.title}
                                </span>
                                <span>{item.question}</span>
                              </button>
                            ))}
                          </div>
                        </section>
                      ))}
                    </div>
                    {(isBootstrapLoading || isWelcomeQuestionLoading) && (
                      <div className="welcome-loading-hint">
                        <div className="loading-spinner-small"></div>
                        <span>runtime 문서와 시작 질문 동기화 중</span>
                      </div>
                    )}
                  </div>
                )}
                {visibleMessages.map((message) => (
                  <div key={message.id} className={`message-row ${message.role}`}>
                    <div className="message-bubble glass-panel">
                      <div className="message-content">
                        {message.role === 'assistant' ? (
                          <>
                            <AssistantAnswer
                              content={message.content}
                              citations={message.citations ?? []}
                              relatedLinks={message.relatedLinks ?? []}
                              relatedSections={message.relatedSections ?? []}
                              visionMode={visionMode}
                              primarySourceLane={message.primarySourceLane}
                              primaryBoundaryTruth={message.primaryBoundaryTruth}
                              primaryRuntimeTruthLabel={message.primaryRuntimeTruthLabel}
                              primaryBoundaryBadge={message.primaryBoundaryBadge}
                              primaryPublicationState={message.primaryPublicationState}
                              primaryApprovalState={message.primaryApprovalState}
                              onCitationClick={(citation) => {
                                handleCitationEvidenceToggle(message.id, citation);
                              }}
                              onRelatedLinkClick={(link) => {
                                void handleRelatedLinkClick(link);
                              }}
                              onToggleFavoriteLink={(link) => {
                                void handleToggleFavoriteLink(link);
                              }}
                              onCheckSectionLink={(link) => {
                                void handleToggleSectionCheckLink(link);
                              }}
                              isFavoriteLink={(link) => {
                                const target = overlayTargetFromLink(link);
                                return Boolean(target && overlayExists('favorite', target.ref));
                              }}
                              isCheckedSectionLink={(link) => {
                                const target = overlayTargetFromLink(link);
                                return Boolean(target && overlayExists('check', target.ref));
                              }}
                            />
                            {(isCourseMode || message.routeKind === 'course') && message.artifacts?.length ? (
                              <CourseChatArtifacts
                                artifacts={message.artifacts}
                                includeKinds={['course_image_evidence']}
                                disableLinks
                              />
                            ) : null}
                            {(() => {
                              const activeCitation = (message.citations ?? []).find(
                                (citation) => citation.index === message.activeCitationIndex,
                              );
                              if (!activeCitation) {
                                return null;
                              }
                              return (
                                <div className="citation-evidence-preview">
                                  <div className="citation-evidence-header">
                                    <span className="citation-evidence-index">[{activeCitation.index}]</span>
                                    <div>
                                      <strong>{citationEvidenceTitle(activeCitation)}</strong>
                                      <p>{citationEvidenceMeta(activeCitation)}</p>
                                    </div>
                                  </div>
                                  {activeCitation.excerpt ? (
                                    <blockquote>{activeCitation.excerpt}</blockquote>
                                  ) : null}
                                  {activeCitation.cli_commands?.length ? (
                                    <div className="citation-evidence-command">
                                      <span>Command</span>
                                      <code>{activeCitation.cli_commands[0]}</code>
                                    </div>
                                  ) : null}
                                  <div className="citation-evidence-actions">
                                    <button
                                      type="button"
                                      onClick={() => { void openCitationEvidenceDrawer(activeCitation, message.content); }}
                                    >
                                      Open document
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleCitationEvidenceToggle(message.id, activeCitation)}
                                    >
                                      Close
                                    </button>
                                  </div>
                                </div>
                              );
                            })()}
                          </>
                        ) : (
                          message.content
                        )}
                      </div>
                      {message.role !== 'assistant' && message.citations && message.citations.length > 0 && (
                        <div className="message-tags">
                          {message.citations.map((citation) => (
                            <CitationTag
                              key={`${message.id}-${citation.index}`}
                              citation={citation}
                              onOpen={(selected) => { void openCitationEvidenceDrawer(selected, message.content); }}
                            />
                          ))}
                        </div>
                      )}
                      {message.role === 'assistant' && message.suggestedQueries && message.suggestedQueries.length > 0 && (
                        <div className="suggested-query-group">
                          <div className="suggested-query-label">{isGuidedSurface ? '다음 경로' : '이런 질문은 어떠세요?'}</div>
                          <div className={isGuidedSurface ? 'suggested-query-list guided-tour-query-list' : 'suggested-query-list'}>
                            {message.suggestedQueries.map((suggestedQuery, suggestedIndex) => (
                              <button
                                key={`${message.id}-suggested-${suggestedIndex}`}
                                className={isGuidedSurface ? 'suggested-query-chip guided-tour-query-chip' : 'suggested-query-chip'}
                                type="button"
                                onClick={() => {
                                  const suggestedMeta = message.routeKind === 'learning'
                                    ? learningQuestionByText.get(suggestedQuery.trim())
                                    : undefined;
                                  void handleSend(suggestedQuery, {
                                    forceCourseMode: message.routeKind === 'course' || isCourseSourceLane(message.primarySourceLane),
                                    routeKind: message.routeKind === 'learning' ? 'learning' : undefined,
                                    learningIndex: suggestedMeta?.learningIndex,
                                    categoryKey: suggestedMeta?.categoryKey,
                                    categoryLabel: suggestedMeta?.categoryLabel,
                                    targetBookSlug: suggestedMeta?.targetBookSlug,
                                    targetTitle: suggestedMeta?.targetTitle,
                                    targetViewerPath: suggestedMeta?.targetViewerPath,
                                    learningPathId: suggestedMeta?.learningPathId,
                                    learningStepId: suggestedMeta?.learningStepId,
                                    labTaskId: suggestedMeta?.labTaskId,
                                  });
                                }}
                                disabled={isSending}
                              >
                                {isGuidedSurface && (
                                  <span className="guided-tour-query-index">{suggestedIndex + 1}</span>
                                )}
                                {suggestedQuery}
                                {isGuidedSurface && (
                                  <span className="guided-tour-query-arrow">
                                    <ArrowRight size={12} />
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {message.role === 'assistant' && message.acquisition && (
                        <NoAnswerAcquisitionCard
                          acquisition={message.acquisition}
                          onConfirm={handleAcquisitionConfirm}
                        />
                      )}
                    </div>
                  </div>
                ))}

                {showThinkingIndicator && <ThinkingIndicator />}

                <div ref={scrollAnchorRef} />
              </div>

              {userScrolledUp && messages.length > 0 && (
                <button
                  className="scroll-to-bottom-btn"
                  type="button"
                  onClick={scrollToBottom}
                >
                  <ArrowDown size={18} />
                </button>
              )}

              <div className="chat-input-wrapper">
                {(activeRepository || activeDocumentId) && (
                  <div className="chat-scope-status">
                    <BookOpen size={14} />
                    <div>
                      <span>{activeDocumentId ? 'Document-scoped RAG' : 'Repository-scoped RAG'}</span>
                      <strong>
                        {activeDocumentId
                          ? activeDocumentScopeLabel
                          : activeRepository?.title || activeRepository?.slug || 'Active repository'}
                      </strong>
                      {activeDocumentId && activeCategoryLabel ? (
                        <small>{activeCategoryLabel}</small>
                      ) : null}
                      {activeDocumentId && activeNextLearningDocuments.length ? (
                        <div className="chat-scope-next">
                          <span>다음 학습</span>
                          {activeNextLearningDocuments.map((document) => (
                            <button
                              key={document.document_source_id}
                              type="button"
                              onClick={() => selectActiveDocumentScope(document)}
                              title="이 문서만 범위로 설정합니다"
                            >
                              {document.title || document.filename || 'Next document'}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      className="chat-scope-clear-btn"
                      onClick={activeDocumentId ? clearActiveDocumentScope : clearActiveRepositoryScope}
                      title={activeDocumentId ? '문서 범위를 해제하고 repository 전체로 질문합니다' : 'Repository 범위를 해제하고 전체 문서에서 질문합니다'}
                      aria-label={activeDocumentId ? 'Clear document scope' : 'Clear repository scope'}
                    >
                      <X size={14} />
                      <span>{activeDocumentId ? '문서 범위 해제' : 'Repository 범위 해제'}</span>
                    </button>
                  </div>
                )}
                <div className="input-container glass-panel">
                  <input
                    type="text"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={handleInputKeyDown}
                    placeholder={isGuidedSurface ? '질문을 던지면 문서 투어를 엽니다...' : '질문을 입력하거나 문서를 탐색하세요...'}
                    disabled={isSending}
                  />
                  <button className="send-btn" onClick={() => { void handleSend(); }} type="button" disabled={isSending}>
                    <Send size={18} />
                  </button>
                </div>
              </div>
            </div>
          </Panel>

          <Separator className="custom-resize-handle">
            <div className="handle-visual" />
          </Separator>

          {/* ── Right Panel: Runtime Sources + Overlay ── */}
          <WorkspaceViewerPanel
            panelRef={rightPanelRef}
            annotationColorId={annotationColorId}
            annotationEnabled={annotationEnabled}
            annotationTool={annotationTool}
            atlasCanvasActive={visionMode === 'atlas_canvas' && viewerPageMode === 'multi'}
            savedInkStrokes={currentInkStrokes}
            isInkSaving={isOverlaySaving}
            isPanelResizing={isPanelResizing}
            rightCollapsed={rightCollapsed}
            testMode={testMode}
            viewerSurfaceMode={rightPanelMode}
            viewerSurfaceTitle={viewerSurfaceTitle}
            sourcesDrawerOpen={sourcesDrawerOpen}
            fileInputRef={fileInputRef}
            headerToolbar={viewerHeaderToolbar}
            inkSurfaceKey={currentOverlayTarget?.ref || currentViewerPath || (activeDraft ? `draft:${activeDraft.draft_id}` : `preview:${preview.kind}`)}
            textAnnotationMode={textAnnotationMode}
            textAnnotationStyle={annotationTextStyle}
            uploadAccept={DOCUMENT_INGEST_UPLOAD_ACCEPT}
            onAnnotationColorChange={setAnnotationColorId}
            onAnnotationEnabledChange={setAnnotationEnabled}
            onAnnotationToolChange={setAnnotationTool}
            onRightPanelCollapsedChange={setRightCollapsed}
            onTextAnnotationModeChange={setTextAnnotationMode}
            onTextAnnotationStyleChange={setAnnotationTextStyle}
            onToggleRightPanel={toggleRightPanel}
            onToggleSourcesDrawer={() => setSourcesDrawerOpen((prev) => !prev)}
            onSaveInk={(strokes) => {
              void handleSaveCurrentInk(strokes);
            }}
            onUploadSelection={(event) => {
              void handleUploadSelection(event);
            }}
            drawerContent={(
              <div className="source-list">
                <div className={`source-section ${collapsedSections.manuals ? 'collapsed' : ''}`}>
                  <button className="section-header-btn" onClick={() => toggleSection('manuals')} type="button">
                    <div className="header-label-group">
                      {collapsedSections.manuals ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      <span className="list-title">{isGuidedSurface ? 'Tour Books' : 'Source Books'}</span>
                    </div>
                    <span className="item-count-badge">{manualSources.length}</span>
                  </button>
                  {!collapsedSections.manuals && (
                    <div className="section-items-container">
                      {manualSources.map((file) => (
                        <div
                          key={file.id}
                          className={`source-item ${activeSourceId === file.id ? 'selected' : ''}`}
                          onClick={() => { void handleSourceClick(file); }}
                        >
                          <div className="item-main">
                            <FileText size={16} className="file-icon" />
                            <div className="item-main-copy">
                              <span className="file-name">{file.name}</span>
                              {file.grade ? (
                                <span className={playbookGradeBadgeClass(file.grade)}>
                                  {normalizePlaybookGrade(file.grade)}
                                </span>
                              ) : null}
                            </div>
                          </div>
                          <div className="item-meta">{file.meta}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className={`source-section ${collapsedSections.drafts ? 'collapsed' : ''}`}>
                  <button className="section-header-btn" onClick={() => toggleSection('drafts')} type="button">
                    <div className="header-label-group">
                      {collapsedSections.drafts ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      <span className="list-title">{isGuidedSurface ? 'Added Sources' : 'Customer Packs'}</span>
                    </div>
                    <span className="item-count-badge">{draftSources.length}</span>
                  </button>
                  {!collapsedSections.drafts && (
                    <div className="section-items-container">
                      {draftSources.map((file) => (
                        <div
                          key={file.id}
                          className={`source-item ${activeSourceId === file.id ? 'selected' : ''}`}
                          onClick={() => { void handleSourceClick(file); }}
                        >
                          <div className="item-main">
                            <FileText size={16} className="file-icon" />
                            <span className="file-name">{file.name}</span>
                          </div>
                          <div className="item-meta">{file.meta}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className={`source-section ${collapsedSections.repositories ? 'collapsed' : ''}`}>
                  <button className="section-header-btn" onClick={() => toggleSection('repositories')} type="button">
                    <div className="header-label-group">
                      {collapsedSections.repositories ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      <span className="list-title">Document Repositories</span>
                    </div>
                    <span className="item-count-badge">{repositorySources.length}</span>
                  </button>
                  {!collapsedSections.repositories && (
                    <div className="section-items-container">
                      {repositorySources.length === 0 ? (
                        <div className="source-item source-item-muted">
                          <div className="item-main">
                            <BookOpen size={16} className="file-icon" />
                            <span className="file-name">No DB repositories</span>
                          </div>
                          <div className="item-meta">Upload documents from Playbook Library.</div>
                        </div>
                      ) : repositorySources.map((file) => (
                        <div
                          key={file.id}
                          className={`source-item ${activeSourceId === file.id ? 'selected' : ''}`}
                          onClick={() => { void handleSourceClick(file); }}
                        >
                          <div className="item-main">
                            <BookOpen size={16} className="file-icon" />
                            <span className="file-name">{file.name}</span>
                          </div>
                          <div className="item-meta">{file.meta}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          >
            {rightPanelMode === 'terminal' ? (
              <TerminalSessionPanel
                learningContext={terminalLearningContext}
                onCommandSubmitted={handleTerminalCommandSubmitted}
                onSessionStateChange={setTerminalConnectionState}
              />
            ) : (
              <>
            {testMode && (
              <WorkspaceTracePanel
                query={activeTestTrace?.query ?? query}
                events={activeTestTrace?.events ?? []}
                result={activeTestTrace?.result}
                isSending={isSending}
              />
            )}

            {!testMode && preview.kind === 'empty' && (
              <div className="empty-state">
                <div className="empty-icon"><BookOpen size={48} className="text-dim" /></div>
                <h4>{isGuidedSurface ? '투어 문서를 여세요' : '문서를 선택하세요'}</h4>
              </div>
            )}

            {!testMode && preview.kind === 'loading' && (
              <div className="empty-state">
                <div className="loading-spinner-small"></div>
                <h4>{preview.title}</h4>
                <p>{isGuidedSurface ? 'Tour is opening' : 'Loading'}</p>
              </div>
            )}

            {!testMode && preview.kind === 'viewer' && (
              <section className="reader-stage animate-in">
                {preview.viewerDocument?.html ? (
                  <ViewerDocumentStage
                    viewerDocument={preview.viewerDocument}
                    currentViewerPath={currentViewerPath}
                    scrollTargetText={preview.scrollTargetText}
                    suspendActiveSectionTracking={isPanelResizing}
                    onActiveSectionChange={viewerPageMode === 'multi' ? setViewerActiveSection : undefined}
                    onNavigateViewerPath={(viewerPath) => {
                      void openViewerPreview(viewerPath, preview.title, undefined, viewerPageMode);
                    }}
                    textAnnotationsByAnchor={sectionTextAnnotationsByAnchor}
                    textToolEnabled={annotationEnabled && annotationTool === 'text' && viewerPageMode === 'multi' && visionMode === 'atlas_canvas'}
                    textToolMode={textAnnotationMode}
                    activeTextStyle={annotationTextStyle}
                    onSaveTextAnnotation={(section, annotation) => {
                      void handleUpsertSectionTextAnnotation(section, annotation);
                    }}
                    onRemoveTextAnnotation={(section, annotationId) => {
                      void handleRemoveSectionTextAnnotation(section, annotationId);
                    }}
                    className="playbook-reader-shadow-host"
                  />
                ) : (
                  <div className="playbook-reader-empty">문서 본문을 불러오지 못했습니다.</div>
                )}
              </section>
            )}

            {!testMode && preview.kind === 'draft' && (() => {
              const draftTruth = truthSurfaceCopy(preview.book ?? preview.draft);
              return (
                <section className="reader-stage reader-stage-draft animate-in">
                  <div className="doc-header">
                    <div className="doc-header-text">
                      <span className="doc-kicker">{draftTruth.label}</span>
                      <h2>{preview.title}</h2>
                    </div>
                  </div>
                  <p className="doc-summary">{preview.subtitle}</p>
                  <div className="doc-metadata">
                    <span>Quality {preview.draft.quality_score}</span>
                    <span>{preview.draft.playable_asset_count} assets</span>
                  </div>
                  {draftTruth.meta.length > 0 && (
                    <div className="doc-chip-row">
                      {draftTruth.meta.map((item) => (
                        <span key={item} className="doc-evidence-chip">{item}</span>
                      ))}
                    </div>
                  )}
                  {preview.derivedAssets.length > 0 && (
                    <div className="doc-chip-row">
                      {preview.derivedAssets.map((asset) => (
                        <button
                          key={asset.asset_slug}
                          className="citation-tag"
                          onClick={() => handleDerivedAssetOpen(asset)}
                          type="button"
                        >
                          <LinkIcon size={12} />
                          {asset.family_label}
                        </button>
                      ))}
                    </div>
                  )}
                  {preview.viewerDocument?.html ? (
                    <ViewerDocumentStage
                      viewerDocument={preview.viewerDocument}
                      currentViewerPath={runtimePathFromUrl(preview.viewerUrl)}
                      suspendActiveSectionTracking={isPanelResizing}
                      onNavigateViewerPath={(viewerPath) => {
                        void openViewerPreview(viewerPath, preview.title, undefined, viewerPageMode);
                      }}
                      className="playbook-reader-shadow-host"
                    />
                  ) : (
                    <div className="doc-section">
                      <h4>Status</h4>
                      <p>{preview.draft.status}</p>
                    </div>
                  )}
                </section>
              );
            })()}

            {activeRepository && (
              <div className="panel-footer viewer-build-actions">
                <div className="footer-actions">
                  <button className="outline-btn" type="button" onClick={() => navigate(ROUTES.pbsRepository)}>
                    <BookOpen size={14} />
                    <span>{activeRepository.document_count} docs</span>
                  </button>
                  <button className="primary-btn" type="button" onClick={() => setSourcesDrawerOpen(true)}>
                    <span>{activeRepository.title || activeRepository.slug}</span>
                    <Check size={14} />
                  </button>
                </div>
              </div>
            )}

            {activeDraft && (
              <div className="panel-footer viewer-build-actions">
                <div className="footer-actions">
                  <button className="outline-btn" onClick={() => { void handleCapture(); }} type="button" disabled={!canCapture}>
                    <Cpu size={14} />
                    <span>{isCapturing ? 'Preparing...' : 'Prepare Pack'}</span>
                  </button>
                  <button className="primary-btn" onClick={() => { void handleNormalize(); }} type="button" disabled={!canNormalize}>
                    <span>{isNormalizing ? 'Saving...' : 'Save to Wiki'}</span>
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            )}
              </>
            )}
          </WorkspaceViewerPanel>
        </Group>
        {evidenceDrawer.kind !== 'closed' && (
          <div className="evidence-drawer-layer">
            <button
              className="evidence-drawer-scrim"
              type="button"
              aria-label="Close evidence document"
              onClick={() => setEvidenceDrawer({ kind: 'closed' })}
            />
            <aside className="evidence-drawer" aria-label="Citation evidence document">
              <header className="evidence-drawer-header">
                <div>
                  <span>Evidence document</span>
                  <h3>{evidenceDrawer.title}</h3>
                  {evidenceDrawer.kind === 'viewer' && evidenceDrawer.subtitle ? (
                    <p>{evidenceDrawer.subtitle}</p>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="evidence-drawer-close"
                  onClick={() => setEvidenceDrawer({ kind: 'closed' })}
                >
                  Close
                </button>
              </header>
              <div className="evidence-drawer-body">
                {evidenceDrawer.kind === 'loading' && (
                  <div className="empty-state">
                    <div className="loading-spinner-small"></div>
                    <h4>Loading evidence</h4>
                  </div>
                )}
                {evidenceDrawer.kind === 'error' && (
                  <div className="empty-state">
                    <h4>Evidence unavailable</h4>
                    <p>{evidenceDrawer.message}</p>
                  </div>
                )}
                {evidenceDrawer.kind === 'viewer' && (
                  <ViewerDocumentStage
                    viewerDocument={evidenceDrawer.viewerDocument}
                    currentViewerPath={evidenceDrawer.viewerPath}
                    scrollTargetText={evidenceDrawer.scrollTargetText}
                    suspendActiveSectionTracking={isPanelResizing}
                    onNavigateViewerPath={(viewerPath) => {
                      void openEvidenceDrawerPath(evidenceDrawer.title, viewerPath);
                    }}
                    className="playbook-reader-shadow-host evidence-drawer-reader"
                  />
                )}
              </div>
            </aside>
          </div>
        )}
        {(resourceYamlDetail || isResourceYamlLoading) && (
          <div className="cluster-yaml-modal-layer">
            <button
              className="cluster-yaml-modal-scrim"
              type="button"
              aria-label="Close resource YAML"
              onClick={() => setResourceYamlDetail(null)}
            />
            <section className="cluster-yaml-modal" role="dialog" aria-modal="true" aria-label="Cluster resource YAML">
              <header className="cluster-yaml-modal-head">
                <div>
                  <span>Resource YAML</span>
                  <h3>{resourceYamlDetail?.name || 'Loading resource'}</h3>
                  {resourceYamlDetail ? <p>{resourceYamlDetail.kind} · {resourceYamlDetail.namespace}</p> : null}
                </div>
                <button type="button" onClick={() => setResourceYamlDetail(null)}>Close</button>
              </header>
              {isResourceYamlLoading ? (
                <div className="outline-empty">
                  <div className="loading-spinner-small"></div>
                  <p>Loading YAML</p>
                </div>
              ) : (
                <pre className="cluster-yaml-modal-body">{resourceYamlDetail?.manifest_yaml || ''}</pre>
              )}
            </section>
          </div>
        )}
        {dashboardOpen && (
          <div className="cluster-yaml-modal-layer">
            <button
              className="cluster-yaml-modal-scrim"
              type="button"
              aria-label="Close dashboard"
              onClick={() => setDashboardOpen(false)}
            />
            <section className="dashboard-modal" role="dialog" aria-modal="true" aria-label="Cluster Dashboard">
              <header className="cluster-yaml-modal-head">
                <div>
                  <span>Dashboard</span>
                  <h3>{activeFooterConnection?.display_name || 'Cluster Dashboard'}</h3>
                  <p>{isClusterConnected ? activeFooterConnection?.cluster_url : 'Cluster가 연결되어 있지 않습니다.'}</p>
                </div>
                <div className="dashboard-modal-actions">
                  <button type="button" onClick={() => { void refreshDashboard(); }} disabled={isDashboardLoading || !isClusterConnected}>
                    {isDashboardLoading ? 'Loading' : 'Refresh'}
                  </button>
                  <button type="button" onClick={() => setDashboardOpen(false)}>Close</button>
                </div>
              </header>
              <div className="dashboard-modal-body">
                {!isClusterConnected ? (
                  <div className="outline-empty"><p>Cluster가 연결되어 있지 않습니다.</p></div>
                ) : dashboardError ? (
                  <div className="outline-empty"><p>{dashboardError}</p></div>
                ) : isDashboardLoading ? (
                  <div className="outline-empty">
                    <div className="loading-spinner-small"></div>
                    <p>Loading cluster dashboard</p>
                  </div>
                ) : (
                  <>
                    <div className="dashboard-summary-grid">
                      <article>
                        <span>Health</span>
                        <strong>{dashboardMetrics?.source.live ? 'Live' : dashboardMetrics ? 'Available' : 'Unavailable'}</strong>
                        <small>{dashboardMetrics?.source.provider || 'no metric source'}</small>
                      </article>
                      <article>
                        <span>Namespaces</span>
                        <strong>{dashboardOverview?.namespace_count ?? '-'}</strong>
                        <small>{dashboardOverview?.default_namespace || selectedResourceNamespace}</small>
                      </article>
                      <article>
                        <span>Warnings</span>
                        <strong>{dashboardMetrics?.summary.warning_events ?? '-'}</strong>
                        <small>recent events</small>
                      </article>
                      <article>
                        <span>Degraded</span>
                        <strong>{dashboardMetrics?.summary.degraded_deployments ?? '-'}</strong>
                        <small>deployments</small>
                      </article>
                    </div>
                    <div className="dashboard-section-grid">
                      <section>
                        <h4>Resource Summary</h4>
                        <div className="dashboard-resource-list">
                          {Object.entries(dashboardOverview?.resource_counts ?? {}).length === 0 ? (
                            <span className="signals-empty">Resource summary unavailable.</span>
                          ) : Object.entries(dashboardOverview?.resource_counts ?? {}).map(([kind, count]) => (
                            <div key={kind}>
                              <span>{kind}</span>
                              <strong>{count}</strong>
                            </div>
                          ))}
                        </div>
                      </section>
                      <section>
                        <h4>Recent Signals</h4>
                        <div className="dashboard-signal-list">
                          {signalEvents.slice(0, 5).length === 0 ? (
                            <span className="signals-empty">CLI signal이 아직 없습니다.</span>
                          ) : signalEvents.slice(0, 5).map((signal) => (
                            <div key={signal.id}>
                              <strong>{signal.operationType}</strong>
                              <span>{signal.resourceKind}{signal.resourceName ? ` · ${signal.resourceName}` : ''}</span>
                            </div>
                          ))}
                        </div>
                      </section>
                    </div>
                  </>
                )}
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
