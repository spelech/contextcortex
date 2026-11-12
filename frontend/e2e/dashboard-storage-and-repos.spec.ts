import { test, expect } from '@playwright/test';
import {
  mockPaths,
  mockRepos,
  navigateToTab,
  setupDashboardRouteMocks,
} from './fixtures/dashboardRouteMocks';

test.beforeEach(async ({ page }) => {
  await setupDashboardRouteMocks(page);
  await page.goto('/');
});

test('2. adds a new Git repository via modal and verifies table/card update + toast', async ({ page, isMobile }) => {
  const repoList: any[] = [...mockRepos];

  await page.route('**/admin/api/repos', async route => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      const newRepo = {
        id: 3,
        name: payload.name,
        url: payload.url,
        branch: payload.branch || 'main',
        commit_sha: 'abcdef1234567890',
        status: 'pending' as const,
        file_count: 0,
        last_synced: 'Never'
      };
      repoList.push(newRepo);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(newRepo)
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(repoList)
      });
    }
  });

  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Open modal
  await page.getByRole('button', { name: 'Add Repository' }).click();
  await expect(page.getByText('Register Git Repository')).toBeVisible();

  // Fill form
  await page.locator('#repo-alias').fill('fastapi-service');
  await page.locator('#repo-url').fill('https://github.com/example/fastapi-service.git');
  await page.locator('#repo-branch').fill('main');
  await page.locator('#repo-token').fill('ghp_testtoken');

  // Submit form
  await page.getByRole('button', { name: 'Add & Start Sync' }).click();

  // Verify modal closed, toast displayed, and new repository row/card visible
  await expect(page.getByRole('heading', { name: 'Register Git Repository' })).not.toBeVisible();
  await expect(page.locator('.toast-success', { hasText: "Repository 'fastapi-service' added successfully" })).toBeVisible();
  if (isMobile) {
    await expect(page.locator('.mobile-card-list').getByText('fastapi-service', { exact: true })).toBeVisible();
  } else {
    await expect(page.locator('.desktop-table-view').getByText('fastapi-service', { exact: true })).toBeVisible();
  }
});

test('3. triggers single-repo sync and verifies status feedback', async ({ page, isMobile }) => {
  let syncRequested = false;

  await page.route('**/admin/api/repos/sync/1', async route => {
    syncRequested = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'syncing' })
    });
  });

  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Trigger sync on the first repo
  const syncBtn = isMobile
    ? page.locator('.mobile-card-list').locator('button[title="Trigger Sync"]').first()
    : page.locator('.desktop-table-view').locator('button[title="Trigger Sync"]').first();
  await syncBtn.click();

  expect(syncRequested).toBe(true);
  await expect(page.locator('.toast-info', { hasText: 'Sync triggered successfully' })).toBeVisible();
});

test('4. deletes a repository with window.confirm dialog verification', async ({ page, isMobile }) => {
  let dialogMessage = '';
  page.on('dialog', async dialog => {
    dialogMessage = dialog.message();
    await dialog.accept();
  });

  let deleteCalled = false;
  await page.route('**/admin/api/repos/1', async route => {
    if (route.request().method() === 'DELETE') {
      deleteCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted' })
      });
    } else {
      await route.fallback();
    }
  });

  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Click delete button on first repo
  const deleteBtn = isMobile
    ? page.locator('.mobile-card-list button.btn-delete').first()
    : page.locator('.desktop-table-view button.btn-delete').first();
  await deleteBtn.click();

  expect(dialogMessage).toContain("Are you sure you want to delete repository 'knowledge-rag-mcp'?");
  expect(deleteCalled).toBe(true);
  await expect(page.locator('.toast-success', { hasText: "Repository 'knowledge-rag-mcp' deleted successfully" })).toBeVisible();
});

test('5. renders repository error status with last_error diagnostic message', async ({ page, isMobile }) => {
  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  if (isMobile) {
    const brokenCard = page.locator('.data-mobile-card', { hasText: 'broken-repo' });
    await expect(brokenCard).toBeVisible();
    await expect(brokenCard.locator('.badge-danger', { hasText: 'Error' })).toBeVisible();
    await expect(brokenCard.getByText('Authentication failed: Bad credentials')).toBeVisible();
  } else {
    const brokenRow = page.locator('.desktop-table-view').getByRole('row', { name: /broken-repo/ });
    await expect(brokenRow).toBeVisible();
    await expect(brokenRow.locator('.badge-danger', { hasText: 'Error' })).toBeVisible();
    await expect(brokenRow.getByText('Authentication failed: Bad credentials')).toBeVisible();
  }
});

test('6. opens filesystem browser, navigates directories, and selects folder for local path', async ({ page }) => {
  await navigateToTab(page, 'Local Paths');
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();

  // Open Add Local Path modal
  await page.getByRole('button', { name: 'Add Local Path' }).click();
  await expect(page.getByText('Add Monitored Local Path')).toBeVisible();

  // Click Browse to open filesystem browser modal
  await page.getByRole('button', { name: 'Browse' }).click();
  await expect(page.getByText('Browse Workspace Files')).toBeVisible();
  await expect(page.locator('.browser-breadcrumbs', { hasText: '/containers/dev/workspace' })).toBeVisible();
  await expect(page.getByText('docs', { exact: true })).toBeVisible();
  await expect(page.getByText('src', { exact: true })).toBeVisible();

  // Click 'docs' directory item to navigate down
  await page.locator('li.browser-item', { hasText: 'docs' }).click();
  await expect(page.locator('.browser-breadcrumbs', { hasText: '/containers/dev/workspace/docs' })).toBeVisible();

  // Click 'Select Current Folder'
  await page.getByRole('button', { name: 'Select Current Folder' }).click();

  // Browser modal should close, selected path input populated
  await expect(page.getByText('Browse Workspace Files')).not.toBeVisible();
  const pathInput = page.locator('input[placeholder="Browse workspace directories..."]');
  await expect(pathInput).toHaveValue('/containers/dev/workspace/docs');
});

test('7. adds local path and deletes local path with confirmation', async ({ page, isMobile }) => {
  let pathList: any[] = [...mockPaths];

  await page.route('**/admin/api/paths', async route => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      const newPath = {
        id: 2,
        path: payload.path,
        repo: payload.repo || 'local',
        type: payload.type || 'directory',
        recursive: Boolean(payload.recursive),
        category: payload.category || 'notes',
        enabled: true
      };
      pathList.push(newPath);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(newPath)
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(pathList)
      });
    }
  });

  await navigateToTab(page, 'Local Paths');
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();

  // Open modal and browse to select folder
  await page.getByRole('button', { name: 'Add Local Path' }).click();
  await page.getByRole('button', { name: 'Browse' }).click();
  await page.getByRole('button', { name: 'Select Current Folder' }).click();

  // Fill in metadata
  await page.locator('#path-repo-alias').fill('workspace-vault');
  await page.locator('#path-category').fill('knowledge-base');

  // Submit modal
  await page.getByRole('button', { name: 'Save Path' }).click();

  // Verify toast and added row/card
  await expect(page.getByText('Add Monitored Local Path')).not.toBeVisible();
  await expect(page.locator('.toast-success', { hasText: 'Path added successfully' })).toBeVisible();
  if (isMobile) {
    await expect(page.locator('.mobile-card-list').getByText('workspace-vault')).toBeVisible();
    await expect(page.locator('.mobile-card-list').getByText('knowledge-base')).toBeVisible();
  } else {
    await expect(page.locator('.desktop-table-view').getByText('workspace-vault')).toBeVisible();
    await expect(page.locator('.desktop-table-view').getByText('knowledge-base')).toBeVisible();
  }

  // Now delete the existing path
  let deletePrompt = '';
  page.on('dialog', async dialog => {
    deletePrompt = dialog.message();
    await dialog.accept();
  });

  let pathDeleted = false;
  await page.route('**/admin/api/paths/1', async route => {
    if (route.request().method() === 'DELETE') {
      pathDeleted = true;
      pathList = pathList.filter(p => p.id !== 1);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted' })
      });
    } else {
      await route.fallback();
    }
  });

  const deleteBtn = isMobile
    ? page.locator('.mobile-card-list button.btn-delete').first()
    : page.locator('.desktop-table-view button.btn-delete').first();
  await deleteBtn.click();

  expect(deletePrompt).toContain('Are you sure you want to delete this local search path?');
  expect(pathDeleted).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'Path deleted successfully' })).toBeVisible();
});

test('16. [Mobile] renders repositories as responsive cards with sync and delete actions', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Git Repositories');

  // Table view should be hidden on mobile
  await expect(page.locator('.desktop-table-view')).not.toBeVisible();

  // Mobile card list should be visible
  const cardList = page.locator('.mobile-card-list');
  await expect(cardList).toBeVisible();

  // Verify first repo card
  const syncedCard = cardList.locator('.data-mobile-card').filter({ hasText: 'knowledge-rag-mcp' });
  await expect(syncedCard).toBeVisible();
  await expect(syncedCard.locator('.badge-success', { hasText: 'Synced' })).toBeVisible();
  await expect(syncedCard.getByText('https://github.com/example/knowledge-rag-mcp.git')).toBeVisible();
  await expect(syncedCard.getByText('main')).toBeVisible();
  await expect(syncedCard.getByText('25 files')).toBeVisible();

  // Verify error repo card
  const errorCard = cardList.locator('.data-mobile-card').filter({ hasText: 'broken-repo' });
  await expect(errorCard).toBeVisible();
  await expect(errorCard.locator('.badge-danger', { hasText: 'Error' })).toBeVisible();
  await expect(errorCard.getByText('Authentication failed: Bad credentials')).toBeVisible();

  // Verify action buttons in mobile card
  await expect(syncedCard.locator('button[title="Trigger Sync"]')).toBeVisible();
  await expect(syncedCard.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('17. [Mobile] renders local paths as responsive cards with category badges and actions', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Local Paths');

  // Table view hidden, cards visible
  await expect(page.locator('.desktop-table-view')).not.toBeVisible();
  const cardList = page.locator('.mobile-card-list');
  await expect(cardList).toBeVisible();

  const pathCard = cardList.locator('.data-mobile-card').filter({ hasText: 'docs-vault' });
  await expect(pathCard).toBeVisible();
  await expect(pathCard.locator('.badge-success', { hasText: 'Enabled' })).toBeVisible();
  await expect(pathCard.getByText('/containers/dev/workspace/docs')).toBeVisible();
  await expect(pathCard.locator('.badge-primary', { hasText: 'directory' })).toBeVisible();
  await expect(pathCard.locator('.badge-accent', { hasText: 'architecture' })).toBeVisible();
  await expect(pathCard.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('22. toggles repository auto-sync ON/OFF with optimistic UI update and toast confirmation', async ({ page, isMobile }) => {
  let patchCalled = false;
  let lastBody: any = null;

  await page.route('**/admin/api/repos/1/auto-sync', async route => {
    patchCalled = true;
    lastBody = JSON.parse(route.request().postData() || '{}');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', repo_id: 1, auto_sync: false })
    });
  });

  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Find the Auto-Sync button for knowledge-rag-mcp (currently ON)
  const autoSyncBtn = isMobile
    ? page.locator('.mobile-card-list').getByRole('button', { name: /Toggle auto-sync for knowledge-rag-mcp/i }).first()
    : page.locator('.desktop-table-view').getByRole('button', { name: /Toggle auto-sync for knowledge-rag-mcp/i }).first();

  await expect(autoSyncBtn).toBeVisible();
  await expect(autoSyncBtn).toContainText('ON');

  // Click to toggle OFF
  await autoSyncBtn.click();

  expect(patchCalled).toBe(true);
  expect(lastBody.auto_sync).toBe(false);
  await expect(page.locator('.toast-info', { hasText: 'Auto-sync disabled' })).toBeVisible();
});
