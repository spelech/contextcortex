import { chromium, type Browser, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { spawn, type ChildProcess } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FRONTEND_ROOT = path.resolve(__dirname, '..');
const DIST_REPORT_DIR = path.join(FRONTEND_ROOT, 'dist', 'layout-report');
const SCREENSHOTS_DIR = path.join(DIST_REPORT_DIR, 'screenshots');
const TEMPLATE_PATH = path.join(__dirname, 'report_template.html');

interface ViewportConfig {
  name: string;
  width: number;
  height: number;
  deviceScaleFactor: number;
}

const VIEWPORTS: ViewportConfig[] = [
  { name: 'mobile-small', width: 375, height: 667, deviceScaleFactor: 2 },
  { name: 'mobile-standard', width: 390, height: 844, deviceScaleFactor: 2 },
  { name: 'tablet', width: 768, height: 1024, deviceScaleFactor: 2 },
  { name: 'desktop', width: 1280, height: 800, deviceScaleFactor: 2 },
];

const TABS = [
  { id: 'overview', name: 'Overview' },
  { id: 'git-repos', name: 'Git Repositories' },
  { id: 'local-paths', name: 'Local Paths' },
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
  masked_token: 'ghp_****1234'
};

const MOCK_VECTOR_STORE = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant',
  url: '',
  collection: 'knowledge_rag_v1'
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
    last_error: null
  }
];

const MOCK_PATHS = [
  {
    id: 1,
    path: '/containers/dev/workspace/docs',
    repo: 'docs-vault',
    type: 'directory',
    recursive: 1,
    category: 'architecture',
    enabled: 1
  },
  {
    id: 2,
    path: '/containers/dev/workspace/src',
    repo: 'backend-core',
    type: 'directory',
    recursive: 1,
    category: 'code',
    enabled: 1
  }
];

const MOCK_LOGS = [
  {
    timestamp: '2026-08-17 01:00:00',
    level: 'INFO',
    logger: 'server.indexer',
    message: 'Indexing completed for repository knowledge-rag-mcp (25 files indexed)',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:01:00',
    level: 'WARNING',
    logger: 'server.fastembed',
    message: 'High memory consumption detected during dense vector embedding generation',
    traceback: null
  },
  {
    timestamp: '2026-08-17 01:02:00',
    level: 'ERROR',
    logger: 'server.git',
    message: 'Failed to clone repository broken-repo from remote',
    traceback: 'Traceback (most recent call last):\n  File "git.py", line 45, in clone\n    raise GitCommandError("auth failed")\nGitCommandError: Authentication failed'
  },
  {
    timestamp: '2026-08-17 01:03:00',
    level: 'DEBUG',
    logger: 'server.ast_parser',
    message: 'Parsed 12 symbols in file app/api/auth.py',
    traceback: null
  }
];

const MOCK_BROWSE = {
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
        github_url: 'https://github.com/example/knowledge-rag-mcp/blob/main/app/api/auth.py'
      }
    }
  ]
};

async function ensureDirectoryExists(dirPath: string) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

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

  console.log(`[Inspector] Spawning local Vite dev server...`);
  const child = spawn('npm', ['run', 'dev'], {
    cwd: FRONTEND_ROOT,
    stdio: 'pipe',
    detached: false
  });

  child.stderr?.on('data', (d) => {
    // console.error('[Vite stderr]', d.toString());
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

async function setupRouteMocks(page: Page) {
  await page.route('**/admin/api/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_STATS)
    });
  });

  await page.route('**/admin/api/vector-store', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_VECTOR_STORE)
    });
  });

  await page.route('**/admin/api/repos', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_REPOS)
    });
  });

  await page.route('**/admin/api/repos/sync-status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
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
            { timestamp: '12:00:05', level: 'INFO', message: 'Scanning delta' }
          ],
          cancelled: false
        }
      })
    });
  });

  await page.route('**/admin/api/paths', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_PATHS)
    });
  });

  await page.route('**/admin/api/browse*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_BROWSE)
    });
  });

  await page.route('**/admin/api/search/test*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SEARCH)
    });
  });

  await page.route('**/admin/api/settings/hosts*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([])
    });
  });

  await page.route('**/admin/api/settings/token', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'saved' })
    });
  });

  await page.route('**/admin/api/logs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_LOGS)
    });
  });

  await page.route('**/admin/api/reindex', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'indexing_started' })
    });
  });
}

async function navigateToTab(page: Page, tabName: string, isMobile: boolean) {
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

async function evaluatePageLayout(page: Page, viewportWidth: number, viewportHeight: number) {
  return await page.evaluate((args: { viewportWidth: number; viewportHeight: number }) => {
    const { viewportWidth, viewportHeight } = args;

    function getElementSelector(el: Element): string {
      if (el.id) return `#${el.id}`;
      const tag = el.tagName.toLowerCase();
      const classes = Array.from(el.classList)
        .filter(c => !c.startsWith('ng-') && !c.includes(':') && c.length < 30)
        .slice(0, 3);
      const classStr = classes.length > 0 ? `.${classes.join('.')}` : '';
      
      let parentDesc = '';
      if (el.parentElement && el.parentElement !== document.body && el.parentElement !== document.documentElement) {
        const parentTag = el.parentElement.tagName.toLowerCase();
        const parentFirstClass = el.parentElement.classList.length > 0 ? `.${el.parentElement.classList[0]}` : '';
        parentDesc = `${parentTag}${parentFirstClass} > `;
      }
      return `${parentDesc}${tag}${classStr}`;
    }

    const elementsToCheck: Array<{
      el: HTMLElement;
      selector: string;
      tag: string;
      text: string;
      rect: DOMRect;
    }> = [];

    // Query candidate UI components
    const candidates = document.querySelectorAll(
      'header, nav, main, section, div.card, div.repo-card, div.path-card, div.metric-card, div.stat-card, div.system-spec-card, ' +
      'button, input, select, textarea, form, .form-group, .form-row, .btn, .badge, ' +
      'table, tr, th, td, .log-item, .search-result-item, .header-status, .status-item, h1, h2, h3, p'
    );

    const seenElements = new Set<Element>();

    candidates.forEach((node) => {
      const el = node as HTMLElement;
      if (!el || seenElements.has(el)) return;
      seenElements.add(el);

      // Skip background decorations and hidden elements
      if (el.classList.contains('background-decor') || el.classList.contains('circle')) return;
      
      const style = window.getComputedStyle(el);
      if (
        style.display === 'none' ||
        style.visibility === 'hidden' ||
        parseFloat(style.opacity || '1') === 0
      ) {
        return;
      }

      // Check if inside closed drawer
      const navParent = el.closest('.dashboard-nav');
      if (navParent && !navParent.classList.contains('drawer-open') && window.innerWidth < 768) {
        return;
      }

      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      elementsToCheck.push({
        el,
        selector: getElementSelector(el),
        tag: el.tagName,
        text: (el.innerText || el.textContent || '').trim().slice(0, 40),
        rect
      });
    });

    const evaluatedElements: any[] = [];
    const violations: any[] = [];

    for (let i = 0; i < elementsToCheck.length; i++) {
      const item = elementsToCheck[i];
      const { el, selector, tag, text, rect } = item;
      const style = window.getComputedStyle(el);

      let status: 'clean' | 'overflow' | 'clipping' | 'collision' = 'clean';
      let violationType: string | undefined = undefined;
      let details: string | undefined = undefined;
      let overflowPixels = 0;

      // 1. Viewport Overflow Check
      const scrollParent = el.closest('.table-container, .table-responsive, [style*="overflow-x: auto"], [style*="overflow-x: scroll"], pre, .traceback-container, .traceback-box');
      const isInsideScrollContainer = scrollParent && scrollParent !== el;

      const rightOverflow = rect.right - viewportWidth;
      const leftOverflow = -rect.left;

      if (!isInsideScrollContainer) {
        if (rightOverflow > 0.5) {
          status = 'overflow';
          violationType = 'VIEWPORT_OVERFLOW';
          overflowPixels = Math.round(rightOverflow * 10) / 10;
          details = `Element overflows viewport right edge by ${overflowPixels}px (rect.right: ${rect.right.toFixed(1)}px, viewport: ${viewportWidth}px)`;
        } else if (leftOverflow > 0.5 && !style.position?.includes('fixed')) {
          status = 'overflow';
          violationType = 'VIEWPORT_OVERFLOW';
          overflowPixels = Math.round(leftOverflow * 10) / 10;
          details = `Element overflows viewport left edge by ${overflowPixels}px (rect.left: ${rect.left.toFixed(1)}px)`;
        }
      }

      // 2. Container Scroll Clipping Check
      if (status === 'clean' && el.scrollWidth > el.clientWidth + 1.5) {
        const isDesignatedScroll =
          style.overflowX === 'auto' ||
          style.overflowX === 'scroll' ||
          style.overflow === 'hidden' ||
          style.textOverflow === 'ellipsis' ||
          el.classList.contains('table-container') ||
          el.classList.contains('table-responsive') ||
          el.classList.contains('traceback-container') ||
          el.classList.contains('traceback-box') ||
          tag === 'PRE' ||
          tag === 'CODE' ||
          tag === 'INPUT' ||
          tag === 'TEXTAREA' ||
          tag === 'SELECT';

        if (!isDesignatedScroll) {
          status = 'clipping';
          violationType = 'CONTAINER_CLIPPING';
          overflowPixels = el.scrollWidth - el.clientWidth;
          details = `Container content (${el.scrollWidth}px) exceeds client width (${el.clientWidth}px) without intentional scroll wrapper`;
        }
      }

      // 3. Bounding Box Collision Check (with subsequent elements)
      if (status === 'clean') {
        for (let j = i + 1; j < elementsToCheck.length; j++) {
          const other = elementsToCheck[j];
          // Skip if one contains the other
          if (el.contains(other.el) || other.el.contains(el)) continue;
          if (el.parentElement !== other.el.parentElement) continue; // Compare siblings or direct relative flow

          const oRect = other.rect;
          const xOverlap = Math.min(rect.right, oRect.right) - Math.max(rect.left, oRect.left);
          const yOverlap = Math.min(rect.bottom, oRect.bottom) - Math.max(rect.top, oRect.top);

          if (xOverlap > 4 && yOverlap > 4) {
            const oStyle = window.getComputedStyle(other.el);
            if (style.position === 'absolute' || oStyle.position === 'absolute' || style.position === 'fixed' || oStyle.position === 'fixed') {
              continue; // Exclude intentional overlays
            }
            status = 'collision';
            violationType = 'ELEMENT_COLLISION';
            details = `Element collides with sibling ${other.selector} (overlap area: ${Math.round(xOverlap)}x${Math.round(yOverlap)}px)`;
            break;
          }
        }
      }

      const elementData = {
        selector,
        tag,
        text,
        box: {
          x: Math.round(rect.x * 10) / 10,
          y: Math.round(rect.y * 10) / 10,
          width: Math.round(rect.width * 10) / 10,
          height: Math.round(rect.height * 10) / 10
        },
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        status,
        violationType,
        overflowPixels: overflowPixels > 0 ? overflowPixels : undefined,
        details
      };

      evaluatedElements.push(elementData);
      if (status !== 'clean') {
        violations.push(elementData);
      }
    }

    return {
      elements: evaluatedElements,
      violations
    };
  }, { viewportWidth, viewportHeight });
}

export async function runLayoutInspection() {
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

    const auditResults: any = {
      timestamp: new Date().toISOString(),
      summary: {
        totalViewports: VIEWPORTS.length,
        totalTabs: TABS.length,
        totalEvaluations: VIEWPORTS.length * TABS.length,
        totalViolations: 0,
        overflowViolations: 0,
        clippingViolations: 0,
        collisionViolations: 0,
        passed: true
      },
      viewports: []
    };

    for (const vp of VIEWPORTS) {
      console.log(`\n📱 Inspecting Viewport: ${vp.name} (${vp.width}x${vp.height})...`);
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: vp.deviceScaleFactor
      });

      const page = await context.newPage();
      await setupRouteMocks(page);

      await page.goto(devServer.url, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.dashboard-container');
      await page.waitForTimeout(500);

      const vpReport: any = {
        name: vp.name,
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: vp.deviceScaleFactor,
        tabs: []
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

        const tabReport = {
          tab: tab.id,
          tabName: tab.name,
          screenshot: relativeScreenshotPath,
          elementsCount: evaluation.elements.length,
          violationsCount: evaluation.violations.length,
          violations: evaluation.violations,
          elements: evaluation.elements
        };

        vpReport.tabs.push(tabReport);

        // Update summaries
        auditResults.summary.totalViolations += evaluation.violations.length;
        evaluation.violations.forEach((v: any) => {
          if (v.violationType === 'VIEWPORT_OVERFLOW') auditResults.summary.overflowViolations++;
          else if (v.violationType === 'CONTAINER_CLIPPING') auditResults.summary.clippingViolations++;
          else if (v.violationType === 'ELEMENT_COLLISION') auditResults.summary.collisionViolations++;
        });

        if (evaluation.violations.length === 0) {
          console.log(`[PASS: 0 violations, ${evaluation.elements.length} elements]`);
        } else {
          console.log(`[FAIL: ${evaluation.violations.length} violations]`);
          evaluation.violations.forEach((v: any) => {
            console.log(`      * [${v.violationType}] ${v.selector}: ${v.details}`);
          });
        }
      }

      auditResults.viewports.push(vpReport);
      await context.close();
    }

    auditResults.summary.passed = auditResults.summary.totalViolations === 0;

    // 1. Write layout-audit.json
    const jsonPath = path.join(DIST_REPORT_DIR, 'layout-audit.json');
    fs.writeFileSync(jsonPath, JSON.stringify(auditResults, null, 2), 'utf-8');
    console.log(`\n📄 Generated layout audit JSON: ${jsonPath}`);

    // 2. Compile HTML visual reporter index.html
    let templateHtml = '';
    if (fs.existsSync(TEMPLATE_PATH)) {
      templateHtml = fs.readFileSync(TEMPLATE_PATH, 'utf-8');
    } else {
      throw new Error(`Report template not found at ${TEMPLATE_PATH}`);
    }

    const compiledHtml = templateHtml.replace(
      '/* __AUDIT_DATA__ */ null',
      JSON.stringify(auditResults, null, 2)
    );

    const htmlPath = path.join(DIST_REPORT_DIR, 'index.html');
    fs.writeFileSync(htmlPath, compiledHtml, 'utf-8');
    console.log(`🎨 Generated interactive visual HTML report: ${htmlPath}`);

    console.log('\n====================================================');
    console.log(` Final Audit Status: ${auditResults.summary.passed ? 'PASSED ✅' : 'FAILED ❌'}`);
    console.log(` Total Violations: ${auditResults.summary.totalViolations}`);
    console.log(` Viewport Overflows: ${auditResults.summary.overflowViolations}`);
    console.log(` Container Clippings: ${auditResults.summary.clippingViolations}`);
    console.log(` Element Collisions: ${auditResults.summary.collisionViolations}`);
    console.log('====================================================\n');

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

// Direct execution entrypoint
if (process.argv[1] && (process.argv[1].endsWith('inspect_layout.ts') || process.argv[1].endsWith('inspect_layout.js'))) {
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
