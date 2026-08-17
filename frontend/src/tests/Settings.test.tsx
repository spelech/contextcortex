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
  masked_token: 'ghp_****5678',
  providers_auth: {
    github: { token_source: 'Database', masked_token: 'ghp_****5678' },
    gitlab: { token_source: 'None', masked_token: 'None' },
    gitea: { token_source: 'None', masked_token: 'None' }
  }
};

describe('Settings Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders multi-provider token boxes and vault manager', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => []
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
    expect(screen.getByText('Custom & Self-Hosted Git Host Vault')).toBeInTheDocument();
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

    const tokenInputs = screen.getAllByPlaceholderText(/ghp_xxxx/i);
    fireEvent.change(tokenInputs[0], { target: { value: 'ghp_newtoken123456789' } });

    const saveBtns = screen.getAllByRole('button', { name: /^Save$/i });
    fireEvent.click(saveBtns[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ github_token: 'ghp_newtoken123456789' })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
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

    const clearBtns = screen.getAllByRole('button', { name: /^Clear$/i });
    fireEvent.click(clearBtns[0]);

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
    });
  });

  it('opens host credential modal and saves custom host credentials', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success' })
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => []
      });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const addHostBtn = screen.getByRole('button', { name: /Add Host Credential/i });
    fireEvent.click(addHostBtn);

    expect(screen.getByRole('heading', { name: /Add Host Credential/i })).toBeInTheDocument();

    const hostInput = screen.getByPlaceholderText(/gitlab\.mycorp\.internal/i);
    const tokenInput = screen.getByPlaceholderText(/Token or password/i);

    fireEvent.change(hostInput, { target: { value: 'gitlab.enterprise.corp' } });
    fireEvent.change(tokenInput, { target: { value: 'glpat_secret999' } });

    const submitBtn = screen.getByRole('button', { name: /Save Host Credential/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/hosts',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            host: 'gitlab.enterprise.corp',
            provider: 'gitlab',
            auth_user: null,
            auth_token: 'glpat_secret999'
          })
        })
      );
    });
  });
});
