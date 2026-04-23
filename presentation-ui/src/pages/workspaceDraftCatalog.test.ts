import { describe, expect, it } from 'vitest';
import type { CustomerPackDraft } from '../lib/runtimeApi';
import {
  isTestRunDraft,
  parseDraftTestRunOrder,
  partitionDraftCatalog,
  shouldOpenDraftAsViewer,
} from './workspaceDraftCatalog';

function makeDraft(title: string, updated_at = '2026-04-23T10:00:00+09:00'): CustomerPackDraft {
  return {
    draft_id: `${title}-id`,
    status: 'normalized',
    created_at: updated_at,
    updated_at,
    source_type: 'pptx',
    title,
    book_slug: `${title}-slug`,
    pack_label: 'Customer Source-First Pack',
    quality_status: 'review',
    quality_score: 70,
    quality_summary: 'ok',
    playable_asset_count: 1,
    derived_asset_count: 0,
    derived_assets: [],
  };
}

describe('workspaceDraftCatalog', () => {
  it('detects numbered test drafts from the title', () => {
    expect(parseDraftTestRunOrder('Test 1')).toBe(1);
    expect(parseDraftTestRunOrder('test2 - qwen')).toBe(2);
    expect(parseDraftTestRunOrder('테스트 3 Surya')).toBe(3);
    expect(parseDraftTestRunOrder('Customer PPT')).toBeNull();
  });

  it('partitions test drafts away from regular uploaded drafts', () => {
    const partition = partitionDraftCatalog([
      makeDraft('Customer PPT'),
      makeDraft('Test 2', '2026-04-23T09:00:00+09:00'),
      makeDraft('Test 1', '2026-04-23T11:00:00+09:00'),
      makeDraft('테스트 3'),
    ]);

    expect(partition.standardDrafts.map((draft) => draft.title)).toEqual(['Customer PPT']);
    expect(partition.testDrafts.map((draft) => draft.title)).toEqual([
      'Test 1',
      'Test 2',
      '테스트 3',
    ]);
  });

  it('exposes a small boolean helper for sidebar grouping', () => {
    expect(isTestRunDraft(makeDraft('Test 9'))).toBe(true);
    expect(isTestRunDraft(makeDraft('Partner Architecture Pack'))).toBe(false);
  });

  it('opens normalized test runs directly in the viewer surface', () => {
    expect(shouldOpenDraftAsViewer(makeDraft('Test 1 - Surya'))).toBe(true);
    expect(shouldOpenDraftAsViewer(makeDraft('Customer PPT'))).toBe(false);
    expect(shouldOpenDraftAsViewer({ ...makeDraft('Test 2 - Qwen'), status: 'captured' })).toBe(false);
  });
});
