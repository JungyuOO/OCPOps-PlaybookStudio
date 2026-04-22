import clsx from 'clsx';
import type { ReactNode } from 'react';

export type LlmWikiBookCardTone = 'default' | 'muted' | 'accent';

export interface LlmWikiBookSectionCardProps {
  className?: string;
  eyebrow?: string;
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  tone?: LlmWikiBookCardTone;
  compact?: boolean;
}

export function LlmWikiBookSectionCard({
  className,
  eyebrow,
  title,
  description,
  actions,
  footer,
  children,
  tone = 'default',
  compact = false,
}: LlmWikiBookSectionCardProps) {
  return (
    <section
      className={clsx(
        'llmwikibook-card',
        compact && 'is-compact',
        className,
      )}
      data-tone={tone}
    >
      {eyebrow || title || description || actions ? (
        <header className="llmwikibook-card__header">
          <div className="llmwikibook-card__copy">
            {eyebrow ? <div className="llmwikibook-card__eyebrow">{eyebrow}</div> : null}
            {title ? <h2 className="llmwikibook-card__title">{title}</h2> : null}
            {description ? <div className="llmwikibook-card__description">{description}</div> : null}
          </div>
          {actions ? <div className="llmwikibook-card__actions">{actions}</div> : null}
        </header>
      ) : null}
      {children ? <div className="llmwikibook-card__body">{children}</div> : null}
      {footer ? <footer className="llmwikibook-card__footer">{footer}</footer> : null}
    </section>
  );
}
