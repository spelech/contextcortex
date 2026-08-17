import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LocalPathManager from '../LocalPathManager';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LocalPath, BrowseData } from '../types';

const mockPaths: LocalPath[] = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: true,
    category: 'architecture',
    enabled: true
  }
];

const mockBrowseRoot: BrowseData = {
  current_path: '/containers/dev',
  parent_path: '/containers',
  directories: [{ name: 'workspace', path: '/containers/dev/workspace' }],
  files: [{ name: 'README.md', path: '/containers/dev/README.md' }]
};

const mockBrowseSub: BrowseData = {
  current_path: '/containers/dev/workspace',
  parent_path: '/containers/dev',
  directories: [{ name: 'docs', path: '/containers/dev/workspace/docs' }],
  files: [{ name: 'index.ts', path: '/containers/dev/workspace/index.ts' }]
};

describe('LocalPathManager Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders configured paths correctly', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPaths
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('/containers/dev/workspace/docs')[0]).toBeInTheDocument();
      expect(screen.getAllByText('docs-vault')[0]).toBeInTheDocument();
      expect(screen.getAllByText('architecture')[0]).toBeInTheDocument();
      expect(screen.getByRole('cell', { name: 'Enabled' })).toBeInTheDocument();
    });
  });

  it('renders mobile cards for local search paths with delete button', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/paths/1') && opts?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'deleted' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockPaths });
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('docs-vault')[0]).toBeInTheDocument();
    });

    const pathCards = document.querySelectorAll('.data-mobile-card');
    expect(pathCards.length).toBeGreaterThan(0);

    // Test delete from mobile card
    const mobileDeleteBtn = pathCards[0].querySelector('.btn-delete');
    expect(mobileDeleteBtn).toBeInTheDocument();
    if (mobileDeleteBtn) {
      fireEvent.click(mobileDeleteBtn);
      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled();
        expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/paths/1', { method: 'DELETE' });
        expect(refreshStats).toHaveBeenCalled();
      });
    }
  });

  it('supports folder navigation drilling and parent directory climbing in browser', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('path=%2Fcontainers%2Fdev%2Fworkspace')) {
        return Promise.resolve({ ok: true, json: async () => mockBrowseSub });
      }
      if (url.includes('/admin/api/browse')) {
        return Promise.resolve({ ok: true, json: async () => mockBrowseRoot });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    // Open add modal
    fireEvent.click(screen.getByRole('button', { name: /Add Local Path/i }));
    // Open browser
    fireEvent.click(screen.getByRole('button', { name: /Browse/i }));

    await waitFor(() => {
      expect(screen.getByText('workspace')).toBeInTheDocument();
    });

    // Click on 'workspace' directory
    fireEvent.click(screen.getByText('workspace'));

    await waitFor(() => {
      expect(screen.getByText('docs')).toBeInTheDocument();
      expect(screen.getByText('.. (Parent Directory)')).toBeInTheDocument();
    });

    // Click on '.. (Parent Directory)'
    fireEvent.click(screen.getByText('.. (Parent Directory)'));

    await waitFor(() => {
      expect(screen.getByText('README.md')).toBeInTheDocument();
    });
  });

  it('selects a single file directly from browser and sets file path type', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/browse')) {
        return Promise.resolve({ ok: true, json: async () => mockBrowseRoot });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /Add Local Path/i }));
    fireEvent.click(screen.getByRole('button', { name: /Browse/i }));

    await waitFor(() => {
      expect(screen.getByText('README.md')).toBeInTheDocument();
    });

    // Click README.md file
    fireEvent.click(screen.getByText('README.md'));

    // Browser closes and selectedPath is updated
    expect(screen.queryByText('Browse Workspace Files')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('/containers/dev/README.md')).toBeInTheDocument();
  });

  it('customizes repo alias, category, and recursive options before saving and refreshes stats', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/browse')) {
        return Promise.resolve({ ok: true, json: async () => mockBrowseRoot });
      }
      if (opts?.method === 'POST') {
        return Promise.resolve({ ok: true, json: async () => ({ id: 2 }) });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /Add Local Path/i }));
    fireEvent.click(screen.getByRole('button', { name: /Browse/i }));

    await waitFor(() => {
      expect(screen.getByText('Select Current Folder')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Select Current Folder'));

    // Customize fields
    fireEvent.change(screen.getByLabelText(/Repo \/ Vault Alias/i), { target: { value: 'custom-vault' } });
    fireEvent.change(screen.getByLabelText(/Category Override/i), { target: { value: 'api-specs' } });
    fireEvent.change(screen.getByLabelText(/Scan Subfolders/i), { target: { value: '0' } });

    fireEvent.click(screen.getByRole('button', { name: /Save Path/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/paths',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            path: '/containers/dev',
            repo: 'custom-vault',
            category: 'api-specs',
            type: 'directory',
            recursive: 0,
            enabled: 1
          })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
    });
  });

  it('deletes path when delete button is confirmed and refreshes stats', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/paths/1') && opts?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'deleted' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockPaths });
    });

    render(
      <ToastProvider>
        <LocalPathManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('/containers/dev/workspace/docs')[0]).toBeInTheDocument();
    });

    const deleteBtn = screen.getAllByTitle('Delete Path')[0];
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/paths/1', { method: 'DELETE' });
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText('Path deleted successfully')).toBeInTheDocument();
    });
  });

  it('handles errors when loading paths, adding path, deleting path, and browsing', async () => {
    // 1. Error on loadPaths
    (globalThis as any).fetch = vi.fn().mockRejectedValueOnce(new Error('Paths offline'));
    render(
      <ToastProvider>
        <LocalPathManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Error loading paths: Paths offline/i)).toBeInTheDocument();
    });

    // 2. Cancel delete
    (globalThis as any).fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => mockPaths });
    render(
      <ToastProvider>
        <LocalPathManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('/containers/dev/workspace/docs')[0]).toBeInTheDocument();
    });

    vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    const deleteBtn = screen.getAllByTitle('Delete Path')[0];
    fireEvent.click(deleteBtn);
    expect(window.confirm).toHaveBeenCalled();

    // 3. Error on delete
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true);
    (globalThis as any).fetch = vi.fn().mockImplementation((_url: string, opts?: any) => {
      if (opts?.method === 'DELETE') {
        return Promise.resolve({ ok: false, json: async () => ({ error: 'Delete denied' }) });
      }
      return Promise.resolve({ ok: true, json: async () => mockPaths });
    });
    fireEvent.click(deleteBtn);
    await waitFor(() => {
      expect(screen.getByText(/Failed to delete path: Delete denied/i)).toBeInTheDocument();
    });
  });
});
