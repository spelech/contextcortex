import type { FormEvent } from 'react';
import type { EmbeddingConfig } from '../../types';

interface EmbeddingSettingsProps {
  embeddingConfig: EmbeddingConfig | null;
  isLoadingEmb: boolean;
  isSavingEmb: boolean;
  embProvider: 'local' | 'api';
  setEmbProvider: (val: 'local' | 'api') => void;
  embThreads: number;
  setEmbThreads: (val: number) => void;
  embBatchSize: number;
  setEmbBatchSize: (val: number) => void;
  embDenseModel: string;
  setEmbDenseModel: (val: string) => void;
  embSparseModel: string;
  setEmbSparseModel: (val: string) => void;
  embLitellmUrl: string;
  setEmbLitellmUrl: (val: string) => void;
  onSaveEmbeddingSettings: (e: FormEvent) => void;
}

export function EmbeddingSettings({
  embeddingConfig,
  isLoadingEmb,
  isSavingEmb,
  embProvider,
  setEmbProvider,
  embThreads,
  setEmbThreads,
  embBatchSize,
  setEmbBatchSize,
  embDenseModel,
  setEmbDenseModel,
  embSparseModel,
  setEmbSparseModel,
  embLitellmUrl,
  setEmbLitellmUrl,
  onSaveEmbeddingSettings,
}: EmbeddingSettingsProps) {
  const systemCpus = embeddingConfig?.system_cpus || 2;
  const systemMemoryGb = embeddingConfig?.system_memory_gb || 4.0;

  return (
    <div className="glass-card">
      <h2><i className="fa-solid fa-microchip"></i> Embedding Engine &amp; Resource Limits</h2>
      <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
        Configure local FastEmbed (ONNX) resource limits, CPU thread concurrency, batch sizes, or remote API endpoints. Safe defaults limit CPU usage to prevent host exhaustion.
      </p>

      <div className="vs-config-layout">
        {/* Active Embedding Status Box */}
        <div className="vs-box">
          <h3><i className="fa-solid fa-gauge-high"></i> Active Embedding Engine</h3>
          {isLoadingEmb && !embeddingConfig ? (
            <p className="text-muted">Loading embedding configuration...</p>
          ) : embeddingConfig ? (
            <div className="specs-list" style={{ marginTop: 0 }}>
              <div className="spec-row">
                <span>Execution Provider:</span>
                <span className="badge badge-accent">
                  {embeddingConfig.provider === 'api' ? 'Remote API (LiteLLM)' : 'Local FastEmbed (ONNX)'}
                </span>
              </div>
              <div className="spec-row">
                <span>CPU Threads Allocation:</span>
                <span className="badge badge-primary">
                  {embeddingConfig.threads} {embeddingConfig.threads === 1 ? 'Core' : 'Cores'} (of {systemCpus} detected)
                </span>
              </div>
              <div className="spec-row">
                <span>Batch Processing Size:</span>
                <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                  {embeddingConfig.batch_size} chunks/batch
                </span>
              </div>
              <div className="spec-row">
                <span>System RAM Capacity:</span>
                <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                  {systemMemoryGb} GB
                </span>
              </div>
              <div className="spec-row">
                <span>Dense Model:</span>
                <code>{embeddingConfig.dense_model || 'BAAI/bge-small-en-v1.5'}</code>
              </div>
              <div className="spec-row">
                <span>Sparse Model (BM25):</span>
                <code>{embeddingConfig.sparse_model || 'Qdrant/bm25'}</code>
              </div>
              {embeddingConfig.provider === 'api' && (
                <div className="spec-row">
                  <span>API Endpoint URL:</span>
                  <code>{embeddingConfig.litellm_url || 'http://litellm:4000/v1'}</code>
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted">No embedding configuration found.</p>
          )}
        </div>

        {/* Configure Resource Limits Box */}
        <div className="vs-box">
          <h3><i className="fa-solid fa-sliders"></i> Configure Resource Limits</h3>

          <form onSubmit={onSaveEmbeddingSettings}>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="emb-provider">Embedding Provider</label>
                <select
                  id="emb-provider"
                  value={embProvider}
                  onChange={e => setEmbProvider(e.target.value as 'local' | 'api')}
                >
                  <option value="local">Local Model (FastEmbed / ONNX Runtime)</option>
                  <option value="api">API Endpoint (LiteLLM / OpenAI Compatible)</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="emb-threads">CPU Thread Cap</label>
                <input
                  id="emb-threads"
                  type="number"
                  min="1"
                  max={Math.max(systemCpus, 128)}
                  value={embThreads}
                  onChange={e => setEmbThreads(Math.max(1, parseInt(e.target.value) || 1))}
                  placeholder="2"
                />
                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '2px', display: 'block' }}>
                  Recommended: 2 cores. Prevents container CPU spikes.
                </span>
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label htmlFor="emb-batch-size">Embedding Batch Size</label>
                <select
                  id="emb-batch-size"
                  value={embBatchSize}
                  onChange={e => setEmbBatchSize(parseInt(e.target.value) || 32)}
                >
                  <option value="16">16 chunks (Lowest RAM footprint)</option>
                  <option value="32">32 chunks (Balanced Default)</option>
                  <option value="64">64 chunks (High throughput)</option>
                  <option value="128">128 chunks (Large RAM environments)</option>
                  <option value="256">256 chunks (FastEmbed default)</option>
                </select>
              </div>

              {embProvider === 'api' ? (
                <div className="form-group">
                  <label htmlFor="emb-litellm-url">API Endpoint URL</label>
                  <input
                    id="emb-litellm-url"
                    type="text"
                    value={embLitellmUrl}
                    onChange={e => setEmbLitellmUrl(e.target.value)}
                    placeholder="http://litellm:4000/v1"
                  />
                </div>
              ) : (
                <div className="form-group">
                  <label htmlFor="emb-dense-model">Dense Model Name</label>
                  <input
                    id="emb-dense-model"
                    type="text"
                    value={embDenseModel}
                    onChange={e => setEmbDenseModel(e.target.value)}
                    placeholder="BAAI/bge-small-en-v1.5"
                  />
                </div>
              )}
            </div>

            {embProvider === 'local' && (
              <div className="form-group">
                <label htmlFor="emb-sparse-model">Sparse BM25 Model</label>
                <input
                  id="emb-sparse-model"
                  type="text"
                  value={embSparseModel}
                  onChange={e => setEmbSparseModel(e.target.value)}
                  placeholder="Qdrant/bm25"
                />
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isSavingEmb || isLoadingEmb}
              >
                {isSavingEmb ? (
                  <><i className="fa-solid fa-spinner fa-spin"></i> Saving &amp; Applying...</>
                ) : (
                  <><i className="fa-solid fa-floppy-disk"></i> Save &amp; Apply Embedding Limits</>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
