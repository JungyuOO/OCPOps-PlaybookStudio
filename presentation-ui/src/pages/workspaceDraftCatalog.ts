import type { CustomerPackDraft } from '../lib/runtimeApi';

const TEST_DRAFT_TITLE_RE = /^(test|테스트)\s*[-_:]?\s*(\d+)\b/i;

export interface DraftCatalogPartition {
  standardDrafts: CustomerPackDraft[];
  testDrafts: CustomerPackDraft[];
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

export function shouldOpenDraftAsViewer(
  draft: Pick<CustomerPackDraft, 'title' | 'status'> | null | undefined,
): boolean {
  return isTestRunDraft(draft) && String(draft?.status || '').trim().toLowerCase() === 'normalized';
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
