import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SearchInspector from '../SearchInspector';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SearchHit } from '../types';

const mockHits: SearchHit[] = [
  {
    score: 0.0325,
    payload: {
      repo: 'notes-rag-mcp',
      rel_path: 'app/services/indexer.py',
      symbol: 'IndexerService.sync',
      start_line: 45,
      end_line: 80,
      github_url: 'https://github.com/example/notes-rag-mcp/blob/main/app/services/indexer.py#L45-L80',
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
  });

  it('performs search and renders matching hit cards', async () => {
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
          body: JSON.stringify({ query: 'IndexerService', type: 'code', repo: null })
        })
      );
      expect(screen.getByText('notes-rag-mcp')).toBeInTheDocument();
      expect(screen.getByText('app/services/indexer.py')).toBeInTheDocument();
      expect(screen.getByText('IndexerService.sync')).toBeInTheDocument();
      expect(screen.getByText('RRF Score: 0.0325')).toBeInTheDocument();
      expect(screen.getByText(/async def sync/)).toBeInTheDocument();
      expect(screen.getByText('View on GitHub')).toBeInTheDocument();
    });
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
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'doc' } });
    fireEvent.change(screen.getByPlaceholderText(/All Repos/i), { target: { value: 'docs-vault' } });

    fireEvent.click(screen.getByRole('button', { name: /Search/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/search/test',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ query: 'system design', type: 'doc', repo: 'docs-vault' })
        })
      );
      expect(screen.getByText('docs-vault')).toBeInTheDocument();
      expect(screen.getByText('architecture.md')).toBeInTheDocument();
      expect(screen.getByText(/System Architecture/)).toBeInTheDocument();
    });
  });
});

