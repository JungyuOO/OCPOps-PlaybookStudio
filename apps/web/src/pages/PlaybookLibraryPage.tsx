import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  Clock3,
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
  Wrench,
  X,
} from 'lucide-react';
import gsap from 'gsap';
import './PlaybookLibraryPage.css';
import AppHeader from '../components/AppHeader';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import { buildDocumentReaderImageState, documentReaderAssetCaption } from '../lib/documentReaderAssets';
import {
  DOCUMENT_INGEST_UPLOAD_ACCEPT,
  type CustomerPackDraft,
  type CorpusChunkViewerResponse,
  type BuyerPacket,
  type DataControlRoomResponse,
  type HiddenLibraryBook,
  type GoldBuildRun,
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
  type DocumentReaderAsset,
  type DocumentReaderChunk,
  type DocumentReaderDocument,
  type DocumentTopology,
  type DocumentTopologyScopeResponse,
  type RuntimeHealthResponse,
  type UploadIngestResponse,
  type UploadIngestStreamEvent,
  recheckUploadDocumentQuality,
  repairUploadCodeBlocks,
  retryUploadDocumentTopology,
  retryUploadDocumentIndex,
  uploadDocumentIngestionStream,
  loadDataControlRoom,
  loadDataControlRoomChunks,
  listCustomerPackDrafts,
  deleteCustomerPackDraft,
  loadCustomerPackBook,
  loadRepositoryFavorites,
  loadRepositoryUnanswered,
  loadDocumentRepositories,
  loadDocumentReader,
  loadDocumentTopology,
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
  setRuntimeIdentityUser,
  toRuntimeUrl,
  formatBytes,
} from '../lib/runtimeApi';
import { listOcpProfiles, type OcpConnection } from '../lib/opsConsoleApi';
import {
  clusterConnectionStatusLabel,
  clusterProfileName,
  normalizeClusterConnectionStatus,
  type ClusterConnectionStatus,
} from '../lib/clusterProfile';
import { useGlobalTheme } from '../lib/globalTheme';
import { ROUTES } from '../routing/routes';

type PipelineStage =
  | 'idle'
  | 'received'
  | 'source_stored'
  | 'parsed'
  | 'chunked'
  | 'persisting'
  | 'persisted'
  | 'indexing'
  | 'indexed'
  | 'index_deferred'
  | 'gold_build'
  | 'topology_build'
  | 'topology_ready'
  | 'topology_deferred'
  | 'topology_failed'
  | 'done'
  | 'error';
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

interface PipelineVisualState {
  activeIndex: number;
  completedIndex: number;
  deferredIndex?: number;
  errorIndex?: number;
}

interface UploadPipelineLedgerEvent {
  event: string;
  pipelineStage: 'bronze' | 'silver' | 'gold' | 'judge' | 'topology' | string;
  status: 'pending' | 'running' | 'completed' | 'deferred' | 'failed' | string;
  occurredAt: string;
  data: Record<string, unknown>;
}

interface UploadEventTraceItem {
  id: string;
  stage: string;
  label: string;
  detail: string;
  time: string;
  occurredAt?: string;
  elapsedMs: number;
  tone: 'info' | 'success' | 'warn' | 'error';
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

function documentReaderSectionId(chunk: DocumentReaderChunk, index: number): string {
  return `reader-section-${chunk.chunk_id || chunk.chunk_key || index}`.replace(/[^A-Za-z0-9_-]/g, '-');
}

function documentReaderChunkMarkdown(chunk: DocumentReaderChunk): string {
  return String(chunk.markdown || chunk.text || '').trim();
}

function documentReaderChunkTitle(chunk: DocumentReaderChunk, index: number): string {
  return (
    String(chunk.heading_title || '').trim()
    || String(chunk.section_path.at(-1) || '').trim()
    || String(chunk.source_anchor || '').trim()
    || `섹션 ${index + 1}`
  );
}

function markdownStartsWithHeading(markdown: string): boolean {
  return /^\s{0,3}#{1,6}\s+\S/.test(markdown);
}

function DocumentReaderMarkdown({
  markdown,
  assetById,
}: {
  markdown: string;
  assetById: Map<string, DocumentReaderAsset>;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url, key) => (key === 'src' && url.startsWith('asset://') ? url : defaultUrlTransform(url))}
      components={{
        img: (props: any) => {
          const { node: _node, src, alt, ...imgProps } = props as React.ComponentPropsWithoutRef<'img'> & {
            node?: unknown;
          };
          const imageState = buildDocumentReaderImageState({ src, alt, assetById });
          if (imageState.kind === 'reader-asset') {
            return (
              <figure className="document-reader-asset-figure">
                <img src={imageState.src} alt={imageState.alt} loading="lazy" />
                <figcaption>
                  <span>{imageState.caption}</span>
                  {imageState.pageNumber ? <em>page {imageState.pageNumber}</em> : null}
                </figcaption>
              </figure>
            );
          }
          if (imageState.kind === 'missing-file' || imageState.kind === 'missing-asset') {
            return <span className="document-reader-missing-asset">{imageState.message}</span>;
          }
          return <img {...imgProps} src={imageState.src} alt={imageState.alt} loading="lazy" />;
        },
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}

function documentReaderScopeLabel(scope: string, fallback: string): string {
  switch (scope) {
    case 'official_docs':
      return 'OCP 자료';
    case 'study_docs':
      return '고객사 문서';
    case 'user_upload':
      return '내 업로드';
    default:
      return fallback || scope || '문서';
  }
}

function topologyStateLabel(state?: string): string {
  switch (state) {
    case 'ready':
      return '연결 준비';
    case 'needs_review':
      return '검수 필요';
    default:
      return '상태 미확인';
  }
}

function topologyRelationLabel(relation: string): string {
  switch (relation) {
    case 'CONTAINS':
      return '포함';
    case 'MENTIONS':
      return '언급';
    case 'VISUALIZES':
      return '시각화';
    case 'VALIDATED_BY':
      return '검증';
    default:
      return relation || '관계';
  }
}

function topologyNodeKindLabel(kind: string): string {
  switch (kind) {
    case 'concept':
      return '개념';
    case 'command':
      return '명령어';
    case 'asset':
      return '이미지';
    case 'section':
      return '섹션';
    case 'chunk':
      return '조각';
    case 'judge':
      return '검증';
    default:
      return kind || '노드';
  }
}

function topologyEvidenceLabel(evidence: Array<{ chunk_id?: string; asset_id?: string; page_number?: number; quote?: string }> = []): string {
  const first = evidence[0];
  if (!first) {
    return '근거 없음';
  }
  const location = [
    first.page_number ? `p.${first.page_number}` : '',
    first.chunk_id ? 'chunk' : '',
    first.asset_id ? 'image' : '',
  ].filter(Boolean).join(' · ');
  const quote = String(first.quote || '').trim();
  return [location, quote].filter(Boolean).join(' — ') || '근거 있음';
}

function DocumentReaderBookView({
  payload,
  loadingMore,
  onLoadMore,
}: {
  payload: DocumentReaderDocument;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  const readableSections = payload.chunks
    .map((chunk, index) => ({
      chunk,
      index,
      id: documentReaderSectionId(chunk, index),
      title: documentReaderChunkTitle(chunk, index),
      markdown: documentReaderChunkMarkdown(chunk),
    }))
    .filter((section) => section.markdown);
  const outlineSections = readableSections
    .filter((section) => section.title)
    .slice(0, 24);
  const assetById = new Map((payload.assets ?? []).map((asset) => [asset.asset_id, asset]));
  const referencedAssetIds = new Set<string>();
  const markdownSources = readableSections.length > 0
    ? readableSections.map((section) => section.markdown)
    : payload.markdown ? [payload.markdown] : [];
  for (const markdown of markdownSources) {
    for (const match of markdown.matchAll(/asset:\/\/([A-Za-z0-9-]+)/g)) {
      referencedAssetIds.add(match[1]);
    }
  }
  const unreferencedAssets = (payload.assets ?? []).filter((asset) => !referencedAssetIds.has(asset.asset_id));
  const topology = payload.topology;
  const topologySummary = topology?.summary;
  const topologyConcepts = (topology?.nodes ?? []).filter((node) => node.kind === 'concept').slice(0, 8);
  const topologyCommands = (topology?.nodes ?? []).filter((node) => node.kind === 'command').slice(0, 4);
  const topologyAssets = (topology?.nodes ?? []).filter((node) => node.kind === 'asset').slice(0, 4);
  const topologyEdges = (topology?.edges ?? []).filter((edge) => edge.relation !== 'CONTAINS').slice(0, 6);
  const topologyEvidenceEdges = (topology?.edges ?? []).filter((edge) => edge.relation !== 'CONTAINS').slice(0, 12);
  const topologyHiddenEdgeCount = Math.max(0, (topology?.edges ?? []).filter((edge) => edge.relation !== 'CONTAINS').length - topologyEvidenceEdges.length);
  const topologyHiddenNodeCount = Math.max(0, (topology?.nodes ?? []).length - (topologyConcepts.length + topologyCommands.length + topologyAssets.length));

  return (
    <div className="document-reader-book-shell">
      <aside className="document-reader-toc" aria-label="문서 목차">
        <span className="document-reader-toc-label">목차</span>
        <nav>
          {topology ? (
            <a href="#reader-topology-snapshot">지식 연결 스냅샷</a>
          ) : null}
          {outlineSections.length > 0 ? (
            outlineSections.map((section) => (
              <a key={section.id} href={`#${section.id}`}>
                {section.title}
              </a>
            ))
          ) : (
            <em>목차 없음</em>
          )}
        </nav>
        {topology ? (
          <section className="document-reader-topology-panel" aria-label="문서 지식 연결">
            <div className="document-reader-topology-head">
              <span>지식 연결</span>
              <strong>{topologyStateLabel(topologySummary?.state)}</strong>
            </div>
            <div className="document-reader-topology-metrics">
              <span><b>{Number(topologySummary?.node_count || 0).toLocaleString()}</b> 노드</span>
              <span><b>{Number(topologySummary?.edge_count || 0).toLocaleString()}</b> 관계</span>
              <span><b>{Number(topologySummary?.concept_count || 0).toLocaleString()}</b> 개념</span>
              <span><b>{Number(topologySummary?.command_count || 0).toLocaleString()}</b> 명령어</span>
            </div>
            {topologySummary?.partial ? (
              <p className="document-reader-topology-note">부분 지식망입니다. 저장 스냅샷은 전체 문서 기준만 재사용합니다.</p>
            ) : (
              <p className="document-reader-topology-note">저장된 전체 문서 스냅샷 기준입니다.</p>
            )}
            {(topologySummary?.blockers ?? []).length > 0 ? (
              <div className="document-reader-topology-blockers">
                {(topologySummary?.blockers ?? []).slice(0, 3).map((blocker) => (
                  <span key={blocker}>{blocker}</span>
                ))}
              </div>
            ) : null}
            {topologyConcepts.length > 0 ? (
              <div className="document-reader-topology-list">
                <span>주요 개념</span>
                {topologyConcepts.map((node) => (
                  <em key={node.id}>{node.label}</em>
                ))}
              </div>
            ) : null}
            {topologyCommands.length > 0 ? (
              <div className="document-reader-topology-list">
                <span>명령어</span>
                {topologyCommands.map((node) => (
                  <code key={node.id}>{node.label}</code>
                ))}
              </div>
            ) : null}
            {topologyEdges.length > 0 ? (
              <div className="document-reader-topology-edges">
                <span>근거 관계</span>
                {topologyEdges.map((edge) => {
                  const targetNode = topology.nodes.find((node) => node.id === edge.target);
                  const sourceNode = topology.nodes.find((node) => node.id === edge.source);
                  return (
                    <div key={edge.id}>
                      <strong>{topologyRelationLabel(edge.relation)}</strong>
                      <p>
                        {sourceNode ? `${topologyNodeKindLabel(sourceNode.kind)}: ${sourceNode.label}` : edge.source}
                        {' → '}
                        {targetNode ? `${topologyNodeKindLabel(targetNode.kind)}: ${targetNode.label}` : edge.target}
                      </p>
                      <small>{topologyEvidenceLabel(edge.evidence)}</small>
                    </div>
                  );
                })}
              </div>
            ) : null}
            {topologyAssets.length > 0 ? (
              <div className="document-reader-topology-list">
                <span>이미지 근거</span>
                {topologyAssets.map((node) => (
                  <em key={node.id}>{node.label}</em>
                ))}
              </div>
            ) : null}
          </section>
        ) : null}
      </aside>
      <article className="document-reader-book">
        <div className="document-reader-book-lede">
          <span>문서 본문</span>
          <strong>{payload.title || payload.filename}</strong>
          <p>
            {payload.total_chunks.toLocaleString()}개 조각 중 {payload.chunks.length.toLocaleString()}개를 불러왔습니다.
            {payload.assets?.length ? ` 원본문서 이미지 ${payload.assets.length.toLocaleString()}개가 함께 연결됐습니다.` : ''}
            {payload.markdown_truncated ? ' 긴 문서는 아래에서 이어서 불러옵니다.' : ''}
          </p>
        </div>
        {topology ? (
          <section id="reader-topology-snapshot" className="document-reader-section document-reader-topology-snapshot">
            <div className="document-reader-topology-snapshot-head">
              <div>
                <span>지식 연결 스냅샷</span>
                <h2>문서가 만드는 운영 지식망</h2>
                <p>
                  schema {topology.schema_version || '-'} · {topologyStateLabel(topologySummary?.state)}
                  {topology.snapshot_id ? ` · 스냅샷 ${topology.snapshot_id.slice(0, 8)}` : ''}
                </p>
              </div>
              <strong className={topologySummary?.state === 'ready' ? 'ok' : 'warning'}>
                {Number(topologySummary?.node_count || 0).toLocaleString()} nodes / {Number(topologySummary?.edge_count || 0).toLocaleString()} edges
              </strong>
            </div>
            <div className="document-reader-topology-snapshot-grid">
              <span><b>{Number(topologySummary?.concept_count || 0).toLocaleString()}</b> 개념</span>
              <span><b>{Number(topologySummary?.command_count || 0).toLocaleString()}</b> 명령어</span>
              <span><b>{Number(topologySummary?.asset_count || 0).toLocaleString()}</b> 이미지</span>
              <span><b>{Number(topologySummary?.missing_asset_description_count || 0).toLocaleString()}</b> 이미지 설명 누락</span>
            </div>
            {(topologySummary?.blockers ?? []).length > 0 ? (
              <div className="document-reader-topology-snapshot-blockers">
                {(topologySummary?.blockers ?? []).map((blocker) => (
                  <span key={blocker}>{blocker}</span>
                ))}
              </div>
            ) : null}
            {topologyEvidenceEdges.length > 0 ? (
              <div className="document-reader-topology-snapshot-evidence">
                <div className="document-reader-topology-snapshot-subhead">
                  <strong>근거 관계</strong>
                  <span>{topologyHiddenEdgeCount > 0 ? `${topologyHiddenEdgeCount.toLocaleString()}개 관계 더 있음` : '전체 주요 관계 표시'}</span>
                </div>
                {topologyEvidenceEdges.map((edge) => {
                  const targetNode = topology.nodes.find((node) => node.id === edge.target);
                  const sourceNode = topology.nodes.find((node) => node.id === edge.source);
                  const firstChunkId = edge.evidence.find((item) => item.chunk_id)?.chunk_id;
                  const targetSection = firstChunkId
                    ? readableSections.find((section) => section.chunk.chunk_id === firstChunkId)
                    : null;
                  return (
                    <a
                      key={edge.id}
                      href={targetSection ? `#${targetSection.id}` : undefined}
                      className="document-reader-topology-snapshot-edge"
                    >
                      <span>{topologyRelationLabel(edge.relation)}</span>
                      <strong>
                        {sourceNode ? sourceNode.label : edge.source}
                        {' -> '}
                        {targetNode ? targetNode.label : edge.target}
                      </strong>
                      <small>{topologyEvidenceLabel(edge.evidence)}</small>
                    </a>
                  );
                })}
              </div>
            ) : null}
            {topologyHiddenNodeCount > 0 ? (
              <p className="document-reader-topology-note">
                미리보기에는 주요 노드만 표시합니다. 전체 노드 {Number(topologySummary?.node_count || 0).toLocaleString()}개는 스냅샷 근거에 저장되어 검색에서 함께 사용됩니다.
              </p>
            ) : null}
          </section>
        ) : null}
        {readableSections.length > 0 ? (
          readableSections.map((section) => (
            <section key={section.id} id={section.id} className="document-reader-section">
              <div className="document-reader-section-meta">
                <span>#{section.chunk.ordinal || section.index + 1}</span>
                {section.chunk.section_path.length > 0 ? <span>{section.chunk.section_path.join(' / ')}</span> : null}
                {section.chunk.token_count ? <span>{section.chunk.token_count.toLocaleString()} tokens</span> : null}
              </div>
              {!markdownStartsWithHeading(section.markdown) ? <h2>{section.title}</h2> : null}
              <div className="document-reader-markdown">
                <DocumentReaderMarkdown markdown={section.markdown} assetById={assetById} />
              </div>
            </section>
          ))
        ) : payload.markdown ? (
          <section className="document-reader-section">
            <div className="document-reader-markdown">
              <DocumentReaderMarkdown markdown={payload.markdown} assetById={assetById} />
            </div>
          </section>
        ) : (
          <div className="preview-no-sections">표시할 문서 본문이 없습니다.</div>
        )}
        {unreferencedAssets.length > 0 ? (
          <section className="document-reader-section document-reader-asset-gallery">
            <div className="document-reader-section-meta">
              <span>원본문서 이미지</span>
              <span>{unreferencedAssets.length.toLocaleString()}개</span>
            </div>
            <div className="document-reader-asset-grid">
              {unreferencedAssets.map((asset) => (
                <figure className="document-reader-asset-figure" key={asset.asset_id}>
                  {asset.data_url ? (
                    <img src={asset.data_url} alt={documentReaderAssetCaption(asset)} loading="lazy" />
                  ) : (
                    <div className="document-reader-missing-asset">
                      이미지 파일을 불러올 수 없습니다.
                    </div>
                  )}
                  <figcaption>
                    <span>{documentReaderAssetCaption(asset)}</span>
                    {asset.page_number ? <em>page {asset.page_number}</em> : null}
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>
        ) : null}
        {payload.has_more ? (
          <button
            type="button"
            className="document-reader-load-more"
            disabled={loadingMore}
            onClick={onLoadMore}
          >
            {loadingMore ? '이어지는 본문을 불러오는 중...' : '이어지는 본문 더 불러오기'}
          </button>
        ) : (
          <div className="document-reader-end">문서 끝입니다.</div>
        )}
        <details className="document-reader-chunk-details">
          <summary>검수용 chunk 정보</summary>
          <div className="chunk-card-list">
            {payload.chunks.map((chunk, index) => (
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
                  {documentReaderChunkTitle(chunk, index)}
                </strong>
                {chunk.section_path.length > 0 ? (
                  <div className="chunk-card-path">{chunk.section_path.join(' › ')}</div>
                ) : null}
                <pre className="chunk-card-text">{chunk.markdown || chunk.text}</pre>
              </article>
            ))}
          </div>
        </details>
      </article>
    </div>
  );
}

type LibraryScopeFilter = 'all' | 'official_docs' | 'study_docs' | 'user_upload';
type LibraryQualityFilter = 'all' | 'gold' | 'readable' | 'needs_repair';
type LibraryIndexFilter = 'all' | 'indexed' | 'partial' | 'not_indexed';

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

function documentGoldBuildBlocksAsk(document: DocumentRepositoryDocument): boolean {
  const status = String(documentGoldBuildRun(document)?.status || '').trim();
  return ['needs_manual_repair', 'repairing', 'building_gold', 'auto_candidate'].includes(status);
}

function isDocumentReadable(document: DocumentRepositoryDocument): boolean {
  return (
    isRepositoryDocumentOperationallyReady(document)
    && Boolean(String(document.parsed_document_id || '').trim())
    && !documentGoldBuildBlocksAsk(document)
  );
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
  if (documentGoldBuildBlocksAsk(document)) {
    reasons.push(`gold_build_run=${documentGoldBuildRun(document)?.status}`);
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
  return `Gold 복구 큐 ${hiddenCount}권 · ${detail}`;
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
      return 'Morning Gate 점검 리포트 없음';
    case 'missing_source_approval_report':
      return '소스 승인 리포트 없음';
    case 'canonical_grade_source_unavailable':
      return 'Gold 판정 기준 소스 확인 불가';
    case 'missing_retrieval_eval_report':
      return '검색 평가 리포트 없음';
    case 'missing_answer_eval_report':
      return '답변 평가 리포트 없음';
    case 'missing_ragas_eval_report':
      return 'RAGAS 평가 리포트 없음';
    case 'missing_runtime_report':
      return '런타임 리포트 없음';
    case 'gold_recovery_items_present':
      return 'Gold 복구 큐 남아 있음';
    case 'retrieval_eval_case_count_below_minimum':
      return '검색 평가 케이스 부족';
    case 'retrieval_hit_at_3_below_threshold':
      return '검색 적중률 기준 미달';
    case 'answer_eval_case_count_below_minimum':
      return '답변 평가 케이스 부족';
    case 'answer_pass_rate_below_threshold':
      return '답변 통과율 기준 미달';
    case 'citation_precision_below_threshold':
      return '인용 정확도 기준 미달';
    case 'ragas_eval_case_count_below_minimum':
      return 'RAGAS 평가 케이스 부족';
    case 'ragas_faithfulness_below_threshold':
      return 'RAGAS 충실도 기준 미달';
    case 'qdrant_parity_failed':
      return 'Qdrant 인덱스 불일치';
    case 'qdrant_parity_unknown':
      return 'Qdrant 인덱스 확인 불가';
    default:
      return blocker || '검증 차단 항목';
  }
}

function certificationBlockerOwnerLabel(owner: string): string {
  switch (owner) {
    case 'foundry':
      return 'Foundry 준비';
    case 'source-approval':
      return '소스 승인';
    case 'retrieval-quality':
      return '검색 품질';
    case 'answer-quality':
      return '답변 품질';
    case 'gold-recovery':
      return 'Gold 복구';
    case 'runtime-index':
      return '런타임 인덱스';
    case 'product-quality':
      return '제품 품질';
    default:
      return owner || '담당 영역';
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
  const goldBuild = documentGoldBuildRun(document);
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
    goldBuild?.status ? `gold_build_${goldBuild.status}` : '',
    recoveryGold && runtimeBook?.gold_recovery_group ? runtimeBook.gold_recovery_group : '',
    metadataString(metadata, 'approval_state'),
    metadataString(metadata, 'review_status'),
    metadataString(metadata, 'translation_status'),
    metadataString(metadata, 'source_lane'),
    metadataString(metadata, 'document_format'),
  ].map((item) => String(item || '').trim()).filter(Boolean);
  return Array.from(new Set(chips)).slice(0, 8);
}

function coerceGoldBuildRun(value: unknown): GoldBuildRun | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const payload = value as Partial<GoldBuildRun>;
  const status = String(payload.status || '').trim();
  if (!status) {
    return null;
  }
  return payload as GoldBuildRun;
}

function documentGoldBuildRun(document: DocumentRepositoryDocument): GoldBuildRun | null {
  return coerceGoldBuildRun(document.gold_build_run) || coerceGoldBuildRun(document.metadata?.gold_build_run);
}

function goldBuildStatusLabel(run?: GoldBuildRun | null): string {
  switch (String(run?.status || '').trim()) {
    case 'gold':
      return 'Gold 통과';
    case 'needs_manual_repair':
      return 'Judge 수리 필요';
    case 'repairing':
      return '수리 중';
    case 'building_gold':
      return 'Gold 생성 중';
    case 'auto_candidate':
      return 'Gold 후보';
    default:
      return 'Gold Build 대기';
  }
}

function goldBuildTone(run?: GoldBuildRun | null): 'gold' | 'repairing' | 'manual' | 'candidate' | 'pending' {
  switch (String(run?.status || '').trim()) {
    case 'gold':
      return 'gold';
    case 'repairing':
    case 'building_gold':
      return 'repairing';
    case 'needs_manual_repair':
      return 'manual';
    case 'auto_candidate':
      return 'candidate';
    default:
      return 'pending';
  }
}

function goldBuildSummary(run?: GoldBuildRun | null): string {
  if (!run) {
    return 'Gold Build run 기록 없음';
  }
  const metrics = run.metrics || {};
  const sectionCount = Number(metrics.section_count ?? 0);
  const chunkCount = Number(metrics.chunk_count ?? 0);
  const actionCount = Array.isArray(run.repair_actions) ? run.repair_actions.length : 0;
  return [
    run.current_stage ? `현재 단계 ${run.current_stage}` : '',
    Number.isFinite(sectionCount) ? `${sectionCount}개 섹션` : '',
    Number.isFinite(chunkCount) ? `${chunkCount}개 chunk` : '',
    actionCount ? `${actionCount}개 수리 항목` : '',
  ].filter(Boolean).join(' · ') || run.policy || '';
}

function goldBuildPrimaryAction(run?: GoldBuildRun | null): string {
  const completedStatuses = new Set(['applied', 'verified', 'not_needed']);
  const action = run?.repair_actions?.find((item) => !completedStatuses.has(String(item.status || '').trim()));
  if (action && (String(action.diagnostic || '').trim() === 'code_loss' || String(action.id || '').trim() === 'quality_code_loss')) {
    return '코드블록 자동 수리로 YAML/명령어를 보존한 뒤 재색인과 품질 재검사를 실행';
  }
  return action?.next_action || action?.summary || run?.gold_evidence?.[0] || '';
}

function goldBuildBlockingMessage(run?: GoldBuildRun | null): string {
  if (!run || run.status === 'gold') {
    return '';
  }
  const diagnostic = run.diagnostics?.find((item) => item.severity === 'blocking') || run.diagnostics?.[0];
  const reason = diagnostic?.code === 'code_loss'
    ? 'YAML/명령어가 코드블록으로 보존되지 않았습니다.'
    : diagnostic?.summary || 'Judge 검수 기준을 통과하지 못했습니다.';
  const nextAction = goldBuildPrimaryAction(run);
  return nextAction
    ? `Judge 검수에서 멈춤: ${reason} 다음 조치: ${nextAction}`
    : `Judge 검수에서 멈춤: ${reason}`;
}

function goldBuildHasCodeLoss(run?: GoldBuildRun | null): boolean {
  if (!run) {
    return false;
  }
  const diagnostics = Array.isArray(run.diagnostics) ? run.diagnostics : [];
  if (diagnostics.some((item) => String(item.code || '').trim() === 'code_loss')) {
    return true;
  }
  const actions = Array.isArray(run.repair_actions) ? run.repair_actions : [];
  return actions.some((item) => {
    const id = String(item.id || '').trim();
    const diagnostic = String(item.diagnostic || '').trim();
    return id === 'quality_code_loss' || diagnostic === 'code_loss';
  });
}

function codeLossRepairSummary(run?: GoldBuildRun | null): string {
  const action = run?.repair_actions?.find((item) => String(item.diagnostic || '').trim() === 'code_loss' || String(item.id || '').trim() === 'quality_code_loss');
  const evidence = action?.evidence?.filter(Boolean).slice(0, 3) || [];
  return evidence.length
    ? `YAML/명령어 fence 누락: ${evidence.join(' · ')}`
    : 'YAML/명령어가 코드블록으로 보존되지 않았습니다.';
}

function codeLossRepairNextAction(run?: GoldBuildRun | null): string {
  const action = run?.repair_actions?.find((item) => String(item.diagnostic || '').trim() === 'code_loss' || String(item.id || '').trim() === 'quality_code_loss');
  return String(action?.next_action || '').trim()
    || '코드블록 자동 수리 후 chunk, Qdrant 색인, 지식망, 품질 판정을 다시 생성합니다.';
}

function repairActionTitle(action: { id?: string; diagnostic?: string; title?: string }): string {
  return String(action.diagnostic || '').trim() === 'code_loss' || String(action.id || '').trim() === 'quality_code_loss'
    ? '코드블록 자동 수리'
    : String(action.title || '수리 항목');
}

function repairActionSummary(action: { id?: string; diagnostic?: string; summary?: string }): string {
  return String(action.diagnostic || '').trim() === 'code_loss' || String(action.id || '').trim() === 'quality_code_loss'
    ? 'YAML/명령어가 평문에 섞인 부분을 찾아 코드블록으로 감싸고 재색인합니다.'
    : String(action.summary || '');
}

function repairActionNextAction(action: { id?: string; diagnostic?: string; next_action?: string }): string {
  return String(action.diagnostic || '').trim() === 'code_loss' || String(action.id || '').trim() === 'quality_code_loss'
    ? '버튼 실행 전 dry-run 요약을 확인하고 적용하면 chunk, Qdrant, 지식망, 품질 판정을 다시 생성합니다.'
    : String(action.next_action || '');
}

function goldBuildStageLabel(stage: string): string {
  switch (String(stage || '').trim()) {
    case 'diagnose':
      return '진단';
    case 'repair':
      return '수리';
    case 'rebuild':
      return '재생성';
    case 'reindex':
      return '색인';
    case 'verify':
      return '검증';
    case 'promote':
      return '합류';
    default:
      return stage || '단계';
  }
}

function goldBuildStageStatusLabel(status: string): string {
  switch (String(status || '').trim()) {
    case 'pass':
      return '통과';
    case 'fail':
      return '실패';
    case 'pending':
      return '대기';
    default:
      return status || '확인 필요';
  }
}

function repairActionStatusLabel(status: string): string {
  switch (String(status || '').trim()) {
    case 'applied':
      return '적용 완료';
    case 'verified':
      return '확인 완료';
    case 'not_needed':
      return '불필요';
    case 'queued':
      return '대기';
    case 'manual_required':
      return '수동 확인 필요';
    case 'provider_required':
      return '자동 수리기 연결 필요';
    default:
      return status || '확인 필요';
  }
}

function documentIndexStatus(row: RepositoryDocumentRow): LibraryIndexFilter {
  const chunkCount = Number(row.document.chunk_count || 0);
  const indexedCount = Number(row.document.indexed_chunk_count || 0);
  if (!Number.isFinite(chunkCount) || chunkCount <= 0) {
    return 'not_indexed';
  }
  if (!Number.isFinite(indexedCount) || indexedCount <= 0) {
    return 'not_indexed';
  }
  if (indexedCount < chunkCount) {
    return 'partial';
  }
  return 'indexed';
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
    const goldBuild = documentGoldBuildRun(row.document);
    const qualityMatches = filters.quality === 'gold'
      ? goldBuild?.status === 'gold'
      : filters.quality === 'readable'
        ? isDocumentReadable(row.document)
        : !isDocumentReadable(row.document);
    if (!qualityMatches) {
      return false;
    }
  }
  return true;
}

function indexStatusLabel(status: LibraryIndexFilter): string {
  switch (status) {
    case 'indexed':
      return '색인 완료';
    case 'partial':
      return '부분 색인';
    case 'not_indexed':
      return '색인 없음';
    default:
      return '전체';
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
    { badge: 'Bronze', title: '원본 수신', description: '파일 업로드 · 원본 캡처' },
    { badge: 'Silver', title: '구조화', description: '정규화 · 섹션 · 위키 문서' },
    { badge: 'Gold', title: '검색 근거 생성', description: 'chunk · Qdrant 색인 생성' },
    { badge: 'Judge', title: '검수 / 합류', description: 'Gold 판정 후 내 업로드 반영' },
    { badge: 'Topology', title: '지식망 생성', description: '개념 · 이미지 · 절차 관계 스냅샷 저장' },
  ],
};

function normalizeUploadStreamStage(stage: string): PipelineStage | null {
  switch (stage) {
    case 'received':
    case 'source_stored':
    case 'parse_start':
    case 'parsed':
    case 'chunk_start':
    case 'chunked':
    case 'persist_start':
    case 'persisting':
    case 'persisted':
    case 'repair_start':
    case 'code_block_repaired':
    case 'index_start':
    case 'indexing':
    case 'reindex_start':
    case 'indexed':
    case 'index_deferred':
    case 'judge_start':
    case 'judge_completed':
    case 'gold_build':
    case 'topology_start':
    case 'topology_build':
    case 'topology_ready':
    case 'topology_deferred':
    case 'topology_failed':
      return uploadPipelineStageFromEventName(stage);
    default:
      return null;
  }
}

function uploadPipelineStageFromEventName(eventName: string): PipelineStage | null {
  switch (eventName) {
    case 'received':
    case 'source_stored':
      return eventName;
    case 'parse_start':
    case 'parsed':
      return 'parsed';
    case 'chunk_start':
    case 'chunked':
      return 'chunked';
    case 'persist_start':
    case 'persisting':
      return 'persisting';
    case 'repair_start':
      return 'persisting';
    case 'persisted':
    case 'code_block_repaired':
      return 'persisted';
    case 'index_start':
    case 'indexing':
    case 'reindex_start':
      return 'indexing';
    case 'indexed':
    case 'index_deferred':
      return eventName;
    case 'judge_start':
    case 'gold_build':
      return 'gold_build';
    case 'judge_completed':
      return 'gold_build';
    case 'topology_start':
    case 'topology_build':
      return 'topology_build';
    case 'topology_ready':
    case 'topology_deferred':
    case 'topology_failed':
      return eventName;
    default:
      return null;
  }
}

function uploadLedgerPipelineStageFromEventName(eventName: string): UploadPipelineLedgerEvent['pipelineStage'] {
  const visualStage = uploadPipelineStageFromEventName(eventName);
  const index = uploadPipelineStepIndex(visualStage);
  return ['bronze', 'silver', 'gold', 'judge', 'topology'][index] || 'bronze';
}

function uploadPipelineStepIndex(stage: PipelineStage | null): number {
  switch (stage) {
    case 'received':
    case 'source_stored':
      return 0;
    case 'parsed':
    case 'chunked':
    case 'persisting':
    case 'persisted':
      return 1;
    case 'indexing':
    case 'indexed':
    case 'index_deferred':
      return 2;
    case 'gold_build':
      return 3;
    case 'topology_build':
    case 'topology_ready':
    case 'topology_deferred':
    case 'topology_failed':
    case 'done':
      return 4;
    default:
      return -1;
  }
}

function uploadPipelineVisualState(stage: PipelineStage, failedStage: PipelineStage | null): PipelineVisualState {
  if (stage === 'done') {
    return { activeIndex: 4, completedIndex: 4 };
  }
  if (stage === 'index_deferred') {
    return { activeIndex: 2, completedIndex: 1, deferredIndex: 2 };
  }
  if (stage === 'gold_build') {
    return { activeIndex: 3, completedIndex: 2, deferredIndex: 3 };
  }
  if (stage === 'topology_deferred') {
    return { activeIndex: 4, completedIndex: 3, deferredIndex: 4 };
  }
  if (stage === 'topology_failed') {
    return { activeIndex: 4, completedIndex: 3, errorIndex: 4 };
  }
  if (stage === 'error') {
    const failedIndex = uploadPipelineStepIndex(failedStage);
    return {
      activeIndex: failedIndex,
      completedIndex: Math.max(-1, failedIndex - 1),
      errorIndex: failedIndex,
    };
  }
  const activeIndex = uploadPipelineStepIndex(stage);
  return { activeIndex, completedIndex: activeIndex - 1 };
}

function uploadPipelineVisualStateFromLedger(events: UploadPipelineLedgerEvent[], fallback: PipelineVisualState): PipelineVisualState {
  if (!events.length) {
    return fallback;
  }
  const order = ['bronze', 'silver', 'gold', 'judge', 'topology'];
  const statuses: Record<string, string> = {};
  for (const event of events) {
    const stage = String(event.pipelineStage || '');
    if (!order.includes(stage)) {
      continue;
    }
    statuses[stage] = String(event.status || 'running');
  }
  const firstKnownIndex = order.findIndex((stage) => Boolean(statuses[stage]));
  if (firstKnownIndex > 0) {
    for (let index = 0; index < firstKnownIndex; index += 1) {
      statuses[order[index]] = 'completed';
    }
  }
  const failedIndex = order.findIndex((stage) => statuses[stage] === 'failed');
  if (failedIndex >= 0) {
    return {
      activeIndex: failedIndex,
      completedIndex: failedIndex - 1,
      errorIndex: failedIndex,
    };
  }
  const deferredIndex = order.findIndex((stage) => statuses[stage] === 'deferred');
  if (deferredIndex >= 0) {
    return {
      activeIndex: deferredIndex,
      completedIndex: deferredIndex - 1,
      deferredIndex,
    };
  }
  const runningIndexes = order
    .map((stage, index) => (statuses[stage] === 'running' ? index : -1))
    .filter((index) => index >= 0);
  if (runningIndexes.length > 0) {
    const activeIndex = Math.max(...runningIndexes);
    return {
      activeIndex,
      completedIndex: activeIndex - 1,
    };
  }
  let completedIndex = -1;
  for (let index = 0; index < order.length; index += 1) {
    if (statuses[order[index]] !== 'completed') {
      break;
    }
    completedIndex = index;
  }
  return {
    activeIndex: completedIndex >= 0 && completedIndex < order.length - 1 ? completedIndex : -1,
    completedIndex,
  };
}

function uploadPipelineOutcomeFromResult(ingest: UploadIngestResponse): PipelineStage {
  const topology = ingest.topology as DocumentTopology | undefined;
  const topologyRecord = ingest.topology as Record<string, unknown> | undefined;
  const topologyStatus = String(
    topologyRecord?.status
    || topologyRecord?.state
    || (topology?.metadata as Record<string, unknown> | undefined)?.storage
    || topology?.state
    || '',
  ).toLowerCase();
  if (topologyStatus === 'failed') {
    return 'topology_failed';
  }
  if (topologyStatus === 'deferred') {
    return 'topology_deferred';
  }
  if (topologyStatus === 'transient' || topologyStatus === 'unavailable') {
    return 'topology_deferred';
  }
  if (topology?.summary?.state === 'needs_review') {
    return 'topology_deferred';
  }
  if (ingest.index?.status === 'deferred') {
    return 'index_deferred';
  }
  if (ingest.gold_build_run && ingest.gold_build_run.status !== 'gold') {
    return 'gold_build';
  }
  return 'done';
}

function uploadStreamEventLog(event: UploadIngestStreamEvent): LogEntry | null {
  if (event.type !== 'event') {
    return null;
  }
  const eventName = event.event || event.stage;
  const data = event.data ?? event.payload ?? {};
  const num = (key: string) => Number(data[key] ?? 0).toLocaleString();
  switch (eventName) {
    case 'received':
      return { time: nowTime(), tag: 'info', msg: `파일 수신: ${String(data.filename || '')}` };
    case 'source_stored':
      return { time: nowTime(), tag: 'success', msg: `원본 저장 완료: ${formatBytes(Number(data.byte_size || 0))}` };
    case 'parse_start':
      return { time: nowTime(), tag: 'info', msg: '파싱을 시작했습니다.' };
    case 'parsed':
      return { time: nowTime(), tag: 'success', msg: `파싱 완료: ${num('block_count')}개 block, ${num('asset_count')}개 asset` };
    case 'chunk_start':
      return { time: nowTime(), tag: 'info', msg: '문서 조각 생성을 시작했습니다.' };
    case 'chunked':
      return { time: nowTime(), tag: 'success', msg: `문서 조각 생성: ${num('chunk_count')}개 chunk` };
    case 'persist_start':
    case 'persisting':
      return { time: nowTime(), tag: 'info', msg: 'PostgreSQL 저장 중입니다.' };
    case 'persisted':
      return { time: nowTime(), tag: 'success', msg: `DB 저장 완료: source ${String(data.document_source_id || '')}` };
    case 'repair_start':
      return { time: nowTime(), tag: 'info', msg: `코드블록 자동 수리 시작: ${num('changed_block_count')}개 후보` };
    case 'code_block_repaired':
      return { time: nowTime(), tag: 'success', msg: `코드블록 수리 적용: ${num('changed_block_count')}개 block, ${num('chunk_count')}개 chunk 재생성` };
    case 'index_start':
    case 'indexing':
    case 'reindex_start':
      return { time: nowTime(), tag: 'info', msg: `Qdrant 색인 중: ${num('chunk_count')}개 chunk` };
    case 'indexed':
      return { time: nowTime(), tag: 'success', msg: `Qdrant 색인 완료: ${num('indexed_count')}/${num('candidate_count')}` };
    case 'index_deferred':
      return { time: nowTime(), tag: 'warn', msg: `Qdrant 색인 보류: ${String(data.error || '임베딩 서버 확인 필요')}` };
    case 'gold_build':
      return { time: nowTime(), tag: 'info', msg: 'Gold/Judge 상태를 갱신했습니다.' };
    case 'judge_start':
      return { time: nowTime(), tag: 'info', msg: 'Judge 품질 판정을 시작했습니다.' };
    case 'judge_completed':
      return {
        time: nowTime(),
        tag: String(data.quality_state || '') === 'gold_ready' ? 'success' : 'warn',
        msg: `Judge 품질 판정: ${String(data.quality_state || '상태 미확인')} · blocker ${num('blocker_count')}`,
      };
    case 'topology_start':
    case 'topology_build':
      return { time: nowTime(), tag: 'info', msg: '지식망 스냅샷을 생성 중입니다.' };
    case 'topology_ready':
      return { time: nowTime(), tag: 'success', msg: `지식망 저장 완료: ${num('node_count')}개 노드, ${num('edge_count')}개 관계` };
    case 'topology_deferred':
      return { time: nowTime(), tag: 'warn', msg: `지식망 보류: ${String(data.error || '근거 보강 또는 재시도 필요')}` };
    case 'topology_failed':
      return { time: nowTime(), tag: 'error', msg: `지식망 실패: ${String(data.error || '스냅샷 생성 실패')}` };
    case 'complete':
      return { time: nowTime(), tag: 'success', msg: '업로드 파이프라인 결과 수신 완료' };
    default:
      return { time: nowTime(), tag: 'info', msg: `서버 이벤트: ${eventName}` };
  }
}

function uploadEventTraceFromStreamEvent(event: UploadIngestStreamEvent, elapsedMs: number): UploadEventTraceItem | null {
  if (event.type !== 'event') {
    return null;
  }
  const log = uploadStreamEventLog(event);
  if (!log) {
    return null;
  }
  return {
    id: `${event.event || event.stage}-${elapsedMs}-${Math.random().toString(36).slice(2)}`,
    stage: event.event || event.stage,
    label: stageLabelForEvent(event.event || event.stage),
    detail: log.msg,
    time: log.time,
    occurredAt: event.occurred_at || '',
    elapsedMs,
    tone: log.tag === 'error' ? 'error' : log.tag === 'warn' ? 'warn' : log.tag === 'success' ? 'success' : 'info',
  };
}

function stageLabelForEvent(stage: string): string {
  switch (stage) {
    case 'received': return '수신';
    case 'source_stored': return '원본 저장';
    case 'parse_start': return '파싱 시작';
    case 'parsed': return '파싱';
    case 'chunk_start': return 'chunk 시작';
    case 'chunked': return 'chunk 생성';
    case 'persist_start': return 'DB 저장 시작';
    case 'persisting': return 'DB 저장 중';
    case 'persisted': return 'DB 저장 완료';
    case 'repair_start': return '수리 시작';
    case 'code_block_repaired': return '코드블록 수리';
    case 'index_start': return '색인 시작';
    case 'indexing': return '색인 중';
    case 'reindex_start': return '재색인 시작';
    case 'indexed': return '색인 완료';
    case 'index_deferred': return '색인 보류';
    case 'judge_start': return 'Judge 시작';
    case 'judge_completed': return 'Judge 판정';
    case 'gold_build': return 'Judge 판정';
    case 'topology_start': return '지식망 시작';
    case 'topology_build': return '지식망 생성';
    case 'topology_ready': return '지식망 준비';
    case 'topology_deferred': return '지식망 보류';
    case 'topology_failed': return '지식망 실패';
    default: return stage;
  }
}

function formatServerEventTime(value?: string): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function uploadStageStatusMessage(stage: PipelineStage): { status: string; message: string } {
  switch (stage) {
    case 'received':
      return { status: 'received', message: '파일을 서버가 수신했습니다.' };
    case 'source_stored':
      return { status: 'stored', message: '원본 파일을 저장했습니다.' };
    case 'parsed':
    case 'chunked':
      return { status: 'parsing', message: '문서 구조를 읽고 조각을 만들고 있습니다.' };
    case 'persisting':
      return { status: 'saving', message: '문서와 chunk를 DB에 저장 중입니다.' };
    case 'persisted':
      return { status: 'saved', message: '문서가 DB에 저장되었습니다.' };
    case 'indexing':
      return { status: 'indexing', message: 'Qdrant 검색 인덱스를 생성 중입니다.' };
    case 'indexed':
      return { status: 'indexed', message: '검색 인덱스 생성이 완료되었습니다.' };
    case 'index_deferred':
      return { status: 'index_deferred', message: '문서는 저장됐고 색인은 보류되었습니다.' };
    case 'gold_build':
      return { status: 'gold_build', message: 'Gold/Judge 상태를 갱신했습니다.' };
    case 'topology_build':
      return { status: 'topology_build', message: '문서 지식망 스냅샷을 생성 중입니다.' };
    case 'topology_ready':
      return { status: 'topology_ready', message: '문서 지식망 스냅샷이 저장되었습니다.' };
    case 'topology_deferred':
      return { status: 'topology_deferred', message: '문서는 저장됐고 지식망 생성은 보류되었습니다.' };
    case 'topology_failed':
      return { status: 'topology_failed', message: '지식망 생성에 실패했습니다. 문서 저장 결과는 유지됩니다.' };
    case 'done':
      return { status: 'ready', message: '문서 준비가 완료되었습니다.' };
    case 'error':
      return { status: 'failed', message: '문서 처리에 실패했습니다.' };
    default:
      return { status: 'idle', message: '엔진 대기 중입니다.' };
  }
}

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
    gold_policy: 'gold_allowed_after_validation',
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
  const headerWorkspaceId = useMemo(() => {
    if (typeof window === 'undefined') {
      return 'ws_default';
    }
    return window.localStorage.getItem('opsConsole.activeWorkspaceId') || 'ws_default';
  }, []);
  const headerConnectionId = useMemo(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage.getItem('opsConsole.activeConnectionId') || '';
  }, []);
  const [headerConnections, setHeaderConnections] = useState<OcpConnection[]>([]);
  const [headerProfileStatus, setHeaderProfileStatus] = useState<ClusterConnectionStatus>('not_connected');
  const [isHeaderProfileLoading, setIsHeaderProfileLoading] = useState(false);
  const [factoryLane, setFactoryLane] = useState<FactoryLane>('tools');
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>('idle');
  const [pipelineFailedStage, setPipelineFailedStage] = useState<PipelineStage | null>(null);
  const [uploadStreamActive, setUploadStreamActive] = useState(false);
  const [indexRetrying, setIndexRetrying] = useState(false);
  const [codeRepairingDocumentId, setCodeRepairingDocumentId] = useState<string | null>(null);
  const [documentRecoveryAction, setDocumentRecoveryAction] = useState<{
    documentSourceId: string;
    action: 'quality' | 'topology';
  } | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState('');
  const [pipelineWarningMsg, setPipelineWarningMsg] = useState('');
  const [currentFile, setCurrentFile] = useState('');
  const [uploadEventTrace, setUploadEventTrace] = useState<UploadEventTraceItem[]>([]);
  const [uploadPipelineLedger, setUploadPipelineLedger] = useState<UploadPipelineLedgerEvent[]>([]);
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
  const [documentTopologyScope, setDocumentTopologyScope] = useState<DocumentTopologyScopeResponse | null>(null);
  const [documentTopologyError, setDocumentTopologyError] = useState('');
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
  const uploadPipelineVisual = useMemo(
    () => uploadPipelineVisualStateFromLedger(
      uploadPipelineLedger,
      uploadPipelineVisualState(pipelineStage, pipelineFailedStage),
    ),
    [pipelineFailedStage, pipelineStage, uploadPipelineLedger],
  );
  const uploadPipelineRunningIndex = useMemo(() => {
    const order = ['bronze', 'silver', 'gold', 'judge', 'topology'];
    const latestRunning = [...uploadPipelineLedger].reverse().find((event) => event.status === 'running');
    return latestRunning ? order.indexOf(latestRunning.pipelineStage) : -1;
  }, [uploadPipelineLedger]);

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

  const refreshDocumentTopology = useCallback((scope: ActiveWikiScope = activeWikiScope) => {
    loadDocumentTopology(scope)
      .then((payload) => {
        setDocumentTopologyScope(payload);
        setDocumentTopologyError('');
      })
      .catch((error: unknown) => {
        setDocumentTopologyScope(null);
        setDocumentTopologyError(error instanceof Error ? error.message : 'topology preview load failed');
      });
  }, [activeWikiScope]);

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
    refreshDocumentTopology();
    refreshRuntimeHealth();
  }, [refreshDocumentRepositories, refreshDocumentTopology, refreshOfficialCatalog, refreshRepositoryFavorites, refreshRepositoryUnanswered, refreshRuntimeHealth, refreshSourceJudgeReports, refreshSourceVerificationQueue]);

  const handleCodeBlockRepair = useCallback(async (document: DocumentRepositoryDocument) => {
    const goldRun = documentGoldBuildRun(document);
    if (!goldBuildHasCodeLoss(goldRun)) {
      addLog('info', '이 문서는 code_loss 자동 수리 대상이 아닙니다.');
      return;
    }
    const documentId = document.document_source_id;
    const parsedId = document.parsed_document_id;
    setCodeRepairingDocumentId(documentId);
    setErrorMsg('');
    setPipelineWarningMsg('');
    try {
      const preview = await repairUploadCodeBlocks({
        documentSourceId: documentId,
        parsedDocumentId: parsedId,
        dryRun: true,
      });
      if (!preview.changed_block_count) {
        addLog('info', '코드블록 자동 수리 후보가 없습니다. 품질 재검사가 필요합니다.');
        return;
      }
      const diffSummary = preview.diff_summary
        .slice(0, 5)
        .map((item) => {
          const previewText = (item.preview || []).slice(0, 2).join(' / ');
          return `${item.language || 'code'} ${item.start_line ?? '?'}-${item.end_line ?? '?'}: ${previewText}`;
        })
        .join('\n');
      const confirmed = typeof window === 'undefined'
        ? true
        : window.confirm(
          [
            `코드블록 자동 수리 후보 ${preview.changed_block_count}개를 찾았습니다.`,
            '',
            diffSummary,
            '',
            '적용하면 markdown, chunk, Qdrant 색인, 지식망, 품질 판정을 다시 생성합니다.',
          ].join('\n'),
        );
      if (!confirmed) {
        addLog('info', '코드블록 자동 수리를 취소했습니다.');
        return;
      }
      setUploadPipelineLedger([]);
      setUploadEventTrace([]);
      setPipelineStage('persisting');
      const applied = await repairUploadCodeBlocks({
        documentSourceId: documentId,
        parsedDocumentId: parsedId,
        dryRun: false,
      });
      const events = (applied.events || []).filter((event): event is Extract<UploadIngestStreamEvent, { type: 'event' }> => event.type === 'event');
      if (events.length) {
        setUploadPipelineLedger(events.map((event) => ({
          event: event.event || event.stage,
          pipelineStage: event.pipeline_stage || uploadLedgerPipelineStageFromEventName(event.event || event.stage),
          status: event.status || 'running',
          occurredAt: event.occurred_at || '',
          data: event.data ?? event.payload ?? {},
        })));
        setUploadEventTrace(events
          .map((event, index) => uploadEventTraceFromStreamEvent(event, index))
          .filter((item): item is UploadEventTraceItem => Boolean(item)));
        const newLogs = events
          .map(uploadStreamEventLog)
          .filter((item): item is LogEntry => Boolean(item));
        if (newLogs.length) {
          setLogs((prev) => [...newLogs.reverse(), ...prev].slice(0, 10));
        }
      }
      if (applied.gold_build_run) {
        setLatestUploadIngest((current) => ({
          dry_run: false,
          filename: applied.filename || current?.filename || document.filename,
          storage_key: current?.storage_key || '',
          byte_size: current?.byte_size || 0,
          document_format: current?.document_format || String(document.metadata?.document_format || ''),
          mime_type: current?.mime_type || document.mime_type || '',
          sha256: current?.sha256 || '',
          block_count: current?.block_count || 0,
          asset_count: current?.asset_count || 0,
          chunk_count: current?.chunk_count || document.chunk_count || 0,
          warnings: applied.warnings || current?.warnings || [],
          sections: current?.sections || [],
          persisted: current?.persisted || {
            document_source_id: documentId,
            document_version_id: '',
            parse_job_id: '',
            parsed_document_id: parsedId,
            block_count: 0,
            asset_count: 0,
            chunk_count: document.chunk_count || 0,
          },
          index: applied.index,
          gold_build_run: applied.gold_build_run,
          topology: applied.topology || undefined,
          quality: applied.quality || undefined,
          source_scope: applied.source_scope || document.source_scope,
        }));
      }
      if (applied.ok) {
        setPipelineStage('done');
        addLog('success', '코드블록 자동 수리 후 Gold 승급 조건을 통과했습니다.');
      } else {
        setPipelineStage(uploadPipelineOutcomeFromResult(applied as unknown as UploadIngestResponse));
        const blockers = applied.quality?.blockers?.length ?? 0;
        setPipelineWarningMsg(`코드블록 수리는 적용됐지만 Gold 승급은 아직 보류입니다. 남은 blocker ${blockers}개`);
        addLog('warn', `코드블록 수리 완료, 남은 blocker ${blockers}개`);
      }
      refreshData();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '코드블록 자동 수리 실패';
      setPipelineStage('error');
      setPipelineFailedStage('gold_build');
      setErrorMsg(message);
      addLog('error', message);
    } finally {
      setCodeRepairingDocumentId(null);
    }
  }, [refreshData]);

  const handleDocumentQualityRecheck = useCallback(async (document: DocumentRepositoryDocument) => {
    const documentId = document.document_source_id;
    setDocumentRecoveryAction({ documentSourceId: documentId, action: 'quality' });
    setErrorMsg('');
    setPipelineWarningMsg('');
    try {
      addLog('info', `${document.title || document.filename} 품질 판정을 다시 확인합니다.`);
      const result = await recheckUploadDocumentQuality({
        documentSourceId: documentId,
        parsedDocumentId: document.parsed_document_id,
      });
      const blockerCount = result.quality?.blockers?.length ?? 0;
      if (result.ok) {
        addLog('success', '품질 재검사 통과: Gold 조건을 만족합니다.');
      } else {
        addLog('warn', `품질 재검사 완료: 남은 blocker ${blockerCount}개`);
        setPipelineWarningMsg(`품질 재검사 결과 Gold 승급은 아직 보류입니다. 남은 blocker ${blockerCount}개`);
      }
      refreshData();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '품질 재검사 실패';
      setErrorMsg(message);
      addLog('error', message);
    } finally {
      setDocumentRecoveryAction(null);
    }
  }, [refreshData]);

  const handleDocumentTopologyRetry = useCallback(async (document: DocumentRepositoryDocument) => {
    const documentId = document.document_source_id;
    setDocumentRecoveryAction({ documentSourceId: documentId, action: 'topology' });
    setPipelineStage('topology_build');
    setErrorMsg('');
    setPipelineWarningMsg('');
    try {
      addLog('info', `${document.title || document.filename} 지식망을 다시 생성합니다.`);
      const result = await retryUploadDocumentTopology({
        documentSourceId: documentId,
        parsedDocumentId: document.parsed_document_id,
      });
      const topologyStatus = String(result.topology_status?.status || result.topology?.state || '').trim() || 'unknown';
      const blockerCount = result.quality?.blockers?.length ?? 0;
      if (result.ok) {
        setPipelineStage('topology_ready');
        addLog('success', '지식망 재생성 및 품질 판정을 통과했습니다.');
      } else {
        setPipelineStage(topologyStatus === 'ready' ? 'done' : 'topology_deferred');
        addLog('warn', `지식망 재생성 결과: ${topologyStatus}, 남은 blocker ${blockerCount}개`);
        setPipelineWarningMsg(`지식망 재생성 후 Gold 승급은 아직 보류입니다. topology ${topologyStatus}, blocker ${blockerCount}개`);
      }
      refreshData();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '지식망 재생성 실패';
      setPipelineStage('topology_failed');
      setErrorMsg(message);
      addLog('error', message);
    } finally {
      setDocumentRecoveryAction(null);
    }
  }, [refreshData]);

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

  const activeHeaderConnection = useMemo(
    () => headerConnections.find((item) => item.connection_id === headerConnectionId) ?? headerConnections[0] ?? null,
    [headerConnectionId, headerConnections],
  );
  const headerProfileName = useMemo(() => clusterProfileName(activeHeaderConnection), [activeHeaderConnection]);
  const headerProfileStatusLabel = clusterConnectionStatusLabel(headerProfileStatus);

  useEffect(() => {
    const identity = activeHeaderConnection
      ? (
          activeHeaderConnection.username_hint?.trim()
          || activeHeaderConnection.display_name?.trim()
          || activeHeaderConnection.connection_id
        )
      : '';
    setRuntimeIdentityUser(identity || null);
    refreshDocumentRepositories();
    refreshDocumentTopology();
  }, [
    activeHeaderConnection?.connection_id,
    activeHeaderConnection?.display_name,
    activeHeaderConnection?.username_hint,
    refreshDocumentRepositories,
    refreshDocumentTopology,
  ]);

  useEffect(() => {
    let cancelled = false;
    setIsHeaderProfileLoading(true);
    listOcpProfiles(headerWorkspaceId)
      .then((connections) => {
        if (cancelled) {
          return;
        }
        const activeConnection = connections.find((item) => item.connection_id === headerConnectionId) ?? connections[0] ?? null;
        setHeaderConnections(connections);
        setHeaderProfileStatus(normalizeClusterConnectionStatus(activeConnection));
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        console.error(error);
        setHeaderProfileStatus('error');
      })
      .finally(() => {
        if (!cancelled) {
          setIsHeaderProfileLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [headerConnectionId, headerWorkspaceId]);

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
    const requestedLane = activeWikiScope === 'official'
      ? 'tools'
      : activeWikiScope === 'uploads'
        ? 'uploads'
        : 'customer';
    setLibraryScopeFilter(libraryFilterForWikiScope(activeWikiScope));
    setFactoryLane(activeWikiScope === 'uploads' ? 'user' : 'tools');
    if (activeWikiScope !== 'official') {
      repositoryAutoloadKeyRef.current = '';
      setRepositoryStage('idle');
      setRepositoryError('');
      if (requestedQuery) {
        setSearchQuery(requestedQuery);
      }
      setFactoryAssistantQuery('');
      return;
    }
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
    if (location.hash !== '#book-factory') {
      return;
    }
    const handle = window.setTimeout(() => {
      document.getElementById('book-factory')?.scrollIntoView({ block: 'start' });
    }, 80);
    return () => window.clearTimeout(handle);
  }, [activeWikiScope, location.hash]);

  useEffect(() => {
    const panel = searchParams.get('panel');
    const targetId = panel === 'data_health'
      ? 'system-data-board'
      : panel === 'source_factory'
        ? 'book-factory'
        : '';
    if (!targetId) {
      return;
    }
    const handle = window.setTimeout(() => {
      document.getElementById(targetId)?.scrollIntoView({ block: 'start' });
    }, 80);
    return () => window.clearTimeout(handle);
  }, [activeWikiScope, searchParams]);

  useEffect(() => {
    if (factoryLane !== 'user') return;
    if (!pipelineRef.current) return;
    const steps = pipelineRef.current.querySelectorAll('.pipeline-step');
    const stageIndex = uploadPipelineVisual.activeIndex;
    if (stageIndex >= 0 && steps[stageIndex]) {
      gsap.fromTo(
        steps[stageIndex].querySelector('.step-icon'),
        { scale: 0.8, opacity: 0.5 },
        { scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(1.7)' },
      );
    }
  }, [factoryLane, uploadPipelineVisual.activeIndex]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';

    setErrorMsg('');
    setPipelineWarningMsg('');
    setCurrentFile(file.name);
    setLatestUploadIngest(null);
    setPipelineStage('idle');
    setPipelineFailedStage(null);
    setUploadStreamActive(true);
    setUploadEventTrace([]);
    setUploadPipelineLedger([]);
    setFactoryLane('user');

    let lastActualStage: PipelineStage = 'idle';
    const uploadStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const writeIngestionStatus = (stage: PipelineStage, filename = file.name, extra: Record<string, unknown> = {}) => {
      const status = uploadStageStatusMessage(stage);
      window.localStorage.setItem(WORKSPACE_INGESTION_STATUS_STORAGE_KEY, JSON.stringify({
        ...status,
        filename,
        updatedAt: new Date().toISOString(),
        ...extra,
      }));
    };

    try {
      addLog('info', `'${file.name}' 업로드 요청을 보냈습니다. 서버 이벤트를 기다립니다.`);
      writeIngestionStatus('received');
      const ingest = await uploadDocumentIngestionStream(
        file,
        { index: true, sourceScope: 'user_upload' },
        (event) => {
          if (event.type === 'event') {
            const eventName = event.event || event.stage;
            const eventData = event.data ?? event.payload ?? {};
            setUploadPipelineLedger((prev) => [
              ...prev,
              {
                event: eventName,
                pipelineStage: event.pipeline_stage || uploadLedgerPipelineStageFromEventName(eventName),
                status: event.status || 'running',
                occurredAt: event.occurred_at || '',
                data: eventData,
              },
            ].slice(-100));
            const normalizedStage = normalizeUploadStreamStage(eventName);
            const logLine = uploadStreamEventLog(event);
            const elapsedMs = (typeof performance !== 'undefined' ? performance.now() : Date.now()) - uploadStartedAt;
            const traceItem = uploadEventTraceFromStreamEvent(event, elapsedMs);
            if (traceItem) {
              setUploadEventTrace((prev) => [...prev, traceItem].slice(-24));
            }
            if (logLine) {
              addLog(logLine.tag, logLine.msg);
            }
            if (normalizedStage) {
              lastActualStage = normalizedStage;
              setPipelineStage(normalizedStage);
              writeIngestionStatus(normalizedStage);
              if (normalizedStage === 'persisted') {
                refreshDocumentRepositories();
              }
              if (normalizedStage === 'topology_ready' || normalizedStage === 'topology_deferred' || normalizedStage === 'topology_failed') {
                refreshDocumentTopology('uploads');
              }
              if (normalizedStage === 'index_deferred') {
                setPipelineWarningMsg(String(eventData.error || '임베딩 서버 확인 후 색인 재시도가 필요합니다.'));
              }
              if (normalizedStage === 'topology_deferred' || normalizedStage === 'topology_failed') {
                setPipelineWarningMsg(String(eventData.error || 'Topology snapshot 보류 상태입니다.'));
              }
              if (eventName === 'judge_completed' && event.status !== 'completed') {
                setPipelineWarningMsg(String(eventData.error || eventData.quality_state || '품질 판정서 보류 상태입니다.'));
              }
            }
          }
          if (event.type === 'error') {
            setUploadPipelineLedger((prev) => [
              ...prev,
              {
                event: event.event || event.stage || 'failed',
                pipelineStage: event.pipeline_stage || uploadLedgerPipelineStageFromEventName(event.event || event.stage || 'failed'),
                status: 'failed',
                occurredAt: event.occurred_at || '',
                data: event.data ?? event.payload ?? { error: event.error },
              },
            ].slice(-100));
            setPipelineFailedStage(lastActualStage === 'idle' ? null : lastActualStage);
            setPipelineStage('error');
            setPipelineWarningMsg('');
            setErrorMsg(event.error || '업로드 스트림 오류');
            const elapsedMs = (typeof performance !== 'undefined' ? performance.now() : Date.now()) - uploadStartedAt;
            setUploadEventTrace((prev) => [
              ...prev,
              {
                id: `error-${Date.now()}`,
                stage: 'error',
                label: '실패',
                detail: event.error || '업로드 스트림 오류',
                time: nowTime(),
                occurredAt: event.occurred_at || '',
                elapsedMs,
                tone: 'error' as const,
              },
            ].slice(-24));
          }
        },
      );
      const indexedCount = ingest.index?.indexed_count ?? 0;
      const indexDeferred = ingest.index?.status === 'deferred';
      const indexLine = ingest.index
        ? indexDeferred
          ? `, 인덱싱 보류 ${indexedCount}/${ingest.index.candidate_count}`
          : `, ${indexedCount}/${ingest.index.candidate_count}개 인덱싱`
        : '';
      const goldRun = ingest.gold_build_run ?? null;
      setLatestUploadIngest(ingest);

      addLog(indexDeferred ? 'warn' : 'success', `'${ingest.filename}' 저장 완료: ${ingest.block_count}개 block, ${ingest.chunk_count}개 chunk${indexLine}.`);
      if (goldRun) {
        addLog(
          goldRun.status === 'gold' ? 'success' : goldRun.status === 'needs_manual_repair' ? 'warn' : 'info',
          `[Gold Build] ${goldBuildStatusLabel(goldRun)} · ${goldBuildSummary(goldRun)}`,
        );
        const nextRepair = goldBuildPrimaryAction(goldRun);
        if (nextRepair) {
          addLog(goldRun.status === 'gold' ? 'success' : 'warn', `[Repair Log] ${nextRepair}`);
        }
      }
      if (ingest.warnings.length > 0) {
        addLog('warn', ingest.warnings.slice(0, 2).join(' / '));
      }

      const outcomeStage = uploadPipelineOutcomeFromResult(ingest);
      const goldBlockingMessage = !indexDeferred ? goldBuildBlockingMessage(goldRun) : '';
      const topology = ingest.topology as DocumentTopology | undefined;
      const topologyWarning = outcomeStage === 'topology_deferred'
        ? (topology?.summary?.blockers ?? topology?.blockers ?? []).slice(0, 2).join(' · ') || '지식망 스냅샷이 보류되었습니다.'
        : outcomeStage === 'topology_failed'
          ? String((ingest.topology as Record<string, unknown> | undefined)?.error || '지식망 스냅샷 생성 실패')
          : '';
      setPipelineWarningMsg(
        outcomeStage === 'index_deferred'
          ? (ingest.index?.error || '색인이 보류되었습니다. 임베딩 서버 복구 후 재시도하세요.')
          : topologyWarning || goldBlockingMessage,
      );
      setErrorMsg('');
      writeIngestionStatus(lastActualStage, ingest.filename || file.name, {
        repositoryId: ingest.repository_id || ingest.persisted?.repository_id || '',
        documentSourceId: ingest.persisted?.document_source_id || '',
      });
      if (goldBlockingMessage) {
        addLog('warn', goldBlockingMessage);
      }
      addLog(
        goldRun?.status === 'gold' && !indexDeferred ? 'success' : 'warn',
        indexDeferred
          ? `'${ingest.filename}' 문서는 저장됐고, 임베딩 서버 복구 후 인덱싱 재시도가 필요합니다.`
          : goldRun?.status === 'gold'
            ? `'${ingest.filename}' 문서가 Gold Wiki 근거로 준비됐습니다.`
            : `'${ingest.filename}' 문서는 저장/인덱싱됐지만 Gold Build 수리 항목이 남아 있습니다.`,
      );
      refreshData();
    } catch (error: unknown) {
      const msg = errorMessage(error, 'Unknown error');
      setPipelineFailedStage(lastActualStage === 'idle' ? null : lastActualStage);
      setPipelineStage('error');
      setPipelineWarningMsg('');
      setErrorMsg(msg);
      writeIngestionStatus('error');
      addLog('error', `Pipeline failed: ${msg}`);
    } finally {
      setUploadStreamActive(false);
    }
  };

  const handleUploadIndexRetry = async () => {
    const documentSourceId = latestUploadIngest?.persisted?.document_source_id || '';
    if (!documentSourceId) {
      addLog('warn', '색인 재시도 대상 document_source_id가 없습니다.');
      return;
    }
    setIndexRetrying(true);
    setUploadStreamActive(true);
    setPipelineStage('indexing');
    setPipelineFailedStage(null);
    setErrorMsg('');
    setPipelineWarningMsg('');
    addLog('info', `'${latestUploadIngest?.filename || currentFile}' Qdrant 색인을 재시도합니다.`);
    try {
      const retry = await retryUploadDocumentIndex({
        documentSourceId,
        sourceScope: latestUploadIngest?.source_scope || 'user_upload',
        chunkCount: latestUploadIngest?.chunk_count || latestUploadIngest?.index?.candidate_count || 100,
        indexRetryAttempts: 3,
      });
      const refreshed = retry.updated_documents.find((item) => item.document_source_id === documentSourceId);
      const nextGoldRun = refreshed?.gold_build_run ?? latestUploadIngest?.gold_build_run;
      const indexDeferred = retry.index?.status === 'deferred' || !retry.ok;
      setLatestUploadIngest((current) => current ? {
        ...current,
        index: retry.index,
        gold_build_run: nextGoldRun ?? current.gold_build_run,
        topology: retry.topology ?? current.topology,
      } : current);
      const retryTopology = retry.topology as DocumentTopology | undefined;
      const retryTopologyDeferred = !indexDeferred
        && Boolean(retryTopology)
        && (retryTopology?.summary?.state === 'needs_review' || String(retryTopology?.metadata?.storage || '').toLowerCase() !== 'postgres');
      setPipelineStage(indexDeferred ? 'index_deferred' : 'indexed');
      const nextGoldWarning = !indexDeferred ? goldBuildBlockingMessage(nextGoldRun) : '';
      const retryTopologyWarning = retryTopologyDeferred
        ? (retryTopology?.summary?.blockers ?? retryTopology?.blockers ?? []).slice(0, 2).join(' · ') || '지식망 스냅샷이 보류되었습니다.'
        : '';
      setPipelineWarningMsg(indexDeferred ? (retry.index?.error || '색인이 다시 보류되었습니다. 임베딩 서버 상태를 확인하세요.') : retryTopologyWarning || nextGoldWarning);
      setErrorMsg('');
      if (nextGoldWarning) {
        addLog('warn', nextGoldWarning);
      }
      addLog(
        indexDeferred ? 'warn' : 'success',
        indexDeferred
          ? `색인 재시도 보류: ${retry.index?.error || '임베딩 서버 확인 필요'}`
          : `색인 재시도 완료: ${retry.index.indexed_count.toLocaleString()}/${retry.index.candidate_count.toLocaleString()}`,
      );
      refreshData();
    } catch (error: unknown) {
      const msg = errorMessage(error, '색인 재시도 실패');
      setPipelineFailedStage('indexing');
      setPipelineStage('error');
      setPipelineWarningMsg('');
      setErrorMsg(msg);
      addLog('error', `색인 재시도 실패: ${msg}`);
    } finally {
      setIndexRetrying(false);
      setUploadStreamActive(false);
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
    addLog('info', `Book Factory OCP lookup: ${nextQuery}`);
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

  const openUserDocsUpload = (openPicker = false) => {
    setFactoryLane('user');
    navigate('/playbook-library?scope=uploads&lane=uploads#book-factory');
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
      if (result.gold_build_run) {
        addLog(
          result.gold_build_run.status === 'gold' ? 'success' : 'warn',
          `[Gold Build] ${goldBuildStatusLabel(result.gold_build_run)} · ${goldBuildSummary(result.gold_build_run)}`,
        );
      }
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
      case 'received': return '파일 수신';
      case 'source_stored': return '원본 저장 완료';
      case 'parsed': return '문서 파싱 완료';
      case 'chunked': return '문서 조각 생성';
      case 'persisting': return 'DB 저장 중';
      case 'persisted': return 'DB 저장 완료';
      case 'indexing': return 'Qdrant 색인 중';
      case 'indexed': return 'Qdrant 색인 완료';
      case 'index_deferred': return '색인 보류';
      case 'gold_build': return 'Gold/Judge 확인';
      case 'topology_build': return '지식망 생성 중';
      case 'topology_ready': return '지식망 준비 완료';
      case 'topology_deferred': return '지식망 보류';
      case 'topology_failed': return '지식망 실패';
      case 'done': return '파이프라인 완료';
      case 'error': return '파이프라인 실패';
      default: return '엔진 대기 중';
    }
  };

  const isProcessing = uploadStreamActive;

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
  const missingQdrantEntryCount = runtimeDbCorpus?.missing_qdrant_index_entries ?? summary?.missing_qdrant_index_entry_count ?? 0;
  const qdrantCorpusInSync = (
    runtimeDbCorpus?.qdrant_index_parity === true
    || (
      runtimeDbCorpus?.qdrant_index_parity !== false
      && typeof dbCorpusChunks === 'number'
      && typeof qdrantPoints === 'number'
      && dbCorpusChunks === qdrantPoints
    )
  );
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
  const certificationBlockerDetails = certification?.blocker_details ?? [];
  const certificationStatus = certification?.status ?? controlRoom?.summary?.certification_status ?? '';
  const isNotCertifiable = Boolean(certificationStatus && certificationStatus !== 'certified');
  const runtimeAlerts = [
    !runtimeHealth && !runtimeHealthError ? '런타임 상태 확인 중입니다.' : '',
    documentRepositoryError ? `문서 목록 확인 실패: ${documentRepositoryError}` : '',
    runtimeHealthError ? `런타임 상태 확인 실패: ${runtimeHealthError}` : '',
    isNotCertifiable
      ? `검증 불가 · ${certificationBlockers.slice(0, 4).map(certificationBlockerLabel).join(' · ') || '검증 차단 항목 확인 필요'}`
      : '',
    operationalWikiGateNotice,
    runtimeHealth && !runtimeQdrant ? 'Qdrant 실시간 상태가 health 응답에 없습니다.' : '',
    runtimeQdrant && runtimeQdrant.ready === false
      ? `Qdrant live check 실패: ${runtimeQdrant.status || 'unknown'}${runtimeQdrant.error ? ` (${runtimeQdrant.error})` : ''}`
      : '',
    runtimeQdrant && typeof qdrantPoints !== 'number'
      ? 'Qdrant points_count 확인 불가'
      : '',
    typeof dbCorpusChunks === 'number' && typeof qdrantPoints === 'number' && dbCorpusChunks !== qdrantPoints
      ? `Postgres chunks ${dbCorpusChunks.toLocaleString()} / Qdrant points ${qdrantPoints.toLocaleString()} 불일치`
      : '',
    runtimeDbCorpus?.qdrant_index_parity === false
      ? 'Postgres qdrant_index_entries parity 확인 필요'
      : '',
    missingQdrantEntryCount
      ? `Qdrant index entry 누락 ${Number(missingQdrantEntryCount).toLocaleString()}건`
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
  const userUploadChunkCount = userUploadDocumentRows.reduce(
    (total, row) => total + Number(row.document.chunk_count || 0),
    0,
  );
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
      ? 'Book Factory 실행 중'
      : repositoryStage === 'loading'
        ? '소스 후보 찾는 중'
        : repositoryUnanswered.length > 0
          ? `${repositoryUnanswered.length}개 소스 요청 대기`
          : 'OCP 자료 찾기 준비됨';
  const bookFactoryStatusClass = factoryLane === 'user'
    ? pipelineStage === 'error'
      ? 'error'
      : pipelineStage === 'topology_failed'
        ? 'error'
      : pipelineStage === 'index_deferred' || pipelineStage === 'topology_deferred' || (pipelineStage === 'gold_build' && !isProcessing)
        ? 'warning'
      : pipelineStage === 'done' || pipelineStage === 'topology_ready'
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
  const bookFactoryModeSummary = activeWikiScope === 'uploads'
    ? `${userUploadDocumentRows.length.toLocaleString()}개 업로드 문서 · ${(latestUploadIngest?.chunk_count ?? userUploadChunkCount).toLocaleString()}개 문서 조각`
    : activeWikiScope === 'customer'
      ? `${customerDocumentRows.length.toLocaleString()}개 고객사 문서 · ${filteredCustomerDocumentRows.length.toLocaleString()}개 표시`
      : `${repositoryUnanswered.length}개 요청 · ${repositoryFavorites.length}개 저장 소스`;
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
    ? 'OCP 자료'
    : activeWikiScope === 'uploads'
      ? '내 업로드'
      : '고객사 문서';
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
  const activeWikiBaseDocumentRows = activeWikiScope === 'uploads'
    ? userUploadDocumentRows
    : activeWikiScope === 'customer'
      ? customerDocumentRows
      : officialDocumentRows;
  const activeWikiBookStats = useMemo(() => {
    const counts = {
      all: activeWikiBaseDocumentRows.length,
      indexed: 0,
      chunked: 0,
      readable: 0,
      needsRepair: 0,
      gold: 0,
    };
    activeWikiBaseDocumentRows.forEach((row) => {
      const chunkCount = Number(row.document.chunk_count || 0);
      if (Number.isFinite(chunkCount) && chunkCount > 0) {
        counts.chunked += 1;
      }
      if (documentIndexStatus(row) === 'indexed') {
        counts.indexed += 1;
      }
      if (isDocumentReadable(row.document)) {
        counts.readable += 1;
      } else {
        counts.needsRepair += 1;
      }
      const goldBuild = documentGoldBuildRun(row.document);
      if (goldBuild?.status === 'gold') {
        counts.gold += 1;
      }
    });
    return counts;
  }, [activeWikiBaseDocumentRows]);
  const topologyPreview = documentTopologyScope;
  const topologyLoading = !documentTopologyError && !topologyPreview;
  const topologyCoverageLabel = topologyPreview
    ? formatPercentRatio(topologyPreview.image_description_coverage)
    : '';
  const topologyHealthLabel = documentTopologyError
    ? '확인 실패'
    : topologyPreview
      ? topologyPreview.needs_review_count > 0
        ? `${topologyPreview.needs_review_count.toLocaleString()}개 보강 필요`
        : '지식망 준비됨'
      : '확인 중';
  const topologyBlockerText = documentTopologyError
    || topologyPreview?.blockers?.slice(0, 3).map((item) => `${item.message} ${item.count}`).join(' · ')
    || '';
  const displayedDocumentRows = repositoryPaneRows;
  const bookFactoryScopeLabel = activeWikiScope === 'official'
    ? 'OCP 자료'
    : activeWikiScope === 'uploads'
      ? '내 업로드'
      : '고객사 문서';
  const bookFactoryScopeDescription = activeWikiScope === 'official'
    ? '질문으로 부족한 OCP 공식 자료를 찾고, Bronze 원천 후보를 Gold Wiki 데이터로 승급시킵니다.'
    : activeWikiScope === 'uploads'
      ? '업로드 파일을 Bronze 시작점으로 받아 Silver 구조화, Gold 생성, Judge 합류까지 한 화면에서 봅니다.'
      : '고객/현장 문서를 Wiki Library 안에서 보강하고, 신뢰 가능한 Gold 데이터로 승급시킵니다.';
  const bookFactoryMainStatusLabel = activeWikiScope === 'customer'
    ? `${activeWikiBookStats.all.toLocaleString()}개 고객사 문서 · ${activeWikiBookStats.gold.toLocaleString()}개 Gold`
    : factoryLane === 'user'
      ? stageLabel(pipelineStage)
      : bookFactoryStatusLabel;
  const bookFactoryPipelineSteps = activeWikiScope === 'uploads'
    ? FACTORY_PIPELINE_STEPS.user
    : FACTORY_PIPELINE_STEPS.tools;
  const bookFactoryPipelineState: PipelineVisualState = activeWikiScope === 'uploads'
    ? uploadPipelineVisual
    : factoryDownloadList.some((item) => item.status === 'done') && !factoryDownloadList.some((item) => item.status === 'producing')
      ? { activeIndex: 3, completedIndex: 3 }
      : materializingOptionKey || factoryDownloadList.some((item) => item.status === 'producing')
        ? { activeIndex: 0, completedIndex: -1 }
        : { activeIndex: -1, completedIndex: -1 };
  const bookFactoryStageMeta = bookFactoryPipelineSteps.map((_, index) => {
    if (index === 0) {
      if (activeWikiScope === 'official') {
        return {
          count: officialSourceCandidates.length + sourceVerificationQueue.length,
          note: '원천 후보',
          action: repositoryStage === 'loading' ? 'OCP 자료 찾는 중' : 'OCP 자료 찾기',
        };
      }
      if (activeWikiScope === 'uploads') {
        return {
          count: latestUploadIngest ? 1 : userUploadDocumentRows.length,
          note: currentFile || '업로드 문서',
          action: isProcessing ? stageLabel(pipelineStage) : 'Upload File',
        };
      }
      return {
        count: customerDocumentRows.length,
        note: '고객사 원천',
        action: '보강 대상 확인',
      };
    }
    if (index === 1) {
      return {
        count: activeWikiBookStats.chunked,
        note: '구조화 완료',
        action: activeWikiBookStats.chunked > 0 ? '섹션 준비' : '구조화 대기',
      };
    }
    if (index === 2) {
      return {
        count: activeWikiBookStats.gold,
        note: 'Gold 준비',
        action: activeWikiBookStats.needsRepair > 0 ? `${activeWikiBookStats.needsRepair}개 수리 필요` : 'Gold 근거',
      };
    }
    if (index === 3) {
      return {
        count: activeWikiScope === 'official' ? sourceJudgeReports.length : activeWikiBookStats.readable,
        note: activeWikiScope === 'official' ? 'Judge 리포트' : '읽기 가능',
        action: latestSourceJudgeReport ? sourceJudgeVerdictLabel(latestSourceJudgeReport.overall_verdict) : 'REVIEW',
      };
    }
    return {
      count: Number(topologyPreview?.ready_count || 0),
      note: '지식망 스냅샷',
      action: topologyPreview?.needs_review_count ? '지식망 보강' : '연결 근거',
    };
  });
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

      <AppHeader
        currentPage="library"
        globalTheme={globalTheme}
        onOpenDashboard={() => navigate(ROUTES.pbsControlTower)}
        onOpenLibrary={() => navigate(ROUTES.pbsPlaybookLibrary)}
        onOpenStudio={() => navigate(ROUTES.pbsStudio)}
        onToggleGlobalTheme={toggleGlobalTheme}
        profile={{
          name: headerProfileName,
          status: headerProfileStatus,
          statusLabel: headerProfileStatusLabel,
          isLoading: isHeaderProfileLoading,
          onClick: () => navigate(ROUTES.pbsControlTower),
        }}
        title="WIKI Library"
      />

      <main className="library-main">
        <div className="library-shell">
          <div className="library-content-panel">
            <section id="system-data-board" className="library-runtime-board">
              <div className="library-runtime-board-head">
                <div>
                  <span className="factory-hub-eyebrow">System Data Board</span>
                  <h2>현재 시스템이 쓰는 데이터</h2>
                  <p>Wiki Library는 Postgres 문서, chunk, Qdrant 검색 인덱스가 서로 맞는지 확인하는 검수 화면입니다.</p>
                </div>
                <button type="button" className="library-runtime-refresh" onClick={() => { refreshDocumentRepositories(); refreshDocumentTopology(); refreshRuntimeHealth(); }}>
                  새로고침
                </button>
              </div>
              <div className="library-runtime-grid">
                <div className="library-runtime-card">
                  <span>OCP 자료</span>
                  <strong>{officialDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>고객사 문서</span>
                  <strong>{customerDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>내 업로드</span>
                  <strong>{userUploadDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>전체 문서</span>
                  <strong>{repositoryDocumentRows.length.toLocaleString()}</strong>
                </div>
                <div className="library-runtime-card">
                  <span>문서 조각</span>
                  <strong>{Number(dbCorpusChunks || 0).toLocaleString()}</strong>
                  <em>
                    OCP {Number(officialDbChunks || 0).toLocaleString()} · 고객사 {Number(customerDbChunks || 0).toLocaleString()}
                  </em>
                  <em>{qdrantEntryCount.toLocaleString()}개 Qdrant 항목</em>
                </div>
                <div className={`library-runtime-card ${qdrantCorpusInSync ? 'ok' : 'warning'}`}>
                  <span>Qdrant 포인트</span>
                  <strong>{typeof qdrantPoints === 'number' ? qdrantPoints.toLocaleString() : '-'}</strong>
                  <em>
                    {qdrantCorpusInSync
                      ? `${qdrantEntryCount.toLocaleString()}개 문서 조각 연결됨`
                      : typeof qdrantIndexedVectors === 'number'
                        ? `내부 벡터 인덱스 ${qdrantIndexedVectors.toLocaleString()}개`
                        : runtimeQdrant?.status ?? '상태 불명'}
                  </em>
                </div>
                <div className={`library-runtime-card ${isNotCertifiable ? 'danger' : 'ok'}`}>
                  <span>검증 상태</span>
                  <strong>{isNotCertifiable ? '검증 불가' : '검증 통과'}</strong>
                  <em>
                    {isNotCertifiable
                      ? `${certificationBlockers.length.toLocaleString()}개 차단 항목`
                      : `${goldPlaybookCount.toLocaleString()}개 Gold 통과`}
                  </em>
                </div>
              </div>
              <div className="library-board-tabs" aria-label="Wiki scope">
                <span className="library-board-tabs-label">WIKI</span>
                <button
                  type="button"
                  className={`library-board-tab ${activeWikiScope === 'official' ? 'active' : ''}`}
                  aria-pressed={activeWikiScope === 'official'}
                  onClick={() => {
                    setLibraryScopeFilter('official_docs');
                    setFactoryLane('tools');
                    navigate('/playbook-library?scope=official&lane=tools');
                  }}
                >
                  <Database size={15} />
                  <span>OCP 자료</span>
                  <strong>{officialDocumentRows.length.toLocaleString()}</strong>
                </button>
                <button
                  type="button"
                  className={`library-board-tab ${activeWikiScope === 'customer' ? 'active' : ''}`}
                  aria-pressed={activeWikiScope === 'customer'}
                  onClick={() => {
                    setLibraryScopeFilter('study_docs');
                    setFactoryLane('tools');
                    navigate('/playbook-library?scope=customer&lane=customer');
                  }}
                >
                  <FileText size={15} />
                  <span>고객사 문서</span>
                  <strong>{customerDocumentRows.length.toLocaleString()}</strong>
                </button>
                <button
                  type="button"
                  className={`library-board-tab ${activeWikiScope === 'uploads' ? 'active' : ''}`}
                  aria-pressed={activeWikiScope === 'uploads'}
                  onClick={() => {
                    setLibraryScopeFilter('user_upload');
                    setFactoryLane('user');
                    navigate('/playbook-library?scope=uploads&lane=uploads');
                  }}
                >
                  <UploadCloud size={15} />
                  <span>내 업로드</span>
                  <strong>{userUploadDocumentRows.length.toLocaleString()}</strong>
                </button>
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
              {certificationBlockerDetails.length > 0 && (
                <details className="certification-worklist">
                  <summary className="certification-worklist-head">
                    <span>검증 불가 이유와 작업 목록</span>
                    <strong>{certificationBlockerDetails.length.toLocaleString()}개 차단 항목</strong>
                  </summary>
                  <div className="certification-worklist-grid">
                    {certificationBlockerDetails.map((detail) => (
                      <article key={detail.blocker} className="certification-worklist-card">
                        <div className="certification-worklist-card-head">
                          <span>{certificationBlockerOwnerLabel(detail.owner)}</span>
                          <strong>{certificationBlockerLabel(detail.blocker)}</strong>
                        </div>
                        <p><b>원인: </b>{detail.root_cause}</p>
                        <p><b>조치: </b>{detail.fix_path}</p>
                        <code>{detail.verification_command}</code>
                      </article>
                    ))}
                  </div>
                </details>
              )}
            </section>

            <section className="wiki-library-overview box-container" aria-label="Wiki Library output">
              <div className="wiki-library-overview-head">
                <div>
                  <span className="factory-hub-eyebrow">Wiki Library</span>
                  <h2>{bookFactoryScopeLabel}</h2>
                  <p>{repositoryPaneDescription}</p>
                </div>
                <div className="wiki-library-overview-actions">
                  <span className="operational-library-count">
                    {displayedDocumentRows.length.toLocaleString()}개 표시 / 전체 {activeWikiBookStats.all.toLocaleString()}개 문서
                  </span>
                  <button type="button" className="library-dashboard-link" onClick={refreshDocumentRepositories}>
                    새로고침
                  </button>
                </div>
              </div>
              <div className="wiki-library-status-grid">
                <div className="wiki-library-status-card active">
                  <span>문서</span>
                  <strong>{activeWikiBookStats.all.toLocaleString()}</strong>
                  <em>{activeWikiBookStats.indexed.toLocaleString()}개 인덱싱됨</em>
                </div>
                <div className="wiki-library-status-card wiki-library-status-card--gold">
                  <span>Gold 준비됨</span>
                  <strong>{activeWikiBookStats.gold.toLocaleString()}</strong>
                  <em>신뢰 가능한 위키 데이터</em>
                </div>
                <div className="wiki-library-status-card">
                  <span>읽기 가능</span>
                  <strong>{activeWikiBookStats.readable.toLocaleString()}</strong>
                  <em>Read / Ask 가능</em>
                </div>
                <div className="wiki-library-status-card wiki-library-status-card--warning">
                  <span>수리 필요</span>
                  <strong>{activeWikiBookStats.needsRepair.toLocaleString()}</strong>
                  <em>차단 또는 대기 중</em>
                </div>
              </div>
              <section className="library-topology-preview" aria-label="지식망 프리뷰">
                <div className="library-topology-preview-head">
                  <div>
                    <span className="factory-hub-eyebrow">지식망 프리뷰</span>
                    <h3>현재 범위의 지식망 상태</h3>
                    <p>문서가 단순 목록이 아니라 개념, 명령어, 절차, 이미지 근거로 연결되는지 확인합니다.</p>
                  </div>
                  <strong className={topologyLoading ? 'loading' : topologyPreview?.needs_review_count ? 'warning' : documentTopologyError ? 'danger' : 'ok'}>
                    {topologyHealthLabel}
                  </strong>
                </div>
                <div className="library-topology-metrics">
                  <span><b>{topologyPreview ? Number(topologyPreview.ready_count || 0).toLocaleString() : '-'}</b> 준비됨</span>
                  <span><b>{Number(topologyPreview?.node_count || 0).toLocaleString()}</b> 노드</span>
                  <span><b>{Number(topologyPreview?.edge_count || 0).toLocaleString()}</b> 관계</span>
                  <span><b>{Number(topologyPreview?.concept_count || 0).toLocaleString()}</b> 개념</span>
                  <span><b>{Number(topologyPreview?.command_count || 0).toLocaleString()}</b> 명령어</span>
                  <span><b>{topologyCoverageLabel || '-'}</b> 이미지 설명</span>
                </div>
                {topologyBlockerText ? (
                  <div className="library-topology-blockers">
                    <AlertCircle size={15} />
                    <span>{topologyBlockerText}</span>
                  </div>
                ) : topologyLoading ? (
                  <div className="library-topology-ok">
                    <Clock3 size={15} />
                    <span>현재 범위의 지식망 스냅샷을 확인하고 있습니다.</span>
                  </div>
                ) : (
                  <div className="library-topology-ok">
                    <CheckCircle2 size={15} />
                    <span>현재 범위의 지식망 스냅샷이 재사용 가능한 상태입니다.</span>
                  </div>
                )}
              </section>
            </section>

                  <div className="repository-view">
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={DOCUMENT_INGEST_UPLOAD_ACCEPT}
              onChange={handleUpload}
            />

            <section id="book-factory" className="pipeline-section box-container factory-workbench-section factory-workbench-section--secondary book-factory-main">
              <div className="factory-workbench-top">
                <div className="factory-workbench-headline">
                  <span className="factory-hub-eyebrow">WIKI Growth Loop</span>
                  <div className="factory-workbench-title-row">
                    <h2>Book Factory</h2>
                    <span className="factory-workbench-title-tag">
                      {bookFactoryScopeLabel}
                    </span>
                  </div>
                  <p className="text-muted">
                    {bookFactoryScopeDescription}
                  </p>
                </div>
                <div className="factory-workbench-controls">
                  <div className="factory-mode-toggle" role="group" aria-label="Book Factory mode">
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
                    ) : activeWikiScope === 'official' && repositoryStage === 'loading' ? (
                      <Loader2 size={14} className="spin-icon" />
                    ) : (
                      <div className={`status-dot ${bookFactoryStatusClass === 'done' ? 'done' : 'pulsing'}`}></div>
                    )}
                    <span>{bookFactoryMainStatusLabel}</span>
                  </div>
                </div>
              </div>

              <div className="factory-workbench-toolbar">
                <div className="factory-entry-caption">
                  <span>{bookFactoryModeSummary}</span>
                  <span>·</span>
                  <span>
                    {bookFactoryScopeDescription}
                  </span>
                </div>
              </div>

              <section className={`book-factory-primary-action book-factory-primary-action--${activeWikiScope}`}>
                {activeWikiScope === 'official' ? (
                  <>
                    <div className="book-factory-primary-copy">
                      <span>Primary Action</span>
                      <strong>OCP 자료 찾기</strong>
                      <p>답하지 못한 질문에서 공식 레포와 공식 문서 후보를 찾아 Bronze 원천 후보로 올립니다.</p>
                    </div>
                    <form
                      className="book-factory-primary-form"
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
                          placeholder="예: 호스팅 컨트롤 플레인 아키텍처"
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
                        <span>{repositoryStage === 'loading' ? '찾는 중...' : 'OCP 자료 찾기'}</span>
                      </button>
                    </form>
                  </>
                ) : activeWikiScope === 'uploads' ? (
                  <>
                    <div className="book-factory-primary-copy">
                      <span>Primary Action</span>
                      <strong>Upload File</strong>
                      <p>파일 업로드가 Bronze 시작점입니다. 업로드 후 Silver 구조화, Gold build, Judge 합류 상태가 이어집니다.</p>
                    </div>
                    <button
                      type="button"
                      className="upload-trigger-btn"
                      onClick={() => openUserDocsUpload(true)}
                      disabled={isProcessing}
                    >
                      {isProcessing ? <Loader2 size={16} className="spin-icon" /> : <UploadCloud size={16} />}
                      <span>{isProcessing ? '처리 중...' : 'Upload File'}</span>
                    </button>
                  </>
                ) : (
                  <>
                    <div className="book-factory-primary-copy">
                      <span>Primary Action</span>
                      <strong>고객/현장 문서 보강</strong>
                      <p>고객 문서의 parse, index, Gold build, Judge 상태를 기준으로 보강 대상을 확인합니다.</p>
                    </div>
                    <button type="button" className="library-dashboard-link" onClick={refreshDocumentRepositories}>
                      상태 새로고침
                    </button>
                  </>
                )}
              </section>

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

              {factoryLane === 'user' && pipelineWarningMsg && !errorMsg && (
                <div className="pipeline-warning-banner">
                  <AlertCircle size={14} />
                  <span>{pipelineWarningMsg}</span>
                </div>
              )}

              {factoryLane === 'user' && latestUploadIngest?.index?.status === 'deferred' && latestUploadIngest.persisted?.document_source_id && (
                <div className="pipeline-retry-banner">
                  <div>
                    <strong>색인 보류</strong>
                    <span>문서는 저장됐습니다. 임베딩 서버가 복구되면 Qdrant 색인을 다시 실행할 수 있습니다.</span>
                  </div>
                  <button type="button" onClick={handleUploadIndexRetry} disabled={indexRetrying}>
                    {indexRetrying ? <Loader2 size={14} className="spin-icon" /> : <Cpu size={14} />}
                    <span>{indexRetrying ? '재시도 중...' : '색인 재시도'}</span>
                  </button>
                </div>
              )}

              {factoryLane === 'user' && uploadEventTrace.length > 0 && (
                <div className="upload-event-trace">
                  <div className="upload-event-trace-head">
                    <strong>처리 이벤트 원장</strong>
                    <span>서버가 기록한 이벤트 시각과 payload 기준으로만 단계가 바뀝니다.</span>
                  </div>
                  <ol>
                    {uploadEventTrace.map((item) => (
                      <li key={item.id} className={`upload-event-trace-item upload-event-trace-item--${item.tone}`}>
                        <span className="upload-event-trace-dot" aria-hidden="true" />
                        <div>
                          <strong>{item.label}</strong>
                          <p>{item.detail}</p>
                        </div>
                        <time>{formatServerEventTime(item.occurredAt) || item.time}</time>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              <div className="pipeline-visualizer book-factory-pipeline" ref={activeWikiScope === 'uploads' ? pipelineRef : undefined}>
                {bookFactoryPipelineSteps.map((step, index) => (
                  <React.Fragment key={`book-factory:${step.badge}`}>
                    <div
                      className={`pipeline-step ${index <= bookFactoryPipelineState.completedIndex ? 'completed' : ''
                        } ${index === bookFactoryPipelineState.activeIndex ? 'active' : ''} ${index === 3 && bookFactoryPipelineState.activeIndex === 3 ? 'final' : ''
                        } ${index === bookFactoryPipelineState.errorIndex ? 'error' : ''
                        } ${index === bookFactoryPipelineState.deferredIndex ? 'deferred' : ''
                        }`}
                    >
                      <div className="step-badge">{step.badge}</div>
                      <div className="step-icon">
                        {index === 0
                          ? activeWikiScope === 'uploads'
                            ? <UploadCloud />
                            : <Search />
                          : index === 1
                            ? <HardDrive />
                            : index === 2
                              ? <Cpu />
                              : <BookOpen />}
                      </div>
                      <div className="step-info">
                        <h4>{step.title}</h4>
                        <p>{step.description}</p>
                        <span className="book-factory-step-meta">
                          <strong>{bookFactoryStageMeta[index].count.toLocaleString()}</strong>
                          <em>{bookFactoryStageMeta[index].note}</em>
                        </span>
                        <small>{bookFactoryStageMeta[index].action}</small>
                      </div>
                    </div>
                    {index < bookFactoryPipelineSteps.length - 1 && (
                      <div
                        className={`pipeline-connector ${index < bookFactoryPipelineState.completedIndex ? 'filled' : ''
                          } ${activeWikiScope === 'uploads'
                            ? uploadStreamActive && uploadPipelineRunningIndex >= 0 && index === uploadPipelineRunningIndex - 1
                              ? 'flowing'
                              : ''
                            : index === bookFactoryPipelineState.activeIndex - 1
                              ? 'flowing'
                              : ''}`}
                      >
                        <div className="flow-particle"></div>
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>

              {factoryLane === 'user' && latestUploadIngest?.gold_build_run && (
                <div className={`gold-build-run-panel gold-build-run-panel--${goldBuildTone(latestUploadIngest.gold_build_run)}`}>
                  <div className="gold-build-run-head">
                    <div>
                      <span className="factory-hub-eyebrow">Judge 판정</span>
                      <h3>{goldBuildStatusLabel(latestUploadIngest.gold_build_run)}</h3>
                      <p>{goldBuildSummary(latestUploadIngest.gold_build_run)}</p>
                    </div>
                    <span>{latestUploadIngest.gold_build_run.final_grade}</span>
                  </div>
                  {goldBuildBlockingMessage(latestUploadIngest.gold_build_run) && (
                    <div className="gold-build-blocking-message">
                      <AlertCircle size={15} />
                      <span>{goldBuildBlockingMessage(latestUploadIngest.gold_build_run)}</span>
                    </div>
                  )}
                  {latestUploadIngest.gold_build_run.stage_results.length > 0 && (
                    <div className="gold-build-stage-strip">
                      {latestUploadIngest.gold_build_run.stage_results.map((stage) => (
                        <span
                          key={stage.stage}
                          className={`gold-build-stage-pill gold-build-stage-pill--${String(stage.status || '').trim()}`}
                          title={stage.detail}
                        >
                          <strong>{goldBuildStageLabel(stage.stage)}</strong>
                          <em>{goldBuildStageStatusLabel(stage.status)}</em>
                        </span>
                      ))}
                    </div>
                  )}
                  {latestUploadIngest.gold_build_run.repair_actions.length > 0 && (
                    <div className="gold-build-repair-list">
                      {latestUploadIngest.gold_build_run.repair_actions.slice(0, 4).map((action) => (
                        <article key={`${action.id}-${action.diagnostic}`}>
                          <strong>{repairActionTitle(action)}</strong>
                          <span>{repairActionStatusLabel(action.status)}</span>
                          <p>{repairActionSummary(action)}</p>
                          {repairActionNextAction(action) && <em>{repairActionNextAction(action)}</em>}
                        </article>
                      ))}
                    </div>
                  )}
                  {latestUploadIngest.persisted && (latestUploadIngest.source_scope || 'user_upload') === 'user_upload' && goldBuildHasCodeLoss(latestUploadIngest.gold_build_run) && (
                    <button
                      type="button"
                      className="gold-build-repair-cta"
                      disabled={codeRepairingDocumentId === latestUploadIngest.persisted.document_source_id}
                      onClick={() => {
                        const document: DocumentRepositoryDocument = {
                          document_source_id: latestUploadIngest.persisted?.document_source_id || '',
                          parsed_document_id: latestUploadIngest.persisted?.parsed_document_id || '',
                          title: latestUploadIngest.filename,
                          filename: latestUploadIngest.filename,
                          source_kind: 'upload',
                          mime_type: latestUploadIngest.mime_type,
                          source_scope: latestUploadIngest.source_scope || 'user_upload',
                          visibility: latestUploadIngest.visibility || 'private_user',
                          metadata: { document_format: latestUploadIngest.document_format },
                          gold_build_run: latestUploadIngest.gold_build_run,
                          parse_status: 'parsed',
                          chunk_count: latestUploadIngest.chunk_count,
                          indexed_chunk_count: latestUploadIngest.index?.indexed_count || 0,
                          created_at: '',
                          updated_at: '',
                        };
                        void handleCodeBlockRepair(document);
                      }}
                    >
                      {codeRepairingDocumentId === latestUploadIngest.persisted.document_source_id ? <Loader2 size={14} className="spin-icon" /> : <Wrench size={14} />}
                      <span>코드블록 자동 수리</span>
                    </button>
                  )}
                  {latestUploadIngest.gold_build_run.gold_evidence.length > 0 && (
                    <div className="gold-build-evidence">
                      {latestUploadIngest.gold_build_run.gold_evidence.slice(0, 6).map((item) => (
                        <span key={item}>{item}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {factoryRunMode === 'manual' && activeWikiScope !== 'customer' && (
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

              {factoryRunMode === 'manual' && activeWikiScope === 'customer' && (
                <div className="factory-manual-workbench factory-manual-workbench--customer">
                  <div className="factory-manual-workbench-header">
                    <div className="factory-manual-note-copy">
                      <span className="factory-manual-note-eyebrow">Manual Mode</span>
                      <strong>고객/현장 문서 수동 검수</strong>
                      <p>
                        고객 scope에서는 OCP 공식 catalog가 아니라 현재 고객 문서의 parse, index, Gold build,
                        Judge 상태를 직접 확인합니다.
                      </p>
                    </div>
                  </div>
                  <div className="factory-manual-customer-grid">
                    <article>
                      <span>Documents</span>
                      <strong>{activeWikiBookStats.all.toLocaleString()}</strong>
                      <p>{activeWikiBookStats.indexed.toLocaleString()} indexed</p>
                    </article>
                    <article>
                      <span>Readable</span>
                      <strong>{activeWikiBookStats.readable.toLocaleString()}</strong>
                      <p>Read / Ask 가능한 문서</p>
                    </article>
                    <article>
                      <span>Needs Repair</span>
                      <strong>{activeWikiBookStats.needsRepair.toLocaleString()}</strong>
                      <p>parse · index · gold_build · judge 확인 필요</p>
                    </article>
                    <article>
                      <span>Gold</span>
                      <strong>{activeWikiBookStats.gold.toLocaleString()}</strong>
                      <p>신뢰 데이터로 승급된 문서</p>
                    </article>
                  </div>
                </div>
              )}

              <div className="pipeline-details">
                <div className="log-container">
                  <div className="log-header">{factoryLane === 'tools' ? 'Book Factory 처리 로그' : '최근 처리 로그'}</div>
                  {logs.length === 0 && (
                    <div className="log-empty">
                      {factoryLane === 'tools' ? '생산을 시작하면 단계별 로그가 여기에 표시됩니다.' : '아직 처리 내역이 없습니다.'}
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

            <section className="library-data-toolbar" aria-label="Document filters">
              <label className="library-filter-search">
                <Search size={16} />
                <input
                  type="search"
                  value={librarySearchQuery}
                  onChange={(event) => setLibrarySearchQuery(event.target.value)}
                  placeholder="문서, 소스, 상태 검색"
                />
              </label>
              <select
                value={libraryQualityFilter}
                onChange={(event) => setLibraryQualityFilter(event.target.value as LibraryQualityFilter)}
                aria-label="품질 필터"
              >
                <option value="all">전체 품질</option>
                <option value="gold">Gold 준비됨</option>
                <option value="readable">읽기 가능</option>
                <option value="needs_repair">수리 필요</option>
              </select>
              <select
                value={libraryIndexFilter}
                onChange={(event) => setLibraryIndexFilter(event.target.value as LibraryIndexFilter)}
                aria-label="인덱스 필터"
              >
                <option value="all">전체 인덱스 상태</option>
                <option value="indexed">인덱싱됨</option>
                <option value="partial">부분 인덱싱</option>
                <option value="not_indexed">미인덱싱</option>
              </select>
            </section>

            <section className="library-repository-strip box-container wiki-document-output">
              <div className="section-header">
                <div>
                  <span className="factory-hub-eyebrow">문서</span>
                  <h2>{repositoryPaneTitle} 문서</h2>
                  <p className="text-muted">{repositoryPaneDescription}</p>
                </div>
                <div className="wiki-document-output-actions">
                  <span className="operational-library-count">
                    {repositoryPaneRows.length.toLocaleString()}개 표시 / 전체 {repositoryPaneTotal.toLocaleString()}개 문서
                  </span>
                  <button type="button" className="library-dashboard-link" onClick={refreshDocumentRepositories}>
                    새로고침
                  </button>
                </div>
              </div>

              {repositoryPaneRows.length === 0 ? (
                <div className="repo-empty">
                  <Database size={28} />
                  <p>{repositoryPaneEmptyMessage}</p>
                </div>
              ) : (
                <div className="operational-library-grid wiki-document-output-grid">
                  {repositoryPaneRows.map(({ repository, document, categoryKey }) => {
                    const row = { repository, document, categoryKey };
                    const runtimeBook = operationalWikiBookBySlug.get(documentBookSlug(row));
                    const goldBuild = documentGoldBuildRun(document);
                    const indexStatus = documentIndexStatus(row);
                    const readable = isDocumentReadable(document);
                    const showDocumentRecoveryActions = document.source_scope === 'user_upload' && !readable;
                    return (
                      <article
                        key={document.document_source_id}
                        className="operational-library-card operational-library-card--document wiki-document-output-card"
                      >
                        <div className="operational-card-open">
                          <span className="operational-library-card-badge">
                            {document.source_scope || repository.visibility || repository.repository_kind}
                          </span>
                          <strong>{document.title || document.filename}</strong>
                          <span className="operational-card-open-subtitle">
                            {document.chunk_count.toLocaleString()} chunks / {document.indexed_chunk_count.toLocaleString()} indexed
                          </span>
                          <div className="library-document-chip-row">
                            {documentQualityChips(row, runtimeBook).map((chip) => (
                              <span key={chip} className="library-document-chip">{chip}</span>
                            ))}
                            <span className={`library-document-chip library-document-chip--${indexStatus}`}>
                              {indexStatusLabel(indexStatus)}
                            </span>
                          </div>
                          {!readable && (
                            <span className="library-document-read-block">
                              <AlertCircle size={13} />
                              {documentReadBlockReason(document)}
                            </span>
                          )}
                          {goldBuild && (
                            <div className={`gold-build-mini gold-build-mini--${goldBuildTone(goldBuild)}`}>
                              <span>{goldBuildStatusLabel(goldBuild)}</span>
                              <p>{goldBuildSummary(goldBuild)}</p>
                            </div>
                          )}
                          {goldBuildHasCodeLoss(goldBuild) && (
                            <div className="gold-build-visible-repair-note">
                              <strong>원인: {codeLossRepairSummary(goldBuild)}</strong>
                              <span>조치: {codeLossRepairNextAction(goldBuild)}</span>
                            </div>
                          )}
                        </div>
                        <div className="library-document-actions">
                          {document.source_scope === 'user_upload' && goldBuildHasCodeLoss(goldBuild) && (
                            <button
                              type="button"
                              className="library-document-chat-btn library-document-repair-btn"
                              title={codeLossRepairSummary(goldBuild)}
                              disabled={codeRepairingDocumentId === document.document_source_id}
                              onClick={() => {
                                void handleCodeBlockRepair(document);
                              }}
                            >
                              {codeRepairingDocumentId === document.document_source_id ? <Loader2 size={14} className="spin-icon" /> : <Wrench size={14} />}
                              <span>{codeRepairingDocumentId === document.document_source_id ? '수리 중' : '코드블록 자동 수리'}</span>
                            </button>
                          )}
                          {showDocumentRecoveryActions && (
                            <>
                              <button
                                type="button"
                                className="library-document-chat-btn library-document-repair-btn"
                                disabled={documentRecoveryAction?.documentSourceId === document.document_source_id}
                                onClick={() => {
                                  void handleDocumentQualityRecheck(document);
                                }}
                              >
                                {documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'quality'
                                  ? <Loader2 size={14} className="spin-icon" />
                                  : <ShieldCheck size={14} />}
                                <span>{documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'quality' ? '검사 중' : '품질 재검사'}</span>
                              </button>
                              <button
                                type="button"
                                className="library-document-chat-btn library-document-repair-btn"
                                disabled={documentRecoveryAction?.documentSourceId === document.document_source_id}
                                onClick={() => {
                                  void handleDocumentTopologyRetry(document);
                                }}
                              >
                                {documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'topology'
                                  ? <Loader2 size={14} className="spin-icon" />
                                  : <Cpu size={14} />}
                                <span>{documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'topology' ? '생성 중' : '지식망 재생성'}</span>
                              </button>
                            </>
                          )}
                          <button
                            type="button"
                            className={`library-document-chat-btn ${readable ? '' : 'library-document-chat-btn--blocked'}`}
                            title={documentReadBlockReason(document) || 'Read document'}
                            disabled={!readable}
                            onClick={() => {
                              if (readable) {
                                void openDocumentReader(repository, document);
                              }
                            }}
                          >
                            <BookOpen size={14} />
                            <span>{readable ? 'Read' : 'Needs repair'}</span>
                          </button>
                          <button
                            type="button"
                            className={`library-document-chat-btn ${readable ? '' : 'library-document-chat-btn--blocked'}`}
                            title={documentReadBlockReason(document) || 'Ask in Studio'}
                            disabled={!readable}
                            onClick={() => {
                              if (readable) {
                                openDocumentInChat(repository, document, categoryKey);
                              }
                            }}
                          >
                            <MessageSquare size={14} />
                            <span>{readable ? 'Ask in Studio' : 'Repair before ask'}</span>
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>

            {activeWikiScope === 'official' && (
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
                                      {item.source_request_id ? <span>request {item.source_request_id.slice(0, 8)}</span> : null}
                                      {item.gold_build_status ? <span>{item.gold_build_status}</span> : null}
                                      {item.warnings.length > 0 ? <span>{item.warnings[0]}</span> : null}
                                    </div>
                                    {item.gold_build_next_action && (
                                      <div className="repo-unanswered-next-action">{item.gold_build_next_action}</div>
                                    )}
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
                          <span className="factory-hub-eyebrow">OCP 자료 찾기</span>
                          <h2>OCP 공식 자료 찾기</h2>
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
                      <p>현재 저장된 User Library 책이 없습니다.</p>
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

{activeWikiScope === 'official' && (
          <details className="library-advanced-details">
            <summary>
              <span>Operational Library Detail</span>
              <strong>{approvedWikiRuntimeBooks.toLocaleString()} runtime books</strong>
            </summary>
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
                  {activeWikiDocumentRows.map(({ repository, document, categoryKey }) => {
                    const goldBuild = documentGoldBuildRun(document);
                    const readable = isDocumentReadable(document);
                    const showDocumentRecoveryActions = document.source_scope === 'user_upload' && !readable;
                    return (
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
                        {!readable && (
                          <span className="library-document-read-block">
                            <AlertCircle size={13} />
                            {documentReadBlockReason(document)}
                          </span>
                        )}
                        {goldBuild && (
                          <div className={`gold-build-mini gold-build-mini--${goldBuildTone(goldBuild)}`}>
                            <span>{goldBuildStatusLabel(goldBuild)}</span>
                            <p>{goldBuildSummary(goldBuild)}</p>
                          </div>
                        )}
                        {goldBuildHasCodeLoss(goldBuild) && (
                          <div className="gold-build-visible-repair-note">
                            <strong>원인: {codeLossRepairSummary(goldBuild)}</strong>
                            <span>조치: {codeLossRepairNextAction(goldBuild)}</span>
                          </div>
                        )}
                      </div>
                      <div className="library-document-actions">
                        {document.source_scope === 'user_upload' && goldBuildHasCodeLoss(goldBuild) && (
                          <button
                            type="button"
                            className="library-document-chat-btn library-document-repair-btn"
                            title={codeLossRepairSummary(goldBuild)}
                            disabled={codeRepairingDocumentId === document.document_source_id}
                            onClick={() => {
                              void handleCodeBlockRepair(document);
                            }}
                          >
                            {codeRepairingDocumentId === document.document_source_id ? <Loader2 size={14} className="spin-icon" /> : <Wrench size={14} />}
                            <span>{codeRepairingDocumentId === document.document_source_id ? '수리 중' : '코드블록 자동 수리'}</span>
                          </button>
                        )}
                        {showDocumentRecoveryActions && (
                          <>
                            <button
                              type="button"
                              className="library-document-chat-btn library-document-repair-btn"
                              disabled={documentRecoveryAction?.documentSourceId === document.document_source_id}
                              onClick={() => {
                                void handleDocumentQualityRecheck(document);
                              }}
                            >
                              {documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'quality'
                                ? <Loader2 size={14} className="spin-icon" />
                                : <ShieldCheck size={14} />}
                              <span>{documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'quality' ? '검사 중' : '품질 재검사'}</span>
                            </button>
                            <button
                              type="button"
                              className="library-document-chat-btn library-document-repair-btn"
                              disabled={documentRecoveryAction?.documentSourceId === document.document_source_id}
                              onClick={() => {
                                void handleDocumentTopologyRetry(document);
                              }}
                            >
                              {documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'topology'
                                ? <Loader2 size={14} className="spin-icon" />
                                : <Cpu size={14} />}
                              <span>{documentRecoveryAction?.documentSourceId === document.document_source_id && documentRecoveryAction.action === 'topology' ? '생성 중' : '지식망 재생성'}</span>
                            </button>
                          </>
                        )}
                        <button
                          type="button"
                          className={`library-document-chat-btn ${readable ? '' : 'library-document-chat-btn--blocked'}`}
                          title={documentReadBlockReason(document) || 'Read document'}
                          disabled={!readable}
                          onClick={() => {
                            if (readable) {
                              void openDocumentReader(repository, document);
                            }
                          }}
                        >
                          <BookOpen size={14} />
                          <span>{readable ? 'Read' : 'Needs repair'}</span>
                        </button>
                        <button
                          type="button"
                          className={`library-document-chat-btn ${readable ? '' : 'library-document-chat-btn--blocked'}`}
                          title={documentReadBlockReason(document) || 'Ask this document'}
                          disabled={!readable}
                          onClick={() => {
                            if (readable) {
                              openDocumentInChat(repository, document, categoryKey);
                            }
                          }}
                        >
                          <MessageSquare size={14} />
                          <span>{readable ? 'Ask this document' : 'Repair before ask'}</span>
                        </button>
                      </div>
                    </article>
                    );
                  })}
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
                    <span className="operational-shelf-eyebrow">Gold Build Repair Queue</span>
                    <h2>Gold로 만들기 위한 수리 대상 {operationalWikiRecoveryRows.length.toLocaleString()}권</h2>
                    <p>이 목록은 탈락장이 아니라 수리 지시서입니다. blocker를 고치고 재빌드하면 운영 위키 Gold로 승급됩니다.</p>
                  </div>
                  <span className="gold-recovery-status">Repair Loop</span>
                </div>
                <div className="gold-recovery-grid">
                  {operationalWikiRecoveryRows.map((book) => (
                    <article key={`recovery-${book.book_slug}`} className="gold-recovery-card">
                      <div className="gold-recovery-card-head">
                        <span>{book.source_grade || 'Gold'} → Gold Build Repair</span>
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
                      {book.repair_actions && book.repair_actions.length > 0 && (
                        <div className="gold-build-repair-list gold-build-repair-list--compact">
                          {book.repair_actions.slice(0, 3).map((action) => (
                            <article key={`${book.book_slug}-${action.id}-${action.diagnostic}`}>
                              <strong>{repairActionTitle(action)}</strong>
                              <span>{repairActionStatusLabel(action.status)}</span>
                              <p>{repairActionSummary(action)}</p>
                              {repairActionNextAction(action) && <em>{repairActionNextAction(action)}</em>}
                            </article>
                          ))}
                        </div>
                      )}
                      {book.gold_recovery_blocking_check && (
                        <div className="gold-recovery-check">
                          <span>Blocking check</span>
                          <code>{book.gold_recovery_blocking_check}</code>
                        </div>
                      )}
                      {book.gold_recovery_rerun_command && (
                        <div className="gold-recovery-check">
                          <span>Rerun</span>
                          <code>{book.gold_recovery_rerun_command}</code>
                        </div>
                      )}
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
          </details>
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
                    viewerTheme={globalTheme}
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
        <div className="preview-overlay document-reader-overlay" data-reader-theme={globalTheme} onClick={closeDocumentReader}>
          <div className="preview-popover preview-popover-chunk document-reader-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <span className="document-reader-eyebrow">문서 리더</span>
                <h3>{documentReader.payload?.title || documentReader.source.title || documentReader.source.filename}</h3>
                <div className="preview-header-meta">
                  <span>{documentReaderScopeLabel(documentReader.source.source_scope, documentReader.repository.title)}</span>
                  <span>{documentReader.repository.title}</span>
                  <span>
                    {(documentReader.payload?.chunks.length ?? 0).toLocaleString()}
                    /
                    {(documentReader.payload?.total_chunks ?? documentReader.source.chunk_count).toLocaleString()} 조각
                  </span>
                  <span>
                    {(documentReader.source.indexed_chunk_count || 0).toLocaleString()}개 색인
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
                      본문 {documentReader.payload.markdown_total_chars.toLocaleString()}자
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
                  <span>Studio에서 질문</span>
                </button>
                <button className="preview-close-btn" onClick={closeDocumentReader}><X size={18} /></button>
              </div>
            </div>
            <div className="metric-popover-body chunk-viewer-body document-reader-body">
              {documentReader.loading ? (
                <div className="preview-loading"><Loader2 size={20} className="spin-icon" /> 문서를 불러오는 중...</div>
              ) : documentReader.error && !documentReader.payload ? (
                <div className="preview-no-sections">{documentReader.error}</div>
              ) : documentReader.payload ? (
                <>
                  <DocumentReaderBookView
                    payload={documentReader.payload}
                    loadingMore={documentReader.loadingMore}
                    onLoadMore={() => { void loadMoreDocumentReader(); }}
                  />
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
                    viewerTheme={globalTheme}
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
