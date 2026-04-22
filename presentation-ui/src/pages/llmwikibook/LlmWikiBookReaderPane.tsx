import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import clsx from 'clsx';
import ViewerDocumentStage, { type ViewerDocumentPayload } from '../../components/ViewerDocumentStage';
import type {
  WikiAnnotationTool,
  WikiEditedTextStyle,
  WikiInkStroke,
  WikiInkStyle,
  WikiTextAnnotation,
  WikiTextAnnotationMode,
} from '../../lib/runtimeApi';

export interface LlmWikiBookReaderPaneProps {
  className?: string;
  viewerDocument?: ViewerDocumentPayload;
  viewerPath?: string;
  emptyState?: ReactNode;
  toolbar?: ReactNode;
  annotationEnabled: boolean;
  annotationTool: WikiAnnotationTool;
  activeInkStyle: WikiInkStyle;
  savedInkStrokes: WikiInkStroke[];
  inkSurfaceKey: string;
  textAnnotationsByAnchor?: Record<string, WikiTextAnnotation[]>;
  textToolMode?: WikiTextAnnotationMode;
  activeTextStyle?: WikiEditedTextStyle;
  onNavigateViewerPath?: (viewerPath: string) => void;
  onActiveSectionChange?: (section: { anchor: string; title: string } | null) => void;
  onSaveTextAnnotation?: (
    section: { anchor: string; title: string },
    annotation: WikiTextAnnotation,
  ) => void;
  onRemoveTextAnnotation?: (
    section: { anchor: string; title: string },
    annotationId: string,
  ) => void;
  onSaveInk: (strokes: WikiInkStroke[]) => void;
}

export function LlmWikiBookReaderPane({
  className,
  viewerDocument,
  viewerPath,
  emptyState,
  toolbar,
  annotationEnabled,
  annotationTool,
  activeInkStyle,
  savedInkStrokes,
  inkSurfaceKey,
  textAnnotationsByAnchor,
  textToolMode = 'add',
  activeTextStyle,
  onNavigateViewerPath,
  onActiveSectionChange,
  onSaveTextAnnotation,
  onRemoveTextAnnotation,
  onSaveInk,
}: LlmWikiBookReaderPaneProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const drawingRef = useRef<{ pointerId: number; stroke: WikiInkStroke } | null>(null);
  const [inkStrokes, setInkStrokes] = useState<WikiInkStroke[]>(savedInkStrokes);
  const [activeInkStroke, setActiveInkStroke] = useState<WikiInkStroke | null>(null);
  const [inkViewport, setInkViewport] = useState({ width: 0, height: 0 });

  const inkEnabled = annotationEnabled && (annotationTool === 'pen' || annotationTool === 'highlighter');
  const activeInkColor = annotationTool === 'highlighter'
    ? activeInkStyle.highlighterColor
    : activeInkStyle.penColor;
  const savedInkSnapshot = useMemo(() => JSON.stringify(savedInkStrokes), [savedInkStrokes]);
  const currentInkSnapshot = useMemo(() => JSON.stringify(inkStrokes), [inkStrokes]);
  const hasInkChanges = currentInkSnapshot !== savedInkSnapshot;

  useEffect(() => {
    setInkStrokes(savedInkStrokes);
    setActiveInkStroke(null);
    drawingRef.current = null;
  }, [inkSurfaceKey, savedInkSnapshot]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) {
      return undefined;
    }

    const updateViewport = (): void => {
      const width = Math.max(Math.ceil(stage.getBoundingClientRect().width), 1);
      const height = Math.max(stage.scrollHeight, stage.clientHeight, 1);
      setInkViewport((current) => (
        current.width === width && current.height === height
          ? current
          : { width, height }
      ));
    };

    updateViewport();
    const resizeObserver = new ResizeObserver(() => {
      updateViewport();
    });
    resizeObserver.observe(stage);
    Array.from(stage.children).forEach((child) => {
      if (child instanceof HTMLElement && !child.classList.contains('llmwikibook-reader-pane__ink-overlay')) {
        resizeObserver.observe(child);
      }
    });
    window.addEventListener('resize', updateViewport);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateViewport);
    };
  }, [viewerDocument, inkSurfaceKey]);

  function pointFromEvent(
    event: React.PointerEvent<SVGSVGElement>,
  ): { x: number; y: number } {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function handleInkPointerDown(event: React.PointerEvent<SVGSVGElement>): void {
    const canStartInk = event.pointerType === 'mouse' ? event.button === 0 : event.isPrimary;
    if (!inkEnabled || !canStartInk) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const { x, y } = pointFromEvent(event);
    const stroke: WikiInkStroke = {
      path: `M ${x.toFixed(1)} ${y.toFixed(1)}`,
      tool: annotationTool === 'highlighter' ? 'highlighter' : 'pen',
      style: activeInkStyle,
    };
    drawingRef.current = { pointerId: event.pointerId, stroke };
    setActiveInkStroke(stroke);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleInkPointerMove(event: React.PointerEvent<SVGSVGElement>): void {
    const activeStroke = drawingRef.current;
    if (!inkEnabled || !activeStroke || activeStroke.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const { x, y } = pointFromEvent(event);
    activeStroke.stroke = {
      ...activeStroke.stroke,
      path: `${activeStroke.stroke.path} L ${x.toFixed(1)} ${y.toFixed(1)}`,
    };
    setActiveInkStroke(activeStroke.stroke);
  }

  function finalizeInkPointer(event: React.PointerEvent<SVGSVGElement>): void {
    const activeStroke = drawingRef.current;
    if (!activeStroke || activeStroke.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (activeStroke.stroke.path.trim()) {
      setInkStrokes((current) => [...current, activeStroke.stroke]);
    }
    drawingRef.current = null;
    setActiveInkStroke(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <div
      className={clsx(
        'llmwikibook-reader-pane',
        inkEnabled && 'is-inking',
        hasInkChanges && 'has-ink-changes',
        className,
      )}
    >
      {toolbar ? <div className="llmwikibook-reader-pane__toolbar">{toolbar}</div> : null}
      <div ref={stageRef} className="llmwikibook-reader-pane__stage">
        {viewerDocument ? (
          <ViewerDocumentStage
            viewerDocument={viewerDocument}
            currentViewerPath={viewerPath}
            onNavigateViewerPath={onNavigateViewerPath}
            onActiveSectionChange={onActiveSectionChange}
            textAnnotationsByAnchor={textAnnotationsByAnchor}
            textToolEnabled={annotationEnabled && annotationTool === 'text'}
            textToolMode={textToolMode}
            activeTextStyle={activeTextStyle}
            onSaveTextAnnotation={onSaveTextAnnotation}
            onRemoveTextAnnotation={onRemoveTextAnnotation}
            className="llmwikibook-reader-pane__document"
            surfaceVariant="editorial"
          />
        ) : (
          <div className="llmwikibook-reader-pane__empty">
            {emptyState}
          </div>
        )}

        {viewerDocument && inkViewport.width > 0 && inkViewport.height > 0 && (
          <svg
            className={clsx(
              'llmwikibook-reader-pane__ink-overlay',
              inkEnabled && 'is-enabled',
              annotationTool === 'highlighter' && 'is-highlighter',
            )}
            width={inkViewport.width}
            height={inkViewport.height}
            viewBox={`0 0 ${inkViewport.width} ${inkViewport.height}`}
            style={{ width: `${inkViewport.width}px`, height: `${inkViewport.height}px` }}
            onPointerDown={handleInkPointerDown}
            onPointerMove={handleInkPointerMove}
            onPointerUp={finalizeInkPointer}
            onPointerCancel={finalizeInkPointer}
            onPointerLeave={finalizeInkPointer}
          >
            <rect
              className="llmwikibook-reader-pane__ink-hit-area"
              x="0"
              y="0"
              width={inkViewport.width}
              height={inkViewport.height}
            />
            {inkStrokes.map((stroke, index) => (
              <path
                key={`llmwikibook-ink-path-${index}`}
                className={clsx(
                  'llmwikibook-reader-pane__ink-path',
                  stroke.tool === 'highlighter' && 'is-highlighter',
                )}
                d={stroke.path}
                style={{
                  stroke: stroke.tool === 'highlighter' ? stroke.style.highlighterColor : stroke.style.penColor,
                }}
              />
            ))}
            {activeInkStroke && (
              <path
                className={clsx(
                  'llmwikibook-reader-pane__ink-path',
                  'is-active',
                  activeInkStroke.tool === 'highlighter' && 'is-highlighter',
                )}
                d={activeInkStroke.path}
                style={{
                  stroke: activeInkStroke.tool === 'highlighter'
                    ? activeInkStroke.style.highlighterColor
                    : activeInkStroke.style.penColor,
                }}
              />
            )}
          </svg>
        )}
      </div>
      {viewerDocument && inkEnabled && hasInkChanges ? (
        <div className="llmwikibook-reader-pane__ink-save">
          <button
            type="button"
            className="llmwikibook-button llmwikibook-button--accent"
            onClick={() => onSaveInk(inkStrokes)}
            style={{ ['--llmwikibook-button-accent' as string]: activeInkColor }}
          >
            잉크 저장
          </button>
        </div>
      ) : null}
    </div>
  );
}
