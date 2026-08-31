import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import GitRepoManager from '../GitRepoManager';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Repo } from '../types';

const mockRepos: Repo[] = [
  {
    id: 1,
    name: 'knowledge-rag-mcp',
    url: 'https://github.com/example/knowledge-rag-mcp.git',
    branch: 'main',
    commit_sha: '687f7b1abcde12345',
    status: 'synced',
    file_count: 25,
    last_synced: '2026-08-17 00:00:00',
    auto_sync: 1,
    webhook_secret: 'secret-xyz-123'
  },
  {
    id: 2,
    name: 'failed-repo',
    url: 'https://github.com/example/failed-repo.git',
    branch: 'master',
    status: 'error',
    last_error: 'Authentication failed for repository',
    file_count: 0,
    auto_sync: 0
  }
];

describe('GitRepoManager Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders repository list with status badges, auto-sync buttons, and details', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRepos
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
      expect(screen.getAllByText('Synced')[0]).toBeInTheDocument();
      expect(screen.getAllByText('687f7b1a')[0]).toBeInTheDocument();
      expect(screen.getAllByText('failed-repo')[0]).toBeInTheDocument();
      expect(screen.getAllByText('Error')[0]).toBeInTheDocument();
      expect(screen.getAllByText('Authentication failed for repository')[0]).toBeInTheDocument();
      expect(screen.getAllByText(/Auto-Sync: ON/i)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/Auto-Sync: OFF/i)[0]).toBeInTheDocument();
    });
  });

  it('shows empty state when no repositories are registered', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => []
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText(/No Git repositories registered/i)[0]).toBeInTheDocument();
    });
  });

  it('opens modal, handles cancel, and submits new repository registration', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ id: 3, name: 'new-repo' })
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => []
      });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    // Open and close via Cancel button
    const addBtn = screen.getByRole('button', { name: /Add Repository/i });
    fireEvent.click(addBtn);
    expect(screen.getByRole('heading', { name: /Register Git Repository/i })).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);
    expect(screen.queryByRole('heading', { name: /Register Git Repository/i })).not.toBeInTheDocument();

    // Reopen modal and submit
    fireEvent.click(addBtn);
    const aliasInput = screen.getByLabelText(/Repository Alias/i);
    const urlInput = screen.getByLabelText(/Git Clone URL/i);
    const branchInput = screen.getByLabelText(/Branch/i);

    fireEvent.change(aliasInput, { target: { value: 'new-repo' } });
    fireEvent.change(urlInput, { target: { value: 'https://github.com/example/new-repo.git' } });
    fireEvent.change(branchInput, { target: { value: 'develop' } });

    const submitBtn = screen.getByRole('button', { name: /Add & Start Sync/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/repos',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            name: 'new-repo',
            url: 'https://github.com/example/new-repo.git',
            branch: 'develop',
            auth_user: null,
            auth_token: null
          })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText("Repository 'new-repo' added successfully")).toBeInTheDocument();
    });
  });

  it('triggers repo sync, refreshes stats, and updates status optimistically', async () => {
    const refreshStats = vi.fn();

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/sync/1')) {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'syncing' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Trigger sync
    const syncButtons = screen.getAllByTitle('Trigger Sync');
    fireEvent.click(syncButtons[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/repos/sync/1', { method: 'POST' });
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText('Sync triggered successfully')).toBeInTheDocument();
    });
  });

  it('toggles auto-sync state and sends PATCH request', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/auto-sync') && opts?.method === 'PATCH') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success', repo_id: 1, auto_sync: false })
        });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Repo 1 has auto_sync: 1 -> toggle to OFF
    const toggleButtons = screen.getAllByLabelText('Toggle auto-sync for knowledge-rag-mcp');
    fireEvent.click(toggleButtons[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/repos/1/auto-sync',
        expect.objectContaining({
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ auto_sync: false })
        })
      );
      expect(screen.getByText('Auto-sync disabled')).toBeInTheDocument();
    });
  });

  it('handles auto-sync toggle error with rollback and error toast', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/auto-sync') && opts?.method === 'PATCH') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Database locked' })
        });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    const toggleButtons = screen.getAllByLabelText('Toggle auto-sync for knowledge-rag-mcp');
    fireEvent.click(toggleButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('Failed to update auto-sync: Database locked')).toBeInTheDocument();
    });
  });

  it('opens webhook modal, displays URL & instructions, and copies URL', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock
      }
    });

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRepos
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Open Webhook modal
    const webhookBtns = screen.getAllByTitle('Webhook Setup');
    fireEvent.click(webhookBtns[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).toBeInTheDocument();
      expect(screen.getByLabelText('Webhook Payload URL')).toBeInTheDocument();
      expect(screen.getByLabelText('Repository Secret Token')).toHaveValue('secret-xyz-123');
      expect(screen.getByText(/GitHub:/i)).toBeInTheDocument();
      expect(screen.getByText(/GitLab:/i)).toBeInTheDocument();
      expect(screen.getByText(/Gitea \/ Forgejo:/i)).toBeInTheDocument();
    });

    // Click Copy button
    const copyBtn = screen.getByLabelText('Copy Webhook URL');
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith(expect.stringContaining('/api/webhooks/git'));
      expect(screen.getByText('Webhook URL copied to clipboard')).toBeInTheDocument();
    });
  });

  it('closes webhook modal via close button and backdrop click', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRepos
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Open Webhook modal
    const webhookBtns = screen.getAllByTitle('Webhook Setup');
    fireEvent.click(webhookBtns[0]);
    expect(screen.getByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).toBeInTheDocument();

    // Close via Close button
    const closeBtn = screen.getByRole('button', { name: /Close$/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).not.toBeInTheDocument();

    // Reopen and close via Backdrop click
    fireEvent.click(webhookBtns[0]);
    const backdrop = screen.getByTestId('webhook-modal-backdrop');
    fireEvent.click(backdrop);
    expect(screen.queryByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).not.toBeInTheDocument();
  });

  it('triggers repo deletion, calls refreshStats, and removes repo optimistically', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/repos/1') && opts?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'deleted' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Trigger delete
    const deleteButtons = screen.getAllByTitle('Delete Repo');
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/repos/1', { method: 'DELETE' });
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText("Repository 'knowledge-rag-mcp' deleted successfully")).toBeInTheDocument();
    });
  });

  it('handles errors when loading repos, adding repo, syncing repo, and deleting repo', async () => {
    // 1. Error on loadRepos
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/admin/api/repos') {
        return Promise.reject(new Error('Network offline'));
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Error loading repos: Network offline/i)).toBeInTheDocument();
    });

    // 2. Error on syncRepo
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/sync/1')) {
        return Promise.resolve({ ok: false, json: async () => ({ error: 'Sync failed on remote' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    const syncButtons = screen.getAllByTitle('Trigger Sync');
    fireEvent.click(syncButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Failed to trigger sync: Sync failed on remote/i)).toBeInTheDocument();
    });

    // 3. Error on deleteRepo
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/repos/1') && opts?.method === 'DELETE') {
        return Promise.resolve({ ok: false, json: async () => ({ error: 'Delete forbidden' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockRepos });
    });

    const deleteButtons = screen.getAllByTitle('Delete Repo');
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Failed to delete repo: Delete forbidden/i)).toBeInTheDocument();
    });
  });

  it('renders mobile cards for repositories with action buttons and auto-sync toggles', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRepos
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );
    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Verify mobile cards exist in DOM alongside desktop table
    const mobileCards = document.querySelectorAll('.data-mobile-card');
    expect(mobileCards.length).toBeGreaterThan(0);

    // Verify action buttons inside mobile cards
    const mobileSyncBtns = screen.getAllByRole('button', { name: /sync/i });
    expect(mobileSyncBtns.length).toBeGreaterThan(0);
    const mobileWebhookBtns = screen.getAllByRole('button', { name: /webhook/i });
    expect(mobileWebhookBtns.length).toBeGreaterThan(0);
  });

  it('opens and closes RepoSyncDrawer when Live Logs button is clicked', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/sync-status')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            1: {
              repo_id: 1,
              repo_name: 'knowledge-rag-mcp',
              status: 'syncing',
              step: 3,
              total_steps: 5,
              step_name: 'Computing File Delta & Scanning',
              current_file: 'src/indexer.ts',
              processed_files: 10,
              total_files: 25,
              percent: 40,
              started_at: Date.now() - 10000,
              updated_at: Date.now(),
              logs: [{ timestamp: '12:00:00', level: 'INFO', message: 'Scanning files' }],
            }
          })
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => mockRepos
      });
    });

    render(
      <ToastProvider>
        <GitRepoManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('knowledge-rag-mcp')[0]).toBeInTheDocument();
    });

    // Click Logs button for knowledge-rag-mcp
    const logButtons = screen.getAllByTitle('View Ingestion Logs');
    fireEvent.click(logButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/knowledge-rag-mcp Ingestion Progress & Live Logs/i)).toBeInTheDocument();
      expect(screen.getAllByText(/Computing File Delta & Scanning/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/Scanning files/i)).toBeInTheDocument();
    });

    // Close drawer via close button
    const closeBtn = screen.getByRole('button', { name: /Close sync drawer/i });
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByText(/knowledge-rag-mcp Ingestion Progress & Live Logs/i)).not.toBeInTheDocument();
    });
  });
});

