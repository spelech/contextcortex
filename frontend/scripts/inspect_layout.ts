import { chromium, type Browser, type Page } from '@playwright/test';
import * as path from 'path';
import { spawn, type ChildProcess } from 'child_process';
import { fileURLToPath } from 'url';
import {
  createInitialAuditReport,
  ensureDirectoryExists,
  evaluatePageLayout,
  recordTabAuditEvaluation,
  writeLayoutAuditReports,
  type AuditTabSpec,
  type LayoutAuditReport,
  type ViewportAuditReport,
  type ViewportConfig,
} from './layout_report_renderer.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FRONTEND_ROOT = path.resolve(__dirname, '..');
const DIST_REPORT_DIR = path.join(FRONTEND_ROOT, 'dist', 'layout-report');
const SCREENSHOTS_DIR = path.join(DIST_REPORT_DIR, 'screenshots');
const TEMPLATE_PATH = path.join(__dirname, 'report_template.html');

const VIEWPORTS: ViewportConfig[] = [
  { name: 'mobile-small', width: 375, height: 667, deviceScaleFactor: 2 },
  { name: 'mobile-standard', width: 390, height: 844, deviceScaleFactor: 2 },
  { name: 'tablet', width: 768, height: 1024, deviceScaleFactor: 2 },
  { name: 'desktop', width: 1280, height: 800, deviceScaleFactor: 2 },
];

const TABS: AuditTabSpec[] = [
  { id: 'overview', name: 'Overview' },
  { id: 'navigator', name: 'Navigator' },
  { id: 'git-repos', name: 'Git Repositories' },
  { id: 'local-paths', name: 'Local Paths' },
  { id: 'local-storage', name: 'Local Storage' },
  { id: 'ingestion-catalog', name: 'Ingestion Catalog' },
  { id: 'search-inspector', name: 'Search & Inspector' },
  { id: 'settings', name: 'Settings' },
  { id: 'diagnostics', name: 'Diagnostics & Logs' },
];

const MOCK_STATS = {
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
  masked_token: 'ghp_****1234',
};

const MOCK_VECTOR_STORE = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant',
  url: '',
  collection: 'knowledge_rag_v1',
};

const MOCK_REPOS = [
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
  },
  {
    id: 3,
    name: 'syncing-repo',
    url: 'https://github.com/example/syncing-repo.git',
    branch: 'main',
    commit_sha: 'c7d8e9f0',
    status: 'syncing',
    file_count: 42,
    last_synced: 'Just now',
    last_error: null,
  },
];

const MOCK_PATHS = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: 1,
    category: 'architecture',
    enabled: 1,
  },
  {
    id: 2,
    path: '/containers/dev/workspace/src',
    repo: 'backend-core',
    type: 'directory',
    recursive: 1,
    category: 'code',
    enabled: 1,
  },
];

const MOCK_LOGS = [
  {
    timestamp: '2026-08-17 01:00:00',
    level: 'INFO',
    logger: 'server.indexer',
    message: 'Indexing completed for repository knowledge-rag-mcp (25 files indexed)',
    traceback: null,
  },
  {
    timestamp: '2026-08-17 01:01:00',
    level: 'WARNING',
    logger: 'server.fastembed',
    message: 'High memory consumption detected during dense vector embedding generation',
    traceback: null,
  },
  {
    timestamp: '2026-08-17 01:02:00',
    level: 'ERROR',
    logger: 'server.git',
    message: 'Failed to clone repository broken-repo from remote',
    traceback:
      'Traceback (most recent call last):\n  File "git.py", line 45, in clone\n    raise GitCommandError("auth failed")\nGitCommandError: Authentication failed',
  },
  {
    timestamp: '2026-08-17 01:03:00',
    level: 'DEBUG',
    logger: 'server.ast_parser',
    message: 'Parsed 12 symbols in file app/api/auth.py',
    traceback: null,
  },
];

const MOCK_BROWSE = {
  current_path: '/containers/dev/workspace',
  parent_path: '/containers/dev',
  directories: [
    { name: 'docs', path: '/containers/dev/workspace/docs' },
    { name: 'src', path: '/containers/dev/workspace/src' },
  ],
  files: [{ name: 'README.md', path: '/containers/dev/workspace/README.md' }],
};

const MOCK_SEARCH = {
  query: 'JWT authentication',
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
        content: 'def verify_token(token: str) -> bool:\n    """Verify JWT access token."""\n    return True',
        github_url: 'https://github.com/example/knowledge-rag-mcp/blob/main/app/api/auth.py',
      },
    },
  ],
};

async function isServerRunning(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'HEAD' });
    return res.ok || res.status === 404 || res.status === 200;
  } catch {
    return false;
  }
}

async function startDevServer(): Promise<{ process?: ChildProcess; url: string }> {
  const targetUrl = 'http://localhost:5173';
  if (await isServerRunning(targetUrl)) {
    console.log(`[Inspector] Existing dev server detected at ${targetUrl}`);
    return { url: targetUrl };
  }

  console.log('[Inspector] Spawning local Vite dev server...');
  const child = spawn('npm', ['run', 'dev'], {
    cwd: FRONTEND_ROOT,
    stdio: 'pipe',
    detached: false,
  });

  child.stderr?.on('data', () => {
    // Suppress noisy Vite stderr output during automated run
  });

  const startTime = Date.now();
  const timeoutMs = 20000;
  while (Date.now() - startTime < timeoutMs) {
    if (await isServerRunning(targetUrl)) {
      console.log(`[Inspector] Dev server successfully ready at ${targetUrl}`);
      return { process: child, url: targetUrl };
    }
    await new Promise((r) => setTimeout(r, 200));
  }

  child.kill();
  throw new Error(`Timeout waiting for dev server at ${targetUrl}`);
}

async function setupRouteMocks(page: Page): Promise<void> {
  const jsonReply = (payload: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });

  await page.route('**/admin/api/stats', (route) => route.fulfill(jsonReply(MOCK_STATS)));
  await page.route('**/admin/api/vector-store', (route) => route.fulfill(jsonReply(MOCK_VECTOR_STORE)));
  await page.route('**/admin/api/repos', (route) => route.fulfill(jsonReply(MOCK_REPOS)));
  await page.route('**/admin/api/repos/sync-status', (route) =>
    route.fulfill(
      jsonReply({
        3: {
          repo_id: 3,
          repo_name: 'syncing-repo',
          status: 'syncing',
          step: 3,
          total_steps: 5,
          step_name: 'Computing File Delta & Scanning',
          current_file: 'src/services/git.ts',
          processed_files: 18,
          total_files: 42,
          percent: 45,
          started_at: Date.now() / 1000 - 20,
          updated_at: Date.now() / 1000,
          logs: [
            { timestamp: '12:00:01', level: 'INFO', message: 'Cloned branch main' },
            { timestamp: '12:00:05', level: 'INFO', message: 'Scanning delta' },
          ],
          cancelled: false,
        },
      })
    )
  );
  await page.route('**/admin/api/paths', (route) => route.fulfill(jsonReply(MOCK_PATHS)));
  await page.route('**/admin/api/browse*', (route) => route.fulfill(jsonReply(MOCK_BROWSE)));
  await page.route('**/admin/api/search/test*', (route) => route.fulfill(jsonReply(MOCK_SEARCH)));
  await page.route('**/admin/api/settings/hosts*', (route) => route.fulfill(jsonReply([])));
  await page.route('**/admin/api/settings/token', (route) => route.fulfill(jsonReply({ status: 'saved' })));
  await page.route('**/admin/api/logs', (route) => route.fulfill(jsonReply(MOCK_LOGS)));
  await page.route('**/admin/api/reindex', (route) =>
    route.fulfill(jsonReply({ status: 'indexing_started' }))
  );
  await page.route('**/admin/api/navigator/tree*', (route) =>
    route.fulfill(
      jsonReply({
        repo: '__all__',
        total_files: 2,
        total_symbols: 4,
        tree: [
          {
            id: 'file:app/main.py',
            name: 'main.py',
            is_dir: false,
            path: 'app/main.py',
            language: 'python',
            symbol_count: 4,
          },
          {
            id: 'file:README.md',
            name: 'README.md',
            is_dir: false,
            path: 'README.md',
            language: 'markdown',
            symbol_count: 0,
          },
        ],
      })
    )
  );
  await page.route('**/admin/api/navigator/file-outline*', (route) =>
    route.fulfill(
      jsonReply({
        repo: '__all__',
        filepath: 'app/main.py',
        language: 'python',
        symbols: [
          {
            id: 1,
            name: 'init_app',
            full_symbol: 'app.main.init_app',
            kind: 'function',
            start_line: 1,
            end_line: 20,
            signature: 'def init_app():',
          },
        ],
      })
    )
  );
  await page.route('**/admin/api/files/read*', (route) =>
    route.fulfill(
      jsonReply({
        filepath: 'README.md',
        content: '# ContextCortex\n\nFast code and doc search.',
        total_lines: 3,
        language: 'markdown',
      })
    )
  );
}

async function navigateToTab(page: Page, tabName: string, isMobile: boolean): Promise<void> {
  if (isMobile) {
    const menuToggle = page.locator('button.menu-toggle-btn');
    if (await menuToggle.isVisible()) {
      const isDrawerOpen = await page.locator('.dashboard-nav.drawer-open').isVisible();
      if (!isDrawerOpen) {
        await menuToggle.click();
        await page.waitForTimeout(200);
      }
    }
  }

  const tabBtn = page.locator('button.nav-tab', { hasText: tabName });
  if (await tabBtn.isVisible()) {
    await tabBtn.click();
    await page.waitForTimeout(300);
  }
}

export async function runLayoutInspection(): Promise<LayoutAuditReport> {
  console.log('====================================================');
  console.log(' Knowledge RAG Hub - LLM Layout & Bounding Box Audit');
  console.log('====================================================\n');

  await ensureDirectoryExists(DIST_REPORT_DIR);
  await ensureDirectoryExists(SCREENSHOTS_DIR);

  let devServer: { process?: ChildProcess; url: string } | null = null;
  let browser: Browser | null = null;

  try {
    devServer = await startDevServer();
    browser = await chromium.launch({ headless: true });

    const auditResults = createInitialAuditReport(VIEWPORTS.length, TABS.length);

    for (const vp of VIEWPORTS) {
      console.log(`\n📱 Inspecting Viewport: ${vp.name} (${vp.width}x${vp.height})...`);
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: vp.deviceScaleFactor,
      });

      const page = await context.newPage();
      page.on('console', (msg) => console.log(`[Browser ${msg.type()}]`, msg.text()));
      page.on('pageerror', (err) => console.error('[Browser PageError]', err));
      await setupRouteMocks(page);

      await page.goto(devServer.url, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.dashboard-container');
      await page.waitForTimeout(500);

      const vpReport: ViewportAuditReport = {
        name: vp.name,
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: vp.deviceScaleFactor,
        tabs: [],
      };

      const isMobile = vp.width <= 768;

      for (const tab of TABS) {
        process.stdout.write(`   -> Tab: ${tab.name} `);

        await navigateToTab(page, tab.name, isMobile);
        await page.waitForTimeout(400);

        const screenshotFileName = `${vp.name}_${tab.id}.png`;
        const screenshotPath = path.join(SCREENSHOTS_DIR, screenshotFileName);
        const relativeScreenshotPath = `screenshots/${screenshotFileName}`;

        await page.screenshot({ path: screenshotPath, fullPage: false });

        const evaluation = await evaluatePageLayout(page, vp.width, vp.height);
        recordTabAuditEvaluation(auditResults, vpReport, tab, relativeScreenshotPath, evaluation);
      }

      auditResults.viewports.push(vpReport);
      await context.close();
    }

    writeLayoutAuditReports(auditResults, DIST_REPORT_DIR, TEMPLATE_PATH);
    return auditResults;
  } finally {
    if (browser) {
      await browser.close();
    }
    if (devServer?.process) {
      console.log('[Inspector] Cleaning up dev server process...');
      devServer.process.kill();
    }
  }
}

if (
  process.argv[1] &&
  (process.argv[1].endsWith('inspect_layout.ts') || process.argv[1].endsWith('inspect_layout.js'))
) {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node --experimental-strip-types scripts/inspect_layout.ts [--help]');
    process.exit(0);
  }

  runLayoutInspection()
    .then((results) => {
      if (!results.summary.passed) {
        console.warn('[Inspector] Layout violations detected.');
      }
      process.exit(0);
    })
    .catch((err) => {
      console.error('[Inspector] Fatal execution error:', err);
      process.exit(1);
    });
}
