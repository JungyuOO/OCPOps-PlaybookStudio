import { describe, expect, it } from 'vitest';
import type { CustomerPackDraft } from '../lib/runtimeApi';
import {
  dedupeDraftCatalogForDisplay,
  describeDraftCatalogSemantics,
  isTestRunDraft,
  needsSlideDeckUpgrade,
  parseDraftTestRunOrder,
  partitionDraftCatalog,
  resolveDraftScopedViewerSourceId,
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

  it('deduplicates repeated uploaded customer documents and keeps the best current draft', () => {
    const staleDuplicate = {
      ...makeDraft('KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL', '2026-04-23T12:43:35+09:00'),
      draft_id: 'dtb-stale',
      uploaded_file_name: 'KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx',
      read_ready: true,
      publish_ready: true,
      playable_asset_count: 1,
    } as CustomerPackDraft & { read_ready: boolean; publish_ready: boolean };
    const currentDuplicate = {
      ...staleDuplicate,
      draft_id: 'dtb-current',
      updated_at: '2026-04-23T13:53:28+09:00',
      playable_asset_count: 6,
    };
    const unrelated = makeDraft('Customer Operations Runbook');

    const deduped = dedupeDraftCatalogForDisplay([staleDuplicate, unrelated, currentDuplicate]);

    expect(deduped.map((draft) => draft.draft_id)).toEqual(['dtb-current', unrelated.draft_id]);
  });

  it('keeps intentional test runs even when they share the same source fingerprint', () => {
    const testOne = {
      ...makeDraft('Test 1 - Surya'),
      draft_id: 'dtb-test-one',
      source_fingerprint: 'same-upload',
    } as CustomerPackDraft & { source_fingerprint: string };
    const testTwo = {
      ...makeDraft('Test 2 - Qwen'),
      draft_id: 'dtb-test-two',
      source_fingerprint: 'same-upload',
    } as CustomerPackDraft & { source_fingerprint: string };

    expect(dedupeDraftCatalogForDisplay([testOne, testTwo]).map((draft) => draft.draft_id)).toEqual([
      'dtb-test-one',
      'dtb-test-two',
    ]);
  });

  it('exposes a small boolean helper for sidebar grouping', () => {
    expect(isTestRunDraft(makeDraft('Test 9'))).toBe(true);
    expect(isTestRunDraft(makeDraft('Partner Architecture Pack'))).toBe(false);
  });

  it('opens normalized pptx drafts directly in the viewer surface', () => {
    expect(shouldOpenDraftAsViewer(makeDraft('Test 1 - Surya'))).toBe(true);
    expect(shouldOpenDraftAsViewer(makeDraft('Customer PPT'))).toBe(true);
    expect(shouldOpenDraftAsViewer({ ...makeDraft('Test 2 - Qwen'), status: 'captured' })).toBe(false);
  });

  it('opens normalized customer docs in the viewer when a materialized book surface exists', () => {
    expect(
      shouldOpenDraftAsViewer(
        { ...makeDraft('Customer DOCX'), source_type: 'docx' },
        { target_viewer_path: '/playbooks/customer-packs/customer-docx/index.html' },
      ),
    ).toBe(true);
    expect(shouldOpenDraftAsViewer({ ...makeDraft('Customer DOCX'), source_type: 'docx' })).toBe(false);
  });

  it('marks stale normalized pptx drafts for slide-deck upgrade', () => {
    expect(needsSlideDeckUpgrade(makeDraft('Customer PPT'))).toBe(true);
    expect(needsSlideDeckUpgrade({ ...makeDraft('Customer PPT'), surface_kind: 'slide_deck' })).toBe(false);
    expect(needsSlideDeckUpgrade(makeDraft('Customer PPT'), { surface_kind: 'slide_deck' })).toBe(false);
    expect(needsSlideDeckUpgrade({ ...makeDraft('Customer DOCX'), source_type: 'docx' })).toBe(false);
  });

  it('recovers draft-scoped identity from customer pack viewer paths', () => {
    expect(resolveDraftScopedViewerSourceId('draft:customer-pack-123')).toBe('draft:customer-pack-123');
    expect(
      resolveDraftScopedViewerSourceId(undefined, '/playbooks/customer-packs/customer-pack-456/index.html#slide-2'),
    ).toBe('draft:customer-pack-456');
    expect(resolveDraftScopedViewerSourceId(undefined, '/docs/ocp/4.20/ko/networking/index.html')).toBeUndefined();
  });

  it('describes customer docs and test runs with explicit surface semantics', () => {
    expect(describeDraftCatalogSemantics(makeDraft('Test 1 - Surya'))).toEqual({
      audienceLabel: '테스트 런',
      surfaceLabel: '슬라이드 덱',
    });
    expect(
      describeDraftCatalogSemantics(
        { ...makeDraft('Customer DOCX'), source_type: 'docx' },
        { target_viewer_path: '/playbooks/customer-packs/customer-docx/index.html' },
      ),
    ).toEqual({
      audienceLabel: '고객 문서',
      surfaceLabel: '위키 북',
    });
  });

  it('does not call promoted normalized customer documents drafts', () => {
    const semantics = describeDraftCatalogSemantics({
      ...makeDraft('Promoted Customer DOCX'),
      source_type: 'docx',
      playable_asset_count: 0,
      shared_grade: 'gold',
      read_ready: true,
      publish_ready: true,
      quality_status: 'ready',
    });

    expect(semantics).toEqual({
      audienceLabel: '고객 문서',
      surfaceLabel: '라이브러리 등록',
    });
    expect(semantics.surfaceLabel).not.toContain('초안');
  });

  it('labels raw uploaded customer documents as waiting rather than draft inventory', () => {
    expect(describeDraftCatalogSemantics({ ...makeDraft('Raw Upload'), source_type: 'docx', status: 'uploaded' })).toEqual({
      audienceLabel: '고객 문서',
      surfaceLabel: '업로드 대기',
    });
  });
});
