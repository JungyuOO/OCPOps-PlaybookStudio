export const RUNTIME_ORIGIN = (import.meta.env.VITE_RUNTIME_ORIGIN ?? '').trim().replace(/\/$/, '');
export const RUNTIME_EXTERNAL_ORIGIN = RUNTIME_ORIGIN || 'http://127.0.0.1:8765';
export const CUSTOMER_PACK_UPLOAD_ACCEPT = '.pdf,.md,.markdown,.docx,.pptx,.xlsx,.txt,.adoc,.asciidoc,.html,.htm,.png,.jpg,.jpeg,.webp';

export interface LibraryBookSourceOption {
  key: string;
  label: string;
  href: string;
  availability: 'available' | 'missing' | string;
  note: string;
  is_current?: boolean;
}

export interface LibraryBook {
  book_slug: string;
  title: string;
  grade: string;
  review_status: string;
  source_type: string;
  source_lane: string;
  section_count: number;
  code_block_count: number;
  viewer_path: string;
  source_url: string;
  updated_at: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  current_source_basis?: 'official_homepage' | 'official_repo' | 'unknown' | string;
  current_source_label?: string;
  source_options?: LibraryBookSourceOption[];
  source_collection?: string;
  source_origin_label?: string;
  source_origin_url?: string;
  draft_id?: string;
  chunk_count?: number;
  token_total?: number;
  command_chunk_count?: number;
  error_chunk_count?: number;
  materialized?: boolean;
  chunk_scope?: 'runtime' | 'customer_pack' | string;
  delete_target_kind?: string;
  delete_target_id?: string;
  delete_target_label?: string;
  corpus_chunk_count?: number;
  corpus_token_total?: number;
  corpus_materialized?: boolean;
  corpus_runtime_eligible?: boolean;
  corpus_vector_status?: string;
  chunk_type_breakdown?: Record<string, number>;
}

export interface LibraryBucket {
  selected_dir?: string;
  selected_path?: string;
  books: LibraryBook[];
}

export interface CorpusChunkRow {
  chunk_id: string;
  ordinal: number;
  chunk_type: string;
  token_count: number;
  chapter: string;
  section: string;
  section_path: string[];
  anchor: string;
  viewer_path: string;
  source_url: string;
  text: string;
  cli_commands: string[];
  error_strings: string[];
  k8s_objects: string[];
  operator_names: string[];
  verification_hints: string[];
}

export interface CorpusChunkViewerResponse {
  scope: 'runtime' | 'customer_pack' | string;
  scope_label: string;
  book_slug: string;
  title: string;
  draft_id?: string;
  document_viewer_path: string;
  source_lane: string;
  source_type: string;
  source_collection?: string;
  source_origin_label?: string;
  source_origin_url?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  vector_status?: string;
  corpus_runtime_eligible?: boolean;
  chunk_count: number;
  token_total: number;
  command_chunk_count: number;
  error_chunk_count: number;
  chunk_type_breakdown: Record<string, number>;
  chunks: CorpusChunkRow[];
}

export interface BuyerPacket {
  book_slug: string;
  title: string;
  review_status: string;
  viewer_path: string;
  source_url: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  approval_state?: string;
  publication_state?: string;
}

export interface BuyerPacketBucket {
  selected_dir: string;
  books: BuyerPacket[];
}

export interface BuyerPacketPreview {
  packet_id: string;
  title: string;
  purpose: string;
  status: string;
  markdown_path: string;
  json_path: string;
  body: string;
}

export interface ReleaseCandidateFreezeSummary {
  packet_id: string;
  title: string;
  viewer_path: string;
  freeze_date: string;
  current_stage: string;
  commercial_truth: string;
  runtime_count: number;
  active_group: string;
  product_gate_pass_rate: number | null;
  product_gate_pass_count: number;
  product_gate_scenario_count: number;
  promotion_gate_count: number;
  release_blocker_count: number;
  sell_now: string;
  do_not_sell_yet: string;
  close: string;
  exists: boolean;
  report_path: string;
}

export interface DataControlRoomSummary {
  known_book_count: number;
  approved_runtime_count: number;
  gold_book_count: number;
  manualbook_count: number;
  corpus_book_count?: number;
  customer_pack_runtime_book_count?: number;
  user_library_book_count?: number;
  user_library_corpus_book_count?: number;
  user_library_corpus_chunk_count?: number;
  gold_candidate_book_count?: number;
  approved_wiki_runtime_book_count?: number;
  wiki_navigation_backlog_count?: number;
  wiki_usage_signal_count?: number;
  product_gate_count?: number;
  buyer_packet_bundle_count?: number;
  release_candidate_freeze_ready?: boolean;
  product_gate_pass_rate?: number | null;
  topic_playbook_count: number;
  derived_playbook_count: number;
  playable_asset_count: number;
  answer_pass_rate: number;
}

export interface DataControlRoomResponse {
  active_pack: {
    pack_label: string;
    ocp_version: string;
    docs_language: string;
    viewer_path_prefix: string;
  };
  summary: DataControlRoomSummary;
  gate?: {
    status: string;
    release_blocking: boolean;
    reasons?: string[];
    summary?: {
      failed_validation_checks?: string[];
      failed_data_quality_checks?: string[];
    };
  };
  product_rehearsal?: {
    status: string;
    exists?: boolean;
    current_stage: string;
    scenario_count: number;
    pass_count: number;
    critical_scenario_pass_rate: number | null;
    blockers: string[];
  };
  known_books: LibraryBook[];
  gold_books: LibraryBook[];
  corpus: LibraryBucket;
  manualbooks: LibraryBucket;
  customer_pack_runtime_books?: LibraryBucket;
  user_library_books?: LibraryBucket;
  user_library_corpus?: LibraryBucket;
  gold_candidate_books?: LibraryBucket;
  approved_wiki_runtime_books?: LibraryBucket;
  wiki_navigation_backlog?: LibraryBucket;
  wiki_usage_signals?: LibraryBucket;
  product_gate?: LibraryBucket;
  buyer_packet_bundle?: BuyerPacketBucket;
  release_candidate_freeze?: ReleaseCandidateFreezeSummary;
  topic_playbooks: LibraryBucket;
  operation_playbooks: LibraryBucket;
  troubleshooting_playbooks: LibraryBucket;
  policy_overlay_books: LibraryBucket;
  synthesized_playbooks: LibraryBucket;
  source_of_truth_drift?: {
    status_alignment?: {
      mismatches?: string[];
    };
  };
}

export interface ChatCitation {
  index: number;
  book_slug: string;
  book_title?: string;
  section: string;
  section_path?: string;
  viewer_path: string;
  source_label?: string;
  source_collection?: string;
  pack_label?: string;
  source_lane?: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
}

export interface ChatTraceEvent {
  type?: string;
  step: string;
  label: string;
  status: string;
  detail?: string;
  timestamp_ms?: number;
  duration_ms?: number;
  meta?: Record<string, unknown>;
}

export interface ChatRelatedLink {
  label: string;
  href: string;
  kind: 'entity' | 'book' | string;
  summary?: string;
  source_lane?: string;
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
}

export type WikiInkTool = 'pen' | 'highlighter';
export type WikiInkColorId = 'cyan' | 'amber' | 'rose' | 'violet' | 'lime' | string;

export interface WikiInkStyle {
  id: WikiInkColorId;
  label: string;
  penColor: string;
  highlighterColor: string;
}

export interface WikiInkStroke {
  path: string;
  tool: WikiInkTool;
  style: WikiInkStyle;
}

export type WikiEditedTextTone = 'amber' | 'ink' | 'teal' | string;
export type WikiEditedTextSize = 'sm' | 'md' | 'lg' | string;
export type WikiEditedTextWeight = 'regular' | 'strong' | string;

export interface WikiEditedTextStyle {
  tone: WikiEditedTextTone;
  size: WikiEditedTextSize;
  weight: WikiEditedTextWeight;
}

export type WikiAnnotationTool = 'text' | WikiInkTool;
export type WikiTextAnnotationMode = 'add' | 'edit';

export interface WikiTextAnnotation {
  annotation_id: string;
  kind: WikiTextAnnotationMode;
  anchor: string;
  text: string;
  style: WikiEditedTextStyle;
  x_ratio?: number;
  y_ratio?: number;
  block_path?: string;
}

export type WikiOverlayKind = 'favorite' | 'check' | 'note' | 'ink' | 'recent_position' | 'edited_card';
export type WikiOverlayTargetKind = 'book' | 'entity_hub' | 'section' | 'figure';

export interface WikiOverlayResolvedTarget {
  target_kind: WikiOverlayTargetKind | string;
  target_ref: string;
  book_slug: string;
  viewer_path: string;
  title: string;
  summary: string;
}

export interface WikiOverlayRecord {
  overlay_id: string;
  user_id: string;
  kind: WikiOverlayKind;
  target_kind: WikiOverlayTargetKind;
  target_ref: string;
  book_slug: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  resolved_target?: WikiOverlayResolvedTarget;
  status?: string;
  checked_at?: string;
  body?: string;
  pinned?: boolean;
  title?: string;
  summary?: string;
  viewer_path?: string;
  strokes?: WikiInkStroke[];
  text_style?: WikiEditedTextStyle;
  text_annotations?: WikiTextAnnotation[];
  card_title?: string;
  source_anchor?: string;
  source_viewer_path?: string;
  document_id?: string;
  document_title?: string;
  document_label?: string;
}

export interface WikiOverlayResponse {
  count: number;
  updated_at: string;
  items: WikiOverlayRecord[];
}

export interface WikiOverlaySignalTarget {
  target_ref: string;
  target_kind: WikiOverlayTargetKind | string;
  book_slug: string;
  title: string;
  viewer_path: string;
  summary: string;
  count: number;
  user_count: number;
  last_touched_at: string;
  weight_score: number;
  kind_breakdown: Record<string, number>;
  primary_kind: string;
  primary_kind_count: number;
}

export interface WikiOverlayRecommendedPlay {
  label: string;
  href: string;
  kind: 'book' | 'entity' | 'section' | string;
  summary: string;
  reason: string;
  source_target_ref: string;
  source_overlay_kind: WikiOverlayKind | string;
}

export interface WikiOverlaySignalsResponse {
  updated_at: string;
  summary: {
    total_overlay_count: number;
    favorite_count: number;
    check_count: number;
    note_count: number;
    ink_count: number;
    edited_card_count: number;
    recent_position_count: number;
    target_count: number;
    user_count: number;
  };
  top_targets: WikiOverlaySignalTarget[];
  user_focus?: {
    user_id: string;
    overlay_count: number;
    favorite_count: number;
    check_count: number;
    note_count: number;
    ink_count: number;
    edited_card_count: number;
    recent_position_count: number;
    recent_targets: Array<{
      overlay_id: string;
      kind: string;
      target_ref: string;
      target_kind: string;
      label: string;
      href: string;
      summary: string;
      updated_at: string;
    }>;
    recommended_next_plays: WikiOverlayRecommendedPlay[];
  };
}

export interface ViewerDocumentResponse {
  viewer_path: string;
  body_class_name: string;
  inline_styles: string[];
  html: string;
  interaction_policy: {
    code_copy: boolean;
    code_wrap_toggle: boolean;
    recent_position_tracking: boolean;
    anchor_navigation: boolean;
  };
}

export type ViewerPageMode = 'single' | 'multi';

export interface ChatResponse {
  answer: string;
  rewritten_query?: string;
  citations: ChatCitation[];
  warnings: string[];
  session_id: string;
  response_kind?: string;
  suggested_queries: string[];
  related_links?: ChatRelatedLink[];
  related_sections?: ChatRelatedLink[];
  acquisition?: {
    kind: 'repository_search' | string;
    title: string;
    body: string;
    checkbox_label: string;
    confirm_label: string;
    repository_query: string;
  };
  retrieval_trace?: Record<string, unknown>;
  pipeline_trace?: {
    timings_ms?: Record<string, number>;
    selection?: {
      selected_hits?: Array<Record<string, unknown>>;
    };
    llm?: Record<string, unknown>;
    events?: ChatTraceEvent[];
  } & Record<string, unknown>;
}

export interface ChatStreamResultEvent {
  type: 'result';
  payload: ChatResponse;
}

export interface ChatStreamTraceEnvelope extends ChatTraceEvent {
  type: 'trace';
}

export interface ChatStreamErrorEvent {
  type: 'error';
  error: string;
}

export type ChatStreamEvent = ChatStreamResultEvent | ChatStreamTraceEnvelope | ChatStreamErrorEvent;

export interface DerivedAsset {
  asset_slug: string;
  asset_kind: string;
  playbook_family: string;
  family_label: string;
  title: string;
  viewer_path: string;
  section_count: number;
  source_type: string;
  family_summary: string;
}

export interface CustomerPackDraft {
  draft_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  source_type: string;
  title: string;
  book_slug: string;
  pack_label: string;
  quality_status: string;
  quality_score: number;
  quality_summary: string;
  uploaded_file_name?: string;
  uploaded_byte_size?: number;
  capture_artifact_path?: string;
  source_lane?: string;
  source_fingerprint?: string;
  parser_route?: string;
  parser_backend?: string;
  parser_version?: string;
  ocr_used?: boolean;
  extraction_confidence?: number;
  tenant_id?: string;
  workspace_id?: string;
  approval_state?: string;
  publication_state?: string;
  playable_asset_count: number;
  derived_asset_count: number;
  derived_assets: DerivedAsset[];
}

export interface CustomerPackDraftListResponse {
  count: number;
  drafts: CustomerPackDraft[];
}

export interface CustomerPackBookSection {
  heading: string;
  section_path_label: string;
  viewer_path: string;
  text: string;
}

export interface CustomerPackBook {
  draft_id: string;
  title: string;
  target_viewer_path: string;
  quality_status: string;
  quality_score: number;
  quality_summary: string;
  playable_asset_count: number;
  derived_asset_count: number;
  derived_assets: DerivedAsset[];
  sections: CustomerPackBookSection[];
  pack_label: string;
  source_type: string;
  source_lane?: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  customer_pack_evidence?: Record<string, unknown>;
}

export type RepositoryCategory =
  | 'Official Docs'
  | 'Enterprise Knowledge'
  | 'Operations Demo'
  | 'Troubleshooting';

export interface RepositoryDocsSignals {
  score: number;
  inspection_status: string;
  has_readme: boolean;
  has_docs_dir: boolean;
  has_demo_assets: boolean;
  doc_keyword_hits: number;
  troubleshooting_hits: number;
  demo_hits: number;
  entry_names: string[];
  summary: string;
}

export interface RepositorySearchResult {
  id: number;
  name: string;
  full_name: string;
  owner_login: string;
  html_url: string;
  description: string;
  stargazers_count: number;
  updated_at: string;
  language: string;
  default_branch: string;
  topics: string[];
  archived: boolean;
  docs_signals: RepositoryDocsSignals;
  suggested_category: RepositoryCategory;
  is_favorite: boolean;
  favorite_category: RepositoryCategory | '';
  ranking_score: number;
}

export interface OfficialSourceCandidate {
  book_slug: string;
  title: string;
  viewer_path: string;
  source_relative_path: string;
  source_repo: string;
  source_kind: string;
  status_kind: 'live' | 'candidate' | string;
  status_label: string;
  match_score: number;
  current_source_basis?: 'official_homepage' | 'official_repo' | 'unknown' | string;
  current_source_label?: string;
  source_options?: LibraryBookSourceOption[];
}

export interface OfficialSourceMaterializeResponse {
  book_slug: string;
  source_basis: 'official_homepage' | 'official_repo' | string;
  source_label: string;
  title: string;
  viewer_path: string;
  request_manifest_path: string;
  draft_summary: Record<string, unknown>;
  gold_summary: Record<string, unknown>;
  smoke: {
    approved_manifest_present: boolean;
    approved_manifest_count: number;
    approved_source_kind: string;
    approved_source_url: string;
    approved_source_lane: string;
    viewer_ready: boolean;
    source_meta_ready: boolean;
    viewer_path: string;
  };
  report_path: string;
}

export interface OfficialSourceCatalogResponse {
  source: string;
  total_count: number;
  live_count: number;
  candidate_count: number;
  rows: OfficialSourceCandidate[];
}

export interface RepositorySearchResponse {
  query: string;
  rewritten_query: string;
  count: number;
  auth_mode: 'token' | 'public';
  categories: RepositoryCategory[];
  results: RepositorySearchResult[];
  official_candidates?: OfficialSourceCandidate[];
}

export interface RepositoryFavorite extends Omit<RepositorySearchResult, 'is_favorite' | 'favorite_category' | 'archived' | 'ranking_score'> {
  favorite_category: RepositoryCategory;
  saved_at: string;
}

export interface RepositoryFavoritesResponse {
  count: number;
  categories: RepositoryCategory[];
  updated_at: string;
  items: RepositoryFavorite[];
  groups: Record<string, RepositoryFavorite[]>;
}

export interface RepositoryUnansweredItem {
  query: string;
  rewritten_query: string;
  timestamp: string;
  response_kind: string;
  warnings: string[];
}

export interface RepositoryUnansweredResponse {
  count: number;
  items: RepositoryUnansweredItem[];
}

export interface SourceMetaResponse {
  book_slug: string;
  book_title: string;
  anchor: string;
  section: string;
  section_path: string[];
  section_path_label: string;
  source_url: string;
  viewer_path: string;
  section_match_exact: boolean;
  source_collection?: string;
  pack_label?: string;
  source_lane?: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
}

export interface RuntimeFigureItem {
  caption: string;
  viewer_path: string;
  asset_url: string;
  asset_kind: string;
  diagram_type: string;
  section_hint: string;
}

export interface RuntimeFiguresResponse {
  count: number;
  book_slug: string;
  items: RuntimeFigureItem[];
}

export interface SessionSummary {
  session_id: string;
  session_name: string;
  turn_count: number;
  updated_at: string;
  first_query: string;
  primary_source_lane?: string;
  primary_boundary_truth?: string;
  primary_runtime_truth_label?: string;
  primary_boundary_badge?: string;
  primary_publication_state?: string;
  primary_approval_state?: string;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  count: number;
}

export interface SessionTurnSnapshot {
  query: string;
  answer: string;
  turn_id: string;
  created_at: string;
  primary_source_lane?: string;
  primary_boundary_truth?: string;
  primary_runtime_truth_label?: string;
  primary_boundary_badge?: string;
  primary_publication_state?: string;
  primary_approval_state?: string;
}

export interface SessionSnapshot {
  session_id: string;
  session_name: string;
  turns: SessionTurnSnapshot[];
  updated_at: string;
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
      // Keep default HTTP message.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function requestResponse(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers ?? {});
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
      // Keep default HTTP message.
    }
    throw new Error(message);
  }
  return response;
}

const CANONICAL_VIEWER_DIRECTORY_PATTERNS = [
  /^\/docs\/ocp\/[^/]+\/[^/]+\/[^/]+$/,
  /^\/playbooks\/wiki-runtime\/active\/[^/]+$/,
  /^\/wiki\/entities\/[^/]+$/,
  /^\/wiki\/figures\/[^/]+\/[^/]+$/,
];

export function normalizeViewerPath(path: string): string {
  const raw = String(path || '').trim();
  if (!raw || /^https?:\/\//i.test(raw)) {
    return raw;
  }
  const baseOrigin = typeof window !== 'undefined' ? window.location.origin : RUNTIME_EXTERNAL_ORIGIN;
  try {
    const parsed = new URL(raw, baseOrigin);
    const trimmedPath = parsed.pathname === '/' ? parsed.pathname : parsed.pathname.replace(/\/+$/, '');
    const normalizedPath = (
      trimmedPath
      && !trimmedPath.endsWith('/index.html')
      && CANONICAL_VIEWER_DIRECTORY_PATTERNS.some((pattern) => pattern.test(trimmedPath))
    )
      ? `${trimmedPath}/index.html`
      : parsed.pathname;
    return `${normalizedPath}${parsed.search || ''}${parsed.hash || ''}`;
  } catch {
    return raw;
  }
}

export function toRuntimeUrl(path: string): string {
  if (!path) {
    return '';
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${RUNTIME_EXTERNAL_ORIGIN}${normalizeViewerPath(path)}`;
}

export async function loadDataControlRoom(): Promise<DataControlRoomResponse> {
  return requestJson<DataControlRoomResponse>('/api/data-control-room');
}

export async function loadDataControlRoomChunks(payload: {
  scope: 'runtime' | 'customer_pack';
  bookSlug: string;
  draftId?: string;
}): Promise<CorpusChunkViewerResponse> {
  const params = new URLSearchParams({
    scope: payload.scope,
    book_slug: payload.bookSlug,
  });
  if (payload.draftId) {
    params.set('draft_id', payload.draftId);
  }
  return requestJson<CorpusChunkViewerResponse>(`/api/data-control-room/chunks?${params.toString()}`);
}

export async function loadBuyerPacket(packetId: string): Promise<BuyerPacketPreview> {
  return requestJson<BuyerPacketPreview>(`/api/buyer-packet?packet_id=${encodeURIComponent(packetId)}`);
}

export async function searchRepositories(query: string, limit = 12): Promise<RepositorySearchResponse> {
  const params = new URLSearchParams({
    query,
    limit: String(limit),
  });
  return requestJson<RepositorySearchResponse>(`/api/repositories/search?${params.toString()}`);
}

export async function loadOfficialSourceCatalog(): Promise<OfficialSourceCatalogResponse> {
  return requestJson<OfficialSourceCatalogResponse>('/api/repositories/official-catalog');
}

export async function materializeOfficialSourceCandidate(
  bookSlug: string,
  sourceBasis: 'official_homepage' | 'official_repo',
): Promise<OfficialSourceMaterializeResponse> {
  return requestJson<OfficialSourceMaterializeResponse>('/api/repositories/official-materialize', {
    method: 'POST',
    body: JSON.stringify({
      book_slug: bookSlug,
      source_basis: sourceBasis,
    }),
  });
}

export async function loadRepositoryFavorites(): Promise<RepositoryFavoritesResponse> {
  return requestJson<RepositoryFavoritesResponse>('/api/repositories/favorites');
}

export async function loadRepositoryUnanswered(limit = 20): Promise<RepositoryUnansweredResponse> {
  return requestJson<RepositoryUnansweredResponse>(`/api/repositories/unanswered?limit=${encodeURIComponent(String(limit))}`);
}

export async function saveRepositoryFavorites(
  category: RepositoryCategory,
  repositories: RepositorySearchResult[],
): Promise<RepositoryFavoritesResponse> {
  return requestJson<RepositoryFavoritesResponse>('/api/repositories/favorites', {
    method: 'POST',
    body: JSON.stringify({ category, repositories }),
  });
}

export async function removeRepositoryFavorite(fullName: string): Promise<RepositoryFavoritesResponse> {
  return requestJson<RepositoryFavoritesResponse>('/api/repositories/favorites/remove', {
    method: 'POST',
    body: JSON.stringify({ full_name: fullName }),
  });
}

export async function loadWikiOverlays(userId: string): Promise<WikiOverlayResponse> {
  return requestJson<WikiOverlayResponse>(`/api/wiki-overlays?user_id=${encodeURIComponent(userId)}`);
}

export async function loadWikiOverlaySignals(userId: string): Promise<WikiOverlaySignalsResponse> {
  return requestJson<WikiOverlaySignalsResponse>(`/api/wiki-overlay-signals?user_id=${encodeURIComponent(userId)}`);
}

export async function saveWikiOverlay(payload: Record<string, unknown>): Promise<{ saved: boolean; record: WikiOverlayRecord; count: number; updated_at: string }> {
  return requestJson('/api/wiki-overlays', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function removeWikiOverlay(payload: Record<string, unknown>): Promise<{ removed: number; count: number; updated_at: string }> {
  return requestJson('/api/wiki-overlays/remove', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function sendChat(payload: {
  query: string;
  sessionId: string;
  mode?: string;
  userId?: string;
  selectedDraftIds?: string[];
  restrictUploadedSources?: boolean;
}): Promise<ChatResponse> {
  return requestJson<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      query: payload.query,
      session_id: payload.sessionId,
      mode: payload.mode ?? 'ops',
      user_id: payload.userId ?? '',
      selected_draft_ids: payload.selectedDraftIds ?? [],
      restrict_uploaded_sources: payload.restrictUploadedSources ?? false,
    }),
  });
}

export async function sendChatStream(
  payload: {
    query: string;
    sessionId: string;
    mode?: string;
    userId?: string;
    selectedDraftIds?: string[];
    restrictUploadedSources?: boolean;
  },
  onEvent: (event: ChatStreamEvent) => void,
): Promise<ChatResponse> {
  const response = await fetch(`${RUNTIME_ORIGIN}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query: payload.query,
      session_id: payload.sessionId,
      mode: payload.mode ?? 'ops',
      user_id: payload.userId ?? '',
      selected_draft_ids: payload.selectedDraftIds ?? [],
      restrict_uploaded_sources: payload.restrictUploadedSources ?? false,
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let resultPayload: ChatResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        const event = JSON.parse(line) as ChatStreamEvent;
        onEvent(event);
        if (event.type === 'error') {
          throw new Error(event.error || 'stream error');
        }
        if (event.type === 'result') {
          resultPayload = event.payload;
        }
      }
      newlineIndex = buffer.indexOf('\n');
    }

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer.trim()) as ChatStreamEvent;
    onEvent(event);
    if (event.type === 'error') {
      throw new Error(event.error || 'stream error');
    }
    if (event.type === 'result') {
      resultPayload = event.payload;
    }
  }

  if (!resultPayload) {
    throw new Error('stream completed without final result');
  }
  return resultPayload;
}

export async function loadSourceMeta(viewerPath: string): Promise<SourceMetaResponse> {
  const normalizedViewerPath = normalizeViewerPath(viewerPath);
  return requestJson<SourceMetaResponse>(`/api/source-meta?viewer_path=${encodeURIComponent(normalizedViewerPath)}`);
}

export async function loadViewerDocument(viewerPath: string, pageMode: ViewerPageMode = 'single'): Promise<ViewerDocumentResponse> {
  const normalizedViewerPath = normalizeViewerPath(viewerPath);
  return requestJson<ViewerDocumentResponse>(`/api/viewer-document?viewer_path=${encodeURIComponent(normalizedViewerPath)}&page_mode=${encodeURIComponent(pageMode)}`);
}

export async function loadRuntimeFigures(bookSlug: string, limit = 3): Promise<RuntimeFiguresResponse> {
  return requestJson<RuntimeFiguresResponse>(`/api/runtime-figures?book_slug=${encodeURIComponent(bookSlug)}&limit=${encodeURIComponent(String(limit))}`);
}

export async function listCustomerPackDrafts(): Promise<CustomerPackDraftListResponse> {
  return requestJson<CustomerPackDraftListResponse>('/api/customer-packs/drafts');
}

export async function loadCustomerPackDraft(draftId: string): Promise<CustomerPackDraft> {
  return requestJson<CustomerPackDraft>(`/api/customer-packs/drafts?draft_id=${encodeURIComponent(draftId)}`);
}

export async function loadCustomerPackBook(draftId: string): Promise<CustomerPackBook> {
  return requestJson<CustomerPackBook>(`/api/customer-packs/book?draft_id=${encodeURIComponent(draftId)}`);
}

export async function loadCustomerPackCapturedPreview(
  draftId: string,
): Promise<{ blob: Blob; contentType: string }> {
  const response = await requestResponse(`/api/customer-packs/captured?draft_id=${encodeURIComponent(draftId)}`);
  return {
    blob: await response.blob(),
    contentType: response.headers.get('Content-Type') || 'application/octet-stream',
  };
}

function inferSourceType(file: File): string {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (['md', 'markdown'].includes(extension)) {
    return 'md';
  }
  if (['html', 'htm'].includes(extension)) {
    return 'web';
  }
  if (['adoc', 'asciidoc'].includes(extension)) {
    return 'asciidoc';
  }
  if (['txt', 'text'].includes(extension)) {
    return 'txt';
  }
  if (['docx'].includes(extension)) {
    return 'docx';
  }
  if (['pptx'].includes(extension)) {
    return 'pptx';
  }
  if (['xlsx'].includes(extension)) {
    return 'xlsx';
  }
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(extension)) {
    return 'image';
  }
  if (['pdf'].includes(extension)) {
    return 'pdf';
  }
  return 'web';
}

export async function uploadCustomerPackDraft(file: File): Promise<CustomerPackDraft> {
  const payload = new FormData();
  payload.append('source_type', inferSourceType(file));
  payload.append('uri', file.name);
  payload.append('title', file.name.replace(/\.[^.]+$/, ''));
  payload.append('language_hint', 'ko');
  payload.append('file_name', file.name);
  payload.append('file', file, file.name);
  return requestJson<CustomerPackDraft>('/api/customer-packs/upload-draft', {
    method: 'POST',
    body: payload,
  });
}

export async function captureCustomerPackDraft(draftId: string): Promise<CustomerPackDraft> {
  return requestJson<CustomerPackDraft>('/api/customer-packs/capture', {
    method: 'POST',
    body: JSON.stringify({ draft_id: draftId }),
  });
}

export async function normalizeCustomerPackDraft(draftId: string): Promise<CustomerPackDraft> {
  return requestJson<CustomerPackDraft>('/api/customer-packs/normalize', {
    method: 'POST',
    body: JSON.stringify({ draft_id: draftId }),
  });
}

export async function listSessions(limit = 50): Promise<SessionListResponse> {
  return requestJson<SessionListResponse>(`/api/sessions?limit=${limit}`);
}

export async function loadSession(sessionId: string): Promise<SessionSnapshot> {
  return requestJson<SessionSnapshot>(`/api/sessions/load?session_id=${encodeURIComponent(sessionId)}`);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await requestJson<{ success: boolean; session_id: string }>('/api/sessions/delete', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function deleteAllSessions(): Promise<number> {
  const payload = await requestJson<{ success: boolean; deleted_count: number }>('/api/sessions/delete-all', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  return Number(payload.deleted_count || 0);
}

export async function deleteCustomerPackDraft(draftId: string): Promise<void> {
  await requestJson<{ success: boolean }>('/api/customer-packs/delete-draft', {
    method: 'POST',
    body: JSON.stringify({ draft_id: draftId }),
  });
}

export function formatBytes(byteSize?: number): string {
  if (!byteSize || Number.isNaN(byteSize)) {
    return '';
  }
  if (byteSize < 1024) {
    return `${byteSize} B`;
  }
  if (byteSize < 1024 * 1024) {
    return `${(byteSize / 1024).toFixed(1)} KB`;
  }
  return `${(byteSize / (1024 * 1024)).toFixed(1)} MB`;
}
