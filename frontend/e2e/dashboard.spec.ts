import { test, expect } from '@playwright/test';
import { navigateToTab, setupDashboardRouteMocks } from './fixtures/dashboardRouteMocks';

test.beforeEach(async ({ page }) => {
  await setupDashboardRouteMocks(page);
  await page.goto('/');
});

test('1. navigates through all tabs including Diagnostics & Logs', async ({ page, isMobile }) => {
  // Header and engine state
  await expect(page.locator('h1', { hasText: 'ContextCortex' })).toBeVisible();
  await expect(page.getByText(/v2\.\d+\.\d+/)).toBeVisible();
  await expect(page.getByText('knowledge_rag_v1')).toBeVisible();
  await expect(page.locator('.header-status')).toContainText('Qdrant (Embedded)');
  await expect(page.locator('.header-status')).toContainText('Healthy');

  // Overview tab
  await expect(page.getByText('System & Embedding Specs')).toBeVisible();
  await expect(page.getByText('Top Extracted Topics & Symbols')).toBeVisible();
  await expect(page.getByText('fastapi', { exact: true })).toBeVisible();
  await expect(page.getByText('tree-sitter', { exact: true })).toBeVisible();
  await expect(page.getByText('qdrant', { exact: true })).toBeVisible();

  // Git Repositories tab
  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();
  if (isMobile) {
    await expect(page.locator('.mobile-card-list').getByText('knowledge-rag-mcp', { exact: true })).toBeVisible();
  } else {
    await expect(page.locator('.desktop-table-view').getByText('knowledge-rag-mcp', { exact: true })).toBeVisible();
  }

  // Local Paths tab
  await navigateToTab(page, 'Local Paths');
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();

  // Search & Inspector tab
  await navigateToTab(page, 'Search & Inspector');
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Settings tab
  await navigateToTab(page, 'Settings');
  await expect(page.getByText('AI & Model Gateway').first()).toBeVisible();

  // Diagnostics & Logs tab
  await navigateToTab(page, 'Diagnostics & Logs');
  await expect(page.getByText('Diagnostics & Server Logs')).toBeVisible();
});

test('8. executes hybrid search with target type toggle (code vs doc) and repo filter', async ({ page }) => {
  let lastSearchPayload: any = null;

  await page.route('**/admin/api/search/test', async route => {
    lastSearchPayload = route.request().postDataJSON();
    if (lastSearchPayload.type === 'doc') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: lastSearchPayload.query,
          type: 'doc',
          results: [
            {
              score: 0.0385,
              payload: {
                repo: 'docs-vault',
                rel_path: 'docs/architecture.md',
                start_line: 1,
                end_line: 25,
                content: '# System Architecture\nHybrid Qdrant + Tree-sitter AST RAG system.'
              }
            }
          ]
        })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: lastSearchPayload.query,
          type: 'code',
          results: [
            {
              score: 0.045,
              payload: {
                repo: 'knowledge-rag-mcp',
                rel_path: 'app/api/auth.py',
                symbol: 'verify_token',
                start_line: 12,
                end_line: 35,
                content: 'def verify_token(token: str):\n    return True',
                github_url: 'https://github.com/example/knowledge-rag-mcp/blob/main/app/api/auth.py'
              }
            }
          ]
        })
      });
    }
  });

  await navigateToTab(page, 'Search & Inspector');
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Test Code Search
  await page.getByPlaceholder(/e.g. JWT token/).fill('verify_token auth');
  await page.locator('input[placeholder="All Repos"]').fill('knowledge-rag-mcp');
  await page.locator('button[type="submit"]').click();

  expect(lastSearchPayload.query).toBe('verify_token auth');
  expect(lastSearchPayload.type).toBe('code');
  expect(lastSearchPayload.repo).toBe('knowledge-rag-mcp');

  await expect(page.getByText('app/api/auth.py')).toBeVisible();
  await expect(page.getByText('verify_token', { exact: true })).toBeVisible();
  await expect(page.getByText('Score: 4.5% (0.0450)')).toBeVisible();
  await expect(page.getByText('View on GitHub')).toBeVisible();

  // Toggle to Doc Search
  await page.locator('.search-bar select, .dashboard-main select').first().selectOption('doc');
  await page.getByPlaceholder(/e.g. JWT token/).fill('architecture overview');
  await page.locator('button[type="submit"]').click();

  expect(lastSearchPayload.query).toBe('architecture overview');
  expect(lastSearchPayload.type).toBe('doc');

  await expect(page.getByText('docs/architecture.md')).toBeVisible();
  await expect(page.getByText('Score: 3.9% (0.0385)')).toBeVisible();
  await expect(page.getByText('# System Architecture')).toBeVisible();
});

test('9. handles empty search query and error response states', async ({ page }) => {
  await navigateToTab(page, 'Search & Inspector');
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Form input validation for empty search
  const queryInput = page.getByPlaceholder(/e.g. JWT token/);
  await expect(queryInput).toHaveAttribute('required', '');

  // Search error response
  await page.route('**/admin/api/search/test', async route => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'Qdrant hybrid vector index unavailable' })
    });
  });

  await queryInput.fill('trigger failure');
  await page.locator('button[type="submit"]').click();

  await expect(page.locator('.toast-error', { hasText: 'Search failed: Qdrant hybrid vector index unavailable' })).toBeVisible();
  await expect(page.getByText('Search error: Qdrant hybrid vector index unavailable')).toBeVisible();

  // Search empty results response
  await page.route('**/admin/api/search/test', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        query: 'unmatched query',
        type: 'code',
        results: []
      })
    });
  });

  await queryInput.fill('unmatched query');
  await page.locator('button[type="submit"]').click();

  await expect(page.getByText('No matching results found in index.')).toBeVisible();
});

test('12. triggers Reindex All Sources on Overview tab', async ({ page }) => {
  let reindexTriggered = false;

  await page.route('**/admin/api/reindex', async route => {
    reindexTriggered = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'indexing_started' })
    });
  });

  // Default Overview tab is loaded
  await expect(page.getByText('System & Embedding Specs')).toBeVisible();

  const reindexBtn = page.getByRole('button', { name: 'Reindex All Sources' });
  await expect(reindexBtn).toBeVisible();
  await reindexBtn.click();

  await expect.poll(() => reindexTriggered).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'Re-indexing triggered successfully' })).toBeVisible();
});

test('13. filters, searches, and clears logs in Diagnostics & Logs tab', async ({ page }) => {
  await navigateToTab(page, 'Diagnostics & Logs');
  await expect(page.getByText('Diagnostics & Server Logs')).toBeVisible();

  // Verify filter pills and initial count
  const allPill = page.locator('button.log-filter-btn', { hasText: 'ALL' });
  const infoPill = page.locator('button.log-filter-btn', { hasText: 'INFO' });
  const warnPill = page.locator('button.log-filter-btn', { hasText: 'WARNING' });
  const errPill = page.locator('button.log-filter-btn', { hasText: 'ERROR' });
  const debugPill = page.locator('button.log-filter-btn', { hasText: 'DEBUG' });

  await expect(allPill).toContainText('4');
  await expect(infoPill).toContainText('1');
  await expect(warnPill).toContainText('1');
  await expect(errPill).toContainText('1');
  await expect(debugPill).toContainText('1');

  // Verify all 4 log entries initially visible
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).toBeVisible();
  await expect(page.getByText('High memory consumption during dense vector generation')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();
  await expect(page.getByText('Parsed 12 symbols in file app/api/auth.py')).toBeVisible();

  // Filter by ERROR
  await errPill.click();
  await expect(errPill).toHaveClass(/active/);
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).not.toBeVisible();
  await expect(page.getByText('High memory consumption during dense vector generation')).not.toBeVisible();

  // Filter by WARNING
  await warnPill.click();
  await expect(warnPill).toHaveClass(/active/);
  await expect(page.getByText('High memory consumption during dense vector generation')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).not.toBeVisible();

  // Reset to ALL
  await allPill.click();
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();

  // Search logs by text query
  const searchInput = page.locator('input.log-search-input');
  await searchInput.fill('ast_parser');
  await expect(page.getByText('Parsed 12 symbols in file app/api/auth.py')).toBeVisible();
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).not.toBeVisible();

  // Clear search input using clear button
  const clearSearchBtn = page.locator('button.clear-search-btn');
  await clearSearchBtn.click();
  await expect(searchInput).toHaveValue('');
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).toBeVisible();

  // Toggle stack trace on error log
  const toggleTraceBtn = page.locator('button.btn-traceback-toggle');
  await expect(toggleTraceBtn).toBeVisible();
  await expect(toggleTraceBtn).toContainText('View Stack Trace');
  await toggleTraceBtn.click();

  await expect(page.locator('.traceback-box')).toBeVisible();
  await expect(page.locator('.traceback-box')).toContainText('GitCommandError: auth failed');
  await expect(toggleTraceBtn).toContainText('Hide Stack Trace');

  await toggleTraceBtn.click();
  await expect(page.locator('.traceback-box')).not.toBeVisible();

  // Clear all logs with confirmation dialog
  let clearPrompt = '';
  page.on('dialog', async dialog => {
    clearPrompt = dialog.message();
    await dialog.accept();
  });

  let logsCleared = false;
  await page.route('**/admin/api/logs', async route => {
    if (route.request().method() === 'DELETE') {
      logsCleared = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'cleared' })
      });
    } else {
      await route.fallback();
    }
  });

  await page.getByRole('button', { name: 'Clear Logs' }).click();

  expect(clearPrompt).toContain('Are you sure you want to clear all server diagnostics logs?');
  expect(logsCleared).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'Diagnostics logs cleared.' })).toBeVisible();
  await expect(page.getByText(/No logs available/)).toBeVisible();
});

test('14. [Mobile] hamburger menu button opens and closes navigation drawer', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });

  const menuToggle = page.locator('button.menu-toggle-btn');
  await expect(menuToggle).toBeVisible();

  const navDrawer = page.locator('.dashboard-nav');
  await expect(navDrawer).not.toHaveClass(/drawer-open/);

  // Open drawer
  await menuToggle.click();
  await expect(navDrawer).toHaveClass(/drawer-open/);
  await expect(page.locator('.nav-tab', { hasText: 'Overview' })).toBeVisible();
  await expect(page.locator('.nav-tab', { hasText: 'Git Repositories' })).toBeVisible();
  await expect(page.locator('.nav-tab', { hasText: 'Files & Storage' })).toBeVisible();
  await expect(page.locator('.nav-tab', { hasText: 'Search & Inspector' })).toBeVisible();
  await expect(page.locator('.nav-tab', { hasText: 'Settings' })).toBeVisible();
  await expect(page.locator('.nav-tab', { hasText: 'Diagnostics & Logs' })).toBeVisible();

  // Close drawer
  await menuToggle.click();
  await expect(navDrawer).not.toHaveClass(/drawer-open/);
});

test('15. [Mobile] selecting a tab in drawer navigates to view and auto-closes drawer', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });

  const menuToggle = page.locator('button.menu-toggle-btn');
  const navDrawer = page.locator('.dashboard-nav');

  // Open drawer
  await menuToggle.click();
  await expect(navDrawer).toHaveClass(/drawer-open/);

  // Click Git Repositories tab
  await page.locator('.nav-tab', { hasText: 'Git Repositories' }).click();

  // Drawer should auto-close and view should switch
  await expect(navDrawer).not.toHaveClass(/drawer-open/);
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Open drawer again and switch to Search & Inspector
  await menuToggle.click();
  await page.locator('.nav-tab', { hasText: 'Search & Inspector' }).click();
  await expect(navDrawer).not.toHaveClass(/drawer-open/);
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();
});

test('20. [Mobile] performs search and renders responsive result item on mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Search & Inspector');

  await page.getByPlaceholder(/e.g. JWT token/).fill('verify_token auth');
  await page.locator('button[type="submit"]').click();

  // Verify result card on mobile
  const resultCard = page.locator('.search-hit-card');
  await expect(resultCard).toBeVisible();
  await expect(resultCard.getByText('app/api/auth.py')).toBeVisible();
  await expect(resultCard.getByText('verify_token', { exact: true })).toBeVisible();
  await expect(resultCard.getByText('Score: 4.5% (0.0450)')).toBeVisible();
  await expect(resultCard.getByText('View on GitHub')).toBeVisible();
  await expect(resultCard.locator('pre.search-hit-code')).toContainText('def verify_token');
});

test('21. [Mobile] log viewer filter pills, search bar, and traceback toggle operate cleanly on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Diagnostics & Logs');

  // Verify pills
  const errPill = page.locator('button.log-filter-btn', { hasText: 'ERROR' });
  await expect(errPill).toBeVisible();
  await errPill.click();

  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();
  await expect(page.getByText('Indexing completed for repository knowledge-rag-mcp')).not.toBeVisible();

  // Toggle traceback on mobile
  const toggleBtn = page.locator('button.btn-traceback-toggle');
  await expect(toggleBtn).toBeVisible();
  await toggleBtn.click();

  await expect(page.locator('.traceback-box')).toBeVisible();
  await expect(page.locator('.traceback-box')).toContainText('GitCommandError: auth failed');

  await toggleBtn.click();
  await expect(page.locator('.traceback-box')).not.toBeVisible();
});
