import clsx from 'clsx';
import type { ElementType, ReactNode } from 'react';

export interface LlmWikiBookReadingStageProps {
  className?: string;
  as?: ElementType;
  eyebrow?: string;
  title?: string;
  lede?: ReactNode;
  meta?: ReactNode;
  toolbar?: ReactNode;
  hero?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  emphasis?: 'default' | 'immersive';
}

export function LlmWikiBookReadingStage({
  className,
  as: Component = 'article',
  eyebrow,
  title,
  lede,
  meta,
  toolbar,
  hero,
  children,
  footer,
  emphasis = 'default',
}: LlmWikiBookReadingStageProps) {
  return (
    <Component className={clsx('llmwikibook-stage', className)} data-emphasis={emphasis}>
      {eyebrow || title || lede || meta || toolbar ? (
        <header className="llmwikibook-stage__header">
          <div className="llmwikibook-stage__copy">
            {eyebrow ? <div className="llmwikibook-stage__eyebrow">{eyebrow}</div> : null}
            {title ? <h1 className="llmwikibook-stage__title">{title}</h1> : null}
            {lede ? <div className="llmwikibook-stage__lede">{lede}</div> : null}
            {meta ? <div className="llmwikibook-stage__meta">{meta}</div> : null}
          </div>
          {toolbar ? <div className="llmwikibook-stage__toolbar">{toolbar}</div> : null}
        </header>
      ) : null}
      {hero ? <div className="llmwikibook-stage__hero">{hero}</div> : null}
      {children ? <div className="llmwikibook-stage__body">{children}</div> : null}
      {footer ? <footer className="llmwikibook-stage__footer">{footer}</footer> : null}
    </Component>
  );
}
