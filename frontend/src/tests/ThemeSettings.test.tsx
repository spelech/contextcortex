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
    expect(screen.getByText('Aqua Breeze')).toBeInTheDocument();
    expect(screen.getByText('Azure Daylight')).toBeInTheDocument();

    const deepOceanRadio = screen.getByRole('radio', { name: /Select Deep Ocean theme/i });
    const midnightRadio = screen.getByRole('radio', { name: /Select Midnight Blue theme/i });
    const aquaRadio = screen.getByRole('radio', { name: /Select Aqua Breeze theme/i });
    const azureRadio = screen.getByRole('radio', { name: /Select Azure Daylight theme/i });

    expect(deepOceanRadio).toHaveAttribute('aria-checked', 'true');
    expect(midnightRadio).toHaveAttribute('aria-checked', 'false');
    expect(aquaRadio).toHaveAttribute('aria-checked', 'false');
    expect(azureRadio).toHaveAttribute('aria-checked', 'false');
  });

  it('switches theme to Aqua Breeze on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const aquaRadio = screen.getByRole('radio', { name: /Select Aqua Breeze theme/i });
    fireEvent.click(aquaRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('aqua-breeze');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('aqua-breeze');
    expect(aquaRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('switches theme to Azure Daylight on click and updates localStorage and documentElement', () => {
    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const azureRadio = screen.getByRole('radio', { name: /Select Azure Daylight theme/i });
    fireEvent.click(azureRadio);

    expect(document.documentElement.getAttribute('data-theme')).toBe('azure-daylight');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('azure-daylight');
    expect(azureRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('loads saved theme from localStorage on initial render', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'aqua-breeze');

    render(
      <ToastProvider>
        <ThemeSettings />
      </ToastProvider>
    );

    const aquaRadio = screen.getByRole('radio', { name: /Select Aqua Breeze theme/i });
    expect(aquaRadio).toHaveAttribute('aria-checked', 'true');
  });

  it('getSavedTheme and applyTheme utility functions handle storage correctly', () => {
    expect(getSavedTheme()).toBe('deep-ocean');

    applyTheme('aqua-breeze');
    expect(getSavedTheme()).toBe('aqua-breeze');
    expect(document.documentElement.getAttribute('data-theme')).toBe('aqua-breeze');

    applyTheme('azure-daylight');
    expect(getSavedTheme()).toBe('azure-daylight');
    expect(document.documentElement.getAttribute('data-theme')).toBe('azure-daylight');

    applyTheme('midnight-blue');
    expect(getSavedTheme()).toBe('midnight-blue');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-blue');

    applyTheme('deep-ocean');
    expect(getSavedTheme()).toBe('deep-ocean');
    expect(document.documentElement.getAttribute('data-theme')).toBe('deep-ocean');
  });
});
