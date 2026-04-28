import type { DataControlRoomResponse, LibraryBook } from './runtimeApi';

type WorkspaceSourceRoom = Pick<
  DataControlRoomResponse,
  | 'known_books'
  | 'manualbooks'
  | 'approved_wiki_runtime_books'
  | 'gold_books'
  | 'customer_pack_runtime_books'
  | 'user_library_books'
>;

const CUSTOMER_PPT_SOURCE_TYPE = 'pptx';
const CUSTOMER_MASTER_SOURCE_TYPE = 'customer_master_book';
const CUSTOMER_DERIVED_SOURCE_TYPES = new Set([
  'operation_playbook',
  'policy_overlay_book',
  'synthesized_playbook',
  'topic_playbook',
  'troubleshooting_playbook',
]);

export function isCustomerPackRuntimeBook(book: Pick<LibraryBook, 'source_lane' | 'source_type' | 'source_collection' | 'viewer_path'>): boolean {
  const sourceLane = String(book.source_lane || '').toLowerCase();
  const sourceType = String(book.source_type || '').toLowerCase();
  const sourceCollection = String(book.source_collection || '').toLowerCase();
  const viewerPath = String(book.viewer_path || '').toLowerCase();
  return (
    sourceLane.includes('customer')
    || sourceCollection.includes('customer')
    || viewerPath.startsWith('/playbooks/customer-packs/')
    || sourceType === CUSTOMER_PPT_SOURCE_TYPE
    || sourceType === CUSTOMER_MASTER_SOURCE_TYPE
    || CUSTOMER_DERIVED_SOURCE_TYPES.has(sourceType)
  );
}

export interface WorkspaceSourceCatalogStats {
  runtimeBookCount: number;
  officialGoldRuntimeCount: number;
  officialHiddenRuntimeCount: number;
  officialCatalogCandidateCount: number;
  customerRuntimeBookCount: number;
  customerPptSourceCount: number;
  customerDerivedRuntimeCount: number;
  customerMasterRuntimeCount: number;
}

function dedupeBooks(books: readonly LibraryBook[]): LibraryBook[] {
  const seen = new Set<string>();
  const items: LibraryBook[] = [];
  for (const book of books) {
    const boundary = isCustomerPackRuntimeBook(book) ? 'customer' : 'official';
    const logicalKey = (book.book_slug || book.viewer_path || book.title || '').trim();
    if (!logicalKey) {
      continue;
    }
    const key = `${boundary}:${logicalKey}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(book);
  }
  return items;
}

function gradeRank(grade: string | undefined): number {
  const normalized = String(grade || '').trim().toLowerCase();
  if (normalized === 'gold') {
    return 0;
  }
  if (normalized === 'silver' || normalized === 'silver draft' || normalized === 'mixed review') {
    return 1;
  }
  return 2;
}

export function summarizeWorkspaceSourceCatalog(
  room: WorkspaceSourceRoom | null | undefined,
): WorkspaceSourceCatalogStats {
  const officialBooks = room?.approved_wiki_runtime_books?.books ?? [];
  const officialHiddenRuntimeCount = Number(
    room?.approved_wiki_runtime_books?.hidden_count
      ?? room?.approved_wiki_runtime_books?.hidden_books?.length
      ?? 0,
  );
  const customerBooks = room?.customer_pack_runtime_books?.books ?? [];
  const customerPptSourceCount = customerBooks.filter(
    (book) => String(book.source_type || '').toLowerCase() === CUSTOMER_PPT_SOURCE_TYPE,
  ).length;
  const customerMasterRuntimeCount = customerBooks.filter(
    (book) => String(book.source_type || '').toLowerCase() === CUSTOMER_MASTER_SOURCE_TYPE,
  ).length;
  const customerDerivedRuntimeCount = customerBooks.filter((book) =>
    CUSTOMER_DERIVED_SOURCE_TYPES.has(String(book.source_type || '').toLowerCase()),
  ).length;

  return {
    runtimeBookCount: resolveWorkspaceSourceBooks(room).length,
    officialGoldRuntimeCount: officialBooks.length,
    officialHiddenRuntimeCount,
    officialCatalogCandidateCount: officialBooks.length + officialHiddenRuntimeCount,
    customerRuntimeBookCount: customerBooks.length,
    customerPptSourceCount,
    customerDerivedRuntimeCount,
    customerMasterRuntimeCount,
  };
}

export function resolveWorkspaceSourceBooks(room: WorkspaceSourceRoom | null | undefined): LibraryBook[] {
  if (!room) {
    return [];
  }

  const officialBooks = room.approved_wiki_runtime_books?.books?.length
    ? room.approved_wiki_runtime_books.books
    : room.manualbooks?.books?.length
      ? room.manualbooks.books
      : room.gold_books ?? [];
  const customerBooks = room.customer_pack_runtime_books?.books?.length
    ? room.customer_pack_runtime_books.books
    : room.user_library_books?.books ?? [];

  return dedupeBooks([...officialBooks, ...customerBooks]).sort((left, right) => {
    const gradeDelta = gradeRank(left.grade) - gradeRank(right.grade);
    if (gradeDelta !== 0) {
      return gradeDelta;
    }
    return (left.title || left.book_slug || '').localeCompare(right.title || right.book_slug || '', 'ko');
  });
}
