import { describe, expect, it } from 'vitest';
import type { LibraryBook } from './runtimeApi';
import { resolveWorkspaceSourceBooks } from './workspaceSourceCatalog';

function makeBook(book_slug: string, overrides: Partial<LibraryBook> = {}): LibraryBook {
  return {
    book_slug,
    title: overrides.title ?? book_slug,
    grade: overrides.grade ?? 'Gold',
    review_status: overrides.review_status ?? 'approved',
    source_type: overrides.source_type ?? 'official_doc',
    source_lane: overrides.source_lane ?? 'official_ko',
    section_count: overrides.section_count ?? 10,
    code_block_count: overrides.code_block_count ?? 1,
    viewer_path: overrides.viewer_path ?? `/docs/ocp/4.20/ko/${book_slug}/index.html`,
    source_url: overrides.source_url ?? `https://example.com/${book_slug}`,
    updated_at: overrides.updated_at ?? '2026-04-17T04:00:00+09:00',
  };
}

type WorkspaceSourceRoom = NonNullable<Parameters<typeof resolveWorkspaceSourceBooks>[0]>;

function makeRoom(overrides: Partial<WorkspaceSourceRoom> = {}): WorkspaceSourceRoom {
  return {
    known_books: [],
    gold_books: [],
    manualbooks: {
      selected_dir: '',
      books: [],
    },
    ...overrides,
  };
}

describe('resolveWorkspaceSourceBooks', () => {
  it('prefers latest pipeline playbooks over the broader source catalog', () => {
    const room = makeRoom({
      known_books: [makeBook('networking'), makeBook('storage'), makeBook('security')],
      manualbooks: {
        selected_dir: '',
        books: [makeBook('networking')],
      },
      approved_wiki_runtime_books: {
        selected_dir: '',
        books: [
          makeBook('networking', { grade: 'Gold' }),
          makeBook('backup_restore_operations', { grade: 'Bronze' }),
        ],
      },
    });

    expect(resolveWorkspaceSourceBooks(room).map((book) => book.book_slug)).toEqual([
      'networking',
      'backup_restore_operations',
    ]);
  });

  it('dedupes repeated latest pipeline playbooks by slug', () => {
    const room = makeRoom({
      approved_wiki_runtime_books: {
        selected_dir: '',
        books: [
          makeBook('networking'),
          makeBook('networking', { title: 'Networking Duplicate', grade: 'Silver' }),
          makeBook('storage', { grade: 'Silver' }),
        ],
      },
      known_books: [
        makeBook('networking'),
        makeBook('storage'),
      ],
    });

    expect(resolveWorkspaceSourceBooks(room).map((book) => book.book_slug)).toEqual([
      'networking',
      'storage',
    ]);
  });
});
