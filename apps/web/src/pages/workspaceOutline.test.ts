import { describe, expect, it } from 'vitest';
import type { WorkspaceManualBook } from './workspaceTypes';
import { buildOutlineBookFamilies, describeOutlineVariant } from './workspaceOutline';

function makeBook(book_slug: string, source_type: string, title = '설치 개요'): WorkspaceManualBook {
  return {
    book_slug,
    title,
    grade: 'Gold',
    review_status: 'approved',
    source_type,
    source_lane: 'approved_wiki_runtime',
    section_count: 10,
    code_block_count: 0,
    viewer_path: `/docs/ocp/4.20/ko/${book_slug}/index.html`,
    source_url: `https://example.com/${book_slug}`,
    updated_at: '2026-04-18T19:00:00+09:00',
  };
}

describe('buildOutlineBookFamilies', () => {
  it('groups one official book with its derived family variants', () => {
    const families = buildOutlineBookFamilies([
      makeBook('installation_overview_troubleshooting_playbook', 'troubleshooting_playbook'),
      makeBook('installation_overview', 'official_doc'),
      makeBook('installation_overview_topic_playbook', 'topic_playbook'),
      makeBook('installation_overview_policy_overlay_book', 'policy_overlay_book'),
    ]);

    expect(families).toHaveLength(1);
    expect(families[0].primary.book_slug).toBe('installation_overview');
    expect(families[0].variants.map((book) => book.book_slug)).toEqual([
      'installation_overview_topic_playbook',
      'installation_overview_policy_overlay_book',
      'installation_overview_troubleshooting_playbook',
    ]);
  });

  it('describes variant labels in user-facing Korean copy', () => {
    expect(describeOutlineVariant(makeBook('installation_overview_topic_playbook', 'topic_playbook'))).toBe('토픽 플레이북');
    expect(describeOutlineVariant(makeBook('installation_overview', 'official_doc'))).toBe('원문');
  });
});
