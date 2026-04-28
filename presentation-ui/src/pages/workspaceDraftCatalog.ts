import type { CustomerPackBook, CustomerPackDraft } from '../lib/runtimeApi';

const TEST_DRAFT_TITLE_RE = /^(test|테스트)\s*[-_:]?\s*(\d+)\b/i;
const CUSTOMER_PACK_VIEWER_RE = /\/playbooks\/customer-packs\/([^/?#]+)/i;

type DraftSurfaceRecord = Pick<
  CustomerPackDraft,
  'title'
  | 'status'
  | 'source_type'
  | 'surface_kind'
  | 'pipeline_target_label'
  | 'playable_asset_count'
  | 'quality_status'
  | 'shared_grade'
  | 'read_ready'
  | 'publish_ready'
> | null | undefined;

type DraftViewerBook = Partial<Pick<CustomerPackBook, 'surface_kind' | 'target_viewer_path'>> | null | undefined;

export interface DraftCatalogPartition {
  standardDrafts: CustomerPackDraft[];
  testDrafts: CustomerPackDraft[];
}

export interface DraftCatalogSemantics {
  audienceLabel: string;
  surfaceLabel: string;
}

function normalizedDraftText(value: unknown): string {
  return String(value || '').trim().toLowerCase();
}

function isTruthyDraftFlag(value: unknown): boolean {
  return value === true || normalizedDraftText(value) === 'true';
}

function isMaterializedDraft(draft: DraftSurfaceRecord): boolean {
  const status = normalizedStatus(draft?.status);
  const quality = normalizedDraftText(draft?.quality_status);
  const grade = normalizedDraftText(draft?.shared_grade);
  return status === 'normalized'
    && (
      isTruthyDraftFlag(draft?.read_ready)
      || isTruthyDraftFlag(draft?.publish_ready)
      || quality === 'ready'
      || grade === 'gold'
      || grade === 'silver'
      || Number(draft?.playable_asset_count || 0) > 0
    );
}

function draftReadyRank(draft: CustomerPackDraft): number {
  const status = normalizedStatus(draft.status);
  const quality = normalizedDraftText(draft.quality_status);
  const grade = normalizedDraftText(draft.shared_grade);
  const readReady = isTruthyDraftFlag(draft.read_ready);
  const publishReady = isTruthyDraftFlag(draft.publish_ready);

  return (
    (readReady ? 100 : 0)
    + (publishReady ? 40 : 0)
    + (status === 'normalized' ? 20 : status === 'captured' ? 10 : 0)
    + (quality === 'ready' ? 5 : 0)
    + (grade === 'gold' ? 3 : 0)
    + Number(draft.playable_asset_count || 0)
  );
}

function draftDisplayDedupeKey(draft: CustomerPackDraft): string {
  const sourceType = normalizedSourceType(draft.source_type);
  const fingerprint = normalizedDraftText((draft as { source_fingerprint?: unknown }).source_fingerprint);
  const bookSlug = normalizedDraftText(draft.book_slug);
  const title = normalizedDraftText(draft.title);
  if (fingerprint) {
    return `fingerprint:${sourceType}:${fingerprint}:${bookSlug}:${title}`;
  }

  const uploadedFileName = normalizedDraftText(draft.uploaded_file_name);
  if (uploadedFileName) {
    return `uploaded:${sourceType}:${uploadedFileName}`;
  }

  return [
    'logical',
    sourceType,
    bookSlug,
    title,
  ].join(':');
}

function isDraftDisplayPreferred(nextDraft: CustomerPackDraft, currentDraft: CustomerPackDraft): boolean {
  const nextRank = draftReadyRank(nextDraft);
  const currentRank = draftReadyRank(currentDraft);
  if (nextRank !== currentRank) {
    return nextRank > currentRank;
  }
  const nextUpdatedAt = String(nextDraft.updated_at || '');
  const currentUpdatedAt = String(currentDraft.updated_at || '');
  if (nextUpdatedAt !== currentUpdatedAt) {
    return nextUpdatedAt > currentUpdatedAt;
  }
  const nextCreatedAt = String(nextDraft.created_at || '');
  const currentCreatedAt = String(currentDraft.created_at || '');
  if (nextCreatedAt !== currentCreatedAt) {
    return nextCreatedAt > currentCreatedAt;
  }
  return String(nextDraft.draft_id || '') > String(currentDraft.draft_id || '');
}

export function dedupeDraftCatalogForDisplay(drafts: CustomerPackDraft[]): CustomerPackDraft[] {
  const selected = new Map<string, CustomerPackDraft>();

  for (const draft of drafts) {
    const key = draftDisplayDedupeKey(draft);
    const current = selected.get(key);
    if (!current || isDraftDisplayPreferred(draft, current)) {
      selected.set(key, draft);
    }
  }

  return [...selected.values()];
}

export function parseDraftTestRunOrder(title: string): number | null {
  const match = String(title || '').trim().match(TEST_DRAFT_TITLE_RE);
  if (!match) {
    return null;
  }
  const order = Number(match[2]);
  return Number.isFinite(order) ? order : null;
}

export function isTestRunDraft(draft: Pick<CustomerPackDraft, 'title'> | null | undefined): boolean {
  return parseDraftTestRunOrder(String(draft?.title || '')) !== null;
}

function normalizedStatus(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase();
}

function normalizedSurfaceKind(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase();
}

function normalizedSourceType(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase();
}

function normalizedViewerPath(value: string | null | undefined): string {
  return String(value || '').trim();
}

function resolvedSurfaceKind(
  draft: Pick<CustomerPackDraft, 'surface_kind'> | null | undefined,
  book?: DraftViewerBook,
): string {
  return normalizedSurfaceKind(book?.surface_kind) || normalizedSurfaceKind(draft?.surface_kind);
}

export function resolveDraftScopedViewerSourceId(
  sourceId?: string | null,
  viewerPath?: string | null,
): string | undefined {
  const normalizedSourceId = String(sourceId || '').trim();
  if (normalizedSourceId.startsWith('draft:')) {
    return normalizedSourceId;
  }
  const match = String(viewerPath || '').trim().match(CUSTOMER_PACK_VIEWER_RE);
  if (!match?.[1]) {
    return undefined;
  }
  return `draft:${match[1]}`;
}

export function describeDraftCatalogSemantics(
  draft: DraftSurfaceRecord,
  book?: DraftViewerBook,
): DraftCatalogSemantics {
  const audienceLabel = isTestRunDraft(draft) ? '테스트 런' : '고객 문서';
  const status = normalizedStatus(draft?.status);
  const sourceType = normalizedSourceType(draft?.source_type);
  const surfaceKind = resolvedSurfaceKind(draft, book);
  const viewerReady = Boolean(normalizedViewerPath(book?.target_viewer_path));
  const hasPlayableAssets = Number(draft?.playable_asset_count || 0) > 0;

  if (surfaceKind === 'slide_deck' || sourceType === 'pptx') {
    return {
      audienceLabel,
      surfaceLabel: status === 'normalized' ? '슬라이드 덱' : '슬라이드 캡처',
    };
  }
  if (viewerReady || (status === 'normalized' && hasPlayableAssets)) {
    return {
      audienceLabel,
      surfaceLabel: '위키 북',
    };
  }
  if (status === 'captured') {
    return {
      audienceLabel,
      surfaceLabel: '캡처 미리보기',
    };
  }
  if (isMaterializedDraft(draft)) {
    return {
      audienceLabel,
      surfaceLabel: '라이브러리 등록',
    };
  }
  if (status === 'normalized') {
    return {
      audienceLabel,
      surfaceLabel: '정규화 완료',
    };
  }
  return {
    audienceLabel,
    surfaceLabel: '업로드 대기',
  };
}

export function shouldOpenDraftAsViewer(
  draft: DraftSurfaceRecord,
  book?: DraftViewerBook,
): boolean {
  if (normalizedStatus(draft?.status) !== 'normalized') {
    return false;
  }
  if (normalizedViewerPath(book?.target_viewer_path)) {
    return true;
  }
  if (resolvedSurfaceKind(draft, book) === 'slide_deck') {
    return true;
  }
  return normalizedSourceType(draft?.source_type) === 'pptx';
}

export function needsSlideDeckUpgrade(
  draft: Pick<CustomerPackDraft, 'status' | 'source_type' | 'surface_kind'> | null | undefined,
  book?: Pick<CustomerPackBook, 'surface_kind'> | null | undefined,
): boolean {
  if (normalizedStatus(draft?.status) !== 'normalized') {
    return false;
  }
  if (normalizedSourceType(draft?.source_type) !== 'pptx') {
    return false;
  }
  return resolvedSurfaceKind(draft, book) !== 'slide_deck';
}

export function partitionDraftCatalog(drafts: CustomerPackDraft[]): DraftCatalogPartition {
  const standardDrafts: CustomerPackDraft[] = [];
  const testDrafts: CustomerPackDraft[] = [];

  drafts.forEach((draft) => {
    if (isTestRunDraft(draft)) {
      testDrafts.push(draft);
      return;
    }
    standardDrafts.push(draft);
  });

  testDrafts.sort((left, right) => {
    const leftOrder = parseDraftTestRunOrder(left.title);
    const rightOrder = parseDraftTestRunOrder(right.title);
    if (leftOrder !== null && rightOrder !== null && leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return String(right.updated_at || '').localeCompare(String(left.updated_at || ''));
  });

  return {
    standardDrafts,
    testDrafts,
  };
}
