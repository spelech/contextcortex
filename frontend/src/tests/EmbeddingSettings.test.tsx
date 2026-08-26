import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { EmbeddingSettings } from '../components/settings/EmbeddingSettings';
import type { EmbeddingConfig } from '../types';

const mockEmbeddingConfig: EmbeddingConfig = {
  provider: 'local',
  dense_model: 'BAAI/bge-small-en-v1.5',
  sparse_model: 'Qdrant/bm25',
  threads: 2,
  batch_size: 32,
  system_cpus: 12,
  system_memory_gb: 32.0,
  litellm_url: 'http://litellm:4000/v1'
};

describe('EmbeddingSettings Component', () => {
  it('renders loading state when embedding configuration is not yet loaded', () => {
    render(
      <EmbeddingSettings
        embeddingConfig={null}
        isLoadingEmb={true}
        isSavingEmb={false}
        embProvider="local"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="BAAI/bge-small-en-v1.5"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    expect(screen.getByText('Loading embedding configuration...')).toBeInTheDocument();
  });

  it('renders active status with hardware metrics and local model parameters', () => {
    render(
      <EmbeddingSettings
        embeddingConfig={mockEmbeddingConfig}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="local"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="BAAI/bge-small-en-v1.5"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    expect(screen.getByText('Local FastEmbed (ONNX)')).toBeInTheDocument();
    expect(screen.getByText(/2 Cores \(of 12 detected\)/i)).toBeInTheDocument();
    expect(screen.getByText('32 chunks/batch')).toBeInTheDocument();
    expect(screen.getByText('32 GB')).toBeInTheDocument();
    expect(screen.getByText('BAAI/bge-small-en-v1.5')).toBeInTheDocument();
    expect(screen.getByText('Qdrant/bm25')).toBeInTheDocument();
  });

  it('handles provider switch to API and updates form fields', () => {
    const setEmbProvider = vi.fn();
    const setEmbLitellmUrl = vi.fn();

    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="api"
        setEmbProvider={setEmbProvider}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="BAAI/bge-small-en-v1.5"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={setEmbLitellmUrl}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    expect(screen.getByText('Remote API (LiteLLM)')).toBeInTheDocument();
    expect(screen.getByLabelText(/API Endpoint URL/i)).toBeInTheDocument();

    const providerSelect = screen.getByLabelText(/Embedding Provider/i);
    fireEvent.change(providerSelect, { target: { value: 'local' } });
    expect(setEmbProvider).toHaveBeenCalledWith('local');
  });

  it('handles changes to CPU threads and batch size', () => {
    const setEmbThreads = vi.fn();
    const setEmbBatchSize = vi.fn();
    const onSave = vi.fn(e => e.preventDefault());

    render(
      <EmbeddingSettings
        embeddingConfig={mockEmbeddingConfig}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="local"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={setEmbThreads}
        embBatchSize={32}
        setEmbBatchSize={setEmbBatchSize}
        embDenseModel="BAAI/bge-small-en-v1.5"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        onSaveEmbeddingSettings={onSave}
      />
    );

    const threadInput = screen.getByLabelText(/CPU Thread Cap/i);
    fireEvent.change(threadInput, { target: { value: '4' } });
    expect(setEmbThreads).toHaveBeenCalledWith(4);

    const batchSelect = screen.getByLabelText(/Embedding Batch Size/i);
    fireEvent.change(batchSelect, { target: { value: '64' } });
    expect(setEmbBatchSize).toHaveBeenCalledWith(64);

    const saveBtn = screen.getByRole('button', { name: /Save & Apply Embedding Limits/i });
    fireEvent.click(saveBtn);
    expect(onSave).toHaveBeenCalled();
  });
});
