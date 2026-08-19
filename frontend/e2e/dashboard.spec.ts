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

const mockVectorStore = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant',
  url: '',
  collection: 'knowledge_rag_v1'
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
    last_synced: '2026-08-17 00:00:00',
    last_error: null,
    auto_sync: 1,
    webhook_secret: null
  },
  {
    id: 2,
    name: 'broken-repo',
    url: 'https://github.com/example/broken-repo.git',
    branch: 'main',
    commit_sha: null,
    status: 'error',
    file_count: 0,
    last_synced: 'Never',
    last_error: 'Authentication failed: Bad credentials',
    auto_sync: 0,
    webhook_secret: null
  }
];

const mockPaths = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: true,
    category: 'architecture',
    enabled: true
  }
];

const mockLogs = [
  {
    timestamp: '2026-08-17 01:00:00',
    level: 'INFO',
    logger: 'server.indexer',
    message: 'Indexing completed for repository knowledge-rag-mcp',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:01:00',
    level: 'WARNING',
    logger: 'server.fastembed',
    message: 'High memory consumption during dense vector generation',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:02:00',
    level: 'ERROR',
    logger: 'server.git',
    message: 'Failed to clone repository broken-repo',
    traceback: 'Traceback (most recent call last):\n  File "git.py", line 45, in clone\n    raise GitCommandError("auth failed")\nGitCommandError: auth failed'
  },
  {
    timestamp: '2026-08-17 01:03:00',
    level: 'DEBUG',
    logger: 'server.ast_parser',
    message: 'Parsed 12 symbols in file app/api/auth.py',
    traceback: null
  }
];

const mockBrowseRoot = {
  current_path: '/containers/dev/workspace',
  parent_path: '/containers/dev',
  directories: [
    { name: 'docs', path: '/containers/dev/workspace/docs' },
    { name: 'src', path: '/containers/dev/workspace/src' }
  ],
  files: [
    { name: 'README.md', path: '/containers/dev/workspace/README.md' }
  ]
};

const mockBrowseDocs = {
  current_path: '/containers/dev/workspace/docs',
  parent_path: '/containers/dev/workspace',
  directories: [
    { name: 'architecture', path: '/containers/dev/workspace/docs/architecture' }
  ],
  files: [
    { name: 'spec.md', path: '/containers/dev/workspace/docs/spec.md' }
  ]
};

async function navigateToTab(page: any, tabName: string) {
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

test.beforeEach(async ({ page }) => {
  // Setup default mock API routes
  await page.route('**/admin/api/stats', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockStats)
    });
  });

  await page.route('**/admin/api/vector-store', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVectorStore)
    });
  });

  await page.route('**/admin/api/repos', async route => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 3,
          name: payload.name || 'new-repo',
          url: payload.url,
          branch: payload.branch || 'main',
          status: 'pending',
          file_count: 0
        })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockRepos)
      });
    }
  });

  await page.route('**/admin/api/repos/sync/*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'syncing' })
    });
  });

  await page.route('**/admin/api/repos/*', async route => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted' })
      });
    } else {
      await route.fallback();
    }
  });

  await page.route('**/admin/api/paths', async route => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 2,
          path: payload.path,
          repo: payload.repo || 'local',
          type: payload.type || 'directory',
          recursive: payload.recursive ?? 1,
          category: payload.category || null,
          enabled: 1
        })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockPaths)
      });
    }
  });

  await page.route('**/admin/api/paths/*', async route => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted' })
      });
    } else {
      await route.fallback();
    }
  });

  await page.route('**/admin/api/browse*', async route => {
    const url = new URL(route.request().url());
    const pathParam = url.searchParams.get('path');
    if (pathParam && pathParam.includes('docs')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockBrowseDocs)
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockBrowseRoot)
      });
    }
  });

  await page.route('**/admin/api/search/test', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        query: 'JWT auth',
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
  });

  await page.route('**/admin/api/settings/token', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'saved' })
    });
  });

  await page.route('**/admin/api/settings/auto-sync*', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success', interval_mins: 15, has_global_secret: false })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          interval_mins: 15,
          webhook_url: 'http://localhost:5173/api/webhooks/git',
          has_global_secret: false
        })
      });
    }
  });

  await page.route('**/admin/api/repos/*/auto-sync', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', repo_id: 1, auto_sync: false })
    });
  });

  await page.route('**/admin/api/settings/hosts*', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' })
      });
    } else if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      });
    }
  });

  await page.route('**/admin/api/reindex', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'indexing_started' })
    });
  });

  await page.route('**/admin/api/logs', async route => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'cleared' })
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockLogs)
      });
    }
  });

  await page.goto('/');
});

test('1. navigates through all tabs including Diagnostics & Logs', async ({ page }) => {
  // Header and engine state
  await expect(page.locator('h1', { hasText: 'ContextCortex' })).toBeVisible();
  await expect(page.getByText('v2.7.0')).toBeVisible();
  await expect(page.getByText('knowledge_rag_v1')).toBeVisible();

  // Overview tab
  await expect(page.getByText('System & Embedding Specs')).toBeVisible();
  await expect(page.getByText('Top Extracted Topics & Symbols')).toBeVisible();
  await expect(page.getByText('fastapi', { exact: true })).toBeVisible();
  await expect(page.getByText('tree-sitter', { exact: true })).toBeVisible();
  await expect(page.getByText('qdrant', { exact: true })).toBeVisible();

  // Git Repositories tab
  await navigateToTab(page, 'Git Repositories');
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Local Paths tab
  await navigateToTab(page, 'Local Paths');
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();

  // Search & Inspector tab
  await navigateToTab(page, 'Search & Inspector');
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Settings tab
  await navigateToTab(page, 'Settings');
  await expect(page.getByText('Global Git Provider Authentication')).toBeVisible();

  // Diagnostics & Logs tab
  await navigateToTab(page, 'Diagnostics & Logs');
  await expect(page.getByText('Diagnostics & Server Logs')).toBeVisible();
});

test('2. adds a new Git repository via modal and verifies table/card update + toast', async ({ page, isMobile }) => {
  let repoList = [...mockRepos];

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
  let pathList = [...mockPaths];

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
  await expect(page.getByText('RRF Score: 0.0450')).toBeVisible();
  await expect(page.getByText('View on GitHub')).toBeVisible();

  // Toggle to Doc Search
  await page.locator('.search-bar select, .dashboard-main select').first().selectOption('doc');
  await page.getByPlaceholder(/e.g. JWT token/).fill('architecture overview');
  await page.locator('button[type="submit"]').click();

  expect(lastSearchPayload.query).toBe('architecture overview');
  expect(lastSearchPayload.type).toBe('doc');

  await expect(page.getByText('docs/architecture.md')).toBeVisible();
  await expect(page.getByText('RRF Score: 0.0385')).toBeVisible();
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
  await expect(page.getByText('Global Git Provider Authentication')).toBeVisible();

  await page.locator('.settings-provider-box').filter({ hasText: 'GitHub' }).getByRole('button', { name: 'Clear' }).click();

  expect(dialogMessage).toContain('Clear the stored GitHub token from database?');
  expect(clearCalled).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'GitHub token cleared' })).toBeVisible();
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
  await expect(page.locator('.nav-tab', { hasText: 'Local Paths' })).toBeVisible();
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
  await expect(resultCard.getByText('RRF Score: 0.0450')).toBeVisible();
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

