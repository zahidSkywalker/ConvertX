/**
 * Theme Management — Dark/Light mode toggle with localStorage persistence.
 * Updates CSS variables and the PWA meta theme-color dynamically.
 */

const STORAGE_KEY = 'convertx-theme';
const META_TAG_ID = 'meta-theme';

type Theme = 'dark' | 'light';

export function initTheme(): void {
  const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initialTheme = saved || (prefersDark ? 'dark' : 'light');
  
  applyTheme(initialTheme);

  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') as Theme;
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem(STORAGE_KEY, next);
    });
  }
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme);
  
  // Update PWA status bar color for mobile browsers
  const meta = document.getElementById(META_TAG_ID) as HTMLMetaElement | null;
  if (meta) {
    meta.content = theme === 'dark' ? '#0f172a' : '#f1f5f9';
  }
}
