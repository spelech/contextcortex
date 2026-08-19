import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DiagnosticsViewer from '../DiagnosticsViewer';
import { ToastProvider } from '../ToastContext';

const mockLogs = [
  {
    timestamp: '2026-08-17 01:00:00',
    level: 'INFO',
    logger: 'knowledge-rag-mcp.server',
    message: 'Server startup complete',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:01:00',
    level: 'WARNING',
    logger: 'knowledge-rag-mcp.indexer',
    message: 'Rate limit threshold near 80%',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:02:00',
    level: 'ERROR',
    logger: 'knowledge-rag-mcp.git',
    message: 'Git clone failed timeout',
    traceback: 'Traceback (most recent call last):\n  File "git.py", line 42, in clone\nTimeoutError: Connection timed out'
  }
];

describe('DiagnosticsViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn((_url: string, options?: any) => {
      if (options?.method === 'DELETE') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'success' })
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockLogs)
      });
    }));
  });

  it('renders log records, badges, and controls', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Server startup complete')).toBeInTheDocument();
    expect(screen.getByText('Rate limit threshold near 80%')).toBeInTheDocument();
    expect(screen.getByText('Git clone failed timeout')).toBeInTheDocument();
    expect(screen.getByText('Diagnostics & Server Logs')).toBeInTheDocument();
    expect(screen.getByText('knowledge-rag-mcp.server')).toBeInTheDocument();
    expect(screen.getByText('knowledge-rag-mcp.indexer')).toBeInTheDocument();
    expect(screen.getByText('knowledge-rag-mcp.git')).toBeInTheDocument();
  });

  it('filters logs by log level buttons', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Server startup complete')).toBeInTheDocument();

    // Click ERROR level filter
    const errorFilterBtn = screen.getByRole('button', { name: /^ERROR/i });
    fireEvent.click(errorFilterBtn);

    expect(screen.queryByText('Server startup complete')).not.toBeInTheDocument();
    expect(screen.queryByText('Rate limit threshold near 80%')).not.toBeInTheDocument();
    expect(screen.getByText('Git clone failed timeout')).toBeInTheDocument();

    // Click WARNING level filter
    const warningFilterBtn = screen.getByRole('button', { name: /^WARNING/i });
    fireEvent.click(warningFilterBtn);

    expect(screen.getByText('Rate limit threshold near 80%')).toBeInTheDocument();
    expect(screen.queryByText('Server startup complete')).not.toBeInTheDocument();
    expect(screen.queryByText('Git clone failed timeout')).not.toBeInTheDocument();

    // Click ALL level filter
    const allFilterBtn = screen.getByRole('button', { name: /^ALL/i });
    fireEvent.click(allFilterBtn);

    expect(screen.getByText('Server startup complete')).toBeInTheDocument();
    expect(screen.getByText('Rate limit threshold near 80%')).toBeInTheDocument();
    expect(screen.getByText('Git clone failed timeout')).toBeInTheDocument();
  });

  it('filters logs by search input', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Server startup complete')).toBeInTheDocument();

    const searchInput = screen.getByPlaceholderText(/search logs/i);
    fireEvent.change(searchInput, { target: { value: 'clone' } });

    expect(screen.queryByText('Server startup complete')).not.toBeInTheDocument();
    expect(screen.queryByText('Rate limit threshold near 80%')).not.toBeInTheDocument();
    expect(screen.getByText('Git clone failed timeout')).toBeInTheDocument();

    // Search by logger name
    fireEvent.change(searchInput, { target: { value: 'indexer' } });
    expect(screen.getByText('Rate limit threshold near 80%')).toBeInTheDocument();
    expect(screen.queryByText('Git clone failed timeout')).not.toBeInTheDocument();
  });

  it('expands and collapses traceback details', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Git clone failed timeout')).toBeInTheDocument();

    // Initially traceback content is hidden or accordion toggled
    const tracebackToggleBtn = screen.getByRole('button', { name: /Traceback|Stack Trace/i });
    expect(tracebackToggleBtn).toBeInTheDocument();

    // Expand traceback
    fireEvent.click(tracebackToggleBtn);
    expect(await screen.findByText(/TimeoutError: Connection timed out/i)).toBeInTheDocument();

    // Collapse traceback
    fireEvent.click(tracebackToggleBtn);
    expect(screen.queryByText(/TimeoutError: Connection timed out/i)).not.toBeInTheDocument();
  });

  it('toggles auto-scroll option', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    await screen.findByText('Server startup complete');

    const autoScrollToggle = screen.getByLabelText(/Auto-scroll/i);
    expect(autoScrollToggle).toBeInTheDocument();
    expect(autoScrollToggle).toBeChecked();

    fireEvent.click(autoScrollToggle);
    expect(autoScrollToggle).not.toBeChecked();
  });

  it('refreshes logs on refresh button click', async () => {
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    await screen.findByText('Server startup complete');

    const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/admin/api/logs');
    });
  });

  it('clears logs on button click after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    const clearBtn = await screen.findByRole('button', { name: /Clear Logs/i });
    fireEvent.click(clearBtn);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/admin/api/logs', expect.objectContaining({ method: 'DELETE' }));
    });

    await waitFor(() => {
      expect(screen.getByText(/No logs available/i)).toBeInTheDocument();
    });
  });

  it('does not clear logs if confirmation is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    await screen.findByText('Server startup complete');

    const clearBtn = await screen.findByRole('button', { name: /Clear Logs/i });
    fireEvent.click(clearBtn);

    expect(fetch).not.toHaveBeenCalledWith('/admin/api/logs', expect.objectContaining({ method: 'DELETE' }));
    expect(screen.getByText('Server startup complete')).toBeInTheDocument();
  });

  it('displays error toast when log fetching fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Network error'))));

    render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Failed to load diagnostics logs/i)).toBeInTheDocument();
    });
  });

  it('renders responsive layout elements for toolbar, search input, and log entry stream', async () => {
    const { container } = render(
      <ToastProvider>
        <DiagnosticsViewer />
      </ToastProvider>
    );

    expect(await screen.findByText('Server startup complete')).toBeInTheDocument();

    expect(container.querySelector('.log-viewer-header')).toBeInTheDocument();
    expect(container.querySelector('.log-viewer-actions')).toBeInTheDocument();
    expect(container.querySelector('.log-toolbar')).toBeInTheDocument();
    expect(container.querySelector('.log-filter-pills')).toBeInTheDocument();
    expect(container.querySelector('.log-search-wrapper')).toBeInTheDocument();
    expect(container.querySelector('.log-stream-container')).toBeInTheDocument();

    const logEntries = container.querySelectorAll('.log-entry-main');
    expect(logEntries.length).toBe(3);
  });
});

