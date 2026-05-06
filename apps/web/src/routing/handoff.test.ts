import { describe, expect, it } from 'vitest';
import { buildHandoffLocation } from './handoff';

describe('buildHandoffLocation', () => {
  it('preserves search and hash during alias handoff', () => {
    expect(
      buildHandoffLocation('/studio', {
        search: '?tab=partner',
        hash: '#top',
      }),
    ).toEqual({
      pathname: '/studio',
      search: '?tab=partner',
      hash: '#top',
    });
  });

  it('falls back to empty search and hash when absent', () => {
    expect(buildHandoffLocation('/llmwikibook', {})).toEqual({
      pathname: '/llmwikibook',
      search: '',
      hash: '',
    });
  });
});
