import { describe, expect, it } from 'vitest';
import type { ChatResponse } from '../lib/runtimeApi';
import {
  deriveSeverity,
  deriveVerdict,
  evaluateScorecard,
  summarizeScorecard,
} from './scorecardEval';

function makeResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    answer: 'answer',
    citations: [
      {
        index: 1,
        book_slug: 'operators',
        section: 'Installing Operators',
        section_path: 'Installing Operators',
        viewer_path: '/wiki/operators#installing-operators',
        source_lane: 'official',
      },
    ],
    warnings: [],
    session_id: 'session-1',
    suggested_queries: ['next question'],
    related_links: [{ label: 'Operators', href: '/wiki/operators', kind: 'book' }],
    related_sections: [{ label: 'Installing Operators', href: '/wiki/operators#installing-operators', kind: 'book' }],
    response_kind: 'rag',
    ...overrides,
  };
}

describe('scorecardEval', () => {
  it('derives grounded verdict for clean grounded answer', () => {
    expect(deriveVerdict(makeResponse())).toBe('Grounded');
  });

  it('derives risk severity when warnings exist', () => {
    const result = makeResponse({ warnings: ['citation mismatch'] });
    expect(deriveSeverity(result, []).severity).toBe('risk');
  });

  it('passes all applicable product-gate checks for grounded official response', () => {
    const items = evaluateScorecard(makeResponse());
    const summary = summarizeScorecard(items);

    expect(items.find((item) => item.id === 'product-002')?.outcome).toBe('pass');
    expect(items.find((item) => item.id === 'product-003')?.outcome).toBe('pass');
    expect(items.find((item) => item.id === 'product-004')?.outcome).toBe('n/a');
    expect(items.find((item) => item.id === 'product-005')?.outcome).toBe('pass');
    expect(summary.pass).toBe(4);
    expect(summary.fail).toBe(0);
  });

  it('fails traceability when citation landing fields are missing', () => {
    const bad = makeResponse({
      citations: [
        {
          index: 1,
          book_slug: 'operators',
          section: 'Installing Operators',
          viewer_path: '',
        },
      ],
    });

    const items = evaluateScorecard(bad);
    expect(items.find((item) => item.id === 'product-003')?.outcome).toBe('fail');
  });
});
