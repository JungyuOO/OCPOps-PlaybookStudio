import clsx from 'clsx';
import type { CSSProperties, ReactNode } from 'react';

export interface LlmWikiBookRightRailProps {
  className?: string;
  header?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  stickyOffset?: number;
}

export function LlmWikiBookRightRail({
  className,
  header,
  children,
  footer,
  stickyOffset = 92,
}: LlmWikiBookRightRailProps) {
  const style = {
    '--llmwikibook-sticky-offset': `${stickyOffset}px`,
  } as CSSProperties;

  return (
    <div className={clsx('llmwikibook-right-rail', className)} style={style}>
      {header ? <div className="llmwikibook-right-rail__header">{header}</div> : null}
      <div className="llmwikibook-right-rail__scroll">{children}</div>
      {footer ? <div className="llmwikibook-right-rail__footer">{footer}</div> : null}
    </div>
  );
}
