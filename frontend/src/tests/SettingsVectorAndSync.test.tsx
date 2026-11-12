import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Settings from '../Settings';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Stats } from '../types';
import {
  installDefaultSettingsFetchMocks,
  mockStats,
  mockVectorStoreConfig,
} from './fixtures/settingsFixtures';

describe('Settings Auto-Sync, Webhooks & Dynamic Vector Sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

    expect(screen.getAllByText('Auto-Sync & Webhooks')[0]).toBeInTheDocument();
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
    installDefaultSettingsFetchMocks();

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
    installDefaultSettingsFetchMocks();

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
    installDefaultSettingsFetchMocks();

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
    installDefaultSettingsFetchMocks();

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
    installDefaultSettingsFetchMocks();

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

  it('dynamically syncs vectorStore state when stats prop updates', async () => {
    installDefaultSettingsFetchMocks();

    const { rerender } = render(
      <ToastProvider>
        <Settings stats={mockStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Qdrant')).toBeInTheDocument();
    });

    const updatedStats: Stats = {
      ...mockStats,
      vector_store: {
        provider: 'pgvector',
        mode: 'remote',
        storage_path: null,
        url: 'postgresql+psycopg://pg-live:5432/contextcortex',
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
      expect(screen.getByText('PostgreSQL (pgvector)')).toBeInTheDocument();
      expect(screen.getByText('5,000')).toBeInTheDocument();
      expect(screen.getByText('live_vectors')).toBeInTheDocument();
    });
  });
});
