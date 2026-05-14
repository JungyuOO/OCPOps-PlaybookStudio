import { describe, expect, it } from 'vitest';
import {
  assetIdFromMarkdownImageSrc,
  buildDocumentReaderImageState,
  documentReaderAssetCaption,
} from './documentReaderAssets';
import type { DocumentReaderAsset } from './runtimeApi';

function asset(overrides: Partial<DocumentReaderAsset> = {}): DocumentReaderAsset {
  const base: DocumentReaderAsset = {
    asset_id: 'asset-1',
    asset_type: 'image',
    mime_type: 'image/png',
    storage_key: 'uploads/assets/asset-1.png',
    sha256: 'sha',
    filename: 'page-001.png',
    data_url: 'data:image/png;base64,abc',
    page_number: 1,
    metadata: {},
  };
  return { ...base, ...overrides, metadata: overrides.metadata ?? base.metadata };
}

describe('document reader assets', () => {
  it('extracts asset ids from markdown image sources', () => {
    expect(assetIdFromMarkdownImageSrc('asset://asset-1')).toBe('asset-1');
    expect(assetIdFromMarkdownImageSrc('https://example.com/image.png')).toBe('');
  });

  it('builds a data-url image state for reader assets', () => {
    const assets = new Map([['asset-1', asset({ caption_text: '원본 아키텍처 그림' })]]);

    const state = buildDocumentReaderImageState({
      src: 'asset://asset-1',
      alt: 'fallback',
      assetById: assets,
    });

    expect(state).toEqual({
      kind: 'reader-asset',
      src: 'data:image/png;base64,abc',
      alt: 'fallback',
      caption: '원본 아키텍처 그림',
      pageNumber: 1,
    });
  });

  it('separates missing db assets from missing asset files', () => {
    const missingAsset = buildDocumentReaderImageState({
      src: 'asset://missing',
      alt: '',
      assetById: new Map(),
    });
    const missingFile = buildDocumentReaderImageState({
      src: 'asset://asset-1',
      alt: '',
      assetById: new Map([['asset-1', asset({ data_url: '' })]]),
    });

    expect(missingAsset.kind).toBe('missing-asset');
    if (missingAsset.kind !== 'missing-asset') {
      throw new Error('expected missing asset state');
    }
    expect(missingAsset.message).toContain('asset을 찾을 수 없습니다');
    expect(missingFile.kind).toBe('missing-file');
    if (missingFile.kind !== 'missing-file') {
      throw new Error('expected missing file state');
    }
    expect(missingFile.message).toContain('이미지 파일을 불러오지 못했습니다');
  });

  it('uses Korean-readable caption precedence', () => {
    expect(documentReaderAssetCaption(asset({ caption_text: '캡션', qwen_description: '설명' }))).toBe('캡션');
    expect(documentReaderAssetCaption(asset({ caption_text: '', qwen_description: '설명' }))).toBe('설명');
  });
});
