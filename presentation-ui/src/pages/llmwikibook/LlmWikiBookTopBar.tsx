import clsx from 'clsx';
import type { ReactNode } from 'react';
import type { LlmWikiBookMode } from './LlmWikiBookShell';

export interface LlmWikiBookTopBarProps {
  className?: string;
  mode?: LlmWikiBookMode;
  eyebrow?: string;
  title: string;
  subtitle?: string;
  breadcrumbs?: ReactNode;
  leading?: ReactNode;
  status?: ReactNode;
  modeToggle?: ReactNode;
  actions?: ReactNode;
}

export function LlmWikiBookTopBar({
  className,
  mode = 'reader',
  eyebrow,
  title,
  subtitle,
  breadcrumbs,
  leading,
  status,
  modeToggle,
  actions,
}: LlmWikiBookTopBarProps) {
  return (
    <header className={clsx('llmwikibook-topbar', className)} data-mode={mode}>
      <div className="llmwikibook-topbar__leading">
        {leading ? <div className="llmwikibook-topbar__leading-slot">{leading}</div> : null}
        <div className="llmwikibook-topbar__titles">
          {eyebrow ? <div className="llmwikibook-topbar__eyebrow">{eyebrow}</div> : null}
          <div className="llmwikibook-topbar__headline-row">
            <div className="llmwikibook-topbar__headline-copy">
              <h1 className="llmwikibook-topbar__title">{title}</h1>
              {subtitle ? <p className="llmwikibook-topbar__subtitle">{subtitle}</p> : null}
            </div>
            {status ? <div className="llmwikibook-topbar__status">{status}</div> : null}
          </div>
          {breadcrumbs ? <div className="llmwikibook-topbar__breadcrumbs">{breadcrumbs}</div> : null}
        </div>
      </div>
      {modeToggle || actions ? (
        <div className="llmwikibook-topbar__actions">
          {modeToggle ? <div className="llmwikibook-topbar__mode-toggle">{modeToggle}</div> : null}
          {actions ? <div className="llmwikibook-topbar__action-row">{actions}</div> : null}
        </div>
      ) : null}
    </header>
  );
}
