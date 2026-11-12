import { test, expect } from '@playwright/test';
import { navigateToGitSyncTab, setupGitSyncRouteMocks } from './fixtures/gitSyncRouteMocks';

test.beforeEach(async ({ page }) => {
  await setupGitSyncRouteMocks(page);
  await page.goto('/');
});

test.describe('Git Sync Real-Time Progress Visibility & Live Log Drawer', () => {
  test('1. renders multi-stage progress chip, percentage, and current file in table and mobile card', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    if (isMobile) {
      const card = page.locator('.mobile-card-list .data-mobile-card').filter({ hasText: 'contextcortex-core' });
      await expect(card).toBeVisible();

      // Progress chip text
      const progressContainer = card.locator('.sync-progress-container');
      await expect(progressContainer).toBeVisible();
      await expect(progressContainer.locator('.progress-pill')).toContainText('Step 3/5: Computing File Delta & Scanning (45%)');

      // Animated progress bar
      const fillBar = progressContainer.locator('.sync-progress-bar-fill');
      await expect(fillBar).toBeVisible();

      // Current file caption
      await expect(progressContainer.locator('.sync-file-caption code')).toHaveText('src/services/git.ts');
    } else {
      const row = page.locator('.desktop-table-view tbody tr').filter({ hasText: 'contextcortex-core' });
      await expect(row).toBeVisible();

      // Progress chip text
      const progressContainer = row.locator('.sync-progress-container');
      await expect(progressContainer).toBeVisible();
      await expect(progressContainer.locator('.progress-pill')).toContainText('Step 3/5: Computing File Delta & Scanning (45%)');

      // Animated progress bar
      const fillBar = progressContainer.locator('.sync-progress-bar-fill');
      await expect(fillBar).toBeVisible();

      // Current file caption
      await expect(progressContainer.locator('.sync-file-caption code')).toHaveText('src/services/git.ts');
    }
  });

  test('2. opens RepoSyncDrawer when clicking progress chip and renders 5-stage checklist and overall progress', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Click on progress container
    const progressEl = isMobile
      ? page.locator('.mobile-card-list .sync-progress-container').first()
      : page.locator('.desktop-table-view .sync-progress-container').first();
    await progressEl.click();

    // Verify Drawer backdrop and panel are visible
    const backdrop = page.locator('.sync-drawer-backdrop');
    await expect(backdrop).toBeVisible();
    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Drawer header
    await expect(drawer.locator('.sync-drawer-header')).toContainText('contextcortex-core Ingestion Progress & Live Logs');
    await expect(drawer.locator('.badge-warning')).toContainText('Syncing');
    await expect(drawer.locator('.sync-drawer-meta')).toContainText('Computing File Delta & Scanning');
    await expect(drawer.locator('.sync-drawer-meta')).toContainText('Elapsed:');

    // Overall Ingestion Section
    await expect(drawer.locator('.sync-progress-section')).toContainText('Overall Ingestion');
    await expect(drawer.locator('.sync-progress-section')).toContainText('45%');

    // Stepper Checklist Verification (5 stages)
    const stepperList = drawer.locator('.sync-stepper-list');
    await expect(stepperList).toBeVisible();

    // Stage 1: Connecting & Remote Check (Completed)
    const stage1 = stepperList.locator('.sync-stepper-item').nth(0);
    await expect(stage1).toHaveClass(/item-completed/);
    await expect(stage1).toContainText('1. Connecting & Remote Check');

    // Stage 2: Shallow Cloning Repository (Completed)
    const stage2 = stepperList.locator('.sync-stepper-item').nth(1);
    await expect(stage2).toHaveClass(/item-completed/);
    await expect(stage2).toContainText('2. Shallow Cloning Repository');

    // Stage 3: Computing File Delta & Scanning (Active)
    const stage3 = stepperList.locator('.sync-stepper-item').nth(2);
    await expect(stage3).toHaveClass(/item-active/);
    await expect(stage3).toContainText('3. Computing File Delta & Scanning');
    await expect(stage3.locator('.sync-current-file code')).toHaveText('src/services/git.ts');
    await expect(stage3.locator('.sync-file-count')).toContainText('9 / 20 files (45%)');

    // Stage 4: Parsing AST Symbols & API Routes (Pending)
    const stage4 = stepperList.locator('.sync-stepper-item').nth(3);
    await expect(stage4).toHaveClass(/item-pending/);
    await expect(stage4).toContainText('4. Parsing AST Symbols & API Routes');

    // Stage 5: Upserting Embeddings & Finalizing (Pending)
    const stage5 = stepperList.locator('.sync-stepper-item').nth(4);
    await expect(stage5).toHaveClass(/item-pending/);
    await expect(stage5).toContainText('5. Upserting Embeddings & Finalizing');
  });

  test('3. opens RepoSyncDrawer via "Logs" button and verifies live terminal logs, search filter, and copy actions', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Click "Logs" button on first repo
    const logsBtn = isMobile
      ? page.locator('.mobile-card-list button', { hasText: 'Logs' }).first()
      : page.locator('.desktop-table-view button', { hasText: 'Logs' }).first();
    await logsBtn.click();

    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Terminal Header
    const terminal = drawer.locator('.sync-terminal-section');
    await expect(terminal).toBeVisible();
    await expect(terminal.locator('.sync-terminal-header')).toContainText('Live Terminal Output');
    await expect(terminal.locator('.sync-terminal-header')).toContainText('5 events');

    // Initial logs rendered
    await expect(terminal.locator('.sync-terminal-lines')).toContainText('Connecting to remote repository...');
    await expect(terminal.locator('.sync-terminal-lines')).toContainText('Cloned branch main with commit a1b2c3d4');
    await expect(terminal.locator('.sync-terminal-lines')).toContainText('Scanning 20 files for modifications');
    await expect(terminal.locator('.sync-terminal-lines')).toContainText('Large file detected: data/vectors.bin');

    // Test Search Filter inside Terminal
    const searchInput = terminal.locator('.sync-terminal-search input');
    await searchInput.fill('Large file');
    await expect(terminal.locator('.sync-terminal-lines')).toContainText('Large file detected');
    await expect(terminal.locator('.sync-terminal-lines')).not.toContainText('Connecting to remote repository...');
    await expect(terminal.locator('.sync-terminal-header')).toContainText('1 event');

    // Clear filter
    await terminal.locator('.sync-terminal-search button').click();
    await expect(terminal.locator('.sync-terminal-header')).toContainText('5 events');

    // Test Autoscroll Toggle
    const autoScrollCheckbox = terminal.locator('.sync-autoscroll-toggle input[type="checkbox"]');
    await expect(autoScrollCheckbox).toBeChecked();
    await autoScrollCheckbox.uncheck();
    await expect(autoScrollCheckbox).not.toBeChecked();
    await autoScrollCheckbox.check();
    await expect(autoScrollCheckbox).toBeChecked();

    // Test Copy Logs Button
    const copyLogsBtn = terminal.locator('button[aria-label="Copy logs"]');
    await expect(copyLogsBtn).toBeVisible();
    await copyLogsBtn.click();
    await expect(terminal.getByText('Copied!')).toBeVisible();
  });

  test('4. dismisses RepoSyncDrawer via close button and backdrop click', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    const logsBtn = isMobile
      ? page.locator('.mobile-card-list button', { hasText: 'Logs' }).first()
      : page.locator('.desktop-table-view button', { hasText: 'Logs' }).first();
    await logsBtn.click();

    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Close via close button
    const closeBtn = drawer.locator('button.btn-close');
    await expect(closeBtn).toBeVisible();
    await closeBtn.click();
    await expect(drawer).not.toBeVisible();

    // Reopen drawer
    await logsBtn.click();
    await expect(drawer).toBeVisible();

    // Close via backdrop click (click in backdrop area)
    const backdrop = page.locator('.sync-drawer-backdrop');
    await backdrop.click({ position: { x: isMobile ? 5 : 50, y: 200 }, force: true });
    await expect(drawer).not.toBeVisible();
  });

  test('5. displays error state in drawer with highlighted failing step and error details', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Click Logs on the second repository (error repo)
    const errorLogsBtn = isMobile
      ? page.locator('.mobile-card-list .data-mobile-card').filter({ hasText: 'docs-vault' }).locator('button', { hasText: 'Logs' })
      : page.locator('.desktop-table-view tbody tr').filter({ hasText: 'docs-vault' }).locator('button', { hasText: 'Logs' });
    await errorLogsBtn.click();

    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Header Error Badge
    await expect(drawer.locator('.sync-drawer-header .badge-danger')).toContainText('Error');

    // Failing Step Highlighted (Step 2)
    const stage2 = drawer.locator('.sync-stepper-item').nth(1);
    await expect(stage2).toHaveClass(/item-error/);
    await expect(stage2).toContainText('2. Shallow Cloning Repository');
    await expect(stage2.locator('.sync-stepper-error-msg')).toContainText('Authentication failed: SSH key rejected');

    // Progress bar fill has error styling
    await expect(drawer.locator('.sync-progress-bar-fill')).toHaveClass(/fill-error/);

    // Terminal contains error log line with red badge
    const errorLogLine = drawer.locator('.sync-terminal-line', { hasText: 'SSH key rejected' });
    await expect(errorLogLine).toBeVisible();
    await expect(errorLogLine.locator('.log-badge.level-error')).toHaveText('ERROR');
  });

  test('6. displays completed synced state with all 5 stages marked complete and 100% progress', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Click Logs on the third repository (synced repo)
    const syncedLogsBtn = isMobile
      ? page.locator('.mobile-card-list .data-mobile-card').filter({ hasText: 'api-service' }).locator('button', { hasText: 'Logs' })
      : page.locator('.desktop-table-view tbody tr').filter({ hasText: 'api-service' }).locator('button', { hasText: 'Logs' });
    await syncedLogsBtn.click();

    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Header Synced Badge
    await expect(drawer.locator('.sync-drawer-header .badge-success')).toContainText('Synced');
    await expect(drawer.locator('.sync-progress-section')).toContainText('100%');

    // Progress bar fill has success styling
    await expect(drawer.locator('.sync-progress-bar-fill')).toHaveClass(/fill-success/);

    // All 5 stages marked completed
    const stages = drawer.locator('.sync-stepper-item');
    await expect(stages).toHaveCount(5);
    for (let i = 0; i < 5; i++) {
      await expect(stages.nth(i)).toHaveClass(/item-completed/);
    }
  });

  test('7. triggers sync action and handles cancel sync from drawer', async ({ page, isMobile }) => {
    let cancelCalled = false;
    await page.route('**/admin/api/repos/1/cancel-sync', async (route) => {
      cancelCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'cancelled', repo_id: 1 }),
      });
    });

    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    // Open drawer for repo 1 (syncing)
    const logsBtn = isMobile
      ? page.locator('.mobile-card-list button', { hasText: 'Logs' }).first()
      : page.locator('.desktop-table-view button', { hasText: 'Logs' }).first();
    await logsBtn.click();

    const drawer = page.locator('.sync-drawer');
    await expect(drawer).toBeVisible();

    // Cancel Sync button should be visible for syncing state
    const cancelBtn = drawer.locator('button.btn-cancel-sync');
    await expect(cancelBtn).toBeVisible();
    await expect(cancelBtn).toContainText('Cancel Sync');

    // Click Cancel Sync
    await cancelBtn.click();
    expect(cancelCalled).toBe(true);
  });

  test('8. validates responsive layout containment on desktop and mobile viewports', async ({ page, isMobile }) => {
    await navigateToGitSyncTab(page, 'Git Repositories');
    await expect(page.getByText('Registered Git Repositories')).toBeVisible();

    if (isMobile) {
      await expect(page.locator('.desktop-table-view')).not.toBeVisible();
      await expect(page.locator('.mobile-card-list')).toBeVisible();

      // Open drawer on Mobile
      await page.locator('.mobile-card-list button', { hasText: 'Logs' }).first().click();
      const mobileDrawer = page.locator('.sync-drawer');
      await expect(mobileDrawer).toBeVisible();

      const mobileBox = await mobileDrawer.boundingBox();
      expect(mobileBox).not.toBeNull();
      if (mobileBox) {
        expect(mobileBox.width).toBeLessThanOrEqual(page.viewportSize()!.width + 5);
      }
    } else {
      await expect(page.locator('.desktop-table-view')).toBeVisible();
      await expect(page.locator('.mobile-card-list')).not.toBeVisible();

      // Open drawer on Desktop
      await page.locator('.desktop-table-view button', { hasText: 'Logs' }).first().click();
      const desktopDrawer = page.locator('.sync-drawer');
      await expect(desktopDrawer).toBeVisible();

      const desktopBox = await desktopDrawer.boundingBox();
      expect(desktopBox).not.toBeNull();
      if (desktopBox) {
        expect(desktopBox.width).toBeLessThanOrEqual(620);
      }
    }
  });
});
