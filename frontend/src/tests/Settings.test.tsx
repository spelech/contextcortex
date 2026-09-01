import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Stats, GitHostCredential, VectorStoreConfig, EmbeddingConfig } from '../types';

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
  },
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1'
};

const mockVectorStoreConfig: VectorStoreConfig = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant_db',
  url: 'http://localhost:6333',
  collection: 'knowledge_rag_v1',
  healthy: true,
  health_message: 'Collection knowledge_rag_v1 is healthy and operational',
  points_count: 1250,
  stats: { points_count: 1250, vector_dimension: 384 }
};

const mockEmbeddingConfig: EmbeddingConfig = {
  provider: 'local',
  dense_model: 'BAAI/bge-small-en-v1.5',
  sparse_model: 'Qdrant/bm25',
  threads: 2,
  batch_size: 32,
  system_cpus: 8,
  system_memory_gb: 16.0,
  litellm_url: 'http://litellm:4000/v1'
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

const mockAutoSyncSettings = {
  interval_mins: 15,
  webhook_url: '/api/webhooks/git',
  has_global_secret: false
};

describe('Settings Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const setupDefaultMocks = () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => mockHostCreds });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({ ok: true, json: async () => mockAutoSyncSettings });
      }
      if (url === '/admin/api/settings/embedding') {
        return Promise.resolve({ ok: true, json: async () => mockEmbeddingConfig });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  };

  it('renders vector database panel, auto-sync panel, multi-provider token boxes, rate limits, and host vault list', async () => {
    setupDefaultMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Vector Database Engine')).toBeInTheDocument();
    expect(screen.getByText('Active Vector Backend')).toBeInTheDocument();
    expect(screen.getByText('Auto-Sync & Webhooks')).toBeInTheDocument();
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

  it('switches vector store form fields between embedded and remote modes and changes default paths/urls', async () => {
    setupDefaultMocks();

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

    // Switch to ChromaDB
    fireEvent.change(providerSelect, { target: { value: 'chroma' } });
    expect(providerSelect.value).toBe('chroma');
    expect(screen.getByLabelText(/Storage Directory Path/i)).toHaveValue('data/chroma_db');

    // Switch mode to Remote
    fireEvent.change(modeSelect, { target: { value: 'remote' } });
    expect(modeSelect.value).toBe('remote');
    expect(screen.getByLabelText(/Remote Server URL/i)).toHaveValue('http://localhost:8000');

    // Switch provider back to Qdrant
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

    const testBtn = screen.getByRole('button', { name: /Test Connection/i });
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
      provider: 'chroma',
      mode: 'embedded',
      storage_path: 'data/chroma_db',
      url: null,
      collection: 'knowledge_rag_v1',
      healthy: true,
      health_message: 'ChromaDB persistent store active',
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
            message: 'Switched vector database to CHROMADB and started re-indexing.',
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
    fireEvent.change(providerSelect, { target: { value: 'chroma' } });

    const switchBtn = screen.getByRole('button', { name: /Save & Switch Backend/i });
    fireEvent.click(switchBtn);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/vector-store/switch',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            provider: 'chroma',
            mode: 'embedded',
            storage_path: 'data/chroma_db',
            url: null,
            collection: 'knowledge_rag_v1'
          })
        })
      );
      expect(screen.getAllByText('Switched vector database to CHROMADB and started re-indexing.').length).toBeGreaterThan(0);
      expect(refreshStats).toHaveBeenCalled();
    });
  });

  it('cancels vector store backend switch when confirmation is dismissed', async () => {
    setupDefaultMocks();
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
    expect(globalThis.fetch).toHaveBeenCalledTimes(4); // Initial loads for hosts, vector store, auto-sync & embedding

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
    setupDefaultMocks();

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
    setupDefaultMocks();

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

  it('renders auto-sync settings panel with loaded interval, secret placeholder, and webhook endpoint URL', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            interval_mins: 30,
            webhook_url: '/api/webhooks/git',
            has_global_secret: true
          })
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Auto-Sync & Webhooks')).toBeInTheDocument();
    expect(screen.getByLabelText(/Repository Polling Interval/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Global Webhook Secret/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Incoming Webhook Payload URL/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('30');
      expect(screen.getByPlaceholderText(/Secret configured \(enter new to change\)/i)).toBeInTheDocument();
      expect(screen.getByText('Secret Active')).toBeInTheDocument();
    });
  });

  it('changes polling interval and saves auto-sync settings', async () => {
    setupDefaultMocks();

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync' && opts?.method === 'POST') {
        const body = JSON.parse(opts.body);
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success', interval_mins: body.interval_mins, has_global_secret: false })
        });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ interval_mins: 15, webhook_url: '/api/webhooks/git', has_global_secret: false })
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
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('15');
    });

    const intervalSelect = screen.getByLabelText(/Repository Polling Interval/i);
    fireEvent.change(intervalSelect, { target: { value: '60' } });
    expect(intervalSelect).toHaveValue('60');

    const saveBtn = screen.getByRole('button', { name: /Save Auto-Sync Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/auto-sync',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ interval_mins: 60 })
        })
      );
      expect(screen.getByText('Auto-sync settings saved successfully')).toBeInTheDocument();
    });
  });

  it('enters new global webhook secret and saves settings successfully', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync' && opts?.method === 'POST') {
        const body = JSON.parse(opts.body);
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success', interval_mins: body.interval_mins, has_global_secret: true })
        });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ interval_mins: 15, webhook_url: '/api/webhooks/git', has_global_secret: false })
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
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('15');
    });

    const secretInput = screen.getByPlaceholderText(/Enter webhook secret \(optional\)/i);
    fireEvent.change(secretInput, { target: { value: 'super-secret-hmac' } });

    const saveBtn = screen.getByRole('button', { name: /Save Auto-Sync Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/auto-sync',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ interval_mins: 15, global_webhook_secret: 'super-secret-hmac' })
        })
      );
      expect(screen.getByText('Auto-sync settings saved successfully')).toBeInTheDocument();
      expect(screen.getByText('Secret Active')).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/Secret configured \(enter new to change\)/i)).toBeInTheDocument();
    });
  });

  it('toggles webhook secret visibility between masked and unmasked', async () => {
    setupDefaultMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('15');
    });

    const secretInput = screen.getByLabelText(/Global Webhook Secret/i);
    expect(secretInput).toHaveAttribute('type', 'password');

    const toggleBtn = screen.getByRole('button', { name: /Reveal secret/i });
    fireEvent.click(toggleBtn);
    expect(secretInput).toHaveAttribute('type', 'text');

    const hideBtn = screen.getByRole('button', { name: /Hide secret/i });
    fireEvent.click(hideBtn);
    expect(secretInput).toHaveAttribute('type', 'password');
  });

  it('clears global webhook secret with confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success', interval_mins: 15, has_global_secret: false })
        });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ interval_mins: 15, webhook_url: '/api/webhooks/git', has_global_secret: true })
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
      expect(screen.getByText('Secret Active')).toBeInTheDocument();
    });

    const clearBtn = screen.getByRole('button', { name: /Clear secret/i });
    fireEvent.click(clearBtn);

    expect(window.confirm).toHaveBeenCalled();

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/settings/auto-sync',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ interval_mins: 15, global_webhook_secret: '' })
        })
      );
      expect(screen.getByText('Global webhook secret cleared')).toBeInTheDocument();
      expect(screen.queryByText('Secret Active')).not.toBeInTheDocument();
    });
  });

  it('cancels clearing global webhook secret when confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ interval_mins: 15, webhook_url: '/api/webhooks/git', has_global_secret: true })
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
      expect(screen.getByText('Secret Active')).toBeInTheDocument();
    });

    const clearBtn = screen.getByRole('button', { name: /Clear secret/i });
    fireEvent.click(clearBtn);

    expect(window.confirm).toHaveBeenCalled();
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/admin/api/settings/auto-sync',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('clears unsaved pending secret input without API call when no secret is stored', async () => {
    setupDefaultMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('15');
    });

    const secretInput = screen.getByLabelText(/Global Webhook Secret/i);
    fireEvent.change(secretInput, { target: { value: 'unsaved-secret' } });
    expect(secretInput).toHaveValue('unsaved-secret');

    const clearBtn = screen.getByRole('button', { name: /Clear secret/i });
    fireEvent.click(clearBtn);

    expect(secretInput).toHaveValue('');
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/admin/api/settings/auto-sync',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('copies webhook endpoint URL to clipboard', async () => {
    setupDefaultMocks();

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock
      }
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    const copyBtn = screen.getByRole('button', { name: /Copy Webhook URL/i });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith(expect.stringContaining('/api/webhooks/git'));
      expect(screen.getByText('Webhook URL copied to clipboard')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Copy Webhook URL/i })).toHaveTextContent(/Copied!/i);
    });
  });

  it('handles clipboard copy failure gracefully', async () => {
    setupDefaultMocks();

    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('Permission denied'))
      }
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Repository Polling Interval/i)).toHaveValue('15');
    });

    const copyBtn = screen.getByRole('button', { name: /Copy Webhook URL/i });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(screen.getByText(/Failed to copy: Permission denied/i)).toBeInTheDocument();
    });
  });

  it('handles auto-sync load and save API errors gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url === '/admin/api/settings/auto-sync' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Invalid auto-sync interval' })
        });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.reject(new Error('Auto-sync settings endpoint failed'));
      }
      if (url === '/admin/api/settings/hosts') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/admin/api/vector-store') return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load auto-sync settings:', expect.any(Error));
    });

    const saveBtn = screen.getByRole('button', { name: /Save Auto-Sync Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText('Error saving auto-sync settings: Invalid auto-sync interval')).toBeInTheDocument();
    });

    consoleSpy.mockRestore();
  });

  it('renders embedding engine settings panel with current CPU threads, batch size, and system hardware', async () => {
    setupDefaultMocks();

    render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Embedding Engine & Resource Limits')).toBeInTheDocument();
    expect(screen.getByText('Active Embedding Engine')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Local FastEmbed (ONNX)')).toBeInTheDocument();
      expect(screen.getByText(/2 Cores \(of 8 detected\)/i)).toBeInTheDocument();
      expect(screen.getByText('32 chunks/batch')).toBeInTheDocument();
      expect(screen.getByText('16 GB')).toBeInTheDocument();
    });
  });

  it('updates thread cap and batch size and saves embedding settings', async () => {
    setupDefaultMocks();
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
            config: { ...mockEmbeddingConfig, threads: body.threads, batch_size: body.batch_size }
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
            provider: 'local',
            threads: 4,
            batch_size: 64,
            dense_model: 'BAAI/bge-small-en-v1.5',
            sparse_model: 'Qdrant/bm25'
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

  it('dynamically syncs vectorStore state when stats prop updates', async () => {
    setupDefaultMocks();

    const { rerender } = render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Qdrant')).toBeInTheDocument();
    });

    // Update stats with new vector store config
    const updatedStats: Stats = {
      ...mockStats,
      vector_store: {
        provider: 'chroma',
        mode: 'remote',
        storage_path: null,
        url: 'http://chroma-live:8000',
        collection: 'live_vectors',
        healthy: true,
        points_count: 5000,
      }
    };

    rerender(
      <ToastProvider>
        <Settings stats={updatedStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('ChromaDB')).toBeInTheDocument();
      expect(screen.getByText('5,000')).toBeInTheDocument();
      expect(screen.getByText('live_vectors')).toBeInTheDocument();
    });
  });
});

