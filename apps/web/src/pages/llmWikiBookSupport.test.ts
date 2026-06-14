import { describe, expect, it } from 'vitest';
import { normalizeViewerDocumentPayload } from './llmWikiBookSupport';
import type { ViewerDocumentResponse } from '../lib/runtimeApi';

describe('normalizeViewerDocumentPayload', () => {
  it('preserves viewer cache and timing metadata without changing viewer content', () => {
    const payload = normalizeViewerDocumentPayload({
      viewer_path: '/playbooks/wiki-runtime/active/support/index.html',
      body_class_name: 'is-embedded',
      inline_styles: ['.viewer-root { color: #111; }'],
      html: '<section>support</section>',
      viewer_cache_status: 'hit',
      viewer_timings_ms: {
        viewer_cache_lookup: 0.4,
        viewer_document_total: 8.2,
      },
      interaction_policy: {
        code_copy: true,
        code_wrap_toggle: true,
        recent_position_tracking: true,
        anchor_navigation: true,
      },
    } satisfies ViewerDocumentResponse);

    expect(payload.html).toBe('<section>support</section>');
    expect(payload.inlineStyles).toEqual(['.viewer-root { color: #111; }']);
    expect(payload.bodyClassName).toBe('is-embedded');
    expect(payload.viewerCacheStatus).toBe('hit');
    expect(payload.viewerTimingsMs).toEqual({
      viewer_cache_lookup: 0.4,
      viewer_document_total: 8.2,
    });
  });
});
