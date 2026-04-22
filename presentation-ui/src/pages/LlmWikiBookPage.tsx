import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  Highlighter,
  PanelLeftClose,
  PanelRightClose,
  PenTool,
  StickyNote,
  Type,
} from 'lucide-react';
import { ROUTES, buildSharedLandingHref } from '../app/routes';
import type {
  CustomerPackDraft,
  ViewerPageMode,
  WikiAnnotationTool,
  WikiEditedTextStyle,
  WikiInkColorId,
  WikiInkStroke,
  WikiInkStyle,
  WikiOverlayRecord,
  WikiTextAnnotation,
  WikiTextAnnotationMode,
} from '../lib/runtimeApi';
import {
  listCustomerPackDrafts,
  loadCustomerPackBook,
  loadCustomerPackDraft,
  loadDataControlRoom,
  loadSourceMeta,
  loadWikiOverlays,
  removeWikiOverlay,
  saveWikiOverlay,
  toRuntimeUrl,
} from '../lib/runtimeApi';
import { resolveWorkspaceSourceBooks } from '../lib/workspaceSourceCatalog';
import type { SourceEntry, WorkspaceManualBook } from './workspaceTypes';
import { buildOutlineBookFamilies, describeOutlineVariant, type OutlineBookFamily } from './workspaceOutline';
import {
  LlmWikiBookLeftRail,
  LlmWikiBookNavList,
  LlmWikiBookReadingStage,
  LlmWikiBookReaderPane,
  LlmWikiBookRightRail,
  LlmWikiBookSectionCard,
  LlmWikiBookShell,
  LlmWikiBookSidecar,
  LlmWikiBookTopBar,
} from './llmwikibook';
import type { LlmWikiBookNavItem } from './llmwikibook';
import {
  type OverlayTargetDescriptor,
  type PreviewState,
  type LlmWikiBookInteractionMode,
  type ViewerActiveSection,
  WIKI_OVERLAY_USER_ID,
  annotationColorIdToTone,
  buildOverlayTargetFromViewerPath,
  extractDraftIdFromViewerPath,
  extractTextAnnotations,
  extractViewerQuickNavItems,
  formatDraftMeta,
  loadViewerDocumentPayload,
  normalizeEditedTextStyle,
  normalizePreviewNavigationTarget,
  normalizeTextAnnotation,
  overlayAnchorFromTargetRef,
  runtimePathFromUrl,
  summarizeBookMeta,
  truthSurfaceCopy,
} from './llmWikiBookSupport';

const LLMWIKIBOOK_INK_STYLES: WikiInkStyle[] = [
  {
    id: 'cyan',
    label: 'Cyan',
    penColor: 'rgba(14, 165, 233, 0.96)',
    highlighterColor: 'rgba(34, 211, 238, 0.28)',
  },
  {
    id: 'amber',
    label: 'Amber',
    penColor: 'rgba(217, 119, 6, 0.96)',
    highlighterColor: 'rgba(250, 204, 21, 0.32)',
  },
  {
    id: 'rose',
    label: 'Rose',
    penColor: 'rgba(225, 29, 72, 0.96)',
    highlighterColor: 'rgba(251, 113, 133, 0.28)',
  },
  {
    id: 'violet',
    label: 'Violet',
    penColor: 'rgba(124, 58, 237, 0.96)',
    highlighterColor: 'rgba(167, 139, 250, 0.28)',
  },
  {
    id: 'lime',
    label: 'Lime',
    penColor: 'rgba(77, 124, 15, 0.96)',
    highlighterColor: 'rgba(163, 230, 53, 0.3)',
  },
];

export default function LlmWikiBookPage() {
  const autoOpenedRef = useRef(false);

  const [manualBooks, setManualBooks] = useState<WorkspaceManualBook[]>([]);
  const [drafts, setDrafts] = useState<CustomerPackDraft[]>([]);
  const [preview, setPreview] = useState<PreviewState>({ kind: 'empty' });
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [viewerActiveSection, setViewerActiveSection] = useState<ViewerActiveSection | null>(null);
  const [viewerPageMode, setViewerPageMode] = useState<ViewerPageMode>('single');
  const [isBootstrapLoading, setIsBootstrapLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState('');
  const [wikiOverlays, setWikiOverlays] = useState<WikiOverlayRecord[]>([]);
  const [isOverlayLoading, setIsOverlayLoading] = useState(false);
  const [isOverlaySaving, setIsOverlaySaving] = useState(false);
  const [noteDraft, setNoteDraft] = useState('');
  const [interactionMode, setInteractionMode] = useState<LlmWikiBookInteractionMode>('reader');
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightRailCollapsed, setRightRailCollapsed] = useState(false);
  const [annotationEnabled, setAnnotationEnabled] = useState(false);
  const [annotationTool, setAnnotationTool] = useState<WikiAnnotationTool>('text');
  const [annotationColorId, setAnnotationColorId] = useState<WikiInkColorId>('amber');
  const [annotationTextMode, setAnnotationTextMode] = useState<WikiTextAnnotationMode>('add');
  const [annotationTextStyle, setAnnotationTextStyle] = useState<WikiEditedTextStyle>({
    tone: 'amber',
    size: 'md',
    weight: 'regular',
  });

  const refreshWikiOverlays = useCallback(async () => {
    setIsOverlayLoading(true);
    try {
      const overlayResult = await loadWikiOverlays(WIKI_OVERLAY_USER_ID);
      setWikiOverlays(overlayResult.items ?? []);
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlayLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap(): Promise<void> {
      setIsBootstrapLoading(true);
      setBootstrapError('');
      try {
        const [room, draftList, overlayResult] = await Promise.all([
          loadDataControlRoom(),
          listCustomerPackDrafts(),
          loadWikiOverlays(WIKI_OVERLAY_USER_ID),
        ]);
        if (cancelled) {
          return;
        }
        setManualBooks(resolveWorkspaceSourceBooks(room));
        setDrafts(draftList.drafts ?? []);
        setWikiOverlays(overlayResult.items ?? []);
      } catch (error) {
        console.error(error);
        if (!cancelled) {
          setBootstrapError(error instanceof Error ? error.message : 'llmwikibook bootstrap failed');
        }
      } finally {
        if (!cancelled) {
          setIsBootstrapLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const manualSources = useMemo<SourceEntry[]>(() => (
    manualBooks.map((book) => ({
      id: `manual:${book.book_slug}`,
      kind: 'manual',
      name: book.title,
      meta: summarizeBookMeta(book),
      grade: book.grade,
      viewerPath: book.viewer_path,
      book,
    }))
  ), [manualBooks]);

  const draftSources = useMemo<SourceEntry[]>(() => (
    drafts.map((draft) => ({
      id: `draft:${draft.draft_id}`,
      kind: 'draft',
      name: draft.title,
      meta: formatDraftMeta(draft),
      grade: draft.quality_status,
      viewerPath: draft.derived_assets?.[0]?.viewer_path || '',
      draft,
    }))
  ), [drafts]);

  const outlineFamilies = useMemo<OutlineBookFamily[]>(
    () => buildOutlineBookFamilies(manualBooks),
    [manualBooks],
  );

  const activeDraft = useMemo(
    () => (preview.kind === 'draft' ? preview.draft : null),
    [preview],
  );

  const noteOverlays = useMemo(
    () => wikiOverlays.filter((overlay) => overlay.kind === 'note'),
    [wikiOverlays],
  );
  const inkOverlays = useMemo(
    () => wikiOverlays.filter((overlay) => overlay.kind === 'ink'),
    [wikiOverlays],
  );
  const editedCardOverlays = useMemo(
    () => wikiOverlays.filter((overlay) => overlay.kind === 'edited_card'),
    [wikiOverlays],
  );

  const noteOverlayByTarget = useMemo(
    () => new Map(noteOverlays.map((overlay) => [overlay.target_ref, overlay])),
    [noteOverlays],
  );
  const inkOverlayByTarget = useMemo(
    () => new Map(inkOverlays.map((overlay) => [overlay.target_ref, overlay])),
    [inkOverlays],
  );
  const editedCardOverlayByTarget = useMemo(
    () => new Map(editedCardOverlays.map((overlay) => [overlay.target_ref, overlay])),
    [editedCardOverlays],
  );

  const currentViewerPath = useMemo(() => {
    if (preview.kind === 'viewer' || preview.kind === 'draft') {
      return runtimePathFromUrl(preview.viewerUrl);
    }
    return '';
  }, [preview]);

  const quickNavItems = useMemo(
    () => ((preview.kind === 'viewer' || preview.kind === 'draft') && preview.viewerDocument
      ? extractViewerQuickNavItems(preview.viewerDocument.html, currentViewerPath)
      : []),
    [currentViewerPath, preview],
  );

  const currentOverlayTarget = useMemo<OverlayTargetDescriptor | null>(() => {
    if (viewerActiveSection && currentViewerPath) {
      return buildOverlayTargetFromViewerPath(`${currentViewerPath.split('#', 1)[0]}#${viewerActiveSection.anchor}`, viewerActiveSection.title);
    }
    if (currentViewerPath && (preview.kind === 'viewer' || preview.kind === 'draft')) {
      return buildOverlayTargetFromViewerPath(currentViewerPath, preview.title);
    }
    return null;
  }, [currentViewerPath, preview, viewerActiveSection]);

  const currentPreviewBookSlug = useMemo(() => {
    const runtimeTarget = currentOverlayTarget?.ref ?? '';
    const runtimeMatch = runtimeTarget.match(/^(?:book|section):([^#]+)(?:#.*)?$/);
    return runtimeMatch?.[1] ?? '';
  }, [currentOverlayTarget]);

  const sectionTextAnnotationsByAnchor = useMemo<Record<string, WikiTextAnnotation[]>>(() => {
    const annotationMap = new Map<string, WikiTextAnnotation[]>();
    editedCardOverlays.forEach((overlay) => {
      const anchor = overlayAnchorFromTargetRef(overlay.target_ref);
      if (!anchor) {
        return;
      }
      const existing = annotationMap.get(anchor) ?? [];
      annotationMap.set(anchor, [
        ...existing,
        ...extractTextAnnotations(overlay, anchor),
      ]);
    });
    return Object.fromEntries(annotationMap.entries());
  }, [editedCardOverlays]);

  const currentNote = useMemo(
    () => (currentOverlayTarget ? noteOverlayByTarget.get(currentOverlayTarget.ref) ?? null : null),
    [currentOverlayTarget, noteOverlayByTarget],
  );
  const currentLegacyInk = useMemo(
    () => (currentOverlayTarget ? inkOverlayByTarget.get(currentOverlayTarget.ref) ?? null : null),
    [currentOverlayTarget, inkOverlayByTarget],
  );
  const currentEditedCard = useMemo(
    () => (currentOverlayTarget ? editedCardOverlayByTarget.get(currentOverlayTarget.ref) ?? null : null),
    [currentOverlayTarget, editedCardOverlayByTarget],
  );

  const currentInkStrokes = useMemo<WikiInkStroke[]>(
    () => currentEditedCard?.strokes ?? currentLegacyInk?.strokes ?? [],
    [currentEditedCard?.strokes, currentLegacyInk?.strokes],
  );

  const currentTruthSurface = useMemo(
    () => truthSurfaceCopy(preview.kind === 'draft' ? preview.book ?? preview.draft : preview.kind === 'viewer' ? preview.meta : null),
    [preview],
  );

  const currentManualBook = useMemo(() => {
    if (!currentPreviewBookSlug) {
      return null;
    }
    return manualBooks.find((book) => book.book_slug === currentPreviewBookSlug) ?? null;
  }, [currentPreviewBookSlug, manualBooks]);

  const currentFamilyVariants = useMemo(() => {
    if (!currentManualBook) {
      return [];
    }
    const family = outlineFamilies.find((entry) => (
      entry.primary.book_slug === currentManualBook.book_slug
      || entry.variants.some((book) => book.book_slug === currentManualBook.book_slug)
    ));
    if (!family) {
      return [];
    }
    return [family.primary, ...family.variants].filter((book) => book.book_slug !== currentManualBook.book_slug);
  }, [currentManualBook, outlineFamilies]);

  const currentSectionAnnotationCount = useMemo(() => {
    if (!currentOverlayTarget) {
      return 0;
    }
    const anchor = overlayAnchorFromTargetRef(currentOverlayTarget.ref);
    if (!anchor) {
      return 0;
    }
    return sectionTextAnnotationsByAnchor[anchor]?.length ?? 0;
  }, [currentOverlayTarget, sectionTextAnnotationsByAnchor]);

  const activeInkStyle = useMemo(
    () => LLMWIKIBOOK_INK_STYLES.find((style) => style.id === annotationColorId) ?? LLMWIKIBOOK_INK_STYLES[0],
    [annotationColorId],
  );

  useEffect(() => {
    setNoteDraft(String(currentNote?.body || ''));
  }, [currentNote?.body, currentNote?.overlay_id]);

  useEffect(() => {
    if (!currentOverlayTarget) {
      return;
    }
    if (currentOverlayTarget.kind === 'entity_hub' || currentOverlayTarget.kind === 'book' || currentOverlayTarget.kind === 'section' || currentOverlayTarget.kind === 'figure') {
      const timer = window.setTimeout(() => {
        void saveWikiOverlay({
          user_id: WIKI_OVERLAY_USER_ID,
          kind: 'recent_position',
          ...currentOverlayTarget.payload,
        }).catch((error) => console.error(error));
      }, 500);
      return () => window.clearTimeout(timer);
    }
    return;
  }, [currentOverlayTarget]);

  useEffect(() => {
    if (autoOpenedRef.current || isBootstrapLoading || preview.kind !== 'empty') {
      return;
    }
    const firstManual = manualBooks[0];
    const firstDraft = drafts[0];
    if (!firstManual && !firstDraft) {
      return;
    }
    autoOpenedRef.current = true;
    if (firstManual) {
      void openViewerPreview(firstManual.viewer_path, firstManual.title, `manual:${firstManual.book_slug}`);
      return;
    }
    if (firstDraft) {
      void openDraftPreview(firstDraft.draft_id, drafts);
    }
  }, [drafts, isBootstrapLoading, manualBooks, preview.kind]);

  useEffect(() => {
    if (interactionMode === 'reader' && annotationEnabled) {
      setAnnotationEnabled(false);
    }
  }, [annotationEnabled, interactionMode]);

  function mergeDraft(nextDraft: CustomerPackDraft, currentDrafts: CustomerPackDraft[] = drafts): CustomerPackDraft[] {
    return [nextDraft, ...currentDrafts.filter((draft) => draft.draft_id !== nextDraft.draft_id)];
  }

  async function openViewerPreview(
    viewerPath: string,
    title: string,
    sourceId?: string,
    pageMode: ViewerPageMode = viewerPageMode,
  ): Promise<void> {
    const normalizedViewerPath = normalizePreviewNavigationTarget(viewerPath);
    if (!normalizedViewerPath) {
      setPreview({ kind: 'empty' });
      return;
    }
    setActiveSourceId(sourceId ?? `viewer:${normalizedViewerPath}`);
    setPreview({ kind: 'loading', title });
    try {
      const meta = await loadSourceMeta(normalizedViewerPath);
      const resolvedViewerPath = meta.viewer_path || normalizedViewerPath;
      const viewerUrl = toRuntimeUrl(resolvedViewerPath);
      const viewerDocument = await loadViewerDocumentPayload(resolvedViewerPath, pageMode);
      setPreview({
        kind: 'viewer',
        title: meta.book_title || title,
        subtitle: meta.section_path_label || meta.section || meta.source_url || '',
        meta,
        viewerUrl,
        viewerDocument,
      });
    } catch (error) {
      console.error('llmwikibook-viewer-preview-failed', {
        viewerPath: normalizedViewerPath,
        error,
      });
      setPreview({
        kind: 'viewer',
        title,
        subtitle: '',
        viewerUrl: toRuntimeUrl(normalizedViewerPath),
      });
    }
  }

  async function openDraftPreview(
    draftId: string,
    currentDrafts: CustomerPackDraft[] = drafts,
    preferredViewerPath = '',
    pageMode: ViewerPageMode = viewerPageMode,
  ): Promise<void> {
    setActiveSourceId(`draft:${draftId}`);
    setPreview({ kind: 'loading', title: 'Customer Pack' });

    const loadedDraft = await loadCustomerPackDraft(draftId);
    const mergedDrafts = mergeDraft(loadedDraft, currentDrafts);
    setDrafts(mergedDrafts);

    let loadedBook: Awaited<ReturnType<typeof loadCustomerPackBook>> | undefined;
    let viewerUrl = '';

    if (loadedDraft.status === 'normalized') {
      loadedBook = await loadCustomerPackBook(draftId);
      viewerUrl = toRuntimeUrl(preferredViewerPath || loadedBook.target_viewer_path);
    } else if (loadedDraft.capture_artifact_path) {
      viewerUrl = toRuntimeUrl(`/api/customer-packs/captured?draft_id=${encodeURIComponent(draftId)}`);
    }

    const viewerDocument = viewerUrl
      ? await loadViewerDocumentPayload(runtimePathFromUrl(viewerUrl), pageMode)
      : undefined;

    setPreview({
      kind: 'draft',
      title: loadedDraft.title,
      subtitle: `${loadedDraft.pack_label} · ${truthSurfaceCopy(loadedBook ?? loadedDraft).label} · ${loadedDraft.quality_status}`,
      draft: loadedDraft,
      book: loadedBook,
      viewerUrl,
      derivedAssets: loadedBook?.derived_assets ?? loadedDraft.derived_assets ?? [],
      viewerDocument,
    });
  }

  async function handleNavigateViewerPath(viewerPath: string): Promise<void> {
    const draftId = extractDraftIdFromViewerPath(viewerPath);
    if (draftId) {
      await openDraftPreview(draftId, drafts, viewerPath);
      return;
    }
    await openViewerPreview(viewerPath, preview.kind === 'empty' ? 'Playbook' : preview.title, activeSourceId ?? undefined);
  }

  async function handleSourceClick(source: SourceEntry): Promise<void> {
    try {
      if (source.kind === 'manual' && source.book) {
        await openViewerPreview(source.book.viewer_path, source.book.title, source.id);
      }
      if (source.kind === 'draft' && source.draft) {
        await openDraftPreview(source.draft.draft_id);
      }
    } catch (error) {
      console.error(error);
      window.alert(error instanceof Error ? error.message : '문서를 여는 중 오류가 발생했습니다.');
    }
  }

  function buildSectionOverlayTarget(anchor: string, title: string): OverlayTargetDescriptor | null {
    const normalizedAnchor = String(anchor || '').trim();
    if (!normalizedAnchor) {
      return null;
    }
    const baseViewerPath = currentViewerPath
      ? currentViewerPath.split('#', 1)[0]
      : preview.kind === 'viewer' || preview.kind === 'draft'
        ? runtimePathFromUrl(preview.viewerUrl).split('#', 1)[0]
        : '';
    if (!baseViewerPath) {
      return null;
    }
    return buildOverlayTargetFromViewerPath(`${baseViewerPath}#${normalizedAnchor}`, title);
  }

  async function cleanupLegacyEditOverlaysForTarget(targetRef: string): Promise<void> {
    const removals: Promise<unknown>[] = [];
    const legacyNote = noteOverlayByTarget.get(targetRef);
    const legacyInk = inkOverlayByTarget.get(targetRef);
    if (legacyNote) {
      removals.push(removeWikiOverlay({
        user_id: WIKI_OVERLAY_USER_ID,
        overlay_id: legacyNote.overlay_id,
      }));
    }
    if (legacyInk) {
      removals.push(removeWikiOverlay({
        user_id: WIKI_OVERLAY_USER_ID,
        overlay_id: legacyInk.overlay_id,
      }));
    }
    if (removals.length > 0) {
      await Promise.all(removals);
    }
  }

  async function saveEditedCardBundleForTarget(
    target: OverlayTargetDescriptor,
    options?: {
      strokes?: WikiInkStroke[];
      textAnnotations?: WikiTextAnnotation[];
      textStyle?: WikiEditedTextStyle;
    },
  ): Promise<void> {
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const legacyNote = noteOverlayByTarget.get(target.ref) ?? null;
    const legacyInk = inkOverlayByTarget.get(target.ref) ?? null;
    const strokes = Array.isArray(options?.strokes)
      ? options.strokes.filter((stroke) => String(stroke.path || '').trim())
      : existingEditedCard?.strokes ?? legacyInk?.strokes ?? [];
    const anchor = target.kind === 'section'
      ? overlayAnchorFromTargetRef(target.ref)
      : '';
    const textAnnotations = Array.isArray(options?.textAnnotations)
      ? options.textAnnotations
        .map((item) => normalizeTextAnnotation(item, anchor))
        .filter((item): item is WikiTextAnnotation => Boolean(item))
      : extractTextAnnotations(existingEditedCard ?? legacyNote, anchor);
    const textStyle = normalizeEditedTextStyle(
      options?.textStyle
      ?? existingEditedCard?.text_style
      ?? legacyNote?.text_style
      ?? annotationTextStyle,
    );

    setIsOverlaySaving(true);
    try {
      if (textAnnotations.length === 0 && strokes.length === 0) {
        if (existingEditedCard) {
          await removeWikiOverlay({
            user_id: WIKI_OVERLAY_USER_ID,
            overlay_id: existingEditedCard.overlay_id,
          });
        }
        await cleanupLegacyEditOverlaysForTarget(target.ref);
      } else {
        await saveWikiOverlay({
          user_id: WIKI_OVERLAY_USER_ID,
          kind: 'edited_card',
          overlay_id: existingEditedCard?.overlay_id ?? '',
          title: target.title,
          card_title: target.title,
          summary: preview.kind === 'viewer' || preview.kind === 'draft' ? preview.subtitle : '',
          body: '',
          strokes,
          text_style: textStyle,
          text_annotations: textAnnotations,
          source_anchor: anchor,
          source_viewer_path: target.viewerPath,
          document_title: `${target.title} 수정본`,
          document_label: target.kind === 'section' ? 'card_edit_snapshot' : 'book_edit_snapshot',
          pinned: true,
          ...target.payload,
        });
        await cleanupLegacyEditOverlaysForTarget(target.ref);
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleUpsertSectionTextAnnotation(
    section: { anchor: string; title: string },
    annotation: WikiTextAnnotation,
  ): Promise<void> {
    const target = buildSectionOverlayTarget(section.anchor, section.title);
    if (!target) {
      return;
    }
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const existingAnnotations = extractTextAnnotations(existingEditedCard ?? noteOverlayByTarget.get(target.ref) ?? null, section.anchor);
    const nextAnnotation = normalizeTextAnnotation(annotation, section.anchor);
    if (!nextAnnotation) {
      return;
    }
    const nextAnnotations = [
      ...existingAnnotations.filter((item) => (
        item.annotation_id !== nextAnnotation.annotation_id
        && !(nextAnnotation.kind === 'edit' && item.kind === 'edit' && item.block_path === nextAnnotation.block_path)
      )),
      nextAnnotation,
    ].sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === 'edit' ? -1 : 1;
      }
      if (left.kind === 'edit') {
        return String(left.block_path || '').localeCompare(String(right.block_path || ''));
      }
      return Number(left.y_ratio || 0) - Number(right.y_ratio || 0);
    });
    await saveEditedCardBundleForTarget(target, {
      textAnnotations: nextAnnotations,
      textStyle: nextAnnotation.style,
    });
  }

  async function handleRemoveSectionTextAnnotation(
    section: { anchor: string; title: string },
    annotationId: string,
  ): Promise<void> {
    const target = buildSectionOverlayTarget(section.anchor, section.title);
    if (!target) {
      return;
    }
    const existingEditedCard = editedCardOverlayByTarget.get(target.ref) ?? null;
    const existingAnnotations = extractTextAnnotations(existingEditedCard ?? noteOverlayByTarget.get(target.ref) ?? null, section.anchor);
    const nextAnnotations = existingAnnotations.filter((item) => item.annotation_id !== annotationId);
    await saveEditedCardBundleForTarget(target, {
      textAnnotations: nextAnnotations,
      textStyle: existingEditedCard?.text_style ?? annotationTextStyle,
    });
  }

  async function handleSaveCurrentInk(strokes: WikiInkStroke[]): Promise<void> {
    if (!currentOverlayTarget) {
      return;
    }
    const normalizedStrokes = strokes.filter((stroke) => String(stroke.path || '').trim());
    await saveEditedCardBundleForTarget(currentOverlayTarget, {
      strokes: normalizedStrokes,
      textStyle: currentEditedCard?.text_style ?? annotationTextStyle,
    });
  }

  async function handleSaveCurrentNote(): Promise<void> {
    if (!currentOverlayTarget) {
      return;
    }
    const nextBody = noteDraft.trim();
    setIsOverlaySaving(true);
    try {
      if (!nextBody) {
        if (currentNote) {
          await removeWikiOverlay({
            user_id: WIKI_OVERLAY_USER_ID,
            overlay_id: currentNote.overlay_id,
          });
        }
      } else {
        await saveWikiOverlay({
          user_id: WIKI_OVERLAY_USER_ID,
          kind: 'note',
          overlay_id: currentNote?.overlay_id ?? '',
          title: currentOverlayTarget.title,
          card_title: currentOverlayTarget.title,
          summary: preview.kind === 'viewer' || preview.kind === 'draft' ? preview.subtitle : '',
          body: nextBody,
          text_style: annotationTextStyle,
          source_anchor: currentOverlayTarget.kind === 'section' ? overlayAnchorFromTargetRef(currentOverlayTarget.ref) : '',
          source_viewer_path: currentOverlayTarget.viewerPath,
          pinned: true,
          ...currentOverlayTarget.payload,
        });
      }
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  async function handleRemoveCurrentNote(): Promise<void> {
    if (!currentNote) {
      return;
    }
    setIsOverlaySaving(true);
    try {
      await removeWikiOverlay({
        user_id: WIKI_OVERLAY_USER_ID,
        overlay_id: currentNote.overlay_id,
      });
      setNoteDraft('');
      await refreshWikiOverlays();
    } catch (error) {
      console.error(error);
    } finally {
      setIsOverlaySaving(false);
    }
  }

  function activateReaderMode(): void {
    setInteractionMode('reader');
    setAnnotationEnabled(false);
  }

  function activateStudioMode(): void {
    setInteractionMode('studio');
  }

  async function handleViewerPageModeChange(nextMode: ViewerPageMode): Promise<void> {
    if (nextMode === viewerPageMode) {
      return;
    }
    setViewerPageMode(nextMode);
    if (preview.kind === 'viewer') {
      await openViewerPreview(
        currentViewerPath || runtimePathFromUrl(preview.viewerUrl),
        preview.title,
        activeSourceId ?? undefined,
        nextMode,
      );
      return;
    }
    if (preview.kind === 'draft') {
      await openDraftPreview(
        preview.draft.draft_id,
        drafts,
        currentViewerPath || preview.book?.target_viewer_path || '',
        nextMode,
      );
    }
  }

  function selectAnnotationTool(tool: WikiAnnotationTool): void {
    activateStudioMode();
    setAnnotationTool(tool);
    setAnnotationEnabled(true);
  }

  const viewerPageModeLabel = viewerPageMode === 'single' ? 'Single page' : 'Multi page';
  const viewerPageModeButtonLabel = viewerPageMode === 'single' ? 'Single' : 'Multi';
  const viewerToolbar = (
    <div className="llmwikibook-page__viewer-toolbar">
      <span className="llmwikibook-chip is-muted">{viewerPageModeLabel}</span>
      <span className={`llmwikibook-chip ${interactionMode === 'studio' ? 'is-accent' : ''}`}>
        {interactionMode === 'studio' ? 'Studio Mode' : 'Reader Mode'}
      </span>
      {currentTruthSurface.label && (
        <span className="llmwikibook-chip">{currentTruthSurface.label}</span>
      )}
      {viewerActiveSection && (
        <span className="llmwikibook-chip is-muted">{viewerActiveSection.title}</span>
      )}
    </div>
  );

  const previewSubtitle = preview.kind === 'viewer' || preview.kind === 'draft' ? preview.subtitle : '';
  const sidecarNoteDirty = noteDraft.trim() !== String(currentNote?.body || '').trim();
  const sidecarOpen = interactionMode === 'studio';
  const hasReaderDocument = preview.kind === 'viewer' || preview.kind === 'draft';
  const isPreviewLoading = preview.kind === 'loading';
  const currentDocumentTitle = hasReaderDocument || isPreviewLoading ? preview.title : 'LLMWikiBook';
  const currentDocumentSubtitle = hasReaderDocument
    ? previewSubtitle || 'Source-backed reading runtime'
    : isPreviewLoading
      ? `${viewerPageModeLabel} view를 여는 중입니다.`
    : 'Connected playbook reading surface';
  const currentSectionLabel = viewerActiveSection?.title || '문서 상단';
  const readerEmptyState = isPreviewLoading ? (
    <div className="llmwikibook-page__reader-empty llmwikibook-page__reader-empty--loading">
      <span className="llmwikibook-chip is-muted">{viewerPageModeLabel}</span>
      <strong>{preview.title}</strong>
      <p>선택한 문서를 같은 reading canvas에서 여는 중입니다.</p>
    </div>
  ) : (
    <div className="llmwikibook-page__reader-empty">
      <BookOpen size={18} />
      <strong>Playbook을 선택하면 LLMWikiBook reading canvas에서 바로 열립니다.</strong>
      <p>문서 읽기, source jump, studio sidecar가 한 surface 안에서 분리된 위계로 동작합니다.</p>
    </div>
  );

  const officialNavItems = useMemo<LlmWikiBookNavItem[]>(() => {
    return outlineFamilies.flatMap((family) => {
      const familyBooks = [family.primary, ...family.variants];
      return familyBooks.map((book, index) => ({
        id: `manual:${book.book_slug}`,
        label: index === 0 ? family.primary.title : describeOutlineVariant(book),
        summary: '',
        badge: book.grade,
        active: activeSourceId === `manual:${book.book_slug}`,
        depth: index === 0 ? 0 : 1,
      }));
    });
  }, [activeSourceId, outlineFamilies]);

  const draftNavItems = useMemo<LlmWikiBookNavItem[]>(() => {
    return draftSources.map((source) => ({
      id: source.id,
      label: source.name,
      summary: source.meta,
      meta: source.draft?.pack_label || '',
      badge: source.grade,
      active: activeSourceId === source.id,
    }));
  }, [activeSourceId, draftSources]);

  const bookTreeItems = useMemo<LlmWikiBookNavItem[]>(() => {
    return quickNavItems.map((item) => ({
      id: item.id,
      label: item.heading,
      active: currentViewerPath.endsWith(`#${item.id}`) || viewerActiveSection?.anchor === item.id,
    }));
  }, [currentViewerPath, quickNavItems, viewerActiveSection?.anchor]);

  const relatedPlayItems = useMemo<LlmWikiBookNavItem[]>(() => {
    if (preview.kind === 'draft') {
      return preview.derivedAssets.map((asset) => ({
        id: asset.asset_slug,
        label: asset.title,
        summary: asset.family_label,
      }));
    }
    return currentFamilyVariants.map((book) => ({
      id: book.book_slug,
      label: book.title,
      summary: describeOutlineVariant(book),
    }));
  }, [currentFamilyVariants, preview]);

  const topBar = (
    <LlmWikiBookTopBar
      className={hasReaderDocument ? 'is-document-active' : undefined}
      mode={interactionMode}
      eyebrow="LLMWikiBook"
      title={currentDocumentTitle}
      subtitle={currentDocumentSubtitle}
      leading={(
            <Link to={ROUTES.pbsPlaybookLibrary} className="llmwikibook-button llmwikibook-button--ghost" aria-label="Playbook Library로 이동">
          <ArrowLeft size={15} />
        </Link>
      )}
      breadcrumbs={(
        <>
              <Link to={buildSharedLandingHref('pbs')} className="llmwikibook-inline-link">Home</Link>
          <span>/</span>
              <Link to={ROUTES.pbsPlaybookLibrary} className="llmwikibook-inline-link">Playbook Library</Link>
          <span>/</span>
          <span>LLMWikiBook</span>
        </>
      )}
      status={(
        <>
          {isBootstrapLoading ? <span className="llmwikibook-chip is-muted">syncing</span> : null}
          <span className="llmwikibook-chip is-muted">{viewerPageModeLabel}</span>
          {currentTruthSurface.label ? <span className="llmwikibook-chip">{currentTruthSurface.label}</span> : null}
          {hasReaderDocument && viewerActiveSection ? (
            <span className="llmwikibook-chip is-muted">{viewerActiveSection.title}</span>
          ) : null}
          {bootstrapError ? <span className="llmwikibook-chip is-danger">warning</span> : null}
        </>
      )}
      modeToggle={(
        <>
          <div className="llmwikibook-segmented" aria-label="Interaction mode">
            <button
              type="button"
              className={`llmwikibook-segmented__button ${interactionMode === 'reader' ? 'is-active' : ''}`}
              onClick={activateReaderMode}
            >
              Reader
            </button>
            <button
              type="button"
              className={`llmwikibook-segmented__button ${interactionMode === 'studio' ? 'is-active' : ''}`}
              onClick={activateStudioMode}
            >
              Studio
            </button>
          </div>
          <div className="llmwikibook-segmented" aria-label="Page mode">
            <button
              type="button"
              className={`llmwikibook-segmented__button ${viewerPageMode === 'single' ? 'is-active' : ''}`}
              onClick={() => {
                void handleViewerPageModeChange('single');
              }}
              disabled={isPreviewLoading}
            >
              Single
            </button>
            <button
              type="button"
              className={`llmwikibook-segmented__button ${viewerPageMode === 'multi' ? 'is-active' : ''}`}
              onClick={() => {
                void handleViewerPageModeChange('multi');
              }}
              disabled={isPreviewLoading}
            >
              Multi
            </button>
          </div>
        </>
      )}
      actions={(
        <>
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--ghost"
            onClick={() => setLeftRailCollapsed((current) => !current)}
            aria-pressed={!leftRailCollapsed}
          >
            <PanelLeftClose size={14} />
            <span>Library</span>
          </button>
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--ghost"
            onClick={() => setRightRailCollapsed((current) => !current)}
            aria-pressed={!rightRailCollapsed}
          >
            <PanelRightClose size={14} />
            <span>Outline</span>
          </button>
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--accent"
            onClick={interactionMode === 'studio' ? activateReaderMode : activateStudioMode}
          >
            <StickyNote size={14} />
            <span>{interactionMode === 'studio' ? 'Reader' : 'Studio'}</span>
          </button>
        </>
      )}
    />
  );

  const leftRail = (
    <LlmWikiBookLeftRail
      header={(
        <LlmWikiBookSectionCard
          eyebrow="Library"
          title="Shelf"
          description={`${manualSources.length} official runtime${draftSources.length > 0 ? ` · ${draftSources.length} draft` : ''}`}
          compact={true}
          className="llmwikibook-page__rail-summary-card"
        />
      )}
    >
      <LlmWikiBookSectionCard
        eyebrow="Official"
        title="Playbook Families"
        description="family 중심으로 읽을 책을 고릅니다."
        className="llmwikibook-page__rail-card"
      >
        {officialNavItems.length > 0 ? (
          <LlmWikiBookNavList
            items={officialNavItems}
            ariaLabel="Official playbooks"
            dense={true}
            className="llmwikibook-page__rail-nav"
            onItemSelect={(item) => {
              const source = manualSources.find((entry) => entry.id === item.id);
              if (source) {
                void handleSourceClick(source);
              }
            }}
          />
        ) : (
          <div className="llmwikibook-page__empty-block">공식 runtime book이 아직 없습니다.</div>
        )}
      </LlmWikiBookSectionCard>
      {draftNavItems.length > 0 ? (
        <LlmWikiBookSectionCard
          eyebrow="Customer"
          title="Drafts"
          description="같은 shell에서 review 대상으로 엽니다."
          tone="muted"
          className="llmwikibook-page__rail-card"
        >
          <LlmWikiBookNavList
            items={draftNavItems}
            ariaLabel="Customer drafts"
            dense={true}
            className="llmwikibook-page__rail-nav"
            onItemSelect={(item) => {
              const source = draftSources.find((entry) => entry.id === item.id);
              if (source) {
                void handleSourceClick(source);
              }
            }}
          />
        </LlmWikiBookSectionCard>
      ) : null}
    </LlmWikiBookLeftRail>
  );

  const readingStage = (
    <LlmWikiBookReadingStage
      className={hasReaderDocument ? 'is-document-loaded' : undefined}
      eyebrow={preview.kind === 'empty' ? 'LLMWikiBook' : isPreviewLoading ? 'Opening document' : undefined}
      title={preview.kind === 'empty' ? 'Reader-first playbook runtime' : isPreviewLoading ? preview.title : undefined}
      lede={
        preview.kind === 'empty'
          ? '좌측 shelf에서 문서를 열면 source-backed reading canvas가 이 자리를 차지합니다.'
          : isPreviewLoading
            ? `${viewerPageModeLabel} view로 문서를 여는 중입니다.`
            : undefined
      }
      meta={isPreviewLoading ? <span>{viewerPageModeLabel}</span> : undefined}
      toolbar={null}
      hero={(
        <>
          {bootstrapError ? (
            <LlmWikiBookSectionCard tone="accent" compact={true}>
              <div className="llmwikibook-page__warning-line">
                <strong>llmwikibook bootstrap warning</strong>
                <span>{bootstrapError}</span>
              </div>
            </LlmWikiBookSectionCard>
          ) : null}
          {preview.kind === 'viewer' || preview.kind === 'draft' ? viewerToolbar : null}
        </>
      )}
      emphasis="immersive"
    >
      <LlmWikiBookReaderPane
        viewerDocument={preview.kind === 'viewer' || preview.kind === 'draft' ? preview.viewerDocument : undefined}
        viewerPath={currentViewerPath}
        emptyState={readerEmptyState}
        toolbar={null}
        annotationEnabled={interactionMode === 'studio' && annotationEnabled}
        annotationTool={annotationTool}
        activeInkStyle={activeInkStyle}
        savedInkStrokes={interactionMode === 'studio' ? currentInkStrokes : []}
        inkSurfaceKey={currentOverlayTarget?.ref || currentViewerPath || (activeDraft ? `draft:${activeDraft.draft_id}` : `preview:${preview.kind}`)}
        textAnnotationsByAnchor={interactionMode === 'studio' ? sectionTextAnnotationsByAnchor : undefined}
        textToolMode={annotationTextMode}
        activeTextStyle={annotationTextStyle}
        onNavigateViewerPath={(viewerPath) => {
          void handleNavigateViewerPath(viewerPath);
        }}
        onActiveSectionChange={setViewerActiveSection}
        onSaveTextAnnotation={(section, annotation) => {
          void handleUpsertSectionTextAnnotation(section, annotation);
        }}
        onRemoveTextAnnotation={(section, annotationId) => {
          void handleRemoveSectionTextAnnotation(section, annotationId);
        }}
        onSaveInk={(strokes) => {
          void handleSaveCurrentInk(strokes);
        }}
      />
    </LlmWikiBookReadingStage>
  );

  const rightRail = (
    <LlmWikiBookRightRail>
      <LlmWikiBookSectionCard
        eyebrow="Reading"
        title={hasReaderDocument ? preview.title : '문서를 선택해 주세요'}
        description={hasReaderDocument ? currentDocumentSubtitle : '선택한 문서의 outline과 source가 이 레일에 정리됩니다.'}
      >
        <dl className="llmwikibook-page__context-list">
          <div className="llmwikibook-page__context-row">
            <dt>Current section</dt>
            <dd>{hasReaderDocument ? currentSectionLabel : 'not loaded'}</dd>
          </div>
          <div className="llmwikibook-page__context-row">
            <dt>Runtime</dt>
            <dd>{currentTruthSurface.label || 'same-truth runtime'}</dd>
          </div>
          <div className="llmwikibook-page__context-row">
            <dt>Mode</dt>
            <dd>{`${viewerPageModeButtonLabel} · ${interactionMode === 'studio' ? 'Studio sidecar open' : 'Reader focused'}`}</dd>
          </div>
        </dl>
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="On this page"
        title="Outline"
      >
        {bookTreeItems.length > 0 ? (
          <LlmWikiBookNavList
            items={bookTreeItems}
            ariaLabel="Document toc"
            dense={true}
            onItemSelect={(item) => {
              const target = quickNavItems.find((entry) => entry.id === item.id);
              if (target) {
                void handleNavigateViewerPath(target.viewerPath);
              }
            }}
          />
        ) : (
          <div className="llmwikibook-page__empty-block">문서를 열면 outline이 여기에 생성됩니다.</div>
        )}
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="Source"
        title="Lineage"
        description="same-truth binding"
      >
        <div className="llmwikibook-page__lineage">
          <div className="llmwikibook-page__lineage-row">
            <strong>viewer path</strong>
            <span>{currentViewerPath || 'not loaded'}</span>
          </div>
          {preview.kind === 'viewer' && preview.meta?.source_url ? (
            <div className="llmwikibook-page__lineage-row">
              <strong>origin</strong>
              <a href={preview.meta.source_url} target="_blank" rel="noreferrer" className="llmwikibook-inline-link">
                {preview.meta.source_url}
              </a>
            </div>
          ) : null}
          {currentTruthSurface.meta.length > 0 ? (
            <div className="llmwikibook-page__chip-row">
              {currentTruthSurface.meta.map((item) => (
                <span key={item} className="llmwikibook-chip is-muted">{item}</span>
              ))}
            </div>
          ) : null}
        </div>
      </LlmWikiBookSectionCard>

      {relatedPlayItems.length > 0 ? (
        <LlmWikiBookSectionCard
          eyebrow={preview.kind === 'draft' ? 'Derived assets' : 'Related plays'}
          title={preview.kind === 'draft' ? 'Pack Outputs' : 'Same Family'}
          description={preview.kind === 'draft' ? 'draft가 만든 runtime candidate' : '같은 family의 다른 playbook variant'}
        >
          <LlmWikiBookNavList
            items={relatedPlayItems}
            ariaLabel="Related plays"
            dense={true}
            onItemSelect={(item) => {
              if (preview.kind === 'draft') {
                const asset = preview.derivedAssets.find((entry) => entry.asset_slug === item.id);
                if (asset) {
                  void handleNavigateViewerPath(asset.viewer_path);
                }
                return;
              }
              const book = currentFamilyVariants.find((entry) => entry.book_slug === item.id);
              if (book) {
                void handleSourceClick({
                  id: `manual:${book.book_slug}`,
                  kind: 'manual',
                  name: book.title,
                  meta: summarizeBookMeta(book),
                  grade: book.grade,
                  viewerPath: book.viewer_path,
                  book,
                });
              }
            }}
          />
        </LlmWikiBookSectionCard>
      ) : null}
    </LlmWikiBookRightRail>
  );

  const sidecar = (
    <LlmWikiBookSidecar
      emphasis="studio"
      header={(
        <LlmWikiBookSectionCard
          title="Studio"
          description="reader를 덮지 않는 editing lane"
          compact={true}
          tone="accent"
          className="llmwikibook-page__sidecar-header"
        />
      )}
    >
      <LlmWikiBookSectionCard
        eyebrow="Target"
        title={currentOverlayTarget?.title || '현재 card를 선택해 주세요'}
        description={
          currentOverlayTarget
            ? `${currentOverlayTarget.kind} · current selection`
            : 'note, ink, edited card는 source overwrite 없이 overlay로 저장됩니다.'
        }
        tone="accent"
        className="llmwikibook-page__sidecar-card"
      >
        <dl className="llmwikibook-page__context-list llmwikibook-page__context-list--compact">
          <div className="llmwikibook-page__context-row">
            <dt>Status</dt>
            <dd>{isOverlaySaving ? 'Saving overlay' : isOverlayLoading ? 'Syncing overlays' : 'Ready for edit'}</dd>
          </div>
          <div className="llmwikibook-page__context-row">
            <dt>Target ref</dt>
            <dd>{currentOverlayTarget?.ref || 'no selection'}</dd>
          </div>
        </dl>
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="Tools"
        title="Annotation"
        description="텍스트, 잉크, 형광펜을 같은 target_ref에 묶습니다."
        className="llmwikibook-page__sidecar-card"
      >
        <div className="llmwikibook-page__tool-grid">
          <button
            type="button"
            className={`llmwikibook-button ${annotationTool === 'text' && annotationEnabled ? 'llmwikibook-button--accent' : 'llmwikibook-button--ghost'}`}
            onClick={() => selectAnnotationTool('text')}
          >
            <Type size={14} />
            텍스트
          </button>
          <button
            type="button"
            className={`llmwikibook-button ${annotationTool === 'pen' && annotationEnabled ? 'llmwikibook-button--accent' : 'llmwikibook-button--ghost'}`}
            onClick={() => selectAnnotationTool('pen')}
          >
            <PenTool size={14} />
            잉크펜
          </button>
          <button
            type="button"
            className={`llmwikibook-button ${annotationTool === 'highlighter' && annotationEnabled ? 'llmwikibook-button--accent' : 'llmwikibook-button--ghost'}`}
            onClick={() => selectAnnotationTool('highlighter')}
          >
            <Highlighter size={14} />
            형광펜
          </button>
        </div>

        {annotationTool === 'text' ? (
          <div className="llmwikibook-page__segmented-stack">
            <div className="llmwikibook-segmented">
              <button
                type="button"
                className={`llmwikibook-segmented__button ${annotationTextMode === 'add' ? 'is-active' : ''}`}
                onClick={() => {
                  activateStudioMode();
                  setAnnotationEnabled(true);
                  setAnnotationTextMode('add');
                }}
              >
                텍스트 추가
              </button>
              <button
                type="button"
                className={`llmwikibook-segmented__button ${annotationTextMode === 'edit' ? 'is-active' : ''}`}
                onClick={() => {
                  activateStudioMode();
                  setAnnotationEnabled(true);
                  setAnnotationTextMode('edit');
                }}
              >
                텍스트 수정
              </button>
            </div>
            <div className="llmwikibook-segmented">
              {(['sm', 'md', 'lg'] as const).map((size) => (
                <button
                  key={size}
                  type="button"
                  className={`llmwikibook-segmented__button ${annotationTextStyle.size === size ? 'is-active' : ''}`}
                  onClick={() => setAnnotationTextStyle({ ...annotationTextStyle, size })}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="llmwikibook-page__swatches">
          {LLMWIKIBOOK_INK_STYLES.map((style) => (
            <button
              key={style.id}
              type="button"
              className={`llmwikibook-page__swatch ${annotationColorId === style.id ? 'is-active' : ''}`}
              style={{
                ['--llmwikibook-swatch-color' as string]:
                  annotationTool === 'highlighter' ? style.highlighterColor : style.penColor,
              }}
              onClick={() => {
                activateStudioMode();
                setAnnotationEnabled(true);
                setAnnotationColorId(style.id);
                if (annotationTool === 'text') {
                  setAnnotationTextStyle({
                    ...annotationTextStyle,
                    tone: annotationColorIdToTone(style.id),
                  });
                }
              }}
              aria-label={`${style.label} annotation`}
            />
          ))}
        </div>
        <p className="llmwikibook-page__helper-copy">
          {annotationEnabled ? `${annotationTool} tool active` : 'Select a tool to enter annotation mode'}
        </p>
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="Overlays"
        title="Current state"
        description="현재 card에 저장된 overlay 상태입니다."
        tone="muted"
        className="llmwikibook-page__sidecar-card"
      >
        <dl className="llmwikibook-page__context-list llmwikibook-page__context-list--compact">
          <div className="llmwikibook-page__context-row">
            <dt>Note</dt>
            <dd>{currentNote?.body ? 'Saved' : 'Empty'}</dd>
          </div>
          <div className="llmwikibook-page__context-row">
            <dt>Edited text</dt>
            <dd>{currentSectionAnnotationCount}</dd>
          </div>
          <div className="llmwikibook-page__context-row">
            <dt>Ink strokes</dt>
            <dd>{currentInkStrokes.length}</dd>
          </div>
        </dl>
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="Note"
        title="Working Note"
        description="현재 card에 남길 note를 적어두세요."
        className="llmwikibook-page__sidecar-card"
      >
        <textarea
          className="llmwikibook-page__note-input"
          value={noteDraft}
          onChange={(event) => setNoteDraft(event.target.value)}
          placeholder="Playbook card 옆에 남길 메모를 적어두세요."
          disabled={!currentOverlayTarget}
        />
        <div className="llmwikibook-page__action-row">
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--accent"
            disabled={!currentOverlayTarget || (!sidecarNoteDirty && !isOverlaySaving)}
            onClick={() => { void handleSaveCurrentNote(); }}
          >
            저장
          </button>
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--ghost"
            disabled={!currentNote || isOverlaySaving}
            onClick={() => { void handleRemoveCurrentNote(); }}
          >
            삭제
          </button>
        </div>
      </LlmWikiBookSectionCard>

      <LlmWikiBookSectionCard
        eyebrow="Contract"
        title="Editing Rules"
        description="source truth를 덮지 않고 refinement layer로 저장합니다."
        tone="muted"
        compact={true}
        className="llmwikibook-page__sidecar-card llmwikibook-page__sidecar-rules"
      >
        <ul className="llmwikibook-page__rule-list">
          <li>source overwrite 없이 overlay만 저장</li>
          <li>text tool은 edited_card bundle로 저장</li>
          <li>ink는 같은 target_ref에 묶여 복원</li>
          <li>legacy /studio와 같은 note contract를 재사용</li>
        </ul>
      </LlmWikiBookSectionCard>
    </LlmWikiBookSidecar>
  );

  return (
    <LlmWikiBookShell
      mode={interactionMode}
      topBar={topBar}
      leftRail={leftRail}
      readingStage={readingStage}
      rightRail={rightRail}
      sidecar={sidecar}
      sidecarOpen={sidecarOpen}
      leftRailCollapsed={leftRailCollapsed}
      rightRailCollapsed={rightRailCollapsed}
    />
  );
}
