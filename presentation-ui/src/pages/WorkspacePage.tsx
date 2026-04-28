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
} from 'lucide-react';
import gsap from 'gsap';
import './WorkspacePage.css';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import {
  CUSTOMER_PACK_UPLOAD_ACCEPT,
  type ChatResponse,
  type ChatCitation,
  type ChatRelatedLink,
  type CustomerPackBook,
  type CustomerPackDraft,
  type DerivedAsset,
  type LibraryBook,
  type SessionSummary,
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
  captureCustomerPackDraft,
  formatBytes,
  listCustomerPackDrafts,
  listSessions,
  loadCustomerPackBook,
  loadCustomerPackDraft,
  loadDataControlRoom,
  loadWikiOverlaySignals,
  loadWikiOverlays,
  loadSession,
  deleteAllSessions,
  deleteSession,
  loadSourceMeta,
  loadViewerDocument,
  normalizeViewerPath,
  normalizeCustomerPackDraft,
  removeWikiOverlay,
  saveWikiOverlay,
  sendChat,
  sendChatStream,
  toRuntimeUrl,
  uploadCustomerPackDraft,
} from '../lib/runtimeApi';
import {
  listOcpProfiles,
  type OcpConnection,
} from '../lib/opsConsoleApi';
import { ROUTES } from '../app/routes';
import { sendCourseChatStream } from '../lib/courseApi';
import { WIKI_VISION_MODES, loadStoredVisionMode, persistVisionMode, type VisionMode } from '../lib/wikiVision';
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

type LeftPanelMode = 'history' | 'outline' | 'signals';
type SignalsFavoriteFilter = 'favorites' | 'edited';
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

const STARTER_QUESTION_POOL = [
  '운영 입문 기준으로 먼저 봐야 할 플레이북 3개 알려줘',
  'Operator 장애가 났을 때 monitoring과 operators 문서를 어떻게 같이 따라가야 하나?',
  '클러스터 네트워크 MTU 변경 전후에 어떤 절차와 검증을 확인해야 하나?',
  '인증 문제와 Ingress 노출 문제를 같이 볼 때 어떤 책 순서로 확인해야 하나?',
  '연결이 끊긴 환경에서 미러 레지스트리 설정을 점검할 때 운영자가 먼저 볼 문서는 무엇인가?',
  '특정 namespace에 admin 권한을 주려면 어떤 절차를 먼저 확인해야 하나?',
  '프로젝트가 Terminating에서 안 지워질 때 어떤 순서로 확인해야 하나?',
  '노드가 Ready가 아니거나 머신컨피그 적용이 늦을 때 어디부터 봐야 하나?',
  'Route나 Ingress 연결 문제를 점검할 때 먼저 볼 절차를 알려줘',
  '모니터링 알림이 쏟아질 때 운영자가 먼저 확인할 플레이북 순서를 알려줘',
  '클러스터 설치 후 Day-2 운영에서 먼저 읽어야 할 문서를 순서대로 알려줘',
  '인증서 갱신이나 만료 문제를 볼 때 먼저 확인할 책과 절차를 알려줘',
];

const COURSE_STARTER_QUESTION_POOL = [
  '아키텍처 설계는 어떤 순서로 보면 전체 구성이 이해돼?',
  '아키텍처 구성도에서 외부, DMZ, 내부망, 데이터베이스 영역은 어떻게 연결돼?',
  '성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?',
  '파이프라인이나 Pod가 Running 상태라는 건 화면에서 무엇으로 확인해?',
];

function pickRandomStarterQuestions(pool: string[], count: number): string[] {
  const shuffled = [...pool];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
  }
  return shuffled.slice(0, count);
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

function extractDraftIdFromViewerPath(viewerPath: string): string | null {
  const match = viewerPath.match(/\/playbooks\/customer-packs\/([^/]+)/);
  return match?.[1] ?? null;
}

const PACK_OPTIONS = [
  'OpenShift 4.20',
] as const;

const FALLBACK_CLUSTER_USER_LABEL = 'Undefined';

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
  const [packLabel, setPackLabel] = useState('OpenShift 4.20');
  const [packDropdownOpen, setPackDropdownOpen] = useState(false);
  const [manualBooks, setManualBooks] = useState<WorkspaceManualBook[]>([]);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [isBootstrapLoading, setIsBootstrapLoading] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState('');
  const [sessionId, setSessionId] = useState(() => makeId('ID'));
  const [testMode, setTestMode] = useState(false);
  const [activeTestTrace, setActiveTestTrace] = useState<WorkspaceTestTrace | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewState>({ kind: 'empty' });
  const [viewerPageMode, setViewerPageMode] = useState<ViewerPageMode>('single');
  const [isSending, setIsSending] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isNormalizing, setIsNormalizing] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    manuals: true,
    drafts: true,
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
  const [visionMode, setVisionMode] = useState<VisionMode>(() => loadStoredVisionMode());
  const isGuidedSurface = visionMode === 'guided_tour' || visionMode === 'course_study';
  const isCourseMode = visionMode === 'course_study';

  useEffect(() => {
    if (isCourseMode && testMode) {
      setTestMode(false);
    }
  }, [isCourseMode, testMode]);

  // Scroll + welcome
  const [userScrolledUp, setUserScrolledUp] = useState(false);

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
      const result = await listSessions();
      setSessionList(result.sessions);
    } catch (error) {
      console.error(error);
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

  const refreshFooterProfile = useCallback(async () => {
    setIsFooterProfileLoading(true);
    try {
      const connections = await listOcpProfiles(opsWorkspaceId);
      setFooterConnections(connections);
    } catch (error) {
      console.error(error);
    } finally {
      setIsFooterProfileLoading(false);
    }
  }, [opsWorkspaceId]);

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

  const welcomeQuestions = useMemo(
    () => pickRandomStarterQuestions(STARTER_QUESTION_POOL, 4),
    [],
  );
  const courseWelcomeQuestions = useMemo(
    () => pickRandomStarterQuestions(COURSE_STARTER_QUESTION_POOL, 4),
    [],
  );
  const displayedWelcomeQuestions = isCourseMode ? courseWelcomeQuestions : welcomeQuestions;
  const activeVision = useMemo(
    () => WIKI_VISION_MODES.find((mode) => mode.id === visionMode) ?? WIKI_VISION_MODES[0],
    [visionMode],
  );
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
    persistVisionMode(visionMode);
  }, [visionMode]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('workspace.outlineCategoryKey', outlineCategoryKey);
  }, [outlineCategoryKey]);

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

    function handleWheel(): void {
      requestAnimationFrame(() => {
        if (!el) return;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        setUserScrolledUp(!atBottom);
        if (atBottom) {
          el.classList.remove('scroll-locked');
        } else {
          el.classList.add('scroll-locked');
        }
      });
    }

    el.addEventListener('wheel', handleWheel, { passive: true });
    return () => el.removeEventListener('wheel', handleWheel);
  }, [refreshSessionList]);

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

  function openOpsRoute(path: string): void {
    navigate(path);
  }

  async function handleSessionResume(targetSessionId: string): Promise<void> {
    if (isLoadingSession) return;
    setIsLoadingSession(true);
    try {
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
    const confirmed = window.confirm('이 대화 기록을 삭제할까요?');
    if (!confirmed) {
      return;
    }
    setDeletingSessionId(targetSessionId);
    try {
      await deleteSession(targetSessionId);
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
    if (!packDropdownOpen) {
      return undefined;
    }

    function handleWindowPointerDown(event: MouseEvent): void {
      const target = event.target as HTMLElement | null;
      if (!target?.closest('.pack-selector-wrapper')) {
        setPackDropdownOpen(false);
      }
    }

    window.addEventListener('mousedown', handleWindowPointerDown);
    return () => {
      window.removeEventListener('mousedown', handleWindowPointerDown);
    };
  }, [packDropdownOpen]);

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
        const [room, draftPayload] = await Promise.all([
          loadDataControlRoom(),
          listCustomerPackDrafts(),
        ]);
        if (cancelled) {
          return;
        }

        const sourceBooks = resolveWorkspaceSourceBooks(room) as WorkspaceManualBook[];
        const nextDrafts = draftPayload.drafts ?? [];

        setPackLabel(room.active_pack.pack_label || 'OpenShift 4.20');
        setManualBooks(sourceBooks);
        setDrafts(nextDrafts);
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

  const activeDraft = useMemo(
    () => drafts.find((draft) => activeSourceId === `draft:${draft.draft_id}`) ?? null,
    [activeSourceId, drafts],
  );

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
          .then(() => refreshWikiOverlays())
          .catch((error) => console.error(error));
      }, 500);
      return () => window.clearTimeout(timer);
    }
    return;
  }, [currentOverlayTarget, refreshWikiOverlays]);

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
      animatePreviewPanel();
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '문서를 여는 중 오류가 발생했습니다.');
    }
  }

  async function handleCitationClick(citation: ChatCitation): Promise<void> {
    try {
      if (rightCollapsed) {
        rightPanelRef.current?.expand();
        setRightCollapsed(false);
      }
      const draftId = extractDraftIdFromViewerPath(citation.viewer_path);
      if (draftId) {
        await openDraftPreview(draftId, drafts, citation.viewer_path);
      } else {
        await openViewerPreview(
          citation.viewer_path,
          citation.source_label || citation.book_title || citation.section,
          undefined,
          viewerPageMode,
          firstCitationCommand(citation),
        );
      }
      if (!isCourseMode) {
        animatePreviewPanel();
      }
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '참조 원문을 여는 중 오류가 발생했습니다.');
    }
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
      const uploaded = await uploadCustomerPackDraft(file);
      setDrafts((current) => mergeDraft(uploaded, current));
      await openDraftPreview(uploaded.draft_id, mergeDraft(uploaded));
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

  async function handleSend(queryOverride?: string): Promise<void> {
    const trimmed = (queryOverride ?? query).trim();
    if (!trimmed || isSending) {
      return;
    }

    const nextUserMessage: Message = {
      id: makeId('user'),
      role: 'user',
      content: trimmed,
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
      };
      let response: ChatResponse;
      let courseAssistantMessageId = '';
      if (isCourseMode) {
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
          },
        ]);
        response = await sendCourseChatStream({
          message: trimmed,
          sessionId,
          userId: wikiOverlayUserId,
        }, (event) => {
          if (event.type === 'answer_delta') {
            streamedAnswer += event.delta;
            setMessages((current) => current.map((message) => (
              message.id === courseAssistantMessageId
                ? { ...message, content: streamedAnswer }
                : message
            )));
          }
        });
      } else if (testMode) {
        setActiveTestTrace({
          query: trimmed,
          sessionId,
          events: [],
          result: null,
        });
        response = await sendChatStream(requestPayload, (event) => {
          if (event.type === 'trace') {
            setActiveTestTrace((current) => ({
              query: current?.query ?? trimmed,
              sessionId: current?.sessionId ?? sessionId,
              events: [...(current?.events ?? []), event],
              result: current?.result ?? null,
            }));
          }
          if (event.type === 'result') {
            setActiveTestTrace((current) => ({
              query: current?.query ?? trimmed,
              sessionId: event.payload.session_id || current?.sessionId || sessionId,
              events: current?.events ?? [],
              result: event.payload,
            }));
          }
        });
      } else {
        response = await sendChat(requestPayload);
      }
      const primaryTruth = primaryCitationTruth(response.citations);

      setSessionId(response.session_id || sessionId);
      const assistantMessage = {
          id: makeId('assistant'),
          role: 'assistant',
          content: response.answer,
          citations: response.citations ?? [],
          suggestedQueries: response.suggested_queries ?? [],
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
      } else {
        setMessages((current) => [...current, assistantMessage]);
      }
      if (testMode && !isCourseMode) {
        setActiveTestTrace((current) => ({
          query: current?.query ?? trimmed,
          sessionId: response.session_id || current?.sessionId || sessionId,
          events: response.pipeline_trace?.events ?? current?.events ?? [],
          result: response,
        }));
      }

      const primaryCitation = pickPrimaryPlaybookCitation(response.citations);
      if (primaryCitation && !isCourseMode) {
        await handleCitationClick(primaryCitation);
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
  const viewerSurfaceTitle = 'Wiki Viewer';
  const viewerHeaderToolbar = !testMode && currentOverlayTarget ? (
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
  return (
    <div className="workspace-wrapper" ref={containerRef} data-lenis-prevent>
      <div className="bokeh-bg bokeh-1"></div>
      <div className="bokeh-bg bokeh-2"></div>

      <WorkspaceHeader
        packDropdownOpen={packDropdownOpen}
        packLabel={packLabel}
        packOptions={PACK_OPTIONS}
        sessionId={sessionId}
        testMode={testMode}
        testModeDisabled={isCourseMode}
        globalTheme={globalTheme}
        onOpenLibrary={() => navigate('/playbook-library')}
        onResetSession={resetSession}
        onSelectPack={(label) => {
          setPackLabel(label);
          setPackDropdownOpen(false);
        }}
        onTogglePackDropdown={() => setPackDropdownOpen((prev) => !prev)}
        onToggleTestMode={() => setTestMode((current) => !current)}
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
                        {preview.kind !== 'empty' && <span>{preview.title}</span>}
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
                          <strong className="outline-toc-title">{preview.kind !== 'empty' ? preview.title : ''}</strong>
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
                </div>
              ) : (
                <div className="signals-panel">
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
                </div>
              )}

              <div className="user-profile-section">
                <div className="profile-container profile-container-ops">
                  <div className="profile-avatar profile-avatar-ops">
                    <Cpu size={18} />
                    <div className={`status-dot-online ${activeFooterConnection ? '' : 'status-dot-idle'}`}></div>
                  </div>
                  <div className="profile-ops-summary">
                    <button
                      className={`profile-ops-name-btn ${activeFooterConnection ? '' : 'is-undefined'}`}
                      type="button"
                      onClick={() => openOpsRoute(activeFooterConnection ? ROUTES.opsOverview : ROUTES.opsConnections)}
                      title={activeFooterConnection ? 'Open Ops Console' : 'Connect OpenShift cluster'}
                    >
                      {isFooterProfileLoading ? 'Syncing' : footerProfileName}
                    </button>
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
              <div className="chat-messages" ref={chatMessagesRef}>
                {messages.length === 0 && (
                  <div className="chat-welcome">
                    <div className="welcome-icon">
                      <Sparkles size={36} />
                    </div>
                    <h2 className="welcome-title">{isGuidedSurface ? '투어를 시작하세요' : '질문을 시작하세요'}</h2>
                    <p className="welcome-vision-copy">
                      {isGuidedSurface
                        ? '질문을 던지면 바로 읽을 절차와 이어서 열 문서를 한 경로로 엽니다.'
                        : activeVision.workspace.summary}
                    </p>
                    {isGuidedSurface ? (
                      <div className="welcome-vision-active">
                        <div className="welcome-vision-active-title">{activeVision.label} Active</div>
                        <p className="welcome-vision-active-copy">{activeVision.workspace.cue}</p>
                      </div>
                    ) : (
                      <div className="welcome-vision-grid">
                        {WIKI_VISION_MODES.map((mode) => (
                          <button
                            key={mode.id}
                            type="button"
                            className={`welcome-vision-card ${visionMode === mode.id ? 'active' : ''}`}
                            onClick={() => setVisionMode(mode.id)}
                          >
                            <strong>{mode.label}</strong>
                            <span>{mode.workspace.cue}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="suggested-query-label welcome-route-label">
                      {isGuidedSurface ? 'Start Tour' : '시작 질문'}
                    </div>
                    <div className={isGuidedSurface ? 'welcome-question-grid guided-welcome-grid' : 'welcome-question-grid'}>
                      {displayedWelcomeQuestions.map((q, i) => (
                        <button
                          key={`welcome-q-${i}`}
                          type="button"
                          className={isGuidedSurface ? 'welcome-question-card glass-panel guided-welcome-card' : 'welcome-question-card glass-panel'}
                          onClick={() => { void handleSend(q); }}
                          disabled={isSending}
                        >
                          {isGuidedSurface && (
                            <span className="guided-welcome-index">Step {i + 1}</span>
                          )}
                          {q}
                          {isGuidedSurface && (
                            <span className="guided-welcome-arrow">
                              <ArrowRight size={14} />
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                    {isBootstrapLoading && (
                      <div className="welcome-loading-hint">
                        <div className="loading-spinner-small"></div>
                        <span>runtime 문서 목록 동기화 중</span>
                      </div>
                    )}
                  </div>
                )}
                {messages.map((message) => (
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
                              visionMode={isCourseMode ? 'guided_tour' : visionMode}
                              primarySourceLane={message.primarySourceLane}
                              primaryBoundaryTruth={message.primaryBoundaryTruth}
                              primaryRuntimeTruthLabel={message.primaryRuntimeTruthLabel}
                              primaryBoundaryBadge={message.primaryBoundaryBadge}
                              primaryPublicationState={message.primaryPublicationState}
                              primaryApprovalState={message.primaryApprovalState}
                              onCitationClick={(citation) => {
                                void handleCitationClick(citation);
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
                            {isCourseMode && message.artifacts?.length ? (
                              <CourseChatArtifacts
                                artifacts={message.artifacts}
                                includeKinds={['course_image_evidence']}
                                disableLinks
                              />
                            ) : null}
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
                              onOpen={(selected) => { void handleCitationClick(selected); }}
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
                                onClick={() => { void handleSend(suggestedQuery); }}
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

                {isSending && <ThinkingIndicator />}

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
            rightCollapsed={rightCollapsed}
            testMode={testMode}
            viewerSurfaceTitle={viewerSurfaceTitle}
            sourcesDrawerOpen={sourcesDrawerOpen}
            fileInputRef={fileInputRef}
            headerToolbar={viewerHeaderToolbar}
            inkSurfaceKey={currentOverlayTarget?.ref || currentViewerPath || (activeDraft ? `draft:${activeDraft.draft_id}` : `preview:${preview.kind}`)}
            textAnnotationMode={textAnnotationMode}
            textAnnotationStyle={annotationTextStyle}
            uploadAccept={CUSTOMER_PACK_UPLOAD_ACCEPT}
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
              </div>
            )}
          >
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
          </WorkspaceViewerPanel>
        </Group>
      </main>
    </div>
  );
}
