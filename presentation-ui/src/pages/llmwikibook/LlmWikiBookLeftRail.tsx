import clsx from 'clsx';
import type { CSSProperties, ReactNode } from 'react';

export interface LlmWikiBookLeftRailProps {
  className?: string;
  header?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  stickyOffset?: number;
}

export function LlmWikiBookLeftRail({
  className,
  header,
  children,
  footer,
  stickyOffset = 92,
}: LlmWikiBookLeftRailProps) {
  const style = {
    '--llmwikibook-sticky-offset': `${stickyOffset}px`,
  } as CSSProperties;

  return (
    <div className={clsx('llmwikibook-left-rail', className)} style={style}>
      {header ? <div className="llmwikibook-left-rail__header">{header}</div> : null}
      <div className="llmwikibook-left-rail__scroll">{children}</div>
      {footer ? <div className="llmwikibook-left-rail__footer">{footer}</div> : null}
    </div>
  );
}
