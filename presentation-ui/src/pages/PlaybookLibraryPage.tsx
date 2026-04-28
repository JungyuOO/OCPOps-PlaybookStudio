import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
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
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import {
  CUSTOMER_PACK_UPLOAD_ACCEPT,
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
  type RuntimeFigureItem,
  uploadCustomerPackDraft,
  captureCustomerPackDraft,
  normalizeCustomerPackDraft,
  loadDataControlRoom,
  loadDataControlRoomChunks,
  listCustomerPackDrafts,
  deleteCustomerPackDraft,
  loadCustomerPackBook,
  loadRepositoryFavorites,
  loadRepositoryUnanswered,
  loadOfficialSourceCatalog,
  materializeOfficialSourceCandidate,
  removeRepositoryFavorite,
  searchRepositories,
  loadCustomerPackCapturedPreview,
  loadRuntimeFigures,
  loadViewerDocument,
  toRuntimeUrl,
  formatBytes,
} from '../lib/runtimeApi';
import { WIKI_VISION_MODES, loadStoredVisionMode, persistVisionMode, type VisionMode } from '../lib/wikiVision';
import { displayCustomerDocumentTitle } from '../lib/customerDocumentTitles';
import { ROUTES } from '../app/routes';
import { dedupeDraftCatalogForDisplay } from './workspaceDraftCatalog';

type PipelineStage = 'idle' | 'uploading' | 'capturing' | 'normalizing' | 'done' | 'error';
type FactoryLane = 'tools' | 'user';
type FactoryRunMode = 'auto' | 'manual';
type OfficialSourceBasisKey = 'official_repo' | 'official_homepage';

interface FigureAtlasEntry {
  key: string;
  title: string;
  subtitle: string;
  kind: string;
  intent: string;
  why: string;
  thumbUrl?: string;
  href: string;
  count?: number;
  isCluster?: boolean;
}

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

function customDocumentMeta(book?: LibraryBook | null): string[] {
  if (!book) {
    return [];
  }
  const sourceCount = Number(book.custom_document_source_count ?? 0);
  const extSummary = Object.entries(book.custom_document_ext_breakdown ?? {})
    .map(([ext, count]) => `${ext.toUpperCase()} ${count}`)
    .join(' · ');
  return [
    book.custom_document_kind_label || '커스텀문서',
    sourceCount > 0 ? `${sourceCount}개 재료` : '',
    extSummary,
    book.custom_document_status === 'ui_ready_source_hidden' ? '원본 비노출' : '',
  ].filter(Boolean);
}

function normalizePlaybookGrade(grade?: string | null): 'Gold' | 'Silver' | 'Bronze' | 'Blocked' {
  const normalized = String(grade || '').trim().toLowerCase();
  if (normalized === 'gold') {
    return 'Gold';
  }
  if (normalized === 'silver' || normalized === 'silver draft' || normalized === 'mixed review') {
    return 'Silver';
  }
  if (normalized === 'blocked') {
    return 'Blocked';
  }
  return 'Bronze';
}

function playbookGradeBadgeClass(grade?: string | null): string {
  const normalized = normalizePlaybookGrade(grade).toLowerCase();
  return `playbook-grade-badge playbook-grade-badge--${normalized}`;
}

function firstFigureSectionToken(sectionHint: string): string {
  const normalized = sectionHint.replace(/[›>]/g, '|');
  return normalized
    .split('|')
    .map((chunk) => chunk.trim())
    .find(Boolean) || '';
}

function buildFigureAtlasEntries(figures: RuntimeFigureItem[]): FigureAtlasEntry[] {
  const groups = new Map<string, RuntimeFigureItem[]>();
  for (const figure of figures) {
    const diagramKey = (figure.diagram_type || '').trim().toLowerCase();
    const sectionKey = firstFigureSectionToken(figure.section_hint || '').toLowerCase();
    const assetKey = (figure.asset_kind || 'figure').trim().toLowerCase();
    const key = diagramKey
      ? `diagram:${diagramKey}`
      : sectionKey
        ? `section:${sectionKey}`
        : `asset:${assetKey}`;
    const bucket = groups.get(key) ?? [];
    bucket.push(figure);
    groups.set(key, bucket);
  }

  return [...groups.entries()]
    .sort((a, b) => {
      if (b[1].length !== a[1].length) return b[1].length - a[1].length;
      return a[1][0].caption.localeCompare(b[1][0].caption);
    })
    .slice(0, 3)
    .map(([key, bucket]) => {
      const first = bucket[0];
      const isDiagram = Boolean(first.diagram_type);
      const thumbUrl = first.asset_url ? toRuntimeUrl(first.asset_url) : undefined;
      if (bucket.length === 1) {
        return {
          key,
          title: first.caption,
          subtitle: first.section_hint || first.diagram_type || first.asset_kind,
          kind: isDiagram ? 'Diagram' : 'Figure',
          intent: 'View',
          why: '문서를 읽기 전에 맥락을 빠르게 잡는 시각 자산',
          thumbUrl,
          href: first.viewer_path,
        };
      }

      const clusterLabel = isDiagram
        ? `${first.diagram_type || 'diagram'} cluster`
        : firstFigureSectionToken(first.section_hint || '') || 'figure cluster';
      return {
        key,
        title: clusterLabel,
        subtitle: `${bucket.length} visual assets grouped`,
        kind: isDiagram ? 'Diagram Cluster' : 'Figure Cluster',
        intent: 'Scan',
        why: `이 문서를 이해시키는 ${bucket.length}개의 시각 자산 묶음`,
        thumbUrl,
        href: first.viewer_path,
        count: bucket.length,
        isCluster: true,
      };
    });
}

function buildWorldKeywords(book: LibraryBook): string[] {
  const slugBits = book.book_slug.split('_').filter(Boolean);
  const titleBits = book.title
    .split(/[·,:()/\s-]+/)
    .map((bit) => bit.trim())
    .filter((bit) => bit.length >= 2);
  return [...new Set([...slugBits, ...titleBits])].slice(0, 5);
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
  const [factoryLane, setFactoryLane] = useState<FactoryLane>('tools');
  const [visionMode, setVisionMode] = useState<VisionMode>(() => loadStoredVisionMode());
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>('idle');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState('');
  const [currentFile, setCurrentFile] = useState('');
  const [controlRoom, setControlRoom] = useState<DataControlRoomResponse | null>(null);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [previewDraft, setPreviewDraft] = useState<CustomerPackDraft | null>(null);
  const [metricPopover, setMetricPopover] = useState<MetricPopoverState | null>(null);
  const [buyerPacketPopover, setBuyerPacketPopover] = useState<{ title: string; packets: BuyerPacket[] } | null>(null);
  const [chunkViewer, setChunkViewer] = useState<ChunkViewerState | null>(null);
  const [bookViewer, setBookViewer] = useState<LibraryBook | null>(null);
  const [bookViewerDocument, setBookViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [bookViewerLoading, setBookViewerLoading] = useState(false);
  const [previewCapturedUrl, setPreviewCapturedUrl] = useState('');
  const [previewCapturedType, setPreviewCapturedType] = useState('');
  const [previewViewerDocument, setPreviewViewerDocument] = useState<ViewerDocumentPayload | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [atlasBookFigures, setAtlasBookFigures] = useState<RuntimeFigureItem[]>([]);
  const atlasBookFigureEntries = useMemo(() => buildFigureAtlasEntries(atlasBookFigures), [atlasBookFigures]);
  const [comparisonBookSlug, setComparisonBookSlug] = useState('');
  const [comparisonBookFigures, setComparisonBookFigures] = useState<RuntimeFigureItem[]>([]);
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
    listCustomerPackDrafts().then((res) => setDrafts(dedupeDraftCatalogForDisplay(res.drafts ?? []))).catch(() => { });
    refreshRepositoryFavorites();
    refreshRepositoryUnanswered();
    refreshOfficialCatalog();
  }, [refreshOfficialCatalog, refreshRepositoryFavorites, refreshRepositoryUnanswered]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  useEffect(() => () => {
    stopToolsRunHeartbeat();
  }, [stopToolsRunHeartbeat]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    persistVisionMode(visionMode);
  }, [visionMode]);

  useEffect(() => {
    if (visionMode !== 'atlas_canvas' || !bookViewer?.book_slug) {
      setAtlasBookFigures([]);
      return;
    }
    loadRuntimeFigures(bookViewer.book_slug, 3)
      .then((payload) => setAtlasBookFigures(payload.items ?? []))
      .catch(() => setAtlasBookFigures([]));
  }, [bookViewer, visionMode]);

  useEffect(() => {
    if (!bookViewer?.viewer_path) {
      setBookViewerDocument(null);
      setBookViewerLoading(false);
      return;
    }

    let cancelled = false;
    setBookViewerLoading(true);
    setBookViewerDocument(null);

    loadViewerDocument(bookViewer.viewer_path)
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
    let draft: CustomerPackDraft;

    try {
      setPipelineStage('uploading');
      addLog('info', `Uploading '${file.name}'...`);
      draft = await uploadCustomerPackDraft(file);
      addLog('success', `'${file.name}' uploaded → draft ${draft.draft_id}`);

      setPipelineStage('capturing');
      addLog('info', `Capturing source artifact (${draft.source_type.toUpperCase()})...`);
      draft = await captureCustomerPackDraft(draft.draft_id);
      addLog('success', `Artifact captured for '${draft.title}'`);

      setPipelineStage('normalizing');
      const backend = ['pdf', 'docx', 'pptx', 'xlsx'].includes(draft.source_type)
        ? 'MarkItDown' : 'Native parser';
      addLog('info', `Normalizing via ${backend} → canonical sections...`);
      draft = await normalizeCustomerPackDraft(draft.draft_id);

      const qualityLine = draft.quality_score > 0
        ? ` (quality: ${draft.quality_score}/100 — ${draft.quality_status})`
        : '';
      addLog('success', `Normalized: ${draft.playable_asset_count} playable assets, ${draft.derived_asset_count} derived${qualityLine}`);

      setPipelineStage('done');
      addLog('success', `'${draft.title}' saved to User Library.`);
      refreshData();
      setTimeout(() => { setPipelineStage('idle'); setCurrentFile(''); }, 6000);
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Unknown error');
      setPipelineStage('error');
      setErrorMsg(msg);
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
    switch (stage) {
      case 'uploading': return 'Uploading...';
      case 'capturing': return 'Capturing Artifact...';
      case 'normalizing': return 'Normalizing...';
      case 'done': return 'Pipeline Complete';
      case 'error': return 'Pipeline Failed';
      default: return 'Engine Idle';
    }
  };

  const isProcessing = ['uploading', 'capturing', 'normalizing'].includes(pipelineStage);

  const summary = controlRoom?.summary;
  const llmwikiPromotion = controlRoom?.llmwiki_promotion;
  const llmwikiRail = llmwikiPromotion?.status_rail ?? [];
  const llmwikiMetrics = llmwikiPromotion?.metrics ?? {};
  const llmwikiReport = llmwikiPromotion?.selected_report;
  const llmwikiModeContract = llmwikiPromotion?.mode_contract?.supported_modes ?? [];
  const llmwikiStatusLabel = llmwikiPromotion?.status ?? summary?.llmwiki_promotion_status ?? 'missing';
  const llmwikiReady = Boolean(llmwikiPromotion?.ready ?? summary?.llmwiki_promotion_ready);
  const llmwikiStale = Boolean(llmwikiReport?.stale ?? summary?.llmwiki_promotion_report_stale);
  const llmwikiGeneratedAt = llmwikiReport?.generated_at ? new Date(llmwikiReport.generated_at).toLocaleString() : 'No report';
  const validationLoop = controlRoom?.llmwiki_validation_loop;
  const validationLoopReport = validationLoop?.selected_report;
  const validationLoopReady = Boolean(validationLoop?.ready ?? summary?.llmwiki_validation_loop_ready);
  const validationLoopStale = Boolean(validationLoopReport?.stale);
  const validationLoopGeneratedAt = validationLoopReport?.generated_at ? new Date(validationLoopReport.generated_at).toLocaleString() : 'No loop report';
  const validationLoopMetrics = validationLoop?.metrics ?? {};
  const validationLoopServices = validationLoop?.acceptance?.essential_services ?? {};
  const suryaPolicy = validationLoop?.surya_policy;
  const suryaOptional = suryaPolicy?.required_for_llmwiki_runtime === false;
  const developmentControl = controlRoom?.development_control;
  const developmentSurfaces = developmentControl?.surfaces ?? [];
  const developmentSummary = developmentControl?.summary;
  const developmentExcluded = developmentControl?.scope?.excluded ?? [];
  const developmentStatusLabel = developmentControl?.ready
    ? 'Ready'
    : developmentControl?.status === 'watch'
      ? 'Watch'
      : developmentControl?.status ?? 'Missing';
  const officialCorpusBooks = [...(controlRoom?.corpus?.books ?? [])];
  const officialPlaybookBooks = [...(controlRoom?.manualbooks?.books ?? [])];
  const customDocumentBooks = [...(controlRoom?.custom_documents?.books ?? [])];
  const userLibraryBucket = controlRoom?.customer_pack_runtime_books ?? controlRoom?.user_library_books;
  const userCorpusBooks = [...(controlRoom?.user_library_corpus?.books ?? [])];
  const approvedRuntimeBooks = summary?.approved_runtime_count ?? summary?.gold_book_count ?? controlRoom?.gold_books?.length ?? 0;
  const userLibraryBooks = [...(userLibraryBucket?.books ?? [])];
  const userLibraryBookCount = summary?.customer_pack_runtime_book_count
    ?? summary?.user_library_book_count
    ?? userLibraryBooks.length;
  const customDocumentCount = summary?.custom_document_count ?? customDocumentBooks.length;
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
  const operationalWikiBooks = allOperationalWikiBooks.slice(0, 8);
  const wikiNavigationBacklog = summary?.wiki_navigation_backlog_count ?? controlRoom?.wiki_navigation_backlog?.books?.length ?? 0;
  const wikiUsageSignals = summary?.wiki_usage_signal_count ?? controlRoom?.wiki_usage_signals?.books?.length ?? 0;
  const productGate = summary?.product_gate_count ?? controlRoom?.product_gate?.books?.length ?? 0;
  const buyerPacketBundle = summary?.buyer_packet_bundle_count ?? controlRoom?.buyer_packet_bundle?.books?.length ?? 0;
  const releaseCandidateFreeze = controlRoom?.release_candidate_freeze;
  const releaseCandidatePacket = controlRoom?.buyer_packet_bundle?.books?.find(
    (packet) => packet.book_slug === 'buyer_packet__release-candidate-freeze',
  ) ?? null;
  const activeVision = WIKI_VISION_MODES.find((mode) => mode.id === visionMode) ?? WIKI_VISION_MODES[0];
  const comparisonCandidates = useMemo(() => {
    const preferred = operationalWikiBooks.find((book) => book.book_slug === 'advanced_networking');
    const others = operationalWikiBooks.filter((book) => book.book_slug !== 'advanced_networking').slice(0, 5);
    return preferred ? [preferred, ...others] : operationalWikiBooks.slice(0, 6);
  }, [operationalWikiBooks]);
  useEffect(() => {
    if (!comparisonCandidates.length) {
      setComparisonBookSlug('');
      return;
    }
    if (!comparisonBookSlug || !comparisonCandidates.some((book) => book.book_slug === comparisonBookSlug)) {
      setComparisonBookSlug(comparisonCandidates[0].book_slug);
    }
  }, [comparisonBookSlug, comparisonCandidates]);
  const comparisonBook = useMemo(
    () => comparisonCandidates.find((book) => book.book_slug === comparisonBookSlug) ?? comparisonCandidates[0] ?? null,
    [comparisonBookSlug, comparisonCandidates],
  );
  useEffect(() => {
    if (!comparisonBook?.book_slug) {
      setComparisonBookFigures([]);
      return;
    }
    loadRuntimeFigures(comparisonBook.book_slug, 4)
      .then((payload) => setComparisonBookFigures(payload.items ?? []))
      .catch(() => setComparisonBookFigures([]));
  }, [comparisonBook]);
  const comparisonFigureEntries = useMemo(() => buildFigureAtlasEntries(comparisonBookFigures), [comparisonBookFigures]);
  const comparisonWorldKeywords = useMemo(
    () => (comparisonBook ? buildWorldKeywords(comparisonBook) : []),
    [comparisonBook],
  );
  const comparisonLinkedDocs = useMemo(
    () => operationalWikiBooks.filter((book) => book.book_slug !== comparisonBook?.book_slug).slice(0, 2),
    [comparisonBook, operationalWikiBooks],
  );
  const guidedTourShelfSteps = useMemo(() => operationalWikiBooks.slice(0, 3), [operationalWikiBooks]);
  const guidedTourShelfDocs = useMemo(() => operationalWikiBooks.slice(3, 5), [operationalWikiBooks]);
  const atlasReadingBooks = useMemo(() => operationalWikiBooks.slice(0, 3), [operationalWikiBooks]);
  const atlasRelationBooks = useMemo(() => operationalWikiBooks.slice(3, 6), [operationalWikiBooks]);
  const atlasContextBooks = useMemo(() => operationalWikiBooks.slice(6, 8), [operationalWikiBooks]);
  const hasMetricSourceDrift = Boolean(controlRoom?.source_of_truth_drift?.status_alignment?.mismatches?.length);
  const gate = controlRoom?.gate;
  const productRehearsal = controlRoom?.product_rehearsal;
  const roleRehearsal = controlRoom?.role_rehearsal;
  const roleRehearsalReport = roleRehearsal?.selected_report;
  const roleRehearsalReady = Boolean(roleRehearsal?.ready ?? summary?.role_rehearsal_ready);
  const roleRehearsalPassCount = roleRehearsal?.pass_count ?? summary?.role_rehearsal_pass_count ?? 0;
  const roleRehearsalTotal = roleRehearsal?.total ?? summary?.role_rehearsal_total ?? 0;
  const operatorRole = roleRehearsal?.roles?.operator_a;
  const learnerRole = roleRehearsal?.roles?.learner_b;
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
    ? `${userLibraryBookCount} user books · ${drafts.length} drafts`
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
              <h1>Playbook Library</h1>
              <p className="text-muted">
                {viewMode === 'repository'
                  ? 'Book Factory & Asset Repository'
                  : 'LLMWiki Runtime Control'}
              </p>
            </div>
          </div>

          <div className="header-actions">
            <div className="view-toggle">
              <Link to={ROUTES.pbsStudio} className="view-toggle-link">
                <Layers size={16} />
                <span>Studio</span>
              </Link>
              <button
                className={viewMode === 'monitoring' ? 'active' : ''}
                onClick={() => navigate('/playbook-library/control-tower')}
              >
                <Activity size={16} />
                <span>{visionMode === 'guided_tour' ? 'Guided Tour' : 'Control Tower'}</span>
              </button>
              <button
                className={viewMode === 'repository' ? 'active' : ''}
                onClick={() => navigate('/playbook-library/repository')}
              >
                <Database size={16} />
                <span>Repository</span>
              </button>
              <Link to={ROUTES.opsWorkspaces} className="view-toggle-link">
                <ShieldCheck size={16} />
                <span>Ops Console</span>
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="library-main">
        {viewMode === 'monitoring' ? (
          <div className="monitoring-view">
            <section className="llmwiki-control-panel box-container">
              <div className="llmwiki-control-header">
                <div>
                  <span className="vision-compare-eyebrow">LLMWiki Control Tower</span>
                  <h2>공식 매뉴얼, 고객 운영북, 챗봇 런타임 상태</h2>
                  <p>
                    같은 promotion report에서 공식 Gold 파이프라인, 고객 PPT master, live LLM/vector, 챗봇 검증을 함께 판단합니다.
                  </p>
                </div>
                <div className={`llmwiki-ready-badge ${llmwikiReady ? 'ready' : llmwikiStale ? 'stale' : 'blocked'}`}>
                  {llmwikiReady ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                  <span>{llmwikiReady ? 'Ready' : llmwikiStale ? 'Stale Report' : llmwikiStatusLabel}</span>
                </div>
              </div>

              <div className="llmwiki-status-rail" aria-label="llmwiki runtime status">
                {(llmwikiRail.length ? llmwikiRail : [
                  { key: 'promotion', label: 'Promotion', status: llmwikiStatusLabel, ready: llmwikiReady, detail: 'promotion report', count: llmwikiReady ? 1 : 0, total: 1 },
                  { key: 'official', label: 'Official', status: summary?.official_gold_ok ? 'ready' : 'unknown', ready: Boolean(summary?.official_gold_ok), detail: 'official gold book', count: approvedRuntimeBooks, total: approvedRuntimeBooks },
                  { key: 'customer', label: 'Customer', status: summary?.customer_master_ok ? 'ready' : 'unknown', ready: Boolean(summary?.customer_master_ok), detail: 'customer PPT master', count: userLibraryBookCount, total: userLibraryBookCount },
                  { key: 'runtime', label: 'Runtime', status: summary?.runtime_live_ok ? 'ready' : 'unknown', ready: Boolean(summary?.runtime_live_ok), detail: 'LLM / vector smoke', count: summary?.runtime_live_ok ? 1 : 0, total: 1 },
                  { key: 'chat', label: 'Chat', status: summary?.chat_matrix_ok ? 'ready' : 'unknown', ready: Boolean(summary?.chat_matrix_ok), detail: 'chat matrix', count: summary?.chat_matrix_ok ? 1 : 0, total: 1 },
                ]).map((item) => (
                  <div key={item.key} className={`llmwiki-rail-item ${item.ready ? 'ready' : item.status === 'stale' ? 'stale' : 'blocked'}`}>
                    <div className="llmwiki-rail-top">
                      <span>{item.label}</span>
                      {item.ready ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                    </div>
                    <strong>
                      {typeof item.count === 'number' && typeof item.total === 'number'
                        ? `${item.count.toLocaleString()} / ${item.total.toLocaleString()}`
                        : item.status}
                    </strong>
                    <p>{item.detail}</p>
                  </div>
                ))}
              </div>

              <div className="llmwiki-evidence-grid">
                <div>
                  <span>Report</span>
                  <strong>{llmwikiGeneratedAt}</strong>
                  <p>{llmwikiReport?.head_matches_current ? 'Current HEAD matched' : 'HEAD mismatch or missing report'}</p>
                </div>
                <div>
                  <span>Official Gold</span>
                  <strong>{Number(llmwikiMetrics.official_chunks_count ?? 0).toLocaleString()} chunks</strong>
                  <p>{Number(llmwikiMetrics.official_code_blocks ?? 0).toLocaleString()} code blocks / {Number(llmwikiMetrics.official_inline_figures ?? 0).toLocaleString()} figures</p>
                </div>
                <div>
                  <span>Figure Sidecar</span>
                  <strong>{Number(llmwikiMetrics.official_figure_sidecar_count ?? 0).toLocaleString()} assets</strong>
                  <p>{Number(llmwikiMetrics.official_figure_matched_section_count ?? 0).toLocaleString()} section links / {Number(llmwikiMetrics.official_figure_missing_relation_count ?? 0).toLocaleString()} missing</p>
                </div>
                <div>
                  <span>BM25 Metadata</span>
                  <strong>{Number(llmwikiMetrics.official_bm25_count ?? 0).toLocaleString()} rows</strong>
                  <p>{Number(llmwikiMetrics.official_bm25_metadata_missing_row_count ?? 0).toLocaleString()} metadata gaps</p>
                </div>
                <div>
                  <span>KO Localization</span>
                  <strong>{String(llmwikiMetrics.official_ko_localization_status || 'unknown')}</strong>
                  <p>{Number(llmwikiMetrics.official_ko_localization_failing_book_count ?? 0).toLocaleString()} English blockers / {Number(llmwikiMetrics.official_ko_localization_book_count ?? 0).toLocaleString()} books</p>
                </div>
                <div>
                  <span>Customer Master</span>
                  <strong>{Number(llmwikiMetrics.customer_master_source_count ?? 0).toLocaleString()} sources</strong>
                  <p>{Number(llmwikiMetrics.customer_master_section_count ?? 0).toLocaleString()} sections / {Number(llmwikiMetrics.customer_master_chunk_count ?? 0).toLocaleString()} chunks</p>
                </div>
                <div>
                  <span>Chat Modes</span>
                  <strong>{llmwikiModeContract.length || 2} modes</strong>
                  <p>{llmwikiModeContract.map((mode) => mode.label).join(' / ') || '학습 모드 / 운영 모드'}</p>
                </div>
                <div>
                  <span>Role Rehearsal</span>
                  <strong>{roleRehearsalReady ? `${roleRehearsalPassCount}/${roleRehearsalTotal} passing` : roleRehearsal?.status ?? 'Missing'}</strong>
                  <p>
                    Operator A {operatorRole?.pass ?? 0}/{operatorRole?.total ?? 0} · Learner B {learnerRole?.pass ?? 0}/{learnerRole?.total ?? 0}
                    {roleRehearsalReport?.stale ? ' · stale report' : ''}
                  </p>
                </div>
                <div>
                  <span>Validation Loop</span>
                  <strong>{validationLoopReady ? 'Loop Ready' : validationLoopStale ? 'Loop Stale' : validationLoop?.status ?? 'Missing'}</strong>
                  <p>{validationLoopGeneratedAt} · {validationLoopMetrics.completed_iterations ?? 0}/{validationLoopMetrics.requested_iterations ?? 0} iterations</p>
                </div>
                <div>
                  <span>Surya Boundary</span>
                  <strong>{suryaOptional ? 'Optional' : 'Check Required'}</strong>
                  <p>{suryaPolicy?.status ?? 'offline_allowed'} · embedder {validationLoopServices.embedding ? 'ready' : 'unknown'} · qdrant {validationLoopServices.qdrant ? 'ready' : 'unknown'}</p>
                </div>
              </div>
            </section>
            {developmentControl && (
              <section className="development-control-panel box-container">
                <div className="development-control-header">
                  <div>
                    <span className="vision-compare-eyebrow">Dev-Kugnus Product Scope</span>
                    <h2>Ops Console 제외 제품 고도화 보드</h2>
                    <p>
                      Studio, 문서 viewer, Library, Book Factory, 공식/고객 문서 파이프라인을 같은 readiness 계약으로 묶어 봅니다.
                    </p>
                  </div>
                  <div className={`development-ready-badge ${developmentControl.ready ? 'ready' : developmentControl.status === 'watch' ? 'watch' : 'blocked'}`}>
                    {developmentControl.ready ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                    <span>{developmentStatusLabel}</span>
                  </div>
                </div>

                <div className="development-summary-strip" aria-label="development control summary">
                  <div>
                    <span>Required</span>
                    <strong>
                      {developmentSummary?.required_ready_count ?? 0} / {developmentSummary?.required_surface_count ?? 0}
                    </strong>
                  </div>
                  <div>
                    <span>All Surfaces</span>
                    <strong>
                      {developmentSummary?.ready_count ?? 0} / {developmentSummary?.surface_count ?? developmentSurfaces.length}
                    </strong>
                  </div>
                  <div>
                    <span>Watch</span>
                    <strong>{developmentSummary?.watch_count ?? 0}</strong>
                  </div>
                  <div>
                    <span>Blocked</span>
                    <strong>{developmentSummary?.blocked_count ?? 0}</strong>
                  </div>
                </div>

                <div className="development-surface-grid">
                  {developmentSurfaces.map((surface) => (
                    <article key={surface.id} className={`development-surface-card ${surface.status}`}>
                      <div className="development-surface-top">
                        <span>{surface.required ? 'Required' : 'Watch lane'}</span>
                        {surface.ready ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                      </div>
                      <h3>{surface.title}</h3>
                      <p>{surface.acceptance}</p>
                      <div className="development-surface-evidence">
                        {surface.evidence.slice(0, 3).map((item) => (
                          <span key={`${surface.id}-${item}`}>{item}</span>
                        ))}
                      </div>
                      {surface.blockers.length > 0 ? (
                        <div className="development-surface-blocker">{surface.blockers[0]}</div>
                      ) : (
                        <div className="development-surface-next">{surface.next_action}</div>
                      )}
                      <a className="development-surface-link" href={surface.route}>
                        <span>Open surface</span>
                        <ExternalLink size={14} />
                      </a>
                    </article>
                  ))}
                </div>

                {developmentExcluded.length > 0 && (
                  <div className="development-excluded-note">
                    <span>Excluded lane</span>
                    <strong>{developmentExcluded.map((item) => item.title).join(', ')}</strong>
                    <p>{developmentExcluded.map((item) => item.reason).join(' · ')}</p>
                  </div>
                )}
              </section>
            )}
            {comparisonBook && (
              <section className="vision-compare box-container">
                <div className="vision-compare-header">
                  <div>
                    <span className="vision-compare-eyebrow">Viewer Compare</span>
                    <h2>같은 문서를 3안으로 비교해보기</h2>
                    <p>
                      같은 문서 하나를 기준으로, 어떤 viewer가 우리 위키 대백과의 중심이 되어야 하는지 바로 비교합니다.
                    </p>
                  </div>
                  <div className="vision-compare-book-picker" role="tablist" aria-label="comparison document picker">
                    {comparisonCandidates.map((book) => (
                      <button
                        key={book.book_slug}
                        type="button"
                        className={`vision-compare-book-chip ${comparisonBook.book_slug === book.book_slug ? 'active' : ''}`}
                        onClick={() => setComparisonBookSlug(book.book_slug)}
                      >
                        {book.title}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="vision-compare-book-meta">
                  <span>{comparisonBook.title}</span>
                  <span>{comparisonBook.section_count} sections</span>
                  <span className={playbookGradeBadgeClass(comparisonBook.grade)}>{normalizePlaybookGrade(comparisonBook.grade)}</span>
                  <span>{comparisonBook.book_slug.replace(/_/g, ' ')}</span>
                </div>
                <div className="vision-compare-grid">
                  {WIKI_VISION_MODES.map((mode) => {
                    const copy = mode.compare;
                    const isActive = visionMode === mode.id;
                    return (
                      <article key={mode.id} className={`vision-compare-card ${isActive ? 'active' : ''}`}>
                        <div className="vision-compare-card-top">
                          <span className="vision-compare-card-eyebrow">{copy.eyebrow}</span>
                          <span className="vision-compare-card-mode">{mode.label}</span>
                        </div>
                        <h3>{copy.title}</h3>
                        <p className="vision-compare-card-summary">{mode.library.summary}</p>
                        <ul className="vision-compare-bullets">
                          {copy.bullets.map((bullet) => (
                            <li key={bullet}>{bullet}</li>
                          ))}
                        </ul>
                        <div className="vision-compare-signals">
                          <span>본문 {mode.id === 'atlas_canvas' ? '강조' : mode.id === 'guided_tour' ? '요약 후 이동' : '주제의 일부'}</span>
                          <span>절차 {mode.id === 'guided_tour' ? '전면' : '보조'}</span>
                          <span>figure {mode.id === 'atlas_canvas' ? '같은 시야' : mode.id === 'encyclopedia_world' ? '맥락 자산' : '선택 노출'}</span>
                        </div>
                        {mode.id === 'atlas_canvas' && (
                          <div className="vision-compare-mini-preview">
                            <div className="vision-compare-mini-kicker">Reading core + side context</div>
                            <strong>{comparisonBook.title}</strong>
                            <span>본문을 중심으로 연결 문서와 figure를 옆에서 확장합니다.</span>
                            <div className="vision-compare-inline-list">
                              {comparisonFigureEntries.slice(0, 2).map((figure) => (
                                <span key={figure.key}>{figure.kind}</span>
                              ))}
                              {comparisonLinkedDocs.slice(0, 1).map((book) => (
                                <span key={book.book_slug}>{book.title}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {mode.id === 'guided_tour' && (
                          <div className="vision-compare-mini-preview vision-compare-mini-route">
                            <div className="vision-compare-mini-kicker">Answer -&gt; next route</div>
                            <div className="vision-compare-route-step">
                              <strong>Start Here</strong>
                              <span>{comparisonBook.title}</span>
                            </div>
                            <div className="vision-compare-route-step">
                              <strong>Then Open</strong>
                              <span>{comparisonLinkedDocs[0]?.title ?? '연결 문서 1개'}</span>
                            </div>
                            <div className="vision-compare-route-step">
                              <strong>Verify</strong>
                              <span>{comparisonLinkedDocs[1]?.title ?? '검증 문서 1개'}</span>
                            </div>
                          </div>
                        )}
                        {mode.id === 'encyclopedia_world' && (
                          <div className="vision-compare-mini-preview vision-compare-mini-world">
                            <div className="vision-compare-mini-kicker">Topic world + connected knowledge</div>
                            <strong>{comparisonBook.title}</strong>
                            <div className="vision-compare-inline-list">
                              {comparisonWorldKeywords.map((keyword) => (
                                <span key={keyword}>{keyword}</span>
                              ))}
                            </div>
                            <span>이 문서를 주제 세계의 한 노드로 보고 연결 키워드를 따라 탐험합니다.</span>
                          </div>
                        )}
                        <button
                          type="button"
                          className="vision-compare-open-btn"
                          onClick={() => {
                            setVisionMode(mode.id);
                            setBookViewer(comparisonBook);
                          }}
                        >
                          {copy.cta}
                        </button>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}
            <section className="wiki-vision-lab box-container">
              <div className="wiki-vision-lab-header">
                <div>
                  <span className="wiki-vision-eyebrow">{visionMode === 'guided_tour' ? 'Guided Tour' : 'Wiki Vision Lab'}</span>
                  <h2>{visionMode === 'guided_tour' ? 'Guided Tour Active' : '위키 대백과 3안'}</h2>
                  <p>{activeVision.library.summary}</p>
                </div>
                <div className="wiki-vision-focus">{visionMode === 'guided_tour' ? 'Active Route' : activeVision.library.focus}</div>
              </div>
              {visionMode === 'guided_tour' ? (
                <div className="wiki-vision-active">
                  <div className="wiki-vision-active-title">질문에서 문서 투어로 바로 이어지는 모드</div>
                  <p className="wiki-vision-active-copy">Start Here와 Then Open만 먼저 열고, 나머지 위키는 진행 중에 따라붙게 정리합니다.</p>
                </div>
              ) : (
                <div className="wiki-vision-grid">
                  {WIKI_VISION_MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      className={`wiki-vision-card ${visionMode === mode.id ? 'active' : ''}`}
                      onClick={() => setVisionMode(mode.id)}
                    >
                      <span className="wiki-vision-card-eyebrow">{mode.library.eyebrow}</span>
                      <strong>{mode.label}</strong>
                      <span>{mode.library.summary}</span>
                    </button>
                  ))}
                </div>
              )}
            </section>

            {operationalWikiBooks.length > 0 && (
              <section className="operational-shelf box-container">
                <div className="operational-shelf-header">
                  <div>
                    <span className="operational-shelf-eyebrow">{visionMode === 'guided_tour' ? 'Start Tour' : visionMode === 'atlas_canvas' ? 'Atlas Canvas' : 'Operational Wiki'}</span>
                    <h2>{visionMode === 'guided_tour' ? '운영 위키 투어 시작점' : visionMode === 'atlas_canvas' ? '운영 위키 아틀라스' : '바로 읽을 수 있는 운영 위키'}</h2>
                    <p>
                      {visionMode === 'guided_tour'
                        ? '가장 먼저 열 문서와 이어서 볼 문서를 이 순서대로 엽니다.'
                        : visionMode === 'atlas_canvas'
                          ? '문서 본문, 연결 경로, 맥락 문서를 한 화면 감각으로 읽기 위한 atlas shelf 입니다.'
                          : '지금 제품 표면에서 바로 여는 핵심 운영 문서 묶음입니다.'}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="operational-shelf-link"
                    onClick={() => openMetricPopover('wikiRuntime')}
                  >
                    전체 {approvedWikiRuntimeBooks.toLocaleString()}권 보기
                  </button>
                </div>
                {visionMode === 'atlas_canvas' && (
                  <div className="operational-atlas-grid">
                    {atlasReadingBooks.length > 0 && (
                      <div className="operational-atlas-lane">
                        <div className="operational-atlas-lane-label">Reading Spine</div>
                        {atlasReadingBooks.map((book, index) => (
                          <button
                            key={`atlas-reading-${book.book_slug}`}
                            type="button"
                            className="operational-atlas-card"
                            onClick={() => setBookViewer(book)}
                          >
                            <div className="operational-atlas-meta-row">
                              <span className="operational-atlas-kind">Document</span>
                              <span className="operational-atlas-intent">Read</span>
                            </div>
                            <span className="operational-atlas-kicker">Core {index + 1}</span>
                            <strong>{book.title}</strong>
                            <span>{book.book_slug.replace(/_/g, ' ')}</span>
                            <span className="operational-atlas-why">아틀라스의 중심에서 먼저 읽을 문서</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {atlasRelationBooks.length > 0 && (
                      <div className="operational-atlas-lane">
                        <div className="operational-atlas-lane-label">Connected Paths</div>
                        {atlasRelationBooks.map((book, index) => (
                          <button
                            key={`atlas-relation-${book.book_slug}`}
                            type="button"
                            className="operational-atlas-card operational-atlas-card-relation"
                            onClick={() => setBookViewer(book)}
                          >
                            <div className="operational-atlas-meta-row">
                              <span className="operational-atlas-kind">Linked Doc</span>
                              <span className="operational-atlas-intent">Open</span>
                            </div>
                            <span className="operational-atlas-kicker">Path {index + 1}</span>
                            <strong>{book.title}</strong>
                            <span>{book.book_slug.replace(/_/g, ' ')}</span>
                            <span className="operational-atlas-why">핵심 문서와 연결되는 확장 경로</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {atlasContextBooks.length > 0 && (
                      <div className="operational-atlas-lane">
                        <div className="operational-atlas-lane-label">Visual Memory</div>
                        {atlasContextBooks.map((book, index) => (
                          <button
                            key={`atlas-context-${book.book_slug}`}
                            type="button"
                            className="operational-atlas-card operational-atlas-card-context"
                            onClick={() => setBookViewer(book)}
                          >
                            <div className="operational-atlas-meta-row">
                              <span className="operational-atlas-kind">Context</span>
                              <span className="operational-atlas-intent">Scan</span>
                            </div>
                            <span className="operational-atlas-kicker">Context {index + 1}</span>
                            <strong>{book.title}</strong>
                            <span>{book.book_slug.replace(/_/g, ' ')}</span>
                            <span className="operational-atlas-why">주변 맥락과 운영 배경을 채우는 층</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {visionMode === 'guided_tour' && (
                  <div className="operational-tour-grid">
                    {guidedTourShelfSteps.length > 0 && (
                      <div className="operational-tour-lane">
                        <div className="operational-tour-lane-label">Start Here</div>
                        {guidedTourShelfSteps.map((book: LibraryBook, index: number) => (
                          <button
                            key={`guided-shelf-step-${book.book_slug}`}
                            type="button"
                            className="operational-tour-card"
                            onClick={() => setBookViewer(book)}
                          >
                            <span className="operational-tour-kicker">Step {index + 1}</span>
                            <strong>{book.title}</strong>
                            <span>{book.book_slug.replace(/_/g, ' ')}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {guidedTourShelfDocs.length > 0 && (
                      <div className="operational-tour-lane">
                        <div className="operational-tour-lane-label">Then Open</div>
                        {guidedTourShelfDocs.map((book: LibraryBook, index: number) => (
                          <button
                            key={`guided-shelf-doc-${book.book_slug}`}
                            type="button"
                            className="operational-tour-card operational-tour-card-doc"
                            onClick={() => setBookViewer(book)}
                          >
                            <span className="operational-tour-kicker">Document {index + 1}</span>
                            <strong>{book.title}</strong>
                            <span>{book.book_slug.replace(/_/g, ' ')}</span>
                            <span className="operational-tour-arrow">
                              <ArrowRight size={14} />
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {visionMode !== 'guided_tour' && visionMode !== 'atlas_canvas' && (
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
                        </button>
                        <OfficialSourcePopover record={book} />
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}

            {allOperationalWikiBooks.length > 0 && visionMode !== 'guided_tour' && (
              <section className="operational-library box-container">
                <div className="operational-library-header">
                  <div>
                    <span className="operational-library-eyebrow">Operational Library</span>
                    <h2>운영 위키 {approvedWikiRuntimeBooks.toLocaleString()}권</h2>
                  </div>
                  <span className="operational-library-count">{approvedWikiRuntimeBooks.toLocaleString()} books</span>
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
                      </button>
                      <OfficialSourcePopover record={book} />
                    </article>
                  ))}
                </div>
              </section>
            )}

            {releaseCandidateFreeze?.exists && visionMode !== 'guided_tour' && (
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

            {(gate || hasMetricSourceDrift) && visionMode !== 'guided_tour' && (
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

            {visionMode !== 'guided_tour' && (
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
              accept={CUSTOMER_PACK_UPLOAD_ACCEPT}
              onChange={handleUpload}
            />

            <section className="pipeline-section box-container factory-workbench-section">
              <div className="factory-workbench-top">
                <div className="factory-workbench-headline">
                  <span className="factory-hub-eyebrow">Production Surface</span>
                  <div className="factory-workbench-title-row">
                    <h2>Book Factory</h2>
                    <span className="factory-workbench-title-tag">
                      {factoryLane === 'tools' ? 'Book Factory Pipeline' : 'User Docs Upload'}
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
                        className={`pipeline-step pipeline-step--${step.badge.toLowerCase()} ${index <= toolsPipelineState.completedIndex ? 'completed' : ''
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
                  <div className="pipeline-step pipeline-step--bronze">
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

                  <div className="pipeline-step pipeline-step--silver">
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

                  <div className="pipeline-step pipeline-step--gold">
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

                  <div className="pipeline-step pipeline-step--judge">
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
                              {displayCustomerDocumentTitle(draft)}
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

            {customDocumentBooks.length > 0 && (
              <section className="draft-management custom-material-section box-container">
                <div className="section-header">
                  <div>
                    <h2>커스텀 문서 ({customDocumentCount})</h2>
                    <p className="text-muted">이번 고객맞춤 플레이북에 사용하는 재료 문서만 모아둔 source-of-truth 버킷입니다.</p>
                  </div>
                </div>
                <div className="draft-grid">
                  {customDocumentBooks.map((book) => {
                    const canOpenViewer = Boolean(book.viewer_path);
                    const meta = customDocumentMeta(book);
                    const displayTitle = displayCustomerDocumentTitle(book);
                    const cardBody = (
                      <>
                        <div className="draft-card-top">
                          <span className="draft-type">커스텀문서</span>
                          <span className="draft-status-badge status-cyan">
                            {book.custom_document_kind_label || '재료'}
                          </span>
                        </div>
                        <h4 className="draft-title">{displayTitle}</h4>
                        {book.custom_document_description ? (
                          <p className="custom-material-description">{book.custom_document_description}</p>
                        ) : null}
                        <div className="draft-meta">
                          {meta.slice(1, 4).map((item) => (
                            <span key={`${book.book_slug}:${item}`}>{item}</span>
                          ))}
                        </div>
                        {meta.length > 0 && (
                          <div className="preview-chip-row">
                            {meta.map((item) => (
                              <span key={`${book.book_slug}:chip:${item}`} className="preview-chip">{item}</span>
                            ))}
                          </div>
                        )}
                        <div className="custom-material-path">
                          원본 비노출 · 플레이북 생산 전용 슬롯
                        </div>
                      </>
                    );
                    return canOpenViewer ? (
                      <button
                        type="button"
                        className="draft-card custom-material-card custom-material-card--openable"
                        key={book.book_slug}
                        onClick={() => setBookViewer(book)}
                      >
                        {cardBody}
                      </button>
                    ) : (
                      <div className="draft-card custom-material-card" key={book.book_slug}>
                        {cardBody}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

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
                          <h2>Tools Docs Upload</h2>
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
                      {userLibraryBooks.map((book) => {
                        const displayTitle = displayCustomerDocumentTitle(book);
                        return (
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
                            <h4 className="draft-title">{displayTitle}</h4>
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
                        );
                      })}
                    </div>
                  </section>
                )}

                {drafts.length > 0 && (
                  <section className="draft-management box-container">
                    <div className="section-header">
                      <h2>Uploaded Drafts ({drafts.length})</h2>
                    </div>
                    <div className="draft-grid">
                      {drafts.map((draft) => {
                        const displayTitle = displayCustomerDocumentTitle(draft);
                        return (
                          <div className="draft-card" key={draft.draft_id} onClick={() => openPreview(draft)} style={{ cursor: 'pointer' }}>
                            <div className="draft-card-top">
                              <FileText size={18} className="draft-file-icon" />
                              <span className={`draft-status-badge status-${statusColor(draft.status)}`}>
                                {draft.status}
                              </span>
                            </div>
                            <h4 className="draft-title">{displayTitle}</h4>
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
                                onClick={(e) => { e.stopPropagation(); handleDelete(draft.draft_id, displayTitle, true); }}
                                disabled={deletingId === draft.draft_id}
                                title="Delete draft"
                              >
                                {deletingId === draft.draft_id ? <Loader2 size={14} className="spin-icon" /> : <Trash2 size={14} />}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        )}
      </main>

      {/* Preview Popover */}
      {previewDraft && (
        <div className="preview-overlay" onClick={closePreview}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{displayCustomerDocumentTitle(previewDraft)}</h3>
                <div className="preview-header-meta">
                  <span className={`draft-status-badge status-${statusColor(previewDraft.status)}`}>{previewDraft.status}</span>
                  <span>{previewDraft.source_type.toUpperCase()}</span>
                  {previewDraft.uploaded_byte_size ? <span>{formatBytes(previewDraft.uploaded_byte_size)}</span> : null}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="preview-delete-btn"
                  onClick={async () => { const ok = await handleDelete(previewDraft.draft_id, displayCustomerDocumentTitle(previewDraft), true); if (ok) closePreview(); }}
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
                  title={displayCustomerDocumentTitle(previewDraft)}
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
                            <span className="metric-book-title">{displayCustomerDocumentTitle(book)}</span>
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

      {/* Book Viewer Popover */}
      {bookViewer && (
        <div className="preview-overlay" onClick={() => setBookViewer(null)}>
          <div className="preview-popover" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <h3>{displayCustomerDocumentTitle(bookViewer)}</h3>
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
              {visionMode === 'atlas_canvas' && (
                <aside className="book-preview-atlas-sidebar">
                  <div className="book-preview-atlas-lane">
                    <div className="book-preview-atlas-label">Reading Spine</div>
                    <div className="book-preview-atlas-card">
                      <div className="book-preview-atlas-meta-row">
                        <span className="book-preview-atlas-kind">Document</span>
                        <span className="book-preview-atlas-intent">Read</span>
                      </div>
                      <strong>{displayCustomerDocumentTitle(bookViewer)}</strong>
                      <span>{bookViewer.book_slug.replace(/_/g, ' ')}</span>
                    </div>
                  </div>
                  <div className="book-preview-atlas-lane">
                    <div className="book-preview-atlas-label">Visual Memory</div>
                    {atlasBookFigureEntries.length > 0 ? (
                      atlasBookFigureEntries.map((figure, index) => (
                        <a
                          key={`${figure.key}-${index}`}
                          className={`book-preview-atlas-card book-preview-atlas-card-link${figure.isCluster ? ' book-preview-atlas-card-cluster' : ''}`}
                          href={toRuntimeUrl(figure.href)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <div className="book-preview-atlas-meta-row">
                            <span className="book-preview-atlas-kind">{figure.kind}</span>
                            <span className="book-preview-atlas-intent">{figure.intent}</span>
                          </div>
                          {typeof figure.count === 'number' ? (
                            <span className="book-preview-atlas-count">{figure.count} linked visuals</span>
                          ) : null}
                          {figure.thumbUrl ? (
                            <div
                              className="book-preview-atlas-thumb"
                              style={{ backgroundImage: `url(${figure.thumbUrl})` }}
                              aria-hidden="true"
                            />
                          ) : null}
                          <strong>{figure.title}</strong>
                          <span>{figure.subtitle}</span>
                          <span className="book-preview-atlas-why">{figure.why}</span>
                        </a>
                      ))
                    ) : (
                      <div className="book-preview-atlas-card book-preview-atlas-card-muted">
                        <strong>Figure 없음</strong>
                        <span>현재 book에 연결된 figure asset이 아직 없습니다.</span>
                      </div>
                    )}
                  </div>
                </aside>
              )}
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
