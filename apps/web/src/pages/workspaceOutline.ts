import type { WorkspaceManualBook } from './workspaceTypes';

const OUTLINE_ROOT_SUFFIXES = [
  '_operations_playbook',
  '_operation_playbook',
  '_topic_playbook',
  '_troubleshooting_playbook',
  '_policy_overlay_book',
  '_synthesized_playbook',
] as const;

const OUTLINE_VARIANT_LABELS: Record<string, string> = {
  official_doc: '원문',
  reader_grade_md: '원문',
  topic_playbook: '토픽 플레이북',
  operation_playbook: '운영 플레이북',
  troubleshooting_playbook: '트러블슈팅 플레이북',
  policy_overlay_book: '정책 오버레이 북',
  synthesized_playbook: '합성 플레이북',
};

const OUTLINE_VARIANT_RANK: Record<string, number> = {
  official_doc: 0,
  reader_grade_md: 0,
  topic_playbook: 1,
  operation_playbook: 2,
  policy_overlay_book: 3,
  troubleshooting_playbook: 4,
  synthesized_playbook: 5,
};

export interface OutlineBookFamily {
  key: string;
  rootSlug: string;
  primary: WorkspaceManualBook;
  variants: WorkspaceManualBook[];
}

function normalizeOutlineRootSlug(bookSlug: string): string {
  const normalized = (bookSlug || '').trim();
  for (const suffix of OUTLINE_ROOT_SUFFIXES) {
    if (normalized.endsWith(suffix)) {
      return normalized.slice(0, -suffix.length);
    }
  }
  return normalized;
}

function outlineVariantRank(book: WorkspaceManualBook): number {
  return OUTLINE_VARIANT_RANK[book.source_type] ?? 99;
}

function compareOutlineBooks(left: WorkspaceManualBook, right: WorkspaceManualBook): number {
  const leftRank = outlineVariantRank(left);
  const rightRank = outlineVariantRank(right);
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  return left.title.localeCompare(right.title, 'ko');
}

export function describeOutlineVariant(book: WorkspaceManualBook): string {
  return OUTLINE_VARIANT_LABELS[book.source_type] ?? book.family_label ?? book.source_type;
}

export function buildOutlineBookFamilies(books: WorkspaceManualBook[]): OutlineBookFamily[] {
  const grouped = new Map<string, WorkspaceManualBook[]>();
  for (const book of books) {
    const rootSlug = normalizeOutlineRootSlug(book.book_slug);
    const bucket = grouped.get(rootSlug) ?? [];
    bucket.push(book);
    grouped.set(rootSlug, bucket);
  }

  return [...grouped.entries()].map(([rootSlug, bucket]) => {
    const members = [...bucket].sort(compareOutlineBooks);
    const primary = members[0];
    return {
      key: `family:${rootSlug}`,
      rootSlug,
      primary,
      variants: members.slice(1),
    };
  });
}
