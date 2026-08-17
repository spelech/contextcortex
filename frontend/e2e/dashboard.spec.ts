import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Mock API endpoints to ensure independent deterministic tests
  await page.route('**/admin/api/stats', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        repos_count: 2,
        symbols_count: 500,
        files_count: 15,
        points_count: 1000,
        last_indexed: '2026-08-17 00:00:00',
        dense_model: 'bge-small-en-v1.5 (384d)',
        sparse_model: 'Qdrant/bm25',
        rate_limit: { remaining: 5000, limit: 5000 },
        top_keywords: ['fastapi', 'tree-sitter'],
        is_indexing: false,
        token_source: 'Database',
        masked_token: 'ghp_****1234'
      }),
    });
  });

  await page.route('**/admin/api/repos', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          name: 'notes-rag-mcp',
          url: 'https://github.com/example/notes-rag-mcp.git',
          branch: 'main',
          commit_sha: '687f7b1abcde12345',
          status: 'synced',
          file_count: 25,
          last_synced: '2026-08-17 00:00:00'
        }
      ]),
    });
  });

  await page.route('**/admin/api/paths', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          path: '/containers/dev/workspace/docs',
          repo: 'docs-vault',
          type: 'directory',
          recursive: true,
          category: 'architecture',
          enabled: true
        }
      ]),
    });
  });

  await page.route('**/admin/api/search/test', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        query: 'JWT auth',
        type: 'code',
        results: [
          {
            score: 0.045,
            payload: {
              repo: 'notes-rag-mcp',
              rel_path: 'app/api/auth.py',
              symbol: 'verify_token',
              start_line: 12,
              end_line: 35,
              content: 'def verify_token(token: str):\n    return True'
            }
          }
        ]
      })
    });
  });

  await page.goto('/');
});

test('has title, version badge, and basic UI elements', async ({ page }) => {
  await expect(page.locator('h1', { hasText: 'Code & Docs RAG Server' })).toBeVisible();
  await expect(page.getByText('v2.2.0')).toBeVisible();

  await expect(page.locator('button.nav-tab', { hasText: 'Overview' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Git Repositories' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Local Paths' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Search & Inspector' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Settings' })).toBeVisible();
});

test('navigates through tabs correctly', async ({ page }) => {
  // Check default Overview content
  await expect(page.getByText('System & Embedding Specs')).toBeVisible();

  // Navigate to Git Repositories
  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'notes-rag-mcp', exact: true })).toBeVisible();

  // Navigate to Local Paths
  await page.locator('button.nav-tab', { hasText: 'Local Paths' }).click();
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();
  await expect(page.getByText('/containers/dev/workspace/docs')).toBeVisible();

  // Navigate to Search & Inspector
  await page.locator('button.nav-tab', { hasText: 'Search & Inspector' }).click();
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Navigate to Settings
  await page.locator('button.nav-tab', { hasText: 'Settings' }).click();
  await expect(page.getByText('GitHub Authentication & Rate Limits')).toBeVisible();
});

test('opens and closes the Add Repository modal', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Open modal
  await page.getByRole('button', { name: 'Add Repository' }).click();
  await expect(page.getByText('Register Git Repository')).toBeVisible();

  // Close modal via Cancel button
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByText('Register Git Repository')).not.toBeVisible();
});

test('submits live search query and renders search hit cards', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Search & Inspector' }).click();
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Fill in search form
  await page.getByPlaceholder(/e.g. JWT token/).fill('JWT auth');
  await page.locator('button[type="submit"]').click();

  // Assert result card appears
  await expect(page.getByText('app/api/auth.py')).toBeVisible();
  await expect(page.getByText('verify_token', { exact: true })).toBeVisible();
  await expect(page.getByText('RRF Score: 0.0450')).toBeVisible();
});
