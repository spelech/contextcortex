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

  it('renders model discovery controls and triggers onDiscoverModels when button clicked', () => {
    const onDiscover = vi.fn();
    const setApiKey = vi.fn();

    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="api"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="gemini-embedding-2"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        embLitellmApiKey="sk-secret"
        setEmbLitellmApiKey={setApiKey}
        onDiscoverModels={onDiscover}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    const apiKeyInput = screen.getByLabelText(/LiteLLM API Key/i);
    expect(apiKeyInput).toBeInTheDocument();
    fireEvent.change(apiKeyInput, { target: { value: 'sk-new-key' } });
    expect(setApiKey).toHaveBeenCalledWith('sk-new-key');

    const discoverBtn = screen.getByRole('button', { name: /Discover Models/i });
    fireEvent.click(discoverBtn);
    expect(onDiscover).toHaveBeenCalled();
  });

  it('renders discovered model dropdowns and allows selecting models', () => {
    const setDense = vi.fn();
    const setVision = vi.fn();
    const setChat = vi.fn();

    const mockDiscovery = {
      status: 'success' as const,
      total_models: 4,
      models: [
        { id: 'gemini-embedding-2', mode: 'embedding' },
        { id: 'text-embedding-3-small', mode: 'embedding' },
        { id: 'gemini-2.5-flash', mode: 'chat' },
        { id: 'qwen3-vl-32b-instruct', mode: 'chat' }
      ],
      embedding_models: ['gemini-embedding-2', 'text-embedding-3-small'],
      vision_models: ['gemini-2.5-flash', 'qwen3-vl-32b-instruct'],
      chat_models: ['gemini-2.5-flash', 'qwen3-vl-32b-instruct']
    };

    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="api"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="gemini-embedding-2"
        setEmbDenseModel={setDense}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        embVisionOcrModel="gemini-2.5-flash"
        setEmbVisionOcrModel={setVision}
        embChatModel="gemini-2.5-flash"
        setEmbChatModel={setChat}
        discoveryResult={mockDiscovery}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    expect(screen.getByText(/4 models available/i)).toBeInTheDocument();

    const denseSelect = screen.getByLabelText(/^Dense Embedding Model/i);
    fireEvent.change(denseSelect, { target: { value: 'text-embedding-3-small' } });
    expect(setDense).toHaveBeenCalledWith('text-embedding-3-small');

    const visionSelect = screen.getByLabelText(/Vision AI OCR Model/i);
    fireEvent.change(visionSelect, { target: { value: 'qwen3-vl-32b-instruct' } });
    expect(setVision).toHaveBeenCalledWith('qwen3-vl-32b-instruct');

    const chatSelect = screen.getByLabelText(/General Chat & Synthesis Model/i);
    fireEvent.change(chatSelect, { target: { value: 'qwen3-vl-32b-instruct' } });
    expect(setChat).toHaveBeenCalledWith('qwen3-vl-32b-instruct');
  });

  it('displays discovery error banner when LiteLLM is unreachable', () => {
    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="api"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="BAAI/bge-small-en-v1.5"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://invalid:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        discoveryResult={{
          status: 'error',
          total_models: 0,
          models: [],
          embedding_models: [],
          vision_models: [],
          chat_models: [],
          message: 'Connection to http://invalid:4000/v1 timed out'
        }}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    expect(screen.getByText(/Connection to http:\/\/invalid:4000\/v1 timed out/i)).toBeInTheDocument();
  });

  it('switches to manual input when Custom is selected from dropdown or link clicked', () => {
    const setDense = vi.fn();
    const mockDiscovery = {
      status: 'success' as const,
      total_models: 2,
      models: [
        { id: 'gemini-embedding-2', mode: 'embedding' },
        { id: 'text-embedding-3-small', mode: 'embedding' }
      ],
      embedding_models: ['gemini-embedding-2', 'text-embedding-3-small'],
      vision_models: [],
      chat_models: []
    };

    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        embProvider="api"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="gemini-embedding-2"
        setEmbDenseModel={setDense}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        discoveryResult={mockDiscovery}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    // Click "Enter custom model →" button
    const customToggleBtn = screen.getByRole('button', { name: /Enter custom model/i });
    expect(customToggleBtn).toBeInTheDocument();
    fireEvent.click(customToggleBtn);

    // Should now be a text input instead of select
    const manualInput = screen.getByPlaceholderText('gemini-embedding-2');
    expect(manualInput.tagName.toLowerCase()).toBe('input');
    fireEvent.change(manualInput, { target: { value: 'my-custom-model-id' } });
    expect(setDense).toHaveBeenCalledWith('my-custom-model-id');
  });

  it('disables discover button and shows spinner while isDiscovering is true', () => {
    render(
      <EmbeddingSettings
        embeddingConfig={{ ...mockEmbeddingConfig, provider: 'api' }}
        isLoadingEmb={false}
        isSavingEmb={false}
        isDiscovering={true}
        embProvider="api"
        setEmbProvider={vi.fn()}
        embThreads={2}
        setEmbThreads={vi.fn()}
        embBatchSize={32}
        setEmbBatchSize={vi.fn()}
        embDenseModel="gemini-embedding-2"
        setEmbDenseModel={vi.fn()}
        embSparseModel="Qdrant/bm25"
        setEmbSparseModel={vi.fn()}
        embLitellmUrl="http://litellm:4000/v1"
        setEmbLitellmUrl={vi.fn()}
        onSaveEmbeddingSettings={vi.fn()}
      />
    );

    const discoverBtn = screen.getByRole('button', { name: /Discovering\.\.\./i });
    expect(discoverBtn).toBeDisabled();
    expect(screen.getByText(/Discovering\.\.\./i)).toBeInTheDocument();
  });
});

