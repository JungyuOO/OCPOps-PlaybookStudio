import clsx from 'clsx';
import type { ReactNode } from 'react';

export type LlmWikiBookMode = 'reader' | 'studio';

export interface LlmWikiBookShellProps {
  className?: string;
  mode?: LlmWikiBookMode;
  topBar?: ReactNode;
  leftRail?: ReactNode;
  readingStage?: ReactNode;
  rightRail?: ReactNode;
  sidecar?: ReactNode;
  sidecarOpen?: boolean;
  leftRailCollapsed?: boolean;
  rightRailCollapsed?: boolean;
  fullBleedStage?: boolean;
}

export function LlmWikiBookShell({
  className,
  mode = 'reader',
  topBar,
  leftRail,
  readingStage,
  rightRail,
  sidecar,
  sidecarOpen = false,
  leftRailCollapsed = false,
  rightRailCollapsed = false,
  fullBleedStage = false,
}: LlmWikiBookShellProps) {
  return (
    <div
      className={clsx(
        'llmwikibook-shell',
        sidecarOpen && 'is-sidecar-open',
        leftRailCollapsed && 'is-left-rail-collapsed',
        rightRailCollapsed && 'is-right-rail-collapsed',
        fullBleedStage && 'is-full-bleed-stage',
        className,
      )}
      data-mode={mode}
    >
      <div className="llmwikibook-shell__frame">
        {topBar ? <div className="llmwikibook-shell__topbar">{topBar}</div> : null}
        <div className="llmwikibook-shell__body">
          {!leftRailCollapsed && leftRail ? (
            <aside className="llmwikibook-shell__left-rail" aria-label="Library and book navigation">
              {leftRail}
            </aside>
          ) : null}
          <main className="llmwikibook-shell__stage" aria-label="Reading stage">
            {readingStage}
          </main>
          {!rightRailCollapsed && rightRail ? (
            <aside className="llmwikibook-shell__right-rail" aria-label="Context and navigation">
              {rightRail}
            </aside>
          ) : null}
          {sidecar ? (
            <aside
              className="llmwikibook-shell__sidecar"
              aria-label="Studio tools"
              aria-hidden={!sidecarOpen}
            >
              {sidecar}
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
