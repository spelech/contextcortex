import { chromium } from '@playwright/test';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import http from 'http';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '../..');

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

async function waitForServer(port) {
  for (let i = 0; i < 30; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(`http://localhost:${port}`, (res) => {
          resolve(res);
        });
        req.on('error', reject);
      });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  throw new Error(`Server on port ${port} did not start in time`);
}

async function main() {
  console.log('Starting Vite preview/dev server on port 5173...');
  const vite = spawn('npm', ['run', 'dev', '--', '--port', '5173'], {
    cwd: path.resolve(rootDir, 'frontend'),
    stdio: 'inherit',
  });

  await waitForServer(5173);
  console.log('Vite server ready!');

  console.log('Launching browser...');
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // Route mocks
  await page.route('**/admin/api/stats', (r) => r.fulfill({ status: 200, json: mockStats }));
  await page.route('**/admin/api/repositories', (r) => r.fulfill({ status: 200, json: mockRepos }));
  await page.route('**/admin/api/repos', (r) => r.fulfill({ status: 200, json: mockRepos }));
  await page.route('**/admin/api/navigator/tree*', (r) => r.fulfill({ status: 200, json: mockTreeData }));
  await page.route('**/admin/api/navigator/file-outline*', (r) => r.fulfill({ status: 200, json: mockOutlineChat }));
  await page.route('**/admin/api/navigator/symbol-impact*', (r) => r.fulfill({ status: 200, json: mockImpactChatCompletion }));

  console.log('Navigating to app...');
  await page.goto('http://localhost:5173');
  await page.waitForLoadState('networkidle');

  // Navigate to Code Navigator
  const navTab = page.locator('button.nav-tab', { hasText: 'Navigator' });
  await navTab.click();
  await page.waitForSelector('[data-testid="code-navigator-container"]');

  // Expand file tree
  const expandBtn = page.locator('button[aria-label="Expand All"]');
  await expandBtn.click();

  // Click chat.py
  const chatFile = page.locator('.nav-tree-item').filter({ has: page.locator('.tree-label:text-is("chat.py")') });
  await chatFile.click();

  // Wait for outline
  await page.waitForSelector('[data-testid="symbol-item-101"]');
  // Click chat_completion_endpoint
  await page.locator('[data-testid="symbol-item-101"]').click();

  // Wait for inspector
  await page.waitForSelector('[data-testid="navigator-inspector-container"]');
  await page.waitForTimeout(500);

  // Take full desktop screenshot
  const imgDir = path.resolve(rootDir, 'docs/images');
  if (!fs.existsSync(imgDir)) {
    fs.mkdirSync(imgDir, { recursive: true });
  }
  const assetDir = path.resolve(rootDir, 'docs/assets');
  if (!fs.existsSync(assetDir)) {
    fs.mkdirSync(assetDir, { recursive: true });
  }

  const screenshotPath1 = path.join(imgDir, 'codebase-navigator.png');
  const screenshotPath2 = path.join(assetDir, 'desktop_codebase-navigator.png');

  console.log(`Saving screenshot to ${screenshotPath1}...`);
  await page.screenshot({ path: screenshotPath1, fullPage: false });
  console.log(`Saving screenshot to ${screenshotPath2}...`);
  await page.screenshot({ path: screenshotPath2, fullPage: false });

  await browser.close();
  vite.kill('SIGINT');
  console.log('Done capturing screenshots!');
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
