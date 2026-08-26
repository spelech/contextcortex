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

    const deepOceanRadio = screen.getByRole('radio', { name: /Select Deep Ocean theme/i });
    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });

    expect(deepOceanRadio).toHaveAttribute('aria-checked', 'true');
    expect(midnightRadio).toHaveAttribute('aria-checked', 'false');
  });

  it('switches theme to Midnight Blue on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });
    fireEvent.click(midnightRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-blue');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('midnight-blue');
    expect(midnightRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('loads saved theme from localStorage on initial render', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'midnight-blue');

    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });
    expect(midnightRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('getSavedTheme and applyTheme utility functions handle storage correctly', () => {
    expect(getSavedTheme()).toBe('deep-ocean');

    applyTheme('midnight-blue');
    expect(getSavedTheme()).toBe('midnight-blue');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-blue');

    applyTheme('deep-ocean');
    expect(getSavedTheme()).toBe('deep-ocean');
    expect(document.documentElement.getAttribute('data-theme')).toBe('deep-ocean');
  });
});
