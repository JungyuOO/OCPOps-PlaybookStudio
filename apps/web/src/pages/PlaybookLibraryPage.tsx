import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Database,
  Layers,
  Cpu,
  ShieldCheck,
  ShieldAlert,
  Search,
  Download,
  FileText,
  UploadCloud,
  Clock,
  Loader2,
  AlertCircle,
  HardDrive,
  BookOpen,
  Trash2,
  CheckCircle2,
  Star,
  ExternalLink,
  ChevronDown,
  BookmarkPlus,
  MessageSquare,
  X,
} from 'lucide-react';
import gsap from 'gsap';
import './PlaybookLibraryPage.css';
import AppHeader from '../components/AppHeader';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import { useGlobalTheme } from '../lib/globalTheme';
import {
  DOCUMENT_INGEST_UPLOAD_ACCEPT,
  type CustomerPackDraft,
  type CorpusChunkViewerResponse,
  type BuyerPacket,
  type DataControlRoomResponse,
  type LibraryBook,
  type LibraryBookSourceOption,
  type OfficialSourceCandidate,
  type OfficialSourceMaterializeResponse,
  type RepositoryCategory,
  type RepositoryFavorite,
  type RepositorySearchResult,
  type RepositoryUnansweredItem,
  type DocumentRepository,
  type DocumentRepositoryDocument,
  type UploadIngestResponse,
  type UploadIngestReport,
  type UploadIngestStreamStageEvent,
  type UploadIngestStreamEvent,
  deleteUploadedDocument,
  type ViewerPageMode,
  uploadDocumentIngestionStream,
  loadUploadIngestReport,
  loadDataControlRoom,
  loadDataControlRoomChunks,
  listCustomerPackDrafts,
  deleteCustomerPackDraft,
  loadCustomerPackBook,
  loadRepositoryFavorites,
  loadRepositoryUnanswered,
  loadDocumentRepositories,
  loadOfficialSourceCatalog,
  materializeOfficialSourceCandidate,
  removeRepositoryFavorite,
  searchRepositories,
  loadCustomerPackCapturedPreview,
  loadViewerDocument,
  toRuntimeUrl,
  formatBytes,
} from '../lib/runtimeApi';
import { ROUTES } from '../routing/routes';

type UserUploadStage = 'received' | 'store' | 'parse' | 'chunk' | 'persist' | 'index' | 'scope' | 'ready';
type PipelineStage = 'idle' | UserUploadStage | 'error';
type FactoryLane = 'tools' | 'user';
type FactoryRunMode = 'auto' | 'manual';
type OfficialSourceBasisKey = 'official_repo' | 'official_homepage';
const WORKSPACE_INGESTION_STATUS_STORAGE_KEY = 'workspace.ingestionStatus';
const WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY = 'workspace.activeDocumentId';
const WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY = 'workspace.activeDocumentTitle';
const WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY = 'workspace.activeCategoryKey';
const WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY = 'workspace.activeCategoryLabel';

interface LogEntry {
  time: string;
  tag: 'success' | 'info' | 'error' | 'warn';
  msg: string;
}

interface UploadProgressItem {
  key: string;
  stage: string;
  taskKind: string;
  label: string;
  message: string;
  current: number;
  total: number;
  percent: number;
  status: string;
}

interface UploadReportViewerState {
  title: string;
  documentSourceId: string;
  report: UploadIngestReport | null;
  loading: boolean;
  error: string;
}

type FactoryDownloadStatus = 'queued' | 'producing' | 'done' | 'error';

interface FactoryDownloadItem {
  id: string;
  requestQuery: string;
  record: OfficialSourceCandidate;
  option: LibraryBookSourceOption;
  friendlyLabel: string;
  status: FactoryDownloadStatus;
  savedAt: string;
  message?: string;
}

interface FactoryMaterializationSnapshot extends OfficialSourceMaterializeResponse {
  requestQuery: string;
  completedAt: string;
}

interface FactoryChecklistItem {
  id: string;
  stage: 'Bronze' | 'Silver' | 'Gold' | 'Judge';
  title: string;
  detail: string;
}


type MetricPopoverMode = 'playbook' | 'corpus';

interface MetricPopoverState {
  title: string;
  mode: MetricPopoverMode;
  rows: LibraryBook[];
}

interface ChunkViewerState {
  title: string;
  payload: CorpusChunkViewerResponse | null;
  loading: boolean;
  error: string;
}

function summaryNumber(summary: Record<string, unknown>, key: string): number | null {
  const raw = summary[key];
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return raw;
  }
  if (typeof raw === 'string') {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function buildFactoryManualChecklist(
  item: FactoryDownloadItem | null,
  snapshot: FactoryMaterializationSnapshot | null,
): FactoryChecklistItem[] {
  if (!item) {
    return [];
  }
  const sourceBasis = String(item.option.key || '').trim();
  const isRepo = sourceBasis === 'official_repo';
  const hasSnapshot = Boolean(snapshot);
  return [
    {
      id: 'bronze-source-proof',
      stage: 'Bronze',
      title: isRepo ? '공식 레포 경로와 slug 일치 확인' : '공식 웹페이지 원문 경로 확인',
      detail: isRepo ? 'source_repo / source_relative_path가 대상 질문과 맞는지 확인' : 'html-single 원문 URL과 대상 질문이 맞는지 확인',
    },
    {
      id: 'silver-structure-count',
      stage: 'Silver',
      title: '구조화 초안 수치 확인',
      detail: hasSnapshot ? 'sections / chunks 수가 기대 범위인지 확인' : '생산 후 sections / chunks 수를 확인',
    },
    {
      id: 'silver-terminology-lock',
      stage: 'Silver',
      title: isRepo ? '공식 KO 용어 꾸러미 적용 확인' : '공식 웹페이지 표현 유지 확인',
      detail: isRepo ? '고유명사 번역이 공식 표기와 일치하는지 확인' : '공식 KO 제목과 핵심 heading이 그대로 살아있는지 확인',
    },
    {
      id: 'gold-viewer-smoke',
      stage: 'Gold',
      title: 'Viewer landing smoke',
      detail: '문서가 실제 viewer에서 열리고 주요 절 이동이 되는지 확인',
    },
    {
      id: 'judge-library-join',
      stage: 'Judge',
      title: 'Library 합류 검증',
      detail: 'approved count, source meta, viewer ready 상태를 확인',
    },
  ];
}

function buildUserManualChecklist(
  draft: CustomerPackDraft | null,
  linkedBook: LibraryBook | null,
): FactoryChecklistItem[] {
  if (!draft) {
    return [];
  }
  const normalized = draft.status === 'normalized';
  return [
    {
      id: 'bronze-upload-proof',
      stage: 'Bronze',
      title: '업로드 원천과 캡처 상태 확인',
      detail: draft.capture_artifact_path
        ? '원본 파일과 캡처 아티팩트가 정상 저장됐는지 확인'
        : '캡처 아티팩트가 없으면 capture 단계부터 다시 확인',
    },
    {
      id: 'silver-parser-route',
      stage: 'Silver',
      title: '파서 경로와 구조화 품질 확인',
      detail: normalized
        ? 'parser backend, quality score, quality summary가 기대 범위인지 확인'
        : '정규화 전이면 parser route와 capture 결과부터 확인',
    },
    {
      id: 'silver-ocr-boundary',
      stage: 'Silver',
      title: draft.ocr_used ? 'OCR 사용 결과 검토' : 'OCR fallback 필요 여부 검토',
      detail: draft.ocr_used
        ? 'OCR이 개입한 경우 heading, 표, 코드블록 손실이 없는지 확인'
        : '구조 품질이 낮으면 OCR fallback이 필요한지 판단',
    },
    {
      id: 'gold-playbook-surface',
      stage: 'Gold',
      title: '플레이북/코퍼스 산출물 수 확인',
      detail: normalized
        ? 'playable asset, derived asset, quality summary가 viewer-grade에 가까운지 확인'
        : '정규화가 끝난 뒤 playable/derived asset 수를 확인',
    },
    {
      id: 'judge-user-library',
      stage: 'Judge',
      title: linkedBook ? 'User Library 합류 및 viewer 확인' : 'User Library 합류 대기 확인',
      detail: linkedBook
        ? 'viewer path, source lane, section count가 기대값과 맞는지 확인'
        : '아직 User Library 합류 전이면 normalize/save 결과를 다시 확인',
    },
  ];
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

const REPOSITORY_CATEGORIES: RepositoryCategory[] = [
  'Official Docs',
  'Enterprise Knowledge',
  'Operations Demo',
  'Troubleshooting',
];

const SUPPORTED_FORMATS = [
  { ext: 'PDF', via: 'MarkItDown' },
  { ext: 'DOCX', via: 'MarkItDown' },
  { ext: 'PPTX', via: 'MarkItDown' },
  { ext: 'XLSX', via: 'MarkItDown' },
  { ext: 'MD', via: 'Native' },
  { ext: 'TXT', via: 'Native' },
  { ext: 'AsciiDoc', via: 'Native' },
  { ext: 'HTML', via: 'Native' },
  { ext: 'Image', via: 'OCR' },
];

const WIKI_CATEGORIES = [
  { key: 'install', label: 'Install', terms: ['install', 'installation', 'installer', 'day-1', 'cluster installation'] },
  { key: 'operations', label: 'Operations', terms: ['operation', 'operator', 'node', 'machine', 'upgrade', 'update', 'backup', 'restore'] },
  { key: 'storage', label: 'Storage', terms: ['storage', 'persistent', 'volume', 'pvc', 'csi', 'odf'] },
  { key: 'observability', label: 'Observability', terms: ['observability', 'monitor', 'logging', 'metric', 'alert', 'telemetry'] },
  { key: 'security', label: 'Security', terms: ['security', 'auth', 'identity', 'rbac', 'certificate', 'compliance', 'oauth'] },
  { key: 'networking', label: 'Networking', terms: ['network', 'ingress', 'route', 'dns', 'service', 'ovn', 'load balanc'] },
  { key: 'troubleshooting', label: 'Troubleshooting', terms: ['troubleshoot', 'support', 'debug', 'must-gather', 'error', 'failure'] },
] as const;

type WikiCategoryKey = typeof WIKI_CATEGORIES[number]['key'];

interface RepositoryDocumentRow {
  repository: DocumentRepository;
  document: DocumentRepositoryDocument;
  categoryKey: WikiCategoryKey;
}

function metadataString(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

function metadataList(metadata: Record<string, unknown> | undefined, key: string): string[] {
  const value = metadata?.[key];
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function wikiCategoryFromValue(value: string): WikiCategoryKey | null {
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  const direct = WIKI_CATEGORIES.find(
    (category) => category.key === normalized || category.label.toLowerCase() === normalized,
  );
  if (direct) {
    return direct.key;
  }
  const matched = WIKI_CATEGORIES.find((category) =>
    category.terms.some((term) => normalized.includes(term)),
  );
  return matched?.key ?? null;
}

function documentSearchText(document: DocumentRepositoryDocument, repository?: DocumentRepository): string {
  const metadata = document.metadata ?? {};
  const repositoryMetadata = repository?.metadata ?? {};
  return [
    document.title,
    document.filename,
    document.source_kind,
    document.source_scope,
    repository?.slug,
    repository?.title,
    repository?.repository_kind,
    repository?.visibility,
    metadata.book_slug,
    metadata.book_title,
    metadata.category,
    metadata.category_key,
    metadata.source_collection,
    metadata.viewer_path,
    metadata.source_scope,
    repositoryMetadata.book_slug,
    repositoryMetadata.book_title,
    repositoryMetadata.category,
    repositoryMetadata.category_key,
    repositoryMetadata.source_collection,
    repositoryMetadata.source_scope,
    ...metadataList(metadata, 'toc_path'),
    ...metadataList(repositoryMetadata, 'toc_path'),
  ].filter(Boolean).join(' ').toLowerCase();
}

function inferWikiCategory(document: DocumentRepositoryDocument, repository?: DocumentRepository): WikiCategoryKey {
  const metadata = document.metadata ?? {};
  const repositoryMetadata = repository?.metadata ?? {};
  const metadataCandidates = [
    metadataString(metadata, 'category_key'),
    metadataString(metadata, 'category'),
    metadataString(repositoryMetadata, 'category_key'),
    metadataString(repositoryMetadata, 'category'),
    metadataString(metadata, 'book_slug'),
    metadataString(repositoryMetadata, 'book_slug'),
    document.source_scope,
    metadataString(metadata, 'source_scope'),
    metadataString(repositoryMetadata, 'source_scope'),
    ...metadataList(metadata, 'toc_path'),
    ...metadataList(repositoryMetadata, 'toc_path'),
  ];
  for (const candidate of metadataCandidates) {
    const category = wikiCategoryFromValue(candidate);
    if (category) {
      return category;
    }
  }
  const text = documentSearchText(document, repository);
  const matched = WIKI_CATEGORIES.find((category) => category.terms.some((term) => text.includes(term)));
  return matched?.key ?? 'operations';
}

const FACTORY_PIPELINE_STEPS: Record<FactoryLane, Array<{ badge: string; title: string; description: string }>> = {
  tools: [
    { badge: 'Bronze', title: '원천 바인딩', description: '선택한 공식 원천을 생산선에 연결' },
    { badge: 'Silver', title: '구조화 초안 생성', description: '섹션 · 구조 · 번역 초안 생성' },
    { badge: 'Gold', title: '플레이북 · 코퍼스 생성', description: '위키 책 · 검색 코퍼스 동시 생성' },
    { badge: 'Judge', title: '라이브러리 합류 검증', description: '완성본 검증 후 Playbook Library 반영' },
  ],
  user: [
    { badge: 'Bronze', title: '업로드 요청', description: '브라우저에서 서버로 파일 전송' },
    { badge: 'Silver', title: '서버 처리', description: '파싱 · 청킹 · DB 저장' },
    { badge: 'Gold', title: '검색 인덱싱', description: '임베딩 · Qdrant 반영' },
    { badge: 'Judge', title: '기본 인덱싱 확인', description: '답변 품질 검수 전' },
  ],
};

const USER_UPLOAD_PIPELINE_STEPS: Array<{
  stage: UserUploadStage;
  badge: string;
  title: string;
  description: string;
}> = [
  { stage: 'received', badge: '1', title: '요청 접수', description: '업로드 요청을 서버가 접수' },
  { stage: 'store', badge: '2', title: '원본 저장', description: '업로드 바이트를 디스크에 보관' },
  { stage: 'parse', badge: '3', title: '문서 파싱', description: '텍스트 · 구조 추출' },
  { stage: 'chunk', badge: '4', title: '청크 생성', description: '검색 단위 생성' },
  { stage: 'persist', badge: '5', title: 'DB 저장', description: 'PostgreSQL · 스코프 기록' },
  { stage: 'index', badge: '6', title: 'Qdrant 인덱싱', description: '임베딩 · 벡터 검색 가능' },
  { stage: 'scope', badge: '7', title: '스코프 확인', description: 'Owner · Repository 연결 확인' },
  { stage: 'ready', badge: '8', title: '완료 판정', description: '기본 검색 가능 상태 확인' },
];

const USER_UPLOAD_STAGE_ORDER = USER_UPLOAD_PIPELINE_STEPS.map((step) => step.stage);

function nowTime(): string {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}

function statusColor(status: string): string {
  switch (status) {
    case 'normalized': return 'green';
    case 'captured': return 'cyan';
    case 'planned': return 'gray';
    default: return 'red';
  }
}

function repositoryDocumentStatus(document: DocumentRepositoryDocument): {
  label: string;
  tone: 'ready' | 'partial' | 'empty' | 'error';
  detail: string;
} {
  const chunks = Number(document.chunk_count || 0);
  const indexed = Number(document.indexed_chunk_count || 0);
  const parseStatus = String(document.parse_status || '').trim().toLowerCase();
  if (parseStatus && !['parsed', 'completed', 'complete', 'ready', 'ok', 'success'].includes(parseStatus)) {
    return {
      label: parseStatus,
      tone: 'error',
      detail: chunks > 0 ? `${chunks.toLocaleString()} chunks captured` : 'Parser needs attention',
    };
  }
  if (chunks > 0 && indexed >= chunks) {
    return {
      label: '기본 인덱싱 완료',
      tone: 'ready',
      detail: `답변 품질 검수 전 · ${indexed.toLocaleString()} / ${chunks.toLocaleString()} chunks indexed`,
    };
  }
  if (chunks > 0 || indexed > 0) {
    return {
      label: 'Indexing',
      tone: 'partial',
      detail: `${indexed.toLocaleString()} / ${chunks.toLocaleString()} chunks indexed`,
    };
  }
  return {
    label: 'Uploaded',
    tone: 'empty',
    detail: 'Waiting for parsed chunks',
  };
}

function repositoryDocumentUpdatedLabel(document: DocumentRepositoryDocument, repository: DocumentRepository): string {
  const raw = document.updated_at || document.created_at || repository.updated_at || repository.last_document_at;
  if (!raw) {
    return 'Updated time unknown';
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  return `Updated ${date.toLocaleDateString()}`;
}

function uploadDocumentViewerPath(document: DocumentRepositoryDocument): string {
  return `/uploads/documents/${document.document_source_id}/index.html`;
}

function formatDurationMs(value: number | undefined): string {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) {
    return '0 ms';
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

function uploadStageTitle(stage: string): string {
  return USER_UPLOAD_PIPELINE_STEPS.find((step) => step.stage === stage)?.title ?? stage;
}

function uploadStageStatusLabel(status: string): string {
  switch (status) {
    case 'running': return '진행 중';
    case 'done': return '완료';
    case 'warning': return '경고';
    case 'failed': return '실패';
    case 'skipped': return '건너뜀';
    case 'duplicate': return '중복';
    default: return status || '-';
  }
}

function uploadStageTone(status: string): 'running' | 'done' | 'warning' | 'failed' | 'idle' {
  if (status === 'running' || status === 'info' || status === 'progress') return 'running';
  if (status === 'done' || status === 'duplicate' || status === 'skipped') return 'done';
  if (status === 'warning') return 'warning';
  if (status === 'failed') return 'failed';
  return 'idle';
}

function uploadStageStateFromEvents(
  events: UploadIngestStreamStageEvent[],
  stage: UserUploadStage,
): 'running' | 'done' | 'warning' | 'failed' | 'idle' {
  let state: 'running' | 'done' | 'warning' | 'failed' | 'idle' = 'idle';
  events.forEach((event) => {
    if (event.stage !== stage) return;
    if (event.status === 'failed') {
      state = 'failed';
      return;
    }
    if (event.status === 'warning') {
      if (state !== 'failed') state = 'warning';
      return;
    }
    if (event.status === 'done' || event.status === 'duplicate' || event.status === 'skipped') {
      if (state !== 'failed') state = 'done';
      return;
    }
    if (event.status === 'progress') {
      const total = Number(event.progress_total || 0);
      const current = Number(event.progress_current || 0);
      if (Number.isFinite(total) && total > 0 && Number.isFinite(current) && current >= total) {
        if (state !== 'failed') state = 'done';
      } else if (state !== 'failed') {
        state = 'running';
      }
      return;
    }
    if (event.status === 'running') {
      if (state !== 'failed') state = 'running';
      return;
    }
    if (event.status === 'info' && state === 'idle') {
      state = 'running';
    }
  });
  return state;
}

function uploadProgressTaskLabel(taskKind: string, stage: string): string {
  switch (taskKind) {
    case 'image_ocr': return '이미지 OCR/설명';
    case 'asset_write': return '이미지 파일 저장';
    default: return taskKind ? taskKind.replace(/_/g, ' ') : uploadStageTitle(stage);
  }
}

function progressFromUploadEvents(events: UploadIngestStreamStageEvent[]): UploadProgressItem[] {
  const items = new Map<string, UploadProgressItem>();
  events.forEach((event) => {
    const total = Number(event.progress_total || 0);
    if (!Number.isFinite(total) || total <= 0) return;
    const current = Math.max(0, Number(event.progress_current || 0));
    const rawPercent = typeof event.progress_percent === 'number'
      ? event.progress_percent
      : (current / total) * 100;
    const percent = Math.max(0, Math.min(100, Math.round(rawPercent)));
    const taskKind = String(event.task_kind || '').trim();
    const key = String(event.progress_key || `${event.stage}:${taskKind || event.item_label || 'progress'}`).trim();
    items.set(key, {
      key,
      stage: event.stage,
      taskKind,
      label: uploadProgressTaskLabel(taskKind, event.stage),
      message: event.item_label || event.message || uploadStageTitle(event.stage),
      current,
      total,
      percent,
      status: event.status,
    });
  });
  return Array.from(items.values());
}

function customerPackBookTruth(book?: LibraryBook | null): string {
  if (!book) {
    return '';
  }
  return book.boundary_badge || book.runtime_truth_label || '';
}

function bookSourceOriginLabel(book?: LibraryBook | null): string {
  if (!book) {
    return '원천 미기록';
  }
  return book.source_origin_label || book.current_source_label || book.source_url || book.source_lane || '원천 미기록';
}

function bookSourceOriginHref(book?: LibraryBook | null): string {
  if (!book) {
    return '';
  }
  return book.source_origin_url || book.source_url || '';
}

function bookChunkCount(book?: LibraryBook | null): number {
  if (!book) {
    return 0;
  }
  const raw = book.chunk_count ?? book.corpus_chunk_count ?? 0;
  const normalized = Number(raw);
  return Number.isFinite(normalized) ? normalized : 0;
}

function customerPackBookEvidenceBits(book?: LibraryBook | null): string[] {
  if (!book) {
    return [];
  }
  const bits = [
    book.approval_state ? `approval ${book.approval_state}` : '',
    book.publication_state ? `publication ${book.publication_state}` : '',
    book.source_lane ? `lane ${book.source_lane}` : '',
    book.parser_backend ? `parser ${book.parser_backend}` : '',
    book.corpus_runtime_eligible ? 'chat ready' : '',
    book.corpus_vector_status ? `vector ${book.corpus_vector_status}` : '',
    book.corpus_chunk_count ? `corpus ${book.corpus_chunk_count}` : '',
  ];
  return bits.filter(Boolean);
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


type SourceOptionRecord = {
  title: string;
  book_slug: string;
  current_source_basis?: string;
  current_source_label?: string;
  source_options?: LibraryBookSourceOption[];
};

function sourceOptionActionKey(record: SourceOptionRecord, option: LibraryBookSourceOption): string {
  return `${record.book_slug}:${String(option.key || '').trim()}`;
}

function sourceBasisLabel(record?: SourceOptionRecord | null): string {
  const explicit = String(record?.current_source_label || '').trim();
  if (explicit) {
    return explicit;
  }
  switch (String(record?.current_source_basis || '').trim()) {
    case 'official_homepage':
      return '공식 홈페이지 기준';
    case 'official_repo':
      return '공식 레포 기준';
    default:
      return '원천 기준 미기록';
  }
}

function catalogSourceDetail(record: OfficialSourceCandidate): string {
  const relativePath = String(record.source_relative_path || '').trim();
  if (relativePath) {
    return relativePath;
  }
  if (record.current_source_basis === 'official_homepage' || record.source_kind === 'html-single') {
    return '공식 홈페이지 원문';
  }
  if (record.current_source_basis === 'official_repo' || record.source_kind === 'source-first') {
    return '공식 레포 원문';
  }
  return 'source path pending';
}

function simplifyOfficialTitle(title: string): string {
  const simplified = title.replace(/\s+(개요|소개|문서)\s*$/u, '').trim();
  return simplified || title.trim();
}

function friendlySourceOptionLabel(record: SourceOptionRecord, option: LibraryBookSourceOption): string {
  const baseTitle = simplifyOfficialTitle(record.title);
  switch (String(option.key || '').trim()) {
    case 'official_repo':
      return `${baseTitle} 공식 깃허브 문서`;
    case 'official_homepage':
      return `${baseTitle} 공식 웹페이지 매뉴얼`;
    default:
      return `${baseTitle} ${option.label}`;
  }
}

function toolsFormatActive(ext: string): boolean {
  return ext === 'AsciiDoc' || ext === 'HTML';
}

function inferCatalogPreferredBasis(query: string): OfficialSourceBasisKey | 'mixed' {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return 'mixed';
  }
  if (
    normalized.includes('github')
    || normalized.includes('repo')
    || normalized.includes('레포')
    || normalized.includes('브랜치')
    || normalized.includes('branch')
    || normalized.includes('asciidoc')
  ) {
    return 'official_repo';
  }
  if (
    normalized.includes('홈페이지')
    || normalized.includes('웹페이지')
    || normalized.includes('manual')
    || normalized.includes('매뉴얼')
    || normalized.includes('html')
  ) {
    return 'official_homepage';
  }
  return 'mixed';
}

function preferredCatalogBasisLabel(preferredBasis: OfficialSourceBasisKey | 'mixed'): string {
  if (preferredBasis === 'official_repo') {
    return '공식 레포 기준';
  }
  if (preferredBasis === 'official_homepage') {
    return '공식 홈페이지 기준';
  }
  return '공식 레포 · 공식 홈페이지';
}

function sourceOptionsForRecord(record?: SourceOptionRecord | null): LibraryBookSourceOption[] {
  return Array.isArray(record?.source_options) ? record.source_options : [];
}

function OfficialSourcePopover({
  record,
  onMaterializeOption,
  materializingOptionKey,
}: {
  record: SourceOptionRecord;
  onMaterializeOption?: (record: SourceOptionRecord, option: LibraryBookSourceOption) => void | Promise<unknown>;
  materializingOptionKey?: string | null;
}) {
  const options = sourceOptionsForRecord(record);
  const basis = String(record.current_source_basis || 'unknown').trim() || 'unknown';

  if (!options.length) {
    return (
      <div className="operational-source-row" onClick={(event) => event.stopPropagation()}>
        <span className={`operational-source-basis operational-source-basis--${basis}`}>
          {sourceBasisLabel(record)}
        </span>
      </div>
    );
  }

  return (
    <div className="operational-source-row" onClick={(event) => event.stopPropagation()}>
      <span className={`operational-source-basis operational-source-basis--${basis}`}>
        {sourceBasisLabel(record)}
      </span>
      <details className="operational-source-popover">
        <summary className="operational-source-trigger">
          <span>원천소스</span>
          <ChevronDown size={14} />
        </summary>
        <div className="operational-source-panel">
          <div className="operational-source-panel-header">
            <strong>{record.title}</strong>
            <span>{record.book_slug.replace(/_/g, ' ')}</span>
          </div>
          <div className="operational-source-list">
            {options.map((option) => {
              const href = String(option.href || '').trim();
              const isAvailable = option.availability === 'available' && Boolean(href);
              const canMaterialize =
                typeof onMaterializeOption === 'function'
                && (option.key === 'official_homepage' || option.key === 'official_repo')
                && isAvailable;
              const currentLabel = option.is_current ? '현재 기준' : isAvailable ? '열기' : '준비 중';
              const actionKey = sourceOptionActionKey(record, option);
              const isMaterializing = materializingOptionKey === actionKey;
              const optionBody = (
                <>
                  <div className="operational-source-option-copy">
                    <div className="operational-source-option-top">
                      <strong>{option.label}</strong>
                      <span
                        className={`operational-source-option-status ${option.is_current ? 'current' : isAvailable ? 'available' : 'missing'
                          }`}
                      >
                        {currentLabel}
                      </span>
                    </div>
                    <span>{option.note}</span>
                  </div>
                </>
              );

              if (!isAvailable) {
                return (
                  <div key={option.key} className="operational-source-option operational-source-option--missing">
                    {optionBody}
                  </div>
                );
              }

              if (canMaterialize) {
                return (
                  <div key={option.key} className="operational-source-option operational-source-option--action">
                    {optionBody}
                    <div className="operational-source-option-actions">
                      <a
                        className="operational-source-option-link"
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ExternalLink size={13} />
                        <span>원본</span>
                      </a>
                      <button
                        type="button"
                        className="operational-source-option-produce"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          void onMaterializeOption?.(record, option);
                        }}
                        disabled={Boolean(materializingOptionKey)}
                      >
                        {isMaterializing ? <Loader2 size={13} className="spin-icon" /> : <UploadCloud size={13} />}
                        <span>{isMaterializing ? '생산 중...' : option.is_current ? '다시 생산' : '생산'}</span>
                      </button>
                    </div>
                  </div>
                );
              }

              return (
                <a
                  key={option.key}
                  className="operational-source-option"
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                >
                  {optionBody}
                </a>
              );
            })}
          </div>
        </div>
      </details>
    </div>
  );
}

const PlaybookLibraryPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { globalTheme, toggleGlobalTheme } = useGlobalTheme();
  const [factoryLane, setFactoryLane] = useState<FactoryLane>('tools');
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>('idle');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState('');
  const [currentFile, setCurrentFile] = useState('');
  const [latestUploadIngest, setLatestUploadIngest] = useState<UploadIngestResponse | null>(null);
  const [uploadStageEvents, setUploadStageEvents] = useState<UploadIngestStreamStageEvent[]>([]);
  const [uploadReportViewer, setUploadReportViewer] = useState<UploadReportViewerState | null>(null);
  const [controlRoom, setControlRoom] = useState<DataControlRoomResponse | null>(null);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [previewDraft, setPreviewDraft] = useState<CustomerPackDraft | null>(null);
  const [metricPopover, setMetricPopover] = useState<MetricPopoverState | null>(null);
  const [buyerPacketPopover, setBuyerPacketPopover] = useState<{ title: string; packets: BuyerPacket[] } | null>(null);
  const [chunkViewer, setChunkViewer] = useState<ChunkViewerState | null>(null);
  const [bookViewer, setBookViewer] = useState<LibraryBook | null>(null);
  const [bookViewerPageMode, setBookViewerPageMode] = useState<ViewerPageMode>('single');
  const [bookViewerDocument, setBookViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [bookViewerLoading, setBookViewerLoading] = useState(false);
  const [previewCapturedUrl, setPreviewCapturedUrl] = useState('');
  const [previewCapturedType, setPreviewCapturedType] = useState('');
  const [previewViewerDocument, setPreviewViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [repositoryResults, setRepositoryResults] = useState<RepositorySearchResult[]>([]);
  const [officialSourceCandidates, setOfficialSourceCandidates] = useState<OfficialSourceCandidate[]>([]);
  const [materializingOptionKey, setMaterializingOptionKey] = useState<string | null>(null);
  const [factoryRunMode, setFactoryRunMode] = useState<FactoryRunMode>('auto');
  const [factoryManualFocusId, setFactoryManualFocusId] = useState<string | null>(null);
  const [factoryMaterializationSnapshots, setFactoryMaterializationSnapshots] = useState<Record<string, FactoryMaterializationSnapshot>>({});
  const [factoryManualChecklistState, setFactoryManualChecklistState] = useState<Record<string, string[]>>({});
  const [factoryManualRequirements, setFactoryManualRequirements] = useState<Record<string, string[]>>({});
  const [factoryManualRequirementDraft, setFactoryManualRequirementDraft] = useState('');
  const [sourceRequestsExpanded, setSourceRequestsExpanded] = useState(false);
  const [downloadListExpanded, setDownloadListExpanded] = useState(true);
  const [officialCatalogExpanded, setOfficialCatalogExpanded] = useState(false);
  const [factoryAssistantQuery, setFactoryAssistantQuery] = useState('');
  const [factoryAssistantError, setFactoryAssistantError] = useState('');
  const [factoryDownloadList, setFactoryDownloadList] = useState<FactoryDownloadItem[]>([]);
  const [officialCatalogRows, setOfficialCatalogRows] = useState<OfficialSourceCandidate[]>([]);
  const [officialCatalogTotalCount, setOfficialCatalogTotalCount] = useState(0);
  const [officialCatalogLiveCount, setOfficialCatalogLiveCount] = useState(0);
  const [generatedCatalogPrompt, setGeneratedCatalogPrompt] = useState('');
  const [openCatalogRowSlug, setOpenCatalogRowSlug] = useState<string | null>(null);
  const [repositoryFavorites, setRepositoryFavorites] = useState<RepositoryFavorite[]>([]);
  const [repositoryUnanswered, setRepositoryUnanswered] = useState<RepositoryUnansweredItem[]>([]);
  const [documentRepositories, setDocumentRepositories] = useState<DocumentRepository[]>([]);
  const [repositoryStage, setRepositoryStage] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [repositoryError, setRepositoryError] = useState('');
  const [repositoryMeta, setRepositoryMeta] = useState<{ rewrittenQuery: string; authMode: 'token' | 'public' }>({
    rewrittenQuery: '',
    authMode: 'public',
  });
  const [removingFavoriteName, setRemovingFavoriteName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pipelineRef = useRef<HTMLDivElement>(null);
  const repositorySearchInputRef = useRef<HTMLInputElement>(null);
  const repositoryAutoloadKeyRef = useRef('');
  const toolsRunHeartbeatRef = useRef<number | null>(null);
  const viewMode: 'monitoring' | 'repository' = location.pathname.endsWith('/repository')
    ? 'repository'
    : 'monitoring';

  const addLog = (tag: LogEntry['tag'], msg: string) => {
    setLogs((prev) => [{ time: nowTime(), tag, msg }, ...prev].slice(0, 40));
  };

  const stopToolsRunHeartbeat = useCallback(() => {
    if (toolsRunHeartbeatRef.current !== null && typeof window !== 'undefined') {
      window.clearInterval(toolsRunHeartbeatRef.current);
      toolsRunHeartbeatRef.current = null;
    }
  }, []);

  const refreshRepositoryFavorites = useCallback(() => {
    loadRepositoryFavorites()
      .then((payload) => setRepositoryFavorites(payload.items))
      .catch(() => setRepositoryFavorites([]));
  }, []);

  const refreshRepositoryUnanswered = useCallback(() => {
    loadRepositoryUnanswered(20)
      .then((payload) => setRepositoryUnanswered(payload.items))
      .catch(() => setRepositoryUnanswered([]));
  }, []);

  const refreshDocumentRepositories = useCallback(() => {
    loadDocumentRepositories()
      .then((payload) => setDocumentRepositories(payload.repositories ?? []))
      .catch(() => setDocumentRepositories([]));
  }, []);

  const refreshOfficialCatalog = useCallback(() => {
    loadOfficialSourceCatalog()
      .then((payload) => {
        setOfficialCatalogRows(payload.rows ?? []);
        setOfficialCatalogTotalCount(payload.total_count ?? (payload.rows?.length ?? 0));
        setOfficialCatalogLiveCount(payload.live_count ?? 0);
      })
      .catch(() => {
        setOfficialCatalogRows([]);
        setOfficialCatalogTotalCount(0);
        setOfficialCatalogLiveCount(0);
      });
  }, []);

  const refreshData = useCallback(() => {
    loadDataControlRoom().then(setControlRoom).catch(() => { });
    listCustomerPackDrafts().then((res) => setDrafts(res.drafts)).catch(() => { });
    refreshRepositoryFavorites();
    refreshRepositoryUnanswered();
    refreshOfficialCatalog();
    refreshDocumentRepositories();
  }, [refreshDocumentRepositories, refreshOfficialCatalog, refreshRepositoryFavorites, refreshRepositoryUnanswered]);

  const openRepositoryInChat = useCallback((repository: DocumentRepository) => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('workspace.activeSourceId', `repository:${repository.repository_id}`);
      window.localStorage.removeItem('workspace.activeDocumentId');
      window.localStorage.removeItem(WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY);
      window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY);
      window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY);
    }
    navigate(ROUTES.pbsStudio);
  }, [navigate]);

  const openDocumentInChat = useCallback((
    repository: DocumentRepository,
    document: DocumentRepositoryDocument,
    categoryKey?: WikiCategoryKey,
  ) => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('workspace.activeSourceId', `repository:${repository.repository_id}`);
      window.localStorage.setItem(WORKSPACE_ACTIVE_DOCUMENT_STORAGE_KEY, document.document_source_id);
      window.localStorage.setItem(WORKSPACE_ACTIVE_DOCUMENT_TITLE_STORAGE_KEY, document.title || document.filename || 'Scoped document');
      if (categoryKey) {
        const category = WIKI_CATEGORIES.find((item) => item.key === categoryKey);
        window.localStorage.setItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY, categoryKey);
        window.localStorage.setItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY, category?.label ?? categoryKey);
      } else {
        window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_KEY_STORAGE_KEY);
        window.localStorage.removeItem(WORKSPACE_ACTIVE_CATEGORY_LABEL_STORAGE_KEY);
      }
    }
    navigate(ROUTES.pbsStudio);
  }, [navigate]);

  const openUploadedDocumentReader = useCallback((document: DocumentRepositoryDocument) => {
    setBookViewerPageMode('single');
    setBookViewer({
      book_slug: 'uploaded-documents',
      title: document.title || document.filename || 'Uploaded document',
      grade: '',
      review_status: document.visibility || 'private_user',
      source_type: 'uploaded_document',
      source_lane: document.source_scope || 'user_upload',
      section_count: Number(document.chunk_count || 0),
      code_block_count: 0,
      viewer_path: uploadDocumentViewerPath(document),
      source_url: '',
      updated_at: document.updated_at || document.created_at || '',
      boundary_badge: document.visibility || 'private_user',
      runtime_truth_label: '업로드 문서 Reader',
      chunk_count: Number(document.chunk_count || 0),
      token_total: 0,
      source_collection: document.source_scope || 'user_upload',
      source_origin_label: document.filename || '',
    });
  }, []);

  const openUploadProcessingReport = useCallback((document: DocumentRepositoryDocument) => {
    const title = document.title || document.filename || 'Uploaded document';
    setUploadReportViewer({
      title,
      documentSourceId: document.document_source_id,
      report: null,
      loading: true,
      error: '',
    });
    loadUploadIngestReport(document.document_source_id)
      .then((report) => {
        setUploadReportViewer({
          title,
          documentSourceId: document.document_source_id,
          report,
          loading: false,
          error: '',
        });
      })
      .catch((error: unknown) => {
        setUploadReportViewer({
          title,
          documentSourceId: document.document_source_id,
          report: null,
          loading: false,
          error: errorMessage(error, '작업 로그를 불러오지 못했습니다.'),
        });
      });
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  useEffect(() => () => {
    stopToolsRunHeartbeat();
  }, [stopToolsRunHeartbeat]);

  useEffect(() => {
    if (!bookViewer?.viewer_path) {
      setBookViewerDocument(null);
      setBookViewerLoading(false);
      return;
    }

    let cancelled = false;
    setBookViewerLoading(true);
    setBookViewerDocument(null);

    loadViewerDocument(bookViewer.viewer_path, bookViewerPageMode)
      .then((viewerDocument) => {
        if (cancelled) {
          return;
        }
        setBookViewerDocument({
          html: viewerDocument.html,
          inlineStyles: viewerDocument.inline_styles,
          bodyClassName: viewerDocument.body_class_name,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setBookViewerDocument(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBookViewerLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [bookViewer, bookViewerPageMode]);

  useEffect(() => {
    return () => {
      if (previewCapturedUrl) {
        URL.revokeObjectURL(previewCapturedUrl);
      }
    };
  }, [previewCapturedUrl]);

  useEffect(() => {
    const requestedView = (searchParams.get('view') || '').trim();
    const requestedQuery = (searchParams.get('q') || '').trim();
    if (location.pathname === '/playbook-library') {
      const nextPath = requestedView === 'repository'
        ? '/playbook-library/repository'
        : '/playbook-library/control-tower';
      navigate(`${nextPath}${requestedQuery ? `?q=${encodeURIComponent(requestedQuery)}` : ''}`, { replace: true });
      return;
    }
    if (!requestedQuery) {
      repositoryAutoloadKeyRef.current = '';
      return;
    }
    const autoloadKey = `${requestedView}|${requestedQuery}`;
    if (repositoryAutoloadKeyRef.current === autoloadKey) {
      return;
    }
    repositoryAutoloadKeyRef.current = autoloadKey;
    setSearchQuery(requestedQuery);
    setRepositoryStage('loading');
    setRepositoryError('');
    searchRepositories(requestedQuery, 12)
      .then((payload) => {
        setRepositoryResults(payload.results);
        setOfficialSourceCandidates(payload.official_candidates ?? []);
        setRepositoryMeta({
          rewrittenQuery: payload.rewritten_query,
          authMode: payload.auth_mode,
        });
        setRepositoryStage('done');
        addLog('info', `Repository search '${requestedQuery}' → ${payload.count} matches`);
      })
      .catch((error: unknown) => {
        const msg = errorMessage(error, 'Repository search failed');
        setRepositoryStage('error');
        setRepositoryError(msg);
        setRepositoryResults([]);
        setOfficialSourceCandidates([]);
        addLog('error', `Repository search failed: ${msg}`);
      });
  }, [location.pathname, navigate, searchParams]);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.from('.header-content', { opacity: 0, y: -20, duration: 0.8, ease: 'power3.out' });
      gsap.from('.metric-card', {
        opacity: 0, y: 20, stagger: 0.1, duration: 0.8, ease: 'power3.out', delay: 0.2,
      });
    });
    return () => ctx.revert();
  }, []);

  useEffect(() => {
    if (factoryLane !== 'user') return;
    if (!pipelineRef.current) return;
    const steps = pipelineRef.current.querySelectorAll('.pipeline-step');
    const connectors = pipelineRef.current.querySelectorAll('.pipeline-connector');

    const stageIndex = pipelineStage === 'error'
      ? -1
      : USER_UPLOAD_STAGE_ORDER.indexOf(pipelineStage as UserUploadStage);
    steps.forEach((step, i) => {
      const stepName = USER_UPLOAD_STAGE_ORDER[i];
      const state = stepName ? uploadStageStateFromEvents(uploadStageEvents, stepName) : 'idle';
      step.classList.toggle('active', i === stageIndex);
      step.classList.toggle('completed', state === 'done');
      step.classList.toggle('final', stepName === 'ready' && state === 'done');
    });

    connectors.forEach((conn, i) => {
      const previousName = USER_UPLOAD_STAGE_ORDER[i];
      const previousState = previousName ? uploadStageStateFromEvents(uploadStageEvents, previousName) : 'idle';
      conn.classList.toggle('filled', previousState === 'done');
      conn.classList.toggle('flowing', i === stageIndex - 1);
    });

    if (stageIndex >= 0 && steps[stageIndex]) {
      gsap.fromTo(
        steps[stageIndex].querySelector('.step-icon'),
        { scale: 0.8, opacity: 0.5 },
        { scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(1.7)' },
      );
    }
  }, [factoryLane, pipelineStage, uploadStageEvents]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';

    setErrorMsg('');
    setCurrentFile(file.name);
    setLatestUploadIngest(null);
    setUploadStageEvents([]);

    try {
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'recognizing',
        message: '서버 단계 이벤트를 기다리는 중입니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      }));
      addLog('info', `Upload request started: '${file.name}'`);

      const handleStreamEvent = (event: UploadIngestStreamEvent) => {
        const nextStage = stageFromUploadEvent(event);
        if (nextStage) {
          setPipelineStage(nextStage);
        }
        if (event.type === 'stage') {
          setUploadStageEvents((prev) => [...prev, event]);
          const status =
            event.stage === 'parse' || event.stage === 'chunk'
              ? 'parsing'
              : event.stage === 'persist' || event.stage === 'index'
                ? 'indexing'
                : event.stage === 'ready'
                  ? event.status === 'done' || event.status === 'duplicate'
                    ? 'basic_index_ready'
                    : 'index_failed'
                  : 'recognizing';
          window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
            status,
            message: event.message,
            filename: file.name,
            updatedAt: new Date().toISOString(),
          }));
        }
        logUploadStreamEvent(event);
      };

      // 같은 파일 재업로드는 백엔드가 자동으로 덮어쓰기. 별도 confirm 없음.
      const ingest = await uploadDocumentIngestionStream(file, { index: true }, handleStreamEvent);
      if (ingest.duplicate?.exists) {
        addLog('info', `'${ingest.duplicate.filename || file.name}' 같은 파일 감지 — 새 버전으로 덮어쓰는 중입니다.`);
      }
      const indexedCount = ingest.index?.indexed_count ?? 0;
      const indexLine = ingest.index ? `, ${indexedCount}/${ingest.index.candidate_count} indexed` : '';
      const indexFailed = ingest.index?.status === 'failed';
      const basicIndexReady = Boolean(ingest.basic_index_ready || ingest.index?.status === 'indexed' || ingest.index?.status === 'duplicate_existing_indexed');
      const timings = ingest.timings_ms ?? {};
      setLatestUploadIngest(ingest);
      setUploadStageEvents(ingest.stage_events ?? uploadStageEvents);

      addLog('success', `Ingested '${ingest.filename}': ${ingest.block_count} blocks, ${ingest.chunk_count} chunks${indexLine}.`);
      addLog(
        'info',
        `Processing receipt: parse ${formatDurationMs(timings.parse_ms)}, chunk ${formatDurationMs(timings.chunk_ms)}, persist ${formatDurationMs(timings.persist_ms)}, index ${formatDurationMs(timings.index_ms)}, total ${formatDurationMs(timings.total_ms)}.`,
      );
      if (ingest.warnings.length > 0) {
        addLog('warn', ingest.warnings.slice(0, 2).join(' / '));
      }
      if (indexFailed) {
        addLog('warn', `Search indexing failed: ${ingest.index?.error || 'embedding service unavailable'}`);
      }

      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: indexFailed ? 'index_failed' : basicIndexReady ? 'basic_index_ready' : 'indexing',
        message: indexFailed
          ? '문서 저장은 완료됐지만 검색 인덱싱에 실패했습니다.'
          : basicIndexReady
            ? '기본 텍스트 인덱싱이 완료되었습니다. 답변 품질 검수는 별도입니다.'
            : '문서 저장은 완료됐지만 검색 인덱싱 확인이 더 필요합니다.',
        filename: ingest.filename || file.name,
        repositoryId: ingest.repository_id || ingest.persisted?.repository_id || '',
        documentSourceId: ingest.persisted?.document_source_id || '',
        updatedAt: new Date().toISOString(),
      }));
      if (indexFailed) {
        addLog('warn', `'${ingest.filename}' was saved, but is not searchable until indexing is retried.`);
      } else if (basicIndexReady) {
        addLog('success', `'${ingest.filename}' 기본 텍스트 인덱싱 완료. 답변 품질 검수는 별도입니다.`);
      } else {
        addLog('warn', `'${ingest.filename}' 저장 완료. 검색 인덱싱 상태를 추가 확인해야 합니다.`);
      }
      refreshData();
      setTimeout(() => { setPipelineStage('idle'); setCurrentFile(''); }, 6000);
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Unknown error');
      setPipelineStage('error');
      setErrorMsg(msg);
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'failed',
        message: '문서 처리에 실패했습니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      }));
      addLog('error', `Pipeline failed: ${msg}`);
      setTimeout(() => { setPipelineStage('idle'); setCurrentFile(''); }, 5000);
    }
  };

  const handleUploadedDocumentDelete = async (
    documentSourceId: string,
    title: string,
  ): Promise<boolean> => {
    if (!documentSourceId) return false;
    if (!confirm(`'${title}' 문서를 삭제할까요?\n\nPostgreSQL · Qdrant 인덱스 · 원본 파일이 모두 삭제됩니다. 같은 파일을 다시 업로드하면 새 인덱싱이 시작됩니다.`)) {
      return false;
    }
    setDeletingDocumentId(documentSourceId);
    try {
      const result = await deleteUploadedDocument(documentSourceId);
      addLog(
        'success',
        `Deleted '${result.filename || title}' — Postgres ${result.postgres_rows_deleted}건, Qdrant ${result.qdrant_points_deleted}개 정리.`,
      );
      if (result.qdrant_errors.length > 0) {
        addLog('warn', `Qdrant 정리 일부 실패: ${result.qdrant_errors.slice(0, 2).join(' / ')}`);
      }
      refreshData();
      return true;
    } catch (err) {
      const msg = errorMessage(err, '문서 삭제 실패');
      addLog('error', `Failed to delete '${title}': ${msg}`);
      return false;
    } finally {
      setDeletingDocumentId(null);
    }
  };

  const handleDelete = async (draftId: string, title: string, skipConfirm = false): Promise<boolean> => {
    if (!skipConfirm && !confirm(`'${title}' 초안을 삭제하시겠습니까?`)) return false;
    setDeletingId(draftId);
    try {
      await deleteCustomerPackDraft(draftId);
      setDrafts((prev) => prev.filter((d) => d.draft_id !== draftId));
      addLog('success', `Deleted draft '${title}'`);
      refreshData();
      return true;
    } catch (err) {
      console.error('[delete-draft] error:', err);
      addLog('error', `Failed to delete '${title}'`);
      return false;
    } finally {
      setDeletingId(null);
    }
  };

  const handleMetricBookDelete = async (book: LibraryBook, skipConfirm = false): Promise<boolean> => {
    const draftId = String(book.delete_target_id || '').trim();
    if (!draftId) {
      return false;
    }
    const ok = await handleDelete(draftId, book.delete_target_label || book.title, skipConfirm);
    if (ok) {
      setMetricPopover((current) => current ? {
        ...current,
        rows: current.rows.filter((row) => String(row.delete_target_id || '').trim() !== draftId),
      } : current);
      setChunkViewer((current) => current?.payload?.draft_id === draftId ? null : current);
      setBookViewer((current) => current?.delete_target_id === draftId ? null : current);
    }
    return ok;
  };

  const runRepositorySearch = async (rawQuery: string) => {
    const normalizedQuery = rawQuery.trim();
    if (!normalizedQuery) {
      setRepositoryStage('idle');
      setRepositoryError('');
      setRepositoryResults([]);
      setOfficialSourceCandidates([]);
      return null;
    }
    setRepositoryStage('loading');
    setRepositoryError('');
    try {
      const payload = await searchRepositories(normalizedQuery, 12);
      setRepositoryResults(payload.results);
      setOfficialSourceCandidates(payload.official_candidates ?? []);
      setRepositoryMeta({
        rewrittenQuery: payload.rewritten_query,
        authMode: payload.auth_mode,
      });
      setRepositoryStage('done');
      addLog('info', `Repository search '${normalizedQuery}' → ${payload.count} matches`);
      return payload;
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Repository search failed');
      setRepositoryStage('error');
      setRepositoryError(msg);
      setRepositoryResults([]);
      setOfficialSourceCandidates([]);
      addLog('error', `Repository search failed: ${msg}`);
      return null;
    }
  };

  const handleRemoveFavorite = async (fullName: string) => {
    setRemovingFavoriteName(fullName);
    try {
      const payload = await removeRepositoryFavorite(fullName);
      setRepositoryFavorites(payload.items);
      setRepositoryResults((prev) =>
        prev.map((item) =>
          item.full_name === fullName
            ? { ...item, is_favorite: false, favorite_category: '' }
            : item
        )
      );
      addLog('info', `Removed favorite ${fullName}`);
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Favorite remove failed');
      setRepositoryError(msg);
      addLog('error', `Favorite remove failed: ${msg}`);
    } finally {
      setRemovingFavoriteName(null);
    }
  };

  const handleFactoryAssistantSubmit = async (query?: string) => {
    const nextQuery = String(query ?? factoryAssistantQuery).trim();
    if (!nextQuery) {
      setFactoryAssistantError('질문을 먼저 넣어야 원천소스를 찾을 수 있습니다.');
      return false;
    }
    setFactoryAssistantError('');
    setFactoryAssistantQuery(nextQuery);
    setSearchQuery(nextQuery);
    addLog('info', `Book Factory assistant lookup: ${nextQuery}`);
    const payload = await runRepositorySearch(nextQuery);
    if (!payload) {
      setGeneratedCatalogPrompt('');
      setFactoryAssistantError('원천소스를 찾지 못했습니다. 질문 표현을 조금만 바꿔보세요.');
      setOfficialCatalogExpanded(false);
      return false;
    }
    if ((payload.official_candidates ?? []).length > 0) {
      setGeneratedCatalogPrompt(nextQuery);
      setOfficialCatalogExpanded(true);
    } else {
      setGeneratedCatalogPrompt('');
      setOfficialCatalogExpanded(false);
    }
    return true;
  };

  const handleQueueOfficialSource = (record: OfficialSourceCandidate, option: LibraryBookSourceOption, requestQuery: string) => {
    const key = sourceOptionActionKey(record, option);
    setFactoryManualFocusId(key);
    setDownloadListExpanded(true);
    setFactoryDownloadList((prev) => {
      if (prev.some((item) => item.id === key)) {
        return prev;
      }
      return [
        {
          id: key,
          requestQuery: requestQuery.trim() || record.title,
          record,
          option,
          friendlyLabel: friendlySourceOptionLabel(record, option),
          status: 'queued',
          savedAt: new Date().toISOString(),
        },
        ...prev,
      ];
    });
    addLog('success', `${friendlySourceOptionLabel(record, option)} 저장됨`);
  };

  const handleQueueOfficialCatalogAll = (sourceBasis: OfficialSourceBasisKey) => {
    const candidates = officialCatalogRows
      .filter((row) => row.status_kind !== 'live')
      .map((row) => {
        const option = sourceOptionsForRecord(row).find(
          (item) => item.key === sourceBasis && item.availability === 'available' && Boolean(item.href),
        );
        return option ? { record: row, option } : null;
      })
      .filter((item): item is { record: OfficialSourceCandidate; option: LibraryBookSourceOption } => Boolean(item));
    if (!candidates.length) {
      addLog('warn', `${sourceBasis === 'official_repo' ? '공식 레포' : '공식 홈페이지'} 기준으로 받을 새 문서가 없습니다.`);
      return;
    }

    setDownloadListExpanded(true);
    const existing = new Set(factoryDownloadList.map((item) => item.id));
    const additions: FactoryDownloadItem[] = [];
    for (const { record, option } of candidates) {
      const id = sourceOptionActionKey(record, option);
      if (existing.has(id)) {
        continue;
      }
      existing.add(id);
      additions.push({
        id,
        requestQuery: generatedCatalogPrompt.trim() || `OCP 4.20 ${sourceBasis === 'official_repo' ? '공식 레포' : '공식 홈페이지'} 전권`,
        record,
        option,
        friendlyLabel: friendlySourceOptionLabel(record, option),
        status: 'queued',
        savedAt: new Date().toISOString(),
      });
    }
    if (additions[0]) {
      setFactoryManualFocusId(additions[0].id);
    }
    if (additions.length) {
      setFactoryDownloadList((prev) => [...additions, ...prev]);
    }
    addLog(
      'success',
      additions.length > 0
        ? `${sourceBasis === 'official_repo' ? '공식 레포' : '공식 홈페이지'} 기준 ${additions.length}권을 다운로드 리스트에 추가했습니다.`
        : `${sourceBasis === 'official_repo' ? '공식 레포' : '공식 홈페이지'} 기준으로 새로 추가할 문서가 없습니다.`,
    );
  };

  const handleDownloadListMaterialize = async (item: FactoryDownloadItem) => {
    setFactoryManualFocusId(item.id);
    setFactoryDownloadList((prev) =>
      prev.map((entry) => (entry.id === item.id ? { ...entry, status: 'producing', message: '' } : entry)),
    );
    try {
      const result = await handleOfficialSourceMaterialize(item.record, item.option);
      if (result) {
        setFactoryMaterializationSnapshots((prev) => ({
          ...prev,
          [item.id]: {
            ...result,
            requestQuery: item.requestQuery,
            completedAt: new Date().toISOString(),
          },
        }));
      }
      setFactoryDownloadList((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, status: 'done', message: 'Library 합류 완료' } : entry)),
      );
    } catch (error: unknown) {
      const msg = errorMessage(error, '생산에 실패했습니다.');
      setFactoryDownloadList((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, status: 'error', message: msg } : entry)),
      );
    }
  };

  const handleRemoveDownloadItem = (itemId: string) => {
    setFactoryDownloadList((prev) => {
      const next = prev.filter((item) => item.id !== itemId);
      if (factoryManualFocusId === itemId) {
        setFactoryManualFocusId(next[0]?.id ?? null);
      }
      return next;
    });
    setFactoryMaterializationSnapshots((prev) => {
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
    setFactoryManualChecklistState((prev) => {
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
    setFactoryManualRequirements((prev) => {
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
    if (factoryManualFocusId === itemId) {
      setFactoryManualRequirementDraft('');
    }
  };

  const openToolsDocsUpload = async (query?: string) => {
    const nextQuery = typeof query === 'string' ? query : searchQuery;
    if (typeof query === 'string') {
      setSearchQuery(query);
      setFactoryAssistantQuery(query);
    }
    setFactoryLane('tools');
    navigate(`/playbook-library/repository${nextQuery.trim() ? `?q=${encodeURIComponent(nextQuery.trim())}` : ''}`);
    requestAnimationFrame(() => repositorySearchInputRef.current?.focus());
    if (nextQuery.trim()) {
      await runRepositorySearch(nextQuery);
    }
  };

  const openUserDocsUpload = (openPicker = false) => {
    setFactoryLane('user');
    navigate('/playbook-library/repository');
    if (openPicker) {
      requestAnimationFrame(() => fileInputRef.current?.click());
    }
  };

  const handleOfficialSourceMaterialize = async (
    record: SourceOptionRecord,
    option: LibraryBookSourceOption,
  ) => {
    const sourceBasis = String(option.key || '').trim();
    if (sourceBasis !== 'official_homepage' && sourceBasis !== 'official_repo') {
      addLog('error', '생산 기준이 올바르지 않습니다.');
      return;
    }
    const actionKey = sourceOptionActionKey(record, option);
    const friendlyLabel = friendlySourceOptionLabel(record, option);
    const sourceBasisLabelText = sourceBasis === 'official_repo' ? '공식 레포 AsciiDoc' : '공식 홈페이지 HTML-single';
    const startedAt = Date.now();
    stopToolsRunHeartbeat();
    setMaterializingOptionKey(actionKey);
    addLog('info', `[Bronze] ${friendlyLabel} 원천 바인딩 시작`);
    addLog('info', `${sourceBasisLabelText} 기준으로 구조화 초안 · 플레이북 · 코퍼스 · 라이브러리 검증을 순서대로 실행합니다.`);
    if (typeof window !== 'undefined') {
      toolsRunHeartbeatRef.current = window.setInterval(() => {
        const elapsedSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
        addLog('info', `${friendlyLabel} 생산 계속 진행 중 · ${elapsedSeconds}초 경과`);
      }, 15000);
    }
    try {
      const result = await materializeOfficialSourceCandidate(record.book_slug, sourceBasis);
      stopToolsRunHeartbeat();
      const draftSummary = result.draft_summary || {};
      const goldSummary = result.gold_summary || {};
      const sectionCount = summaryNumber(draftSummary, 'section_count');
      const chunkCount = summaryNumber(draftSummary, 'chunk_count');
      const generatedCount = summaryNumber(draftSummary, 'generated_count');
      const promotedCount = summaryNumber(goldSummary, 'promoted_count');
      const qdrantCount = summaryNumber(goldSummary, 'qdrant_upserted_count');
      const draftBits = [
        generatedCount !== null ? `generated ${generatedCount}` : '',
        sectionCount !== null ? `sections ${sectionCount}` : '',
        chunkCount !== null ? `chunks ${chunkCount}` : '',
      ].filter(Boolean);
      const goldBits = [
        promotedCount !== null ? `promoted ${promotedCount}` : '',
        qdrantCount !== null ? `qdrant ${qdrantCount}` : '',
      ].filter(Boolean);
      addLog('success', `[Silver] 구조화 초안 생성 완료${draftBits.length ? ` · ${draftBits.join(' · ')}` : ''}`);
      addLog('success', `[Gold] 플레이북 · 코퍼스 생성 완료${goldBits.length ? ` · ${goldBits.join(' · ')}` : ''}`);
      addLog(
        result.smoke.viewer_ready && result.smoke.source_meta_ready ? 'success' : 'warn',
        `[Judge] 라이브러리 합류 검증 ${result.smoke.viewer_ready && result.smoke.source_meta_ready ? '완료' : '점검 필요'} · viewer ${result.smoke.viewer_ready ? 'ok' : 'missing'} · source meta ${result.smoke.source_meta_ready ? 'ok' : 'missing'} · library ${result.smoke.approved_manifest_count}권`,
      );
      addLog('success', `${result.title} · ${result.source_label}로 Library에 반영됨`);
      refreshData();
      const nextQuery = searchQuery.trim() || record.title || record.book_slug.replace(/_/g, ' ');
      setSearchQuery(nextQuery);
      await runRepositorySearch(nextQuery);
      return result;
    } catch (error: unknown) {
      stopToolsRunHeartbeat();
      const message = errorMessage(error, `${record.title} 생산에 실패했습니다.`);
      addLog('error', message);
      throw new Error(message);
    } finally {
      stopToolsRunHeartbeat();
      setMaterializingOptionKey(null);
    }
  };

  const openPreview = async (draft: CustomerPackDraft) => {
    setPreviewDraft(draft);
    if (previewCapturedUrl) {
      URL.revokeObjectURL(previewCapturedUrl);
    }
    setPreviewCapturedUrl('');
    setPreviewCapturedType('');
    setPreviewViewerDocument(null);
    setPreviewLoading(true);

    try {
      if (draft.status === 'normalized') {
        const book = await loadCustomerPackBook(draft.draft_id);
        const viewerDocument = await loadViewerDocument(book.target_viewer_path);
        setPreviewViewerDocument({
          html: viewerDocument.html,
          inlineStyles: viewerDocument.inline_styles,
          bodyClassName: viewerDocument.body_class_name,
        });
      } else if (draft.capture_artifact_path) {
        const captured = await loadCustomerPackCapturedPreview(draft.draft_id);
        setPreviewCapturedType(captured.contentType);
        setPreviewCapturedUrl(URL.createObjectURL(captured.blob));
      }
    } catch {
      setPreviewCapturedUrl('');
      setPreviewCapturedType('');
      setPreviewViewerDocument(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const openPreviewViewerPath = async (viewerPath: string) => {
    const viewerDocument = await loadViewerDocument(viewerPath);
    setPreviewViewerDocument({
      html: viewerDocument.html,
      inlineStyles: viewerDocument.inline_styles,
      bodyClassName: viewerDocument.body_class_name,
      interactionPolicy: {
        codeCopy: viewerDocument.interaction_policy.code_copy,
        codeWrapToggle: viewerDocument.interaction_policy.code_wrap_toggle,
        recentPositionTracking: viewerDocument.interaction_policy.recent_position_tracking,
        anchorNavigation: viewerDocument.interaction_policy.anchor_navigation,
      },
    });
  };

  const closePreview = () => {
    if (previewCapturedUrl) {
      URL.revokeObjectURL(previewCapturedUrl);
    }
    setPreviewDraft(null);
    setPreviewCapturedUrl('');
    setPreviewCapturedType('');
    setPreviewViewerDocument(null);
  };

  const openChunkViewer = async (book: LibraryBook) => {
    const scope = String(book.chunk_scope || '').trim() === 'customer_pack' ? 'customer_pack' : 'runtime';
    const draftId = String(book.draft_id || '').trim()
      || (scope === 'customer_pack' ? book.book_slug.split('--', 1)[0] : '');
    setChunkViewer({
      title: book.title,
      payload: null,
      loading: true,
      error: '',
    });
    try {
      const payload = await loadDataControlRoomChunks({
        scope,
        bookSlug: book.book_slug,
        draftId: draftId || undefined,
      });
      setChunkViewer({
        title: book.title,
        payload,
        loading: false,
        error: '',
      });
    } catch (error: unknown) {
      setChunkViewer({
        title: book.title,
        payload: null,
        loading: false,
        error: errorMessage(error, 'Chunk detail load failed'),
      });
    }
  };

  const openMetricPopover = (kind: 'approved' | 'latestNonGold' | 'customerPack' | 'wikiRuntime' | 'navBacklog' | 'wikiUsage' | 'buyerGate' | 'buyerPackets' | 'corpus' | 'playbookFiles' | 'userCorpus') => {
    if (!controlRoom) return;
    const cr = controlRoom;
    let title = '';
    let mode: MetricPopoverMode = 'playbook';
    let books: LibraryBook[] = [];
    let packets: BuyerPacket[] = [];
    switch (kind) {
      case 'approved':
        title = 'Gold PlayBooks';
        books = [...(cr.gold_books ?? [])];
        break;
      case 'latestNonGold':
        title = 'Silver · Bronze PlayBooks';
        books = [...(cr.approved_wiki_runtime_books?.books ?? [])].filter((book) => normalizePlaybookGrade(book.grade) !== 'Gold');
        break;
      case 'customerPack':
        title = 'User PlayBooks';
        books = [...((cr.customer_pack_runtime_books ?? cr.user_library_books)?.books ?? [])];
        break;
      case 'wikiRuntime':
        title = 'Latest Pipeline PlayBooks';
        books = [...(cr.approved_wiki_runtime_books?.books ?? [])];
        break;
      case 'corpus':
        title = 'Corpus Files';
        mode = 'corpus';
        books = [...(cr.corpus?.books ?? [])];
        break;
      case 'playbookFiles':
        title = 'PlayBook Files';
        books = [...(cr.manualbooks?.books ?? [])];
        break;
      case 'userCorpus':
        title = 'User Corpus';
        mode = 'corpus';
        books = [...(cr.user_library_corpus?.books ?? [])];
        break;
      case 'navBacklog':
        title = 'Wiki Navigation Backlog';
        books = [...(cr.wiki_navigation_backlog?.books ?? [])];
        break;
      case 'wikiUsage':
        title = 'Usage';
        books = [...(cr.wiki_usage_signals?.books ?? [])];
        break;
      case 'buyerGate':
        title = 'Release Gate Surface';
        books = [...(cr.product_gate?.books ?? [])];
        break;
      case 'buyerPackets':
        title = 'Release Candidate Packets';
        packets = [...(cr.buyer_packet_bundle?.books ?? [])];
        break;
    }
    if (kind === 'buyerPackets') {
      setBuyerPacketPopover({ title, packets });
      return;
    }
    setMetricPopover({ title, mode, rows: books });
  };

  const openBuyerPacket = (packet: BuyerPacket) => {
    setBuyerPacketPopover(null);
    setBookViewer({
      book_slug: packet.book_slug,
      title: packet.title,
      grade: 'Release Packet',
      review_status: packet.review_status,
      source_type: 'buyer_packet_bundle',
      source_lane: 'buyer_packet_bundle',
      section_count: 1,
      code_block_count: 0,
      viewer_path: packet.viewer_path,
      source_url: packet.source_url,
      updated_at: '',
      approval_state: packet.approval_state,
      publication_state: packet.publication_state,
      runtime_truth_label: packet.runtime_truth_label,
      boundary_badge: packet.boundary_badge || 'Release Packet',
    });
  };

  const openReleaseCandidateFreeze = () => {
    if (releaseCandidatePacket) {
      openBuyerPacket(releaseCandidatePacket);
    }
  };

  const openChunkViewerDocument = (payload: CorpusChunkViewerResponse, viewerPath?: string) => {
    const nextViewerPath = String(viewerPath || payload.document_viewer_path || '').trim();
    if (!nextViewerPath) {
      return;
    }
    setChunkViewer(null);
    setBookViewer({
      book_slug: payload.book_slug,
      title: payload.title,
      grade: payload.scope === 'customer_pack' ? 'Bronze' : 'Gold',
      review_status: payload.scope === 'customer_pack'
        ? (payload.corpus_runtime_eligible ? 'approved' : 'private')
        : 'approved',
      source_type: payload.source_type,
      source_lane: payload.source_lane,
      section_count: payload.chunk_count,
      code_block_count: 0,
      viewer_path: nextViewerPath,
      source_url: payload.source_origin_url || '',
      updated_at: '',
      draft_id: payload.draft_id,
      runtime_truth_label: payload.runtime_truth_label,
      boundary_badge: payload.boundary_badge,
      source_collection: payload.source_collection,
      source_origin_label: payload.source_origin_label,
      source_origin_url: payload.source_origin_url,
      chunk_count: payload.chunk_count,
      token_total: payload.token_total,
      chunk_scope: payload.scope,
      delete_target_kind: payload.scope === 'customer_pack' ? 'customer_pack_draft' : '',
      delete_target_id: payload.draft_id || '',
      delete_target_label: payload.source_origin_label || payload.title,
      corpus_runtime_eligible: payload.corpus_runtime_eligible,
      corpus_vector_status: payload.vector_status,
    });
  };

  const stageLabel = (stage: PipelineStage) => {
    if (stage === 'idle') return '대기 중';
    if (stage === 'error') return '문서 처리 실패';
    if (stage === 'ready') return '기본 인덱싱 확인';
    return `${uploadStageTitle(stage)} 처리 중`;
  };

  const isProcessing = pipelineStage !== 'idle' && pipelineStage !== 'ready' && pipelineStage !== 'error';

  const stageFromUploadEvent = (event: UploadIngestStreamEvent): PipelineStage | null => {
    if (event.type === 'error') return 'error';
    if (event.type === 'result') return null;
    if (USER_UPLOAD_STAGE_ORDER.includes(event.stage as UserUploadStage)) {
      return event.stage as UserUploadStage;
    }
    return null;
  };

  const latestUploadStageByName = useMemo(() => {
    const byStage = new Map<string, UploadIngestStreamStageEvent>();
    uploadStageEvents.forEach((event) => byStage.set(event.stage, event));
    return byStage;
  }, [uploadStageEvents]);

  const liveUploadProgressItems = useMemo(
    () => progressFromUploadEvents(uploadStageEvents),
    [uploadStageEvents],
  );

  const uploadStepState = (stage: UserUploadStage, index: number): 'idle' | 'running' | 'done' | 'warning' | 'failed' => {
    void index;
    const state = uploadStageStateFromEvents(uploadStageEvents, stage);
    if (state !== 'idle') return state;
    if (pipelineStage === 'error') return 'failed';
    return 'idle';
  };

  const logUploadStreamEvent = (event: UploadIngestStreamEvent) => {
    if (event.type === 'result') return;
    if (event.type === 'error') {
      addLog('error', event.error || 'Upload ingestion stream failed');
      return;
    }
    const suffixParts = [
      typeof event.duration_ms === 'number' ? formatDurationMs(event.duration_ms) : '',
      typeof (event.counts?.block_count ?? event.block_count) === 'number'
        ? `${event.counts?.block_count ?? event.block_count} blocks`
        : '',
      typeof (event.counts?.chunk_count ?? event.chunk_count) === 'number'
        ? `${event.counts?.chunk_count ?? event.chunk_count} chunks`
        : '',
      typeof (event.counts?.indexed_count ?? event.indexed_count) === 'number'
        && typeof (event.counts?.candidate_count ?? event.candidate_count) === 'number'
        ? `${event.counts?.indexed_count ?? event.indexed_count}/${event.counts?.candidate_count ?? event.candidate_count} indexed`
        : '',
      typeof event.progress_current === 'number' && typeof event.progress_total === 'number' && event.progress_total > 0
        ? `${event.progress_current}/${event.progress_total}`
        : '',
    ].filter(Boolean);
    const suffix = suffixParts.length ? ` (${suffixParts.join(', ')})` : '';
    const tag: LogEntry['tag'] = event.status === 'failed'
      ? 'error'
      : event.status === 'done' || event.status === 'duplicate' || event.status === 'skipped'
        ? 'success'
        : event.status === 'warning'
          ? 'warn'
          : 'info';
    addLog(tag, `[${uploadStageTitle(event.stage)}] ${event.message}${suffix}`);
  };

  const summary = controlRoom?.summary;
  const officialCorpusBooks = [...(controlRoom?.corpus?.books ?? [])];
  const officialPlaybookBooks = [...(controlRoom?.manualbooks?.books ?? [])];
  const userLibraryBucket = controlRoom?.customer_pack_runtime_books ?? controlRoom?.user_library_books;
  const userCorpusBooks = [...(controlRoom?.user_library_corpus?.books ?? [])];
  const repositoryDocumentRows = useMemo<RepositoryDocumentRow[]>(
    () => documentRepositories.flatMap((repository) =>
      (repository.documents ?? []).map((document) => ({
        repository,
        document,
        categoryKey: inferWikiCategory(document, repository),
      })),
    ),
    [documentRepositories],
  );
  const userUploadDocumentRows = useMemo(
    () => repositoryDocumentRows.filter(({ document, repository }) => {
      const scope = String(document.source_scope || repository.metadata?.source_scope || '').toLowerCase();
      const visibility = String(document.visibility || repository.visibility || '').toLowerCase();
      return scope.includes('user') || visibility === 'private_user';
    }),
    [repositoryDocumentRows],
  );
  const userUploadIndexedChunkCount = userUploadDocumentRows.reduce(
    (total, { document }) => total + Number(document.indexed_chunk_count || 0),
    0,
  );
  const userUploadChunkCount = userUploadDocumentRows.reduce(
    (total, { document }) => total + Number(document.chunk_count || 0),
    0,
  );
  const approvedRuntimeBooks = summary?.approved_runtime_count ?? summary?.gold_book_count ?? controlRoom?.gold_books?.length ?? 0;
  const userLibraryBooks = [...(userLibraryBucket?.books ?? [])];
  const userLibraryBookCount = summary?.customer_pack_runtime_book_count
    ?? summary?.user_library_book_count
    ?? userLibraryBooks.length;
  const userRuntimePlaybookCount = summary?.customer_pack_runtime_book_count ?? userLibraryBooks.length;
  const officialCorpusBookCount = summary?.corpus_book_count ?? officialCorpusBooks.length;
  const officialPlaybookFileCount = summary?.manualbook_count ?? officialPlaybookBooks.length;
  const userCorpusBookCount = summary?.user_library_corpus_book_count ?? userCorpusBooks.length;
  const approvedWikiRuntimeBooks = summary?.approved_wiki_runtime_book_count ?? controlRoom?.approved_wiki_runtime_books?.books?.length ?? 0;
  const allOperationalWikiBooks = [...(controlRoom?.approved_wiki_runtime_books?.books ?? [])];
  const goldOperationalWikiBooks = allOperationalWikiBooks.filter((book) => normalizePlaybookGrade(book.grade) === 'Gold');
  const latestNonGoldOperationalWikiBooks = allOperationalWikiBooks.filter((book) => normalizePlaybookGrade(book.grade) !== 'Gold');
  const goldPlaybookCount = allOperationalWikiBooks.length ? goldOperationalWikiBooks.length : approvedRuntimeBooks;
  const latestNonGoldPlaybookCount = allOperationalWikiBooks.length
    ? latestNonGoldOperationalWikiBooks.length
    : Math.max(approvedWikiRuntimeBooks - approvedRuntimeBooks, 0);
  const wikiNavigationBacklog = summary?.wiki_navigation_backlog_count ?? controlRoom?.wiki_navigation_backlog?.books?.length ?? 0;
  const wikiUsageSignals = summary?.wiki_usage_signal_count ?? controlRoom?.wiki_usage_signals?.books?.length ?? 0;
  const productGate = summary?.product_gate_count ?? controlRoom?.product_gate?.books?.length ?? 0;
  const buyerPacketBundle = summary?.buyer_packet_bundle_count ?? controlRoom?.buyer_packet_bundle?.books?.length ?? 0;
  const releaseCandidateFreeze = controlRoom?.release_candidate_freeze;
  const releaseCandidatePacket = controlRoom?.buyer_packet_bundle?.books?.find(
    (packet) => packet.book_slug === 'buyer_packet__release-candidate-freeze',
  ) ?? null;
  const hasMetricSourceDrift = Boolean(controlRoom?.source_of_truth_drift?.status_alignment?.mismatches?.length);
  const gate = controlRoom?.gate;
  const productRehearsal = controlRoom?.product_rehearsal;
  const gateReasons = [
    ...((gate?.reasons ?? []).slice(0, 3)),
    ...((gate?.summary?.failed_validation_checks ?? []).slice(0, 2)),
    ...((gate?.summary?.failed_data_quality_checks ?? []).slice(0, 2)),
  ].filter(Boolean).slice(0, 3);
  const hasProductRehearsalMetric = typeof productRehearsal?.critical_scenario_pass_rate === 'number';
  const productGatePassRate = hasProductRehearsalMetric
    ? Math.round((productRehearsal?.critical_scenario_pass_rate ?? 0) * 100)
    : null;
  const productGateBlockerCopy = !productRehearsal
    ? 'Product rehearsal unavailable'
    : productRehearsal.status === 'missing'
      ? 'Current product rehearsal report is missing'
      : productRehearsal.blockers?.length
        ? productRehearsal.blockers.join(' · ')
        : 'No current gate blockers';
  const productRehearsalStatus = !productRehearsal || productRehearsal.status === 'missing'
    ? 'Missing'
    : productRehearsal.blockers?.length
      ? 'Blocking'
      : 'Passing';
  const gateBannerCopy = gate?.release_blocking
    ? `Release blocked · ${gate?.status ?? 'unknown'}`
    : `Release gate · ${gate?.status ?? 'unknown'}`;
  const groupedFavorites = REPOSITORY_CATEGORIES.map((category) => ({
    category,
    items: repositoryFavorites.filter((item) => item.favorite_category === category),
  })).filter((group) => group.items.length > 0);
  const toolsRunActive = Boolean(materializingOptionKey) || factoryDownloadList.some((item) => item.status === 'producing');
  const factoryManualFocusItem = useMemo(
    () => factoryDownloadList.find((item) => item.id === factoryManualFocusId) ?? factoryDownloadList[0] ?? null,
    [factoryDownloadList, factoryManualFocusId],
  );
  const factoryManualSnapshot = factoryManualFocusItem ? factoryMaterializationSnapshots[factoryManualFocusItem.id] ?? null : null;
  const factoryManualChecklist = useMemo(
    () => buildFactoryManualChecklist(factoryManualFocusItem, factoryManualSnapshot),
    [factoryManualFocusItem, factoryManualSnapshot],
  );
  const userManualFocusDraft = useMemo(() => {
    const preferredId = String(factoryManualFocusId ?? '').startsWith('draft:')
      ? String(factoryManualFocusId).slice(6)
      : factoryManualFocusId;
    return drafts.find((draft) => draft.draft_id === preferredId) ?? drafts[0] ?? null;
  }, [drafts, factoryManualFocusId]);
  const userManualLinkedBook = useMemo(() => {
    if (!userManualFocusDraft) {
      return null;
    }
    return userLibraryBooks.find(
      (book) => book.book_slug === userManualFocusDraft.book_slug || book.title === userManualFocusDraft.title,
    ) ?? null;
  }, [userLibraryBooks, userManualFocusDraft]);
  const userManualChecklist = useMemo(
    () => buildUserManualChecklist(userManualFocusDraft, userManualLinkedBook),
    [userManualFocusDraft, userManualLinkedBook],
  );
  const factoryManualSubjectKey = factoryLane === 'tools'
    ? factoryManualFocusItem?.id ?? null
    : userManualFocusDraft ? `draft:${userManualFocusDraft.draft_id}` : null;
  const activeFactoryManualChecklist = factoryLane === 'tools' ? factoryManualChecklist : userManualChecklist;
  const factoryManualCheckedIds = factoryManualSubjectKey ? factoryManualChecklistState[factoryManualSubjectKey] ?? [] : [];
  const factoryManualRequirementItems = factoryManualSubjectKey ? factoryManualRequirements[factoryManualSubjectKey] ?? [] : [];
  const bookFactoryStatusLabel = factoryLane === 'user'
    ? stageLabel(pipelineStage)
    : toolsRunActive
      ? 'Book Factory Running...'
      : repositoryStage === 'loading'
        ? 'Finding Source Candidates...'
        : repositoryUnanswered.length > 0
          ? `${repositoryUnanswered.length} source requests queued`
          : 'Source Finder Ready';
  const bookFactoryStatusClass = factoryLane === 'user'
    ? pipelineStage === 'error'
      ? 'error'
      : pipelineStage === 'ready'
        ? 'done'
        : ''
    : factoryDownloadList.some((item) => item.status === 'error')
      ? 'error'
      : factoryDownloadList.some((item) => item.status === 'done')
        ? 'done'
        : repositoryStage === 'error'
          ? 'error'
          : repositoryStage === 'done'
            ? 'done'
            : '';
  const bookFactoryModeSummary = factoryLane === 'user'
    ? `${userLibraryBookCount} user books · ${latestUploadIngest?.chunk_count ?? userCorpusBookCount} chunks`
    : `${repositoryUnanswered.length} requests · ${repositoryFavorites.length} saved sources`;
  const toggleFactoryManualChecklist = (checkId: string) => {
    if (!factoryManualSubjectKey) return;
    setFactoryManualChecklistState((prev) => {
      const current = prev[factoryManualSubjectKey] ?? [];
      const next = current.includes(checkId)
        ? current.filter((item) => item !== checkId)
        : [...current, checkId];
      return { ...prev, [factoryManualSubjectKey]: next };
    });
  };
  const addFactoryManualRequirement = () => {
    if (!factoryManualSubjectKey) return;
    const next = factoryManualRequirementDraft.trim();
    if (!next) return;
    setFactoryManualRequirements((prev) => ({
      ...prev,
      [factoryManualSubjectKey]: [...(prev[factoryManualSubjectKey] ?? []), next],
    }));
    setFactoryManualRequirementDraft('');
  };
  const removeFactoryManualRequirement = (index: number) => {
    if (!factoryManualSubjectKey) return;
    setFactoryManualRequirements((prev) => ({
      ...prev,
      [factoryManualSubjectKey]: (prev[factoryManualSubjectKey] ?? []).filter((_, itemIndex) => itemIndex !== index),
    }));
  };
  const activeFactoryFormats = useMemo(
    () =>
      SUPPORTED_FORMATS.map((format) => ({
        ...format,
        active: factoryLane === 'tools' ? toolsFormatActive(format.ext) : true,
      })),
    [factoryLane],
  );
  const toolsPipelineState = useMemo(() => {
    if (materializingOptionKey || factoryDownloadList.some((item) => item.status === 'producing')) {
      return { activeIndex: 0, completedIndex: -1 };
    }
    if (factoryDownloadList.some((item) => item.status === 'done') && !factoryDownloadList.some((item) => item.status === 'producing')) {
      return { activeIndex: 3, completedIndex: 3 };
    }
    return { activeIndex: -1, completedIndex: -1 };
  }, [factoryDownloadList, materializingOptionKey]);
  const assistantHint = factoryAssistantQuery.trim() || searchQuery.trim();
  const generatedCatalogRows = useMemo(() => officialCatalogRows, [officialCatalogRows]);
  const generatedCatalogPreferredBasis = useMemo(
    () => inferCatalogPreferredBasis(generatedCatalogPrompt),
    [generatedCatalogPrompt],
  );
  const generatedCatalogQueuedCount = useMemo(
    () =>
      officialCatalogRows.filter((row) =>
        factoryDownloadList.some((item) => item.record.book_slug === row.book_slug),
      ).length,
    [factoryDownloadList, officialCatalogRows],
  );
  const generatedCatalogBulkActions = useMemo(() => {
    const actions: Array<{ key: OfficialSourceBasisKey; label: string }> = [
      { key: 'official_repo', label: '공식 레포 전권 받기' },
      { key: 'official_homepage', label: '공식 홈페이지 전권 받기' },
    ];
    if (generatedCatalogPreferredBasis === 'official_homepage') {
      return [actions[1], actions[0]];
    }
    return actions;
  }, [generatedCatalogPreferredBasis]);
  const activeLibrarySurface = viewMode === 'repository' ? 'uploads' : 'official';
  const connectedOfficialBookCountLabel = controlRoom ? allOperationalWikiBooks.length.toLocaleString() : '--';
  const librarySurfaceCards = [
    {
      key: 'official',
      label: '공식 문서',
      value: allOperationalWikiBooks.length,
      detail: '연결 완료 문서',
      icon: BookOpen,
      action: () => navigate('/playbook-library/control-tower'),
    },
    {
      key: 'uploads',
      label: '내 업로드',
      value: userUploadDocumentRows.length,
      detail: `${userCorpusBookCount.toLocaleString()}개 사용자 코퍼스`,
      icon: UploadCloud,
      action: () => navigate('/playbook-library/repository'),
    },
  ];

  return (
    <div className="library-wrapper">
      <div className="bokeh-bg bokeh-1"></div>
      <div className="bokeh-bg bokeh-2"></div>

      <AppHeader
        currentPage="library"
        globalTheme={globalTheme}
        onOpenDashboard={() => navigate(ROUTES.pbsControlTower)}
        onOpenLibrary={() => navigate(ROUTES.pbsPlaybookLibrary)}
        onOpenStudio={() => navigate(ROUTES.pbsStudio)}
        onToggleGlobalTheme={toggleGlobalTheme}
        title="WIKI Library"
      />

      <main className="library-main">
        <div className="library-shell">
          <div className="library-content-panel">
            <section id="system-data-board" className={`library-runtime-board ${viewMode === 'repository' ? 'compact' : ''}`}>
              <div className="library-runtime-board-head">
                <div className="library-board-tabs" role="tablist" aria-label="Library surface">
                  {librarySurfaceCards.map((card) => {
                    const Icon = card.icon;
                    const active = card.key === activeLibrarySurface;
                    return (
                      <button
                        key={card.key}
                        type="button"
                        className={`library-board-tab ${active ? 'active' : ''}`}
                        onClick={card.action}
                      >
                        <Icon size={16} />
                        <span>{card.label}</span>
                      </button>
                    );
                  })}
                </div>

                <button type="button" className="library-runtime-refresh" onClick={refreshData}>
                  새로고침
                </button>
              </div>

              {viewMode === 'monitoring' ? (
                <>
                  <div className="library-runtime-board-copy">
                    <span className="factory-hub-eyebrow">공식 지식 베이스</span>
                    <h2>현재 연결된 공식 문서</h2>
                    <p>플랫폼에서 바로 질문 범위로 선택할 수 있는 공식 문서를 한 화면에 보여줍니다.</p>
                  </div>

                  <div className="library-runtime-summary" aria-label="Official document connection summary">
                    <span>공식 문서 {connectedOfficialBookCountLabel}권</span>
                    <span>현재 런타임 연결 기준</span>
                  </div>
                </>
              ) : (
                <div className="library-upload-summary" aria-label="업로드 문서 요약">
                  <span>업로드 문서 {userUploadDocumentRows.length.toLocaleString()}개</span>
                  <span>인덱싱 {userUploadIndexedChunkCount.toLocaleString()} / {userUploadChunkCount.toLocaleString()} 청크</span>
                  <span>인덱싱 완료 후 문서 단위 질문 가능</span>
                </div>
              )}
            </section>

        {viewMode === 'monitoring' ? (
          <div className="monitoring-view">
            <section className="operational-shelf box-container">
              <div className="operational-shelf-header">
                <div>
                  <span className="operational-shelf-eyebrow">공식 문서</span>
                  <h2>연결된 공식 문서 {connectedOfficialBookCountLabel}권</h2>
                  <p>현재 런타임에 연결된 공식 문서 전체입니다. 문서는 전체 페이지로 열고, 원천소스 기준은 카드 안에서 바로 확인합니다.</p>
                </div>
                <span className="operational-library-count">{connectedOfficialBookCountLabel}권</span>
              </div>
              {!controlRoom ? (
                <div className="repo-empty">
                  <Loader2 size={32} className="spin-icon" />
                  <p>연결된 공식 문서를 불러오는 중입니다.</p>
                </div>
              ) : allOperationalWikiBooks.length === 0 ? (
                <div className="repo-empty">
                  <Database size={36} />
                  <p>연결된 공식 문서가 아직 없습니다.</p>
                </div>
              ) : (
                <div className="operational-library-grid">
                  {allOperationalWikiBooks.map((book) => (
                    <article
                      key={`official-${book.book_slug}`}
                      className="operational-library-card"
                    >
                      <div className="operational-card-open">
                        <span className="operational-library-card-badge">{normalizePlaybookGrade(book.grade)}</span>
                        <strong>{book.title}</strong>
                        <span className="operational-card-open-subtitle">{book.book_slug.replace(/_/g, ' ')}</span>
                      </div>
                      <div className="library-document-actions">
                        <OfficialSourcePopover record={book} />
                        <button
                          type="button"
                          className="library-document-chat-btn"
                          onClick={() => {
                            setBookViewerPageMode('single');
                            setBookViewer(book);
                          }}
                        >
                          <BookOpen size={14} />
                          <span>문서 열기</span>
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>

            {releaseCandidateFreeze?.exists && (
              <section className="release-freeze-hero">
                <div className="release-freeze-hero-copy">
                  <span className="release-freeze-eyebrow">Current Freeze</span>
                  <h2>{releaseCandidateFreeze.title}</h2>
                  <p>{releaseCandidateFreeze.close || releaseCandidateFreeze.commercial_truth}</p>
                  <div className="release-freeze-meta">
                    <span>{releaseCandidateFreeze.current_stage || 'paid_poc_candidate'}</span>
                    <span>{releaseCandidateFreeze.runtime_count} runtime books</span>
                    <span>
                      product gate {releaseCandidateFreeze.product_gate_pass_count}/{releaseCandidateFreeze.product_gate_scenario_count}
                    </span>
                    <span>{releaseCandidateFreeze.release_blocker_count} blockers</span>
                  </div>
                </div>
                <div className="release-freeze-hero-actions">
                  <button
                    type="button"
                    className="release-freeze-primary-btn"
                    onClick={openReleaseCandidateFreeze}
                    disabled={!releaseCandidatePacket}
                  >
                    <FileText size={16} />
                    <span>Open Packet</span>
                  </button>
                  <button
                    type="button"
                    className="release-freeze-secondary-btn"
                    onClick={() => openMetricPopover('buyerPackets')}
                  >
                    <Layers size={16} />
                    <span>Packets</span>
                  </button>
                </div>
              </section>
            )}

            {(gate || hasMetricSourceDrift) && (
              <div className="truth-banner">
                <AlertCircle size={16} />
                <div className="truth-banner-copy">
                  {gate && (
                    <>
                      <strong>{gateBannerCopy}</strong>
                      <span>{gateReasons.length > 0 ? gateReasons.join(' · ') : 'Aligned with current runtime evidence.'}</span>
                    </>
                  )}
                  {productRehearsal && (
                    <span>
                      {productRehearsal.status === 'missing'
                        ? productGateBlockerCopy
                        : `Product gate ${productRehearsal.pass_count}/${productRehearsal.scenario_count} · ${productGateBlockerCopy}`}
                    </span>
                  )}
                  {hasMetricSourceDrift && (
                    <span>Current approval and storage counts are shown.</span>
                  )}
                </div>
              </div>
            )}

            <section className="metrics-grid metrics-grid-primary">
              <div className="metric-card metric-card-priority metric-clickable" onClick={() => openMetricPopover('approved')}>
                <div className="metric-icon"><ShieldCheck size={24} /></div>
                <div className="metric-data">
                  <h3>{goldPlaybookCount.toLocaleString()}</h3>
                  <p>Gold PlayBooks</p>
                </div>
                <div className="metric-status online">Gold</div>
              </div>
              <div className="metric-card metric-card-priority metric-clickable" onClick={() => openMetricPopover('latestNonGold')}>
                <div className="metric-icon"><Layers size={24} /></div>
                <div className="metric-data">
                  <h3>{latestNonGoldPlaybookCount.toLocaleString()}</h3>
                  <p>Silver · Bronze PlayBooks</p>
                </div>
                <div className="metric-trend positive">
                  <BookOpen size={14} /> <span>Latest</span>
                </div>
              </div>
              <div className="metric-card metric-card-priority metric-clickable" onClick={() => openMetricPopover('wikiRuntime')}>
                <div className="metric-icon"><CheckCircle2 size={24} /></div>
                <div className="metric-data">
                  <h3>{approvedWikiRuntimeBooks.toLocaleString()}</h3>
                  <p>Latest Pipeline PlayBooks</p>
                </div>
                <div className="metric-status online">Runtime</div>
              </div>
              <div className="metric-card metric-card-priority metric-clickable" onClick={() => openMetricPopover('buyerGate')}>
                <div className="metric-icon"><ShieldAlert size={24} /></div>
                <div className="metric-data">
                  <h3>{productGate.toLocaleString()}</h3>
                  <p>Release Gate</p>
                </div>
                <div className="metric-status warning">Release</div>
              </div>
            </section>

            {(
              <section className="metrics-grid metrics-grid-secondary">
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('customerPack')}>
                  <div className="metric-icon"><HardDrive size={24} /></div>
                  <div className="metric-data">
                    <h3>{userRuntimePlaybookCount.toLocaleString()}</h3>
                    <p>User Library</p>
                  </div>
                  <div className="metric-status optimized">Private</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('userCorpus')}>
                  <div className="metric-icon"><Database size={24} /></div>
                  <div className="metric-data">
                    <h3>{userCorpusBookCount.toLocaleString()}</h3>
                    <p>User Corpus</p>
                  </div>
                  <div className="metric-status optimized">Chat</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('corpus')}>
                  <div className="metric-icon"><Database size={24} /></div>
                  <div className="metric-data">
                    <h3>{officialCorpusBookCount.toLocaleString()}</h3>
                    <p>Corpus Files</p>
                  </div>
                  <div className="metric-status online">Runtime</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('playbookFiles')}>
                  <div className="metric-icon"><BookOpen size={24} /></div>
                  <div className="metric-data">
                    <h3>{officialPlaybookFileCount.toLocaleString()}</h3>
                    <p>PlayBook Files</p>
                  </div>
                  <div className="metric-status online">Viewer</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('navBacklog')}>
                  <div className="metric-icon"><Search size={24} /></div>
                  <div className="metric-data">
                    <h3>{wikiNavigationBacklog.toLocaleString()}</h3>
                    <p>Wiki Navigation Backlog</p>
                  </div>
                  <div className="metric-status online">Signals</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('wikiUsage')}>
                  <div className="metric-icon"><Star size={24} /></div>
                  <div className="metric-data">
                    <h3>{wikiUsageSignals.toLocaleString()}</h3>
                    <p>Usage</p>
                  </div>
                  <div className="metric-status optimized">Personal</div>
                </div>
                <div className="metric-card metric-card-secondary metric-clickable" onClick={() => openMetricPopover('buyerPackets')}>
                  <div className="metric-icon"><FileText size={24} /></div>
                  <div className="metric-data">
                    <h3>{buyerPacketBundle.toLocaleString()}</h3>
                    <p>Release Candidate Packets</p>
                  </div>
                  <div className="metric-status online">Packets</div>
                </div>
                <div className="metric-card metric-card-secondary">
                  <div className="metric-icon"><CheckCircle2 size={24} /></div>
                  <div className="metric-data">
                    <h3>{productGatePassRate === null ? '--' : `${productGatePassRate}%`}</h3>
                    <p>Product Rehearsal</p>
                  </div>
                  <div className={`metric-status ${productRehearsalStatus === 'Passing' ? 'online' : 'warning'}`}>
                    {productRehearsalStatus}
                  </div>
                </div>
              </section>
            )}
          </div>
        ) : (
          <div className="repository-view">
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={DOCUMENT_INGEST_UPLOAD_ACCEPT}
              onChange={handleUpload}
            />

            <section className="library-repository-strip box-container">
              <div className="section-header">
                <div>
                  <h2>내 업로드</h2>
                  <p className="text-muted">개인 문서를 업로드하면 세션 범위 안에서만 Studio Chat의 검색 근거로 연결합니다.</p>
                  <div className="library-upload-flow" aria-label="Upload ingestion flow">
                    <span>업로드</span>
                    <span>파싱/청킹</span>
                    <span>PostgreSQL 저장</span>
                    <span>Qdrant 인덱싱</span>
                    <span>챗봇 질문 가능</span>
                  </div>
                </div>
                <div className="library-section-actions">
                  <button
                    type="button"
                    className="upload-trigger-btn"
                    onClick={() => openUserDocsUpload(true)}
                    disabled={isProcessing}
                  >
                    {isProcessing ? <Loader2 size={16} className="spin-icon" /> : <UploadCloud size={16} />}
                    <span>{isProcessing ? '처리 중...' : '문서 업로드'}</span>
                  </button>
                  <button type="button" className="library-dashboard-link" onClick={refreshDocumentRepositories}>
                    새로고침
                  </button>
                </div>
              </div>
              {userUploadDocumentRows.length === 0 ? (
                <div className="repo-empty">
                  <Database size={36} />
                  <p>아직 업로드한 문서가 없습니다.</p>
                  <span>문서를 올리면 처리 단계와 인덱싱 결과를 카드에서 바로 확인할 수 있습니다.</span>
                </div>
              ) : (
                <div className="library-repository-grid library-upload-grid">
                  {userUploadDocumentRows.map(({ repository, document, categoryKey }) => {
                    const status = repositoryDocumentStatus(document);
                    const title = document.title || document.filename || 'Untitled upload';
                    const subtitle = document.filename && document.filename !== title ? document.filename : repository.title || repository.slug;
                    return (
                      <article className="library-repository-card library-upload-card" key={document.document_source_id}>
                        <div className="library-upload-card-top">
                          <span className="library-repository-scope">{document.source_scope || repository.visibility || repository.repository_kind}</span>
                          <span className={`library-upload-status library-upload-status--${status.tone}`}>{status.label}</span>
                        </div>
                        <div className="library-upload-card-main">
                          <FileText size={20} className="library-upload-icon" />
                          <div>
                            <h3>{title}</h3>
                            <p>{subtitle}</p>
                          </div>
                        </div>
                        <div className="library-upload-facts" aria-label={`${title} repository status`}>
                          <span>{status.detail}</span>
                          <span>업로드 묶음 {repository.document_count.toLocaleString()}개 문서</span>
                          <span>{repositoryDocumentUpdatedLabel(document, repository)}</span>
                        </div>
                        <div className="library-upload-proof" aria-label={`${title} RAG ingestion proof`}>
                          <span>PostgreSQL 저장 기록</span>
                          <span>Qdrant {document.indexed_chunk_count.toLocaleString()}개 인덱싱</span>
                          <span>세션 범위 기록</span>
                        </div>
                        <div className="library-document-actions">
                          <button
                            type="button"
                            className="library-document-chat-btn library-document-chat-btn--reader"
                            onClick={() => openUploadedDocumentReader(document)}
                          >
                            <BookOpen size={14} />
                            <span>문서 보기</span>
                          </button>
                          <button
                            type="button"
                            className="library-document-chat-btn library-document-chat-btn--report"
                            onClick={() => openUploadProcessingReport(document)}
                          >
                            <Clock size={14} />
                            <span>작업 로그</span>
                          </button>
                          <button
                            type="button"
                            className="library-document-chat-btn"
                            onClick={() => openDocumentInChat(repository, document, categoryKey)}
                          >
                            <MessageSquare size={14} />
                            <span>이 문서로 질문</span>
                          </button>
                          <button
                            type="button"
                            className="library-document-chat-btn library-document-chat-btn--secondary"
                            onClick={() => openRepositoryInChat(repository)}
                          >
                            <Layers size={14} />
                            <span>전체 업로드로 질문</span>
                          </button>
                          <button
                            type="button"
                            className="library-document-chat-btn library-document-chat-btn--danger"
                            disabled={deletingDocumentId === document.document_source_id}
                            onClick={() => handleUploadedDocumentDelete(document.document_source_id, title)}
                            title="이 문서와 관련 인덱스를 모두 삭제"
                          >
                            {deletingDocumentId === document.document_source_id
                              ? <Loader2 size={14} className="spin-icon" />
                              : <Trash2 size={14} />}
                            <span>삭제</span>
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="pipeline-section box-container factory-workbench-section">
              <div className="factory-workbench-top">
                <div className="factory-workbench-headline">
                  <span className="factory-hub-eyebrow">Production Surface</span>
                  <div className="factory-workbench-title-row">
                    <h2>Book Factory</h2>
                    <span className="factory-workbench-title-tag">
                      {factoryLane === 'tools' ? 'Book Factory Pipeline' : 'User Docs Pipeline'}
                    </span>
                  </div>
                  <p className="text-muted">
                    {factoryLane === 'tools'
                      ? '질문에서 부족한 공식 문서를 source candidate로 받아 공장 대기열로 올립니다.'
                      : '사용자 문서를 업로드해 위키형 책과 코퍼스로 생산합니다.'}
                  </p>
                </div>
                <div className="factory-workbench-controls">
                  <div className="factory-mode-toggle" role="tablist" aria-label="Book Factory mode">
                    <button
                      type="button"
                      className={`factory-mode-btn ${factoryRunMode === 'auto' ? 'active' : ''}`}
                      onClick={() => setFactoryRunMode('auto')}
                    >
                      자동
                    </button>
                    <button
                      type="button"
                      className={`factory-mode-btn ${factoryRunMode === 'manual' ? 'active' : ''}`}
                      onClick={() => setFactoryRunMode('manual')}
                    >
                      수동
                    </button>
                  </div>
                  <div className={`pipeline-status ${bookFactoryStatusClass}`}>
                    {bookFactoryStatusClass === 'error' ? (
                      <AlertCircle size={14} className="status-icon-error" />
                    ) : factoryLane === 'user' && isProcessing ? (
                      <Loader2 size={14} className="spin-icon" />
                    ) : factoryLane === 'tools' && repositoryStage === 'loading' ? (
                      <Loader2 size={14} className="spin-icon" />
                    ) : (
                      <div className={`status-dot ${bookFactoryStatusClass === 'done' ? 'done' : 'pulsing'}`}></div>
                    )}
                    <span>{bookFactoryStatusLabel}</span>
                  </div>
                </div>
              </div>

              <div className="factory-workbench-toolbar">
                <div className="factory-entry-strip">
                  <button
                    type="button"
                    className={`factory-entry-btn ${factoryLane === 'tools' ? 'active' : ''}`}
                    onClick={() => { void openToolsDocsUpload(); }}
                  >
                    <Database size={16} />
                    <span>Official Source Pipeline</span>
                  </button>
                  <button
                    type="button"
                    className={`factory-entry-btn ${factoryLane === 'user' ? 'active' : ''}`}
                    onClick={() => setFactoryLane('user')}
                  >
                    <UploadCloud size={16} />
                    <span>User Document Pipeline</span>
                  </button>
                </div>

                <div className="factory-entry-caption">
                  <span>{bookFactoryModeSummary}</span>
                  <span>·</span>
                  <span>
                    {factoryLane === 'tools'
                      ? '공식 레포와 공식 홈페이지 후보를 받아 생산 대기열로 연결합니다.'
                      : '현재 업로드 lane을 Book Factory 안으로 합쳐 same-surface production으로 보여줍니다.'}
                  </span>
                </div>
              </div>

              <div className={`format-strip format-strip--${factoryLane}`}>
                <span className="format-label">Supported Inputs</span>
                <div className="format-tags">
                  {activeFactoryFormats.map((f) => (
                    <span
                      key={f.ext}
                      className={`format-tag ${f.via === 'MarkItDown' ? 'markitdown' : f.via === 'OCR' ? 'ocr' : ''} ${f.active ? 'active' : 'inactive'}`}
                    >
                      {f.ext}
                    </span>
                  ))}
                </div>
              </div>

              {factoryLane === 'user' && currentFile && isProcessing && (
                <div className="current-file-banner">
                  <FileText size={14} />
                  <span>{currentFile}</span>
                </div>
              )}

              {factoryLane === 'user' && errorMsg && (
                <div className="pipeline-error-banner">
                  <AlertCircle size={14} />
                  <span>{errorMsg}</span>
                </div>
              )}

              {factoryLane === 'tools' ? (
                <div className="pipeline-visualizer pipeline-visualizer--factory-tools">
                  {FACTORY_PIPELINE_STEPS.tools.map((step, index) => (
                    <React.Fragment key={step.badge}>
                      <div
                        className={`pipeline-step ${index <= toolsPipelineState.completedIndex ? 'completed' : ''
                          } ${index === toolsPipelineState.activeIndex ? 'active' : ''} ${index === 3 && toolsPipelineState.activeIndex === 3 ? 'final' : ''
                          }`}
                      >
                        <div className="step-badge">{step.badge}</div>
                        <div className="step-icon">
                          {index === 0 ? <Search /> : index === 1 ? <BookmarkPlus /> : index === 2 ? <UploadCloud /> : <BookOpen />}
                        </div>
                        <div className="step-info">
                          <h4>{step.title}</h4>
                          <p>{step.description}</p>
                        </div>
                      </div>
                      {index < FACTORY_PIPELINE_STEPS.tools.length - 1 && (
                        <div
                          className={`pipeline-connector ${index < toolsPipelineState.completedIndex ? 'filled' : ''
                            } ${index === toolsPipelineState.activeIndex - 1 ? 'flowing' : ''}`}
                        >
                          <div className="flow-particle"></div>
                        </div>
                      )}
                    </React.Fragment>
                  ))}
                </div>
              ) : (
                <div className="pipeline-visualizer pipeline-visualizer--user-upload" ref={pipelineRef}>
                  {USER_UPLOAD_PIPELINE_STEPS.map((step, index) => {
                    const stepState = uploadStepState(step.stage, index);
                    const event = latestUploadStageByName.get(step.stage);
                    const icon = step.stage === 'received'
                      ? <UploadCloud />
                      : step.stage === 'store'
                        ? <HardDrive />
                        : step.stage === 'parse'
                          ? <FileText />
                          : step.stage === 'chunk'
                            ? <Layers />
                            : step.stage === 'persist'
                              ? <Database />
                              : step.stage === 'index'
                                ? <Cpu />
                                : step.stage === 'scope'
                                  ? <ShieldCheck />
                                  : <BookOpen />;
                    return (
                      <div
                        className={`pipeline-step pipeline-step--compact pipeline-step--stage-${step.stage} pipeline-step--${stepState} ${stepState === 'done' ? 'completed' : ''} ${stepState === 'running' ? 'active' : ''} ${step.stage === 'ready' && stepState === 'done' ? 'final' : ''}`}
                        key={step.stage}
                      >
                        <div className="step-badge">{step.badge}</div>
                        <div className="step-icon">
                          {stepState === 'running' ? <Loader2 className="spin-icon" /> : icon}
                        </div>
                        <div className="step-info">
                          <h4>{step.title}</h4>
                          <p>{event?.message || step.description}</p>
                          {typeof event?.duration_ms === 'number' ? (
                            <span className="step-duration">{formatDurationMs(event.duration_ms)}</span>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {factoryRunMode === 'manual' && (
                <div className="factory-manual-workbench">
                  <div className="factory-manual-workbench-header">
                    <div className="factory-manual-note-copy">
                      <span className="factory-manual-note-eyebrow">Manual Mode</span>
                      <strong>단계별 산출물과 규칙 체크리스트를 직접 보고 조정하는 자리</strong>
                      <p>
                        {factoryLane === 'tools'
                          ? 'Queue에 저장한 공식 문서 후보 중 하나를 골라 현재 생산선의 결과와 다음 단계 할 일을 손으로 확인합니다.'
                          : '업로드한 초안 중 하나를 골라 캡처, 정규화, User Library 합류 상태를 손으로 확인합니다.'}
                      </p>
                    </div>
                    {factoryLane === 'tools' && factoryDownloadList.length > 0 && (
                      <label className="factory-manual-selector">
                        <span>검토 대상</span>
                        <select
                          value={factoryManualFocusItem?.id ?? ''}
                          onChange={(event) => setFactoryManualFocusId(event.target.value || null)}
                        >
                          {factoryDownloadList.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.friendlyLabel}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {factoryLane === 'user' && drafts.length > 0 && (
                      <label className="factory-manual-selector">
                        <span>검토 대상</span>
                        <select
                          value={userManualFocusDraft?.draft_id ?? ''}
                          onChange={(event) => setFactoryManualFocusId(event.target.value ? `draft:${event.target.value}` : null)}
                        >
                          {drafts.map((draft) => (
                            <option key={draft.draft_id} value={draft.draft_id}>
                              {draft.title}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>

                  {!factoryManualSubjectKey ? (
                    <div className="factory-manual-empty">
                      <MessageSquare size={28} />
                      <p>
                        {factoryLane === 'tools'
                          ? '다운로드 리스트에 공식 문서 후보를 하나 이상 저장하면 수동 검토가 열립니다.'
                          : '업로드한 초안이 하나 이상 있으면 수동 검토가 열립니다.'}
                      </p>
                    </div>
                  ) : (
                    <div className="factory-manual-grid">
                      <section className="factory-manual-card">
                        <div className="factory-manual-card-header">
                          <div>
                            <span className="factory-manual-card-eyebrow">Artifacts</span>
                            <h3>단계별 산출물</h3>
                          </div>
                          {factoryLane === 'tools' ? (
                            <span className={`operational-source-basis operational-source-basis--${String(factoryManualFocusItem?.record.current_source_basis || 'unknown').trim() || 'unknown'}`}>
                              {sourceBasisLabel(factoryManualFocusItem?.record)}
                            </span>
                          ) : (
                            <span className="operational-source-basis operational-source-basis--unknown">
                              {userManualFocusDraft?.source_type?.toUpperCase() || 'UPLOAD'}
                            </span>
                          )}
                        </div>

                        <div className="factory-manual-stage-list">
                          <article className="factory-manual-stage">
                            <div className="factory-manual-stage-top">
                              <span className="step-badge">Bronze</span>
                              <strong>원천 바인딩</strong>
                            </div>
                            {factoryLane === 'tools' ? (
                              <ul>
                                <li>대상: {factoryManualFocusItem?.friendlyLabel}</li>
                                <li>질문: {factoryManualFocusItem?.requestQuery}</li>
                                <li>원천: {factoryManualFocusItem?.option.label}</li>
                              </ul>
                            ) : (
                              <ul>
                                <li>파일: {userManualFocusDraft?.uploaded_file_name || userManualFocusDraft?.title}</li>
                                <li>타입: {userManualFocusDraft?.source_type?.toUpperCase() || '-'}</li>
                                <li>캡처: {userManualFocusDraft?.capture_artifact_path ? 'ready' : 'pending'}</li>
                              </ul>
                            )}
                          </article>

                          <article className="factory-manual-stage">
                            <div className="factory-manual-stage-top">
                              <span className="step-badge">Silver</span>
                              <strong>구조화 초안 생성</strong>
                            </div>
                            {factoryLane === 'tools' ? (
                              factoryManualSnapshot ? (
                                <ul>
                                  <li>generated {summaryNumber(factoryManualSnapshot.draft_summary, 'generated_count') ?? '-'}</li>
                                  <li>sections {summaryNumber(factoryManualSnapshot.draft_summary, 'section_count') ?? '-'}</li>
                                  <li>chunks {summaryNumber(factoryManualSnapshot.draft_summary, 'chunk_count') ?? '-'}</li>
                                </ul>
                              ) : (
                                <p>생산을 실행하면 sections / chunks / 초안 생성 결과가 여기에 표시됩니다.</p>
                              )
                            ) : userManualFocusDraft ? (
                              <ul>
                                <li>status {userManualFocusDraft.status}</li>
                                <li>parser {userManualFocusDraft.parser_backend || userManualFocusDraft.parser_route || '-'}</li>
                                <li>quality {userManualFocusDraft.quality_score > 0 ? `${userManualFocusDraft.quality_score}/100 · ${userManualFocusDraft.quality_status}` : (userManualFocusDraft.quality_status || '-')}</li>
                              </ul>
                            ) : (
                              <p>업로드한 초안의 정규화 상태와 parser route가 여기에 표시됩니다.</p>
                            )}
                          </article>

                          <article className="factory-manual-stage">
                            <div className="factory-manual-stage-top">
                              <span className="step-badge">Gold</span>
                              <strong>플레이북 · 코퍼스 생성</strong>
                            </div>
                            {factoryLane === 'tools' ? (
                              factoryManualSnapshot ? (
                                <ul>
                                  <li>promoted {summaryNumber(factoryManualSnapshot.gold_summary, 'promoted_count') ?? '-'}</li>
                                  <li>qdrant {summaryNumber(factoryManualSnapshot.gold_summary, 'qdrant_upserted_count') ?? '-'}</li>
                                  <li>{factoryManualSnapshot.source_label}</li>
                                </ul>
                              ) : (
                                <p>생산을 실행하면 플레이북 승격과 코퍼스 반영 결과가 여기에 표시됩니다.</p>
                              )
                            ) : userManualFocusDraft ? (
                              <ul>
                                <li>playable {userManualFocusDraft.playable_asset_count}</li>
                                <li>derived {userManualFocusDraft.derived_asset_count}</li>
                                <li>{userManualFocusDraft.quality_summary || 'quality summary unavailable'}</li>
                              </ul>
                            ) : (
                              <p>정규화 이후 playable / derived asset과 품질 요약이 여기에 표시됩니다.</p>
                            )}
                          </article>

                          <article className="factory-manual-stage">
                            <div className="factory-manual-stage-top">
                              <span className="step-badge">Judge</span>
                              <strong>라이브러리 합류 검증</strong>
                            </div>
                            {factoryLane === 'tools' ? (
                              factoryManualSnapshot ? (
                                <ul>
                                  <li>viewer {factoryManualSnapshot.smoke.viewer_ready ? 'ok' : 'missing'}</li>
                                  <li>source meta {factoryManualSnapshot.smoke.source_meta_ready ? 'ok' : 'missing'}</li>
                                  <li>library {factoryManualSnapshot.smoke.approved_manifest_count}권</li>
                                </ul>
                              ) : (
                                <p>생산 완료 후 viewer / source meta / library 반영 검증이 여기에 표시됩니다.</p>
                              )
                            ) : userManualLinkedBook ? (
                              <ul>
                                <li>viewer {userManualLinkedBook.viewer_path ? 'ok' : 'missing'}</li>
                                <li>sections {userManualLinkedBook.section_count}</li>
                                <li>{customerPackBookTruth(userManualLinkedBook) || userManualLinkedBook.source_lane || 'User Library ready'}</li>
                              </ul>
                            ) : (
                              <p>User Library 합류가 완료되면 viewer 경로와 section 수가 여기에 표시됩니다.</p>
                            )}
                          </article>
                        </div>
                      </section>

                      <section className="factory-manual-card">
                        <div className="factory-manual-card-header">
                          <div>
                            <span className="factory-manual-card-eyebrow">Checklist</span>
                            <h3>다음 단계 규칙 제안</h3>
                          </div>
                          <span className="factory-manual-card-meta">
                            {factoryManualCheckedIds.length}/{activeFactoryManualChecklist.length} checked
                          </span>
                        </div>

                        <div className="factory-manual-checklist">
                          {activeFactoryManualChecklist.map((item) => (
                            <label className="factory-manual-check" key={item.id}>
                              <input
                                type="checkbox"
                                checked={factoryManualCheckedIds.includes(item.id)}
                                onChange={() => toggleFactoryManualChecklist(item.id)}
                              />
                              <div className="factory-manual-check-copy">
                                <span className="factory-manual-check-stage">{item.stage}</span>
                                <strong>{item.title}</strong>
                                <p>{item.detail}</p>
                              </div>
                            </label>
                          ))}
                        </div>

                        <div className="factory-manual-requirements">
                          <div className="factory-manual-requirements-header">
                            <span className="factory-manual-card-eyebrow">Custom Input</span>
                            <strong>사용자 추가 요구</strong>
                          </div>
                          {factoryManualRequirementItems.length > 0 && (
                            <div className="factory-manual-requirement-list">
                              {factoryManualRequirementItems.map((item, index) => (
                                <div className="factory-manual-requirement-item" key={`${item}-${index}`}>
                                  <span>{item}</span>
                                  <button type="button" onClick={() => removeFactoryManualRequirement(index)}>
                                    <X size={14} />
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="factory-manual-input-row">
                            <input
                              type="text"
                              value={factoryManualRequirementDraft}
                              onChange={(event) => setFactoryManualRequirementDraft(event.target.value)}
                              placeholder="예: 공식 KO 용어 우선, figure caption 유지"
                            />
                            <button type="button" onClick={addFactoryManualRequirement}>
                              추가
                            </button>
                          </div>
                        </div>
                      </section>
                    </div>
                  )}
                </div>
              )}

              <div className="pipeline-details">
                <div className="log-container">
                  <div className="log-header">{factoryLane === 'tools' ? 'Book Factory Processing Logs' : 'Recent Processing Logs'}</div>
                  {factoryLane === 'user' && liveUploadProgressItems.length > 0 && (
                    <div className="upload-progress-board" aria-label="Upload detailed progress">
                      <div className="upload-progress-board-head">
                        <span>작업별 진행률</span>
                        <strong>{currentFile || latestUploadIngest?.filename || '업로드 문서'}</strong>
                      </div>
                      <div className="upload-progress-list">
                        {liveUploadProgressItems.map((item) => (
                          <div className={`upload-progress-row upload-progress-row--${uploadStageTone(item.status)}`} key={item.key}>
                            <div className="upload-progress-row-top">
                              <span>{item.label}</span>
                              <strong>{item.current.toLocaleString()} / {item.total.toLocaleString()}</strong>
                            </div>
                            <div className="upload-progress-track" aria-hidden="true">
                              <span style={{ width: `${item.percent}%` }} />
                            </div>
                            <div className="upload-progress-row-bottom">
                              <span>{item.message}</span>
                              <em>{item.percent}%</em>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {logs.length === 0 && (
                    <div className="log-empty">
                      {factoryLane === 'tools' ? '생산을 시작하면 단계별 로그가 여기에 표시됩니다.' : 'No activity yet.'}
                    </div>
                  )}
                  {logs.map((log, i) => (
                    <div className="log-item" key={i}>
                      <span className="log-time">{log.time}</span>
                      <span className={`log-tag tag-${log.tag}`}>{log.tag.toUpperCase()}</span>
                      <span className="log-msg">{log.msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {factoryLane === 'tools' && (
              <>
                <section className="repo-panel box-container">
                  <div className="book-factory-workspace">
                    <div className="book-factory-sidebar">
                      <section className="factory-fold-section">
                        <button
                          type="button"
                          className="factory-fold-header"
                          onClick={() => setSourceRequestsExpanded((prev) => !prev)}
                        >
                          <div>
                            <span className="factory-fold-eyebrow">Queue</span>
                            <strong>Source Requests</strong>
                          </div>
                          <div className="factory-fold-meta">
                            <span>{repositoryUnanswered.length}</span>
                            <ChevronDown size={16} className={sourceRequestsExpanded ? 'is-open' : ''} />
                          </div>
                        </button>
                        {sourceRequestsExpanded && (
                          repositoryUnanswered.length === 0 ? (
                            <div className="repo-empty repo-unanswered-empty">
                              <AlertCircle size={28} />
                              <p>아직 저장된 미답변 질문이 없습니다.</p>
                            </div>
                          ) : (
                            <div className="repo-unanswered-list repo-unanswered-list--compact">
                              {repositoryUnanswered.map((item) => (
                                <div className="repo-unanswered-item repo-unanswered-item--row" key={`${item.timestamp}-${item.query}`}>
                                  <div className="repo-unanswered-main">
                                    <div className="repo-unanswered-query">{item.query}</div>
                                    <div className="repo-unanswered-meta">
                                      <span>{new Date(item.timestamp).toLocaleString()}</span>
                                      {item.warnings.length > 0 ? <span>{item.warnings[0]}</span> : null}
                                    </div>
                                  </div>
                                  <button
                                    type="button"
                                    className="repo-search-btn repo-search-btn--inline"
                                    onClick={() => { void handleFactoryAssistantSubmit(item.query); }}
                                  >
                                    <MessageSquare size={14} />
                                    <span>문의하기</span>
                                  </button>
                                </div>
                              ))}
                            </div>
                          )
                        )}
                      </section>

                      <section className="factory-fold-section">
                        <button
                          type="button"
                          className="factory-fold-header"
                          onClick={() => setDownloadListExpanded((prev) => !prev)}
                        >
                          <div>
                            <span className="factory-fold-eyebrow">Queue</span>
                            <strong>다운로드 리스트</strong>
                          </div>
                          <div className="factory-fold-meta">
                            <span>{factoryDownloadList.length}</span>
                            <ChevronDown size={16} className={downloadListExpanded ? 'is-open' : ''} />
                          </div>
                        </button>
                        {downloadListExpanded && (
                          factoryDownloadList.length === 0 ? (
                            <div className="repo-empty repo-unanswered-empty">
                              <BookmarkPlus size={28} />
                              <p>아직 저장된 원천소스가 없습니다.</p>
                            </div>
                          ) : (
                            <div className="factory-download-list">
                              {factoryDownloadList.map((item) => (
                                <article className="factory-download-item" key={item.id}>
                                  <div className="factory-download-copy">
                                    <strong>{item.friendlyLabel}</strong>
                                    <span>{item.requestQuery}</span>
                                    {item.message ? <span>{item.message}</span> : null}
                                  </div>
                                  <div className="factory-download-actions">
                                    <a
                                      className="repo-link-btn"
                                      href={String(item.option.href || '').trim()}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      <ExternalLink size={14} />
                                      <span>원본</span>
                                    </a>
                                    <button
                                      type="button"
                                      className="operational-source-option-produce"
                                      onClick={() => { void handleDownloadListMaterialize(item); }}
                                      disabled={Boolean(materializingOptionKey)}
                                    >
                                      {item.status === 'producing' ? <Loader2 size={13} className="spin-icon" /> : <UploadCloud size={13} />}
                                      <span>{item.status === 'done' ? '완료됨' : item.status === 'producing' ? '생산 중...' : '생산'}</span>
                                    </button>
                                    <button
                                      type="button"
                                      className="favorite-remove-btn"
                                      onClick={() => handleRemoveDownloadItem(item.id)}
                                      disabled={item.status === 'producing'}
                                    >
                                      <Trash2 size={14} />
                                    </button>
                                  </div>
                                </article>
                              ))}
                            </div>
                          )
                        )}
                      </section>

                      <section className="factory-fold-section">
                        <button
                          type="button"
                          className="factory-fold-header"
                          onClick={() => setOfficialCatalogExpanded((prev) => !prev)}
                        >
                          <div>
                            <span className="factory-fold-eyebrow">Plan</span>
                            <strong>OCP 4.20 Generated Catalog</strong>
                          </div>
                          <div className="factory-fold-meta">
                            <span>{officialCatalogLiveCount}/{officialCatalogTotalCount || 113}</span>
                            <ChevronDown size={16} className={officialCatalogExpanded ? 'is-open' : ''} />
                          </div>
                        </button>
                        {officialCatalogExpanded && (
                          <div className="factory-catalog-panel">
                            <>
                              <div className="factory-generated-catalog-intro">
                                <div className="factory-generated-catalog-copy">
                                  <span className="factory-hub-eyebrow">
                                    {generatedCatalogPrompt.trim() ? 'Generated by Assistant' : 'Default Catalog'}
                                  </span>
                                  <strong>OCP 4.20 공식 문서 목록 {officialCatalogTotalCount || 113}권</strong>
                                  <p>
                                    {generatedCatalogPrompt.trim()
                                      ? <>질문 <code>{generatedCatalogPrompt}</code> 기준으로 {preferredCatalogBasisLabel(generatedCatalogPreferredBasis)} 원천소스를 정리했습니다. 필요할 때 하나씩 받거나 전권을 큐에 넣을 수 있습니다.</>
                                      : <>기본 원천 목록입니다. 이미 준비된 책은 <code>Ready</code>로 보이고, 없는 책은 바로 받거나 전권을 큐에 넣을 수 있습니다.</>}
                                  </p>
                                </div>
                                <div className="factory-catalog-bulk-actions">
                                  {generatedCatalogBulkActions.map((action) => (
                                    <button
                                      type="button"
                                      key={action.key}
                                      className={`factory-catalog-bulk-btn ${generatedCatalogPreferredBasis === action.key ? 'is-primary' : ''}`}
                                      onClick={() => handleQueueOfficialCatalogAll(action.key)}
                                    >
                                      <Download size={14} />
                                      <span>{action.label}</span>
                                    </button>
                                  ))}
                                </div>
                              </div>
                              <div className="factory-catalog-summary">
                                <span>전체 {officialCatalogTotalCount || 113}권</span>
                                <span>Ready {officialCatalogLiveCount}권</span>
                                <span>Queue {generatedCatalogQueuedCount}권</span>
                                <span>대상 {Math.max((officialCatalogTotalCount || 0) - officialCatalogLiveCount, 0)}권</span>
                              </div>
                              <div className="factory-catalog-legend">
                                <span className="factory-catalog-legend-item factory-catalog-legend-item--live">Ready</span>
                                <span className="factory-catalog-legend-item factory-catalog-legend-item--queued">다운로드 대기</span>
                                <span className="factory-catalog-legend-item factory-catalog-legend-item--producing">생산 중</span>
                                <span className="factory-catalog-legend-item factory-catalog-legend-item--candidate">아직 없음</span>
                              </div>
                              {generatedCatalogRows.length === 0 ? (
                                <div className="repo-empty repo-unanswered-empty">
                                  <AlertCircle size={28} />
                                  <p>OCP 4.20 기본 목록을 아직 불러오지 못했습니다.</p>
                                </div>
                              ) : (
                                <div className="factory-catalog-list">
                                  {generatedCatalogRows.map((row, rowIndex) => {
                                    const rowOptions = [...sourceOptionsForRecord(row)
                                      .filter((option) => option.availability === 'available' && option.href)]
                                      .sort((left, right) => {
                                        if (generatedCatalogPreferredBasis === 'mixed') {
                                          return 0;
                                        }
                                        const leftPriority = left.key === generatedCatalogPreferredBasis ? 0 : 1;
                                        const rightPriority = right.key === generatedCatalogPreferredBasis ? 0 : 1;
                                        return leftPriority - rightPriority;
                                      });
                                    const queuedItems = factoryDownloadList.filter((item) => item.record.book_slug === row.book_slug);
                                    const producing = Boolean(materializingOptionKey && materializingOptionKey.startsWith(`${row.book_slug}:`));
                                    const queued = queuedItems.length > 0;
                                    const rowStatus = producing
                                      ? 'producing'
                                      : row.status_kind === 'live'
                                        ? 'live'
                                        : queued
                                          ? 'queued'
                                          : 'candidate';
                                    const rowStatusLabel = producing
                                      ? '생산 중'
                                      : row.status_kind === 'live'
                                        ? 'Ready'
                                        : queued
                                          ? '다운로드 대기'
                                          : '아직 없음';
                                    const isOpen = openCatalogRowSlug === row.book_slug;
                                    return (
                                      <div className={`factory-catalog-item factory-catalog-item--${rowStatus} ${isOpen ? 'is-open' : ''}`} key={row.book_slug}>
                                        <button
                                          type="button"
                                          className="factory-catalog-summary-row"
                                          aria-expanded={isOpen}
                                          onClick={() => setOpenCatalogRowSlug((prev) => prev === row.book_slug ? null : row.book_slug)}
                                        >
                                          <span className="factory-catalog-main">
                                            <span className="factory-catalog-main-top">
                                              <span className="factory-catalog-order">{String(rowIndex + 1).padStart(3, '0')}</span>
                                              <span className="factory-catalog-slug">{row.book_slug.replace(/_/g, ' ')}</span>
                                            </span>
                                            <strong>{row.title}</strong>
                                            <span>{catalogSourceDetail(row)}</span>
                                          </span>
                                          <span className="factory-catalog-meta">
                                            <span className={`operational-source-basis operational-source-basis--${String(row.current_source_basis || 'unknown').trim() || 'unknown'}`}>
                                              {sourceBasisLabel(row)}
                                            </span>
                                            <span className={`factory-catalog-status factory-catalog-status--${rowStatus}`}>
                                              {rowStatusLabel}
                                            </span>
                                            <ChevronDown size={14} className={`factory-catalog-chevron ${isOpen ? 'is-open' : ''}`} />
                                          </span>
                                        </button>
                                        {isOpen ? (
                                          <div className="factory-catalog-options">
                                            {rowOptions.map((option) => {
                                              const actionKey = sourceOptionActionKey(row, option);
                                              const saved = factoryDownloadList.some((item) => item.id === actionKey);
                                              return (
                                                <div className="factory-candidate-option" key={actionKey}>
                                                  <div className="factory-candidate-option-copy">
                                                    <strong>{friendlySourceOptionLabel(row, option)}</strong>
                                                    <span>{option.note}</span>
                                                  </div>
                                                  <div className="operational-source-option-actions">
                                                    <a
                                                      className="operational-source-option-link"
                                                      href={option.href}
                                                      target="_blank"
                                                      rel="noreferrer"
                                                    >
                                                      <ExternalLink size={13} />
                                                      <span>원본</span>
                                                    </a>
                                                    <button
                                                      type="button"
                                                      className="operational-source-option-save"
                                                      onClick={() => handleQueueOfficialSource(row, option, generatedCatalogPrompt)}
                                                      disabled={saved || row.status_kind === 'live'}
                                                    >
                                                      <BookmarkPlus size={13} />
                                                      <span>{row.status_kind === 'live' ? '있음' : saved ? '저장됨' : '하나 받기'}</span>
                                                    </button>
                                                  </div>
                                                </div>
                                              );
                                            })}
                                          </div>
                                        ) : null}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </>
                          </div>
                        )}
                      </section>
                    </div>

                    <section className="book-factory-assistant glass-panel">
                      <div className="repo-panel-header">
                        <div>
                          <span className="factory-hub-eyebrow">Factory Assistant</span>
                          <h2>Official Source Intake</h2>
                          <p className="text-muted">
                            답하지 못한 질문에서 공식 레포 AsciiDoc과 공식 웹페이지 manual 후보를 찾고, 내려받을 계획표를 준비합니다.
                          </p>
                        </div>
                        <div className="repo-panel-badge">
                          <Database size={14} />
                          <span>{repositoryMeta.authMode === 'token' ? 'Authenticated Search' : 'Public Search'}</span>
                        </div>
                      </div>

                      <form
                        className="repo-search-form"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void handleFactoryAssistantSubmit();
                        }}
                      >
                        <div className="search-bar repo-search-bar">
                          <MessageSquare size={18} />
                          <input
                            ref={repositorySearchInputRef}
                            type="text"
                            placeholder="예: 호스팅 컨트롤 플레인 아키텍처를 요약해줘"
                            value={factoryAssistantQuery}
                            onChange={(e) => setFactoryAssistantQuery(e.target.value)}
                          />
                        </div>
                        <button
                          type="submit"
                          className="repo-search-btn"
                          disabled={repositoryStage === 'loading'}
                        >
                          {repositoryStage === 'loading' ? <Loader2 size={16} className="spin-icon" /> : <Search size={16} />}
                          <span>{repositoryStage === 'loading' ? '찾는 중...' : '원천소스 찾기'}</span>
                        </button>
                      </form>

                      {(assistantHint || factoryAssistantError || repositoryMeta.rewrittenQuery) && (
                        <div className="repo-meta-strip">
                          {assistantHint ? <span>질문: <code>{assistantHint}</code></span> : null}
                          <span>repo matches: <code>{repositoryResults.length}</code></span>
                          {repositoryMeta.rewrittenQuery ? <span>rewritten: <code>{repositoryMeta.rewrittenQuery}</code></span> : null}
                          {factoryAssistantError ? <span className="repo-error-text">{factoryAssistantError}</span> : null}
                          {repositoryError ? <span className="repo-error-text">{repositoryError}</span> : null}
                        </div>
                      )}

                      {officialSourceCandidates.length === 0 ? (
                        <div className="repo-empty">
                          <MessageSquare size={40} />
                          <p>문의하기를 누르거나 질문을 직접 넣으면 공식 원천소스 두 종류와 다운로드 계획표를 준비합니다.</p>
                        </div>
                      ) : (
                        <div className="factory-assistant-results">
                          {officialSourceCandidates.map((candidate) => (
                            <article className="repo-card repo-card--official glass-panel" key={candidate.book_slug}>
                              <div className="card-header repo-card-header repo-card-header--stack">
                                <div className="repo-card-source-meta">
                                  <span
                                    className={`operational-source-basis operational-source-basis--${String(candidate.current_source_basis || 'unknown').trim() || 'unknown'
                                      }`}
                                  >
                                    {sourceBasisLabel(candidate)}
                                  </span>
                                  <span
                                    className="status-pill"
                                    data-status={
                                      materializingOptionKey?.startsWith(`${candidate.book_slug}:`)
                                        ? 'processing'
                                        : candidate.status_kind === 'live'
                                          ? 'ready'
                                          : 'processing'
                                    }
                                  >
                                    {materializingOptionKey?.startsWith(`${candidate.book_slug}:`) ? '생산 중' : candidate.status_label}
                                  </span>
                                </div>
                                <span className="repo-candidate-score">match {candidate.match_score}</span>
                              </div>

                              <div className="card-body">
                                <h4>{candidate.title}</h4>
                                <p className="text-muted">
                                  {candidate.book_slug.replace(/_/g, ' ')}
                                  {candidate.source_relative_path ? ` · ${candidate.source_relative_path}` : ''}
                                </p>
                              </div>

                              <div className="factory-candidate-options">
                                {sourceOptionsForRecord(candidate)
                                  .filter((option) => option.availability === 'available' && option.href)
                                  .map((option) => {
                                    const actionKey = sourceOptionActionKey(candidate, option);
                                    const saved = factoryDownloadList.some((item) => item.id === actionKey);
                                    return (
                                      <div className="factory-candidate-option" key={actionKey}>
                                        <div className="factory-candidate-option-copy">
                                          <strong>{friendlySourceOptionLabel(candidate, option)}</strong>
                                          <span>{option.note}</span>
                                        </div>
                                        <div className="operational-source-option-actions">
                                          <a
                                            className="operational-source-option-link"
                                            href={option.href}
                                            target="_blank"
                                            rel="noreferrer"
                                          >
                                            <ExternalLink size={13} />
                                            <span>원본</span>
                                          </a>
                                          <button
                                            type="button"
                                            className="operational-source-option-save"
                                            onClick={() => handleQueueOfficialSource(candidate, option, assistantHint || candidate.title)}
                                            disabled={saved}
                                          >
                                            <BookmarkPlus size={13} />
                                            <span>{saved ? '저장됨' : '하나 받기'}</span>
                                          </button>
                                        </div>
                                      </div>
                                    );
                                  })}
                              </div>

                              {candidate.status_kind === 'live' && candidate.viewer_path ? (
                                <div className="card-footer repo-card-footer repo-card-footer--official">
                                  <OfficialSourcePopover
                                    record={candidate}
                                    onMaterializeOption={handleOfficialSourceMaterialize}
                                    materializingOptionKey={materializingOptionKey}
                                  />
                                  <a
                                    className="repo-link-btn"
                                    href={toRuntimeUrl(candidate.viewer_path)}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <ExternalLink size={14} />
                                    <span>Open Book</span>
                                  </a>
                                </div>
                              ) : null}
                            </article>
                          ))}
                        </div>
                      )}
                    </section>
                  </div>
                </section>

                <section className="repo-favorites-section box-container">
                  <div className="section-header">
                    <h2>Saved Source Candidates</h2>
                  </div>

                  {groupedFavorites.length === 0 ? (
                    <div className="repo-empty repo-favorites-empty">
                      <BookmarkPlus size={40} />
                      <p>아직 저장된 source candidate가 없습니다.</p>
                    </div>
                  ) : (
                    <div className="favorites-groups">
                      {groupedFavorites.map((group) => (
                        <div className="favorite-group" key={group.category}>
                          <div className="favorite-group-header">
                            <h3>{group.category}</h3>
                            <span>{group.items.length}</span>
                          </div>
                          <div className="favorite-group-list">
                            {group.items.map((favorite) => (
                              <div className="favorite-item" key={favorite.full_name}>
                                <div className="favorite-item-main">
                                  <div className="favorite-item-title">
                                    <Database size={14} />
                                    <span>{favorite.full_name}</span>
                                  </div>
                                  <p className="text-muted">{favorite.description || 'No description available.'}</p>
                                </div>
                                <div className="favorite-item-actions">
                                  <a
                                    className="repo-link-btn"
                                    href={favorite.html_url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <ExternalLink size={14} />
                                    <span>Open</span>
                                  </a>
                                  <button
                                    type="button"
                                    className="favorite-remove-btn"
                                    onClick={() => handleRemoveFavorite(favorite.full_name)}
                                    disabled={removingFavoriteName === favorite.full_name}
                                  >
                                    {removingFavoriteName === favorite.full_name ? (
                                      <Loader2 size={14} className="spin-icon" />
                                    ) : (
                                      <Trash2 size={14} />
                                    )}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}

            {factoryLane === 'user' && (
              <>

                {userLibraryBooks.length > 0 && (
                  <section className="draft-management user-library-section box-container">
                    <div className="section-header">
                      <div>
                        <h2>User Library ({userLibraryBookCount})</h2>
                        <p className="text-muted">Normalized uploads that are ready to open from the private library.</p>
                      </div>
                      <button
                        type="button"
                        className="operational-shelf-link"
                        onClick={() => openMetricPopover('customerPack')}
                      >
                        Open All
                      </button>
                    </div>
                    <div className="draft-grid">
                      {userLibraryBooks.map((book) => (
                        <button
                          type="button"
                          className="draft-card user-library-card"
                          key={book.book_slug}
                          onClick={() => setBookViewer(book)}
                        >
                          <div className="draft-card-top">
                            <span className="draft-type">User Library</span>
                            <span className={`draft-status-badge status-${book.review_status === 'approved' ? 'green' : 'cyan'}`}>
                              {book.review_status}
                            </span>
                          </div>
                          <h4 className="draft-title">{book.title}</h4>
                          <div className="draft-meta">
                            <span>{customerPackBookTruth(book) || book.source_lane}</span>
                            <span>{book.section_count} sections</span>
                            <span className={playbookGradeBadgeClass(book.grade)}>{normalizePlaybookGrade(book.grade)}</span>
                          </div>
                          {customerPackBookEvidenceBits(book).length > 0 && (
                            <div className="preview-chip-row">
                              {customerPackBookEvidenceBits(book).slice(0, 3).map((item) => (
                                <span key={item} className="preview-chip">{item}</span>
                              ))}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </section>
                )}

                {drafts.length > 0 && (
                  <section className="draft-management box-container">
                    <div className="section-header">
                      <h2>Uploaded Drafts ({drafts.length})</h2>
                    </div>
                    <div className="draft-grid">
                      {drafts.map((draft) => (
                        <div className="draft-card" key={draft.draft_id} onClick={() => openPreview(draft)} style={{ cursor: 'pointer' }}>
                          <div className="draft-card-top">
                            <FileText size={18} className="draft-file-icon" />
                            <span className={`draft-status-badge status-${statusColor(draft.status)}`}>
                              {draft.status}
                            </span>
                          </div>
                          <h4 className="draft-title">{draft.title}</h4>
                          <div className="draft-meta">
                            <span className="draft-type">{draft.source_type.toUpperCase()}</span>
                            {draft.uploaded_byte_size ? (
                              <span>{formatBytes(draft.uploaded_byte_size)}</span>
                            ) : null}
                            {draft.quality_score > 0 && (
                              <span className="draft-quality">Q:{draft.quality_score}</span>
                            )}
                          </div>
                          {draft.derived_asset_count > 0 && (
                            <div className="draft-assets">
                              <CheckCircle2 size={12} />
                              <span>{draft.playable_asset_count} playable · {draft.derived_asset_count} derived</span>
                            </div>
                          )}
                          <div className="draft-card-footer">
                            <span className="draft-date">
                              <Clock size={12} />
                              {new Date(draft.created_at).toLocaleDateString()}
                            </span>
                            <button
                              className="draft-delete-btn"
                              onClick={(e) => { e.stopPropagation(); handleDelete(draft.draft_id, draft.title, true); }}
                              disabled={deletingId === draft.draft_id}
                              title="Delete draft"
                            >
                              {deletingId === draft.draft_id ? <Loader2 size={14} className="spin-icon" /> : <Trash2 size={14} />}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        )}
          </div>
        </div>
      </main>

      {/* Preview Popover */}
      {previewDraft && (
        <div className="preview-overlay" onClick={closePreview}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{previewDraft.title}</h3>
                <div className="preview-header-meta">
                  <span className={`draft-status-badge status-${statusColor(previewDraft.status)}`}>{previewDraft.status}</span>
                  <span>{previewDraft.source_type.toUpperCase()}</span>
                  {previewDraft.uploaded_byte_size ? <span>{formatBytes(previewDraft.uploaded_byte_size)}</span> : null}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="preview-delete-btn"
                  onClick={async () => { const ok = await handleDelete(previewDraft.draft_id, previewDraft.title, true); if (ok) closePreview(); }}
                  disabled={deletingId === previewDraft.draft_id}
                  title="Delete"
                >
                  {deletingId === previewDraft.draft_id ? <Loader2 size={16} className="spin-icon" /> : <Trash2 size={16} />}
                </button>
                <button className="preview-close-btn" onClick={closePreview}><X size={18} /></button>
              </div>
            </div>
            <div className="preview-body">
              {previewLoading && (
                <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> Loading viewer...</div>
              )}
              {!previewLoading && previewViewerDocument && (
                <div className="preview-viewer-shell">
                  <ViewerDocumentStage
                    viewerDocument={previewViewerDocument}
                    onNavigateViewerPath={(viewerPath) => { void openPreviewViewerPath(viewerPath); }}
                    className="preview-viewer-document"
                  />
                </div>
              )}
              {!previewLoading && !previewViewerDocument && previewCapturedUrl && (
                <iframe
                  title={previewDraft.title}
                  className="preview-viewer-frame"
                  src={previewCapturedUrl}
                  sandbox={previewCapturedType.includes('text/html') ? 'allow-same-origin' : undefined}
                />
              )}
              {!previewLoading && !previewViewerDocument && !previewCapturedUrl && (
                <div className="preview-no-sections">
                  {previewDraft.status === 'planned'
                    ? '아직 캡처되지 않은 초안입니다. Capture/Normalize 후 미리보기를 확인할 수 있습니다.'
                    : '뷰어를 불러올 수 없습니다.'}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Metric Detail Popover */}
      {metricPopover && (
        <div className="preview-overlay" onClick={() => setMetricPopover(null)}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{metricPopover.title}</h3>
                <div className="preview-header-meta">
                  <span>{metricPopover.rows.length} {metricPopover.mode === 'corpus' ? 'corpus books' : 'books'}</span>
                </div>
              </div>
              <button className="preview-close-btn" onClick={() => setMetricPopover(null)}><X size={18} /></button>
            </div>
            <div className="metric-popover-body">
              {metricPopover.rows.length === 0 ? (
                <div className="preview-no-sections">등록된 북이 없습니다.</div>
              ) : (
                <div className="metric-book-list">
                  {metricPopover.rows.map((book) => {
                    const isCorpusMode = metricPopover.mode === 'corpus';
                    const sourceHref = bookSourceOriginHref(book);
                    const sourceLabel = bookSourceOriginLabel(book);
                    const chunkCount = bookChunkCount(book);
                    const canOpenViewer = Boolean(book.viewer_path);
                    const canInspectChunks = chunkCount > 0;
                    const canDelete = Boolean(book.delete_target_id);
                    const rowChips = isCorpusMode
                      ? [
                        book.command_chunk_count ? `commands ${book.command_chunk_count}` : '',
                        book.error_chunk_count ? `errors ${book.error_chunk_count}` : '',
                        ...Object.entries(book.chunk_type_breakdown ?? {})
                          .slice(0, 3)
                          .map(([kind, count]) => `${kind} ${count}`),
                      ].filter(Boolean)
                      : customerPackBookEvidenceBits(book);
                    return (
                      <div className="metric-book-row metric-book-row-shell" key={`${book.book_slug}:${metricPopover.mode}`}>
                        <div className="metric-book-row-main">
                          {isCorpusMode ? (
                            <Database size={16} className="metric-book-icon" />
                          ) : (
                            <FileText size={16} className="metric-book-icon" />
                          )}
                          <div className="metric-book-info">
                            <span className="metric-book-title">{book.title}</span>
                            <div className="metric-book-meta">
                              <span>{customerPackBookTruth(book) || book.source_lane || book.source_type}</span>
                              {isCorpusMode ? (
                                <>
                                  <span>{chunkCount} chunks</span>
                                  <span>{Number(book.token_total ?? 0).toLocaleString()} tokens</span>
                                </>
                              ) : (
                                <span>{book.section_count} sections</span>
                              )}
                              <span className={playbookGradeBadgeClass(book.grade)}>{normalizePlaybookGrade(book.grade)}</span>
                            </div>
                            <div className="metric-book-origin">원천 · {sourceLabel}</div>
                            {rowChips.length > 0 && (
                              <div className="metric-book-chip-row">
                                {rowChips.map((item) => (
                                  <span key={item} className="metric-book-chip">{item}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="metric-book-actions">
                          {canInspectChunks && (
                            <button
                              type="button"
                              className="metric-row-action metric-row-action--primary"
                              onClick={() => { void openChunkViewer(book); }}
                            >
                              <Database size={14} />
                              <span>{isCorpusMode ? 'Chunks' : 'Corpus'}</span>
                            </button>
                          )}
                          {canOpenViewer && (
                            <button
                              type="button"
                              className="metric-row-action"
                              onClick={() => setBookViewer(book)}
                            >
                              <BookOpen size={14} />
                              <span>Viewer</span>
                            </button>
                          )}
                          {sourceHref && (
                            <a
                              className="metric-row-action"
                              href={toRuntimeUrl(sourceHref)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <ExternalLink size={14} />
                              <span>Source</span>
                            </a>
                          )}
                          {canDelete && (
                            <button
                              type="button"
                              className="metric-row-action metric-row-action--danger"
                              disabled={deletingId === book.delete_target_id}
                              onClick={() => { void handleMetricBookDelete(book); }}
                            >
                              <Trash2 size={14} />
                              <span>{deletingId === book.delete_target_id ? 'Deleting' : 'Delete'}</span>
                            </button>
                          )}
                          <span className={`metric-book-status ${book.review_status === 'approved' ? 'approved' : ''}`}>
                            {book.review_status}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {chunkViewer && (
        <div className="preview-overlay" onClick={() => setChunkViewer(null)}>
          <div className="preview-popover preview-popover-chunk" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{chunkViewer.payload?.title || chunkViewer.title}</h3>
                <div className="preview-header-meta">
                  <span>{chunkViewer.payload?.chunk_count ?? 0} chunks</span>
                  {chunkViewer.payload?.token_total ? <span>{chunkViewer.payload.token_total.toLocaleString()} tokens</span> : null}
                  {chunkViewer.payload?.scope_label ? <span>{chunkViewer.payload.scope_label}</span> : null}
                  {chunkViewer.payload?.corpus_runtime_eligible ? <span>Chat Ready</span> : null}
                </div>
              </div>
              <div className="preview-header-actions">
                {chunkViewer.payload?.document_viewer_path ? (
                  <button
                    type="button"
                    className="preview-open-full-btn"
                    onClick={() => openChunkViewerDocument(chunkViewer.payload!)}
                  >
                    <BookOpen size={14} />
                    <span>Open Book</span>
                  </button>
                ) : null}
                {chunkViewer.payload?.source_origin_url ? (
                  <a
                    className="preview-open-full-btn"
                    href={toRuntimeUrl(chunkViewer.payload.source_origin_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={14} />
                    <span>Source</span>
                  </a>
                ) : null}
                <button className="preview-close-btn" onClick={() => setChunkViewer(null)}><X size={18} /></button>
              </div>
            </div>
            <div className="metric-popover-body chunk-viewer-body">
              {chunkViewer.loading ? (
                <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> Loading chunks...</div>
              ) : chunkViewer.error ? (
                <div className="preview-no-sections">{chunkViewer.error}</div>
              ) : chunkViewer.payload ? (
                <div className="chunk-card-list">
                  {chunkViewer.payload.chunks.map((chunk, index) => {
                    const auxiliaryBits = [
                      chunk.anchor ? `anchor ${chunk.anchor}` : '',
                      chunk.cli_commands.length ? `${chunk.cli_commands.length} commands` : '',
                      chunk.error_strings.length ? `${chunk.error_strings.length} errors` : '',
                    ].filter(Boolean);
                    return (
                      <article className="chunk-card" key={chunk.chunk_id || `${chunk.section}-${index}`}>
                        <div className="chunk-card-header">
                          <div className="chunk-card-meta">
                            <span className="chunk-card-type">{chunk.chunk_type}</span>
                            <span>#{chunk.ordinal || index + 1}</span>
                            <span>{chunk.token_count} tokens</span>
                          </div>
                          {chunk.viewer_path ? (
                            <button
                              type="button"
                              className="metric-row-action"
                              onClick={() => openChunkViewerDocument(chunkViewer.payload!, chunk.viewer_path)}
                            >
                              <BookOpen size={14} />
                              <span>Viewer</span>
                            </button>
                          ) : null}
                        </div>
                        <strong className="chunk-card-title">{chunk.section || chunk.chapter || 'Untitled chunk'}</strong>
                        {chunk.section_path.length > 0 ? (
                          <div className="chunk-card-path">{chunk.section_path.join(' › ')}</div>
                        ) : null}
                        {auxiliaryBits.length > 0 ? (
                          <div className="chunk-card-chip-row">
                            {auxiliaryBits.map((item) => (
                              <span key={item} className="metric-book-chip">{item}</span>
                            ))}
                          </div>
                        ) : null}
                        <pre className="chunk-card-text">{chunk.text}</pre>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="preview-no-sections">표시할 chunk가 없습니다.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {buyerPacketPopover && (
        <div className="preview-overlay" onClick={() => setBuyerPacketPopover(null)}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{buyerPacketPopover.title}</h3>
                <div className="preview-header-meta">
                  <span>{buyerPacketPopover.packets.length} packets</span>
                </div>
              </div>
              <button className="preview-close-btn" onClick={() => setBuyerPacketPopover(null)}><X size={18} /></button>
            </div>
            <div className="metric-popover-body">
              {buyerPacketPopover.packets.length === 0 ? (
                <div className="preview-no-sections">등록된 buyer packet이 없습니다.</div>
              ) : (
                <div className="metric-book-list">
                  {buyerPacketPopover.packets.map((packet) => (
                    <button
                      type="button"
                      className="metric-book-row metric-book-row-clickable"
                      key={packet.book_slug}
                      onClick={() => openBuyerPacket(packet)}
                    >
                      <FileText size={16} className="metric-book-icon" />
                      <div className="metric-book-info">
                        <span className="metric-book-title">{packet.title}</span>
                        <span className="metric-book-meta">
                          {packet.boundary_badge || 'Release Packet'} · {packet.runtime_truth_label || ''}
                        </span>
                      </div>
                      <span className={`metric-book-status ${packet.review_status === 'ready' ? 'approved' : ''}`}>
                        {packet.review_status}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {uploadReportViewer && (
        <div className="preview-overlay" onClick={() => setUploadReportViewer(null)}>
          <div className="preview-popover preview-popover-upload-report" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{uploadReportViewer.title}</h3>
                <div className="preview-header-meta">
                  <span>User Upload Report</span>
                  <span>{uploadReportViewer.documentSourceId}</span>
                  {uploadReportViewer.report?.report_reconstructed ? <span>reconstructed</span> : <span>stored report</span>}
                </div>
              </div>
              <div className="preview-header-actions">
                <button className="preview-close-btn" onClick={() => setUploadReportViewer(null)}><X size={18} /></button>
              </div>
            </div>
            <div className="upload-report-body">
              {uploadReportViewer.loading ? (
                <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> 작업 로그를 불러오는 중...</div>
              ) : uploadReportViewer.error ? (
                <div className="preview-no-sections">{uploadReportViewer.error}</div>
              ) : uploadReportViewer.report ? (
                <>
                  <div className="upload-report-summary">
                    <div>
                      <span>파일</span>
                      <strong>{uploadReportViewer.report.filename || uploadReportViewer.title}</strong>
                    </div>
                    <div>
                      <span>검색 상태</span>
                      <strong>
                        {uploadReportViewer.report.basic_index_ready
                          ? '기본 인덱싱 완료'
                          : '검색 인덱싱 확인 필요'}
                      </strong>
                    </div>
                    <div>
                      <span>답변 품질</span>
                      <strong>
                        {uploadReportViewer.report.answer_ready || uploadReportViewer.report.ready_for_chat
                          ? '검증 완료'
                          : '검수 전'}
                      </strong>
                    </div>
                    <div>
                      <span>청크 / 인덱싱</span>
                      <strong>
                        {Number(uploadReportViewer.report.counts?.chunk_count || 0).toLocaleString()}
                        {' / '}
                        {Number(uploadReportViewer.report.counts?.indexed_count || 0).toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span>Owner Scope</span>
                      <strong>{uploadReportViewer.report.scope?.owner_user_id || uploadReportViewer.report.owner_user_id || '-'}</strong>
                    </div>
                  </div>

                  <div className="upload-report-scope">
                    <span>repository_id: {uploadReportViewer.report.scope?.repository_id || uploadReportViewer.report.repository_id || '-'}</span>
                    <span>document_source_id: {uploadReportViewer.report.document_source_id}</span>
                    {uploadReportViewer.report.index?.collection ? <span>collection: {uploadReportViewer.report.index.collection}</span> : null}
                  </div>

                  {(uploadReportViewer.report.warnings ?? []).length > 0 && (
                    <div className="upload-report-warning-list">
                      {(uploadReportViewer.report.warnings ?? []).map((warning, index) => (
                        <span key={`${warning}-${index}`}>{warning}</span>
                      ))}
                    </div>
                  )}

                  {progressFromUploadEvents(uploadReportViewer.report.stages ?? []).length > 0 && (
                    <div className="upload-report-progress-list">
                      {progressFromUploadEvents(uploadReportViewer.report.stages ?? []).map((item) => (
                        <div className={`upload-progress-row upload-progress-row--${uploadStageTone(item.status)}`} key={item.key}>
                          <div className="upload-progress-row-top">
                            <span>{item.label}</span>
                            <strong>{item.current.toLocaleString()} / {item.total.toLocaleString()}</strong>
                          </div>
                          <div className="upload-progress-track" aria-hidden="true">
                            <span style={{ width: `${item.percent}%` }} />
                          </div>
                          <div className="upload-progress-row-bottom">
                            <span>{item.message}</span>
                            <em>{item.percent}%</em>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="upload-report-timeline">
                    {USER_UPLOAD_PIPELINE_STEPS.map((step) => {
                      const stageEvents = (uploadReportViewer.report?.stages ?? [])
                        .filter((item) => item.stage === step.stage);
                      const event = stageEvents
                        .filter((item) => item.stage === step.stage)
                        .slice(-1)[0];
                      const status = event?.status || 'not_recorded';
                      const stageState = uploadStageStateFromEvents(stageEvents, step.stage);
                      const labelStatus = stageState === 'done' ? 'done' : status;
                      return (
                        <div className={`upload-report-stage upload-report-stage--${stageState}`} key={step.stage}>
                          <div className="upload-report-stage-head">
                            <span>{step.badge}</span>
                            <strong>{step.title}</strong>
                            <em>{uploadStageStatusLabel(labelStatus)}</em>
                          </div>
                          <p>{event?.message || '저장된 단계 이벤트가 없습니다.'}</p>
                          <div className="upload-report-stage-meta">
                            {typeof event?.duration_ms === 'number' ? <span>{formatDurationMs(event.duration_ms)}</span> : null}
                            {event?.started_at ? <span>start {new Date(event.started_at).toLocaleTimeString()}</span> : null}
                            {event?.finished_at ? <span>end {new Date(event.finished_at).toLocaleTimeString()}</span> : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="preview-no-sections">표시할 작업 로그가 없습니다.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Book Viewer Popover */}
      {bookViewer && (
        <div className="preview-overlay" onClick={() => setBookViewer(null)}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{bookViewer.title}</h3>
                <div className="preview-header-meta">
                  <span>{customerPackBookTruth(bookViewer) || bookViewer.source_lane}</span>
                  {bookViewer.current_source_label ? <span>{bookViewer.current_source_label}</span> : null}
                  {bookViewer.source_origin_label ? <span>{bookViewer.source_origin_label}</span> : null}
                  <span>
                    {bookViewer.source_type === 'uploaded_document'
                      ? `${bookViewer.chunk_count || bookViewer.section_count} chunks`
                      : `${bookViewer.section_count} sections`}
                  </span>
                  {bookViewer.source_type !== 'uploaded_document' ? (
                    <span className={playbookGradeBadgeClass(bookViewer.grade)}>{normalizePlaybookGrade(bookViewer.grade)}</span>
                  ) : null}
                </div>
                {customerPackBookEvidenceBits(bookViewer).length > 0 && (
                  <div className="preview-chip-row">
                    {customerPackBookEvidenceBits(bookViewer).map((item) => (
                      <span key={item} className="preview-chip">{item}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="preview-header-actions">
                {bookViewer.source_type === 'uploaded_document' ? (
                  <span className="preview-viewer-mode preview-viewer-mode-static" title="업로드 문서는 HTML 문서 뷰어로 표시합니다.">
                    <BookOpen size={14} aria-hidden="true" />
                    <span>업로드 문서</span>
                  </span>
                ) : (
                  <label className="preview-viewer-mode" title="문서 보기 형식">
                    <BookOpen size={14} aria-hidden="true" />
                    <select
                      className="preview-viewer-mode-select"
                      value={bookViewerPageMode}
                      aria-label="문서 보기 형식"
                      onChange={(event) => setBookViewerPageMode(event.target.value as ViewerPageMode)}
                    >
                      <option value="single">단일</option>
                      <option value="multi">멀티</option>
                    </select>
                  </label>
                )}
                {bookViewer.source_type !== 'uploaded_document' && bookSourceOriginHref(bookViewer) ? (
                  <a
                    className="preview-open-full-btn"
                    href={toRuntimeUrl(bookSourceOriginHref(bookViewer))}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={14} />
                    <span>Source</span>
                  </a>
                ) : null}
                {bookViewer.delete_target_id ? (
                  <button
                    type="button"
                    className="preview-delete-btn"
                    disabled={deletingId === bookViewer.delete_target_id}
                    onClick={() => { void handleMetricBookDelete(bookViewer); }}
                  >
                    <Trash2 size={16} />
                  </button>
                ) : null}
                <button className="preview-close-btn" onClick={() => setBookViewer(null)}><X size={18} /></button>
              </div>
            </div>
            <div className="preview-body">
              <div className="preview-viewer-shell">
                {bookViewerLoading ? (
                  <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> Loading viewer...</div>
                ) : bookViewerDocument ? (
                  <ViewerDocumentStage
                    viewerDocument={bookViewerDocument}
                    onNavigateViewerPath={(viewerPath) => {
                      setBookViewer((current) => (current ? { ...current, viewer_path: viewerPath } : current));
                    }}
                    className="preview-viewer-document"
                  />
                ) : (
                  <div className="preview-no-sections">뷰어 경로가 없는 북입니다.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default PlaybookLibraryPage;
