import { useEffect, useRef, useState } from 'react';
import type { WikiEditedTextStyle, WikiTextAnnotation, WikiTextAnnotationMode } from '../lib/runtimeApi';

export interface ViewerDocumentPayload {
  html: string;
  inlineStyles: string[];
  bodyClassName: string;
  interactionPolicy?: {
    codeCopy?: boolean;
    codeWrapToggle?: boolean;
    recentPositionTracking?: boolean;
    anchorNavigation?: boolean;
  };
}

const VIEWER_READER_POLISH = `
  :host {
    display: block;
    color: #0f172a;
    min-width: 0;
    max-width: 100%;
  }

  .viewer-root {
    min-height: 100%;
    background: transparent;
    padding-bottom: 40px;
    min-width: 0;
    max-width: 100%;
  }

  /* 
   * Allow the native styling from viewer_page.py to take over entirely.
   * Hide the reader-sidebar as requested by user ("목록들은 껍데기같은데 싹 지우면 안돼?").
   */
  .viewer-root .reader-sidebar {
    display: none !important;
  }

  .viewer-root .reader-layout {
    grid-template-columns: 1fr !important;
    min-width: 0 !important;
    max-width: 100% !important;
  }

  .viewer-root .hero .actions.hero-actions,
  .viewer-root .hero .hero-meta,
  .viewer-root .hero .meta-pill {
    display: none !important;
  }

  .viewer-root .document-toolbar {
    display: none !important;
  }

  .viewer-root .hero {
    margin-bottom: 20px !important;
  }

  /* Constrain the main width similar to a typical book/documentation layout */
  .viewer-root main {
    width: min(860px, 100%) !important;
    max-width: 860px !important;
    margin: 0 auto !important;
    padding: 28px 32px 56px !important;
    min-width: 0 !important;
  }

  .viewer-root .section-card {
    background: var(--pbs-reader-card-bg) !important;
    border: 1px solid var(--pbs-reader-border) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03) !important;
    border-radius: 12px !important;
    margin-bottom: 24px !important;
    transition: border-color 0.3s ease, background-color 0.3s ease;
  }

  .viewer-root .section-header h2,
  .viewer-root .section-header h3 {
    color: var(--pbs-reader-text) !important;
  }

  .viewer-root .section-meta {
    color: var(--pbs-reader-dim) !important;
  }

  .viewer-root .code-block {
    background: rgba(0,0,0,0.03) !important;
    border: 1px solid var(--pbs-reader-border) !important;
  }

  .viewer-root .code-block pre,
  .viewer-root .code-block code,
  .viewer-root .code-block span,
  .viewer-root pre,
  .viewer-root pre code {
    color: #0f172a !important;
  }

  :host([data-viewer-theme="obsidian"]) .viewer-root .code-block {
    background: rgba(255,255,255,0.03) !important;
  }

  :host([data-viewer-theme="obsidian"]) .viewer-root .code-block pre,
  :host([data-viewer-theme="obsidian"]) .viewer-root .code-block code,
  :host([data-viewer-theme="obsidian"]) .viewer-root .code-block span,
  :host([data-viewer-theme="obsidian"]) .viewer-root pre,
  :host([data-viewer-theme="obsidian"]) .viewer-root pre code {
    color: #e5eef8 !important;
  }

  .viewer-root .study-document,
  .viewer-root .hero,
  .viewer-root .hero-grid,
  .viewer-root .hero-main,
  .viewer-root .section-list,
  .viewer-root .section-body,
  .viewer-root .table-wrap {
    min-width: 0 !important;
    max-width: 100% !important;
  }

  @media (max-width: 1100px) {
    .viewer-root main {
      padding: 24px 20px 48px !important;
    }
  }

  :host([data-viewer-variant="editorial"]) .viewer-root {
    background: transparent;
    color: #182230;
  }

  :host([data-viewer-variant="editorial"]) .viewer-root main {
    width: min(760px, 100%) !important;
    max-width: 760px !important;
    padding: 0 0 72px !important;
  }

  :host([data-viewer-variant="editorial"]) .viewer-root .hero {
    margin-bottom: 28px !important;
  }

  :host([data-viewer-variant="editorial"]) .viewer-root .section-card {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    margin-bottom: 34px !important;
  }

  :host([data-viewer-variant="editorial"]) .viewer-root .code-block {
    background: #f5f7fb !important;
    border: 1px solid #d9e0ea !important;
    border-radius: 14px !important;
    box-shadow: none !important;
  }

  :host([data-viewer-variant="editorial"]) .viewer-root .table-wrap {
    border-radius: 14px !important;
    border: 1px solid #dde4ef !important;
    box-shadow: none !important;
    background: #ffffff !important;
  }
`;

const VIEWER_ANNOTATION_POLISH = `
  .viewer-annotated-section {
    position: relative !important;
  }

  .viewer-section-annotation-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 9;
  }

  .viewer-floating-text-annotation,
  .viewer-inline-text-patch {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    border-radius: 18px;
    border: 1px solid rgba(194, 120, 49, 0.16);
    background: rgba(255, 252, 247, 0.96);
    box-shadow: 0 16px 28px rgba(89, 64, 37, 0.08);
    color: #2e2219;
    text-align: left;
  }

  .viewer-floating-text-annotation {
    position: absolute;
    left: calc(var(--annotation-x, 0.08) * 100%);
    top: calc(var(--annotation-y, 0.12) * 100%);
    width: min(340px, max(190px, calc(100% - 32px - (var(--annotation-x, 0.08) * 100%))));
    padding: 13px 15px;
    pointer-events: auto;
    cursor: pointer;
    transform: translateY(-4px);
  }

  .viewer-inline-source-block-hidden {
    display: none !important;
  }

  .viewer-inline-text-patch {
    position: relative;
    width: 100%;
    margin: 10px 0 12px;
    padding: 14px 16px;
    cursor: pointer;
  }

  .viewer-text-annotation-kicker {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 24px;
    padding: 0 9px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.72);
    color: #8f5a2c;
    font-size: 0.66rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .viewer-text-annotation-body {
    display: block;
    width: 100%;
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.7;
  }
`;

type ViewerTextEditorDraft = {
  annotationId: string;
  anchor: string;
  title: string;
  kind: WikiTextAnnotationMode;
  text: string;
  xRatio: number;
  yRatio: number;
  blockPath: string;
  style: WikiEditedTextStyle;
  left: number;
  top: number;
};

function editedTextToneColor(tone: string): string {
  switch (String(tone || '').trim().toLowerCase()) {
    case 'ink':
      return '#2e2219';
    case 'teal':
      return '#16555f';
    case 'cyan':
      return '#0f6e85';
    case 'rose':
      return '#9f1239';
    case 'violet':
      return '#6d28d9';
    case 'lime':
      return '#4d7c0f';
    default:
      return '#6d451f';
  }
}

function editedTextSurfaceColor(tone: string): { border: string; background: string } {
  switch (String(tone || '').trim().toLowerCase()) {
    case 'ink':
      return { border: 'rgba(98, 82, 69, 0.18)', background: 'rgba(252, 249, 244, 0.98)' };
    case 'teal':
      return { border: 'rgba(22, 85, 95, 0.2)', background: 'rgba(241, 253, 254, 0.98)' };
    case 'cyan':
      return { border: 'rgba(14, 116, 144, 0.18)', background: 'rgba(241, 252, 255, 0.98)' };
    case 'rose':
      return { border: 'rgba(190, 24, 93, 0.18)', background: 'rgba(255, 244, 248, 0.98)' };
    case 'violet':
      return { border: 'rgba(109, 40, 217, 0.18)', background: 'rgba(248, 245, 255, 0.98)' };
    case 'lime':
      return { border: 'rgba(77, 124, 15, 0.18)', background: 'rgba(248, 255, 238, 0.98)' };
    default:
      return { border: 'rgba(194, 120, 49, 0.16)', background: 'rgba(255, 252, 247, 0.98)' };
  }
}

function normalizeEditedTextStyle(value?: Partial<WikiEditedTextStyle> | null): WikiEditedTextStyle {
  const tone = String(value?.tone || '').trim().toLowerCase();
  const size = String(value?.size || '').trim().toLowerCase();
  const weight = String(value?.weight || '').trim().toLowerCase();
  return {
    tone:
      tone === 'ink'
        || tone === 'teal'
        || tone === 'amber'
        || tone === 'cyan'
        || tone === 'rose'
        || tone === 'violet'
        || tone === 'lime'
        ? tone
        : 'amber',
    size: size === 'sm' || size === 'md' || size === 'lg' ? size : 'md',
    weight: weight === 'strong' || weight === 'regular' ? weight : 'regular',
  };
}

function applyAnnotationTextStyle(node: HTMLElement, styleValue?: Partial<WikiEditedTextStyle> | null): void {
  const style = normalizeEditedTextStyle(styleValue);
  const surface = editedTextSurfaceColor(style.tone);
  node.style.color = editedTextToneColor(style.tone);
  node.style.borderColor = surface.border;
  node.style.background = surface.background;
  node.style.fontSize = style.size === 'sm' ? '0.88rem' : style.size === 'lg' ? '1.04rem' : '0.95rem';
  node.style.fontWeight = style.weight === 'strong' ? '700' : '500';
}

function clampAnnotationRatio(value: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.max(0, Math.min(1, value));
}

function findSectionFromNode(node: HTMLElement | null): HTMLElement | null {
  const section = node?.closest('section.section-card[id], section.embedded-section[id]');
  return section instanceof HTMLElement ? section : null;
}

function findEditableBlock(node: HTMLElement | null): HTMLElement | null {
  const block = node?.closest('p, li, h2, h3, h4, h5, blockquote, td, th');
  if (!(block instanceof HTMLElement)) {
    return null;
  }
  if (block.closest('.code-block, pre, .viewer-inline-text-patch, .viewer-floating-text-annotation')) {
    return null;
  }
  return block;
}

function elementPathWithinSection(section: HTMLElement, element: HTMLElement): string {
  const path: number[] = [];
  let current: HTMLElement | null = element;
  while (current && current !== section) {
    const parent: HTMLElement | null = current.parentElement;
    if (!parent) {
      return '';
    }
    const index = Array.from(parent.children).indexOf(current);
    if (index < 0) {
      return '';
    }
    path.push(index);
    current = parent;
  }
  return path.reverse().join('.');
}

function elementFromSectionPath(section: HTMLElement, path: string): HTMLElement | null {
  const segments = String(path || '').split('.').filter(Boolean);
  let current: Element = section;
  for (const segment of segments) {
    const index = Number(segment);
    if (!Number.isInteger(index) || index < 0 || !current.children[index]) {
      return null;
    }
    current = current.children[index];
  }
  return current instanceof HTMLElement ? current : null;
}

function isViewerHref(href: string): boolean {
  try {
    const parsed = new URL(href, window.location.origin);
    return (
      parsed.pathname.startsWith('/playbooks/')
      || parsed.pathname.startsWith('/docs/ocp/')
      || parsed.pathname.startsWith('/wiki/entities/')
      || parsed.pathname.startsWith('/wiki/figures/')
    );
  } catch {
    return false;
  }
}

function scrollShadowTargetIntoView(host: HTMLDivElement, targetNode: HTMLElement): void {
  let scrollContainer: Element | null = host.parentElement;
  while (scrollContainer && scrollContainer !== document.documentElement) {
    const style = window.getComputedStyle(scrollContainer);
    if (style.overflowY === 'auto' || style.overflowY === 'scroll') break;
    scrollContainer = scrollContainer.parentElement;
  }
  if (scrollContainer && scrollContainer !== document.documentElement) {
    const containerRect = scrollContainer.getBoundingClientRect();
    const nodeRect = targetNode.getBoundingClientRect();
    const targetScrollTop = scrollContainer.scrollTop + (nodeRect.top - containerRect.top) - 16;
    scrollContainer.scrollTo({ top: targetScrollTop, behavior: 'smooth' });
    return;
  }
  targetNode.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function findScrollContainer(host: HTMLDivElement): HTMLElement | Window {
  let scrollContainer: Element | null = host.parentElement;
  while (scrollContainer && scrollContainer !== document.documentElement) {
    const style = window.getComputedStyle(scrollContainer);
    if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
      return scrollContainer as HTMLElement;
    }
    scrollContainer = scrollContainer.parentElement;
  }
  return window;
}

function sectionDescriptor(node: HTMLElement | null): { anchor: string; title: string } | null {
  if (!node) {
    return null;
  }
  const anchor = String(node.id || '').trim();
  if (!anchor) {
    return null;
  }
  const title = node.querySelector('h2, h3, .section-title, .section-meta')?.textContent?.trim() || anchor;
  return { anchor, title };
}

function pickActiveSection(
  sections: HTMLElement[],
  scrollContainer: HTMLElement | Window,
): HTMLElement | null {
  if (sections.length === 0) {
    return null;
  }
  let containerRect: { top: number; height: number };
  if (scrollContainer === window) {
    containerRect = { top: 0, height: window.innerHeight };
  } else {
    containerRect = (scrollContainer as HTMLElement).getBoundingClientRect();
  }
  const leadLine = containerRect.top + Math.min(160, Math.max(containerRect.height * 0.24, 72));
  let currentSection: HTMLElement | null = null;
  let nextSection: HTMLElement | null = null;

  for (const section of sections) {
    const rect = section.getBoundingClientRect();
    if (rect.top <= leadLine && rect.bottom > leadLine) {
      return section;
    }
    if (rect.top <= leadLine) {
      currentSection = section;
      continue;
    }
    nextSection = section;
    break;
  }

  return currentSection ?? nextSection ?? sections[0];
}

function findShadowTarget(root: ShadowRoot, targetId: string): HTMLElement | null {
  const normalizedTargetId = String(targetId || '').trim();
  if (!normalizedTargetId) {
    return null;
  }
  const candidates = [normalizedTargetId];
  try {
    const decodedTargetId = decodeURIComponent(normalizedTargetId);
    if (decodedTargetId && decodedTargetId !== normalizedTargetId) {
      candidates.push(decodedTargetId);
    }
  } catch {
    // Keep the raw hash when the fragment is not URI-encoded.
  }
  for (const candidate of candidates) {
    const matched =
      root.getElementById(candidate)
      ?? root.querySelector(`[id="${CSS.escape(candidate)}"]`);
    if (matched instanceof HTMLElement) {
      return matched;
    }
  }
  return null;
}

function findSectionNodes(container: ParentNode): HTMLElement[] {
  return Array.from(
    container.querySelectorAll('section.section-card[id], section.embedded-section[id]'),
  ).filter((node): node is HTMLElement => node instanceof HTMLElement);
}

export default function ViewerDocumentStage({
  viewerDocument,
  currentViewerPath,
  onNavigateViewerPath,
  onActiveSectionChange,
  textAnnotationsByAnchor,
  textToolEnabled = false,
  textToolMode = 'add',
  activeTextStyle,
  onSaveTextAnnotation,
  onRemoveTextAnnotation,
  className,
  surfaceVariant = 'default',
}: {
  viewerDocument: ViewerDocumentPayload;
  currentViewerPath?: string;
  onNavigateViewerPath?: (viewerPath: string) => void;
  onActiveSectionChange?: (section: { anchor: string; title: string } | null) => void;
  textAnnotationsByAnchor?: Record<string, WikiTextAnnotation[]>;
  textToolEnabled?: boolean;
  textToolMode?: WikiTextAnnotationMode;
  activeTextStyle?: WikiEditedTextStyle;
  onSaveTextAnnotation?: (
    section: { anchor: string; title: string },
    annotation: WikiTextAnnotation,
  ) => void;
  onRemoveTextAnnotation?: (
    section: { anchor: string; title: string },
    annotationId: string,
  ) => void;
  className?: string;
  surfaceVariant?: 'default' | 'editorial';
}) {
  const shellRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const shadowRootRef = useRef<ShadowRoot | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<HTMLDivElement | null>(null);
  const editorTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const latestViewerPathRef = useRef(currentViewerPath);
  const latestNavigateViewerPathRef = useRef(onNavigateViewerPath);
  const latestActiveSectionChangeRef = useRef(onActiveSectionChange);
  const latestTextAnnotationsRef = useRef(textAnnotationsByAnchor ?? {});
  const latestTextToolEnabledRef = useRef(textToolEnabled);
  const latestTextToolModeRef = useRef(textToolMode);
  const latestTextStyleRef = useRef(activeTextStyle);
  const latestSaveTextAnnotationRef = useRef(onSaveTextAnnotation);
  const latestRemoveTextAnnotationRef = useRef(onRemoveTextAnnotation);
  const [editorDraft, setEditorDraft] = useState<ViewerTextEditorDraft | null>(null);
  const inlineStylesKey = viewerDocument.inlineStyles.join('\n/*__viewer-style-split__*/\n');

  latestViewerPathRef.current = currentViewerPath;
  latestNavigateViewerPathRef.current = onNavigateViewerPath;
  latestActiveSectionChangeRef.current = onActiveSectionChange;
  latestTextAnnotationsRef.current = textAnnotationsByAnchor ?? {};
  latestTextToolEnabledRef.current = textToolEnabled;
  latestTextToolModeRef.current = textToolMode;
  latestTextStyleRef.current = activeTextStyle;
  latestSaveTextAnnotationRef.current = onSaveTextAnnotation;
  latestRemoveTextAnnotationRef.current = onRemoveTextAnnotation;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    host.dataset.viewerVariant = surfaceVariant;
    const root = host.shadowRoot ?? host.attachShadow({ mode: 'open' });
    shadowRootRef.current = root;
    root.replaceChildren();

    viewerDocument.inlineStyles.forEach((styleText) => {
      const style = document.createElement('style');
      style.textContent = styleText;
      root.appendChild(style);
    });

    const polishStyle = document.createElement('style');
    polishStyle.textContent = VIEWER_READER_POLISH;
    root.appendChild(polishStyle);

    const annotationStyle = document.createElement('style');
    annotationStyle.textContent = VIEWER_ANNOTATION_POLISH;
    root.appendChild(annotationStyle);

    const wrapper = document.createElement('div');
    wrapper.className = ['viewer-root', 'is-embedded', viewerDocument.bodyClassName].filter(Boolean).join(' ');
    wrapper.innerHTML = viewerDocument.html;
    root.appendChild(wrapper);
    wrapperRef.current = wrapper;

    let cleanupSectionTracking = (): void => { };
    const sections = findSectionNodes(wrapper);
    if (sections.length === 0) {
      latestActiveSectionChangeRef.current?.(null);
    } else {
      const scrollContainer = findScrollContainer(host);
      const scrollTarget = scrollContainer === window ? window : scrollContainer;
      let frameId = 0;
      let lastAnchor = '';
      const syncActiveSection = (): void => {
        if (frameId) {
          window.cancelAnimationFrame(frameId);
        }
        frameId = window.requestAnimationFrame(() => {
          const nextSection = sectionDescriptor(pickActiveSection(sections, scrollContainer));
          const nextAnchor = nextSection?.anchor || '';
          if (nextAnchor === lastAnchor) {
            return;
          }
          lastAnchor = nextAnchor;
          latestActiveSectionChangeRef.current?.(nextSection);
        });
      };
      syncActiveSection();
      scrollTarget.addEventListener('scroll', syncActiveSection, { passive: true });
      window.addEventListener('resize', syncActiveSection);
      const resizeObserver = new ResizeObserver(() => {
        syncActiveSection();
      });
      resizeObserver.observe(host);
      sections.forEach((section) => resizeObserver.observe(section));
      cleanupSectionTracking = (): void => {
        if (frameId) {
          window.cancelAnimationFrame(frameId);
        }
        scrollTarget.removeEventListener('scroll', syncActiveSection);
        window.removeEventListener('resize', syncActiveSection);
        resizeObserver.disconnect();
        latestActiveSectionChangeRef.current?.(null);
      };
    }

    root.querySelectorAll('a[href]').forEach((node) => {
      const anchor = node as HTMLAnchorElement;
      const href = anchor.getAttribute('href') ?? '';
      if (!href || href.startsWith('#') || isViewerHref(href)) {
        return;
      }
      if (!anchor.hasAttribute('target')) {
        anchor.setAttribute('target', '_blank');
      }
      anchor.setAttribute('rel', 'noreferrer');
    });

    const buildEditorDraftFromInteraction = (
      target: HTMLElement | null,
      clickEvent?: MouseEvent,
    ): ViewerTextEditorDraft | null => {
      if (!latestTextToolEnabledRef.current || !target) {
        return null;
      }
      if (target.closest('.copy-button, .wrap-button, .collapse-button, .document-nav-menu')) {
        return null;
      }

      const hostRect = host.getBoundingClientRect();
      const currentAnnotations = latestTextAnnotationsRef.current;
      const annotationNode = target.closest('.viewer-floating-text-annotation, .viewer-inline-text-patch') as HTMLElement | null;
      if (annotationNode) {
        const section = findSectionFromNode(annotationNode);
        const descriptor = sectionDescriptor(section);
        if (!descriptor) {
          return null;
        }
        const existing = (currentAnnotations[descriptor.anchor] ?? []).find((item) => (
          item.annotation_id === annotationNode.dataset.annotationId
        ));
        const referenceRect = annotationNode.getBoundingClientRect();
        return {
          annotationId: existing?.annotation_id || annotationNode.dataset.annotationId || `ant-${Date.now()}`,
          anchor: descriptor.anchor,
          title: descriptor.title,
          kind: existing?.kind ?? (annotationNode.classList.contains('viewer-inline-text-patch') ? 'edit' : 'add'),
          text: existing?.text ?? '',
          xRatio: clampAnnotationRatio(Number(existing?.x_ratio ?? annotationNode.dataset.annotationX ?? 0.08), 0.08),
          yRatio: clampAnnotationRatio(Number(existing?.y_ratio ?? annotationNode.dataset.annotationY ?? 0.12), 0.12),
          blockPath: String(existing?.block_path || annotationNode.dataset.blockPath || ''),
          style: normalizeEditedTextStyle(existing?.style ?? latestTextStyleRef.current),
          left: Math.max(12, Math.min(referenceRect.left - hostRect.left, hostRect.width - 344)),
          top: Math.max(12, referenceRect.bottom - hostRect.top + 10),
        };
      }

      const section = findSectionFromNode(target);
      const descriptor = sectionDescriptor(section);
      if (!section || !descriptor) {
        return null;
      }

      if (latestTextToolModeRef.current === 'edit') {
        const editableBlock = findEditableBlock(target);
        if (!editableBlock) {
          return null;
        }
        const blockPath = elementPathWithinSection(section, editableBlock);
        if (!blockPath) {
          return null;
        }
        const existing = (currentAnnotations[descriptor.anchor] ?? []).find((item) => (
          item.kind === 'edit' && item.block_path === blockPath
        ));
        const blockRect = editableBlock.getBoundingClientRect();
        return {
          annotationId: existing?.annotation_id || `ant-${Date.now()}`,
          anchor: descriptor.anchor,
          title: descriptor.title,
          kind: 'edit',
          text: existing?.text ?? editableBlock.textContent?.trim() ?? '',
          xRatio: clampAnnotationRatio(Number(existing?.x_ratio ?? 0.08), 0.08),
          yRatio: clampAnnotationRatio(Number(existing?.y_ratio ?? 0.12), 0.12),
          blockPath,
          style: normalizeEditedTextStyle(existing?.style ?? latestTextStyleRef.current),
          left: Math.max(12, Math.min(blockRect.left - hostRect.left, hostRect.width - 344)),
          top: Math.max(12, blockRect.bottom - hostRect.top + 10),
        };
      }

      const sectionRect = section.getBoundingClientRect();
      const clientX = clickEvent?.clientX ?? sectionRect.left + 40;
      const clientY = clickEvent?.clientY ?? sectionRect.top + 48;
      return {
        annotationId: `ant-${Date.now()}`,
        anchor: descriptor.anchor,
        title: descriptor.title,
        kind: 'add',
        text: '',
        xRatio: clampAnnotationRatio((clientX - sectionRect.left) / Math.max(sectionRect.width, 1), 0.08),
        yRatio: clampAnnotationRatio((clientY - sectionRect.top) / Math.max(sectionRect.height, 1), 0.12),
        blockPath: '',
        style: normalizeEditedTextStyle(latestTextStyleRef.current),
        left: Math.max(12, Math.min(clientX - hostRect.left, hostRect.width - 344)),
        top: Math.max(12, clientY - hostRect.top + 10),
      };
    };

    const handleClick = async (event: Event): Promise<void> => {
      const target = event.target as HTMLElement | null;
      if (latestTextToolEnabledRef.current) {
        const editorCandidate = buildEditorDraftFromInteraction(target, event as MouseEvent);
        if (editorCandidate) {
          event.preventDefault();
          event.stopPropagation();
          setEditorDraft(editorCandidate);
          return;
        }
      }

      const anchor = target?.closest('a[href]') as HTMLAnchorElement | null;
      if (anchor) {
        const href = anchor.getAttribute('href') ?? '';
        const navMenu = anchor.closest('.document-nav-menu') as HTMLDetailsElement | null;
        if (href.startsWith('#')) {
          event.preventDefault();
          const targetId = href.slice(1);
          const targetNode = findShadowTarget(root, targetId);
          if (targetNode instanceof HTMLElement) {
            scrollShadowTargetIntoView(host, targetNode);
          }
          if (!targetNode && latestNavigateViewerPathRef.current && latestViewerPathRef.current) {
            const basePath = latestViewerPathRef.current.split('#', 1)[0];
            if (basePath) {
              latestNavigateViewerPathRef.current(`${basePath}#${targetId}`);
            }
          }
          if (navMenu) {
            navMenu.open = false;
          }
          return;
        }
        if (href && isViewerHref(href) && latestNavigateViewerPathRef.current) {
          event.preventDefault();
          const parsed = new URL(href, window.location.origin);
          if (navMenu) {
            navMenu.open = false;
          }
          latestNavigateViewerPathRef.current(`${parsed.pathname}${parsed.search}${parsed.hash}`);
          return;
        }
      }

      const button = target?.closest('button');
      if (!button) {
        return;
      }
      if (button.classList.contains('copy-button')) {
        const copyPayload = button.getAttribute('data-copy') ?? '""';
        const defaultLabel = button.getAttribute('data-label-default') ?? '복사';
        try {
          const text = JSON.parse(copyPayload) as string;
          if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
          }
          button.classList.add('is-copied');
          button.setAttribute('title', button.getAttribute('data-label-active') ?? '복사됨');
          button.setAttribute('aria-label', button.getAttribute('data-label-active') ?? '복사됨');
          window.setTimeout(() => {
            button.classList.remove('is-copied');
            button.setAttribute('title', defaultLabel);
            button.setAttribute('aria-label', defaultLabel);
          }, 1400);
        } catch {
          button.setAttribute('title', '실패');
          button.setAttribute('aria-label', '실패');
          window.setTimeout(() => {
            button.setAttribute('title', defaultLabel);
            button.setAttribute('aria-label', defaultLabel);
          }, 1400);
        }
        return;
      }
      if (button.classList.contains('wrap-button')) {
        const codeBlock = button.closest('.code-block');
        if (!codeBlock) {
          return;
        }
        codeBlock.classList.toggle('is-wrapped');
        const wrapped = codeBlock.classList.contains('is-wrapped');
        button.setAttribute('aria-pressed', wrapped ? 'true' : 'false');
        button.setAttribute(
          'title',
          wrapped
            ? button.getAttribute('data-label-active') ?? '줄바꿈 해제'
            : button.getAttribute('data-label-default') ?? '줄바꿈',
        );
        button.setAttribute(
          'aria-label',
          wrapped
            ? button.getAttribute('data-label-active') ?? '줄바꿈 해제'
            : button.getAttribute('data-label-default') ?? '줄바꿈',
        );
        return;
      }
      if (button.classList.contains('collapse-button')) {
        const codeBlock = button.closest('.code-block');
        if (!codeBlock) {
          return;
        }
        codeBlock.classList.toggle('is-collapsed');
        const collapsed = codeBlock.classList.contains('is-collapsed');
        button.classList.toggle('is-collapsed', collapsed);
        button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        button.textContent = collapsed
          ? button.getAttribute('data-label-collapsed') ?? 'Show more'
          : button.getAttribute('data-label-expanded') ?? 'Show less';
      }
    };

    root.addEventListener('click', handleClick);
    return () => {
      cleanupSectionTracking();
      wrapperRef.current = null;
      root.removeEventListener('click', handleClick);
    };
  }, [surfaceVariant, viewerDocument.bodyClassName, viewerDocument.html, inlineStylesKey]);

  useEffect(() => {
    const host = hostRef.current;
    const root = shadowRootRef.current;
    if (!host || !root || !currentViewerPath || !currentViewerPath.includes('#')) {
      return;
    }
    const targetId = currentViewerPath.split('#').slice(1).join('#');
    const targetNode = findShadowTarget(root, targetId);
    if (!targetNode) {
      return;
    }
    requestAnimationFrame(() => {
      scrollShadowTargetIntoView(host, targetNode);
    });
  }, [currentViewerPath, viewerDocument.html]);

  useEffect(() => {
    if (!onActiveSectionChange) {
      return;
    }
    const host = hostRef.current;
    const wrapper = wrapperRef.current;
    if (!host || !wrapper) {
      onActiveSectionChange(null);
      return;
    }
    const sections = findSectionNodes(wrapper);
    if (sections.length === 0) {
      onActiveSectionChange(null);
      return;
    }
    const scrollContainer = findScrollContainer(host);
    onActiveSectionChange(sectionDescriptor(pickActiveSection(sections, scrollContainer)));
  }, [currentViewerPath, onActiveSectionChange, viewerDocument.html]);

  useEffect(() => {
    setEditorDraft(null);
  }, [currentViewerPath, textToolEnabled, viewerDocument.html]);

  useEffect(() => {
    if (!editorDraft) {
      return;
    }
    const frameId = window.requestAnimationFrame(() => {
      editorTextareaRef.current?.focus();
      editorTextareaRef.current?.setSelectionRange(
        editorTextareaRef.current.value.length,
        editorTextareaRef.current.value.length,
      );
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [editorDraft]);

  useEffect(() => {
    if (!activeTextStyle) {
      return;
    }
    setEditorDraft((current) => (
      current
        ? { ...current, style: normalizeEditedTextStyle(activeTextStyle) }
        : current
    ));
  }, [activeTextStyle]);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    const root = shadowRootRef.current;
    if (!wrapper || !root) {
      return;
    }

    const cleanupAnnotations = (): void => {
      wrapper.querySelectorAll('.viewer-section-annotation-layer').forEach((node) => node.remove());
      wrapper.querySelectorAll('.viewer-inline-text-patch').forEach((node) => node.remove());
      wrapper.querySelectorAll('.viewer-inline-source-block-hidden').forEach((node) => {
        node.classList.remove('viewer-inline-source-block-hidden');
      });
    };

    cleanupAnnotations();

    Object.entries(textAnnotationsByAnchor ?? {}).forEach(([anchor, annotations]) => {
      const sectionTarget = findShadowTarget(root, anchor);
      const section = sectionTarget?.matches('section.section-card[id], section.embedded-section[id]')
        ? sectionTarget
        : findSectionFromNode(sectionTarget ?? null);
      if (!section) {
        return;
      }
      section.classList.add('viewer-annotated-section');

      const addAnnotations = annotations.filter((item) => item.kind === 'add');
      if (addAnnotations.length > 0) {
        const layer = document.createElement('div');
        layer.className = 'viewer-section-annotation-layer';
        addAnnotations.forEach((annotation) => {
          const note = document.createElement('button');
          note.type = 'button';
          note.className = 'viewer-floating-text-annotation';
          note.dataset.annotationId = annotation.annotation_id;
          note.dataset.annotationKind = annotation.kind;
          note.dataset.annotationAnchor = annotation.anchor;
          note.dataset.annotationX = String(annotation.x_ratio ?? 0.08);
          note.dataset.annotationY = String(annotation.y_ratio ?? 0.12);
          note.style.setProperty('--annotation-x', String(clampAnnotationRatio(Number(annotation.x_ratio ?? 0.08), 0.08)));
          note.style.setProperty('--annotation-y', String(clampAnnotationRatio(Number(annotation.y_ratio ?? 0.12), 0.12)));
          applyAnnotationTextStyle(note, annotation.style);

          const kicker = document.createElement('span');
          kicker.className = 'viewer-text-annotation-kicker';
          kicker.textContent = '추가 텍스트';

          const body = document.createElement('span');
          body.className = 'viewer-text-annotation-body';
          body.textContent = annotation.text;

          note.append(kicker, body);
          layer.appendChild(note);
        });
        section.appendChild(layer);
      }

      annotations
        .filter((item) => item.kind === 'edit')
        .forEach((annotation) => {
          const sourceBlock = elementFromSectionPath(section, annotation.block_path || '');
          if (!sourceBlock) {
            return;
          }
          sourceBlock.classList.add('viewer-inline-source-block-hidden');

          const patch = document.createElement('button');
          patch.type = 'button';
          patch.className = 'viewer-inline-text-patch';
          patch.dataset.annotationId = annotation.annotation_id;
          patch.dataset.annotationKind = annotation.kind;
          patch.dataset.annotationAnchor = annotation.anchor;
          patch.dataset.blockPath = annotation.block_path || '';
          applyAnnotationTextStyle(patch, annotation.style);

          const kicker = document.createElement('span');
          kicker.className = 'viewer-text-annotation-kicker';
          kicker.textContent = '수정 텍스트';

          const body = document.createElement('span');
          body.className = 'viewer-text-annotation-body';
          body.textContent = annotation.text;

          patch.append(kicker, body);
          sourceBlock.insertAdjacentElement('afterend', patch);
        });
    });

    return cleanupAnnotations;
  }, [currentViewerPath, textAnnotationsByAnchor, viewerDocument.html]);

  useEffect(() => {
    if (!editorDraft) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setEditorDraft(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [editorDraft]);

  return (
    <div className="viewer-document-stage-shell" ref={shellRef}>
      <div className={className} ref={hostRef} />
      {editorDraft && (
        <div
          ref={editorRef}
          className="viewer-text-editor-popover"
          style={{ left: `${editorDraft.left}px`, top: `${editorDraft.top}px` }}
        >
          <div className="viewer-text-editor-kicker">
            {editorDraft.kind === 'edit' ? '텍스트 수정' : '텍스트 추가'}
          </div>
          <div className="viewer-text-editor-title">{editorDraft.title}</div>
          <textarea
            ref={editorTextareaRef}
            className="viewer-text-editor-input"
            value={editorDraft.text}
            onChange={(event) => {
              const nextValue = event.target.value;
              setEditorDraft((current) => (
                current
                  ? { ...current, text: nextValue }
                  : current
              ));
            }}
            placeholder={editorDraft.kind === 'edit' ? '이 문단의 수정본을 적어두세요.' : '본문 위에 올릴 텍스트를 적어두세요.'}
          />
          <div className="viewer-text-editor-actions">
            <button
              type="button"
              className="viewer-text-editor-btn"
              onClick={() => setEditorDraft(null)}
            >
              취소
            </button>
            <button
              type="button"
              className="viewer-text-editor-btn viewer-text-editor-btn-danger"
              onClick={() => {
                latestRemoveTextAnnotationRef.current?.(
                  { anchor: editorDraft.anchor, title: editorDraft.title },
                  editorDraft.annotationId,
                );
                setEditorDraft(null);
              }}
            >
              삭제
            </button>
            <button
              type="button"
              className="viewer-text-editor-btn viewer-text-editor-btn-primary"
              onClick={() => {
                const text = editorDraft.text.trim();
                if (!text) {
                  latestRemoveTextAnnotationRef.current?.(
                    { anchor: editorDraft.anchor, title: editorDraft.title },
                    editorDraft.annotationId,
                  );
                  setEditorDraft(null);
                  return;
                }
                latestSaveTextAnnotationRef.current?.(
                  { anchor: editorDraft.anchor, title: editorDraft.title },
                  {
                    annotation_id: editorDraft.annotationId,
                    kind: editorDraft.kind,
                    anchor: editorDraft.anchor,
                    text,
                    style: normalizeEditedTextStyle(editorDraft.style),
                    x_ratio: editorDraft.xRatio,
                    y_ratio: editorDraft.yRatio,
                    block_path: editorDraft.blockPath,
                  },
                );
                setEditorDraft(null);
              }}
            >
              저장
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
