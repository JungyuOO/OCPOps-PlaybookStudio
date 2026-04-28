import { describe, expect, it } from 'vitest';
import type { LibraryBook } from './runtimeApi';
import {
  isCustomerPackRuntimeBook,
  resolveWorkspaceSourceBooks,
  summarizeWorkspaceSourceCatalog,
} from './workspaceSourceCatalog';

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

  it('keeps uploaded customer books in the same workspace source catalog', () => {
    const room = makeRoom({
      approved_wiki_runtime_books: {
        selected_dir: '',
        books: [makeBook('networking', { grade: 'Gold' })],
      },
      customer_pack_runtime_books: {
        selected_dir: '',
        books: [
          makeBook('customer-master', {
            grade: 'Gold',
            source_collection: 'uploaded',
            source_lane: 'customer_source_first_pack',
            viewer_path: '/playbooks/customer-packs/customer-master/index.html',
          }),
        ],
      },
    });

    expect(resolveWorkspaceSourceBooks(room).map((book) => book.book_slug)).toEqual([
      'customer-master',
      'networking',
    ]);
  });

  it('does not collapse official and customer runtime books that share a slug', () => {
    const room = makeRoom({
      approved_wiki_runtime_books: {
        selected_dir: '',
        books: [makeBook('networking', {
          grade: 'Gold',
          source_lane: 'approved_wiki_runtime',
          source_collection: 'official',
        })],
      },
      customer_pack_runtime_books: {
        selected_dir: '',
        books: [makeBook('networking', {
          grade: 'Gold',
          source_type: 'pptx',
          source_lane: 'customer_source_first_pack',
          source_collection: 'uploaded',
          viewer_path: '/playbooks/customer-packs/networking/index.html',
        })],
      },
    });

    expect(resolveWorkspaceSourceBooks(room).map((book) => `${book.source_lane}:${book.book_slug}`)).toEqual([
      'approved_wiki_runtime:networking',
      'customer_source_first_pack:networking',
    ]);
  });
});

describe('summarizeWorkspaceSourceCatalog', () => {
  it('keeps official gold, hidden silver, customer source, and derived counts separate', () => {
    const room = makeRoom({
      approved_wiki_runtime_books: {
        selected_dir: '',
        hidden_count: 72,
        books: [
          makeBook('installing', { grade: 'Gold' }),
          makeBook('networking', { grade: 'Gold' }),
        ],
      },
      customer_pack_runtime_books: {
        selected_dir: '',
        books: [
          makeBook('customer-ppt-1', { source_type: 'pptx', source_lane: 'customer_source_first_pack' }),
          makeBook('customer-ppt-2', { source_type: 'pptx', source_lane: 'customer_source_first_pack' }),
          makeBook('customer-topic-1', { source_type: 'topic_playbook', source_lane: 'customer_source_first_pack' }),
          makeBook('customer-ops-1', { source_type: 'operation_playbook', source_lane: 'customer_source_first_pack' }),
          makeBook('customer-master', { source_type: 'customer_master_book', source_lane: 'customer_source_first_pack' }),
        ],
      },
    });

    expect(summarizeWorkspaceSourceCatalog(room)).toMatchObject({
      runtimeBookCount: 7,
      officialGoldRuntimeCount: 2,
      officialHiddenRuntimeCount: 72,
      officialCatalogCandidateCount: 74,
      customerRuntimeBookCount: 5,
      customerPptSourceCount: 2,
      customerDerivedRuntimeCount: 2,
      customerMasterRuntimeCount: 1,
    });
  });
});

describe('isCustomerPackRuntimeBook', () => {
  it('separates customer pack runtime from official runtime', () => {
    expect(isCustomerPackRuntimeBook(makeBook('official', {
      source_type: 'reader_grade_md',
      source_lane: 'approved_wiki_runtime',
      source_collection: 'official',
    }))).toBe(false);
    expect(isCustomerPackRuntimeBook(makeBook('customer-ppt', {
      source_type: 'pptx',
      source_lane: 'customer_source_first_pack',
      viewer_path: '/playbooks/customer-packs/customer-ppt/index.html',
    }))).toBe(true);
    expect(isCustomerPackRuntimeBook(makeBook('customer-derived', {
      source_type: 'troubleshooting_playbook',
      source_lane: 'customer_source_first_pack',
    }))).toBe(true);
  });
});
