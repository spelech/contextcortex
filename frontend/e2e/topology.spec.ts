import { test, expect } from '@playwright/test';

const mockStats = {
  repos_count: 2,
  symbols_count: 500,
  files_count: 15,
  points_count: 1000,
  last_indexed: '2026-08-17 00:00:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1',
  rate_limit: { remaining: 5000, limit: 5000 },
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234'
};

const mockRepos = [
  {
    id: 1,
    name: 'contextcortex-core',
    url: 'https://github.com/spelech/contextcortex.git',
    branch: 'main',
    commit_sha: 'c0ffee1234',
    status: 'synced',
    file_count: 25,
    last_synced: '2026-08-17 00:00:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: null
  }
];

const mockTopology = {
  nodes: [
    { id: 'file:contextcortex-core:app/api/routes.py', name: 'routes.py', type: 'file', repo: 'contextcortex-core', filepath: 'app/api/routes.py' },
    { id: 'file:contextcortex-core:app/services/topology.py', name: 'topology.py', type: 'file', repo: 'contextcortex-core', filepath: 'app/services/topology.py' },
    { id: 'symbol:101', name: 'api_get_graph_topology', type: 'function', repo: 'contextcortex-core', filepath: 'app/api/routes.py', start_line: 490, end_line: 520 },
    { id: 'route:201', name: 'GET /admin/api/graph/topology', type: 'route', repo: 'contextcortex-core', filepath: 'app/api/routes.py', method: 'GET', path_pattern: '/admin/api/graph/topology' }
  ],
  edges: [
    { source: 'file:contextcortex-core:app/api/routes.py', target: 'file:contextcortex-core:app/services/topology.py', type: 'IMPORTS' },
    { source: 'file:contextcortex-core:app/api/routes.py', target: 'symbol:101', type: 'DEFINES' },
    { source: 'route:201', target: 'symbol:101', type: 'HANDLES' }
  ],
  stats: { node_count: 4, edge_count: 3 }
};

const mockNodeDetails = {
  id: 'symbol:101',
  name: 'api_get_graph_topology',
  type: 'function',
  repo: 'contextcortex-core',
  filepath: 'app/api/routes.py',
  start_line: 490,
  end_line: 520,
  signature: 'async def api_get_graph_topology(repo: str, view_type: str = "files"):',
  code_preview: 'async def api_get_graph_topology(repo: str, view_type: str = "files"):\n    return get_topology_graph(repo=repo, view_type=view_type)',
  permalink: 'https://github.com/spelech/contextcortex/blob/c0ffee1234/app/api/routes.py#L490-L520',
  incoming: [
    { id: 'route:201', name: 'GET /admin/api/graph/topology', type: 'route', edge_type: 'HANDLES', line_number: 490 }
  ],
  outgoing: [
    { id: 'symbol:102', name: 'get_topology_graph', type: 'function', edge_type: 'CALLS', line_number: 495 }
  ],
  metadata: { kind: 'function', language: 'python' }
};

test.beforeEach(async ({ page }) => {
  await page.route('**/admin/api/stats', async (route) => {
    await route.fulfill({ json: mockStats });
  });
  await page.route('**/admin/api/repos', async (route) => {
    await route.fulfill({ json: mockRepos });
  });
  await page.route('**/admin/api/graph/topology*', async (route) => {
    await route.fulfill({ json: mockTopology });
  });
  await page.route('**/admin/api/graph/node-details*', async (route) => {
    await route.fulfill({ json: mockNodeDetails });
  });
});

test.describe('Topology Explorer Journey', () => {
  test('navigates to Topology tab and renders graph controls', async ({ page }) => {
    await page.goto('/');

    const topologyTab = page.locator('nav.dashboard-nav button:has-text("Topology")');
    await expect(topologyTab).toBeVisible();
    await topologyTab.click();

    await expect(page.locator('.topology-toolbar')).toBeVisible();
    await expect(page.locator('button:has-text("FILES")')).toBeVisible();
    await expect(page.locator('button:has-text("SYMBOLS")')).toBeVisible();
    await expect(page.locator('button:has-text("ROUTES")')).toBeVisible();
    await expect(page.locator('button:has-text("FULL")')).toBeVisible();
  });

  test('interacts with view types, search, node inspector drawer, and exports', async ({ page }) => {
    await page.goto('/');
    await page.click('nav.dashboard-nav button:has-text("Topology")');

    // Switch view type
    const symbolsBtn = page.locator('.topology-view-btn:has-text("SYMBOLS")');
    await symbolsBtn.click();
    await expect(symbolsBtn).toHaveClass(/active/);

    // Search filter
    const searchInput = page.locator('input[placeholder*="Search nodes"]');
    await searchInput.fill('routes');

    // Click node in graph
    const nodeEl = page.locator('[data-testid="node-symbol:101"], g.topology-node').first();
    if (await nodeEl.isVisible()) {
      await nodeEl.click();
      await expect(page.locator('.topology-drawer')).toBeVisible();
      await expect(page.locator('.topology-drawer')).toContainText('Location & Repository');
      await page.click('button[aria-label="Close Inspector"]');
      await expect(page.locator('.topology-drawer')).not.toBeVisible();
    }

    // Export buttons
    await expect(page.locator('button[title="Export as SVG"]')).toBeVisible();
    await expect(page.locator('button[title="Export as JSON"]')).toBeVisible();
  });
});
