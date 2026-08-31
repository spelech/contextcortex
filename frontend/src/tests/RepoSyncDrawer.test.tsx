import { render, screen, fireEvent, waitFor, renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RepoSyncDrawer } from '../components/git/RepoSyncDrawer';
import { useGitSyncStream } from '../hooks/useGitSyncStream';
import type { GitSyncJob } from '../types';

const mockJobSyncing: GitSyncJob = {
  repo_id: 1,
  repo_name: 'test-repo',
  status: 'syncing',
  step: 3,
  total_steps: 5,
  step_name: 'Computing File Delta & Scanning',
  current_file: 'src/main.ts',
  processed_files: 45,
  total_files: 100,
  percent: 50,
  started_at: Date.now() / 1000 - 65, // 1m 5s ago
  updated_at: Date.now() / 1000,
  error: null,
  logs: [
    { timestamp: '12:00:01', level: 'INFO', message: 'Starting shallow clone' },
    { timestamp: '12:00:15', level: 'WARN', message: 'Large file detected: data.bin' },
    { timestamp: '12:00:30', level: 'ERROR', message: 'Failed to parse symbol in legacy.js' },
    { timestamp: '12:00:45', level: 'INFO', message: 'Delta scan 45/100 files complete' },
  ],
  cancelled: false,
};

const mockJobSynced: GitSyncJob = {
  repo_id: 2,
  repo_name: 'synced-repo',
  status: 'synced',
  step: 5,
  total_steps: 5,
  step_name: 'Sync Complete',
  current_file: null,
  processed_files: 120,
  total_files: 120,
  percent: 100,
  started_at: Date.now() / 1000 - 120,
  updated_at: Date.now() / 1000,
  error: null,
  logs: [
    { timestamp: '11:00:00', level: 'INFO', message: 'Sync finished successfully' },
  ],
  cancelled: false,
};

const mockJobError: GitSyncJob = {
  repo_id: 3,
  repo_name: 'broken-repo',
  status: 'error',
  step: 2,
  total_steps: 5,
  step_name: 'Shallow Cloning Repository',
  current_file: null,
  processed_files: 0,
  total_files: 0,
  percent: 20,
  started_at: Date.now() / 1000 - 10,
  updated_at: Date.now() / 1000,
  error: 'Remote authentication failed: Invalid token',
  logs: [
    { timestamp: '10:00:00', level: 'INFO', message: 'Connecting to remote host' },
    { timestamp: '10:00:05', level: 'ERROR', message: 'Remote authentication failed: Invalid token' },
  ],
  cancelled: false,
};

describe('RepoSyncDrawer Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not render anything when isOpen is false', () => {
    const { container } = render(
      <RepoSyncDrawer
        isOpen={false}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders drawer header with title, status badge, and elapsed timer', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    expect(screen.getByText(/test-repo Ingestion Progress & Live Logs/i)).toBeInTheDocument();
    expect(screen.getByText(/Syncing/i)).toBeInTheDocument();
    expect(screen.getByText(/Elapsed:/i)).toBeInTheDocument();
  });

  it('renders close button and closes drawer when clicked or backdrop clicked', () => {
    const onClose = vi.fn();
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={onClose}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    const closeBtn = screen.getByRole('button', { name: /close/i });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);

    const backdrop = screen.getByTestId('sync-drawer-backdrop');
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('renders 5-stage stepper with completed, active, and pending steps', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    // 5 Stages
    expect(screen.getByText(/1\. Connecting & Remote Check/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Shallow Cloning Repository/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Computing File Delta & Scanning/i)).toBeInTheDocument();
    expect(screen.getByText(/4\. Parsing AST Symbols & API Routes/i)).toBeInTheDocument();
    expect(screen.getByText(/5\. Upserting Embeddings & Finalizing/i)).toBeInTheDocument();

    // Check step 3 shows active details
    expect(screen.getByText(/src\/main\.ts/i)).toBeInTheDocument();
    expect(screen.getByText(/45 \/ 100 files/i)).toBeInTheDocument();
    expect(screen.getAllByText(/50%/i).length).toBeGreaterThan(0);
  });

  it('renders all 5 stages as completed when status is synced', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={2}
        repoName="synced-repo"
        job={mockJobSynced}
      />
    );

    expect(screen.getByText(/synced-repo Ingestion Progress & Live Logs/i)).toBeInTheDocument();
    expect(screen.getByText('Synced')).toBeInTheDocument();
    expect(screen.getAllByText(/100%/i).length).toBeGreaterThan(0);
    // Cancel button should not be visible when synced
    expect(screen.queryByRole('button', { name: /cancel sync/i })).not.toBeInTheDocument();
  });

  it('renders error state and last error message when status is error', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={3}
        repoName="broken-repo"
        job={mockJobError}
      />
    );

    expect(screen.getByText(/broken-repo Ingestion Progress & Live Logs/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Error/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Remote authentication failed: Invalid token/i).length).toBeGreaterThan(0);
  });

  it('shows and calls onCancelSync button when status is syncing', async () => {
    const onCancelSync = vi.fn().mockResolvedValue(undefined);
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
        onCancelSync={onCancelSync}
      />
    );

    const cancelBtn = screen.getByRole('button', { name: /cancel sync/i });
    await act(async () => {
      fireEvent.click(cancelBtn);
    });
    expect(onCancelSync).toHaveBeenCalledWith(1);
  });

  it('renders log messages with level styling and handles search filter', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    // Initial logs
    expect(screen.getByText('Starting shallow clone')).toBeInTheDocument();
    expect(screen.getByText('Large file detected: data.bin')).toBeInTheDocument();
    expect(screen.getByText('Failed to parse symbol in legacy.js')).toBeInTheDocument();
    expect(screen.getByText('Delta scan 45/100 files complete')).toBeInTheDocument();

    // Filter logs
    const filterInput = screen.getByPlaceholderText(/filter logs/i);
    fireEvent.change(filterInput, { target: { value: 'Large file' } });

    expect(screen.getByText('Large file detected: data.bin')).toBeInTheDocument();
    expect(screen.queryByText('Starting shallow clone')).not.toBeInTheDocument();
    expect(screen.queryByText('Failed to parse symbol in legacy.js')).not.toBeInTheDocument();
  });

  it('shows empty state when no logs exist', () => {
    const emptyJob: GitSyncJob = {
      ...mockJobSyncing,
      logs: [],
    };

    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={emptyJob}
      />
    );

    expect(screen.getByText(/waiting for sync activity\.\.\./i)).toBeInTheDocument();
  });

  it('copies logs to clipboard when Copy Logs button is clicked', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    const copyBtn = screen.getByRole('button', { name: /copy logs/i });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalled();
      const copiedText = writeTextMock.mock.calls[0][0];
      expect(copiedText).toContain('Starting shallow clone');
      expect(copiedText).toContain('Large file detected: data.bin');
      expect(screen.getByText(/copied!/i)).toBeInTheDocument();
    });
  });

  it('toggles autoscroll checkbox in terminal toolbar', () => {
    render(
      <RepoSyncDrawer
        isOpen={true}
        onClose={vi.fn()}
        repoId={1}
        repoName="test-repo"
        job={mockJobSyncing}
      />
    );

    const autoScrollCheckbox = screen.getByRole('checkbox', { name: /autoscroll/i }) as HTMLInputElement;
    expect(autoScrollCheckbox.checked).toBe(true);

    fireEvent.click(autoScrollCheckbox);
    expect(autoScrollCheckbox.checked).toBe(false);
  });
});

describe('useGitSyncStream Hook', () => {
  let mockEventSourceInstances: any[] = [];

  class MockEventSource {
    url: string;
    listeners: Record<string, Function[]> = {};
    onerror: ((err: any) => void) | null = null;
    close = vi.fn();

    constructor(url: string) {
      this.url = url;
      mockEventSourceInstances.push(this);
    }

    addEventListener(event: string, callback: Function) {
      if (!this.listeners[event]) this.listeners[event] = [];
      this.listeners[event].push(callback);
    }

    removeEventListener(event: string, callback: Function) {
      if (this.listeners[event]) {
        this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
      }
    }

    emit(event: string, data: any) {
      const callbacks = this.listeners[event] || [];
      callbacks.forEach(cb => cb({ data: JSON.stringify(data) }));
    }

    triggerError(err: any = new Error('SSE Connection Error')) {
      if (this.onerror) {
        this.onerror(err);
      }
    }
  }

  beforeEach(() => {
    mockEventSourceInstances = [];
    (globalThis as any).EventSource = MockEventSource;
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ 1: mockJobSyncing }),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('connects to SSE endpoint and seeds initial snapshot via init event', async () => {
    const { result } = renderHook(() => useGitSyncStream());

    expect(mockEventSourceInstances.length).toBe(1);
    const es = mockEventSourceInstances[0];
    expect(es.url).toBe('/admin/api/repos/sync/stream');

    act(() => {
      es.emit('init', { 1: mockJobSyncing });
    });

    await waitFor(() => {
      expect(result.current.syncStates[1]).toBeDefined();
      expect(result.current.syncStates[1].repo_name).toBe('test-repo');
      expect(result.current.isConnected).toBe(true);
    });
  });

  it('updates job progress upon receiving progress event', async () => {
    const { result } = renderHook(() => useGitSyncStream());
    const es = mockEventSourceInstances[0];

    act(() => {
      es.emit('init', { 1: mockJobSyncing });
    });

    const updatedJob = {
      ...mockJobSyncing,
      step: 4,
      step_name: 'Parsing AST Symbols & API Routes',
      percent: 75,
    };

    act(() => {
      es.emit('progress', { type: 'progress', data: updatedJob });
    });

    await waitFor(() => {
      expect(result.current.syncStates[1].step).toBe(4);
      expect(result.current.syncStates[1].step_name).toBe('Parsing AST Symbols & API Routes');
      expect(result.current.syncStates[1].percent).toBe(75);
    });
  });

  it('appends log entries upon receiving log event', async () => {
    const { result } = renderHook(() => useGitSyncStream());
    const es = mockEventSourceInstances[0];

    act(() => {
      es.emit('init', { 1: mockJobSyncing });
    });

    act(() => {
      es.emit('log', {
        type: 'log',
        repo_id: 1,
        data: { timestamp: '12:01:00', level: 'INFO', message: 'New log entry streamed' },
      });
    });

    await waitFor(() => {
      const logs = result.current.syncStates[1].logs;
      expect(logs[logs.length - 1].message).toBe('New log entry streamed');
    });
  });

  it('cancels sync by calling /admin/api/repos/{id}/cancel-sync', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'cancelled', repo_id: 1 }),
    });

    const { result } = renderHook(() => useGitSyncStream());

    await act(async () => {
      await result.current.cancelSync(1);
    });

    expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/repos/1/cancel-sync', {
      method: 'POST',
    });
  });

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() => useGitSyncStream());
    const es = mockEventSourceInstances[0];
    unmount();
    expect(es.close).toHaveBeenCalled();
  });
});
