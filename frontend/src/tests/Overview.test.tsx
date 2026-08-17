import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Overview from '../Overview';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Stats } from '../types';

const sampleStats: Stats = {
  repos_count: 3,
  symbols_count: 850,
  files_count: 24,
  points_count: 1400,
  last_indexed: '2026-08-17 01:23:45',
  dense_model: 'bge-small-en-v1.5 (384d)',
  sparse_model: 'Qdrant/bm25',
  top_keywords: ['fastapi', 'tree-sitter', 'qdrant'],
  is_indexing: false
};

describe('Overview Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state when stats is null', () => {
    render(
      <ToastProvider>
        <Overview stats={null} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders metrics, specs, and top keywords accurately', () => {
    render(
      <ToastProvider>
        <Overview stats={sampleStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Git Repositories')).toBeInTheDocument();
    expect(screen.getByText('850')).toBeInTheDocument();
    expect(screen.getByText('AST Code Symbols')).toBeInTheDocument();
    expect(screen.getByText('24')).toBeInTheDocument();
    expect(screen.getByText('Indexed Files')).toBeInTheDocument();
    expect(screen.getByText('1,400')).toBeInTheDocument();
    expect(screen.getByText(/QDRANT \(Embedded\) Vectors/i)).toBeInTheDocument();

    expect(screen.getByText('Vector Database:')).toBeInTheDocument();
    expect(screen.getByText(/Qdrant \(Embedded Disk\)/i)).toBeInTheDocument();
    expect(screen.getByText('bge-small-en-v1.5 (384d)')).toBeInTheDocument();
    expect(screen.getByText('Qdrant/bm25 (FastEmbed)')).toBeInTheDocument();
    expect(screen.getByText('2026-08-17 01:23:45')).toBeInTheDocument();

    expect(screen.getByText('fastapi')).toBeInTheDocument();
    expect(screen.getByText('tree-sitter')).toBeInTheDocument();
    expect(screen.getByText('qdrant')).toBeInTheDocument();
  });

  it('renders ChromaDB vector store specs correctly', () => {
    const chromaStats: Stats = {
      ...sampleStats,
      vector_store_provider: 'chroma',
      vector_store_mode: 'remote'
    };

    render(
      <ToastProvider>
        <Overview stats={chromaStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(screen.getByText(/CHROMA \(Remote\) Vectors/i)).toBeInTheDocument();
    expect(screen.getByText(/ChromaDB \(Remote Server\)/i)).toBeInTheDocument();
    expect(screen.getByText('Dense Vector Cosine Similarity')).toBeInTheDocument();
  });


  it('triggers reindex and calls refreshStats on success', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'started' })
    });

    render(
      <ToastProvider>
        <Overview stats={sampleStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const reindexBtn = screen.getByRole('button', { name: /Reindex All Sources/i });
    fireEvent.click(reindexBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/reindex', { method: 'POST' });
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText('Re-indexing triggered successfully')).toBeInTheDocument();
    });
  });

  it('handles reindex API error gracefully', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: 'Cluster busy' })
    });

    render(
      <ToastProvider>
        <Overview stats={sampleStats} refreshStats={refreshStats} />
      </ToastProvider>
    );

    const reindexBtn = screen.getByRole('button', { name: /Reindex All Sources/i });
    fireEvent.click(reindexBtn);

    await waitFor(() => {
      expect(screen.getByText(/Reindex error: Cluster busy/i)).toBeInTheDocument();
    });
  });

  it('renders system specs with responsive word wrapping and badge elements', () => {
    render(
      <ToastProvider>
        <Overview stats={sampleStats} refreshStats={vi.fn()} />
      </ToastProvider>
    );
    expect(screen.getByText('System & Embedding Specs')).toBeInTheDocument();
    expect(screen.getByText(/Dense \+ BM25 Reciprocal Rank Fusion/i)).toBeInTheDocument();
    const specRows = document.querySelectorAll('.spec-row');
    expect(specRows.length).toBeGreaterThan(0);
  });
});
