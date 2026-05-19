import { useCallback, useEffect, useState } from 'react';

export type GlobalTheme = 'dark' | 'light';

const GLOBAL_THEME_STORAGE_KEY = 'pbs.globalTheme';

function normalizeGlobalTheme(value: string | null): GlobalTheme | null {
  return value === 'dark' || value === 'light' ? value : null;
}

function readInitialGlobalTheme(): GlobalTheme {
  if (typeof window === 'undefined') {
    return 'dark';
  }
  return normalizeGlobalTheme(window.localStorage.getItem(GLOBAL_THEME_STORAGE_KEY))
    ?? normalizeGlobalTheme(document.documentElement.getAttribute('data-theme'))
    ?? 'dark';
}

export function useGlobalTheme() {
  const [globalTheme, setGlobalTheme] = useState<GlobalTheme>(readInitialGlobalTheme);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    document.documentElement.setAttribute('data-theme', globalTheme);
    window.localStorage.setItem(GLOBAL_THEME_STORAGE_KEY, globalTheme);
  }, [globalTheme]);

  const toggleGlobalTheme = useCallback(() => {
    setGlobalTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return { globalTheme, setGlobalTheme, toggleGlobalTheme };
}
