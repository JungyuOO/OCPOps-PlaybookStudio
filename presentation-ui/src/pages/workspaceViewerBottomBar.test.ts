import { describe, expect, it } from 'vitest';

import {
  resolveDraftScopedSourceId,
  resolveViewerBuildActionState,
} from './WorkspacePage';
import { buildWorkspaceViewerPanelClassName } from './workspace/WorkspaceViewerPanel';

describe('workspace viewer bottom bar helpers', () => {
  it('keeps save action visible for normalized drafts while hiding prepare pack', () => {
    const state = resolveViewerBuildActionState({ status: 'normalized' }, false, false);

    expect(state.show).toBe(true);
    expect(state.showPrepare).toBe(false);
    expect(state.canCapture).toBe(false);
    expect(state.canNormalize).toBe(true);
  });

  it('shows prepare pack only before normalization', () => {
    const state = resolveViewerBuildActionState({ status: 'captured' }, false, false);

    expect(state.show).toBe(true);
    expect(state.showPrepare).toBe(true);
    expect(state.canCapture).toBe(true);
    expect(state.canNormalize).toBe(true);
  });

  it('preserves draft scoped source ids across viewer navigation', () => {
    expect(resolveDraftScopedSourceId('draft:customer-pack-123')).toBe('draft:customer-pack-123');
    expect(resolveDraftScopedSourceId('viewer:/playbooks/customer-packs/customer-pack-123/index.html')).toBeUndefined();
    expect(resolveDraftScopedSourceId('')).toBeUndefined();
  });

  it('adds a docked layout class only when the bottom toolbar exists', () => {
    expect(buildWorkspaceViewerPanelClassName(true, false)).toContain('workspace-viewer-panel--with-bottom-toolbar');
    expect(buildWorkspaceViewerPanelClassName(false, false)).not.toContain('workspace-viewer-panel--with-bottom-toolbar');
    expect(buildWorkspaceViewerPanelClassName(true, true)).toContain('panel-collapsed-inner');
  });
});
