import { describe, expect, it } from 'vitest';

import { DEFAULT_VISION_MODE, WIKI_VISION_MODES, resolveVisionMode } from './wikiVision';

describe('wikiVision', () => {
  it('accepts supported vision modes', () => {
    expect(resolveVisionMode('guided_tour')).toBe('guided_tour');
    expect(resolveVisionMode('encyclopedia_world')).toBe('encyclopedia_world');
  });

  it('falls back to atlas canvas for invalid values', () => {
    expect(resolveVisionMode(null)).toBe(DEFAULT_VISION_MODE);
    expect(resolveVisionMode('unknown-mode')).toBe(DEFAULT_VISION_MODE);
  });

  it('keeps the three supported wiki vision descriptors aligned', () => {
    expect(WIKI_VISION_MODES.map((mode) => mode.id)).toEqual([
      'atlas_canvas',
      'guided_tour',
      'encyclopedia_world',
    ]);
    expect(WIKI_VISION_MODES.every((mode) => mode.compare.bullets.length >= 3)).toBe(true);
  });
});
