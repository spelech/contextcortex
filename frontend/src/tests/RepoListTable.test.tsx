import { render, screen, fireEvent } from '@testing-library/react';
import { RepoListTable } from '../components/git/RepoListTable';
import { describe, it, expect, vi } from 'vitest';
import type { Repo, GitSyncJob } from '../types';

const mockRepos: Repo[] = [
  {
    id: 1,
    name: 'backend-core',
    url: 'https://github.com/example/backend-core.git',
    branch: 'main',
    commit_sha: 'abcdef1234567890',
    status: 'synced',
    file_count: 120,
    last_synced: '2026-08-30 12:00:00',
    auto_sync: 1,
  },
  {
    id: 2,
    name: 'frontend-app',
    url: 'https://github.com/example/frontend-app.git',
    branch: 'dev',
    commit_sha: 'fedcba0987654321',
    status: 'syncing',
    file_count: 85,
    last_synced: '2026-08-30 11:00:00',
    auto_sync: 0,
  },
  {
    id: 3,
    name: 'docs-repo',
    url: 'https://github.com/example/docs-repo.git',
    branch: 'main',
    status: 'error',
    last_error: 'Connection timeout',
    file_count: 10,
    auto_sync: 1,
  },
  {
    id: 4,
    name: 'pending-repo',
    url: 'https://github.com/example/pending-repo.git',
    branch: 'main',
    status: 'pending',
    file_count: 0,
    auto_sync: 1,
  },
];

const mockSyncStates: Record<number, GitSyncJob> = {
  2: {
    repo_id: 2,
    repo_name: 'frontend-app',
    status: 'syncing',
    step: 4,
    total_steps: 5,
    step_name: 'Parsing AST Symbols & API Routes',
    current_file: 'src/components/Dashboard.tsx',
    processed_files: 68,
    total_files: 85,
    percent: 80,
    started_at: Date.now() - 25000,
    updated_at: Date.now(),
    logs: [
      { timestamp: '12:00:01', level: 'info', message: 'Started sync' },
    ],
  },
};

describe('RepoListTable Component', () => {
  it('renders empty state when repos array is empty', () => {
    render(
      <RepoListTable
        repos={[]}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getAllByText(/No Git repositories registered/i)[0]).toBeInTheDocument();
  });

  it('renders repos with standard statuses (synced, error, pending)', () => {
    render(
      <RepoListTable
        repos={mockRepos}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getAllByText('backend-core')[0]).toBeInTheDocument();
    expect(screen.getAllByText('abcdef12')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Synced')[0]).toBeInTheDocument();

    expect(screen.getAllByText('docs-repo')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Error')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Connection timeout')[0]).toBeInTheDocument();

    expect(screen.getAllByText('pending-repo')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Pending')[0]).toBeInTheDocument();
  });

  it('renders multi-phase progress badge, progress bar, and active file caption when syncing', () => {
    render(
      <RepoListTable
        repos={mockRepos}
        syncStates={mockSyncStates}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
        onOpenSyncDrawer={vi.fn()}
      />
    );

    // Should render step chip / badge text
    expect(screen.getAllByText(/Step 4\/5: Parsing AST Symbols & API Routes \(80%\)/i)[0]).toBeInTheDocument();

    // Should render current file caption
    expect(screen.getAllByText('src/components/Dashboard.tsx')[0]).toBeInTheDocument();

    // Progress bar width should match percent
    const progressBars = document.querySelectorAll('.sync-progress-bar-fill');
    expect(progressBars.length).toBeGreaterThan(0);
    const fillElement = Array.from(progressBars).find(
      (el) => (el as HTMLElement).style.width === '80%'
    );
    expect(fillElement).toBeDefined();
  });

  it('clicking progress badge or progress bar container calls onOpenSyncDrawer with repo id', () => {
    const onOpenSyncDrawer = vi.fn();

    render(
      <RepoListTable
        repos={mockRepos}
        syncStates={mockSyncStates}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
        onOpenSyncDrawer={onOpenSyncDrawer}
      />
    );

    const progressPill = screen.getAllByText(/Step 4\/5: Parsing AST Symbols & API Routes \(80%\)/i)[0];
    fireEvent.click(progressPill);
    expect(onOpenSyncDrawer).toHaveBeenCalledWith(2);

    const progressContainers = document.querySelectorAll('.sync-progress-container');
    expect(progressContainers.length).toBeGreaterThan(0);
    fireEvent.click(progressContainers[0]);
    expect(onOpenSyncDrawer).toHaveBeenCalledWith(2);
  });

  it('renders Live Logs button in actions and triggers onOpenSyncDrawer on click', () => {
    const onOpenSyncDrawer = vi.fn();

    render(
      <RepoListTable
        repos={mockRepos}
        syncStates={mockSyncStates}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
        onOpenSyncDrawer={onOpenSyncDrawer}
      />
    );

    const logsButtons = screen.getAllByTitle('View Ingestion Logs');
    expect(logsButtons.length).toBeGreaterThan(0);
    fireEvent.click(logsButtons[0]);
    expect(onOpenSyncDrawer).toHaveBeenCalledWith(1);
  });

  it('handles onSync, onToggleAutoSync, onOpenWebhook, and onDelete callbacks', () => {
    const onSync = vi.fn();
    const onToggleAutoSync = vi.fn();
    const onOpenWebhook = vi.fn();
    const onDelete = vi.fn();

    render(
      <RepoListTable
        repos={mockRepos}
        onSync={onSync}
        onToggleAutoSync={onToggleAutoSync}
        onOpenWebhook={onOpenWebhook}
        onDelete={onDelete}
      />
    );

    // Sync button
    const syncButtons = screen.getAllByTitle('Trigger Sync');
    fireEvent.click(syncButtons[0]);
    expect(onSync).toHaveBeenCalledWith(1);

    // Auto-sync button
    const autoSyncButtons = screen.getAllByLabelText('Toggle auto-sync for backend-core');
    fireEvent.click(autoSyncButtons[0]);
    expect(onToggleAutoSync).toHaveBeenCalledWith(1, true);

    // Webhook button
    const webhookButtons = screen.getAllByTitle('Webhook Setup');
    fireEvent.click(webhookButtons[0]);
    expect(onOpenWebhook).toHaveBeenCalledWith(mockRepos[0]);

    // Delete button
    const deleteButtons = screen.getAllByTitle('Delete Repo');
    fireEvent.click(deleteButtons[0]);
    expect(onDelete).toHaveBeenCalledWith(1, 'backend-core');
  });

  it('renders fallback progress information when sync job is syncing but without active job state', () => {
    render(
      <RepoListTable
        repos={mockRepos}
        syncStates={{}}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    // Repo 2 is syncing but not in syncStates -> fallback step 1/5: Syncing... (0%)
    expect(screen.getAllByText(/Step 1\/5: Syncing\.\.\. \(0%\)/i)[0]).toBeInTheDocument();
  });

  it('renders mobile card with progress bar, active file caption, and logs action button', () => {
    render(
      <RepoListTable
        repos={mockRepos}
        syncStates={mockSyncStates}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
        onOpenSyncDrawer={vi.fn()}
      />
    );

    const mobileCards = document.querySelectorAll('.data-mobile-card');
    expect(mobileCards.length).toBe(4);

    // Mobile card for repo 2 should have progress container
    const mobileSyncCard = mobileCards[1];
    expect(mobileSyncCard.textContent).toContain('Step 4/5');
    expect(mobileSyncCard.textContent).toContain('src/components/Dashboard.tsx');
  });
});
