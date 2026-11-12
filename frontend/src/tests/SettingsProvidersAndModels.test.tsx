import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  installDefaultSettingsFetchMocks,
  mockAutoSyncSettings,
  mockEmbeddingConfig,
  mockHostCreds,
  mockStats,
  mockVectorStoreConfig,
} from './fixtures/settingsFixtures';

describe('Settings Git Providers, Host Vault & Embedding Models', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('saves new tokens for GitHub, GitLab, and Gitea', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'success' }) });
      }
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => mockHostCreds });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument();
    });

    const saveBtns = screen.getAllByRole('button', { name: /^Save$/i });

    // 1. Save empty (guard branch)
    fireEvent.click(saveBtns[0]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(6);

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
      expect(screen.getByText('GitHub token saved successfully.')).toBeInTheDocument();
      expect(refreshStats).toHaveBeenCalled();
    });

    // 3. Save GitLab token
    const glInput = screen.getByPlaceholderText(/glpat-xxxx/i);
    fireEvent.change(glInput, { target: { value: 'glpat_test999' } });
    fireEvent.click(saveBtns[1]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ gitlab_token: 'glpat_test999' })
        })
      );
      expect(screen.getByText('GitLab token saved successfully.')).toBeInTheDocument();
    });

    // 4. Save Gitea token
    const gtInput = screen.getByPlaceholderText(/Token \/ Personal Token/i);
    fireEvent.change(gtInput, { target: { value: 'gitea_tok_555' } });
    fireEvent.click(saveBtns[2]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ gitea_token: 'gitea_tok_555' })
        })
      );
      expect(screen.getByText('Gitea token saved successfully.')).toBeInTheDocument();
    });
  });

  it('handles token save failures gracefully', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({ ok: false, json: async () => ({ error: 'Invalid token format' }) });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const ghInput = screen.getByPlaceholderText(/ghp_xxxx/i);
    const saveBtns = screen.getAllByRole('button', { name: /^Save$/i });
    fireEvent.change(ghInput, { target: { value: 'invalid_token' } });
    fireEvent.click(saveBtns[0]);

    await waitFor(() => {
      expect(screen.getByText(/Error saving GitHub token: Invalid token format/i)).toBeInTheDocument();
    });
  });

  it('clears tokens with confirmation', async () => {
    const refreshStats = vi.fn();
    installDefaultSettingsFetchMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const clearBtns = screen.getAllByRole('button', { name: /^Clear$/i });

    // Cancel confirmation
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(clearBtns[0]);
    expect(window.confirm).toHaveBeenCalled();

    // Confirm clear GitHub token
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'cleared' })
    });

    fireEvent.click(clearBtns[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/token',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ github_token: '' })
        })
      );
      expect(screen.getByText('GitHub token cleared')).toBeInTheDocument();
      expect(refreshStats).toHaveBeenCalled();
    });
  });

  it('opens host modal, creates new credential, and handles cancel & duplicate error', async () => {
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
    installDefaultSettingsFetchMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('gitlab.enterprise.internal')[0]).toBeInTheDocument();
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

    const remainingDeleteBtn = screen.getAllByTitle(/Delete Credential/i)[0];
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
      expect(screen.getAllByText(/No custom host credentials configured/i)[0]).toBeInTheDocument();
    });
    consoleSpy.mockRestore();
  });

  it('renders responsive mobile card list for host credentials and handles mobile deletion', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts' && opts?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'success' }) });
      }
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => mockHostCreds });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    const { container } = render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('gitlab.enterprise.internal')[0]).toBeInTheDocument();
    });

    const vsLayout = container.querySelector('.vs-config-layout');
    expect(vsLayout).toBeInTheDocument();

    const mobileCards = container.querySelectorAll('.mobile-card-list .data-mobile-card');
    expect(mobileCards.length).toBe(2);
    const deleteBtn = mobileCards[0].querySelector('.btn-delete') as HTMLElement;
    expect(deleteBtn).toBeInTheDocument();
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/settings/hosts/1', { method: 'DELETE' });
    });
  });

  it('renders embedding engine settings panel with current CPU threads, batch size, and system hardware', async () => {
    installDefaultSettingsFetchMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Embedding Engine & Resource Limits')).toBeInTheDocument();
    expect(screen.getByText('Active Embedding Engine')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Remote API (LiteLLM)')).toBeInTheDocument();
      expect(screen.getByText(/2 Cores \(of 8 detected\)/i)).toBeInTheDocument();
      expect(screen.getByText('32 chunks/batch')).toBeInTheDocument();
      expect(screen.getByText('16 GB')).toBeInTheDocument();
    });
  });

  it('updates thread cap and batch size and saves embedding settings', async () => {
    installDefaultSettingsFetchMocks();
    const refreshStats = vi.fn();

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync') return Promise.resolve({ ok: true, json: async () => mockAutoSyncSettings });
      if (url === '/admin/api/settings/embedding' && opts?.method === 'POST') {
        const body = JSON.parse(opts.body);
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            config: { ...mockEmbeddingConfig, provider: 'api', threads: body.threads, batch_size: body.batch_size }
          })
        });
      }
      if (url === '/admin/api/settings/embedding') {
        return Promise.resolve({ ok: true, json: async () => mockEmbeddingConfig });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/CPU Thread Cap/i)).toHaveValue(2);
    });

    const threadInput = screen.getByLabelText(/CPU Thread Cap/i);
    const batchSelect = screen.getByLabelText(/Embedding Batch Size/i);

    fireEvent.change(threadInput, { target: { value: '4' } });
    fireEvent.change(batchSelect, { target: { value: '64' } });

    const saveBtn = screen.getByRole('button', { name: /Save & Apply Embedding Limits/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/embedding',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            provider: 'api',
            threads: 4,
            batch_size: 64,
            dense_model: 'BAAI/bge-small-en-v1.5',
            sparse_model: 'Qdrant/bm25',
            vision_ocr_model: 'gemini-2.5-flash',
            chat_model: 'gemini-2.5-flash'
          })
        })
      );
      expect(screen.getByText('Embedding resource limits updated successfully')).toBeInTheDocument();
      expect(refreshStats).toHaveBeenCalled();
    });
  });

  it('handles embedding save failure and load errors gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync') return Promise.resolve({ ok: true, json: async () => mockAutoSyncSettings });
      if (url === '/admin/api/settings/embedding' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Invalid thread allocation value' })
        });
      }
      if (url === '/admin/api/settings/embedding') {
        return Promise.reject(new Error('Embedding endpoint down'));
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load embedding config:', expect.any(Error));
    });

    const saveBtn = screen.getByRole('button', { name: /Save & Apply Embedding Limits/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText('Error saving embedding settings: Invalid thread allocation value')).toBeInTheDocument();
    });

    consoleSpy.mockRestore();
  });
});
