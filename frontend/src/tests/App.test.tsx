import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import App from '../App';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockStats = {
  repos_count: 5,
  symbols_count: 1250,
  files_count: 42,
  points_count: 3200,
  last_indexed: '2026-08-17 00:00:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  rate_limit: { remaining: 4950, limit: 5000 },
  top_keywords: ['auth', 'indexer', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234'
};

describe('App Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/stats')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockStats
        } as Response);
      }
      if (url.includes('/admin/api/repos')) {
        return Promise.resolve({
          ok: true,
          json: async () => []
        } as Response);
      }
      if (url.includes('/admin/api/paths')) {
        return Promise.resolve({
          ok: true,
          json: async () => []
        } as Response);
      }
      if (url.includes('/admin/api/logs')) {
        return Promise.resolve({
          ok: true,
          json: async () => []
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({})
      } as Response);
    });
  });

  it('renders header, status indicators, and default Overview tab', async () => {
    render(
      <ToastProvider>
        <App />
      </ToastProvider>
    );

    expect(screen.getByText('ContextHub')).toBeInTheDocument();
    expect(screen.getByText('v2.7.0')).toBeInTheDocument();


    await waitFor(() => {
      expect(screen.getByText('Vector Backend')).toBeInTheDocument();
      expect(screen.getByText(/Qdrant \(Embedded\)/)).toBeInTheDocument();
    });

    expect(screen.getByText('System & Embedding Specs')).toBeInTheDocument();
  });


  it('switches between tabs on navigation click', async () => {
    render(
      <ToastProvider>
        <App />
      </ToastProvider>
    );

    // Switch to Git Repositories
    const gitTab = screen.getByRole('button', { name: /Git Repositories/i });
    fireEvent.click(gitTab);
    await waitFor(() => {
      expect(screen.getByText('Registered Git Repositories')).toBeInTheDocument();
    });

    // Switch to Local Paths
    const pathsTab = screen.getByRole('button', { name: /Local Paths/i });
    fireEvent.click(pathsTab);
    await waitFor(() => {
      expect(screen.getByText('Monitored Local Paths')).toBeInTheDocument();
    });

    // Switch to Search & Inspector
    const searchTab = screen.getByRole('button', { name: /Search & Inspector/i });
    fireEvent.click(searchTab);
    await waitFor(() => {
      expect(screen.getByText('Live Hybrid Search Inspector')).toBeInTheDocument();
    });

    // Switch to Settings
    const settingsTab = screen.getByRole('button', { name: /Settings/i });
    fireEvent.click(settingsTab);
    await waitFor(() => {
      expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
    });

    // Switch to Diagnostics & Logs
    const diagnosticsTab = screen.getByRole('button', { name: /Diagnostics & Logs/i });
    fireEvent.click(diagnosticsTab);
    await waitFor(() => {
      expect(screen.getByText('Diagnostics & Server Logs')).toBeInTheDocument();
    });
  });

  it('renders Syncing... engine state badge when is_indexing is true', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/stats')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ ...mockStats, is_indexing: true })
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <App />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText(/Syncing\.\.\./).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('toggles mobile navigation drawer and closes upon tab selection', async () => {
    render(
      <ToastProvider>
        <App />
      </ToastProvider>
    );
    const menuToggle = screen.getByRole('button', { name: /toggle navigation/i });
    expect(menuToggle).toBeInTheDocument();
    
    // Drawer should initially be closed
    const nav = screen.getByRole('navigation');
    expect(nav).not.toHaveClass('drawer-open');
    
    // Click toggle to open drawer
    fireEvent.click(menuToggle);
    expect(nav).toHaveClass('drawer-open');
    
    // Click a navigation tab to select and auto-close drawer
    const settingsTab = screen.getByRole('button', { name: /settings/i });
    fireEvent.click(settingsTab);
    expect(nav).not.toHaveClass('drawer-open');
  });
});

