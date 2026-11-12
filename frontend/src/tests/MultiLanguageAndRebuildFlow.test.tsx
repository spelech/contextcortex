import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Settings from '../Settings';
import IngestionCatalogViewer from '../IngestionCatalogViewer';
import { ToastProvider } from '../ToastContext';
import { NavigatorOutline } from '../components/navigator/NavigatorOutline';
import { NavigatorInspector } from '../components/navigator/NavigatorInspector';
import { NavigatorCodeViewer } from '../components/navigator/NavigatorCodeViewer';
import { formatKind } from '../components/navigator/NavigatorOmniSearch';
import { cleanKind } from '../SearchInspector';
import { filterTopologyBundles } from '../components/topology/topologySelection';

describe('Multi-Language UI Semantics & Rebuild Confirmation Consistency', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it('prompts confirmation and retries with rebuild_index=true when POST /admin/api/settings/embedding returns 400', async () => {
    const refreshStats = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    let postCount = 0;
    const postBodies: any[] = [];

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/admin/api/settings/embedding' && init?.method === 'POST') {
        postCount += 1;
        const parsed = JSON.parse(String(init.body));
        postBodies.push(parsed);
        if (postCount === 1) {
          return Promise.resolve({
            ok: false,
            status: 400,
            json: async () => ({
              status: 'error',
              error: "Dimension mismatch: Explicit rebuild confirmation is required (set 'rebuild_index': true).",
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'success',
            config: { provider: 'api', dense_model: parsed.dense_model, threads: 4, batch_size: 64 },
          }),
        });
      }
      if (url === '/admin/api/settings/embedding') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            provider: 'api',
            dense_model: 'BAAI/bge-small-en-v1.5',
            sparse_model: 'Qdrant/bm25',
            threads: 4,
            batch_size: 64,
            litellm_url: 'http://litellm:4000/v1',
          }),
        });
      }
      if (url === '/admin/api/vector-store') {
        return Promise.resolve({ ok: true, json: async () => ({ provider: 'qdrant', mode: 'embedded' }) });
      }
      if (url === '/admin/api/settings/auto-sync') {
        return Promise.resolve({ ok: true, json: async () => ({ interval_mins: 15, has_global_secret: false }) });
      }
      if (url === '/admin/api/settings/hosts') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url === '/admin/api/settings/ai-gateway') {
        return Promise.resolve({ ok: true, json: async () => ({ url: 'http://litellm:4000/v1' }) });
      }
      if (url === '/admin/api/settings/files') {
        return Promise.resolve({ ok: true, json: async () => ({ summary_max_file_size_mb: 10, read_file_max_lines: 2000 }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(
      <ToastProvider>
        <Settings stats={null} refreshStats={refreshStats} initialCategory="embedding" />
      </ToastProvider>
    );

    const denseInput = await screen.findByLabelText(/Dense Embedding Model/i).catch(() =>
      document.getElementById('emb-dense-model') as HTMLInputElement
    );
    fireEvent.change(denseInput, { target: { value: 'text-embedding-3-large' } });

    const saveBtn = screen.getByRole('button', { name: /Save & Apply Embedding Limits & Model Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledTimes(1);
      expect(postBodies).toHaveLength(2);
    });

    expect(postBodies[0].rebuild_index).toBeUndefined();
    expect(postBodies[1].rebuild_index).toBe(true);
    expect(postBodies[1].dense_model).toBe('text-embedding-3-large');
    expect(refreshStats).toHaveBeenCalledTimes(1);
  });

  it('displays COBOL, C#, TSX, TypeScript, JavaScript, and Python badges in IngestionCatalogViewer detailed table', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        source_type: 'all',
        detail_level: 'detailed',
        git_repositories: [],
        monitored_paths: [],
        local_storage: null,
        files: [
          { filepath: 'src/PAYROLL.CBL', repo: 'core-cobol', doc_type: 'code', language: 'cobol', mtime: 1700000100 },
          { filepath: 'Domain/LedgerRecord.cs', repo: 'core-dotnet', doc_type: 'code', language: 'c_sharp', mtime: 1700000200 },
          { filepath: 'ui/Dashboard.tsx', repo: 'core-web', doc_type: 'code', language: 'tsx', mtime: 1700000300 },
          { filepath: 'ui/client.ts', repo: 'core-web', doc_type: 'code', language: 'typescript', mtime: 1700000400 },
          { filepath: 'scripts/worker.js', repo: 'core-web', doc_type: 'code', language: 'javascript', mtime: 1700000500 },
          { filepath: 'app/engine.py', repo: 'core-py', doc_type: 'code', language: 'python', mtime: 1700000600 },
        ],
      }),
    });

    render(
      <ToastProvider>
        <IngestionCatalogViewer />
      </ToastProvider>
    );

    fireEvent.click(await screen.findByRole('button', { name: /Detailed File Tree/i }));

    expect((await screen.findAllByText('COBOL')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('C#').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('TSX').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('TypeScript').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('JavaScript').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Python').length).toBeGreaterThanOrEqual(1);
  });

  it('classifies and formats COBOL and C# AST symbol kinds across NavigatorOutline, OmniSearch, Inspector, and CodeViewer', () => {
    render(
      <NavigatorOutline
        outline={{
          repo: 'enterprise-suite',
          filepath: 'PAYROLL.CBL',
          language: 'cobol',
          symbols: [
            { id: 1, name: 'PAYROLL-PGM', kind: 'program_definition', start_line: 1, end_line: 120 },
            { id: 2, name: 'EMP-RECORD', kind: 'record_definition', start_line: 15, end_line: 30 },
            { id: 3, name: 'CALC-SECTION', kind: 'section', start_line: 40, end_line: 90 },
            { id: 4, name: 'CALC-TAX-PARA', kind: 'paragraph', start_line: 50, end_line: 80 },
            { id: 5, name: 'OrderDto', kind: 'record_declaration', start_line: 95, end_line: 105 },
            { id: 6, name: 'OrderService', kind: 'constructor_declaration', start_line: 106, end_line: 118 },
          ],
        }}
        selectedSymbolId={1}
        onSelectSymbol={vi.fn()}
      />
    );

    expect(screen.getByTestId('outline-language-badge')).toHaveTextContent('COB');
    expect(screen.getByText('program')).toBeInTheDocument();
    expect(screen.getAllByText('record')).toHaveLength(2);
    expect(screen.getByText('section')).toBeInTheDocument();
    expect(screen.getByText('paragraph')).toBeInTheDocument();
    expect(screen.getByText('constructor')).toBeInTheDocument();

    // Classes chip includes program_definition + record_definition + record_declaration (3)
    fireEvent.click(screen.getByRole('button', { name: /Classes/i }));
    expect(screen.getByText('PAYROLL-PGM')).toBeInTheDocument();
    expect(screen.getByText('EMP-RECORD')).toBeInTheDocument();
    expect(screen.getByText('OrderDto')).toBeInTheDocument();
    expect(screen.queryByText('CALC-TAX-PARA')).not.toBeInTheDocument();

    // Functions chip includes section + paragraph + constructor_declaration (3)
    fireEvent.click(screen.getByRole('button', { name: /Functions/i }));
    expect(screen.getByText('CALC-SECTION')).toBeInTheDocument();
    expect(screen.getByText('CALC-TAX-PARA')).toBeInTheDocument();
    expect(screen.getByText('OrderService')).toBeInTheDocument();

    // OmniSearch & SearchInspector kind formatters
    expect(formatKind('constructor_declaration')).toBe('ctor');
    expect(formatKind('record_declaration')).toBe('record');
    expect(formatKind('program_definition')).toBe('program');
    expect(cleanKind('record_definition')).toBe('record');
    expect(cleanKind('paragraph')).toBe('paragraph');

    // Inspector & CodeViewer C# badge
    render(
      <NavigatorInspector
        impact={{
          symbol: {
            id: 99,
            name: 'InvoiceRecord',
            kind: 'record_declaration',
            filepath: 'Domain/InvoiceRecord.cs',
            start_line: 1,
            end_line: 12,
            language: 'c_sharp',
          },
          route: null,
          callers: [],
          callees: [],
          imports: [],
        }}
        onSelectCaller={vi.fn()}
      />
    );
    expect(screen.getByTestId('metric-scope')).toHaveTextContent('C#');

    render(
      <NavigatorCodeViewer
        filepath="src/PAYROLL.CBL"
        content={'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYROLL.'}
        totalLines={2}
        language="cobol"
      />
    );
    expect(screen.getByTestId('code-viewer-language-badge')).toHaveTextContent('COBOL');
  });

  it('filters compiled frontend/framework bundle artifacts from topology graph data', () => {
    const filtered = filterTopologyBundles({
      nodes: [
        { id: 'file:repo:app/main.py', name: 'main.py', type: 'file', repo: 'repo', filepath: 'app/main.py' },
        { id: 'file:repo:www/assets/index-9f2a.js', name: 'index-9f2a.js', type: 'file', repo: 'repo', filepath: 'www/assets/index-9f2a.js' },
        { id: 'file:repo:wwwroot/_framework/blazor.webassembly.js', name: 'blazor.webassembly.js', type: 'file', repo: 'repo', filepath: 'wwwroot/_framework/blazor.webassembly.js' },
      ],
      edges: [
        { source: 'file:repo:app/main.py', target: 'file:repo:www/assets/index-9f2a.js', type: 'IMPORTS' },
      ],
      stats: { node_count: 3, edge_count: 1 },
    });

    expect(filtered.nodes.map((n) => n.id)).toEqual(['file:repo:app/main.py']);
    expect(filtered.edges).toEqual([]);
    expect(filtered.stats).toEqual({ node_count: 1, edge_count: 0 });
  });
});
