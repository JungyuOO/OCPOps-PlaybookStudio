import { Moon, Sun } from 'lucide-react';
import type { GlobalTheme } from '../lib/useGlobalTheme';
import './GlobalThemeToggle.css';

type GlobalThemeToggleProps = {
  theme: GlobalTheme;
  onToggle: () => void;
  className?: string;
};

export default function GlobalThemeToggle({ theme, onToggle, className = '' }: GlobalThemeToggleProps) {
  const isLight = theme === 'light';

  return (
    <button
      className={`global-theme-toggle ${className}`.trim()}
      type="button"
      onClick={onToggle}
      aria-label={isLight ? '다크 테마로 전환' : '라이트 테마로 전환'}
      aria-pressed={isLight}
      title={isLight ? 'Dark mode' : 'Light mode'}
    >
      <span className="global-theme-toggle-track" aria-hidden="true">
        <span className="global-theme-toggle-thumb">
          {isLight ? <Sun size={14} /> : <Moon size={14} />}
        </span>
      </span>
      <span className="global-theme-toggle-label">{isLight ? 'Light' : 'Dark'}</span>
    </button>
  );
}
