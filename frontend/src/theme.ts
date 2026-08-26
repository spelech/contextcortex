export type ThemeId = 'deep-ocean' | 'midnight-blue';

export interface ThemeOption {
  id: ThemeId;
  name: string;
  description: string;
  swatches: string[];
}

export const THEME_STORAGE_KEY = 'contextcortex_theme';
export const DEFAULT_THEME: ThemeId = 'deep-ocean';

export const AVAILABLE_THEMES: ThemeOption[] = [
  {
    id: 'deep-ocean',
    name: 'Deep Ocean',
    description: 'Monochromatic petrol slate with vibrant cyan and mint accents.',
    swatches: ['#07181b', '#0d2c2f', '#0891b2', '#2dd4bf'],
  },
  {
    id: 'midnight-blue',
    name: 'Midnight Blue',
    description: 'Classic deep space navy with cobalt blue and teal highlights.',
    swatches: ['#0a0f1d', '#121a2f', '#3b82f6', '#14b8a6'],
  },
];

export function getSavedTheme(): ThemeId {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === 'midnight-blue' || saved === 'deep-ocean') {
      return saved;
    }
  } catch (_e) {
    // LocalStorage might be restricted
  }
  return DEFAULT_THEME;
}

export function applyTheme(themeId: ThemeId): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', themeId);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, themeId);
  } catch (_e) {
    // LocalStorage might be restricted
  }
}
