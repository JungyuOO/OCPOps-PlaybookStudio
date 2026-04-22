import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode, type RefObject } from 'react';
import { BookOpen, Highlighter, PanelRightClose, PenTool, Trash2, Type } from 'lucide-react';
import { Panel, usePanelRef } from 'react-resizable-panels';
import type {
  WikiAnnotationTool,
  WikiEditedTextStyle,
  WikiInkColorId,
  WikiInkStroke,
  WikiInkStyle,
  WikiInkTool,
  WikiTextAnnotationMode,
} from '../../lib/runtimeApi';

const INK_STYLES: WikiInkStyle[] = [
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

type WorkspaceViewerPanelProps = {
  annotationColorId: WikiInkColorId;
  annotationEnabled: boolean;
  annotationTool: WikiAnnotationTool;
  atlasCanvasActive: boolean;
  children: ReactNode;
  drawerContent: ReactNode;
  fileInputRef: RefObject<HTMLInputElement | null>;
  headerToolbar?: ReactNode;
  inkSurfaceKey: string;
  isInkSaving: boolean;
  rightCollapsed: boolean;
  savedInkStrokes: WikiInkStroke[];
  sourcesDrawerOpen: boolean;
  testMode: boolean;
  textAnnotationMode: WikiTextAnnotationMode;
  textAnnotationStyle: WikiEditedTextStyle;
  uploadAccept: string;
  viewerSurfaceTitle: string;
  onAnnotationColorChange: (colorId: WikiInkColorId) => void;
  onAnnotationEnabledChange: (enabled: boolean) => void;
  onAnnotationToolChange: (tool: WikiAnnotationTool) => void;
  onSaveInk: (strokes: WikiInkStroke[]) => void;
  onRightPanelCollapsedChange: (collapsed: boolean) => void;
  onTextAnnotationModeChange: (mode: WikiTextAnnotationMode) => void;
  onTextAnnotationStyleChange: (style: WikiEditedTextStyle) => void;
  onToggleRightPanel: () => void;
  onToggleSourcesDrawer: () => void;
  onUploadSelection: (event: ChangeEvent<HTMLInputElement>) => void;
  panelRef: ReturnType<typeof usePanelRef>;
};

export default function WorkspaceViewerPanel({
  annotationColorId,
  annotationEnabled,
  annotationTool,
  atlasCanvasActive,
  children,
  drawerContent,
  fileInputRef,
  headerToolbar,
  inkSurfaceKey,
  isInkSaving,
  rightCollapsed,
  savedInkStrokes,
  sourcesDrawerOpen,
  testMode,
  textAnnotationMode,
  textAnnotationStyle,
  uploadAccept,
  viewerSurfaceTitle,
  onAnnotationColorChange,
  onAnnotationEnabledChange,
  onAnnotationToolChange,
  onSaveInk,
  onRightPanelCollapsedChange,
  onTextAnnotationModeChange,
  onTextAnnotationStyleChange,
  onToggleRightPanel,
  onToggleSourcesDrawer,
  onUploadSelection,
  panelRef,
}: WorkspaceViewerPanelProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const inkPopoverRef = useRef<HTMLDivElement | null>(null);
  const drawingRef = useRef<{ pointerId: number; stroke: WikiInkStroke } | null>(null);
  const [annotationPopoverOpen, setAnnotationPopoverOpen] = useState(false);
  const [inkStrokes, setInkStrokes] = useState<WikiInkStroke[]>(savedInkStrokes);
  const [activeInkStroke, setActiveInkStroke] = useState<WikiInkStroke | null>(null);
  const [inkViewport, setInkViewport] = useState({ width: 0, height: 0 });
  const annotationAvailable = atlasCanvasActive && !rightCollapsed;
  const inkTool = annotationTool === 'highlighter' ? 'highlighter' : 'pen';
  const inkToolActive = annotationTool === 'pen' || annotationTool === 'highlighter';
  const inkEnabled = annotationAvailable && annotationEnabled && inkToolActive;
  const activeInkStyle = INK_STYLES.find((style) => style.id === annotationColorId) ?? INK_STYLES[0];
  const ActiveToolIcon = annotationTool === 'text' ? Type : annotationTool === 'highlighter' ? Highlighter : PenTool;
  const activeToolLabel = annotationTool === 'text' ? '텍스트' : annotationTool === 'highlighter' ? '형광펜' : '잉크펜';
  const activeToolColor = annotationTool === 'highlighter' ? activeInkStyle.highlighterColor : activeInkStyle.penColor;
  const savedInkSnapshot = useMemo(() => JSON.stringify(savedInkStrokes), [savedInkStrokes]);
  const currentInkSnapshot = useMemo(() => JSON.stringify(inkStrokes), [inkStrokes]);
  const hasInkChanges = currentInkSnapshot !== savedInkSnapshot;
  const inkStatusLabel = isInkSaving
    ? '저장 중'
    : hasInkChanges
      ? '변경됨'
      : inkStrokes.length > 0
        ? '저장됨'
        : '비어 있음';

  useEffect(() => {
    if (!annotationAvailable) {
      onAnnotationEnabledChange(false);
      setAnnotationPopoverOpen(false);
    }
  }, [annotationAvailable, onAnnotationEnabledChange]);

  useEffect(() => {
    onAnnotationEnabledChange(false);
    setAnnotationPopoverOpen(false);
    setInkStrokes(savedInkStrokes);
    setActiveInkStroke(null);
    drawingRef.current = null;
  }, [inkSurfaceKey, onAnnotationEnabledChange, savedInkSnapshot]);

  useEffect(() => {
    if (!annotationPopoverOpen) {
      return undefined;
    }

    const handlePointerDown = (event: PointerEvent): void => {
      const targetNode = event.target;
      if (!(targetNode instanceof Node)) {
        return;
      }
      if (inkPopoverRef.current?.contains(targetNode)) {
        return;
      }
      setAnnotationPopoverOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setAnnotationPopoverOpen(false);
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [annotationPopoverOpen]);

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
      if (child instanceof HTMLElement && !child.classList.contains('atlas-ink-overlay')) {
        resizeObserver.observe(child);
      }
    });
    window.addEventListener('resize', updateViewport);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateViewport);
    };
  }, [children, annotationAvailable, inkSurfaceKey]);

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
      tool: inkTool as WikiInkTool,
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

  function handleAnnotationPrimaryAction(): void {
    if (!annotationEnabled) {
      onAnnotationEnabledChange(true);
      setAnnotationPopoverOpen(true);
      return;
    }
    setAnnotationPopoverOpen((current) => !current);
  }

  return (
    <Panel
      id="workspace-right"
      panelRef={panelRef}
      defaultSize={40}
      minSize={24}
      collapsible={true}
      collapsedSize={0}
      onResize={(panelSize) => onRightPanelCollapsedChange(panelSize.asPercentage <= 0.5)}
      className="workspace-panel-item"
      >
        <div className={`panel-inner workspace-viewer-panel no-border-radius-left ${rightCollapsed ? 'panel-collapsed-inner' : ''}`}>
          <div className={`panel-header ${testMode ? '' : 'viewer-panel-toolbar'}`} style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <div className="panel-header-copy" style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '12px' }}>
              {testMode && <div className="header-icon"><BookOpen size={18} /></div>}
              <h3 style={{ margin: 0 }}>{viewerSurfaceTitle}</h3>
            </div>

            <div className={`viewer-utility-bar ${testMode ? '' : 'viewer-utility-bar-minimal'}`} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: 0, border: 'none', background: 'transparent' }}>
              {headerToolbar}
              {annotationAvailable && (
                <div
                  ref={inkPopoverRef}
                className={`viewer-ink-popover-anchor ${annotationPopoverOpen ? 'open' : ''}`}
              >
                <button
                  className={`viewer-utility-btn ${annotationEnabled ? 'active' : ''}`}
                  type="button"
                  onClick={handleAnnotationPrimaryAction}
                  title={annotationEnabled ? '편집 도구 열기' : '주석 시작'}
                >
                  <ActiveToolIcon size={13} />
                  <span>{activeToolLabel}</span>
                  <span
                    className="viewer-ink-current-dot"
                    style={{ ['--ink-current-color' as string]: activeToolColor }}
                    aria-hidden="true"
                  />
                </button>
                {annotationPopoverOpen && (
                  <div className="viewer-ink-popover" role="dialog" aria-label="Annotation tools">
                    <div className="viewer-ink-popover-header">
                      <strong>Annotation Tools</strong>
                      <button
                        type="button"
                        className="viewer-ink-popover-close"
                        onClick={() => setAnnotationPopoverOpen(false)}
                      >
                        완료
                      </button>
                    </div>
                    <div className={`viewer-ink-status ${hasInkChanges ? 'is-dirty' : ''}`}>
                      <span>{annotationTool === 'text' ? (annotationEnabled ? '본문 편집 활성' : '본문 편집 대기') : inkStatusLabel}</span>
                      <span>{annotationTool === 'text' ? (textAnnotationMode === 'edit' ? '텍스트 수정' : '텍스트 추가') : `${inkStrokes.length} stroke${inkStrokes.length === 1 ? '' : 's'}`}</span>
                    </div>
                    <div className="viewer-ink-mode-switch" role="group" aria-label="Annotation tools">
                      <button
                        type="button"
                        className={`viewer-ink-mode-btn ${annotationTool === 'text' ? 'active' : ''}`}
                        onClick={() => {
                          onAnnotationEnabledChange(true);
                          onAnnotationToolChange('text');
                        }}
                      >
                        <Type size={13} />
                        텍스트
                      </button>
                      <button
                        type="button"
                        className={`viewer-ink-mode-btn ${annotationTool === 'pen' ? 'active' : ''}`}
                        onClick={() => {
                          onAnnotationEnabledChange(true);
                          onAnnotationToolChange('pen');
                        }}
                      >
                        <PenTool size={13} />
                        잉크펜
                      </button>
                      <button
                        type="button"
                        className={`viewer-ink-mode-btn ${annotationTool === 'highlighter' ? 'active' : ''}`}
                        onClick={() => {
                          onAnnotationEnabledChange(true);
                          onAnnotationToolChange('highlighter');
                        }}
                      >
                        <Highlighter size={13} />
                        형광펜
                      </button>
                    </div>
                    {annotationTool === 'text' && (
                      <>
                        <div className="viewer-annotation-submode-switch" role="group" aria-label="Text annotation mode">
                          <button
                            type="button"
                            className={`viewer-annotation-submode-btn ${textAnnotationMode === 'add' ? 'active' : ''}`}
                            onClick={() => onTextAnnotationModeChange('add')}
                          >
                            텍스트 추가
                          </button>
                          <button
                            type="button"
                            className={`viewer-annotation-submode-btn ${textAnnotationMode === 'edit' ? 'active' : ''}`}
                            onClick={() => onTextAnnotationModeChange('edit')}
                          >
                            텍스트 수정
                          </button>
                        </div>
                        <div className="viewer-annotation-style-row">
                          <span className="viewer-annotation-style-label">Size</span>
                          <div className="viewer-annotation-style-controls">
                            {(['sm', 'md', 'lg'] as const).map((size) => (
                              <button
                                key={size}
                                type="button"
                                className={`viewer-annotation-style-btn ${textAnnotationStyle.size === size ? 'active' : ''}`}
                                onClick={() => onTextAnnotationStyleChange({ ...textAnnotationStyle, size })}
                              >
                                {size === 'sm' ? 'Compact' : size === 'lg' ? 'Large' : 'Default'}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="viewer-annotation-style-row">
                          <span className="viewer-annotation-style-label">Weight</span>
                          <div className="viewer-annotation-style-controls">
                            {(['regular', 'strong'] as const).map((weight) => (
                              <button
                                key={weight}
                                type="button"
                                className={`viewer-annotation-style-btn ${textAnnotationStyle.weight === weight ? 'active' : ''}`}
                                onClick={() => onTextAnnotationStyleChange({ ...textAnnotationStyle, weight })}
                              >
                                {weight === 'strong' ? 'Bold' : 'Regular'}
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                    <div className="viewer-ink-color-row" role="group" aria-label="Annotation colors">
                      {INK_STYLES.map((style) => (
                        <button
                          key={style.id}
                          type="button"
                          className={`viewer-ink-color-swatch ${annotationColorId === style.id ? 'active' : ''}`}
                          style={{
                            ['--ink-swatch-color' as string]:
                              annotationTool === 'highlighter' ? style.highlighterColor : style.penColor,
                          }}
                          title={`${annotationTool === 'text' ? '텍스트' : annotationTool === 'highlighter' ? '형광펜' : '잉크펜'} ${style.label}`}
                          aria-label={`${annotationTool === 'text' ? '텍스트' : annotationTool === 'highlighter' ? '형광펜' : '잉크펜'} ${style.label}`}
                          onClick={() => {
                            onAnnotationEnabledChange(true);
                            onAnnotationColorChange(style.id);
                          }}
                        />
                      ))}
                    </div>
                    <div className="viewer-ink-popover-actions">
                      {annotationTool !== 'text' && (
                        <>
                          <button
                            className="viewer-utility-btn"
                            type="button"
                            onClick={() => {
                              setInkStrokes([]);
                              setActiveInkStroke(null);
                              drawingRef.current = null;
                            }}
                            disabled={inkStrokes.length === 0 && !activeInkStroke}
                            title="낙서 지우기"
                          >
                            <Trash2 size={13} />
                            <span>지우기</span>
                          </button>
                          <button
                            className="viewer-utility-btn"
                            type="button"
                            onClick={() => onSaveInk(inkStrokes)}
                            disabled={!hasInkChanges || isInkSaving}
                            title="낙서 저장"
                          >
                            <span>{isInkSaving ? '저장 중' : '저장'}</span>
                          </button>
                        </>
                      )}
                      <button
                        className="viewer-utility-btn"
                        type="button"
                        onClick={() => {
                          onAnnotationEnabledChange(false);
                          setAnnotationPopoverOpen(false);
                        }}
                        title="편집 종료"
                      >
                        <span>끄기</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            <button className="header-action-btn" type="button" onClick={onToggleRightPanel} title="Close panel">
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>

        <input
          ref={fileInputRef}
          className="file-input-hidden"
          type="file"
          accept={uploadAccept}
          onChange={onUploadSelection}
        />

        {sourcesDrawerOpen && (
          <>
            <div
              className="sources-drawer-scrim"
              onClick={onToggleSourcesDrawer}
              aria-hidden="true"
            />
            <div className="sources-drawer-overlay" role="dialog" aria-label="Sources">
              {drawerContent}
            </div>
          </>
        )}

        <div className="source-viewer-content viewer-surface">
          <div
            ref={stageRef}
            className={`atlas-ink-stage ${inkEnabled ? 'is-inking' : ''}`}
          >
            {children}
            {annotationAvailable && inkToolActive && inkViewport.width > 0 && inkViewport.height > 0 && (
              <svg
                className={`atlas-ink-overlay ${inkEnabled ? 'is-enabled' : ''} atlas-ink-overlay--${inkTool}`}
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
                  className="atlas-ink-hit-area"
                  x="0"
                  y="0"
                  width={inkViewport.width}
                  height={inkViewport.height}
                />
                {inkStrokes.map((stroke, index) => (
                  <path
                    key={`ink-path-${index}`}
                    className={`atlas-ink-path atlas-ink-path--${stroke.tool}`}
                    d={stroke.path}
                    style={{
                      stroke: stroke.tool === 'highlighter' ? stroke.style.highlighterColor : stroke.style.penColor,
                    }}
                  />
                ))}
                {activeInkStroke && (
                  <path
                    className={`atlas-ink-path atlas-ink-path-active atlas-ink-path--${activeInkStroke.tool}`}
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
        </div>
      </div>
    </Panel>
  );
}
