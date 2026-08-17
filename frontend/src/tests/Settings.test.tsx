import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Stats, GitHostCredential } from '../types';

const mockStats: Stats = {
  repos_count: 2,
  symbols_count: 100,
  files_count: 5,
  points_count: 200,
  last_indexed: '2026-08-17',
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****5678',
  rate_limit: { remaining: 4950, limit: 5000 },
  providers_auth: {
    github: { token_source: 'Database', masked_token: 'ghp_****5678' },
    gitlab: { token_source: 'Environment', masked_token: 'glpat_****4321' },
    gitea: { token_source: 'Database', masked_token: 'gitea_****9876' }
  }
};

const mockHostCreds: GitHostCredential[] = [
  {
    id: 1,
    host: 'gitlab.enterprise.internal',
    provider: 'gitlab',
    auth_user: 'gitlab-ci-token',
    masked_token: 'glpa...9999',
    added_at: '2026-08-17 12:00:00'
  },
  {
    id: 2,
    host: 'http://git.lan:3000',
    provider: 'gitea',
    auth_user: undefined,
    masked_token: 'gt_s...1111',
    added_at: '2026-08-17 12:05:00'
  }
];

describe('Settings Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders multi-provider token boxes, rate limits, and host vault list', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockHostCreds
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
    expect(screen.getByText('Custom & Self-Hosted Git Host Vault')).toBeInTheDocument();
    expect(screen.getByText('ghp_****5678')).toBeInTheDocument();
    expect(screen.getByText('glpat_****4321')).toBeInTheDocument();
    expect(screen.getByText('gitea_****9876')).toBeInTheDocument();
    expect(screen.getByText(/4950 \/ 5000 requests/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('gitlab.enterprise.internal')).toBeInTheDocument();
      expect(screen.getByText('http://git.lan:3000')).toBeInTheDocument();
      expect(screen.getByText('gitlab-ci-token')).toBeInTheDocument();
      expect(screen.getByText('Default')).toBeInTheDocument();
    });
  });

  it('handles empty stats or fallback provider auth structure', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => []
    });

    render(
      <ToastProvider>
        <Settings stats={null} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
  });

  it('saves new tokens for GitHub, GitLab, and Gitea', async () => {
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

    const saveBtns = screen.getAllByRole('button', { name: /^Save$/i });

    // 1. Save empty (guard branch)
    fireEvent.click(saveBtns[0]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1); // Only initial loadHostCredentials

    // 2. Save GitHub token
    const ghInput = screen.getByPlaceholderText(/ghp_xxxx/i);
    fireEvent.change(ghInput, { target: { value: 'ghp_newtoken123' } });
    fireEvent.click(saveBtns[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ github_token: 'ghp_newtoken123' })
        })
      );
    });

    // 3. Save GitLab token
    const glInput = screen.getByPlaceholderText(/glpat-xxxx/i);
    fireEvent.change(glInput, { target: { value: 'glpat_newtoken456' } });
    fireEvent.click(saveBtns[1]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ gitlab_token: 'glpat_newtoken456' })
        })
      );
    });

    // 4. Save Gitea token
    const gtInput = screen.getByPlaceholderText(/Token \/ Personal Token/i);
    fireEvent.change(gtInput, { target: { value: 'gitea_newtoken789' } });
    fireEvent.click(saveBtns[2]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ gitea_token: 'gitea_newtoken789' })
        })
      );
    });

    expect(refreshStats).toHaveBeenCalledTimes(3);
  });

  it('handles error saving token', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Invalid token format' })
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const ghInput = screen.getByPlaceholderText(/ghp_xxxx/i);
    fireEvent.change(ghInput, { target: { value: 'invalid_tok' } });

    const saveBtns = screen.getAllByRole('button', { name: /^Save$/i });
    fireEvent.click(saveBtns[0]);

    await waitFor(() => {
      expect(screen.getByText(/Error saving GitHub token: Invalid token format/i)).toBeInTheDocument();
    });
  });

  it('clears tokens with confirmation and handles cancellation / clear errors', async () => {
    const refreshStats = vi.fn();
    
    // 1. Cancel clear
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const clearBtns = screen.getAllByRole('button', { name: /^Clear$/i });
    fireEvent.click(clearBtns[0]);
    expect(window.confirm).toHaveBeenCalled();
    expect(refreshStats).not.toHaveBeenCalled();

    // 2. Confirm clear GitLab token
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'cleared' })
    });

    fireEvent.click(clearBtns[1]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ gitlab_token: '' })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
    });

    // 3. Clear Gitea token error
    (globalThis as any).fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'Database error' })
    });

    fireEvent.click(clearBtns[2]);

    await waitFor(() => {
      expect(screen.getByText(/Failed to clear Gitea token: Database error/i)).toBeInTheDocument();
    });
  });

  it('manages Custom Git Host Credential modal and saves new credentials', async () => {
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

    // Test close button
    const closeBtn = screen.getByRole('button', { name: '×' });
    fireEvent.click(closeBtn);
    expect(screen.queryByRole('heading', { name: /Add Host Credential/i })).not.toBeInTheDocument();

    // Reopen
    fireEvent.click(addHostBtn);

    // Fill form
    const hostInput = screen.getByPlaceholderText(/gitlab\.mycorp\.internal/i);
    const userInput = screen.getByPlaceholderText(/oauth2 or gitlab-ci-token/i);
    const tokenInput = screen.getByPlaceholderText(/Token or password/i);
    const providerSelect = screen.getByLabelText(/Provider Type/i);

    fireEvent.change(hostInput, { target: { value: 'gitea.corp.lan:3000' } });
    fireEvent.change(providerSelect, { target: { value: 'gitea' } });
    fireEvent.change(userInput, { target: { value: 'gituser' } });
    fireEvent.change(tokenInput, { target: { value: 'gitea_secret_token' } });

    const submitBtn = screen.getByRole('button', { name: /Save Host Credential/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/hosts',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            host: 'gitea.corp.lan:3000',
            provider: 'gitea',
            auth_user: 'gituser',
            auth_token: 'gitea_secret_token'
          })
        })
      );
      expect(screen.getByText("Host credential for 'gitea.corp.lan:3000' saved")).toBeInTheDocument();
    });
  });

  it('handles host credential modal cancel and validation error', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Host already exists' })
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

    // Cancel button
    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);
    expect(screen.queryByRole('heading', { name: /Add Host Credential/i })).not.toBeInTheDocument();

    // Reopen and trigger API error
    fireEvent.click(addHostBtn);
    const hostInput = screen.getByPlaceholderText(/gitlab\.mycorp\.internal/i);
    const tokenInput = screen.getByPlaceholderText(/Token or password/i);
    fireEvent.change(hostInput, { target: { value: 'dup.host.com' } });
    fireEvent.change(tokenInput, { target: { value: 'tok' } });

    const submitBtn = screen.getByRole('button', { name: /Save Host Credential/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Error: Host already exists/i)).toBeInTheDocument();
    });
  });

  it('deletes host credential and handles cancellation / delete error', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockHostCreds
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('gitlab.enterprise.internal')).toBeInTheDocument();
    });

    const deleteBtns = screen.getAllByTitle(/Delete Credential/i);

    // 1. Cancel deletion
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(deleteBtns[0]);
    expect(window.confirm).toHaveBeenCalled();

    // 2. Confirm deletion
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'success' }) });
      }
      return Promise.resolve({ ok: true, json: async () => [mockHostCreds[1]] });
    });

    fireEvent.click(deleteBtns[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/settings/hosts/1', { method: 'DELETE' });
      expect(screen.getByText("Removed credentials for 'gitlab.enterprise.internal'")).toBeInTheDocument();
    });

    // 3. Delete error on second item
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'DELETE') {
        return Promise.resolve({ ok: false, json: async () => ({ error: 'Permission denied' }) });
      }
      return Promise.resolve({ ok: true, json: async () => [mockHostCreds[1]] });
    });

    const remainingDeleteBtn = screen.getByTitle(/Delete Credential/i);
    fireEvent.click(remainingDeleteBtn);

    await waitFor(() => {
      expect(screen.getByText(/Failed to remove: Permission denied/i)).toBeInTheDocument();
    });
  });

  it('handles loadHostCredentials network failure gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    (globalThis as any).fetch = vi.fn().mockRejectedValue(new Error('Network offline'));

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load host credentials:', expect.any(Error));
      expect(screen.getByText(/No custom host credentials configured/i)).toBeInTheDocument();
    });
    consoleSpy.mockRestore();
  });
});
