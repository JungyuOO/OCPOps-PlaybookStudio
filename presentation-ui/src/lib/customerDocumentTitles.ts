import type { CustomerPackDraft, LibraryBook } from './runtimeApi';

export type CustomerDocumentTitleSource = Partial<Pick<
  CustomerPackDraft,
  'title' | 'uploaded_file_name' | 'book_slug' | 'source_type'
> & Pick<
  LibraryBook,
  'source_origin_label' | 'source_collection' | 'source_kind' | 'custom_document_kind'
>>;

function textValue(value: unknown): string {
  return String(value || '').trim();
}

function basename(value: string): string {
  const normalized = value.replace(/\\/g, '/');
  return normalized.split('/').filter(Boolean).pop() || normalized;
}

function withoutExtension(value: string): string {
  return basename(value).replace(/\.[a-z0-9]+$/i, '');
}

function normalizeProbe(value: string): string {
  return withoutExtension(value)
    .replace(/\bKMSC-COCP-[A-Z]+-\d+(?=[_\s-]|$)[_\s-]*/gi, '')
    .replace(/아키텍쳐/g, '아키텍처')
    .replace(/서비스메쉬/g, '서비스메시')
    .replace(/CICD/gi, 'CI/CD')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function compactProbe(value: string): string {
  return normalizeProbe(value).replace(/\s+/g, '');
}

function knownCustomerDocumentTitle(rawTitle: string): string {
  const probe = compactProbe(rawTitle);

  if (!probe) {
    return '';
  }
  if (probe.includes('완료보고')) {
    return '운영 전환 완료 보고';
  }
  if (probe.includes('서비스메시') && probe.includes('아키텍처')) {
    return '서비스 메시 아키텍처 설계서';
  }
  if ((probe.includes('ci/cd') || probe.includes('cicd')) && probe.includes('아키텍처')) {
    return 'CI/CD 아키텍처 설계서';
  }
  if (probe.includes('ocp운영') && probe.includes('아키텍처')) {
    return 'OCP 운영 아키텍처 설계서';
  }
  if (probe.includes('ocp') && probe.includes('단위테스트') && probe.includes('계획')) {
    return 'OCP 단위 테스트 계획';
  }
  if (probe.includes('서비스') && probe.includes('단위테스트') && probe.includes('계획')) {
    return '서비스 단위 테스트 계획';
  }
  if (probe.includes('ocp') && probe.includes('통합테스트') && probe.includes('계획')) {
    return 'OCP 통합 테스트 계획';
  }
  if (probe.includes('서비스') && probe.includes('통합') && probe.includes('성능') && probe.includes('계획')) {
    return '서비스 통합/성능 테스트 계획';
  }
  if (probe.includes('ocp') && probe.includes('통합테스트') && probe.includes('결과')) {
    return 'OCP 통합 테스트 결과';
  }
  if (probe.includes('서비스') && probe.includes('통합') && probe.includes('성능') && probe.includes('결과')) {
    return '서비스 통합/성능 테스트 결과';
  }

  return '';
}

function cleanupRawDocumentTitle(rawTitle: string): string {
  return withoutExtension(rawTitle)
    .replace(/\bKMSC-COCP-[A-Z]+-\d+(?=[_\s-]|$)[_\s-]*/gi, '')
    .replace(/\b20\d{6}\b/g, '')
    .replace(/\bFINAL\b/gi, '')
    .replace(/완료본/g, '')
    .replace(/아키텍쳐/g, '아키텍처')
    .replace(/서비스메쉬/g, '서비스 메시')
    .replace(/CICD/gi, 'CI/CD')
    .replace(/OCP운영/g, 'OCP 운영')
    .replace(/단위테스트/g, '단위 테스트')
    .replace(/통합테스트/g, '통합 테스트')
    .replace(/테스트계획/g, '테스트 계획')
    .replace(/계획서/g, '계획')
    .replace(/결과서/g, '결과')
    .replace(/설계서/g, '설계서')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+및\s+/g, ' 및 ')
    .replace(/\s+/g, ' ')
    .replace(/^[\s._-]+|[\s._-]+$/g, '')
    .trim();
}

function looksLikeRawCustomerDocumentTitle(value: string): boolean {
  const raw = withoutExtension(value);
  return /\bKMSC-COCP-/i.test(raw)
    || /\b20\d{6}\b/.test(raw)
    || /[_]/.test(raw)
    || /\bFINAL\b/i.test(raw);
}

export function customerDocumentOriginalTitle(source?: CustomerDocumentTitleSource | null): string {
  const candidates = [
    source?.source_origin_label,
    source?.uploaded_file_name,
    source?.title,
    source?.book_slug,
  ].map(textValue);
  return candidates.find(Boolean) || '';
}

export function displayCustomerDocumentTitle(source?: CustomerDocumentTitleSource | null): string {
  const title = textValue(source?.title);
  const original = customerDocumentOriginalTitle(source);
  const rawTitle = title || original;
  const known = knownCustomerDocumentTitle(rawTitle) || knownCustomerDocumentTitle(original);

  if (known) {
    return known;
  }
  if (!rawTitle) {
    return '';
  }
  if (!looksLikeRawCustomerDocumentTitle(rawTitle)) {
    return rawTitle;
  }

  const cleaned = cleanupRawDocumentTitle(rawTitle);
  return cleaned || rawTitle;
}
