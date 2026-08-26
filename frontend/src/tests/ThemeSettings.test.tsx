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
    expect(screen.getByText('Arctic Frost')).toBeInTheDocument();
    expect(screen.getByText('Solar Daybreak')).toBeInTheDocument();

    const deepOceanRadio = screen.getByRole('radio', { name: /Select Deep Ocean theme/i });
    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });
    const arcticRadio = screen.getByRole('radio', { name: /Select Arctic Frost theme/i });
    const solarRadio = screen.getByRole('radio', { name: /Select Solar Daybreak theme/i });

    expect(deepOceanRadio).toHaveAttribute('aria-checked', 'true');
    expect(midnightRadio).toHaveAttribute('aria-checked', 'false');
    expect(arcticRadio).toHaveAttribute('aria-checked', 'false');
    expect(solarRadio).toHaveAttribute('aria-checked', 'false');
  });

  it('switches theme to Arctic Frost on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const arcticRadio = screen.getByRole('radio', { name: /Select Arctic Frost theme/i });
    fireEvent.click(arcticRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('arctic-frost');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('arctic-frost');
    expect(arcticRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('switches theme to Solar Daybreak on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const solarRadio = screen.getByRole('radio', { name: /Select Solar Daybreak theme/i });
    fireEvent.click(solarRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('solar-daybreak');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('solar-daybreak');
    expect(solarRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('loads saved theme from localStorage on initial render', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'arctic-frost');

    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const arcticRadio = screen.getByRole('radio', { name: /Select Arctic Frost theme/i });
    expect(arcticRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('getSavedTheme and applyTheme utility functions handle storage correctly', () => {
    expect(getSavedTheme()).toBe('deep-ocean');

    applyTheme('arctic-frost');
    expect(getSavedTheme()).toBe('arctic-frost');
    expect(document.documentElement.getAttribute('data-theme')).toBe('arctic-frost');

    applyTheme('solar-daybreak');
    expect(getSavedTheme()).toBe('solar-daybreak');
    expect(document.documentElement.getAttribute('data-theme')).toBe('solar-daybreak');

    applyTheme('midnight-blue');
    expect(getSavedTheme()).toBe('midnight-blue');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-blue');

    applyTheme('deep-ocean');
    expect(getSavedTheme()).toBe('deep-ocean');
    expect(document.documentElement.getAttribute('data-theme')).toBe('deep-ocean');
  });
});
