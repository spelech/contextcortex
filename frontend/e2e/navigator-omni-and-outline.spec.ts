import { test, expect } from '@playwright/test';
import 'playwright-layout-inspector/matchers';
import { navigateToNavigator, setupNavigatorMocks } from './fixtures/navigatorRouteMocks';

test.describe('Codebase Navigator Outline, Doc Reader & Omni-Search Suite', () => {
  test.beforeEach(async ({ page }) => {
    await setupNavigatorMocks(page);
    await page.goto('/');
  });

  test('3. Symbol Outline & Category Filtering: loads symbols, filters by category chips, and searches', async ({ page }) => {
    await navigateToNavigator(page);

    // Expand all and click chat.py
    await page.locator('button[aria-label="Expand All"]').click();
    const chatFile = page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("chat.py")') });
    await chatFile.click();

    // Verify outline header shows selected file
    await expect(page.locator('.nav-file-badge .file-name')).toHaveText('chat.py');

    // Verify symbol items rendered
    const symbolEndpoint = page.locator('[data-testid="symbol-item-101"]');
    const symbolStream = page.locator('[data-testid="symbol-item-102"]');
    const symbolClass = page.locator('[data-testid="symbol-item-103"]');
    const symbolFunc = page.locator('[data-testid="symbol-item-104"]');

    await expect(symbolEndpoint).toBeVisible();
    await expect(symbolStream).toBeVisible();
    await expect(symbolClass).toBeVisible();
    await expect(symbolFunc).toBeVisible();

    // Category Filter: Routes
    const routesChip = page.locator('.category-chip', { hasText: 'Routes' });
    await routesChip.click();
    await expect(routesChip).toHaveClass(/active/);
    await expect(symbolEndpoint).toBeVisible();
    await expect(symbolStream).toBeVisible();
    await expect(symbolClass).not.toBeVisible();
    await expect(symbolFunc).not.toBeVisible();

    // Category Filter: Classes
    const classesChip = page.locator('.category-chip', { hasText: 'Classes' });
    await classesChip.click();
    await expect(classesChip).toHaveClass(/active/);
    await expect(symbolClass).toBeVisible();
    await expect(symbolEndpoint).not.toBeVisible();
    await expect(symbolFunc).not.toBeVisible();

    // Category Filter: Functions
    const funcsChip = page.locator('.category-chip', { hasText: 'Functions' });
    await funcsChip.click();
    await expect(funcsChip).toHaveClass(/active/);
    await expect(symbolFunc).toBeVisible();
    await expect(symbolClass).not.toBeVisible();
    await expect(symbolEndpoint).not.toBeVisible();

    // Reset to All
    const allChip = page.locator('.category-chip', { hasText: 'All' });
    await allChip.click();
    await expect(allChip).toHaveClass(/active/);
    await expect(symbolEndpoint).toBeVisible();
    await expect(symbolClass).toBeVisible();

    // Search query filtering in outline
    const outlineSearch = page.locator('.nav-outline-search-input');
    await outlineSearch.fill('format');
    await expect(symbolFunc).toBeVisible();
    await expect(symbolEndpoint).not.toBeVisible();
    await expect(symbolClass).not.toBeVisible();

    // Clear search
    await page.locator('button[aria-label="Clear symbol search"]').click();
    await expect(symbolEndpoint).toBeVisible();
  });

  test('8. Document Reader: opens markdown document, renders full content and switches between rendered and source view', async ({ page }) => {
    await navigateToNavigator(page);

    // Locate README.md in tree and click
    const readmeFile = page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("README.md")') });
    await expect(readmeFile).toBeVisible();
    await readmeFile.click();

    // Verify Outline shows doc state
    const docState = page.locator('[data-testid="outline-doc-state"]');
    await expect(docState).toBeVisible();
    await expect(docState).toContainText('Document File Active');

    // Verify Inspector renders NavigatorDocReader
    const docReader = page.locator('[data-testid="nav-doc-reader"]');
    await expect(docReader).toBeVisible();
    await expect(docReader.locator('.doc-filename')).toContainText('README.md');
    await expect(docReader.locator('.doc-rendered-content')).toBeVisible();
    await expect(docReader.locator('.doc-rendered-content')).toContainText('ContextCortex Documentation');
    await expect(docReader.locator('.doc-rendered-content')).toContainText('Hybrid Vector and Lexical Search');

    // Switch to Raw Source tab
    await docReader.getByRole('button', { name: 'Raw Source' }).click();
    await expect(docReader.locator('.doc-lines-table')).toBeVisible();
    await expect(docReader.locator('.doc-lines-table')).toContainText('ContextCortex Documentation');

    // Switch back to Rendered View
    await docReader.getByRole('button', { name: 'Rendered' }).click();
    await expect(docReader.locator('.doc-rendered-content')).toBeVisible();
  });

  test('9. Omni-Search & Synchronized Full-File Code Viewer: searches across symbols, opens full source, highlights target line with zero layout shift', async ({ page }) => {
    await navigateToNavigator(page);

    const toolbar = page.locator('[data-testid="navigator-toolbar"]');
    const toolbarBoxBefore = await toolbar.boundingBox();

    // Type query into omni-search input
    const omniInput = page.getByRole('textbox', { name: /omni-search/i });
    await expect(omniInput).toBeVisible();
    await omniInput.fill('chat_completion');

    // Wait for floating dropdown
    const dropdown = page.locator('[data-testid="nav-omni-dropdown"]');
    await expect(dropdown).toBeVisible();

    // Check overlay has position: absolute and z-index >= 50
    const dropdownStyle = await dropdown.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return { position: computed.position, zIndex: computed.zIndex };
    });
    expect(dropdownStyle.position).toBe('absolute');
    expect(Number(dropdownStyle.zIndex)).toBeGreaterThanOrEqual(50);

    // Verify toolbar height didn't expand (within 2px tolerance)
    const toolbarBoxAfter = await toolbar.boundingBox();
    expect(Math.abs((toolbarBoxAfter?.height || 0) - (toolbarBoxBefore?.height || 0))).toBeLessThanOrEqual(2);

    // Click matching symbol result
    const matchItem = dropdown.locator('.nav-omni-item').first();
    await expect(matchItem).toContainText('chat_completion_endpoint');
    await expect(matchItem).toContainText('99% AST exact match');
    await matchItem.click();

    // Dropdown should dismiss
    await expect(dropdown).not.toBeVisible();

    // Pane 3 should display NavigatorCodeViewer
    const codeViewer = page.locator('[data-testid="navigator-code-viewer"]');
    await expect(codeViewer).toBeVisible();
    await expect(codeViewer.locator('.nav-code-filename')).toContainText('chat.py');

    // Target line 45 should have highlight class and signature text
    const targetLine = codeViewer.locator('[data-testid="code-line-45"]');
    await expect(targetLine).toHaveClass(/nav-code-line-target/);
    await expect(targetLine).toContainText('async def chat_completion_endpoint');

    // Toggle Callers & Impact drawer
    const drawerToggle = codeViewer.locator('.nav-code-drawer-toggle');
    await expect(drawerToggle).toBeVisible();
    await expect(drawerToggle).toContainText('Callers & Impact (2)');
    await drawerToggle.click();

    // Verify caller chip is visible in drawer
    const drawer = codeViewer.locator('.nav-code-impact-drawer');
    await expect(drawer).toBeVisible();
    const callerChip = drawer.locator('.nav-impact-chip.caller').first();
    await expect(callerChip.locator('.chip-name')).toContainText('test_chat_completions_e2e');

    // Click caller chip to navigate cross-file to caller in Symbol Intelligence
    await callerChip.click();

    // Viewer switches to intelligence inspector showing the caller symbol
    const inspector = page.locator('[data-testid="navigator-inspector-container"]');
    await expect(inspector).toBeVisible();
    await expect(inspector.locator('.summary-name')).toHaveText('test_chat_completions_e2e');

    // Check zero layout collisions
    await expect(page).toHaveNoLayoutOverflow();
    await expect(page).toHaveNoElementCollisions();
  });
});
