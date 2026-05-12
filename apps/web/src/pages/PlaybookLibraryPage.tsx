import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  Activity,
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
import ThemeToggleButton from '../components/ThemeToggleButton';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import {
  DOCUMENT_INGEST_UPLOAD_ACCEPT,
  type CustomerPackDraft,
  type CorpusChunkViewerResponse,
  type BuyerPacket,
  type DataControlRoomResponse,
  type HiddenLibraryBook,
  type LibraryBucket,
  type LibraryBook,
  type LibraryBookSourceOption,
  type OfficialSourceCandidate,
  type OfficialSourceMaterializeResponse,
  type RepositoryCategory,
  type RepositoryFavorite,
  type RepositorySearchResult,
  type SourceDiscoveryLaneResult,
  type SourceDiscoverySearchResponse,
  type SourceDiscoveryJudgeNextAction,
  type SourceDiscoveryJudgeReport,
  type SourceDiscoveryVerificationRecord,
  type RepositoryUnansweredItem,
  type DocumentRepository,
  type DocumentRepositoryDocument,
  type DocumentReaderDocument,
  type RuntimeHealthResponse,
  type UploadIngestResponse,
  uploadDocumentIngestion,
  loadDataControlRoom,
  loadDataControlRoomChunks,
  listCustomerPackDrafts,
  deleteCustomerPackDraft,
  loadCustomerPackBook,
  loadRepositoryFavorites,
  loadRepositoryUnanswered,
  loadDocumentRepositories,
  loadDocumentReader,
  loadRuntimeHealth,
  loadOfficialSourceCatalog,
  loadSourceDiscoveryVerificationQueue,
  loadSourceDiscoveryJudgeReports,
  materializeOfficialSourceCandidate,
  removeRepositoryFavorite,
  runSourceDiscoveryJudgeReplay,
  searchSourceDiscovery,
  saveSourceDiscoveryVerificationCandidate,
  loadCustomerPackCapturedPreview,
  loadViewerDocument,
  toRuntimeUrl,
  formatBytes,
} from '../lib/runtimeApi';
import { useGlobalTheme } from '../lib/globalTheme';
import { ROUTES } from '../routing/routes';

type PipelineStage = 'idle' | 'uploading' | 'capturing' | 'normalizing' | 'done' | 'error';
type FactoryLane = 'tools' | 'user';
type ActiveWikiScope = 'official' | 'customer' | 'uploads';
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
  emptyMessage?: string;
  noticeMessage?: string;
}

interface ChunkViewerState {
  title: string;
  payload: CorpusChunkViewerResponse | null;
  loading: boolean;
  error: string;
}

interface DocumentReaderState {
  repository: DocumentRepository;
  source: DocumentRepositoryDocument;
  payload: DocumentReaderDocument | null;
  loading: boolean;
  loadingMore: boolean;
  error: string;
}

type LibraryScopeFilter = 'all' | 'official_docs' | 'study_docs' | 'user_upload';
type LibraryQualityFilter = 'all' | 'approved_ko' | 'needs_review' | 'original' | 'source_gold';
type LibraryIndexFilter = 'all' | 'ready' | 'needs_index' | 'zero_chunks';

function activeWikiScopeFromRoute(pathname: string, searchParams: URLSearchParams): ActiveWikiScope {
  const requestedScope = (searchParams.get('scope') || '').trim().toLowerCase();
  const requestedLane = (searchParams.get('lane') || '').trim().toLowerCase();
  if (requestedScope === 'uploads' || requestedScope === 'user' || requestedLane === 'uploads') {
    return 'uploads';
  }
  if (requestedScope === 'customer' || requestedScope === 'study' || pathname.endsWith('/repository')) {
    return 'customer';
  }
  return 'official';
}

function libraryFilterForWikiScope(scope: ActiveWikiScope): LibraryScopeFilter {
  switch (scope) {
    case 'customer':
      return 'study_docs';
    case 'uploads':
      return 'user_upload';
    default:
      return 'official_docs';
  }
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

function isRepositoryDocumentOperationallyReady(document: DocumentRepositoryDocument): boolean {
  const parseStatus = String(document.parse_status || '').trim().toLowerCase();
  const parseReady = ['succeeded', 'completed', 'complete', 'done', 'parsed', 'normalized'].includes(parseStatus);
  const chunkCount = Number(document.chunk_count || 0);
  return parseReady && Number.isFinite(chunkCount) && chunkCount > 0;
}

function isDocumentReadable(document: DocumentRepositoryDocument): boolean {
  return isRepositoryDocumentOperationallyReady(document) && Boolean(String(document.parsed_document_id || '').trim());
}

function documentReadBlockReasons(document: DocumentRepositoryDocument): string[] {
  if (isDocumentReadable(document)) {
    return [];
  }
  const reasons: string[] = [];
  const parseStatus = String(document.parse_status || '').trim();
  const chunkCount = Number(document.chunk_count || 0);
  if (!String(document.parsed_document_id || '').trim()) {
    reasons.push('parsed_document_id 없음');
  }
  if (!Number.isFinite(chunkCount) || chunkCount <= 0) {
    reasons.push('chunk 없음');
  }
  if (!isRepositoryDocumentOperationallyReady(document)) {
    reasons.push(parseStatus ? `parse_status=${parseStatus}` : 'parse_status 확인 필요');
  }
  return reasons.length > 0 ? reasons : ['문서 검수 필요'];
}

function documentReadBlockReason(document: DocumentRepositoryDocument): string {
  return documentReadBlockReasons(document).join(' · ');
}

function isOperationalWikiRuntimeBook(book: LibraryBook): boolean {
  return book.runtime_readable === true && Boolean(String(book.viewer_path || '').trim());
}

function operationalWikiHiddenCount(bucket: LibraryBucket | undefined): number {
  const raw = bucket?.hidden_count;
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return raw;
  }
  return bucket?.hidden_books?.length ?? 0;
}

function runtimeGateReasonLabel(reason: string): string {
  switch (reason) {
    case 'runtime_not_readable::zero_sections':
      return '섹션 0개';
    case 'runtime_not_readable::zero_chunks':
      return '청크 0개';
    case 'runtime_not_readable::missing_viewer_path':
      return '뷰어 경로 없음';
    case 'runtime_not_readable::missing_runtime_artifact':
      return '런타임 산출물 없음';
    case 'runtime_not_readable::viewer_slug_mismatch':
      return '뷰어 slug 불일치';
    case 'runtime_not_readable::unknown_viewer_route':
      return '알 수 없는 뷰어 경로';
    case 'runtime_not_readable::viewer_404':
      return '뷰어 404';
    case 'runtime_not_readable::viewer_empty_body':
      return '뷰어 본문 없음';
    case 'runtime_not_readable::viewer_no_sections':
      return '뷰어 섹션 없음';
    case 'runtime_not_readable::viewer_exception':
      return '뷰어 검증 오류';
    case 'runtime_not_readable::non_ko_content':
    case 'non_ko_content':
      return '한글화 미완료';
    case 'mixed_ko_content':
      return '한글화 검토';
    default:
      return reason || 'runtime gate';
  }
}

function languageGateReasonLabel(reason: string): string {
  switch (reason) {
    case 'non_ko_content':
      return '한글화 미완료';
    case 'mixed_ko_content':
      return '한글화 검토';
    default:
      return reason || 'language gate';
  }
}

function formatPercentRatio(value: unknown): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return '';
  }
  return `${Math.round(numeric * 1000) / 10}%`;
}

function languageGateBadgeLabel(book: LibraryBook): string {
  const status = String(book.language_gate_status || '').trim().toLowerCase();
  if (!status || status === 'pass' || status === 'unknown') {
    return '';
  }
  const reasonLabel = languageGateReasonLabel(String(book.language_gate_reason || status));
  const hangulRatio = formatPercentRatio(book.hangul_chunk_ratio);
  return hangulRatio ? `${reasonLabel} · 한글 ${hangulRatio}` : reasonLabel;
}

function languageGateChips(book: LibraryBook): string[] {
  const status = String(book.language_gate_status || '').trim().toLowerCase();
  if (!status || status === 'pass' || status === 'unknown') {
    return [];
  }
  return [
    languageGateReasonLabel(String(book.language_gate_reason || status)),
    formatPercentRatio(book.hangul_chunk_ratio) ? `한글 ${formatPercentRatio(book.hangul_chunk_ratio)}` : '',
  ].filter(Boolean);
}

function viewerSmokeReasonLabel(reason: string): string {
  switch (reason) {
    case 'missing_viewer_path':
      return '뷰어 경로 없음';
    case 'viewer_404':
      return '뷰어 404';
    case 'viewer_empty_body':
      return '본문 없음';
    case 'viewer_no_sections':
      return '섹션 없음';
    case 'viewer_exception':
      return '검증 오류';
    case 'viewer_title_not_matched':
      return '제목 경고';
    default:
      return reason || 'viewer smoke';
  }
}

function hasViewerSmokeEvidence(book: LibraryBook): boolean {
  return Boolean(String(book.viewer_smoke_status || '').trim());
}

function viewerSmokeTone(book: LibraryBook): 'pass' | 'fail' | 'warning' | 'skipped' {
  const status = String(book.viewer_smoke_status || '').trim().toLowerCase();
  if (status === 'fail') return 'fail';
  if (status === 'skipped') return 'skipped';
  if (status === 'pass') return book.viewer_smoke_warning ? 'warning' : 'pass';
  return 'skipped';
}

function viewerSmokeBadgeLabel(book: LibraryBook): string {
  const status = String(book.viewer_smoke_status || '').trim().toLowerCase();
  const headingCount = Number(book.viewer_smoke_heading_count ?? 0);
  if (status === 'fail') {
    return `Viewer Fail · ${viewerSmokeReasonLabel(String(book.viewer_smoke_reason || ''))}`;
  }
  if (status === 'skipped') {
    return `Viewer Skip · ${viewerSmokeReasonLabel(String(book.viewer_smoke_reason || ''))}`;
  }
  if (status !== 'pass') {
    return 'Viewer Smoke 없음';
  }
  const suffix = headingCount > 0 ? ` · h${headingCount}` : '';
  const warning = book.viewer_smoke_warning ? ` · ${viewerSmokeReasonLabel(book.viewer_smoke_warning)}` : '';
  return `Viewer OK${suffix}${warning}`;
}

function viewerSmokeChips(book: LibraryBook): string[] {
  const status = String(book.viewer_smoke_status || '').trim().toLowerCase();
  const headingCount = Number(book.viewer_smoke_heading_count ?? 0);
  if (!status) {
    return [];
  }
  if (status === 'fail') {
    return ['Viewer Fail', viewerSmokeReasonLabel(String(book.viewer_smoke_reason || ''))];
  }
  if (status === 'skipped') {
    return ['Viewer Skip', viewerSmokeReasonLabel(String(book.viewer_smoke_reason || ''))];
  }
  if (status !== 'pass') {
    return ['Viewer Smoke', viewerSmokeReasonLabel(status)];
  }
  return [
    'Viewer OK',
    headingCount > 0 ? `${headingCount} headings` : '',
    book.viewer_smoke_warning ? viewerSmokeReasonLabel(book.viewer_smoke_warning) : '',
  ].filter(Boolean);
}

function operationalWikiHiddenMessage(hiddenRows: HiddenLibraryBook[] = [], hiddenCount = hiddenRows.length): string {
  if (hiddenCount <= 0) {
    return '등록된 북이 없습니다.';
  }
  const reasonCounts = hiddenRows.reduce<Record<string, number>>((acc, book) => {
    const reason = String(book.hidden_reason || book.runtime_readiness || book.runtime_gate || 'runtime gate').trim();
    acc[reason] = (acc[reason] || 0) + 1;
    return acc;
  }, {});
  const summary = Object.entries(reasonCounts)
    .slice(0, 2)
    .map(([reason, count]) => `${runtimeGateReasonLabel(reason)} ${count}`)
    .join(' · ');
  const detail = summary || '상세 사유는 recovery_books payload를 확인해야 합니다.';
  return `Gold Recovery Queue ${hiddenCount}권 · ${detail}`;
}

function goldRecoveryRows(bucket: LibraryBucket | undefined): HiddenLibraryBook[] {
  return [...(bucket?.recovery_books ?? bucket?.hidden_books ?? [])];
}

function goldRecoveryAction(book: HiddenLibraryBook): string {
  return String(book.gold_recovery_action || '').trim() || 'Gold 계약 blocker 해소 후 재검증 필요';
}

function goldRecoveryBlockerText(book: HiddenLibraryBook): string {
  const blockers = book.gold_contract_blockers ?? [];
  if (blockers.length > 0) {
    return blockers.map(runtimeGateReasonLabel).join(' · ');
  }
  return runtimeGateReasonLabel(String(book.hidden_reason || book.runtime_readiness || 'runtime gate'));
}

function certificationBlockerLabel(blocker: string): string {
  switch (blocker) {
    case 'missing_morning_gate_report':
      return 'Morning gate report 없음';
    case 'missing_source_approval_report':
    case 'canonical_grade_source_unavailable':
      return 'Source approval report 없음';
    case 'missing_retrieval_eval_report':
      return 'Retrieval eval 없음';
    case 'missing_answer_eval_report':
      return 'Answer eval 없음';
    case 'missing_ragas_eval_report':
      return 'RAGAS eval 없음';
    case 'missing_runtime_report':
      return 'Runtime report 없음';
    case 'gold_recovery_items_present':
      return 'Gold Recovery 남아 있음';
    default:
      return blocker || '검증 blocker';
  }
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
    document.parse_status,
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

function repositoryDocumentScope(row: RepositoryDocumentRow): {
  sourceKind: string;
  scope: string;
  visibility: string;
  repositoryKind: string;
} {
  const metadata = row.document.metadata ?? {};
  const repositoryMetadata = row.repository.metadata ?? {};
  return {
    sourceKind: String(row.document.source_kind || '').toLowerCase(),
    scope: String(row.document.source_scope || metadata.source_scope || repositoryMetadata.source_scope || '').toLowerCase(),
    visibility: String(row.document.visibility || row.repository.visibility || '').toLowerCase(),
    repositoryKind: String(row.repository.repository_kind || '').toLowerCase(),
  };
}

function isOfficialRepositoryDocument(row: RepositoryDocumentRow): boolean {
  const { sourceKind, scope, repositoryKind } = repositoryDocumentScope(row);
  return scope.includes('official') || sourceKind.includes('official') || repositoryKind === 'official';
}

function isMyUploadRepositoryDocument(row: RepositoryDocumentRow): boolean {
  const { scope, visibility, repositoryKind } = repositoryDocumentScope(row);
  return scope === 'user_upload' || visibility === 'private_user' || repositoryKind === 'personal';
}

function isCustomerRepositoryDocument(row: RepositoryDocumentRow): boolean {
  if (isOfficialRepositoryDocument(row) || isMyUploadRepositoryDocument(row)) {
    return false;
  }
  const { sourceKind, scope, visibility, repositoryKind } = repositoryDocumentScope(row);
  return (
    scope.includes('study')
    || scope.includes('customer')
    || sourceKind.includes('kmsc')
    || sourceKind.includes('course')
    || repositoryKind === 'study'
    || repositoryKind === 'customer'
    || repositoryKind === 'enterprise'
    || visibility === 'workspace_shared'
  );
}

function documentBookSlug(row: RepositoryDocumentRow): string {
  const metadata = row.document.metadata ?? {};
  const repositoryMetadata = row.repository.metadata ?? {};
  return (
    metadataString(metadata, 'book_slug')
    || metadataString(repositoryMetadata, 'book_slug')
    || row.repository.slug
  ).trim();
}

function documentQualityChips(row: RepositoryDocumentRow, runtimeBook?: LibraryBook): string[] {
  const { document } = row;
  const metadata = document.metadata ?? {};
  const parseStatus = String(document.parse_status || '').trim();
  const readBlockReason = documentReadBlockReason(document);
  const certifiedGold = runtimeBook?.certified_gold === true && runtimeBook?.gold_contract_status === 'gold_certified';
  const recoveryGold = runtimeBook?.gold_contract_status === 'gold_recovery' || runtimeBook?.certified_gold === false;
  const chips = [
    document.source_scope,
    parseStatus ? `parse_${parseStatus}` : '',
    readBlockReason ? 'read_blocked' : 'readable',
    document.source_kind?.includes('gold') ? 'source_gold' : '',
    certifiedGold ? 'certified_gold' : '',
    recoveryGold ? 'gold_recovery' : '',
    recoveryGold && runtimeBook?.gold_recovery_group ? runtimeBook.gold_recovery_group : '',
    metadataString(metadata, 'approval_state'),
    metadataString(metadata, 'review_status'),
    metadataString(metadata, 'translation_status'),
    metadataString(metadata, 'source_lane'),
    metadataString(metadata, 'document_format'),
  ].map((item) => String(item || '').trim()).filter(Boolean);
  return Array.from(new Set(chips)).slice(0, 8);
}

function documentIndexStatus(row: RepositoryDocumentRow): LibraryIndexFilter {
  const chunkCount = Number(row.document.chunk_count || 0);
  const indexedCount = Number(row.document.indexed_chunk_count || 0);
  if (!Number.isFinite(chunkCount) || chunkCount <= 0) {
    return 'zero_chunks';
  }
  if (!Number.isFinite(indexedCount) || indexedCount < chunkCount) {
    return 'needs_index';
  }
  return 'ready';
}

function matchesLibraryFilters(
  row: RepositoryDocumentRow,
  filters: {
    query: string;
    scope: LibraryScopeFilter;
    quality: LibraryQualityFilter;
    index: LibraryIndexFilter;
  },
): boolean {
  const query = filters.query.trim().toLowerCase();
  if (query && !documentSearchText(row.document, row.repository).includes(query)) {
    return false;
  }
  if (filters.scope !== 'all') {
    const scopeMatches = filters.scope === 'official_docs'
      ? isOfficialRepositoryDocument(row)
      : filters.scope === 'study_docs'
        ? isCustomerRepositoryDocument(row)
        : isMyUploadRepositoryDocument(row);
    if (!scopeMatches) {
      return false;
    }
  }
  if (filters.index !== 'all' && documentIndexStatus(row) !== filters.index) {
    return false;
  }
  if (filters.quality !== 'all') {
    const chips = documentQualityChips(row).map((item) => item.toLowerCase());
    if (!chips.includes(filters.quality)) {
      return false;
    }
  }
  return true;
}

function indexStatusLabel(status: LibraryIndexFilter): string {
  switch (status) {
    case 'ready':
      return 'indexed';
    case 'needs_index':
      return 'index check';
    case 'zero_chunks':
      return 'no chunks';
    default:
      return 'all';
  }
}

const FACTORY_PIPELINE_STEPS: Record<FactoryLane, Array<{ badge: string; title: string; description: string }>> = {
  tools: [
    { badge: 'Bronze', title: '원천 바인딩', description: '선택한 공식 원천을 생산선에 연결' },
    { badge: 'Silver', title: '구조화 초안 생성', description: '섹션 · 구조 · 번역 초안 생성' },
    { badge: 'Gold', title: '플레이북 · 코퍼스 생성', description: '위키 책 · 검색 코퍼스 동시 생성' },
    { badge: 'Judge', title: '라이브러리 합류 검증', description: '완성본 검증 후 Playbook Library 반영' },
  ],
  user: [
    { badge: 'Bronze', title: 'Source Intake', description: '파일 업로드 · 원본 캡처' },
    { badge: 'Silver', title: 'Structured Wiki', description: '정규화 · 섹션 · 위키 책' },
    { badge: 'Gold', title: 'Playbook Materialize', description: '코퍼스 · 플레이북 생성' },
    { badge: 'Judge', title: 'User Library Join', description: 'User Library 저장' },
  ],
};

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

function sourceDiscoveryValue(item: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      return String(value);
    }
  }
  return '';
}

function sourceDiscoveryItemTitle(item: Record<string, unknown>): string {
  return sourceDiscoveryValue(item, ['title', 'full_name', 'book_slug', 'name', 'html_url']) || 'Source candidate';
}

function sourceDiscoveryItemHref(item: Record<string, unknown>): string {
  const directHref = sourceDiscoveryValue(item, ['html_url']);
  if (directHref) {
    return directHref;
  }
  const viewerPath = sourceDiscoveryValue(item, ['viewer_path']);
  if (viewerPath) {
    return toRuntimeUrl(viewerPath);
  }
  const sourceOptions = item.source_options;
  if (Array.isArray(sourceOptions)) {
    const firstOption = sourceOptions.find((option): option is LibraryBookSourceOption => {
      if (!option || typeof option !== 'object') {
        return false;
      }
      const record = option as Partial<LibraryBookSourceOption>;
      return Boolean(String(record.href || '').trim());
    });
    if (firstOption) {
      return firstOption.href;
    }
  }
  return '';
}

function sourceDiscoveryItemMeta(item: Record<string, unknown>): string {
  const parts = [
    sourceDiscoveryValue(item, ['repository_full_name', 'owner_login']),
    sourceDiscoveryValue(item, ['kind', 'status_label', 'suggested_category', 'source_relative_path']),
    sourceDiscoveryValue(item, ['updated_at']),
  ].filter(Boolean);
  return parts.slice(0, 3).join(' · ');
}

function sourceDiscoveryLaneKoreanName(lane: SourceDiscoveryLaneResult['lane'] | string, fallback = ''): string {
  switch (lane) {
    case 'official_manual':
      return '공식 매뉴얼';
    case 'official_source_repo':
      return '공식 소스 레포';
    case 'official_issue_pr':
      return '공식 Issue/PR';
    case 'community_troubleshooting':
      return '커뮤니티 트러블슈팅';
    case 'vendor_kb':
      return '벤더 KB';
    case 'unsafe_unverified':
      return '검증 불가';
    default:
      return fallback || lane;
  }
}

function sourceDiscoveryLaneKoreanLabel(lane: SourceDiscoveryLaneResult): string {
  return sourceDiscoveryLaneKoreanName(lane.lane, lane.label);
}

function sourceDiscoveryLaneStatusLabel(lane: SourceDiscoveryLaneResult): string {
  if (lane.status === 'ok') {
    return `${lane.count}개`;
  }
  if (lane.status === 'not_configured') {
    return 'provider 미연결';
  }
  if (lane.status === 'blocked') {
    return '자동 차단';
  }
  if (lane.status === 'error') {
    return '오류';
  }
  return lane.status || 'unknown';
}

function sourceDiscoveryPlannerMeta(payload: SourceDiscoverySearchResponse | null): {
  rewrittenQuery: string;
  authMode: 'token' | 'public';
  plannerMode: string;
  llmPlannerEnabled: boolean;
  riskLevel: string;
  goldPolicy: string;
  requiresHumanReview: boolean;
  reason: string;
} {
  return {
    rewrittenQuery: payload?.plan?.question ?? '',
    authMode: payload?.auth_mode ?? 'public',
    plannerMode: payload?.planner_mode ?? '',
    llmPlannerEnabled: Boolean(payload?.llm_planner_enabled),
    riskLevel: String(payload?.plan?.risk_level ?? ''),
    goldPolicy: String(payload?.plan?.gold_policy ?? ''),
    requiresHumanReview: Boolean(payload?.plan?.requires_human_review),
    reason: String(payload?.plan?.reason ?? ''),
  };
}

function sourceDiscoveryLaneNeedsVerification(lane: SourceDiscoveryLaneResult): boolean {
  if (['official_manual', 'official_source_repo'].includes(String(lane.lane))) {
    return false;
  }
  return Boolean(lane.requires_human_review) || [
    'official_issue_pr',
    'community_troubleshooting',
    'vendor_kb',
    'unsafe_unverified',
  ].includes(String(lane.lane));
}

function sourceDiscoveryCandidateKey(lane: SourceDiscoveryLaneResult, item?: Record<string, unknown>): string {
  const title = item ? sourceDiscoveryItemTitle(item) : `${sourceDiscoveryLaneKoreanLabel(lane)} 후보 조사 필요`;
  const href = item ? sourceDiscoveryItemHref(item) : '';
  return [lane.lane, lane.provider, lane.query, href, title].join('|');
}

function sourceDiscoveryQueueCandidate(lane: SourceDiscoveryLaneResult, item?: Record<string, unknown>): Record<string, unknown> {
  if (item) {
    return item;
  }
  return {
    title: `${sourceDiscoveryLaneKoreanLabel(lane)} 후보 조사 필요`,
    kind: lane.status,
    message: lane.message || lane.error,
  };
}

function sourceDiscoveryRecordKey(record: SourceDiscoveryVerificationRecord): string {
  return [
    record.lane,
    record.provider,
    record.query,
    record.source_url,
    record.title,
  ].join('|');
}

function sourceJudgeVerdictLabel(verdict?: string): string {
  switch (verdict) {
    case 'pass':
      return 'PASS';
    case 'needs_review':
      return 'REVIEW';
    case 'needs_replay':
      return 'REPLAY';
    case 'fail':
      return 'FAIL';
    default:
      return String(verdict || 'PENDING').toUpperCase();
  }
}

function sourceJudgeVerdictClass(verdict?: string): string {
  switch (verdict) {
    case 'pass':
      return 'pass';
    case 'needs_review':
      return 'needs-review';
    case 'needs_replay':
      return 'needs-replay';
    case 'fail':
      return 'fail';
    default:
      return 'pending';
  }
}

function sourceJudgeActionClass(severity?: string): string {
  switch (severity) {
    case 'critical':
      return 'critical';
    case 'warning':
      return 'warning';
    default:
      return 'info';
  }
}

function sourceJudgeActionButtonLabel(action: SourceDiscoveryJudgeNextAction): string {
  switch (action.action_id) {
    case 'record_answerable_case':
      return '';
    case 'rerun_rag_replay':
      return '다시 실행';
    case 'verify_bronze_queue':
      return '큐 확인';
    case 'replace_non_eligible_citations':
    case 'remove_unsafe_citation':
      return '대체 공식 근거 찾기';
    default:
      return '원천소스 찾기';
  }
}

function sourceJudgeCitationTitle(item: Record<string, unknown>): string {
  return sourceDiscoveryItemTitle(item);
}

function sourceJudgeCitationHref(item: Record<string, unknown>): string {
  return sourceDiscoveryValue(item, ['source_url', 'href', 'html_url']) || sourceDiscoveryItemHref(item);
}

function sourceJudgeCitationLane(item: Record<string, unknown>): string {
  return sourceDiscoveryValue(item, ['lane', 'source_lane', 'source_collection', 'boundary_truth']) || 'source';
}

function sourceDiscoveryJudgeCandidates(lanes: SourceDiscoveryLaneResult[]): Record<string, unknown>[] {
  return lanes.flatMap((lane) => {
    if (lane.items.length === 0 && !sourceDiscoveryLaneNeedsVerification(lane)) {
      return [];
    }
    const laneItems = lane.items.length > 0
      ? lane.items.slice(0, 5)
      : [sourceDiscoveryQueueCandidate(lane)];
    return laneItems.map((item) => ({
      ...item,
      title: sourceDiscoveryItemTitle(item),
      source_url: sourceDiscoveryItemHref(item),
      lane: lane.lane,
      provider: lane.provider,
      query: lane.query,
      trust_level: lane.trust_level,
      gold_policy: lane.gold_policy,
      requires_human_review: lane.requires_human_review,
      citation_eligible: !sourceDiscoveryLaneNeedsVerification(lane),
    }));
  });
}

function officialCandidateToJudgeSource(candidate: OfficialSourceCandidate): Record<string, unknown> {
  const firstSourceOption = sourceOptionsForRecord(candidate).find((option) => option.availability === 'available' && option.href);
  return {
    title: candidate.title,
    book_slug: candidate.book_slug,
    viewer_path: candidate.viewer_path,
    source_url: firstSourceOption?.href ?? '',
    source_label: candidate.current_source_label ?? firstSourceOption?.label ?? 'official source',
    source_relative_path: candidate.source_relative_path,
    source_repo: candidate.source_repo,
    lane: 'official_manual',
    provider: 'official_catalog',
    trust_level: 'authoritative',
    gold_policy: 'eligible',
    citation_eligible: true,
    can_promote_to_gold: true,
  };
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
  const [controlRoom, setControlRoom] = useState<DataControlRoomResponse | null>(null);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [previewDraft, setPreviewDraft] = useState<CustomerPackDraft | null>(null);
  const [metricPopover, setMetricPopover] = useState<MetricPopoverState | null>(null);
  const [buyerPacketPopover, setBuyerPacketPopover] = useState<{ title: string; packets: BuyerPacket[] } | null>(null);
  const [chunkViewer, setChunkViewer] = useState<ChunkViewerState | null>(null);
  const [documentReader, setDocumentReader] = useState<DocumentReaderState | null>(null);
  const [bookViewer, setBookViewer] = useState<LibraryBook | null>(null);
  const [bookViewerDocument, setBookViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [bookViewerLoading, setBookViewerLoading] = useState(false);
  const [bookViewerError, setBookViewerError] = useState('');
  const [previewCapturedUrl, setPreviewCapturedUrl] = useState('');
  const [previewCapturedType, setPreviewCapturedType] = useState('');
  const [previewViewerDocument, setPreviewViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [repositoryResults, setRepositoryResults] = useState<RepositorySearchResult[]>([]);
  const [officialSourceCandidates, setOfficialSourceCandidates] = useState<OfficialSourceCandidate[]>([]);
  const [sourceDiscoveryLaneResults, setSourceDiscoveryLaneResults] = useState<SourceDiscoveryLaneResult[]>([]);
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
  const [sourceVerificationQueue, setSourceVerificationQueue] = useState<SourceDiscoveryVerificationRecord[]>([]);
  const [sourceJudgeReports, setSourceJudgeReports] = useState<SourceDiscoveryJudgeReport[]>([]);
  const [sourceJudgeRunning, setSourceJudgeRunning] = useState(false);
  const [sourceJudgeError, setSourceJudgeError] = useState('');
  const [savingVerificationKey, setSavingVerificationKey] = useState<string | null>(null);
  const [documentRepositories, setDocumentRepositories] = useState<DocumentRepository[]>([]);
  const [documentRepositoryError, setDocumentRepositoryError] = useState('');
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealthResponse | null>(null);
  const [runtimeHealthError, setRuntimeHealthError] = useState('');
  const [librarySearchQuery, setLibrarySearchQuery] = useState('');
  const [libraryScopeFilter, setLibraryScopeFilter] = useState<LibraryScopeFilter>('official_docs');
  const [libraryQualityFilter, setLibraryQualityFilter] = useState<LibraryQualityFilter>('all');
  const [libraryIndexFilter, setLibraryIndexFilter] = useState<LibraryIndexFilter>('all');
  const [repositoryStage, setRepositoryStage] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [repositoryError, setRepositoryError] = useState('');
  const [repositoryMeta, setRepositoryMeta] = useState<{
    rewrittenQuery: string;
    authMode: 'token' | 'public';
    plannerMode: string;
    llmPlannerEnabled: boolean;
    riskLevel: string;
    goldPolicy: string;
    requiresHumanReview: boolean;
    reason: string;
  }>({
    rewrittenQuery: '',
    authMode: 'public',
    plannerMode: '',
    llmPlannerEnabled: false,
    riskLevel: '',
    goldPolicy: '',
    requiresHumanReview: false,
    reason: '',
  });
  const [removingFavoriteName, setRemovingFavoriteName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pipelineRef = useRef<HTMLDivElement>(null);
  const repositorySearchInputRef = useRef<HTMLInputElement>(null);
  const sourceVerificationQueueRef = useRef<HTMLElement>(null);
  const repositoryAutoloadKeyRef = useRef('');
  const toolsRunHeartbeatRef = useRef<number | null>(null);
  const documentReaderRequestRef = useRef(0);
  const activeWikiScope = useMemo(
    () => activeWikiScopeFromRoute(location.pathname, searchParams),
    [location.pathname, searchParams],
  );

  const addLog = (tag: LogEntry['tag'], msg: string) => {
    setLogs((prev) => [{ time: nowTime(), tag, msg }, ...prev].slice(0, 10));
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

  const refreshSourceVerificationQueue = useCallback(() => {
    loadSourceDiscoveryVerificationQueue(50)
      .then((payload) => setSourceVerificationQueue(payload.items ?? []))
      .catch(() => setSourceVerificationQueue([]));
  }, []);

  const refreshSourceJudgeReports = useCallback(() => {
    loadSourceDiscoveryJudgeReports(10)
      .then((payload) => setSourceJudgeReports(payload.items ?? []))
      .catch(() => setSourceJudgeReports([]));
  }, []);

  const refreshDocumentRepositories = useCallback(() => {
    loadDocumentRepositories()
      .then((payload) => {
        setDocumentRepositories(payload.repositories ?? []);
        setDocumentRepositoryError('');
      })
      .catch((error: unknown) => {
        setDocumentRepositories([]);
        setDocumentRepositoryError(error instanceof Error ? error.message : 'document repositories load failed');
      });
  }, []);

  const refreshRuntimeHealth = useCallback(() => {
    loadRuntimeHealth()
      .then((payload) => {
        setRuntimeHealth(payload);
        setRuntimeHealthError('');
      })
      .catch((error: unknown) => {
        setRuntimeHealth(null);
        setRuntimeHealthError(error instanceof Error ? error.message : 'runtime health load failed');
      });
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
    refreshSourceVerificationQueue();
    refreshSourceJudgeReports();
    refreshOfficialCatalog();
    refreshDocumentRepositories();
    refreshRuntimeHealth();
  }, [refreshDocumentRepositories, refreshOfficialCatalog, refreshRepositoryFavorites, refreshRepositoryUnanswered, refreshRuntimeHealth, refreshSourceJudgeReports, refreshSourceVerificationQueue]);

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
    if (!isDocumentReadable(document)) {
      return;
    }
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

  const openDocumentReader = useCallback(async (
    repository: DocumentRepository,
    document: DocumentRepositoryDocument,
  ) => {
    const requestId = documentReaderRequestRef.current + 1;
    documentReaderRequestRef.current = requestId;
    const readBlockReason = documentReadBlockReason(document);
    if (readBlockReason) {
      setDocumentReader({
        repository,
        source: document,
        payload: null,
        loading: false,
        loadingMore: false,
        error: `이 문서는 아직 reader로 열 수 없습니다: ${readBlockReason}`,
      });
      addLog('warn', `${document.title || document.filename} 문서 reader 차단: ${readBlockReason}`);
      return;
    }
    setDocumentReader({
      repository,
      source: document,
      payload: null,
      loading: true,
      loadingMore: false,
      error: '',
    });
    try {
      const response = await loadDocumentReader({
        documentSourceId: document.document_source_id,
        parsedDocumentId: document.parsed_document_id,
        limit: 80,
        offset: 0,
      });
      if (documentReaderRequestRef.current !== requestId) {
        return;
      }
      setDocumentReader({
        repository,
        source: document,
        payload: response.document,
        loading: false,
        loadingMore: false,
        error: response.document ? '' : '문서 본문을 찾지 못했습니다.',
      });
    } catch (error: unknown) {
      if (documentReaderRequestRef.current !== requestId) {
        return;
      }
      setDocumentReader({
        repository,
        source: document,
        payload: null,
        loading: false,
        loadingMore: false,
        error: errorMessage(error, '문서 본문을 불러오지 못했습니다.'),
      });
    }
  }, []);

  const loadMoreDocumentReader = useCallback(async () => {
    const current = documentReader;
    if (!current?.payload || current.loadingMore || !current.payload.has_more) {
      return;
    }
    const requestId = documentReaderRequestRef.current;
    const nextOffset = current.payload.offset + current.payload.chunks.length;
    setDocumentReader({ ...current, loadingMore: true, error: '' });
    try {
      const response = await loadDocumentReader({
        documentSourceId: current.source.document_source_id,
        parsedDocumentId: current.source.parsed_document_id,
        limit: current.payload.limit || 80,
        offset: nextOffset,
      });
      if (documentReaderRequestRef.current !== requestId) {
        return;
      }
      if (!response.document) {
        setDocumentReader((prev) => (
          prev?.source.document_source_id === current.source.document_source_id
            ? { ...prev, loadingMore: false, error: '추가 chunk를 찾지 못했습니다.' }
            : prev
        ));
        return;
      }
      setDocumentReader((prev) => {
        if (!prev?.payload || prev.source.document_source_id !== current.source.document_source_id) {
          return prev;
        }
        return {
          ...prev,
          payload: {
            ...response.document!,
            chunks: [...prev.payload.chunks, ...response.document!.chunks],
            offset: prev.payload.offset,
          },
          loadingMore: false,
          error: '',
        };
      });
    } catch (error: unknown) {
      if (documentReaderRequestRef.current !== requestId) {
        return;
      }
      setDocumentReader((prev) => (
        prev?.source.document_source_id === current.source.document_source_id
          ? { ...prev, loadingMore: false, error: errorMessage(error, '추가 chunk를 불러오지 못했습니다.') }
          : prev
      ));
    }
  }, [documentReader]);

  const closeDocumentReader = useCallback(() => {
    documentReaderRequestRef.current += 1;
    setDocumentReader(null);
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
      setBookViewerError('문서 뷰어 경로가 아직 생성되지 않았습니다.');
      return;
    }

    let cancelled = false;
    setBookViewerLoading(true);
    setBookViewerDocument(null);
    setBookViewerError('');

    loadViewerDocument(bookViewer.viewer_path)
      .then((viewerDocument) => {
        if (cancelled) {
          return;
        }
        setBookViewerError('');
        setBookViewerDocument({
          html: viewerDocument.html,
          inlineStyles: viewerDocument.inline_styles,
          bodyClassName: viewerDocument.body_class_name,
        });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBookViewerDocument(null);
          const message = error instanceof Error ? error.message : '';
          setBookViewerError(message ? `문서 본문을 열 수 없습니다: ${message}` : '문서 본문을 열 수 없습니다.');
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
  }, [bookViewer]);

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
    const requestedLane = activeWikiScope === 'uploads' ? 'uploads' : 'customer';
    setLibraryScopeFilter(libraryFilterForWikiScope(activeWikiScope));
    setFactoryLane(activeWikiScope === 'uploads' ? 'user' : 'tools');
    if (!requestedQuery) {
      repositoryAutoloadKeyRef.current = '';
      return;
    }
    const autoloadKey = `${requestedView}|${activeWikiScope}|${requestedLane}|${requestedQuery}`;
    if (repositoryAutoloadKeyRef.current === autoloadKey) {
      return;
    }
    repositoryAutoloadKeyRef.current = autoloadKey;
    setSearchQuery(requestedQuery);
    setFactoryAssistantQuery(requestedQuery);
    setSourceRequestsExpanded(true);
    setRepositoryStage('loading');
    setRepositoryError('');
    searchSourceDiscovery(requestedQuery, 8)
      .then((payload) => {
        setRepositoryResults(payload.github_repository_results ?? []);
        const officialCandidates = payload.official_candidates ?? [];
        setOfficialSourceCandidates(officialCandidates);
        setSourceDiscoveryLaneResults(payload.lane_results ?? []);
        setRepositoryMeta(sourceDiscoveryPlannerMeta(payload));
        refreshRepositoryUnanswered();
        if (officialCandidates.length > 0) {
          setGeneratedCatalogPrompt(requestedQuery);
          setOfficialCatalogExpanded(true);
        } else {
          setGeneratedCatalogPrompt('');
          setOfficialCatalogExpanded(false);
        }
        setRepositoryStage('done');
        addLog('info', `Source discovery '${requestedQuery}' → ${payload.totals.lane_count} lanes`);
      })
      .catch((error: unknown) => {
        const msg = errorMessage(error, 'Repository search failed');
        setRepositoryStage('error');
        setRepositoryError(msg);
        setRepositoryResults([]);
        setOfficialSourceCandidates([]);
        setSourceDiscoveryLaneResults([]);
        addLog('error', `Repository search failed: ${msg}`);
      });
  }, [activeWikiScope, refreshRepositoryUnanswered, searchParams]);

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

    const stageIndex = { idle: -1, uploading: 0, capturing: 1, normalizing: 2, done: 3, error: -1 }[pipelineStage];

    steps.forEach((step, i) => {
      step.classList.toggle('completed', i < stageIndex);
      step.classList.toggle('active', i === stageIndex);
      step.classList.toggle('final', pipelineStage === 'done' && i === 3);
    });

    connectors.forEach((conn, i) => {
      conn.classList.toggle('filled', i < stageIndex);
      conn.classList.toggle('flowing', i === stageIndex - 1 || (pipelineStage === 'done' && i === 2));
    });

    if (stageIndex >= 0 && steps[stageIndex]) {
      gsap.fromTo(
        steps[stageIndex].querySelector('.step-icon'),
        { scale: 0.8, opacity: 0.5 },
        { scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(1.7)' },
      );
    }
  }, [factoryLane, pipelineStage]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';

    setErrorMsg('');
    setCurrentFile(file.name);
    setLatestUploadIngest(null);

    try {
      setPipelineStage('uploading');
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'recognizing',
        message: '문서 인식중입니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      }));
      addLog('info', `Uploading '${file.name}' to document ingestion...`);

      setPipelineStage('capturing');
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'parsing',
        message: '문서 파싱중입니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      }));
      addLog('info', 'Parsing source into Markdown blocks and semantic chunks...');
      setPipelineStage('normalizing');
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'indexing',
        message: '인덱싱중입니다.',
        filename: file.name,
        updatedAt: new Date().toISOString(),
      }));
      addLog('info', 'Persisting chunks to PostgreSQL and indexing them for RAG...');
      const ingest = await uploadDocumentIngestion(file, { index: true });
      const indexedCount = ingest.index?.indexed_count ?? 0;
      const indexLine = ingest.index ? `, ${indexedCount}/${ingest.index.candidate_count} indexed` : '';
      setLatestUploadIngest(ingest);

      addLog('success', `Ingested '${ingest.filename}': ${ingest.block_count} blocks, ${ingest.chunk_count} chunks${indexLine}.`);
      if (ingest.warnings.length > 0) {
        addLog('warn', ingest.warnings.slice(0, 2).join(' / '));
      }

      setPipelineStage('done');
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        status: 'ready',
        message: '문서 준비가 완료되었습니다.',
        filename: ingest.filename || file.name,
        repositoryId: ingest.repository_id || ingest.persisted?.repository_id || '',
        documentSourceId: ingest.persisted?.document_source_id || '',
        updatedAt: new Date().toISOString(),
      }));
      addLog('success', `'${ingest.filename}' is now available to the RAG corpus.`);
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
      setSourceDiscoveryLaneResults([]);
      setRepositoryMeta(sourceDiscoveryPlannerMeta(null));
      return null;
    }
    setRepositoryStage('loading');
    setRepositoryError('');
    setSourceRequestsExpanded(true);
    try {
      const payload = await searchSourceDiscovery(normalizedQuery, 8);
      setRepositoryResults(payload.github_repository_results ?? []);
      setOfficialSourceCandidates(payload.official_candidates ?? []);
      setSourceDiscoveryLaneResults(payload.lane_results ?? []);
      setRepositoryMeta(sourceDiscoveryPlannerMeta(payload));
      refreshRepositoryUnanswered();
      setRepositoryStage('done');
      addLog('info', `Source discovery '${normalizedQuery}' → ${payload.totals.lane_count} lanes`);
      return payload;
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Repository search failed');
      setRepositoryStage('error');
      setRepositoryError(msg);
      setRepositoryResults([]);
      setOfficialSourceCandidates([]);
      setSourceDiscoveryLaneResults([]);
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

  const handleSaveSourceVerificationCandidate = async (
    lane: SourceDiscoveryLaneResult,
    item?: Record<string, unknown>,
  ) => {
    if (!sourceDiscoveryLaneNeedsVerification(lane)) {
      return;
    }
    const key = sourceDiscoveryCandidateKey(lane, item);
    setSavingVerificationKey(key);
    try {
      const payload = await saveSourceDiscoveryVerificationCandidate({
        lane: lane.lane,
        provider: lane.provider,
        query: lane.query,
        sourceRequestQuery: factoryAssistantQuery.trim() || searchQuery.trim(),
        candidate: sourceDiscoveryQueueCandidate(lane, item),
      });
      setSourceVerificationQueue(payload.items ?? []);
      addLog(
        payload.saved ? 'success' : 'info',
        payload.saved
          ? `Bronze 검증 큐에 저장: ${payload.item.title}`
          : `이미 Bronze 검증 큐에 있음: ${payload.item.title}`,
      );
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Verification queue save failed');
      setFactoryAssistantError(msg);
      addLog('error', `Verification queue save failed: ${msg}`);
    } finally {
      setSavingVerificationKey(null);
    }
  };

  const handleRunSourceJudge = async (questionOverride?: string) => {
    const question = (String(questionOverride || '').trim() || factoryAssistantQuery.trim() || searchQuery.trim()).trim();
    if (!question) {
      setSourceJudgeError('Judge를 실행하려면 실패 질문이나 검색 질문이 필요합니다.');
      return;
    }
    setFactoryAssistantQuery(question);
    setSearchQuery(question);
    setSourceJudgeRunning(true);
    setSourceJudgeError('');
    try {
      const sourceCandidates = [
        ...sourceDiscoveryJudgeCandidates(sourceDiscoveryLaneResults),
        ...officialSourceCandidates.slice(0, 12).map(officialCandidateToJudgeSource),
      ];
      const replay = await runSourceDiscoveryJudgeReplay({
        question,
        beforeAnswer: '챗봇이 근거 부족 또는 답변 실패 상태로 Source Discovery가 요청됨',
        sourceCandidates,
        verificationRecords: sourceVerificationQueue,
        includeVerificationQueue: true,
      });
      const report = replay.judge_report;
      setSourceJudgeReports((prev) => [
        report,
        ...prev.filter((item) => item.judge_id !== report.judge_id),
      ].slice(0, 10));
      addLog(
        report.overall_verdict === 'pass' ? 'success' : report.overall_verdict === 'fail' ? 'error' : 'warn',
        `[Judge] RAG 재답변 검증 ${sourceJudgeVerdictLabel(report.overall_verdict)} · citations ${replay.replay.citations.length} · ${replay.replay.response_kind ?? 'unknown'} · gap ${report.remaining_gap.length}`,
      );
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Judge 실행에 실패했습니다.');
      setSourceJudgeError(msg);
      addLog('error', `Judge failed: ${msg}`);
    } finally {
      setSourceJudgeRunning(false);
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
    addLog('info', `Source Factory assistant lookup: ${nextQuery}`);
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

  const handleJudgeNextAction = async (action: SourceDiscoveryJudgeNextAction) => {
    const query = String(action.query || latestSourceJudgeReport?.question || factoryAssistantQuery || searchQuery).trim();
    switch (action.action_id) {
      case 'record_answerable_case':
        addLog('success', 'Judge 통과 케이스입니다. 같은 질문 유형을 Gold/운영 위키 개선 후보로 보면 됩니다.');
        return;
      case 'rerun_rag_replay':
        await handleRunSourceJudge(query);
        return;
      case 'verify_bronze_queue':
        sourceVerificationQueueRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        addLog('info', `${action.lane ? sourceDiscoveryLaneKoreanName(action.lane, action.lane) : 'Bronze'} 후보를 공식 근거와 대조하세요.`);
        return;
      default:
        if (!query) {
          setFactoryAssistantError('다음 행동을 실행할 질문이 없습니다.');
          return;
        }
        await handleFactoryAssistantSubmit(query);
    }
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
    const params = new URLSearchParams({ scope: 'customer', panel: 'factory', lane: 'customer' });
    if (nextQuery.trim()) {
      params.set('q', nextQuery.trim());
    }
    navigate(`/playbook-library?${params.toString()}`);
    requestAnimationFrame(() => repositorySearchInputRef.current?.focus());
    if (nextQuery.trim()) {
      await runRepositorySearch(nextQuery);
    }
  };

  const openUserDocsUpload = (openPicker = false) => {
    setFactoryLane('user');
    navigate('/playbook-library?scope=uploads&lane=uploads');
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
    let emptyMessage: string | undefined;
    let noticeMessage: string | undefined;
    const gatedRuntimeBooks = [...(cr.approved_wiki_runtime_books?.books ?? [])].filter(isOperationalWikiRuntimeBook);
    const hiddenRuntimeBooks = goldRecoveryRows(cr.approved_wiki_runtime_books);
    const hiddenRuntimeCount = operationalWikiHiddenCount(cr.approved_wiki_runtime_books);
    const runtimeGateNotice = hiddenRuntimeCount > 0
      ? operationalWikiHiddenMessage(hiddenRuntimeBooks, hiddenRuntimeCount)
      : undefined;
    switch (kind) {
      case 'approved':
        title = 'Gold PlayBooks';
        books = gatedRuntimeBooks.filter((book) => normalizePlaybookGrade(book.grade) === 'Gold');
        emptyMessage = runtimeGateNotice ?? operationalWikiHiddenMessage();
        noticeMessage = runtimeGateNotice;
        break;
      case 'latestNonGold':
        title = 'Silver · Bronze PlayBooks';
        books = gatedRuntimeBooks.filter((book) => normalizePlaybookGrade(book.grade) !== 'Gold');
        emptyMessage = runtimeGateNotice ?? operationalWikiHiddenMessage();
        noticeMessage = runtimeGateNotice;
        break;
      case 'customerPack':
        title = 'User PlayBooks';
        books = [...((cr.customer_pack_runtime_books ?? cr.user_library_books)?.books ?? [])];
        break;
      case 'wikiRuntime':
        title = 'Latest Pipeline PlayBooks';
        books = gatedRuntimeBooks;
        emptyMessage = runtimeGateNotice ?? operationalWikiHiddenMessage();
        noticeMessage = runtimeGateNotice;
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
    setMetricPopover({ title, mode, rows: books, emptyMessage, noticeMessage });
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
    switch (stage) {
      case 'uploading': return 'Uploading...';
      case 'capturing': return 'Parsing Document...';
      case 'normalizing': return 'Indexing Chunks...';
      case 'done': return 'Pipeline Complete';
      case 'error': return 'Pipeline Failed';
      default: return 'Engine Idle';
    }
  };

  const isProcessing = ['uploading', 'capturing', 'normalizing'].includes(pipelineStage);

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
  const officialDocumentRows = useMemo(
    () => repositoryDocumentRows.filter(isOfficialRepositoryDocument),
    [repositoryDocumentRows],
  );
  const customerDocumentRows = useMemo(
    () => repositoryDocumentRows.filter(isCustomerRepositoryDocument),
    [repositoryDocumentRows],
  );
  const userUploadDocumentRows = useMemo(
    () => repositoryDocumentRows.filter(isMyUploadRepositoryDocument),
    [repositoryDocumentRows],
  );
  const activeLibraryFilters = useMemo(
    () => ({
      query: librarySearchQuery,
      scope: libraryScopeFilter,
      quality: libraryQualityFilter,
      index: libraryIndexFilter,
    }),
    [libraryIndexFilter, libraryQualityFilter, libraryScopeFilter, librarySearchQuery],
  );
  const activeWikiDocumentRows = useMemo(
    () => officialDocumentRows.filter((row) => matchesLibraryFilters(row, activeLibraryFilters)),
    [activeLibraryFilters, officialDocumentRows],
  );
  const filteredCustomerDocumentRows = useMemo(
    () => customerDocumentRows.filter((row) => matchesLibraryFilters(row, activeLibraryFilters)),
    [activeLibraryFilters, customerDocumentRows],
  );
  const filteredUserUploadDocumentRows = useMemo(
    () => userUploadDocumentRows.filter((row) => matchesLibraryFilters(row, activeLibraryFilters)),
    [activeLibraryFilters, userUploadDocumentRows],
  );
  const runtimeDbCorpus = runtimeHealth?.runtime?.db_corpus;
  const runtimeQdrant = runtimeHealth?.runtime?.qdrant_live;
  const totalRepositoryChunks = repositoryDocumentRows.reduce((total, row) => total + Number(row.document.chunk_count || 0), 0);
  const totalIndexedRepositoryChunks = repositoryDocumentRows.reduce((total, row) => total + Number(row.document.indexed_chunk_count || 0), 0);
  const officialDbChunks = runtimeDbCorpus?.chunk_counts?.official_docs
    ?? summary?.official_corpus_chunk_count
    ?? officialDocumentRows.reduce((total, row) => total + Number(row.document.chunk_count || 0), 0);
  const customerDbChunks = runtimeDbCorpus?.chunk_counts?.study_docs
    ?? summary?.customer_corpus_chunk_count
    ?? customerDocumentRows.reduce((total, row) => total + Number(row.document.chunk_count || 0), 0);
  const dbCorpusChunks = runtimeDbCorpus?.total_chunks ?? summary?.total_repository_chunk_count ?? totalRepositoryChunks;
  const qdrantPoints = runtimeQdrant?.points_count ?? null;
  const qdrantIndexedVectors = runtimeQdrant?.indexed_vectors_count ?? null;
  const qdrantEntryCount = runtimeDbCorpus?.qdrant_index_entries ?? summary?.qdrant_index_entry_count ?? totalIndexedRepositoryChunks;
  const allOperationalWikiBooks = [...(controlRoom?.approved_wiki_runtime_books?.books ?? [])].filter(isOperationalWikiRuntimeBook);
  const operationalWikiRecoveryRows = goldRecoveryRows(controlRoom?.approved_wiki_runtime_books);
  const operationalWikiBookBySlug = useMemo(() => {
    const items = [...allOperationalWikiBooks, ...operationalWikiRecoveryRows];
    return new Map(items.map((book) => [book.book_slug, book]));
  }, [allOperationalWikiBooks, operationalWikiRecoveryRows]);
  const operationalWikiRecoveryBooks = operationalWikiHiddenCount(controlRoom?.approved_wiki_runtime_books);
  const operationalWikiGateNotice = operationalWikiRecoveryBooks > 0
    ? operationalWikiHiddenMessage(operationalWikiRecoveryRows, operationalWikiRecoveryBooks)
    : '';
  const certification = controlRoom?.certification;
  const certificationBlockers = certification?.blockers ?? [];
  const certificationStatus = certification?.status ?? controlRoom?.summary?.certification_status ?? '';
  const isNotCertifiable = Boolean(certificationStatus && certificationStatus !== 'certified');
  const runtimeAlerts = [
    !runtimeHealth && !runtimeHealthError ? 'Runtime health 확인 중입니다.' : '',
    documentRepositoryError ? `Document repository 확인 실패: ${documentRepositoryError}` : '',
    runtimeHealthError ? `Runtime health 확인 실패: ${runtimeHealthError}` : '',
    isNotCertifiable
      ? `검증 불가 · ${certificationBlockers.slice(0, 4).map(certificationBlockerLabel).join(' · ') || 'certification blockers 확인 필요'}`
      : '',
    operationalWikiGateNotice,
    runtimeHealth && !runtimeQdrant ? 'Qdrant live 상태가 health payload에 없습니다.' : '',
    runtimeQdrant && runtimeQdrant.ready === false
      ? `Qdrant live check 실패: ${runtimeQdrant.status || 'unknown'}${runtimeQdrant.error ? ` (${runtimeQdrant.error})` : ''}`
      : '',
    runtimeQdrant && typeof qdrantPoints !== 'number'
      ? 'Qdrant points_count 확인 불가'
      : '',
    typeof dbCorpusChunks === 'number' && typeof qdrantPoints === 'number' && dbCorpusChunks !== qdrantPoints
      ? `Postgres chunks ${dbCorpusChunks.toLocaleString()} / Qdrant points ${qdrantPoints.toLocaleString()} 불일치`
      : '',
    typeof qdrantPoints === 'number' && typeof qdrantIndexedVectors === 'number' && qdrantPoints !== qdrantIndexedVectors
      ? `Qdrant indexed vectors ${qdrantIndexedVectors.toLocaleString()} / points ${qdrantPoints.toLocaleString()} 확인 필요`
      : '',
    runtimeDbCorpus?.qdrant_index_parity === false
      ? 'Postgres qdrant_index_entries parity 확인 필요'
      : '',
    summary?.missing_qdrant_index_entry_count
      ? `Qdrant index entry 누락 ${Number(summary.missing_qdrant_index_entry_count).toLocaleString()}건`
      : '',
  ].filter(Boolean);
  const goldOperationalWikiBooks = allOperationalWikiBooks.filter((book) => normalizePlaybookGrade(book.grade) === 'Gold' && book.certified_gold !== false);
  const latestNonGoldOperationalWikiBooks = allOperationalWikiBooks.filter((book) => normalizePlaybookGrade(book.grade) !== 'Gold');
  const userLibraryBooks = [...(userLibraryBucket?.books ?? [])];
  const userLibraryBookCount = summary?.customer_pack_runtime_book_count
    ?? summary?.user_library_book_count
    ?? userLibraryBooks.length;
  const userRuntimePlaybookCount = summary?.customer_pack_runtime_book_count ?? userLibraryBooks.length;
  const officialCorpusBookCount = summary?.corpus_book_count ?? officialCorpusBooks.length;
  const officialPlaybookFileCount = summary?.manualbook_count ?? officialPlaybookBooks.length;
  const userCorpusBookCount = summary?.user_library_corpus_book_count ?? userCorpusBooks.length;
  const approvedWikiRuntimeBooks = allOperationalWikiBooks.length;
  const goldPlaybookCount = goldOperationalWikiBooks.length;
  const latestNonGoldPlaybookCount = latestNonGoldOperationalWikiBooks.length;
  const operationalWikiBooks = allOperationalWikiBooks.slice(0, 8);
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
  const sourceVerificationSavedKeys = useMemo(
    () => new Set(sourceVerificationQueue.map((record) => sourceDiscoveryRecordKey(record))),
    [sourceVerificationQueue],
  );
  const latestSourceJudgeReport = sourceJudgeReports[0] ?? null;
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
      ? 'Source Factory Running...'
      : repositoryStage === 'loading'
        ? 'Finding Source Candidates...'
        : repositoryUnanswered.length > 0
          ? `${repositoryUnanswered.length} source requests queued`
          : 'Source Finder Ready';
  const bookFactoryStatusClass = factoryLane === 'user'
    ? pipelineStage === 'error'
      ? 'error'
      : pipelineStage === 'done'
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
  const repositoryPaneRows = activeWikiScope === 'official'
    ? activeWikiDocumentRows
    : activeWikiScope === 'uploads'
      ? filteredUserUploadDocumentRows
      : filteredCustomerDocumentRows;
  const repositoryPaneTotal = activeWikiScope === 'official'
    ? officialDocumentRows.length
    : activeWikiScope === 'uploads'
      ? userUploadDocumentRows.length
      : customerDocumentRows.length;
  const repositoryPaneTitle = activeWikiScope === 'official'
    ? 'OCP Official'
    : activeWikiScope === 'uploads'
      ? 'My Uploads'
      : 'Customer Docs';
  const repositoryPaneDescription = activeWikiScope === 'official'
    ? '공식 OpenShift 문서가 실제 RAG와 운영 위키에서 믿고 쓰이는 상태인지 검수합니다.'
    : activeWikiScope === 'uploads'
      ? '내가 업로드한 문서와 생산된 User Library 책을 확인합니다.'
      : '고객사/현장 원천 문서와 질문 보강용 source request를 확인합니다.';
  const repositoryPaneEmptyMessage = activeWikiScope === 'official'
    ? '조회 가능한 공식 문서가 없습니다.'
    : activeWikiScope === 'uploads'
      ? '아직 조회 가능한 내 업로드 문서가 없습니다.'
      : '아직 조회 가능한 고객/현장 문서가 없습니다.';
  const handleLibraryScopeFilterChange = (value: LibraryScopeFilter) => {
    setLibraryScopeFilter(value);
    if (value === 'official_docs') {
      navigate('/playbook-library?scope=official');
      return;
    }
    if (value === 'study_docs') {
      navigate('/playbook-library?scope=customer&lane=customer');
      return;
    }
    if (value === 'user_upload') {
      openUserDocsUpload(false);
    }
  };
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

  return (
    <div className="library-wrapper">
      <div className="bokeh-bg bokeh-1"></div>
      <div className="bokeh-bg bokeh-2"></div>

      <header className="library-header">
        <div className="header-container">
          <div className="header-content">
            <button className="back-btn" onClick={() => navigate('/')}>
              <ArrowLeft size={20} />
            </button>
            <div className="header-text">
              <h1>WIKI Library</h1>
              <p className="text-muted">
                WIKI 데이터, 검수 상태, 원천 보강 루프를 한 화면에서 관리합니다.
              </p>
            </div>
          </div>

          <div className="header-actions">
            <button className="library-dashboard-link" type="button" onClick={() => navigate('/')}>
              Playbook Studio
            </button>
            <ThemeToggleButton
              className="library-theme-toggle-btn"
              globalTheme={globalTheme}
              onToggleGlobalTheme={toggleGlobalTheme}
            />
          </div>
        </div>
      </header>

      <main className="library-main">
        <div className="library-shell">
          <aside className="library-sidebar" aria-label="Playbook Library categories">
            <section>
              <h2>WIKI</h2>
              <button
                type="button"
                className={`library-sidebar-item ${activeWikiScope === 'official' ? 'active' : ''}`}
                onClick={() => {
                  setLibraryScopeFilter('official_docs');
                  navigate('/playbook-library?scope=official');
                }}
              >
                <Activity size={15} />
                <span>OCP Official</span>
                <strong>{officialDocumentRows.length.toLocaleString()}</strong>
              </button>
              <button
                type="button"
                className={`library-sidebar-item ${activeWikiScope === 'customer' ? 'active' : ''}`}
                onClick={() => {
                  setLibraryScopeFilter('study_docs');
                  navigate('/playbook-library?scope=customer&lane=customer');
                }}
              >
                <Database size={15} />
                <span>Customer Docs</span>
                <strong>{customerDocumentRows.length.toLocaleString()}</strong>
              </button>
              <button
                type="button"
                className={`library-sidebar-item ${activeWikiScope === 'uploads' ? 'active' : ''}`}
                onClick={() => {
                  setLibraryScopeFilter('user_upload');
                  openUserDocsUpload(false);
                }}
              >
                <UploadCloud size={15} />
                <span>My Uploads</span>
                <strong>{userUploadDocumentRows.length.toLocaleString()}</strong>
              </button>
            </section>
          </aside>
          <div className="library-content-panel">
            <section className="library-runtime-board">
              <div className="library-runtime-board-head">
                <div>
                  <span className="factory-hub-eyebrow">System Data Board</span>
                  <h2>현재 시스템이 쓰는 데이터</h2>
                  <p>Book Library는 Postgres 문서, chunk, Qdrant 검색 인덱스가 서로 맞는지 확인하는 검수 화면입니다.</p>
                </div>
                <button type="button" className="library-runtime-refresh" onClick={() => { refreshDocumentRepositories(); refreshRuntimeHealth(); }}>
                  Refresh
                </button>
              </div>
              <div className="library-runtime-grid">
                <div className="library-runtime-card">
                  <span>Official Docs</span>
                  <strong>{officialDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>Customer Docs</span>
                  <strong>{customerDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>My Uploads</span>
                  <strong>{userUploadDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>Total Docs</span>
                  <strong>{repositoryDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>Chunks</span>
                  <strong>{Number(dbCorpusChunks || 0).toLocaleString()}</strong>
                  <em>
                    official {Number(officialDbChunks || 0).toLocaleString()} · customer {Number(customerDbChunks || 0).toLocaleString()}
                  </em>
                  <em>{qdrantEntryCount.toLocaleString()} qdrant entries</em>
                </div>
                <div className={`library-runtime-card ${runtimeAlerts.length > 0 ? 'warning' : 'ok'}`}>
                  <span>Qdrant Points</span>
                  <strong>{typeof qdrantPoints === 'number' ? qdrantPoints.toLocaleString() : '-'}</strong>
                  <em>{typeof qdrantIndexedVectors === 'number' ? `${qdrantIndexedVectors.toLocaleString()} indexed` : runtimeQdrant?.status ?? 'unknown'}</em>
                </div>
                <div className={`library-runtime-card ${isNotCertifiable ? 'danger' : 'ok'}`}>
                  <span>Certification</span>
                  <strong>{isNotCertifiable ? 'Not Certifiable' : 'Certified'}</strong>
                  <em>
                    {isNotCertifiable
                      ? `${certificationBlockers.length.toLocaleString()} blockers`
                      : `${goldPlaybookCount.toLocaleString()} Gold passed`}
                  </em>
                </div>
              </div>
              {runtimeAlerts.length > 0 ? (
                <div className="library-runtime-alerts">
                  <AlertCircle size={16} />
                  <span>{runtimeAlerts.join(' · ')}</span>
                </div>
              ) : (
                <div className="library-runtime-ok">
                  <CheckCircle2 size={16} />
                  <span>Postgres 문서/chunk와 Qdrant 기준 수량이 현재 런타임에서 일치합니다.</span>
                </div>
              )}
            </section>

            <section className="library-data-toolbar" aria-label="Book Library filters">
              <label className="library-filter-search">
                <Search size={16} />
                <input
                  type="search"
                  value={librarySearchQuery}
                  onChange={(event) => setLibrarySearchQuery(event.target.value)}
                  placeholder="문서 제목, source, 상태 검색"
                />
              </label>
              <select value={libraryScopeFilter} onChange={(event) => handleLibraryScopeFilterChange(event.target.value as LibraryScopeFilter)}>
                <option value="official_docs">OCP Official</option>
                <option value="study_docs">Customer Docs</option>
                <option value="user_upload">My Uploads</option>
              </select>
              <select value={libraryQualityFilter} onChange={(event) => setLibraryQualityFilter(event.target.value as LibraryQualityFilter)}>
                <option value="all">All quality</option>
                <option value="approved_ko">approved_ko</option>
                <option value="needs_review">needs_review</option>
                <option value="original">original</option>
                <option value="source_gold">source_gold</option>
              </select>
              <select value={libraryIndexFilter} onChange={(event) => setLibraryIndexFilter(event.target.value as LibraryIndexFilter)}>
                <option value="all">All index states</option>
                <option value="ready">Indexed</option>
                <option value="needs_index">Index check</option>
                <option value="zero_chunks">No chunks</option>
              </select>
            </section>
        {activeWikiScope === 'official' && (
          <div className="monitoring-view">
            <section className="operational-shelf box-container">
              <div className="operational-shelf-header">
                <div>
                  <span className="operational-shelf-eyebrow">Official Documents</span>
                  <h2>OCP Official documents</h2>
                  <p>PostgreSQL document_sources 기준으로 분류된 공식 OpenShift 문서입니다. 문서별 채팅은 해당 document_source_id로 RAG 범위를 고정합니다.</p>
                </div>
                <span className="operational-library-count">
                  {activeWikiDocumentRows.length.toLocaleString()} / {officialDocumentRows.length.toLocaleString()} docs
                </span>
              </div>
              {activeWikiDocumentRows.length === 0 ? (
                <div className="repo-empty">
                  <Database size={36} />
                  <p>이 카테고리에 매핑된 공식 문서가 아직 없습니다.</p>
                </div>
              ) : (
                <div className="operational-library-grid">
                  {activeWikiDocumentRows.map(({ repository, document, categoryKey }) => (
                    <article
                      key={document.document_source_id}
                      className="operational-library-card operational-library-card--document"
                    >
                      <div className="operational-card-open">
                        <span className="operational-library-card-badge">{document.source_scope || repository.visibility}</span>
                        <strong>{document.title || document.filename}</strong>
                        <span className="operational-card-open-subtitle">
                          {document.chunk_count.toLocaleString()} chunks / {document.indexed_chunk_count.toLocaleString()} indexed
                        </span>
                        <div className="library-document-chip-row">
                          {documentQualityChips(
                            { repository, document, categoryKey },
                            operationalWikiBookBySlug.get(documentBookSlug({ repository, document, categoryKey })),
                          ).map((chip) => (
                            <span key={chip} className="library-document-chip">{chip}</span>
                          ))}
                          <span className={`library-document-chip library-document-chip--${documentIndexStatus({ repository, document, categoryKey })}`}>
                            {indexStatusLabel(documentIndexStatus({ repository, document, categoryKey }))}
                          </span>
                        </div>
                        {!isDocumentReadable(document) && (
                          <span className="library-document-read-block">
                            <AlertCircle size={13} />
                            {documentReadBlockReason(document)}
                          </span>
                        )}
                      </div>
                      <div className="library-document-actions">
                        <button
                          type="button"
                          className={`library-document-chat-btn ${isDocumentReadable(document) ? '' : 'library-document-chat-btn--blocked'}`}
                          title={documentReadBlockReason(document) || 'Read document'}
                          disabled={!isDocumentReadable(document)}
                          onClick={() => {
                            if (isDocumentReadable(document)) {
                              void openDocumentReader(repository, document);
                            }
                          }}
                        >
                          <BookOpen size={14} />
                          <span>{isDocumentReadable(document) ? 'Read' : 'Needs repair'}</span>
                        </button>
                        <button
                          type="button"
                          className={`library-document-chat-btn ${isDocumentReadable(document) ? '' : 'library-document-chat-btn--blocked'}`}
                          title={documentReadBlockReason(document) || 'Ask this document'}
                          disabled={!isDocumentReadable(document)}
                          onClick={() => {
                            if (isDocumentReadable(document)) {
                              openDocumentInChat(repository, document, categoryKey);
                            }
                          }}
                        >
                          <MessageSquare size={14} />
                          <span>{isDocumentReadable(document) ? 'Ask this document' : 'Repair before ask'}</span>
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>

            {operationalWikiBooks.length > 0 && (
              <section className="operational-shelf box-container">
                <div className="operational-shelf-header">
                  <div>
                    <span className="operational-shelf-eyebrow">Operational Wiki</span>
                    <h2>바로 읽을 수 있는 운영 위키</h2>
                    <p>지금 제품 표면에서 바로 여는 핵심 운영 문서 묶음입니다.</p>
                  </div>
                  <div className="operational-shelf-actions">
                    {operationalWikiGateNotice && (
                      <button
                        type="button"
                        className="operational-gate-notice"
                        onClick={() => openMetricPopover('wikiRuntime')}
                      >
                        <ShieldAlert size={14} />
                        <span>{operationalWikiGateNotice}</span>
                      </button>
                    )}
                    <button
                      type="button"
                      className="operational-shelf-link"
                      onClick={() => openMetricPopover('wikiRuntime')}
                    >
                      전체 {approvedWikiRuntimeBooks.toLocaleString()}권 보기
                    </button>
                  </div>
                </div>
                {(
                  <div className="operational-shelf-grid">
                    {operationalWikiBooks.map((book) => (
                      <article
                        key={book.book_slug}
                        className="operational-book-card"
                      >
                        <button
                          type="button"
                          className="operational-card-open"
                          onClick={() => setBookViewer(book)}
                        >
                          <span className="operational-book-badge">{normalizePlaybookGrade(book.grade)}</span>
                          <strong>{book.title}</strong>
                          <span className="operational-card-open-subtitle">{book.book_slug.replace(/_/g, ' ')}</span>
                          {languageGateBadgeLabel(book) ? (
                            <span className="operational-viewer-smoke operational-viewer-smoke--warning">
                              {languageGateBadgeLabel(book)}
                            </span>
                          ) : null}
                          {hasViewerSmokeEvidence(book) ? (
                            <span className={`operational-viewer-smoke operational-viewer-smoke--${viewerSmokeTone(book)}`}>
                              {viewerSmokeBadgeLabel(book)}
                            </span>
                          ) : null}
                        </button>
                        <OfficialSourcePopover record={book} />
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}

            {operationalWikiRecoveryRows.length > 0 && (
              <section className="gold-recovery-panel box-container">
                <div className="operational-shelf-header">
                  <div>
                    <span className="operational-shelf-eyebrow">Gold Recovery Queue</span>
                    <h2>Gold에서 탈락한 복구 대상 {operationalWikiRecoveryRows.length.toLocaleString()}권</h2>
                    <p>이 문서들은 Gold 라벨을 달 수 없습니다. blocker를 해소하고 다시 검증해야 운영 위키에 합류합니다.</p>
                  </div>
                  <span className="gold-recovery-status">Not Gold</span>
                </div>
                <div className="gold-recovery-grid">
                  {operationalWikiRecoveryRows.map((book) => (
                    <article key={`recovery-${book.book_slug}`} className="gold-recovery-card">
                      <div className="gold-recovery-card-head">
                        <span>{book.source_grade || 'Gold'} → Gold Recovery</span>
                        <strong>{book.title}</strong>
                      </div>
                      <div className="gold-recovery-card-meta">
                        <span>{book.book_slug.replace(/_/g, ' ')}</span>
                        <span>{Number(book.section_count || 0).toLocaleString()} sections</span>
                        <span>{Number(book.chunk_count || 0).toLocaleString()} chunks</span>
                      </div>
                      <div className="gold-recovery-blocker">
                        <AlertCircle size={14} />
                        <span>{goldRecoveryBlockerText(book)}</span>
                      </div>
                      {formatPercentRatio(book.hangul_chunk_ratio) && (
                        <div className="gold-recovery-language">
                          한글 비율 {formatPercentRatio(book.hangul_chunk_ratio)}
                        </div>
                      )}
                      <p>{goldRecoveryAction(book)}</p>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {allOperationalWikiBooks.length > 0 && (
              <section className="operational-library box-container">
                <div className="operational-library-header">
                  <div>
                    <span className="operational-library-eyebrow">Operational Library</span>
                    <h2>운영 위키 {approvedWikiRuntimeBooks.toLocaleString()}권</h2>
                  </div>
                  <div className="operational-library-header-meta">
                    {operationalWikiRecoveryBooks > 0 && (
                      <span className="operational-library-gate-count">
                        Recovery {operationalWikiRecoveryBooks.toLocaleString()}권
                      </span>
                    )}
                    <span className="operational-library-count">{approvedWikiRuntimeBooks.toLocaleString()} books</span>
                  </div>
                </div>
                <div className="operational-library-grid">
                  {allOperationalWikiBooks.map((book) => (
                    <article
                      key={`library-${book.book_slug}`}
                      className="operational-library-card"
                    >
                      <button
                        type="button"
                        className="operational-card-open"
                        onClick={() => setBookViewer(book)}
                      >
                        <span className="operational-library-card-badge">{normalizePlaybookGrade(book.grade)}</span>
                        <strong>{book.title}</strong>
                        <span className="operational-card-open-subtitle">{book.book_slug.replace(/_/g, ' ')}</span>
                        {languageGateBadgeLabel(book) ? (
                          <span className="operational-viewer-smoke operational-viewer-smoke--warning">
                            {languageGateBadgeLabel(book)}
                          </span>
                        ) : null}
                        {hasViewerSmokeEvidence(book) ? (
                          <span className={`operational-viewer-smoke operational-viewer-smoke--${viewerSmokeTone(book)}`}>
                            {viewerSmokeBadgeLabel(book)}
                          </span>
                        ) : null}
                      </button>
                      <OfficialSourcePopover record={book} />
                    </article>
                  ))}
                </div>
              </section>
            )}

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
        )}
          <div className="repository-view">
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={DOCUMENT_INGEST_UPLOAD_ACCEPT}
              onChange={handleUpload}
            />

            {activeWikiScope !== 'official' && (
            <section className="library-repository-strip box-container">
              <div className="section-header">
                <div>
                  <h2>{repositoryPaneTitle}</h2>
                  <p className="text-muted">{repositoryPaneDescription}</p>
                </div>
                <span className="operational-library-count">
                  {repositoryPaneRows.length.toLocaleString()} / {repositoryPaneTotal.toLocaleString()} docs
                </span>
                <button type="button" className="library-dashboard-link" onClick={refreshDocumentRepositories}>
                  Refresh
                </button>
              </div>
              {repositoryPaneRows.length === 0 ? (
                <div className="repo-empty">
                  <Database size={36} />
                  <p>{repositoryPaneEmptyMessage}</p>
                </div>
              ) : (
                <div className="library-repository-grid">
                  {repositoryPaneRows.map(({ repository, document, categoryKey }) => (
                    <article className="library-repository-card" key={document.document_source_id}>
                      <div>
                        <span className="library-repository-scope">{document.source_scope || repository.visibility || repository.repository_kind}</span>
                        <h3>{document.title || document.filename}</h3>
                        <p>{document.chunk_count.toLocaleString()} chunks · {document.indexed_chunk_count.toLocaleString()} indexed</p>
                        <div className="library-document-chip-row">
                          {documentQualityChips(
                            { repository, document, categoryKey },
                            operationalWikiBookBySlug.get(documentBookSlug({ repository, document, categoryKey })),
                          ).map((chip) => (
                            <span key={chip} className="library-document-chip">{chip}</span>
                          ))}
                          <span className={`library-document-chip library-document-chip--${documentIndexStatus({ repository, document, categoryKey })}`}>
                            {indexStatusLabel(documentIndexStatus({ repository, document, categoryKey }))}
                          </span>
                        </div>
                        {!isDocumentReadable(document) && (
                          <span className="library-document-read-block">
                            <AlertCircle size={13} />
                            {documentReadBlockReason(document)}
                          </span>
                        )}
                      </div>
                      <div className="library-document-actions">
                        <button
                          type="button"
                          className={isDocumentReadable(document) ? '' : 'library-document-chat-btn--blocked'}
                          title={documentReadBlockReason(document) || 'Read document'}
                          disabled={!isDocumentReadable(document)}
                          onClick={() => {
                            if (isDocumentReadable(document)) {
                              void openDocumentReader(repository, document);
                            }
                          }}
                        >
                          {isDocumentReadable(document) ? 'Read' : 'Needs repair'}
                        </button>
                        <button
                          type="button"
                          className={isDocumentReadable(document) ? '' : 'library-document-chat-btn--blocked'}
                          title={documentReadBlockReason(document) || 'Ask this document'}
                          disabled={!isDocumentReadable(document)}
                          onClick={() => {
                            if (isDocumentReadable(document)) {
                              openDocumentInChat(repository, document, categoryKey);
                            }
                          }}
                        >
                          {isDocumentReadable(document) ? 'Ask this document' : 'Repair before ask'}
                        </button>
                        <button type="button" onClick={() => openRepositoryInChat(repository)}>
                          Ask this collection
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
            )}

            <section className="pipeline-section box-container factory-workbench-section factory-workbench-section--secondary">
              <div className="factory-workbench-top">
                <div className="factory-workbench-headline">
                  <span className="factory-hub-eyebrow">WIKI Growth Loop</span>
                  <div className="factory-workbench-title-row">
                    <h2>Source Factory</h2>
                    <span className="factory-workbench-title-tag">
                      {factoryLane === 'tools' ? 'Tools Docs Upload' : 'User Docs Upload'}
                    </span>
                  </div>
                  <p className="text-muted">
                    {factoryLane === 'tools'
                      ? '질문에서 부족한 공식 문서를 source candidate로 받아 공장 대기열로 올립니다.'
                      : '사용자 문서를 업로드해 위키형 책과 코퍼스로 생산합니다.'}
                  </p>
                </div>
                <div className="factory-workbench-controls">
                  {factoryLane === 'user' && (
                    <button
                      className="upload-trigger-btn"
                      onClick={() => openUserDocsUpload(true)}
                      disabled={isProcessing}
                    >
                      {isProcessing ? <Loader2 size={16} className="spin-icon" /> : <UploadCloud size={16} />}
                      <span>{isProcessing ? 'Processing...' : 'Upload File'}</span>
                    </button>
                  )}
                  <div className="factory-mode-toggle" role="tablist" aria-label="Source Factory mode">
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
                    <span>Tools Docs Upload</span>
                  </button>
                  <button
                    type="button"
                    className={`factory-entry-btn ${factoryLane === 'user' ? 'active' : ''}`}
                    onClick={() => openUserDocsUpload(true)}
                  >
                    <UploadCloud size={16} />
                    <span>User Docs Upload</span>
                  </button>
                </div>

                <div className="factory-entry-caption">
                  <span>{bookFactoryModeSummary}</span>
                  <span>·</span>
                  <span>
                    {factoryLane === 'tools'
                      ? '공식 레포와 공식 홈페이지 후보를 받아 생산 대기열로 연결합니다.'
                      : '현재 업로드 lane을 Source Factory 안으로 합쳐 same-surface production으로 보여줍니다.'}
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
                <div className="pipeline-visualizer" ref={pipelineRef}>
                  <div className="pipeline-step">
                    <div className="step-badge">Bronze</div>
                    <div className="step-icon">
                      {pipelineStage === 'uploading' ? <Loader2 className="spin-icon" /> : <UploadCloud />}
                    </div>
                    <div className="step-info">
                      <h4>Source Intake</h4>
                      <p>파일 업로드 · 원본 캡처</p>
                    </div>
                  </div>

                  <div className="pipeline-connector"><div className="flow-particle"></div></div>

                  <div className="pipeline-step">
                    <div className="step-badge">Silver</div>
                    <div className="step-icon">
                      {pipelineStage === 'capturing' ? <Loader2 className="spin-icon" /> : <HardDrive />}
                    </div>
                    <div className="step-info">
                      <h4>Structured Wiki</h4>
                      <p>정규화 · 섹션 · 위키 책</p>
                    </div>
                  </div>

                  <div className="pipeline-connector"><div className="flow-particle"></div></div>

                  <div className="pipeline-step">
                    <div className="step-badge">Gold</div>
                    <div className="step-icon">
                      {pipelineStage === 'normalizing' ? <Loader2 className="spin-icon" /> : <Cpu />}
                    </div>
                    <div className="step-info">
                      <h4>Playbook Materialize</h4>
                      <p>코퍼스 · 플레이북 생성</p>
                    </div>
                  </div>

                  <div className="pipeline-connector"><div className="flow-particle"></div></div>

                  <div className="pipeline-step">
                    <div className="step-badge">Judge</div>
                    <div className="step-icon"><BookOpen /></div>
                    <div className="step-info">
                      <h4>User Library Join</h4>
                      <p>정상 저장 · 재오픈 가능</p>
                    </div>
                  </div>
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
                  <div className="log-header">{factoryLane === 'tools' ? 'Source Factory Processing Logs' : 'Recent Processing Logs'}</div>
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
                                    <span>원천소스 찾기</span>
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
                          <h2>Tools Docs Upload</h2>
                          <p className="text-muted">
                            답하지 못한 질문에서 공식 레포 AsciiDoc과 공식 웹페이지 manual 후보를 찾고, 내려받을 계획표를 준비합니다.
                          </p>
                        </div>
                        <div className="repo-panel-badge">
                          <Database size={14} />
                          <span>{repositoryMeta.authMode === 'token' ? 'Authenticated Search' : 'Public Search'}</span>
                        </div>
                        <div className={`repo-panel-badge repo-panel-badge--planner ${repositoryMeta.llmPlannerEnabled ? 'is-llm' : 'is-deterministic'}`}>
                          <ShieldCheck size={14} />
                          <span>{repositoryMeta.llmPlannerEnabled ? 'LLM planner on' : 'deterministic planner · LLM planner off'}</span>
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
                          <span>공식 후보: <code>{officialSourceCandidates.length}</code></span>
                          <span>GitHub repo matches: <code>{repositoryResults.length}</code></span>
                          <span>lanes: <code>{sourceDiscoveryLaneResults.length}</code></span>
                          <span>Bronze 검증 큐: <code>{sourceVerificationQueue.length}</code></span>
                          {repositoryMeta.plannerMode ? <span>planner: <code>{repositoryMeta.plannerMode}</code></span> : null}
                          {repositoryMeta.riskLevel ? <span>risk: <code>{repositoryMeta.riskLevel}</code></span> : null}
                          {repositoryMeta.goldPolicy ? <span>Gold: <code>{repositoryMeta.goldPolicy}</code></span> : null}
                          {repositoryMeta.requiresHumanReview ? <span className="repo-warning-text">human review required</span> : null}
                          {factoryAssistantError ? <span className="repo-error-text">{factoryAssistantError}</span> : null}
                          {repositoryError ? <span className="repo-error-text">{repositoryError}</span> : null}
                          {repositoryMeta.reason ? <span className="repo-meta-reason">{repositoryMeta.reason}</span> : null}
                        </div>
                      )}

                      {sourceDiscoveryLaneResults.length > 0 ? (
                        <div className="source-discovery-lane-grid">
                          {sourceDiscoveryLaneResults.map((lane) => (
                            <section
                              className={`source-discovery-lane-card source-discovery-lane-card--${String(lane.lane).replace(/_/g, '-')}`}
                              key={`${lane.lane}:${lane.provider}`}
                            >
                              <div className="source-discovery-lane-head">
                                <div>
                                  <span className="source-discovery-lane-eyebrow">{lane.lane}</span>
                                  <h3>{sourceDiscoveryLaneKoreanLabel(lane)}</h3>
                                  <span className="source-discovery-lane-provider">{lane.provider}</span>
                                </div>
                                <span className={`source-discovery-lane-status source-discovery-lane-status--${lane.status}`}>
                                  {sourceDiscoveryLaneStatusLabel(lane)}
                                </span>
                              </div>
                              <div className="source-discovery-lane-policy">
                                <span>{lane.trust_level}</span>
                                <span>{lane.gold_policy}</span>
                                {lane.requires_human_review ? <span>human review</span> : null}
                                {lane.filtered_count ? <span>filtered {lane.filtered_count}</span> : null}
                              </div>
                              {(lane.message || lane.trust_note) ? (
                                <p className="source-discovery-lane-note">
                                  {[lane.message, lane.trust_note].filter(Boolean).join(' · ')}
                                </p>
                              ) : null}
                              {lane.items.length > 0 ? (
                                <div className="source-discovery-lane-items">
                                  {lane.items.slice(0, 4).map((item, index) => {
                                    const href = sourceDiscoveryItemHref(item);
                                    const title = sourceDiscoveryItemTitle(item);
                                    const meta = sourceDiscoveryItemMeta(item);
                                    const verificationKey = sourceDiscoveryCandidateKey(lane, item);
                                    const canSaveForVerification = sourceDiscoveryLaneNeedsVerification(lane);
                                    const savedForVerification = sourceVerificationSavedKeys.has(verificationKey);
                                    const savingForVerification = savingVerificationKey === verificationKey;
                                    return (
                                      <div className="source-discovery-lane-item" key={`${lane.lane}:${title}:${index}`}>
                                        <div className="source-discovery-lane-item-copy">
                                          <strong>{title}</strong>
                                          {meta ? <span>{meta}</span> : null}
                                          <div className="source-discovery-lane-item-badges">
                                            <span>source {lane.provider}</span>
                                            <span>trust {lane.trust_level}</span>
                                            <span>Gold {lane.gold_policy}</span>
                                            <span>{lane.requires_human_review ? 'human review required' : 'human review not required'}</span>
                                          </div>
                                        </div>
                                        <div className="source-discovery-lane-actions">
                                          {canSaveForVerification ? (
                                            <button
                                              type="button"
                                              className="source-discovery-verification-btn"
                                              onClick={() => handleSaveSourceVerificationCandidate(lane, item)}
                                              disabled={savedForVerification || savingForVerification}
                                            >
                                              {savingForVerification ? (
                                                <Loader2 size={13} className="spin-icon" />
                                              ) : savedForVerification ? (
                                                <CheckCircle2 size={13} />
                                              ) : (
                                                <BookmarkPlus size={13} />
                                              )}
                                              <span>{savedForVerification ? 'Bronze 큐' : '검증 큐'}</span>
                                            </button>
                                          ) : null}
                                          {href ? (
                                            <a className="source-discovery-lane-link" href={href} target="_blank" rel="noreferrer">
                                              <ExternalLink size={13} />
                                            </a>
                                          ) : null}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : (
                                <div className="source-discovery-lane-empty-block">
                                  <p className="source-discovery-lane-empty">
                                    {lane.error || lane.message || '이 lane에는 아직 후보가 없습니다.'}
                                  </p>
                                  {sourceDiscoveryLaneNeedsVerification(lane) ? (() => {
                                    const verificationKey = sourceDiscoveryCandidateKey(lane);
                                    const savedForVerification = sourceVerificationSavedKeys.has(verificationKey);
                                    const savingForVerification = savingVerificationKey === verificationKey;
                                    return (
                                      <button
                                        type="button"
                                        className="source-discovery-verification-btn"
                                        onClick={() => handleSaveSourceVerificationCandidate(lane)}
                                        disabled={savedForVerification || savingForVerification}
                                      >
                                        {savingForVerification ? (
                                          <Loader2 size={13} className="spin-icon" />
                                        ) : savedForVerification ? (
                                          <CheckCircle2 size={13} />
                                        ) : (
                                          <BookmarkPlus size={13} />
                                        )}
                                        <span>{savedForVerification ? 'Bronze 큐' : 'lane 검증 큐'}</span>
                                      </button>
                                    );
                                  })() : null}
                                </div>
                              )}
                            </section>
                          ))}
                        </div>
                      ) : null}

                      {officialSourceCandidates.length > 0 ? (
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
                      ) : sourceDiscoveryLaneResults.length === 0 ? (
                        <div className="repo-empty">
                          <MessageSquare size={40} />
                          <p>원천소스 찾기를 누르거나 질문을 직접 넣으면 공식 원천소스 두 종류와 다운로드 계획표를 준비합니다.</p>
                        </div>
                      ) : null}
                    </section>
                  </div>
                </section>

                <section className="repo-favorites-section box-container" ref={sourceVerificationQueueRef}>
                  <div className="section-header">
                    <div>
                      <h2>Bronze Verification Queue</h2>
                      <p className="text-muted">커뮤니티, 벤더 KB, Issue/PR 후보는 공식 교차검증 전까지 인용과 Gold 승격을 막습니다.</p>
                    </div>
                    <div className="source-verification-header-actions">
                      <span className="status-pill" data-status={sourceVerificationQueue.length > 0 ? 'processing' : 'ready'}>
                        {sourceVerificationQueue.length} pending
                      </span>
                      <button
                        type="button"
                        className="source-judge-run-btn"
                        onClick={() => void handleRunSourceJudge()}
                        disabled={sourceJudgeRunning || !(factoryAssistantQuery.trim() || searchQuery.trim())}
                      >
                        {sourceJudgeRunning ? <Loader2 size={14} className="spin-icon" /> : <ShieldCheck size={14} />}
                        <span>Run Judge</span>
                      </button>
                    </div>
                  </div>

                  {sourceVerificationQueue.length === 0 ? (
                    <div className="repo-empty repo-favorites-empty">
                      <ShieldCheck size={40} />
                      <p>검증 대기 중인 비공식 source candidate가 없습니다.</p>
                    </div>
                  ) : (
                    <div className="source-verification-list">
                      {sourceVerificationQueue.slice(0, 8).map((record) => (
                        <article className="source-verification-item" key={record.candidate_id}>
                          <div className="source-verification-copy">
                            <div className="source-verification-title-row">
                              <span className="source-verification-grade">{record.grade}</span>
                              <strong>{record.title}</strong>
                            </div>
                            <p>{sourceDiscoveryLaneKoreanName(record.lane, record.lane)}</p>
                            <div className="source-verification-tags">
                              <span>{record.verification_status}</span>
                              <span>{record.gold_policy}</span>
                              <span>{record.citation_eligible ? 'citation allowed' : 'citation blocked'}</span>
                              {record.required_checks.slice(0, 2).map((check) => (
                                <span key={check.id || check.label}>{check.label || check.id}</span>
                              ))}
                              {record.promotion_blockers.slice(0, 2).map((blocker) => (
                                <span key={blocker}>{blocker}</span>
                              ))}
                            </div>
                          </div>
                          {record.source_url ? (
                            <a className="source-discovery-lane-link" href={record.source_url} target="_blank" rel="noreferrer">
                              <ExternalLink size={13} />
                            </a>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  )}

                  {sourceJudgeError ? (
                    <p className="repo-error-text">{sourceJudgeError}</p>
                  ) : null}

                  {latestSourceJudgeReport ? (
                    <div className={`source-judge-report source-judge-report--${sourceJudgeVerdictClass(latestSourceJudgeReport.overall_verdict)}`}>
                      <div className="source-judge-report-head">
                        <div>
                          <span className="source-judge-eyebrow">Source Discovery Judge</span>
                          <strong>{sourceJudgeVerdictLabel(latestSourceJudgeReport.overall_verdict)}</strong>
                        </div>
                        <span>{latestSourceJudgeReport.pass_fail}</span>
                      </div>
                      <p>{latestSourceJudgeReport.question}</p>
                      <div className="source-judge-metrics">
                        <span>공식 교차검증 <strong>{latestSourceJudgeReport.source_trust.official_cross_check ? 'OK' : 'MISSING'}</strong></span>
                        <span>공식 인용 <strong>{latestSourceJudgeReport.citation_coverage.official_citation_count}</strong></span>
                        <span>검증 대기 <strong>{latestSourceJudgeReport.source_trust.needs_verification_count}</strong></span>
                        <span>Gap <strong>{latestSourceJudgeReport.remaining_gap.length}</strong></span>
                      </div>
                      {latestSourceJudgeReport.remaining_gap.length > 0 ? (
                        <div className="source-judge-chip-row">
                          {latestSourceJudgeReport.remaining_gap.slice(0, 5).map((gap) => (
                            <span key={gap}>{gap}</span>
                          ))}
                        </div>
                      ) : null}
                      {latestSourceJudgeReport.after_answer ? (
                        <div className="source-judge-answer">
                          <span>RAG replay answer</span>
                          <p>{latestSourceJudgeReport.after_answer}</p>
                        </div>
                      ) : null}
                      {latestSourceJudgeReport.evidence.citations.length > 0 ? (
                        <div className="source-judge-citations">
                          <span>Replay citations</span>
                          {latestSourceJudgeReport.evidence.citations.slice(0, 4).map((citation, index) => {
                            const href = sourceJudgeCitationHref(citation);
                            const title = sourceJudgeCitationTitle(citation);
                            const lane = sourceJudgeCitationLane(citation);
                            const body = (
                              <>
                                <strong>{index + 1}. {title}</strong>
                                <em>{sourceDiscoveryLaneKoreanName(lane, lane)}</em>
                              </>
                            );
                            return href ? (
                              <a key={`${href}:${title}`} href={href} target="_blank" rel="noreferrer">
                                {body}
                              </a>
                            ) : (
                              <div key={`${lane}:${title}:${index}`}>
                                {body}
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                      {(latestSourceJudgeReport.next_actions ?? []).length > 0 ? (
                        <div className="source-judge-actions">
                          <span>Next actions</span>
                          {(latestSourceJudgeReport.next_actions ?? []).slice(0, 4).map((action) => {
                            const buttonLabel = sourceJudgeActionButtonLabel(action);
                            return (
                              <div
                                className={`source-judge-action source-judge-action--${sourceJudgeActionClass(action.severity)}`}
                                key={`${action.action_id}:${action.lane ?? ''}:${action.query}`}
                              >
                                <div>
                                  <strong>{action.label}</strong>
                                  <p>{action.description}</p>
                                  {action.lane ? <em>{sourceDiscoveryLaneKoreanName(action.lane, action.lane)}</em> : null}
                                </div>
                                {buttonLabel ? (
                                  <button
                                    type="button"
                                    onClick={() => void handleJudgeNextAction(action)}
                                    disabled={sourceJudgeRunning}
                                  >
                                    {action.action_id === 'rerun_rag_replay' && sourceJudgeRunning ? (
                                      <Loader2 size={13} className="spin-icon" />
                                    ) : action.action_id === 'rerun_rag_replay' ? (
                                      <ShieldCheck size={13} />
                                    ) : (
                                      <Search size={13} />
                                    )}
                                    <span>{buttonLabel}</span>
                                  </button>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="source-judge-empty">
                      Judge를 실행하면 원 질문을 실제 RAG로 다시 답변하고, 인용 커버리지와 공식 교차검증, 남은 gap을 여기 기록합니다.
                    </div>
                  )}
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
                  {userLibraryBooks.length === 0 ? (
                    <div className="repo-empty">
                      <FileText size={24} />
                      <p>현재 저장된 User Library 문서가 없습니다.</p>
                    </div>
                  ) : (
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
                  )}
                </section>

                <section className="draft-management box-container">
                  <div className="section-header">
                    <h2>Uploaded Drafts ({drafts.length})</h2>
                  </div>
                  {drafts.length === 0 ? (
                    <div className="repo-empty">
                      <FileText size={24} />
                      <p>현재 저장된 업로드 초안이 없습니다.</p>
                    </div>
                  ) : (
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
                  )}
                </section>
              </>
            )}
          </div>
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
            {metricPopover.noticeMessage && (
              <div className="metric-popover-notice">
                <ShieldAlert size={14} />
                <span>{metricPopover.noticeMessage}</span>
              </div>
            )}
            <div className="metric-popover-body">
              {metricPopover.rows.length === 0 ? (
                <div className="preview-no-sections">{metricPopover.emptyMessage || '등록된 북이 없습니다.'}</div>
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
                    const operationalSmokeChips = isCorpusMode || !hasViewerSmokeEvidence(book) ? [] : viewerSmokeChips(book);
                    const operationalLanguageChips = isCorpusMode ? [] : languageGateChips(book);
                    const rowChips = isCorpusMode
                      ? [
                        book.command_chunk_count ? `commands ${book.command_chunk_count}` : '',
                        book.error_chunk_count ? `errors ${book.error_chunk_count}` : '',
                        ...Object.entries(book.chunk_type_breakdown ?? {})
                          .slice(0, 3)
                          .map(([kind, count]) => `${kind} ${count}`),
                      ].filter(Boolean)
                      : [...customerPackBookEvidenceBits(book), ...operationalLanguageChips, ...operationalSmokeChips];
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

      {documentReader && (
        <div className="preview-overlay document-reader-overlay" onClick={closeDocumentReader}>
          <div className="preview-popover preview-popover-chunk document-reader-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <span className="document-reader-eyebrow">Document Reader</span>
                <h3>{documentReader.payload?.title || documentReader.source.title || documentReader.source.filename}</h3>
                <div className="preview-header-meta">
                  <span>{documentReader.source.source_scope || documentReader.repository.repository_kind}</span>
                  <span>{documentReader.repository.title}</span>
                  <span>
                    {(documentReader.payload?.chunks.length ?? 0).toLocaleString()}
                    /
                    {(documentReader.payload?.total_chunks ?? documentReader.source.chunk_count).toLocaleString()} chunks
                  </span>
                  <span>
                    {(documentReader.source.indexed_chunk_count || 0).toLocaleString()} indexed
                  </span>
                </div>
                <div className="library-document-chip-row">
                  {documentQualityChips(
                    {
                      repository: documentReader.repository,
                      document: documentReader.source,
                      categoryKey: inferWikiCategory(documentReader.source, documentReader.repository),
                    },
                    operationalWikiBookBySlug.get(documentBookSlug({
                      repository: documentReader.repository,
                      document: documentReader.source,
                      categoryKey: inferWikiCategory(documentReader.source, documentReader.repository),
                    })),
                  ).map((chip) => (
                    <span key={chip} className="library-document-chip">{chip}</span>
                  ))}
                  {documentReader.payload?.markdown_total_chars ? (
                    <span className="library-document-chip">
                      {documentReader.payload.markdown_total_chars.toLocaleString()} parsed chars
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="preview-header-actions">
                <button
                  type="button"
                  className="preview-open-full-btn"
                  onClick={() => openDocumentInChat(documentReader.repository, documentReader.source)}
                >
                  <MessageSquare size={14} />
                  <span>Ask</span>
                </button>
                <button className="preview-close-btn" onClick={closeDocumentReader}><X size={18} /></button>
              </div>
            </div>
            <div className="metric-popover-body chunk-viewer-body document-reader-body">
              {documentReader.loading ? (
                <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> Loading document...</div>
              ) : documentReader.error && !documentReader.payload ? (
                <div className="preview-no-sections">{documentReader.error}</div>
              ) : documentReader.payload ? (
                <>
                  {documentReader.payload.markdown ? (
                    <section className="document-reader-summary">
                      <h4>
                        Parsed document
                        {documentReader.payload.markdown_truncated ? <span>preview truncated</span> : null}
                      </h4>
                      <pre>{documentReader.payload.markdown.slice(0, 6000)}</pre>
                    </section>
                  ) : null}
                  <div className="chunk-card-list">
                    {documentReader.payload.chunks.map((chunk, index) => (
                      <article className="chunk-card" key={chunk.chunk_id || `${chunk.chunk_key}-${index}`}>
                        <div className="chunk-card-header">
                          <div className="chunk-card-meta">
                            <span className="chunk-card-type">{chunk.chunk_type || 'document'}</span>
                            <span>#{chunk.ordinal || index + 1}</span>
                            {chunk.section_number ? <span>{chunk.section_number}</span> : null}
                            <span>{chunk.token_count.toLocaleString()} tokens</span>
                          </div>
                        </div>
                        <strong className="chunk-card-title">
                          {chunk.heading_title || chunk.section_path.at(-1) || chunk.source_anchor || 'Untitled section'}
                        </strong>
                        {chunk.section_path.length > 0 ? (
                          <div className="chunk-card-path">{chunk.section_path.join(' › ')}</div>
                        ) : null}
                        <pre className="chunk-card-text">{chunk.markdown || chunk.text}</pre>
                      </article>
                    ))}
                  </div>
                  {documentReader.payload.has_more ? (
                    <button
                      type="button"
                      className="document-reader-load-more"
                      disabled={documentReader.loadingMore}
                      onClick={() => { void loadMoreDocumentReader(); }}
                    >
                      {documentReader.loadingMore ? 'Loading...' : 'Load more chunks'}
                    </button>
                  ) : (
                    <div className="document-reader-end">모든 chunk를 불러왔습니다.</div>
                  )}
                  {documentReader.error ? <div className="preview-no-sections">{documentReader.error}</div> : null}
                </>
              ) : (
                <div className="preview-no-sections">표시할 문서 본문이 없습니다.</div>
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
                  <span>{bookViewer.section_count} sections</span>
                  <span className={playbookGradeBadgeClass(bookViewer.grade)}>{normalizePlaybookGrade(bookViewer.grade)}</span>
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
                {bookSourceOriginHref(bookViewer) ? (
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
                  <div className="preview-no-sections">{bookViewerError || '문서 본문을 불러올 수 없습니다.'}</div>
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
