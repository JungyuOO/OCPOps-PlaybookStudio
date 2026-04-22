import clsx from 'clsx';
import type { CSSProperties, ReactNode } from 'react';

export interface LlmWikiBookSidecarProps {
  className?: string;
  header?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  stickyOffset?: number;
  emphasis?: 'default' | 'studio';
}

export function LlmWikiBookSidecar({
  className,
  header,
  children,
  footer,
  stickyOffset = 92,
  emphasis = 'default',
}: LlmWikiBookSidecarProps) {
  const style = {
    '--llmwikibook-sticky-offset': `${stickyOffset}px`,
  } as CSSProperties;

  return (
    <div className={clsx('llmwikibook-sidecar-panel', className)} style={style} data-emphasis={emphasis}>
      {header ? <div className="llmwikibook-sidecar-panel__header">{header}</div> : null}
      <div className="llmwikibook-sidecar-panel__scroll">{children}</div>
      {footer ? <div className="llmwikibook-sidecar-panel__footer">{footer}</div> : null}
    </div>
  );
}
