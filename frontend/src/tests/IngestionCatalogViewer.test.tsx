import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import IngestionCatalogViewer from '../IngestionCatalogViewer';
import { ToastProvider } from '../ToastContext';
import type { IngestionCatalogData } from '../types';

const mockCatalogSummary: IngestionCatalogData = {
  source_type: 'all',
  detail_level: 'summary',
  git_repositories: [
    {
      id: 1,
      name: 'fastapi-backend',
      url: 'https://github.com/org/fastapi-backend',
      branch: 'main',
      commit_sha: 'a1b2c3d4e5',
      provider: 'github',
      status: 'synced',
      last_synced: '2026-08-28 07:30:00',
      file_count: 85
    }
  ],
  monitored_paths: [
    {
      path: '/containers/dev/vault',
      repo: 'dev-vault',
      category: 'specs',
      file_count: 12
    }
  ],
  local_storage: {
    root_path: '/app/data/storage',
    file_count: 4,
    tree: {
      root: '/app/data/storage',
      current_folder: '',
      directories: [{ name: 'docs', rel_path: 'docs', abs_path: '/app/data/storage/docs' }],
      files: [{ name: 'guide.md', rel_path: 'guide.md', abs_path: '/app/data/storage/guide.md', size_bytes: 512, mtime: 1700000000 }]
    }
  },
  files: []
};

const mockCatalogDetailed: IngestionCatalogData = {
  ...mockCatalogSummary,
  detail_level: 'detailed',
  files: [
    {
      filepath: '/containers/dev/vault/spec.md',
      repo: 'dev-vault',
      doc_type: 'doc',
      language: 'markdown',
      mtime: 1700000100
    },
    {
      filepath: '/app/data/storage/guide.md',
      repo: 'local_storage',
      doc_type: 'doc',
      language: 'markdown',
      mtime: 1700000200
    }
  ]
};

describe('IngestionCatalogViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders summary catalog with git repos, monitored paths, and local storage stats', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/ingestion/catalog')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockCatalogSummary
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <IngestionCatalogViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Unified Ingestion Catalog')).toBeInTheDocument();
    expect(screen.getAllByText('fastapi-backend')[0]).toBeInTheDocument();
    expect(screen.getAllByText('/containers/dev/vault')[0]).toBeInTheDocument();
    expect(screen.getByText('/app/data/storage')).toBeInTheDocument();
  });

  it('switches source type filters (git, monitored_path, local_storage)', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('source_type=git')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ...mockCatalogSummary,
            source_type: 'git',
            monitored_paths: [],
            local_storage: null
          })
        } as Response);
      }
      if (url.includes('/admin/api/ingestion/catalog')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockCatalogSummary
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <IngestionCatalogViewer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('fastapi-backend')[0]).toBeInTheDocument();
    });

    // Click 'Git Repositories' filter tab
    fireEvent.click(screen.getByRole('button', { name: /Git Repositories/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('source_type=git'));
    });
  });

  it('toggles detail level to detailed and renders ingested files list', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('detail_level=detailed')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockCatalogDetailed
        } as Response);
      }
      if (url.includes('/admin/api/ingestion/catalog')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockCatalogSummary
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <IngestionCatalogViewer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('fastapi-backend')[0]).toBeInTheDocument();
    });

    // Click Detailed toggle button
    fireEvent.click(screen.getByRole('button', { name: /Detailed File Tree/i }));

    await waitFor(() => {
      expect(screen.getAllByText('/containers/dev/vault/spec.md')[0]).toBeInTheDocument();
      expect(screen.getAllByText('/app/data/storage/guide.md')[0]).toBeInTheDocument();
    });
  });

  it('applies search and extension filters', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('file_extension=.md')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockCatalogDetailed
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => mockCatalogSummary
      } as Response);
    });

    render(
      <ToastProvider>
        <IngestionCatalogViewer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('fastapi-backend')[0]).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText(/e.g. .md, .py/i), {
      target: { value: '.md' }
    });

    fireEvent.click(screen.getByRole('button', { name: /Apply/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('file_extension=.md'));
    });
  });
});
