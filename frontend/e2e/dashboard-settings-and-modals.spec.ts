import { test, expect } from '@playwright/test';
import {
  mockRepos,
  mockStats,
  navigateToTab,
  setupDashboardRouteMocks,
} from './fixtures/dashboardRouteMocks';

test.beforeEach(async ({ page }) => {
  await setupDashboardRouteMocks(page);
  await page.goto('/');
});

test('10. saves GitHub personal access token and verifies rate limit update', async ({ page }) => {
  let savedToken = '';

  await page.route('**/admin/api/settings/token', async route => {
    const payload = route.request().postDataJSON();
    savedToken = payload.github_token;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'saved' })
    });
  });

  await navigateToTab(page, 'Settings');
  await page.locator('.settings-category-btn', { hasText: 'Git & Host Credentials' }).click();
  await expect(page.getByText('Global Git Provider Authentication')).toBeVisible();

  // Verify initial token display
  await expect(page.getByText('ghp_****1234')).toBeVisible();

  // Update token
  const tokenInput = page.locator('input[placeholder="ghp_xxxxxxxxxxxx"]');
  await tokenInput.fill('ghp_updated_super_secret_pat_9999');

  // When saved, refreshStats fetches /admin/api/stats
  await page.route('**/admin/api/stats', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockStats,
        masked_token: 'ghp_****9999',
        providers_auth: {
          github: { token_source: 'Database', masked_token: 'ghp_****9999' }
        },
        rate_limit: { remaining: 5000, limit: 5000 }
      })
    });
  });

  await page.locator('.settings-provider-box').filter({ hasText: 'GitHub' }).getByRole('button', { name: 'Save' }).click();

  expect(savedToken).toBe('ghp_updated_super_secret_pat_9999');
  await expect(page.locator('.toast-success', { hasText: 'GitHub token saved successfully.' })).toBeVisible();
  await expect(tokenInput).toHaveValue('');
  await expect(page.getByText('ghp_****9999')).toBeVisible();
});

test('11. clears GitHub token with confirmation dialog', async ({ page }) => {
  let dialogMessage = '';
  page.on('dialog', async dialog => {
    dialogMessage = dialog.message();
    await dialog.accept();
  });

  let clearCalled = false;
  await page.route('**/admin/api/settings/token', async route => {
    const payload = route.request().postDataJSON();
    if (payload.github_token === '') {
      clearCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'cleared' })
      });
    } else {
      await route.fallback();
    }
  });

  await navigateToTab(page, 'Settings');
  await page.locator('.settings-category-btn', { hasText: 'Git & Host Credentials' }).click();
  await expect(page.getByText('Global Git Provider Authentication')).toBeVisible();

  await page.locator('.settings-provider-box').filter({ hasText: 'GitHub' }).getByRole('button', { name: 'Clear' }).click();

  expect(dialogMessage).toContain('Clear the stored GitHub token from database?');
  expect(clearCalled).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'GitHub token cleared' })).toBeVisible();
});

test('18. [Mobile] Add Repository modal renders correctly on mobile viewport and registers repo', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Git Repositories');

  // Click Add Repository
  await page.getByRole('button', { name: 'Add Repository' }).click();

  const modal = page.locator('.modal-card');
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('heading', { name: 'Register Git Repository' })).toBeVisible();

  // Fill in form on mobile
  await page.locator('#repo-alias').fill('mobile-ui-app');
  await page.locator('#repo-url').fill('https://github.com/example/mobile-ui.git');
  await page.locator('#repo-branch').fill('develop');

  // Mock POST response
  await page.route('**/admin/api/repos', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 4,
          name: 'mobile-ui-app',
          url: 'https://github.com/example/mobile-ui.git',
          branch: 'develop',
          commit_sha: null,
          status: 'pending',
          file_count: 0,
          last_synced: 'Never'
        })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          ...mockRepos,
          {
            id: 4,
            name: 'mobile-ui-app',
            url: 'https://github.com/example/mobile-ui.git',
            branch: 'develop',
            commit_sha: null,
            status: 'pending',
            file_count: 0,
            last_synced: 'Never'
          }
        ])
      });
    }
  });

  await page.getByRole('button', { name: 'Add & Start Sync' }).click();

  // Modal closes, toast appears, card is in mobile card list
  await expect(modal).not.toBeVisible();
  await expect(page.locator('.toast-success', { hasText: "Repository 'mobile-ui-app' added successfully" })).toBeVisible();
  await expect(page.locator('.mobile-card-list').getByText('mobile-ui-app')).toBeVisible();
});

test('19. [Mobile] filesystem browser modal navigates and selects path on mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await navigateToTab(page, 'Local Paths');

  // Open Add Local Path modal
  await page.getByRole('button', { name: 'Add Local Path' }).click();
  await expect(page.getByText('Add Monitored Local Path')).toBeVisible();

  // Open browser modal
  await page.getByRole('button', { name: 'Browse' }).click();
  await expect(page.getByText('Browse Workspace Files')).toBeVisible();

  // Click docs item
  await page.locator('li.browser-item', { hasText: 'docs' }).click();
  await expect(page.locator('.browser-breadcrumbs', { hasText: '/containers/dev/workspace/docs' })).toBeVisible();

  // Select current folder
  await page.getByRole('button', { name: 'Select Current Folder' }).click();
  await expect(page.getByText('Browse Workspace Files')).not.toBeVisible();

  // Path input populated
  const pathInput = page.locator('input[placeholder="Browse workspace directories..."]');
  await expect(pathInput).toHaveValue('/containers/dev/workspace/docs');

  // Close path modal
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByText('Add Monitored Local Path')).not.toBeVisible();
});

test('23. opens Webhook setup modal, displays copyable endpoint, and shows provider setup guides', async ({ page, isMobile }) => {
  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Click Webhook button on the first repo
  const webhookBtn = isMobile
    ? page.locator('.mobile-card-list').locator('button[title="Webhook Setup"]').first()
    : page.locator('.desktop-table-view').locator('button[title="Webhook Setup"]').first();

  await expect(webhookBtn).toBeVisible();
  await webhookBtn.click();

  // Modal header and content
  await expect(page.getByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).toBeVisible();
  await expect(page.getByLabel('Webhook Payload URL')).toBeVisible();

  // Check provider setup guides
  await expect(page.getByText('GitHub:')).toBeVisible();
  await expect(page.getByText('GitLab:')).toBeVisible();
  await expect(page.getByText('Gitea / Forgejo:')).toBeVisible();

  // Test Copy Endpoint button
  const copyBtn = page.getByRole('button', { name: /Copy Webhook URL/i });
  await expect(copyBtn).toBeVisible();
  await copyBtn.click();
  await expect(page.locator('.toast-info', { hasText: 'Webhook URL copied to clipboard' })).toBeVisible();

  // Dismiss modal
  const closeBtn = page.locator('button[aria-label="Close webhook modal"]');
  await expect(closeBtn).toBeVisible();
  await closeBtn.click();
  await expect(page.getByRole('heading', { name: /Webhook Setup: knowledge-rag-mcp/i })).not.toBeVisible();
});

test('24. configures auto-sync polling schedule and manages global webhook secret in Settings', async ({ page }) => {
  let settingsSaved = false;
  let savedPayload: any = null;

  await page.route('**/admin/api/settings/auto-sync*', async route => {
    if (route.request().method() === 'POST') {
      settingsSaved = true;
      savedPayload = JSON.parse(route.request().postData() || '{}');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success', interval_mins: 30, has_global_secret: true })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          interval_mins: 15,
          webhook_url: '/api/webhooks/git',
          has_global_secret: false
        })
      });
    }
  });

  await navigateToTab(page, 'Settings');
  await page.locator('.settings-category-btn', { hasText: 'Auto-Sync & Webhooks' }).click();
  await expect(page.getByRole('heading', { name: /Auto-Sync & Webhooks/i })).toBeVisible();

  // Select 30 minutes polling interval
  const intervalSelect = page.locator('#auto-sync-interval');
  await expect(intervalSelect).toBeVisible();
  await intervalSelect.selectOption('30');

  // Fill in Webhook Secret and test mask/unmask toggle
  const secretInput = page.locator('#auto-sync-secret');
  await expect(secretInput).toBeVisible();
  await secretInput.fill('my-super-secret-key-123');

  const eyeToggle = page.locator('button[aria-label="Reveal secret"], button[aria-label="Hide secret"]');
  await expect(eyeToggle).toBeVisible();
  await expect(secretInput).toHaveAttribute('type', 'password');
  await eyeToggle.click();
  await expect(secretInput).toHaveAttribute('type', 'text');
  await eyeToggle.click();
  await expect(secretInput).toHaveAttribute('type', 'password');

  // Test Copy Webhook URL button in Settings
  const copySettingsBtn = page.getByRole('button', { name: /Copy Webhook URL/i });
  await expect(copySettingsBtn).toBeVisible();
  await copySettingsBtn.click();
  await expect(page.locator('.toast-info', { hasText: 'Webhook URL copied to clipboard' })).toBeVisible();

  // Save Settings
  const saveBtn = page.getByRole('button', { name: /Save Auto-Sync/i });
  await expect(saveBtn).toBeVisible();
  await saveBtn.click();

  expect(settingsSaved).toBe(true);
  expect(savedPayload.interval_mins).toBe(30);
  expect(savedPayload.global_webhook_secret).toBe('my-super-secret-key-123');
  await expect(page.locator('.toast-success', { hasText: 'Auto-sync settings saved successfully' })).toBeVisible();
});
