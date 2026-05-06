import type { DataControlRoomResponse, LibraryBook } from './runtimeApi';

type WorkspaceSourceRoom = Pick<
  DataControlRoomResponse,
  'known_books' | 'manualbooks' | 'approved_wiki_runtime_books' | 'gold_books'
>;

function dedupeBooks(books: readonly LibraryBook[]): LibraryBook[] {
  const seen = new Set<string>();
  const items: LibraryBook[] = [];
  for (const book of books) {
    const key = (book.book_slug || book.viewer_path || book.title || '').trim();
    if (!key || seen.has(key)) {
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

export function resolveWorkspaceSourceBooks(room: WorkspaceSourceRoom | null | undefined): LibraryBook[] {
  if (!room) {
    return [];
  }

  const preferredBooks = room.approved_wiki_runtime_books?.books?.length
    ? room.approved_wiki_runtime_books.books
    : room.manualbooks?.books?.length
      ? room.manualbooks.books
      : room.gold_books ?? [];

  return dedupeBooks(preferredBooks).sort((left, right) => {
    const gradeDelta = gradeRank(left.grade) - gradeRank(right.grade);
    if (gradeDelta !== 0) {
      return gradeDelta;
    }
    return (left.title || left.book_slug || '').localeCompare(right.title || right.book_slug || '', 'ko');
  });
}
