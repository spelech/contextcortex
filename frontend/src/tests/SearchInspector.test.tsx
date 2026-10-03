import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SearchInspector from '../SearchInspector';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SearchHit } from '../types';

const mockHits: SearchHit[] = [
  {
    score: 0.825,
    dense_score: 0.880,
    sparse_score: 0.720,
    dense_rank: 1,
    sparse_rank: 2,
    payload: {
      repo: 'knowledge-rag-mcp',
      rel_path: 'app/services/indexer.py',
      symbol: 'IndexerService.sync',
      signature: 'async def sync(self) -> bool:',
      kind: 'method_declaration',
      ast_symbol_id: 101,
      start_line: 45,
      end_line: 80,
      github_url: 'https://github.com/example/knowledge-rag-mcp/blob/main/app/services/indexer.py#L45-L80',
      content: 'async def sync(self):\n    pass'
    }
  }
];

describe('SearchInspector Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders initial prompt and inputs', () => {
    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    expect(screen.getByText('Live Hybrid Search Inspector')).toBeInTheDocument();
    expect(screen.getByText('Enter a query above to test hybrid retrieval.')).toBeInTheDocument();
    expect(screen.getByTestId('mode-hybrid-btn')).toBeInTheDocument();
    expect(screen.getByTestId('mode-semantic-btn')).toBeInTheDocument();
    expect(screen.getByTestId('mode-lexical-btn')).toBeInTheDocument();
    expect(screen.getByLabelText('Hybrid dense weight slider')).toBeInTheDocument();
  });

  it('switches search mode and updates UI controls', () => {
    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    // Click Semantic
    fireEvent.click(screen.getByTestId('mode-semantic-btn'));
    expect(screen.queryByLabelText('Hybrid dense weight slider')).not.toBeInTheDocument();

    // Click Lexical
    fireEvent.click(screen.getByTestId('mode-lexical-btn'));
    expect(screen.queryByLabelText('Hybrid dense weight slider')).not.toBeInTheDocument();

    // Click Hybrid again
    fireEvent.click(screen.getByTestId('mode-hybrid-btn'));
    expect(screen.getByLabelText('Hybrid dense weight slider')).toBeInTheDocument();
  });

  it('adjusts hybrid split slider and presets', () => {
    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    const slider = screen.getByLabelText('Hybrid dense weight slider') as HTMLInputElement;
    expect(slider.value).toBe('0.5');

    // Click Semantic Bias preset
    fireEvent.click(screen.getByRole('button', { name: /Semantic Bias/i }));
    expect(slider.value).toBe('0.7');

    // Click Keyword Bias preset
    fireEvent.click(screen.getByRole('button', { name: /Keyword Bias/i }));
    expect(slider.value).toBe('0.3');

    // Click Balanced preset
    fireEvent.click(screen.getByRole('button', { name: /Balanced/i }));
    expect(slider.value).toBe('0.5');
  });

  it('performs search and renders matching hit cards with score breakdowns and signature', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: mockHits })
    });

    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    const queryInput = screen.getByPlaceholderText(/e.g. JWT token/i);
    fireEvent.change(queryInput, { target: { value: 'IndexerService' } });

    const searchBtn = screen.getByRole('button', { name: /Search/i });
    fireEvent.click(searchBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/search/test',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            query: 'IndexerService',
            type: 'code',
            repo: null,
            limit: 5,
            search_mode: 'hybrid',
            dense_weight: 0.5
          })
        })
      );
      expect(screen.getByText('knowledge-rag-mcp')).toBeInTheDocument();
      expect(screen.getByText('app/services/indexer.py')).toBeInTheDocument();
      expect(screen.getByText('IndexerService.sync')).toBeInTheDocument();
      expect(screen.getByText('Score: 82.5% (0.8250)')).toBeInTheDocument();
      expect(screen.getByText('Semantic: 88.0%')).toBeInTheDocument();
      expect(screen.getByText('Lexical: 72.0%')).toBeInTheDocument();
      expect(screen.getByText(/async def sync\(self\) -> bool:/)).toBeInTheDocument();
      expect(screen.getByText('View on GitHub')).toBeInTheDocument();
    });
  });

  it('invokes onOpenInNavigator when Open in Navigator button is clicked', async () => {
    const handleOpenInNavigator = vi.fn();
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: mockHits })
    });

    render(
      <ToastProvider>
        <SearchInspector onOpenInNavigator={handleOpenInNavigator} />
      </ToastProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/e.g. JWT token/i), { target: { value: 'IndexerService' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Open in Navigator/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Open in Navigator/i }));
    expect(handleOpenInNavigator).toHaveBeenCalledWith(
      'knowledge-rag-mcp',
      'app/services/indexer.py',
      101,
      45,
      80
    );
  });

  it('displays empty results message when no hits found', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: [] })
    });

    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    const queryInput = screen.getByPlaceholderText(/e.g. JWT token/i);
    fireEvent.change(queryInput, { target: { value: 'nonexistent-symbol' } });

    const searchBtn = screen.getByRole('button', { name: /Search/i });
    fireEvent.click(searchBtn);

    await waitFor(() => {
      expect(screen.getByText('No matching results found in index.')).toBeInTheDocument();
    });
  });

  it('handles search API failure with error display', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: 'Qdrant connection timed out' })
    });

    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    const queryInput = screen.getByPlaceholderText(/e.g. JWT token/i);
    fireEvent.change(queryInput, { target: { value: 'test' } });

    const searchBtn = screen.getByRole('button', { name: /Search/i });
    fireEvent.click(searchBtn);

    await waitFor(() => {
      expect(screen.getByText(/Search error: Qdrant connection timed out/i)).toBeInTheDocument();
    });
  });

  it('performs doc search with repo filter and renders documentation hits', async () => {
    const docHit: SearchHit = {
      score: 0.045,
      payload: {
        repo: 'docs-vault',
        rel_path: 'architecture.md',
        start_line: 1,
        end_line: 30,
        content: '# System Architecture\n\nHigh level design overview.'
      }
    };

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: [docHit] })
    });

    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/e.g. JWT token/i), { target: { value: 'system design' } });
    fireEvent.change(screen.getByRole('combobox', { name: /Target Type/i }), { target: { value: 'doc' } });
    fireEvent.change(screen.getByPlaceholderText(/All Repos/i), { target: { value: 'docs-vault' } });

    fireEvent.click(screen.getByRole('button', { name: /Search/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/search/test',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            query: 'system design',
            type: 'doc',
            repo: 'docs-vault',
            limit: 5,
            search_mode: 'hybrid',
            dense_weight: 0.5
          })
        })
      );
      expect(screen.getByText('docs-vault')).toBeInTheDocument();
      expect(screen.getByText('architecture.md')).toBeInTheDocument();
      expect(screen.getByText(/System Architecture/)).toBeInTheDocument();
    });
  });

  it('copies code snippet when Copy button is clicked', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock
      }
    });

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ results: mockHits })
    });

    render(
      <ToastProvider>
        <SearchInspector />
      </ToastProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/e.g. JWT token/i), { target: { value: 'IndexerService' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Copy/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Copy/i }));
    expect(writeTextMock).toHaveBeenCalledWith('async def sync(self):\n    pass');
    await waitFor(() => {
      expect(screen.getByText('Copied')).toBeInTheDocument();
    });
  });
});
