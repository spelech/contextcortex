import type { Page } from '@playwright/test';

export const mockStats = {
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
  vector_db_status: 'Healthy',
  rate_limit: { remaining: 5000, limit: 5000 },
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant'],
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****1234',
};

export const mockVectorStore = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant',
  url: '',
  collection: 'knowledge_rag_v1',
};

export const mockRepos = [
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
    webhook_secret: null,
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
    webhook_secret: null,
  },
];

export const mockPaths = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: true,
    category: 'architecture',
    enabled: true,
  },
];

export const mockLogs = [
  {
    timestamp: '2026-08-17 01:00:00',
    level: 'INFO',
    logger: 'server.indexer',
    message: 'Indexing completed for repository knowledge-rag-mcp',
    traceback: null,
  },
  {
    timestamp: '2026-08-17 01:01:00',
    level: 'WARNING',
    logger: 'server.fastembed',
    message: 'High memory consumption during dense vector generation',
    traceback: null,
  },
  {
    timestamp: '2026-08-17 01:02:00',
    level: 'ERROR',
    logger: 'server.git',
    message: 'Failed to clone repository broken-repo',
    traceback:
      'Traceback (most recent call last):\n  File "git.py", line 45, in clone\n    raise GitCommandError("auth failed")\nGitCommandError: auth failed',
  },
  {
    timestamp: '2026-08-17 01:03:00',
    level: 'DEBUG',
    logger: 'server.ast_parser',
    message: 'Parsed 12 symbols in file app/api/auth.py',
    traceback: null,
  },
];

export const mockBrowseRoot = {
  current_path: '/containers/dev/workspace',
  parent_path: '/containers/dev',
  directories: [
    { name: 'docs', path: '/containers/dev/workspace/docs' },
    { name: 'src', path: '/containers/dev/workspace/src' },
  ],
  files: [{ name: 'README.md', path: '/containers/dev/workspace/README.md' }],
};

export const mockBrowseDocs = {
  current_path: '/containers/dev/workspace/docs',
  parent_path: '/containers/dev/workspace',
  directories: [{ name: 'architecture', path: '/containers/dev/workspace/docs/architecture' }],
  files: [{ name: 'spec.md', path: '/containers/dev/workspace/docs/spec.md' }],
};

export async function navigateToTab(page: Page, tabName: string): Promise<void> {
  const menuToggle = page.locator('button.menu-toggle-btn');
  if (await menuToggle.isVisible()) {
    const isDrawerOpen = await page.locator('.dashboard-nav.drawer-open').isVisible();
    if (!isDrawerOpen) {
      await menuToggle.click();
    }
  }
  const resolvedName = tabName === 'Local Paths' ? 'Files & Storage' : tabName;
  await page.locator('button.nav-tab', { hasText: resolvedName }).click();
}

export async function setupDashboardRouteMocks(page: Page): Promise<void> {
  const jsonReply = (payload: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });

  await page.route('**/admin/api/stats', (route) => route.fulfill(jsonReply(mockStats)));
  await page.route('**/admin/api/vector-store', (route) => route.fulfill(jsonReply(mockVectorStore)));

  await page.route('**/admin/api/repos', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      await route.fulfill(
        jsonReply({
          id: 3,
          name: payload.name || 'new-repo',
          url: payload.url,
          branch: payload.branch || 'main',
          status: 'pending',
          file_count: 0,
        })
      );
    } else {
      await route.fulfill(jsonReply(mockRepos));
    }
  });

  await page.route('**/admin/api/repos/sync/*', (route) => route.fulfill(jsonReply({ status: 'syncing' })));
  await page.route('**/admin/api/repos/sync-status', (route) => route.fulfill(jsonReply({})));
  await page.route('**/admin/api/repos/sync/stream', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: init\ndata: {}\n\n' })
  );

  await page.route('**/admin/api/repos/*', async (route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill(jsonReply({ status: 'deleted' }));
    } else {
      await route.fallback();
    }
  });

  await page.route('**/admin/api/paths', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      await route.fulfill(
        jsonReply({
          id: 2,
          path: payload.path,
          repo: payload.repo || 'local',
          type: payload.type || 'directory',
          recursive: payload.recursive ?? 1,
          category: payload.category || null,
          enabled: 1,
        })
      );
    } else {
      await route.fulfill(jsonReply(mockPaths));
    }
  });

  await page.route('**/admin/api/paths/*', async (route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill(jsonReply({ status: 'deleted' }));
    } else {
      await route.fallback();
    }
  });

  await page.route('**/admin/api/browse*', async (route) => {
    const pathParam = new URL(route.request().url()).searchParams.get('path');
    await route.fulfill(jsonReply(pathParam?.includes('docs') ? mockBrowseDocs : mockBrowseRoot));
  });

  await page.route('**/admin/api/search/test', (route) =>
    route.fulfill(
      jsonReply({
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
              github_url: 'https://github.com/example/knowledge-rag-mcp/blob/main/app/api/auth.py',
            },
          },
        ],
      })
    )
  );

  await page.route('**/admin/api/settings/token', (route) => route.fulfill(jsonReply({ status: 'saved' })));

  await page.route('**/admin/api/settings/auto-sync*', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill(jsonReply({ status: 'success', interval_mins: 15, has_global_secret: false }));
    } else {
      await route.fulfill(
        jsonReply({
          interval_mins: 15,
          webhook_url: 'http://localhost:5173/api/webhooks/git',
          has_global_secret: false,
        })
      );
    }
  });

  await page.route('**/admin/api/repos/*/auto-sync', (route) =>
    route.fulfill(jsonReply({ status: 'success', repo_id: 1, auto_sync: false }))
  );

  await page.route('**/admin/api/settings/hosts*', async (route) => {
    const method = route.request().method();
    await route.fulfill(jsonReply(method === 'POST' || method === 'DELETE' ? { status: 'success' } : []));
  });

  await page.route('**/admin/api/reindex', (route) => route.fulfill(jsonReply({ status: 'indexing_started' })));

  await page.route('**/admin/api/logs', async (route) => {
    await route.fulfill(jsonReply(route.request().method() === 'DELETE' ? { status: 'cleared' } : mockLogs));
  });
}
