import type { CustomerPackBook, CustomerPackDraft } from '../lib/runtimeApi';

const TEST_DRAFT_TITLE_RE = /^(test|테스트)\s*[-_:]?\s*(\d+)\b/i;
const CUSTOMER_PACK_VIEWER_RE = /\/playbooks\/customer-packs\/([^/?#]+)/i;

type DraftSurfaceRecord = Pick<
  CustomerPackDraft,
  'title' | 'status' | 'source_type' | 'surface_kind' | 'pipeline_target_label' | 'playable_asset_count'
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
  if (status === 'normalized') {
    return {
      audienceLabel,
      surfaceLabel: '정규화 초안',
    };
  }
  return {
    audienceLabel,
    surfaceLabel: '업로드 초안',
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
