import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { VectorStoreConfig } from '../types';
import {
  installDefaultSettingsFetchMocks,
  mockHostCreds,
  mockStats,
  mockVectorStoreConfig,
} from './fixtures/settingsFixtures';

describe('Settings Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders vector database panel, auto-sync panel, multi-provider token boxes, rate limits, and host vault list', async () => {
    installDefaultSettingsFetchMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Vector Database Engine')).toBeInTheDocument();
    expect(screen.getByText('Active Vector Backend')).toBeInTheDocument();
    expect(screen.getAllByText('Auto-Sync & Webhooks')[0]).toBeInTheDocument();
    expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
    expect(screen.getByText('Custom & Self-Hosted Git Host Vault')).toBeInTheDocument();
    expect(screen.getByText('ghp_****5678')).toBeInTheDocument();
    expect(screen.getByText('glpat_****4321')).toBeInTheDocument();
    expect(screen.getByText('gitea_****9876')).toBeInTheDocument();
    expect(screen.getByText(/4950 \/ 5000 requests/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument();
      expect(screen.getByText('Healthy')).toBeInTheDocument();
      expect(screen.getAllByText('gitlab.enterprise.internal')[0]).toBeInTheDocument();
      expect(screen.getAllByText('http://git.lan:3000')[0]).toBeInTheDocument();
      expect(screen.getAllByText('gitlab-ci-token')[0]).toBeInTheDocument();
      expect(screen.getAllByText('Default')[0]).toBeInTheDocument();
    });
  });

  it('handles empty stats or fallback provider auth structure and vector store load error', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/admin/api/vector-store') {
        return Promise.reject(new Error('Vector store endpoint unreachable'));
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <Settings stats={null} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Vector Database Engine')).toBeInTheDocument();
    expect(screen.getByText('Global Git Provider Authentication')).toBeInTheDocument();
    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load vector store config:', expect.any(Error));
    });
    consoleSpy.mockRestore();
  });

  it('switches vector store form fields between Qdrant and pgvector and changes default paths/urls', async () => {
    installDefaultSettingsFetchMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Vector Store Provider/i)).toBeInTheDocument();
    });

    const providerSelect = screen.getByLabelText(/Vector Store Provider/i) as HTMLSelectElement;
    const modeSelect = screen.getByLabelText(/Operating Mode/i) as HTMLSelectElement;

    // Switch to PostgreSQL (pgvector)
    fireEvent.change(providerSelect, { target: { value: 'pgvector' } });
    expect(providerSelect.value).toBe('pgvector');
    expect(screen.getByLabelText(/PostgreSQL Connection URL/i)).toHaveValue('postgresql+psycopg://localhost:5432/contextcortex');

    // Switch provider back to Qdrant (now in remote mode)
    fireEvent.change(providerSelect, { target: { value: 'qdrant' } });
    expect(screen.getByLabelText(/Remote Server URL/i)).toHaveValue('http://localhost:6333');

    // Switch mode back to Embedded
    fireEvent.change(modeSelect, { target: { value: 'embedded' } });
    expect(screen.getByLabelText(/Storage Directory Path/i)).toHaveValue('data/qdrant_db');
  });

  it('tests vector store connection successfully and displays success feedback banner', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => mockHostCreds });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      }
      if (url === '/admin/api/vector-store/test' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ success: true, message: 'Qdrant connection verified successfully' })
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument();
    });

    const testBtn = screen.getByRole('button', { name: /^Test Connection$/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      const calls = (globalThis.fetch as any).mock.calls;
      const urls = calls.map((c: any) => c[0]);
      expect(urls).toContain('/admin/api/vector-store/test');
      expect(screen.getAllByText('Qdrant connection verified successfully').length).toBeGreaterThan(0);
    });
  });

  it('handles vector store connection test failure and network error', async () => {
    // 1. API returns error status
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/vector-store/test' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ success: false, message: 'Cannot connect to remote server at http://localhost:6333' })
        });
      }
      return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const testBtn = screen.getByRole('button', { name: /Test Connection/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(screen.getAllByText(/Cannot connect to remote server at http:\/\/localhost:6333/i).length).toBeGreaterThan(0);
    });

    // 2. Network throw error
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/vector-store/test' && opts?.method === 'POST') {
        return Promise.reject(new Error('Connection timed out'));
      }
      return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
    });

    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(screen.getAllByText(/Connection timed out/i).length).toBeGreaterThan(0);
    });
  });

  it('executes vector store backend switch with user confirmation and refreshes stats', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const updatedConfig: VectorStoreConfig = {
      provider: 'pgvector',
      mode: 'remote',
      storage_path: null,
      url: 'postgresql+psycopg://localhost:5432/contextcortex',
      collection: 'knowledge_rag_v1',
      healthy: true,
      health_message: 'PostgreSQL pgvector store active',
      points_count: 0
    };

    let activeVs = mockVectorStoreConfig;
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => activeVs });
      }
      if (url === '/admin/api/vector-store/switch' && opts?.method === 'POST') {
        activeVs = updatedConfig;
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            message: 'Switched vector database to PGVECTOR and started re-indexing.',
            config: updatedConfig
          })
        });
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

    const providerSelect = screen.getByLabelText(/Vector Store Provider/i);
    fireEvent.change(providerSelect, { target: { value: 'pgvector' } });

    const switchBtn = screen.getByRole('button', { name: /Save & Switch Backend/i });
    fireEvent.click(switchBtn);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/vector-store/switch',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            provider: 'pgvector',
            mode: 'remote',
            storage_path: null,
            url: 'postgresql+psycopg://localhost:5432/contextcortex',
            collection: 'knowledge_rag_v1'
          })
        })
      );
      expect(screen.getAllByText('Switched vector database to PGVECTOR and started re-indexing.').length).toBeGreaterThan(0);
      expect(refreshStats).toHaveBeenCalled();
    });
  });

  it('cancels vector store backend switch when confirmation is dismissed', async () => {
    installDefaultSettingsFetchMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument();
    });

    const switchBtn = screen.getByRole('button', { name: /Save & Switch Backend/i });
    fireEvent.click(switchBtn);

    expect(window.confirm).toHaveBeenCalled();
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/admin/api/vector-store/switch',
      expect.anything()
    );
  });

  it('handles vector store backend switch API failure', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/vector-store/switch' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ status: 'error', error: 'ChromaDB directory permission denied' })
        });
      }
      return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument();
    });

    const switchBtn = screen.getByRole('button', { name: /Save & Switch Backend/i });
    fireEvent.click(switchBtn);

    await waitFor(() => {
      expect(screen.getByText('ChromaDB directory permission denied')).toBeInTheDocument();
    });
  });
});
