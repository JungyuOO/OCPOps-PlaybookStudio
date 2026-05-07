import type { ViewerDocumentPayload } from '../components/ViewerDocumentStage';
import type {
  CustomerPackBook,
  CustomerPackDraft,
  SourceMetaResponse,
  ViewerPageMode,
  WikiEditedTextStyle,
  WikiInkColorId,
  WikiOverlayRecord,
  WikiOverlayTargetKind,
  WikiTextAnnotation,
} from '../lib/runtimeApi';
import { loadViewerDocument, normalizeViewerPath } from '../lib/runtimeApi';
import type { WorkspaceManualBook } from './workspaceTypes';

export interface OverlayTargetDescriptor {
  kind: WikiOverlayTargetKind;
  ref: string;
  title: string;
  viewerPath: string;
  payload: Record<string, unknown>;
}

export interface ViewerActiveSection {
  anchor: string;
  title: string;
}

export interface OutlineTocNode {
  id: string;
  heading: string;
  depth: number;
  viewerPath: string;
  sectionPathLabel: string;
}

export type PreviewState =
  | { kind: 'empty' }
  | { kind: 'loading'; title: string }
  | {
    kind: 'viewer';
    title: string;
    subtitle: string;
    meta?: SourceMetaResponse;
    viewerUrl: string;
    viewerDocument?: ViewerDocumentPayload;
  }
  | {
    kind: 'draft';
    title: string;
    subtitle: string;
    draft: CustomerPackDraft;
    book?: CustomerPackBook;
    viewerUrl: string;
    derivedAssets: CustomerPackDraft['derived_assets'];
    viewerDocument?: ViewerDocumentPayload;
  };

export type LlmWikiBookInteractionMode = 'reader' | 'studio';

export const WIKI_OVERLAY_USER_ID = 'kugnus@cywell.co.kr';
export const DEFAULT_EDITED_TEXT_STYLE: WikiEditedTextStyle = {
  tone: 'amber',
  size: 'md',
  weight: 'regular',
};

export function formatBytes(value?: number): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return '';
  }
  if (numeric < 1024) {
    return `${numeric} B`;
  }
  if (numeric < 1024 * 1024) {
    return `${(numeric / 1024).toFixed(1)} KB`;
  }
  return `${(numeric / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDraftMeta(draft: CustomerPackDraft): string {
  const size = formatBytes(draft.uploaded_byte_size);
  return [draft.status, draft.source_type.toUpperCase(), size].filter(Boolean).join(' · ');
}

export function summarizeBookMeta(book: WorkspaceManualBook): string {
  const parts = [
    book.library_group_label,
    book.family_label,
    book.source_type,
    Number.isFinite(book.section_count) && book.section_count > 0 ? `${book.section_count} sections` : '',
  ].filter(Boolean);
  return parts.join(' · ');
}

export function truthSurfaceCopy(payload?: {
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  source_lane?: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  pack_label?: string;
} | null): {
  label: string;
  meta: string[];
} {
  if (!payload) {
    return { label: '', meta: [] };
  }
  const boundaryTruth = String(payload.boundary_truth || '').trim();
  const sourceLane = String(payload.source_lane || '').trim();
  const runtimeTruthLabel = String(payload.runtime_truth_label || '').trim();
  const packLabel = String(payload.pack_label || '').trim();

  if (boundaryTruth === 'private_customer_pack_runtime' || sourceLane === 'customer_source_first_pack') {
    return {
      label: 'Private Runtime',
      meta: [
        runtimeTruthLabel || 'Customer Source-First Pack',
        payload.approval_state ? `approval ${payload.approval_state}` : '',
        payload.publication_state ? `publication ${payload.publication_state}` : '',
        payload.parser_backend ? `parser ${payload.parser_backend}` : '',
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'official_gold_playbook_runtime') {
    return {
      label: 'Gold Playbook',
      meta: [
        runtimeTruthLabel || (packLabel ? `${packLabel} Gold Playbook` : 'Gold Playbook'),
        packLabel || '',
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'official_validated_runtime') {
    return {
      label: 'Validated Runtime',
      meta: [
        runtimeTruthLabel || (packLabel ? `${packLabel} Runtime` : 'Validated Pack Runtime'),
        packLabel || '',
      ].filter(Boolean),
    };
  }

  return {
    label: payload.boundary_badge || runtimeTruthLabel || sourceLane || '',
    meta: [
      payload.approval_state ? `approval ${payload.approval_state}` : '',
      payload.publication_state ? `publication ${payload.publication_state}` : '',
      payload.parser_backend ? `parser ${payload.parser_backend}` : '',
    ].filter(Boolean),
  };
}

export function normalizeEditedTextStyle(value?: Partial<WikiEditedTextStyle> | null): WikiEditedTextStyle {
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
        : DEFAULT_EDITED_TEXT_STYLE.tone,
    size: size === 'sm' || size === 'lg' || size === 'md' ? size : DEFAULT_EDITED_TEXT_STYLE.size,
    weight: weight === 'strong' || weight === 'regular' ? weight : DEFAULT_EDITED_TEXT_STYLE.weight,
  };
}

export function normalizeAnnotationRatio(value: unknown, fallback: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(0, Math.min(1, numeric));
}

export function createTextAnnotationId(): string {
  if (typeof globalThis !== 'undefined' && 'crypto' in globalThis && typeof globalThis.crypto?.randomUUID === 'function') {
    return `ant-${globalThis.crypto.randomUUID().slice(0, 8)}`;
  }
  return `ant-${Math.random().toString(36).slice(2, 10)}`;
}

export function overlayAnchorFromTargetRef(targetRef: string): string {
  const normalized = String(targetRef || '').trim();
  if (!normalized.startsWith('section:') || !normalized.includes('#')) {
    return '';
  }
  return normalized.split('#').slice(1).join('#').trim();
}

export function annotationColorIdToTone(colorId: WikiInkColorId): WikiEditedTextStyle['tone'] {
  const normalized = String(colorId || '').trim().toLowerCase();
  if (
    normalized === 'amber'
    || normalized === 'ink'
    || normalized === 'teal'
    || normalized === 'cyan'
    || normalized === 'rose'
    || normalized === 'violet'
    || normalized === 'lime'
  ) {
    return normalized;
  }
  return DEFAULT_EDITED_TEXT_STYLE.tone;
}

export function normalizeTextAnnotation(
  value: Partial<WikiTextAnnotation> | null | undefined,
  fallbackAnchor: string,
): WikiTextAnnotation | null {
  const kind = String(value?.kind || '').trim().toLowerCase();
  if (kind !== 'add' && kind !== 'edit') {
    return null;
  }
  const text = String(value?.text || '').trim();
  if (!text) {
    return null;
  }
  const anchor = String(value?.anchor || fallbackAnchor || '').trim();
  if (!anchor) {
    return null;
  }
  const annotationId = String(value?.annotation_id || '').trim() || createTextAnnotationId();
  const blockPath = String(value?.block_path || '').trim();
  if (kind === 'edit' && !blockPath) {
    return null;
  }
  return {
    annotation_id: annotationId,
    kind,
    anchor,
    text,
    style: normalizeEditedTextStyle(value?.style),
    x_ratio: normalizeAnnotationRatio(value?.x_ratio, 0.08),
    y_ratio: normalizeAnnotationRatio(value?.y_ratio, 0.12),
    block_path: blockPath,
  };
}

export function extractTextAnnotations(
  value?: Pick<WikiOverlayRecord, 'text_annotations' | 'payload' | 'body' | 'text_style' | 'target_ref'> | null,
  fallbackAnchor = '',
): WikiTextAnnotation[] {
  if (!value) {
    return [];
  }
  const anchor = String(fallbackAnchor || overlayAnchorFromTargetRef(value.target_ref || '')).trim();
  const payload = value.payload && typeof value.payload === 'object'
    ? value.payload as Record<string, unknown>
    : {};
  const rawAnnotations = Array.isArray(value.text_annotations)
    ? value.text_annotations
    : Array.isArray(payload.text_annotations)
      ? payload.text_annotations as Partial<WikiTextAnnotation>[]
      : [];
  const normalized = rawAnnotations
    .map((item) => normalizeTextAnnotation(item, anchor))
    .filter((item): item is WikiTextAnnotation => Boolean(item));
  if (normalized.length > 0) {
    return normalized;
  }
  const legacyBody = String(value.body || '').trim();
  if (!legacyBody || !anchor) {
    return [];
  }
  return [
    {
      annotation_id: `legacy-${anchor}`,
      kind: 'add',
      anchor,
      text: legacyBody,
      style: normalizeEditedTextStyle(value.text_style),
      x_ratio: 0.08,
      y_ratio: 0.12,
      block_path: '',
    },
  ];
}

export function extractDraftIdFromViewerPath(viewerPath: string): string | null {
  const match = viewerPath.match(/\/playbooks\/customer-packs\/([^/]+)/);
  return match?.[1] ?? null;
}

export function runtimePathFromUrl(viewerUrl: string): string {
  try {
    const parsed = new URL(viewerUrl, window.location.origin);
    return normalizeViewerPath(`${parsed.pathname}${parsed.search || ''}${parsed.hash || ''}`);
  } catch {
    return normalizeViewerPath(viewerUrl);
  }
}

export function normalizeViewerDocumentPayload(
  viewerDocument: Awaited<ReturnType<typeof loadViewerDocument>>,
): ViewerDocumentPayload {
  return {
    html: viewerDocument.html,
    inlineStyles: viewerDocument.inline_styles,
    bodyClassName: viewerDocument.body_class_name,
    interactionPolicy: {
      codeCopy: viewerDocument.interaction_policy.code_copy,
      codeWrapToggle: viewerDocument.interaction_policy.code_wrap_toggle,
      recentPositionTracking: viewerDocument.interaction_policy.recent_position_tracking,
      anchorNavigation: viewerDocument.interaction_policy.anchor_navigation,
    },
  };
}

export function parseViewerHtml(viewerHtml: string): Document | null {
  if (typeof DOMParser === 'undefined') {
    return null;
  }
  try {
    return new DOMParser().parseFromString(viewerHtml, 'text/html');
  } catch {
    return null;
  }
}

export function extractViewerQuickNavItems(viewerHtml: string, viewerPath: string): OutlineTocNode[] {
  const documentRoot = parseViewerHtml(viewerHtml);
  if (!documentRoot) {
    return [];
  }
  const baseViewerPath = normalizeViewerPath(viewerPath.split('#', 1)[0] || viewerPath);
  const nodes: OutlineTocNode[] = [];
  const seen = new Set<string>();

  documentRoot.querySelectorAll('.document-nav-link[href]').forEach((node) => {
    if (!(node instanceof HTMLAnchorElement)) {
      return;
    }
    const rawHref = String(node.getAttribute('href') || '').trim();
    const label = node.textContent?.trim() || '';
    if (!rawHref || !label) {
      return;
    }
    const anchor = rawHref.startsWith('#') ? rawHref.slice(1) : rawHref.split('#', 2)[1] || '';
    if (!anchor || seen.has(anchor)) {
      return;
    }
    seen.add(anchor);
    nodes.push({
      id: anchor,
      heading: label,
      depth: 1,
      viewerPath: rawHref.startsWith('#') ? `${baseViewerPath}#${anchor}` : normalizeViewerPath(rawHref),
      sectionPathLabel: String(node.getAttribute('title') || label).trim(),
    });
  });

  if (nodes.length > 0) {
    return nodes;
  }

  documentRoot.querySelectorAll('section.section-card[id], section.embedded-section[id]').forEach((node) => {
    if (!(node instanceof HTMLElement)) {
      return;
    }
    const anchor = String(node.id || '').trim();
    const heading = node.querySelector('h2')?.textContent?.trim() || node.querySelector('.section-meta')?.textContent?.trim() || anchor;
    const sectionPathLabel = node.querySelector('.section-meta')?.textContent?.trim() || heading;
    if (!anchor || !heading || seen.has(anchor)) {
      return;
    }
    seen.add(anchor);
    nodes.push({
      id: anchor,
      heading,
      depth: 1,
      viewerPath: `${baseViewerPath}#${anchor}`,
      sectionPathLabel,
    });
  });

  return nodes;
}

export async function loadViewerDocumentPayload(viewerPath: string, pageMode: ViewerPageMode): Promise<ViewerDocumentPayload> {
  return normalizeViewerDocumentPayload(await loadViewerDocument(viewerPath, pageMode));
}

export function normalizePreviewNavigationTarget(viewerPath: string): string | null {
  const raw = String(viewerPath || '').trim();
  if (!raw) {
    return null;
  }
  try {
    const parsed = new URL(raw, window.location.origin);
    const runtimePath = `${parsed.pathname}${parsed.search || ''}${parsed.hash || ''}`;
    if (
      parsed.pathname.startsWith('/playbooks/')
      || parsed.pathname.startsWith('/docs/ocp/')
      || parsed.pathname.startsWith('/wiki/entities/')
      || parsed.pathname.startsWith('/wiki/figures/')
      || parsed.pathname.startsWith('/api/customer-packs/captured')
    ) {
      return normalizeViewerPath(runtimePath);
    }
    if (/^https?:\/\//i.test(raw)) {
      window.open(raw, '_blank', 'noopener,noreferrer');
      return null;
    }
    return normalizeViewerPath(runtimePath);
  } catch {
    return normalizeViewerPath(raw);
  }
}

export function buildOverlayTargetFromViewerPath(viewerUrl: string, fallbackTitle: string): OverlayTargetDescriptor | null {
  const runtimePath = runtimePathFromUrl(viewerUrl);
  const [pathWithQuery, anchorPart] = runtimePath.split('#', 2);
  const [pathOnly, searchPart] = pathWithQuery.split('?', 2);
  const searchParams = new URLSearchParams(searchPart ?? '');
  const anchor = anchorPart?.trim() ?? '';

  const entityMatch = pathOnly.match(/^\/wiki\/entities\/([^/]+)\/index\.html$/);
  if (entityMatch) {
    const entitySlug = entityMatch[1];
    return {
      kind: 'entity_hub',
      ref: `entity:${entitySlug}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: WIKI_OVERLAY_USER_ID,
        target_kind: 'entity_hub',
        entity_slug: entitySlug,
        viewer_path: runtimePath,
      },
    };
  }

  const figureMatch = pathOnly.match(/^\/wiki\/figures\/([^/]+)\/([^/]+)\/index\.html$/);
  if (figureMatch) {
    const [, bookSlug, assetName] = figureMatch;
    return {
      kind: 'figure',
      ref: `figure:${bookSlug}:${assetName}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: WIKI_OVERLAY_USER_ID,
        target_kind: 'figure',
        book_slug: bookSlug,
        asset_name: assetName,
        viewer_path: runtimePath,
      },
    };
  }

  const runtimeBookMatch = pathOnly.match(/^\/playbooks\/wiki-runtime\/active\/([^/]+)\/index\.html$/);
  const officialBookMatch = pathOnly.match(/^\/docs\/ocp\/[^/]+\/[^/]+\/([^/]+)\/index\.html$/);
  const customerPackMatch = pathOnly.match(/^\/playbooks\/customer-packs\/([^/]+)\/index\.html$/);
  const capturedDraftId = pathOnly === '/api/customer-packs/captured'
    ? String(searchParams.get('draft_id') || '').trim()
    : '';
  const bookSlug = runtimeBookMatch?.[1] ?? officialBookMatch?.[1] ?? customerPackMatch?.[1] ?? capturedDraftId;
  if (bookSlug) {
    if (anchor) {
      return {
        kind: 'section',
        ref: `section:${bookSlug}#${anchor}`,
        title: fallbackTitle,
        viewerPath: runtimePath,
        payload: {
          user_id: WIKI_OVERLAY_USER_ID,
          target_kind: 'section',
          book_slug: bookSlug,
          anchor,
          viewer_path: runtimePath,
        },
      };
    }
    return {
      kind: 'book',
      ref: `book:${bookSlug}`,
      title: fallbackTitle,
      viewerPath: runtimePath,
      payload: {
        user_id: WIKI_OVERLAY_USER_ID,
        target_kind: 'book',
        book_slug: bookSlug,
        viewer_path: runtimePath,
      },
    };
  }

  return null;
}
