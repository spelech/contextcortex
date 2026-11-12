import type { Page } from '@playwright/test';
import type { GitSyncJob } from '../../src/types';

export const mockGitSyncStats = {
  repos_count: 2,
  symbols_count: 500,
  files_count: 15,
  points_count: 1000,
  last_indexed: '2026-08-31 12:00:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1',
  rate_limit: { remaining: 5000, limit: 5000 },
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234',
};

export const mockGitSyncVectorStore = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant',
  url: '',
  collection: 'knowledge_rag_v1',
};

export const mockGitSyncRepos = [
  {
    id: 1,
    name: 'contextcortex-core',
    url: 'https://github.com/spelech/contextcortex.git',
    branch: 'main',
    commit_sha: 'a1b2c3d4e5',
    status: 'syncing',
    file_count: 45,
    last_synced: '2026-08-31 10:00:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: null,
    provider: 'github',
  },
  {
    id: 2,
    name: 'docs-vault',
    url: 'https://github.com/spelech/docs-vault.git',
    branch: 'main',
    commit_sha: 'f6e5d4c3b2',
    status: 'error',
    file_count: 12,
    last_synced: '2026-08-30 08:00:00',
    last_error: 'Authentication failed: SSH key rejected',
    auto_sync: 0,
    webhook_secret: null,
    provider: 'github',
  },
  {
    id: 3,
    name: 'api-service',
    url: 'https://gitlab.com/example/api-service.git',
    branch: 'main',
    commit_sha: '9876543210',
    status: 'synced',
    file_count: 88,
    last_synced: '2026-08-31 11:30:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: null,
    provider: 'gitlab',
  },
];

export const mockSyncingJob: GitSyncJob = {
  repo_id: 1,
  repo_name: 'contextcortex-core',
  status: 'syncing',
  step: 3,
  total_steps: 5,
  step_name: 'Computing File Delta & Scanning',
  current_file: 'src/services/git.ts',
  processed_files: 9,
  total_files: 20,
  percent: 45,
  started_at: Math.floor(Date.now() / 1000) - 30,
  updated_at: Math.floor(Date.now() / 1000),
  logs: [
    { timestamp: '14:00:01', level: 'INFO', message: 'Connecting to remote repository...' },
    { timestamp: '14:00:05', level: 'INFO', message: 'Cloned branch main with commit a1b2c3d4' },
    { timestamp: '14:00:10', level: 'DEBUG', message: 'Comparing previous commit tree' },
    { timestamp: '14:00:15', level: 'INFO', message: 'Scanning 20 files for modifications' },
    { timestamp: '14:00:20', level: 'WARN', message: 'Large file detected: data/vectors.bin' },
  ],
  cancelled: false,
};

export const mockErrorJob: GitSyncJob = {
  repo_id: 2,
  repo_name: 'docs-vault',
  status: 'error',
  step: 2,
  total_steps: 5,
  step_name: 'Shallow Cloning Repository',
  current_file: null,
  processed_files: 0,
  total_files: 0,
  percent: 20,
  started_at: Math.floor(Date.now() / 1000) - 60,
  updated_at: Math.floor(Date.now() / 1000),
  error: 'Authentication failed: SSH key rejected',
  logs: [
    { timestamp: '13:55:01', level: 'INFO', message: 'Initiating SSH handshake with git server' },
    { timestamp: '13:55:04', level: 'ERROR', message: 'Permission denied (publickey). SSH key rejected' },
  ],
  cancelled: false,
};

export const mockSyncedJob: GitSyncJob = {
  repo_id: 3,
  repo_name: 'api-service',
  status: 'synced',
  step: 5,
  total_steps: 5,
  step_name: 'Upserting Embeddings & Finalizing',
  current_file: null,
  processed_files: 88,
  total_files: 88,
  percent: 100,
  started_at: Math.floor(Date.now() / 1000) - 120,
  updated_at: Math.floor(Date.now() / 1000),
  logs: [
    { timestamp: '13:40:01', level: 'INFO', message: 'Sync started for api-service' },
    { timestamp: '13:40:15', level: 'INFO', message: 'Parsed 142 symbols and 28 API routes' },
    { timestamp: '13:40:30', level: 'INFO', message: 'Upserted 88 points into Qdrant collection' },
    { timestamp: '13:40:35', level: 'INFO', message: 'Ingestion completed successfully in 34s' },
  ],
  cancelled: false,
};

export async function navigateToGitSyncTab(page: Page, tabName: string): Promise<void> {
  const menuToggle = page.locator('button.menu-toggle-btn');
  if (await menuToggle.isVisible()) {
    const isDrawerOpen = await page.locator('.dashboard-nav.drawer-open').isVisible();
    if (!isDrawerOpen) {
      await menuToggle.click();
    }
  }
  const tab = page.locator('button.nav-tab', { hasText: tabName });
  await tab.click();
}

export async function setupGitSyncRouteMocks(page: Page): Promise<void> {
  await page.route('**/admin/api/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockGitSyncStats),
    });
  });

  await page.route('**/admin/api/vector-store', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockGitSyncVectorStore),
    });
  });

  await page.route('**/admin/api/repos', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockGitSyncRepos),
      });
    } else {
      await route.fallback();
    }
  });

  const mockSyncSnapshot = {
    1: mockSyncingJob,
    2: mockErrorJob,
    3: mockSyncedJob,
  };

  await page.route('**/admin/api/repos/sync-status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncSnapshot),
    });
  });

  await page.route('**/admin/api/repos/sync/stream', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: init\ndata: ${JSON.stringify(mockSyncSnapshot)}\n\n`,
    });
  });

  await page.route('**/admin/api/paths', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.route('**/admin/api/logs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
}
