export type ThemeId = 'deep-ocean' | 'midnight-blue' | 'lavender-haze' | 'amber-warmth' | 'aqua-breeze' | 'azure-daylight' | 'arctic-frost' | 'solar-daybreak';

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
    id: 'lavender-haze',
    name: 'Lavender Haze',
    mode: 'light',
    description: 'Elegant soft violet canvas with vibrant purple, fuchsia accents, and plum text.',
    swatches: ['#f5f3ff', '#faf8ff', '#7c3aed', '#ec4899'],
  },
  {
    id: 'amber-warmth',
    name: 'Amber Warmth',
    mode: 'light',
    description: 'Warm sandstone canvas with terracotta orange, amber accents, and espresso text.',
    swatches: ['#fdf8f4', '#ffffff', '#ea580c', '#d97706'],
  },
];

export function getSavedTheme(): ThemeId {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY) as ThemeId | null;
    if (saved === 'arctic-frost' || saved === 'aqua-breeze') return 'lavender-haze';
    if (saved === 'solar-daybreak' || saved === 'azure-daylight') return 'amber-warmth';
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
