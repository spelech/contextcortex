import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Stats } from '../types';

const mockStats: Stats = {
  repos_count: 2,
  symbols_count: 100,
  files_count: 5,
  points_count: 200,
  last_indexed: '2026-08-17',
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****5678'
};

describe('Settings Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders active token source and masked token', () => {
    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('GitHub Authentication & Rate Limits')).toBeInTheDocument();
    expect(screen.getByText('Database')).toBeInTheDocument();
    expect(screen.getByText('ghp_****5678')).toBeInTheDocument();
  });

  it('saves new GitHub token and refreshes stats', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'success' })
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const tokenInput = screen.getByPlaceholderText(/ghp_xxxx/i);
    fireEvent.change(tokenInput, { target: { value: 'ghp_newtoken123456789' } });

    const saveBtn = screen.getByRole('button', { name: /Save Token to DB/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ github_token: 'ghp_newtoken123456789' })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText('GitHub Token saved successfully.')).toBeInTheDocument();
    });
  });

  it('clears GitHub token after confirmation', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'cleared' })
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const clearBtn = screen.getByRole('button', { name: /Clear Token/i });
    fireEvent.click(clearBtn);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ github_token: '' })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText('GitHub token cleared')).toBeInTheDocument();
    });
  });

  it('handles cancellation and errors during token save and clear', async () => {
    // 1. Cancel clear token
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const clearBtn = screen.getByRole('button', { name: /Clear Token/i });
    fireEvent.click(clearBtn);
    expect(window.confirm).toHaveBeenCalled();

    // 2. Error saving token
    (globalThis as any).fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'Invalid token format' })
    });

    const tokenInput = screen.getByPlaceholderText(/ghp_xxxx/i);
    fireEvent.change(tokenInput, { target: { value: 'bad_token' } });

    const saveBtn = screen.getByRole('button', { name: /Save Token to DB/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText(/Error saving token: Invalid token format/i)).toBeInTheDocument();
    });

    // 3. Error clearing token
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'Database locked' })
    });

    fireEvent.click(clearBtn);
    await waitFor(() => {
      expect(screen.getByText(/Failed to clear token: Database locked/i)).toBeInTheDocument();
    });
  });
});
