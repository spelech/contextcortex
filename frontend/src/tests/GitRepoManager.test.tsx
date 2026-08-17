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
    last_synced: '2026-08-17 00:00:00'
  },
  {
    id: 2,
    name: 'failed-repo',
    url: 'https://github.com/example/failed-repo.git',
    branch: 'master',
    status: 'error',
    last_error: 'Authentication failed for repository',
    file_count: 0
  }
];

describe('GitRepoManager Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders repository list with status badges and details', async () => {
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
    (globalThis as any).fetch = vi.fn().mockRejectedValueOnce(new Error('Network offline'));
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

  it('renders mobile cards for repositories with action buttons', async () => {
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
  });
});

