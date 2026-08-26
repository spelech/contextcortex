export type ThemeId = 'deep-ocean' | 'midnight-blue' | 'aqua-breeze' | 'azure-daylight' | 'arctic-frost' | 'solar-daybreak';

export interface ThemeOption {
  id: ThemeId;
  name: string;
  mode: 'dark' | 'light';
  description: string;
  swatches: string[];
}

export const THEME_STORAGE_KEY = 'contextcortex_theme';
export const DEFAULT_THEME: ThemeId = 'deep-ocean';

export const AVAILABLE_THEMES: ThemeOption[] = [
  {
    id: 'deep-ocean',
    name: 'Deep Ocean',
    mode: 'dark',
    description: 'Monochromatic petrol slate with vibrant cyan and mint accents.',
    swatches: ['#07181b', '#0d2c2f', '#0891b2', '#2dd4bf'],
  },
  {
    id: 'midnight-blue',
    name: 'Midnight Blue',
    mode: 'dark',
    description: 'Classic deep space navy with cobalt blue and teal highlights.',
    swatches: ['#0a0f1d', '#121a2f', '#3b82f6', '#14b8a6'],
  },
  {
    id: 'aqua-breeze',
    name: 'Aqua Breeze',
    mode: 'light',
    description: 'Refreshing aquamarine with vibrant cyan accents and deep petrol text.',
    swatches: ['#e1f2f5', '#f2fafb', '#0891b2', '#0d9488'],
  },
  {
    id: 'azure-daylight',
    name: 'Azure Daylight',
    mode: 'light',
    description: 'Crisp sky blue with cobalt royal blue and indigo highlights.',
    swatches: ['#e8effe', '#f5f8ff', '#2563eb', '#4f46e5'],
  },
];

export function getSavedTheme(): ThemeId {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY) as ThemeId | null;
    if (saved === 'arctic-frost') return 'aqua-breeze';
    if (saved === 'solar-daybreak') return 'azure-daylight';
    if (saved && AVAILABLE_THEMES.some((t) => t.id === saved)) {
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
