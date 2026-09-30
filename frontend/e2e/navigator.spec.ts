import { test, expect } from '@playwright/test';
import 'playwright-layout-inspector/matchers';
import { LayoutInspector, getDevicePreset } from 'playwright-layout-inspector';

const mockStats = {
  repos_count: 2,
  symbols_count: 18,
  files_count: 5,
  points_count: 1500,
  last_indexed: '2026-08-31 20:00:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1',
  vector_db_status: 'Healthy',
  rate_limit: { remaining: 5000, limit: 5000 },
  top_keywords: ['fastapi', 'chat', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234',
};

const mockRepos = [
  { id: 1, name: 'contextcortex-core' },
  { id: 2, name: 'contextcortex-web' },
];

const mockTreeData = {
  repo: '__all__',
  total_files: 5,
  total_symbols: 18,
  tree: [
    {
      id: 'dir:app',
      name: 'app',
      is_dir: true,
      path: 'app',
      symbol_count: 14,
      route_count: 4,
      children: [
        {
          id: 'dir:app/api',
          name: 'api',
          is_dir: true,
          path: 'app/api',
          symbol_count: 10,
          route_count: 4,
          children: [
            {
              id: 'dir:app/api/routers',
              name: 'routers',
              is_dir: true,
              path: 'app/api/routers',
              symbol_count: 10,
              route_count: 4,
              children: [
                {
                  id: 'file:app/api/routers/chat.py',
                  name: 'chat.py',
                  is_dir: false,
                  path: 'app/api/routers/chat.py',
                  language: 'python',
                  symbol_count: 6,
                  route_count: 2,
                },
                {
                  id: 'file:app/api/routers/auth.py',
                  name: 'auth.py',
                  is_dir: false,
                  path: 'app/api/routers/auth.py',
                  language: 'python',
                  symbol_count: 4,
                  route_count: 2,
                },
              ],
            },
          ],
        },
        {
          id: 'dir:app/services',
          name: 'services',
          is_dir: true,
          path: 'app/services',
          symbol_count: 4,
          route_count: 0,
          children: [
            {
              id: 'file:app/services/vector_store.py',
              name: 'vector_store.py',
              is_dir: false,
              path: 'app/services/vector_store.py',
              language: 'python',
              symbol_count: 4,
              route_count: 0,
            },
          ],
        },
      ],
    },
    {
      id: 'dir:tests',
      name: 'tests',
      is_dir: true,
      path: 'tests',
      symbol_count: 4,
      route_count: 0,
      children: [
        {
          id: 'dir:tests/e2e',
          name: 'e2e',
          is_dir: true,
          path: 'tests/e2e',
          symbol_count: 4,
          route_count: 0,
          children: [
            {
              id: 'file:tests/e2e/test_chat.py',
              name: 'test_chat.py',
              is_dir: false,
              path: 'tests/e2e/test_chat.py',
              language: 'python',
              symbol_count: 4,
              route_count: 0,
            },
          ],
        },
      ],
    },
    {
      id: 'file:README.md',
      name: 'README.md',
      is_dir: false,
      path: 'README.md',
      language: 'markdown',
      symbol_count: 0,
      route_count: 0,
    },
  ],
};

const mockOutlineChat = {
  repo: '__all__',
  filepath: 'app/api/routers/chat.py',
  language: 'python',
  symbols: [
    {
      id: 101,
      name: 'chat_completion_endpoint',
      full_symbol: 'app.api.routers.chat.chat_completion_endpoint',
      kind: 'function',
      start_line: 45,
      end_line: 85,
      signature: 'async def chat_completion_endpoint(request: ChatCompletionRequest) -> ChatCompletionResponse:',
      route: {
        http_method: 'POST',
        path_pattern: '/v1/chat/completions',
        framework: 'FastAPI',
      },
    },
    {
      id: 102,
      name: 'stream_chat_endpoint',
      full_symbol: 'app.api.routers.chat.stream_chat_endpoint',
      kind: 'function',
      start_line: 90,
      end_line: 130,
      signature: 'async def stream_chat_endpoint(request: ChatCompletionRequest):',
      route: {
        http_method: 'POST',
        path_pattern: '/v1/chat/stream',
        framework: 'FastAPI',
      },
    },
    {
      id: 103,
      name: 'ChatCompletionRequest',
      full_symbol: 'app.api.routers.chat.ChatCompletionRequest',
      kind: 'class',
      start_line: 15,
      end_line: 35,
      signature: 'class ChatCompletionRequest(BaseModel):',
    },
    {
      id: 104,
      name: 'format_chat_response',
      full_symbol: 'app.api.routers.chat.format_chat_response',
      kind: 'function',
      start_line: 135,
      end_line: 150,
      signature: 'def format_chat_response(raw_text: str) -> dict:',
    },
  ],
};

const mockOutlineTestChat = {
  repo: '__all__',
  filepath: 'tests/e2e/test_chat.py',
  language: 'python',
  symbols: [
    {
      id: 301,
      name: 'test_chat_completions_e2e',
      full_symbol: 'tests.e2e.test_chat.test_chat_completions_e2e',
      kind: 'function',
      start_line: 20,
      end_line: 45,
      signature: 'async def test_chat_completions_e2e(client: AsyncClient):',
    },
    {
      id: 302,
      name: 'test_stream_chat_e2e',
      full_symbol: 'tests.e2e.test_chat.test_stream_chat_e2e',
      kind: 'function',
      start_line: 50,
      end_line: 75,
      signature: 'async def test_stream_chat_e2e(client: AsyncClient):',
    },
  ],
};

const mockImpactChatCompletion = {
  symbol: {
    id: 101,
    name: 'chat_completion_endpoint',
    full_symbol: 'app.api.routers.chat.chat_completion_endpoint',
    kind: 'function',
    filepath: 'app/api/routers/chat.py',
    start_line: 45,
    end_line: 85,
    signature: 'async def chat_completion_endpoint(request: ChatCompletionRequest) -> ChatCompletionResponse:',
    docstring: 'Processes OpenAI-compatible chat completion requests with vector context augmentations.',
    language: 'python',
    repo: 'contextcortex-core',
  },
  route: {
    http_method: 'POST',
    path_pattern: '/v1/chat/completions',
    framework: 'FastAPI',
  },
  callers: [
    {
      id: 501,
      source_symbol_id: 301,
      source_filepath: 'tests/e2e/test_chat.py',
      source_symbol: 'test_chat_completions_e2e',
      target_symbol: 'chat_completion_endpoint',
      relationship_type: 'CALLS',
      line_number: 28,
    },
  ],
  callees: [
    {
      id: 601,
      target_symbol: 'format_chat_response',
      target_filepath: 'app/api/routers/chat.py',
      relationship_type: 'CALLS',
      line_number: 80,
    },
  ],
  imports: [
    {
      id: 701,
      target_symbol: 'vector_store',
      relationship_type: 'IMPORTS',
      line_number: 8,
    },
  ],
};

const mockImpactTestChat = {
  symbol: {
    id: 301,
    name: 'test_chat_completions_e2e',
    full_symbol: 'tests.e2e.test_chat.test_chat_completions_e2e',
    kind: 'function',
    filepath: 'tests/e2e/test_chat.py',
    start_line: 20,
    end_line: 45,
    signature: 'async def test_chat_completions_e2e(client: AsyncClient):',
    docstring: 'Validates end-to-end chat completions against test fixtures.',
    language: 'python',
    repo: 'contextcortex-core',
  },
  route: null,
  callers: [],
  callees: [
    {
      id: 501,
      target_symbol: 'chat_completion_endpoint',
      target_filepath: 'app/api/routers/chat.py',
      relationship_type: 'CALLS',
      line_number: 28,
    },
  ],
  imports: [
    {
      id: 702,
      target_symbol: 'pytest',
      relationship_type: 'IMPORTS',
      line_number: 2,
    },
  ],
};

async function setupNavigatorMocks(page: any) {
  await page.route('**/admin/api/stats', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockStats),
    });
  });

  await page.route('**/admin/api/repositories', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockRepos),
    });
  });

  await page.route('**/admin/api/repos', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockRepos),
    });
  });

  await page.route('**/admin/api/navigator/tree*', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockTreeData),
    });
  });

  await page.route('**/admin/api/navigator/file-outline*', async (route: any) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('README.md')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          repo: '__all__',
          filepath: 'README.md',
          language: 'markdown',
          symbols: [],
        }),
      });
    } else if (url.includes('tests/e2e/test_chat.py')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockOutlineTestChat),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockOutlineChat),
      });
    }
  });

  await page.route('**/admin/api/navigator/omni-search*', async (route: any) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('chat_completion')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: 'chat_completion',
          repo: '__all__',
          total_matches: 1,
          matches: [
            {
              id: 'sym_101',
              type: 'symbol',
              symbol_id: 101,
              name: 'chat_completion_endpoint',
              kind: 'function',
              filepath: 'app/api/routers/chat.py',
              repo: 'contextcortex-core',
              start_line: 45,
              end_line: 85,
              score: 0.99,
              score_label: '99% AST exact match',
              preview: 'async def chat_completion_endpoint(...)',
            },
          ],
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ query: '', repo: '__all__', total_matches: 0, matches: [] }),
      });
    }
  });

  await page.route('**/admin/api/files/read*', async (route: any) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('chat.py')) {
      const codeLines = Array.from({ length: 90 }, (_, i) => {
        const lineNum = i + 1;
        if (lineNum === 45) return 'async def chat_completion_endpoint(request: ChatCompletionRequest):';
        if (lineNum === 46) return '    return {"status": "ok"}';
        return `# Line ${lineNum} sample source code`;
      }).join('\n');

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          filepath: 'app/api/routers/chat.py',
          content: codeLines,
          total_lines: 90,
          language: 'python',
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          filepath: 'README.md',
          content: '# ContextCortex Documentation\n\nFull documentation reader is active.\n\n## Features\n\n- Hybrid Vector and Lexical Search\n- Interactive AST Symbol Navigator\n- Markdown and Source Code Viewer',
          total_lines: 8,
          language: 'markdown',
        }),
      });
    }
  });

  await page.route('**/admin/api/navigator/symbol-impact*', async (route: any) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('symbol_id=301')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockImpactTestChat),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockImpactChatCompletion),
      });
    }
  });
}

async function navigateToNavigator(page: any) {
  const menuToggle = page.locator('button.menu-toggle-btn');
  if (await menuToggle.isVisible()) {
    const isDrawerOpen = await page.locator('.dashboard-nav.drawer-open').isVisible();
    if (!isDrawerOpen) {
      await menuToggle.click();
    }
  }
  const tab = page.locator('button.nav-tab', { hasText: 'Navigator' });
  await tab.click();
}

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
    await expect(page.locator('[data-testid="metric-scope"]')).toHaveText('python');

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
    const copyBtn = page.locator('button[aria-label="Copy Permalink"]');
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
    await expect(page).toHaveNoElementCollisions();

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
    await expect(page).toHaveNoElementCollisions();
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

