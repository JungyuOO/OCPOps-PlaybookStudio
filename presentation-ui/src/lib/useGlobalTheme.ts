import { useCallback, useEffect, useState } from 'react';

export type GlobalTheme = 'dark' | 'light';

const THEME_STORAGE_KEY = 'pbs.globalTheme';

function readStoredTheme(): GlobalTheme {
  if (typeof window === 'undefined') {
    return 'dark';
  }
  return window.localStorage.getItem(THEME_STORAGE_KEY) === 'light' ? 'light' : 'dark';
}

export function applyGlobalTheme(theme: GlobalTheme): void {
  if (typeof window === 'undefined') {
    return;
  }
  document.documentElement.setAttribute('data-theme', theme);
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
}

export function useGlobalTheme(): [GlobalTheme, () => void] {
  const [theme, setTheme] = useState<GlobalTheme>(readStoredTheme);

  useEffect(() => {
    applyGlobalTheme(theme);
  }, [theme]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) {
        setTheme(event.newValue === 'light' ? 'light' : 'dark');
      }
    };

    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return [theme, toggleTheme];
}
