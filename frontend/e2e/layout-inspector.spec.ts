import { test, expect } from '@playwright/test';
import 'playwright-layout-inspector/matchers';
import { LayoutInspector, getDevicePreset } from 'playwright-layout-inspector';

const mockStats = {
  repos_count: 3,
  symbols_count: 1250,
  files_count: 42,
  points_count: 3200,
  last_indexed: '2026-08-30 18:30:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1',
  vector_db_status: 'Healthy',
  rate_limit: { remaining: 4950, limit: 5000 },
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant', 'vitest', 'playwright', 'rag'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234'
};

const mockVectorStore = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant_db',
  url: null,
  collection: 'knowledge_rag_v1',
  healthy: true,
  health_message: 'Healthy',
  points_count: 3200
};

const mockRepos = [
  {
    id: 1,
    name: 'knowledge-rag-mcp',
    url: 'https://github.com/example/knowledge-rag-mcp.git',
    branch: 'main',
    commit_sha: '687f7b1abcde12345',
    status: 'synced',
    file_count: 25,
    last_synced: '2026-08-30 18:00:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: 'whsec_test123'
  },
  {
    id: 2,
    name: 'backend-core',
    url: 'https://gitlab.com/example/backend-core.git',
    branch: 'dev',
    commit_sha: '12345678abcdef',
    status: 'synced',
    file_count: 64,
    last_synced: '2026-08-30 17:30:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: null
  }
];

const mockPaths = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: 1,
    category: 'architecture',
    enabled: 1
  }
];

const mockAutoSyncSettings = {
  interval_mins: 15,
  webhook_url: '/api/webhooks/git',
  has_global_secret: true
};

const mockEmbeddingSettings = {
  provider: 'local',
  dense_model: 'BAAI/bge-small-en-v1.5',
  sparse_model: 'Qdrant/bm25',
  threads: 4,
  batch_size: 32,
  system_cpus: 8,
  system_memory_gb: 16.0,
  litellm_url: 'http://litellm:4000/v1'
};

const mockHosts = [
  {
    id: 1,
    host: 'gitlab.enterprise.internal',
    provider: 'gitlab',
    auth_user: 'ci-runner',
    masked_token: 'glpat_****9999',
    added_at: '2026-08-30 12:00:00'
  }
];

const mockLogs = [
  {
    timestamp: '2026-08-30 18:30:00',
    level: 'INFO',
    message: 'Global re-indexing completed successfully (42 files, 3200 vectors).',
    traceback: null
  },
  {
    timestamp: '2026-08-30 18:25:00',
    level: 'WARNING',
    message: 'GitHub rate limit threshold nearing 90% capacity.',
    traceback: null
  }
];

const mockTopology = {
  nodes: [
    { id: 'app/main.py', name: 'main.py', type: 'file', filepath: 'app/main.py', node_type: 'file', symbol_count: 5 },
    { id: 'app/api/auth.py', name: 'auth.py', type: 'file', filepath: 'app/api/auth.py', node_type: 'file', symbol_count: 3 },
    { id: 'app/services/vector_store.py', name: 'vector_store.py', type: 'file', filepath: 'app/services/vector_store.py', node_type: 'file', symbol_count: 8 }
  ],
  edges: [
    { source: 'app/main.py', target: 'app/api/auth.py', type: 'imports' },
    { source: 'app/main.py', target: 'app/services/vector_store.py', type: 'imports' }
  ]
};

async function setupLayoutMocks(page: any) {
  await page.route('**/admin/api/stats', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStats) });
  });
  await page.route('**/admin/api/vector-store', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockVectorStore) });
  });
  await page.route('**/admin/api/repos', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockRepos) });
  });
  await page.route('**/admin/api/repos/sync-status', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
  await page.route('**/admin/api/repos/sync/stream', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: init\ndata: {}\n\n' });
  });
  await page.route('**/admin/api/paths', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPaths) });
  });
  await page.route('**/admin/api/settings/auto-sync', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAutoSyncSettings) });
  });
  await page.route('**/admin/api/settings/embedding', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmbeddingSettings) });
  });
  await page.route('**/admin/api/settings/hosts', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockHosts) });
  });
  await page.route('**/admin/api/logs', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) });
  });
  await page.route('**/admin/api/graph/topology*', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockTopology) });
  });
}

async function navigateTab(page: any, tabName: string) {
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

test.describe('Playwright Layout Inspector UI UX Audits', () => {
  test.beforeEach(async ({ page }) => {
    await setupLayoutMocks(page);
    await page.goto('/');
  });

  test('1. Overview Tab - Desktop Layout Audit (1080p)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect(page.locator('h1', { hasText: 'ContextCortex' })).toBeVisible();

    // 1. Assert zero horizontal overflow / bleed
    await expect(page).toHaveNoLayoutOverflow();

    // 2. Run comprehensive layout inspector audit
    const inspector = new LayoutInspector(page);
    const audit = await inspector.audit({
      device: getDevicePreset('Desktop 1080p'),
      includeScreenshot: false,
    });

    expect(audit.uxScore.totalScore).toBeGreaterThanOrEqual(80);
    expect(audit.overflowIssues.length).toBe(0);
  });

  test('2. Overview Tab - Samsung Galaxy S25+ Mobile Layout & Touch Ergonomics', async ({ page }) => {
    const s25plus = getDevicePreset('Samsung Galaxy S25+');
    await page.setViewportSize({ width: s25plus.width, height: s25plus.height });

    await expect(page.locator('h1', { hasText: 'ContextCortex' })).toBeVisible();

    // 1. Zero horizontal overflow
    await expect(page).toHaveNoLayoutOverflow();

    // 2. Mobile fit and viewport compliance
    await expect(page).toHaveMobileFit();

    // 3. Composite score check
    await expect(page).toPassLayoutAudit({ minScore: 80 });
  });

  test('3. Git Repositories Tab - Mobile Card Layout & Action Touch Targets', async ({ page }) => {
    const s25 = getDevicePreset('Samsung Galaxy S25');
    await page.setViewportSize({ width: s25.width, height: s25.height });

    await navigateTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Assert cards are rendered without overflow
    await expect(page.locator('.mobile-card-list')).toBeVisible();
    await expect(page).toHaveNoLayoutOverflow();

    const inspector = new LayoutInspector(page);
    const audit = await inspector.audit({ device: s25 });
    expect(audit.overflowIssues.length).toBe(0);
    expect(audit.uxScore.totalScore).toBeGreaterThanOrEqual(75);
  });

  test('4. Local Paths Tab - Mobile Card Layout Stability', async ({ page }) => {
    const iphone = getDevicePreset('iPhone 16 Pro');
    await page.setViewportSize({ width: iphone.width, height: iphone.height });

    await navigateTab(page, 'Local Paths');
    await expect(page.getByText('Monitored Local Paths')).toBeVisible();
    await expect(page.locator('.mobile-card-list')).toBeVisible();

    await expect(page).toHaveNoLayoutOverflow();
    await expect(page).toHaveMobileFit();
  });

  test('5. Settings Tab - Vector Store & Embedding Engine Layout Audit', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await navigateTab(page, 'Settings');

    await expect(page.getByText('Vector Database Engine')).toBeVisible();
    await expect(page.getByText('Embedding Engine & Resource Limits')).toBeVisible();

    await expect(page).toHaveNoLayoutOverflow();

    const inspector = new LayoutInspector(page);
    const audit = await inspector.audit();
    expect(audit.overflowIssues.length).toBe(0);
  });

  test('6. Diagnostics & Logs Tab - Log Container & Filter Layout Stability', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await navigateTab(page, 'Diagnostics & Logs');

    await expect(page.getByText('Diagnostics & Server Logs')).toBeVisible();
    await expect(page).toHaveNoLayoutOverflow();

    // Verify filter toolbar responsiveness
    const filterPills = page.locator('.log-filter-btn');
    await expect(filterPills.first()).toBeVisible();
  });

  test('7. Add Repository Modal - Layout Shift & Center Alignment', async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 852 });
    await navigateTab(page, 'Git Repositories');

    // Measure layout shift during modal open
    await expect(page).toHaveAcceptableLayoutShift(
      async () => {
        await page.getByRole('button', { name: 'Add Repository' }).click();
        await expect(page.locator('.modal-card')).toBeVisible();
      },
      { maxAcceptableScore: 0.15 }
    );

    // Modal dialog itself should not cause viewport overflow
    await expect(page).toHaveNoLayoutOverflow();

    // Close modal
    await page.locator('button.btn-close').click();
    await expect(page.locator('.modal-card')).not.toBeVisible();
  });
});
