import clsx from 'clsx';
import type { CSSProperties, ReactNode } from 'react';

export interface LlmWikiBookNavItem {
  id: string;
  label: string;
  summary?: string;
  meta?: string;
  badge?: string;
  active?: boolean;
  dimmed?: boolean;
  depth?: number;
  trailing?: ReactNode;
}

export interface LlmWikiBookNavListProps {
  className?: string;
  items: LlmWikiBookNavItem[];
  ariaLabel?: string;
  dense?: boolean;
  onItemSelect?: (item: LlmWikiBookNavItem) => void;
}

export function LlmWikiBookNavList({
  className,
  items,
  ariaLabel,
  dense = false,
  onItemSelect,
}: LlmWikiBookNavListProps) {
  return (
    <div className={clsx('llmwikibook-nav', dense && 'is-dense', className)} role="list" aria-label={ariaLabel}>
      {items.map((item) => {
        const style = {
          '--llmwikibook-nav-depth': String(item.depth ?? 0),
        } as CSSProperties;

        if (onItemSelect) {
          return (
            <button
              key={item.id}
              type="button"
              className={clsx(
                'llmwikibook-nav__item',
                item.active && 'is-active',
                item.dimmed && 'is-dimmed',
              )}
              style={style}
              onClick={() => onItemSelect(item)}
            >
              <NavItemBody item={item} />
            </button>
          );
        }

        return (
          <div
            key={item.id}
            className={clsx(
              'llmwikibook-nav__item',
              item.active && 'is-active',
              item.dimmed && 'is-dimmed',
            )}
            style={style}
            role="listitem"
          >
            <NavItemBody item={item} />
          </div>
        );
      })}
    </div>
  );
}

function NavItemBody({ item }: { item: LlmWikiBookNavItem }) {
  return (
    <>
      <div className="llmwikibook-nav__copy">
        <span className="llmwikibook-nav__label-row">
          <span className="llmwikibook-nav__label">{item.label}</span>
          {item.badge ? <span className="llmwikibook-nav__badge">{item.badge}</span> : null}
        </span>
        {item.summary ? <span className="llmwikibook-nav__summary">{item.summary}</span> : null}
      </div>
      {item.meta || item.trailing ? (
        <span className="llmwikibook-nav__meta-cluster">
          {item.meta ? <span className="llmwikibook-nav__meta">{item.meta}</span> : null}
          {item.trailing ? <span className="llmwikibook-nav__trailing">{item.trailing}</span> : null}
        </span>
      ) : null}
    </>
  );
}
