import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ThemeSettings } from '../components/settings/ThemeSettings';
import { ToastProvider } from '../ToastContext';
import { getSavedTheme, applyTheme, THEME_STORAGE_KEY } from '../theme';

describe('ThemeSettings Component & theme utilities', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    vi.restoreAllMocks();
  });

  it('renders theme options with Deep Ocean as default when no storage exists', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    expect(screen.getByText('Appearance & Theme')).toBeInTheDocument();
    expect(screen.getByText('Deep Ocean')).toBeInTheDocument();
    expect(screen.getByText('Midnight Blue')).toBeInTheDocument();
    expect(screen.getByText('Lavender Haze')).toBeInTheDocument();
    expect(screen.getByText('Amber Warmth')).toBeInTheDocument();

    const deepOceanRadio = screen.getByRole('radio', { name: /Select Deep Ocean theme/i });
    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });
    const lavenderRadio = screen.getByRole('radio', { name: /Select Lavender Haze theme/i });
    const amberRadio = screen.getByRole('radio', { name: /Select Amber Warmth theme/i });

    expect(deepOceanRadio).toHaveAttribute('aria-checked', 'true');
    expect(midnightRadio).toHaveAttribute('aria-checked', 'false');
    expect(lavenderRadio).toHaveAttribute('aria-checked', 'false');
    expect(amberRadio).toHaveAttribute('aria-checked', 'false');
  });

  it('switches theme to Lavender Haze on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const lavenderRadio = screen.getByRole('radio', { name: /Select Lavender Haze theme/i });
    fireEvent.click(lavenderRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('lavender-haze');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('lavender-haze');
    expect(lavenderRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('switches theme to Amber Warmth on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const amberRadio = screen.getByRole('radio', { name: /Select Amber Warmth theme/i });
    fireEvent.click(amberRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('amber-warmth');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('amber-warmth');
    expect(amberRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('loads saved theme from localStorage on initial render', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'lavender-haze');

    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const lavenderRadio = screen.getByRole('radio', { name: /Select Lavender Haze theme/i });
    expect(lavenderRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('getSavedTheme and applyTheme utility functions handle storage correctly', () => {
    expect(getSavedTheme()).toBe('deep-ocean');

    applyTheme('lavender-haze');
    expect(getSavedTheme()).toBe('lavender-haze');
    expect(document.documentElement.getAttribute('data-theme')).toBe('lavender-haze');

    applyTheme('amber-warmth');
    expect(getSavedTheme()).toBe('amber-warmth');
    expect(document.documentElement.getAttribute('data-theme')).toBe('amber-warmth');

    applyTheme('midnight-blue');
    expect(getSavedTheme()).toBe('midnight-blue');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-blue');

    applyTheme('deep-ocean');
    expect(getSavedTheme()).toBe('deep-ocean');
    expect(document.documentElement.getAttribute('data-theme')).toBe('deep-ocean');
  });
});
