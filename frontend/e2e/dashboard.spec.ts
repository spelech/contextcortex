import { test, expect } from '@playwright/test';

const mockStats = {
  repos_count: 2,
  symbols_count: 500,
  files_count: 15,
  points_count: 1000,
  last_indexed: '2026-08-17 00:00:00',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  rate_limit: { remaining: 5000, limit: 5000 },
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234'
};

const mockRepos = [
  {
    id: 1,
    name: 'notes-rag-mcp',
    url: 'https://github.com/example/notes-rag-mcp.git',
    branch: 'main',
    commit_sha: '687f7b1abcde12345',
    status: 'synced',
    file_count: 25,
    last_synced: '2026-08-17 00:00:00',
    last_error: null
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
    last_error: 'Authentication failed: Bad credentials'
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
    message: 'Indexing completed for repository notes-rag-mcp',
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

test.beforeEach(async ({ page }) => {
  // Setup default mock API routes
  await page.route('**/admin/api/stats', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockStats)
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
              repo: 'notes-rag-mcp',
              rel_path: 'app/api/auth.py',
              symbol: 'verify_token',
              start_line: 12,
              end_line: 35,
              content: 'def verify_token(token: str):\n    return True',
              github_url: 'https://github.com/example/notes-rag-mcp/blob/main/app/api/auth.py'
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
  await expect(page.locator('h1', { hasText: 'Code & Docs RAG Server' })).toBeVisible();
  await expect(page.getByText('v2.2.0')).toBeVisible();
  await expect(page.getByText('notes_rag_v2')).toBeVisible();
  await expect(page.getByText('5,000 / 5,000 reqs')).toBeVisible();

  // Overview tab
  await expect(page.getByText('System & Embedding Specs')).toBeVisible();
  await expect(page.getByText('Top Extracted Topics & Symbols')).toBeVisible();
  await expect(page.getByText('fastapi', { exact: true })).toBeVisible();
  await expect(page.getByText('tree-sitter', { exact: true })).toBeVisible();
  await expect(page.getByText('qdrant', { exact: true })).toBeVisible();

  // Git Repositories tab
  const gitTab = page.locator('button.nav-tab', { hasText: 'Git Repositories' });
  await gitTab.click();
  await expect(gitTab).toHaveClass(/active/);
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Local Paths tab
  const pathsTab = page.locator('button.nav-tab', { hasText: 'Local Paths' });
  await pathsTab.click();
  await expect(pathsTab).toHaveClass(/active/);
  await expect(page.getByText('Monitored Local Paths')).toBeVisible();

  // Search & Inspector tab
  const searchTab = page.locator('button.nav-tab', { hasText: 'Search & Inspector' });
  await searchTab.click();
  await expect(searchTab).toHaveClass(/active/);
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Settings tab
  const settingsTab = page.locator('button.nav-tab', { hasText: 'Settings' });
  await settingsTab.click();
  await expect(settingsTab).toHaveClass(/active/);
  await expect(page.getByText('GitHub Authentication & Rate Limits')).toBeVisible();

  // Diagnostics & Logs tab
  const diagTab = page.locator('button.nav-tab', { hasText: 'Diagnostics & Logs' });
  await diagTab.click();
  await expect(diagTab).toHaveClass(/active/);
  await expect(page.getByText('Diagnostics & Server Logs')).toBeVisible();
});

test('2. adds a new Git repository via modal and verifies table update + toast', async ({ page }) => {
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

  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
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

  // Verify modal closed, toast displayed, and new repository row visible
  await expect(page.getByText('Register Git Repository')).not.toBeVisible();
  await expect(page.locator('.toast-success', { hasText: "Repository 'fastapi-service' added successfully" })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'fastapi-service', exact: true })).toBeVisible();
});

test('3. triggers single-repo sync and verifies status feedback', async ({ page }) => {
  let syncRequested = false;

  await page.route('**/admin/api/repos/sync/1', async route => {
    syncRequested = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'syncing' })
    });
  });

  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Trigger sync on the first repo
  const syncBtn = page.getByRole('button', { name: 'Sync' }).first();
  await syncBtn.click();

  expect(syncRequested).toBe(true);
  await expect(page.locator('.toast-info', { hasText: 'Sync triggered successfully' })).toBeVisible();
});

test('4. deletes a repository with window.confirm dialog verification', async ({ page }) => {
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

  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Click delete button on first repo
  const deleteBtn = page.locator('button.btn-delete[title="Delete Repo"]').first();
  await deleteBtn.click();

  expect(dialogMessage).toContain("Are you sure you want to delete repository 'notes-rag-mcp'?");
  expect(deleteCalled).toBe(true);
  await expect(page.locator('.toast-success', { hasText: "Repository 'notes-rag-mcp' deleted successfully" })).toBeVisible();
});

test('5. renders repository error status with last_error diagnostic message', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Git Repositories' }).click();
  await expect(page.getByText('Registered Git Repositories')).toBeVisible();

  // Check the broken repo row
  const brokenRow = page.getByRole('row', { name: /broken-repo/ });
  await expect(brokenRow).toBeVisible();
  await expect(brokenRow.locator('.badge-danger', { hasText: 'Error' })).toBeVisible();
  await expect(brokenRow.getByText('Authentication failed: Bad credentials')).toBeVisible();
});

test('6. opens filesystem browser, navigates directories, and selects folder for local path', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Local Paths' }).click();
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

test('7. adds local path and deletes local path with confirmation', async ({ page }) => {
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

  await page.locator('button.nav-tab', { hasText: 'Local Paths' }).click();
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

  // Verify toast and added row
  await expect(page.getByText('Add Monitored Local Path')).not.toBeVisible();
  await expect(page.locator('.toast-success', { hasText: 'Path added successfully' })).toBeVisible();
  await expect(page.getByText('workspace-vault')).toBeVisible();
  await expect(page.getByText('knowledge-base')).toBeVisible();

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

  const deleteBtn = page.locator('button[aria-label="Delete Path"]').first();
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
                repo: 'notes-rag-mcp',
                rel_path: 'app/api/auth.py',
                symbol: 'verify_token',
                start_line: 12,
                end_line: 35,
                content: 'def verify_token(token: str):\n    return True',
                github_url: 'https://github.com/example/notes-rag-mcp/blob/main/app/api/auth.py'
              }
            }
          ]
        })
      });
    }
  });

  await page.locator('button.nav-tab', { hasText: 'Search & Inspector' }).click();
  await expect(page.getByText('Live Hybrid Search Inspector')).toBeVisible();

  // Test Code Search
  await page.getByPlaceholder(/e.g. JWT token/).fill('verify_token auth');
  await page.locator('input[placeholder="All Repos"]').fill('notes-rag-mcp');
  await page.locator('button[type="submit"]').click();

  expect(lastSearchPayload.query).toBe('verify_token auth');
  expect(lastSearchPayload.type).toBe('code');
  expect(lastSearchPayload.repo).toBe('notes-rag-mcp');

  await expect(page.getByText('app/api/auth.py')).toBeVisible();
  await expect(page.getByText('verify_token', { exact: true })).toBeVisible();
  await expect(page.getByText('RRF Score: 0.0450')).toBeVisible();
  await expect(page.getByText('View on GitHub')).toBeVisible();

  // Toggle to Doc Search
  await page.locator('select').selectOption('doc');
  await page.getByPlaceholder(/e.g. JWT token/).fill('architecture overview');
  await page.locator('button[type="submit"]').click();

  expect(lastSearchPayload.query).toBe('architecture overview');
  expect(lastSearchPayload.type).toBe('doc');

  await expect(page.getByText('docs/architecture.md')).toBeVisible();
  await expect(page.getByText('RRF Score: 0.0385')).toBeVisible();
  await expect(page.getByText('# System Architecture')).toBeVisible();
});

test('9. handles empty search query and error response states', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Search & Inspector' }).click();
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

  await page.locator('button.nav-tab', { hasText: 'Settings' }).click();
  await expect(page.getByText('GitHub Authentication & Rate Limits')).toBeVisible();

  // Verify initial token display
  await expect(page.getByText('ghp_****1234')).toBeVisible();
  await expect(page.getByText('Database', { exact: true })).toBeVisible();

  // Update token
  const tokenInput = page.locator('#github-token-input');
  await tokenInput.fill('ghp_updated_super_secret_pat_9999');

  // When saved, refreshStats fetches /admin/api/stats
  await page.route('**/admin/api/stats', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockStats,
        masked_token: 'ghp_****9999',
        rate_limit: { remaining: 5000, limit: 5000 }
      })
    });
  });

  await page.getByRole('button', { name: 'Save Token to DB' }).click();

  expect(savedToken).toBe('ghp_updated_super_secret_pat_9999');
  await expect(page.locator('.toast-success', { hasText: 'GitHub Token saved successfully.' })).toBeVisible();
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

  await page.locator('button.nav-tab', { hasText: 'Settings' }).click();
  await expect(page.getByText('GitHub Authentication & Rate Limits')).toBeVisible();

  await page.getByRole('button', { name: 'Clear Token' }).click();

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

  expect(reindexTriggered).toBe(true);
  await expect(page.locator('.toast-success', { hasText: 'Re-indexing triggered successfully' })).toBeVisible();
});

test('13. filters, searches, and clears logs in Diagnostics & Logs tab', async ({ page }) => {
  await page.locator('button.nav-tab', { hasText: 'Diagnostics & Logs' }).click();
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
  await expect(page.getByText('Indexing completed for repository notes-rag-mcp')).toBeVisible();
  await expect(page.getByText('High memory consumption during dense vector generation')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();
  await expect(page.getByText('Parsed 12 symbols in file app/api/auth.py')).toBeVisible();

  // Filter by ERROR
  await errPill.click();
  await expect(errPill).toHaveClass(/active/);
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();
  await expect(page.getByText('Indexing completed for repository notes-rag-mcp')).not.toBeVisible();
  await expect(page.getByText('High memory consumption during dense vector generation')).not.toBeVisible();

  // Filter by WARNING
  await warnPill.click();
  await expect(warnPill).toHaveClass(/active/);
  await expect(page.getByText('High memory consumption during dense vector generation')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).not.toBeVisible();

  // Reset to ALL
  await allPill.click();
  await expect(page.getByText('Indexing completed for repository notes-rag-mcp')).toBeVisible();
  await expect(page.getByText('Failed to clone repository broken-repo')).toBeVisible();

  // Search logs by text query
  const searchInput = page.locator('input.log-search-input');
  await searchInput.fill('ast_parser');
  await expect(page.getByText('Parsed 12 symbols in file app/api/auth.py')).toBeVisible();
  await expect(page.getByText('Indexing completed for repository notes-rag-mcp')).not.toBeVisible();

  // Clear search input using clear button
  const clearSearchBtn = page.locator('button.clear-search-btn');
  await clearSearchBtn.click();
  await expect(searchInput).toHaveValue('');
  await expect(page.getByText('Indexing completed for repository notes-rag-mcp')).toBeVisible();

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
