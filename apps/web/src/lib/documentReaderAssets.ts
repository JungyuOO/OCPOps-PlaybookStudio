import type { DocumentReaderAsset } from './runtimeApi';

export type DocumentReaderImageState =
  | {
      kind: 'reader-asset';
      src: string;
      alt: string;
      caption: string;
      pageNumber: number | null;
    }
  | {
      kind: 'missing-file';
      message: string;
    }
  | {
      kind: 'missing-asset';
      message: string;
    }
  | {
      kind: 'plain-image';
      src: string;
      alt: string;
    };

export function assetIdFromMarkdownImageSrc(src: unknown): string {
  const value = String(src || '').trim();
  return value.startsWith('asset://') ? value.slice('asset://'.length) : '';
}

export function documentReaderAssetCaption(asset: DocumentReaderAsset, fallback = '문서 이미지'): string {
  return (
    String(asset.caption_text || '').trim()
    || String(asset.qwen_description || '').trim()
    || String(asset.filename || '').trim()
    || fallback
  );
}

export function buildDocumentReaderImageState({
  src,
  alt,
  assetById,
}: {
  src: unknown;
  alt: unknown;
  assetById: Map<string, DocumentReaderAsset>;
}): DocumentReaderImageState {
  const rawSrc = String(src || '').trim();
  const rawAlt = String(alt || '문서 이미지');
  const assetId = assetIdFromMarkdownImageSrc(rawSrc);
  if (!assetId) {
    return { kind: 'plain-image', src: rawSrc, alt: rawAlt };
  }
  const asset = assetById.get(assetId);
  if (!asset) {
    return { kind: 'missing-asset', message: `이미지 asset을 찾을 수 없습니다: ${assetId}` };
  }
  const caption = documentReaderAssetCaption(asset, rawAlt);
  if (!asset.data_url) {
    return { kind: 'missing-file', message: `이미지 파일을 불러오지 못했습니다: ${caption}` };
  }
  return {
    kind: 'reader-asset',
    src: asset.data_url,
    alt: rawAlt || caption,
    caption,
    pageNumber: asset.page_number ?? null,
  };
}
