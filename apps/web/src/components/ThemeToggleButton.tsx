import { Moon, Sun } from 'lucide-react';
import type { GlobalTheme } from '../lib/globalTheme';

type ThemeToggleButtonProps = {
  className?: string;
  globalTheme: GlobalTheme;
  onToggleGlobalTheme: () => void;
};

export default function ThemeToggleButton({
  className,
  globalTheme,
  onToggleGlobalTheme,
}: ThemeToggleButtonProps) {
  return (
    <button
      aria-label="Toggle Dark/Light Mode"
      className={className}
      onClick={onToggleGlobalTheme}
      title="Toggle Dark/Light Mode"
      type="button"
    >
      {globalTheme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
