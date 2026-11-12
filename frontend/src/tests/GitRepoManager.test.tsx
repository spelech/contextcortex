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
            auth_token: null,
            keep_shallow: false,
            retain_commits_count: 20
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
});
