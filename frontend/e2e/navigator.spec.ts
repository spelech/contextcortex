import { test, expect } from '@playwright/test';
import 'playwright-layout-inspector/matchers';
import { LayoutInspector, getDevicePreset } from 'playwright-layout-inspector';
import { navigateToNavigator, setupNavigatorMocks } from './fixtures/navigatorRouteMocks';

test.describe('Codebase Navigator End-to-End Suite', () => {
  test.beforeEach(async ({ page }) => {
    await setupNavigatorMocks(page);
    await page.goto('/');
  });

  test('1. Navigation and Initial Load: mounts CodeNavigator container, toolbar, and stats', async ({ page }) => {
    await navigateToNavigator(page);

    // Verify container and toolbar
    const container = page.locator('[data-testid="code-navigator-container"]');
    await expect(container).toBeVisible();

    const toolbar = page.locator('[data-testid="navigator-toolbar"]');
    await expect(toolbar).toBeVisible();

    // Verify Repository Selector and options
    const repoSelect = page.locator('#nav-repo-select');
    await expect(repoSelect).toBeVisible();
    await expect(repoSelect).toHaveValue('__all__');

    // Verify summary statistics badges
    await expect(page.getByText('5 files')).toBeVisible();
    await expect(page.getByText('18 symbols')).toBeVisible();

    // Verify sidebar tabs and hero viewport
    await expect(page.locator('.nav-sidebar-tab-btn', { hasText: 'Files' })).toBeVisible();
    await expect(page.locator('.nav-sidebar-tab-btn', { hasText: 'Symbols' })).toBeVisible();
    await expect(page.locator('[data-testid="navigator-inspector-container"]')).toBeVisible();
  });

  test('2. File Tree Interaction: hierarchical structure, expand/collapse, and search filtering', async ({ page }) => {
    await navigateToNavigator(page);

    const treeContainer = page.locator('[data-testid="navigator-tree-container"]');
    await expect(treeContainer).toBeVisible();

    // Verify initial directories and root files are rendered
    await expect(page.locator('.tree-label:text-is("app")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("tests")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("README.md")')).toBeVisible();

    // Click Expand All button in tree header
    const expandAllBtn = page.locator('button[aria-label="Expand All"]');
    await expandAllBtn.click();

    // Verify nested files are now visible
    await expect(page.locator('.tree-label:text-is("chat.py")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("auth.py")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("vector_store.py")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("test_chat.py")')).toBeVisible();

    // Click Collapse All button
    const collapseAllBtn = page.locator('button[aria-label="Collapse All"]');
    await collapseAllBtn.click();
    await expect(page.locator('.tree-label:text-is("chat.py")')).not.toBeVisible();

    // Filter file tree via search input
    const searchInput = page.locator('.nav-tree-search-input');
    await searchInput.fill('chat');

    // Matching files should be visible and directories auto-expanded
    await expect(page.locator('.tree-label:text-is("chat.py")')).toBeVisible();
    await expect(page.locator('.tree-label:text-is("test_chat.py")')).toBeVisible();

    // Non-matching files should be filtered out
    await expect(page.locator('.tree-label:text-is("auth.py")')).not.toBeVisible();
    await expect(page.locator('.tree-label:text-is("README.md")')).not.toBeVisible();

    // Clear filter
    const clearBtn = page.locator('button[aria-label="Clear filter"]');
    await clearBtn.click();
    await expect(searchInput).toHaveValue('');
  });

  test('4. Impact Inspector & Route Details: displays metrics, route card, signature, and copy permalink', async ({ page }) => {
    await navigateToNavigator(page);

    // Expand tree and click chat.py
    await page.locator('button[aria-label="Expand All"]').click();
    await page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("chat.py")') }).click();

    // Select chat_completion_endpoint
    const symbolItem = page.locator('[data-testid="symbol-item-101"]');
    await symbolItem.click();

    // Verify Inspector Header & Location Details
    const inspector = page.locator('[data-testid="navigator-inspector-container"]');
    await expect(inspector).toBeVisible();
    await expect(page.locator('.summary-name')).toHaveText('chat_completion_endpoint');
    await expect(page.locator('.summary-file-path')).toContainText('app/api/routers/chat.py');
    await expect(page.locator('.summary-line-range')).toHaveText('L45 - L85');

    // Verify 4-Metrics Grid
    await expect(page.locator('[data-testid="metric-callers"]')).toHaveText('1');
    await expect(page.locator('[data-testid="metric-callees"]')).toHaveText('1');
    await expect(page.locator('[data-testid="metric-imports"]')).toHaveText('1');
    await expect(page.locator('[data-testid="metric-scope"]')).toHaveText('Python');

    // Verify API Route Mapping Card
    const routeCard = page.locator('.inspector-card.route-card');
    await expect(routeCard).toBeVisible();
    await expect(routeCard.locator('.route-method-badge')).toHaveText('POST');
    await expect(routeCard.locator('.route-path-code')).toHaveText('/v1/chat/completions');
    await expect(routeCard.locator('.route-framework-tag')).toHaveText('FastAPI');

    // Verify Signature Code Block and Docstring
    await expect(page.locator('.signature-code-block')).toContainText('async def chat_completion_endpoint');
    await expect(page.locator('.docstring-text')).toContainText('Processes OpenAI-compatible chat completion');

    // Verify Copy Permalink interaction
    const copyBtn = inspector.locator('button[aria-label="Copy Permalink"]');
    await expect(copyBtn).toBeVisible();
    await copyBtn.click();
    await expect(copyBtn).toContainText('Copied!');
  });

  test('5. Caller Click-Through Navigation: jumps from caller card in inspector to caller file and symbol', async ({ page }) => {
    await navigateToNavigator(page);

    // Expand tree and click chat.py
    await page.locator('button[aria-label="Expand All"]').click();
    await page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("chat.py")') }).click();

    // Select chat_completion_endpoint
    await page.locator('[data-testid="symbol-item-101"]').click();

    // Locate incoming caller card in inspector
    const callerCard = page.locator('[data-testid="caller-item-501"]');
    await expect(callerCard).toBeVisible();
    await expect(callerCard.locator('.rel-symbol-name')).toHaveText('test_chat_completions_e2e');
    await expect(callerCard.locator('.rel-filepath')).toHaveText('tests/e2e/test_chat.py');

    // Click caller card
    await callerCard.click();

    // Verify file tree switched to test_chat.py and marked selected
    await page.locator('.nav-sidebar-tab-btn', { hasText: 'Files' }).click();
    const testChatFile = page.locator('.nav-tree-item.file-item.selected').filter({ has: page.locator('.tree-label:text-is("test_chat.py")') });
    await expect(testChatFile).toBeVisible();

    // Verify outline pane loaded test_chat.py and highlighted test_chat_completions_e2e
    await page.locator('.nav-sidebar-tab-btn', { hasText: 'Symbols' }).click();
    await expect(page.locator('.nav-file-badge .file-name')).toHaveText('test_chat.py');
    const activeSymbol = page.locator('[data-testid="symbol-item-301"]');
    await expect(activeSymbol).toHaveClass(/active/);

    // Verify Inspector updated with caller's intelligence
    await expect(page.locator('.summary-name')).toHaveText('test_chat_completions_e2e');
    await expect(page.locator('.docstring-text')).toContainText('Validates end-to-end chat completions');
  });

  test('6. Density Mode Toggling: toggles Compact, Balanced, and Spacious layout modes', async ({ page }) => {
    await navigateToNavigator(page);

    const container = page.locator('[data-testid="code-navigator-container"]');

    // Compact Mode (IDE mode)
    const compactBtn = page.getByRole('button', { name: 'Compact', exact: true });
    await compactBtn.click();
    await expect(compactBtn).toHaveClass(/active/);
    await expect(container).toHaveClass(/density-compact/);

    // Spacious Mode (Cards mode)
    const spaciousBtn = page.getByRole('button', { name: 'Spacious', exact: true });
    await spaciousBtn.click();
    await expect(spaciousBtn).toHaveClass(/active/);
    await expect(container).toHaveClass(/density-spacious/);

    // Balanced Mode (Default mode)
    const balancedBtn = page.getByRole('button', { name: 'Balanced', exact: true });
    await balancedBtn.click();
    await expect(balancedBtn).toHaveClass(/active/);
    await expect(container).toHaveClass(/density-balanced/);
  });

  test('7. Responsive Layout Audit: zero overflow, zero element collisions, and stable layout across desktop and mobile', async ({ page }) => {
    // Desktop 1080p
    await page.setViewportSize({ width: 1920, height: 1080 });
    await navigateToNavigator(page);

    // Expand all and select a file
    await page.locator('button[aria-label="Expand All"]').click();
    await page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("chat.py")') }).click();

    // Assert zero horizontal overflow and zero element collisions
    await expect(page).toHaveNoLayoutOverflow();
    await expect(page).toHaveNoElementCollisions({ ignoreSelectors: ['.token'] });

    // Layout Inspector UX Audit
    const inspector = new LayoutInspector(page);
    const audit = await inspector.audit({
      device: getDevicePreset('Desktop 1080p'),
      includeScreenshot: false,
    });

    expect(audit.overflowIssues.length).toBe(0);

    // Mobile Viewport (Samsung Galaxy S25: 360x780)
    const s25 = getDevicePreset('Samsung Galaxy S25');
    await page.setViewportSize({ width: s25.width, height: s25.height });
    await page.waitForTimeout(200);

    await expect(page).toHaveNoLayoutOverflow();
    await expect(page).toHaveNoElementCollisions({ ignoreSelectors: ['.token'] });
  });
});
