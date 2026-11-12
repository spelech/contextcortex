import type { Page } from '@playwright/test';

export const mockNavigatorStats = {
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

export const mockNavigatorRepos = [
  { id: 1, name: 'contextcortex-core' },
  { id: 2, name: 'contextcortex-web' },
];

export const mockTreePayload = {
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

export const mockOutlineChat = {
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
      route: { http_method: 'POST', path_pattern: '/v1/chat/completions', framework: 'FastAPI' },
    },
    {
      id: 102,
      name: 'stream_chat_endpoint',
      full_symbol: 'app.api.routers.chat.stream_chat_endpoint',
      kind: 'function',
      start_line: 90,
      end_line: 130,
      signature: 'async def stream_chat_endpoint(request: ChatCompletionRequest):',
      route: { http_method: 'POST', path_pattern: '/v1/chat/stream', framework: 'FastAPI' },
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

export const mockOutlineTestChat = {
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

export const mockImpactChatCompletion = {
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
  route: { http_method: 'POST', path_pattern: '/v1/chat/completions', framework: 'FastAPI' },
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
  imports: [{ id: 701, target_symbol: 'vector_store', relationship_type: 'IMPORTS', line_number: 8 }],
};

export const mockImpactTestChat = {
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
  imports: [{ id: 702, target_symbol: 'pytest', relationship_type: 'IMPORTS', line_number: 2 }],
};

export async function setupNavigatorMocks(page: Page): Promise<void> {
  const jsonReply = (payload: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });

  await page.route('**/admin/api/stats', (route) => route.fulfill(jsonReply(mockNavigatorStats)));
  await page.route('**/admin/api/repositories', (route) => route.fulfill(jsonReply(mockNavigatorRepos)));
  await page.route('**/admin/api/repos', (route) => route.fulfill(jsonReply(mockNavigatorRepos)));
  await page.route('**/admin/api/navigator/tree*', (route) => route.fulfill(jsonReply(mockTreePayload)));

  await page.route('**/admin/api/navigator/file-outline*', async (route) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('README.md')) {
      await route.fulfill(jsonReply({ repo: '__all__', filepath: 'README.md', language: 'markdown', symbols: [] }));
    } else if (url.includes('tests/e2e/test_chat.py')) {
      await route.fulfill(jsonReply(mockOutlineTestChat));
    } else {
      await route.fulfill(jsonReply(mockOutlineChat));
    }
  });

  await page.route('**/admin/api/navigator/omni-search*', async (route) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('chat_completion')) {
      await route.fulfill(
        jsonReply({
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
        })
      );
    } else {
      await route.fulfill(jsonReply({ query: '', repo: '__all__', total_matches: 0, matches: [] }));
    }
  });

  await page.route('**/admin/api/files/read*', async (route) => {
    const url = decodeURIComponent(route.request().url());
    if (url.includes('chat.py')) {
      const codeLines = Array.from({ length: 90 }, (_, i) => {
        const lineNum = i + 1;
        if (lineNum === 45) return 'async def chat_completion_endpoint(request: ChatCompletionRequest):';
        if (lineNum === 46) return '    return {"status": "ok"}';
        return `# Line ${lineNum} sample source code`;
      }).join('\n');

      await route.fulfill(
        jsonReply({ filepath: 'app/api/routers/chat.py', content: codeLines, total_lines: 90, language: 'python' })
      );
    } else {
      await route.fulfill(
        jsonReply({
          filepath: 'README.md',
          content:
            '# ContextCortex Documentation\n\nFull documentation reader is active.\n\n## Features\n\n- Hybrid Vector and Lexical Search\n- Interactive AST Symbol Navigator\n- Markdown and Source Code Viewer',
          total_lines: 8,
          language: 'markdown',
        })
      );
    }
  });

  await page.route('**/admin/api/navigator/symbol-impact*', async (route) => {
    const url = decodeURIComponent(route.request().url());
    await route.fulfill(jsonReply(url.includes('symbol_id=301') ? mockImpactTestChat : mockImpactChatCompletion));
  });
}

export async function navigateToNavigator(page: Page): Promise<void> {
  const menuToggle = page.locator('button.menu-toggle-btn');
  if (await menuToggle.isVisible()) {
    const isDrawerOpen = await page.locator('.dashboard-nav.drawer-open').isVisible();
    if (!isDrawerOpen) {
      await menuToggle.click();
    }
  }
  await page.locator('button.nav-tab', { hasText: 'Navigator' }).click();
}
