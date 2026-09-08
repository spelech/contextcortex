import { useState, type FormEvent } from 'react';
import type { EmbeddingConfig, ModelDiscoveryResult } from '../../types';

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
  embLitellmApiKey?: string;
  setEmbLitellmApiKey?: (val: string) => void;
  embVisionOcrModel?: string;
  setEmbVisionOcrModel?: (val: string) => void;
  embChatModel?: string;
  setEmbChatModel?: (val: string) => void;
  discoveryResult?: ModelDiscoveryResult | null;
  isDiscovering?: boolean;
  onDiscoverModels?: () => void;
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
  embLitellmApiKey = '',
  setEmbLitellmApiKey,
  embVisionOcrModel = 'gemini-2.5-flash',
  setEmbVisionOcrModel,
  embChatModel = 'gemini-2.5-flash',
  setEmbChatModel,
  discoveryResult = null,
  isDiscovering = false,
  onDiscoverModels,
  onSaveEmbeddingSettings,
}: EmbeddingSettingsProps) {
  const systemCpus = embeddingConfig?.system_cpus || 2;
  const systemMemoryGb = embeddingConfig?.system_memory_gb || 4.0;

  // Custom model text input toggles
  const [customDense, setCustomDense] = useState(false);
  const [customVision, setCustomVision] = useState(false);
  const [customChat, setCustomChat] = useState(false);

  const embeddingModels = discoveryResult?.embedding_models || [];
  const visionModels = discoveryResult?.vision_models || [];
  const chatModels = discoveryResult?.chat_models || [];

  return (
    <div className="glass-card">
      <h2><i className="fa-solid fa-microchip"></i> Embedding Engine &amp; Resource Limits</h2>
      <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
        Configure local FastEmbed (ONNX) resource limits, CPU thread concurrency, or remote LiteLLM endpoints with dynamic model discovery for embeddings, Vision AI OCR, and chat synthesis.
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
              <div className="spec-row">
                <span>Vision AI OCR Model:</span>
                <code>{embeddingConfig.vision_ocr_model || 'gemini-2.5-flash'}</code>
              </div>
              <div className="spec-row">
                <span>Chat Completion Model:</span>
                <code>{embeddingConfig.chat_model || 'gemini-2.5-flash'}</code>
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
          <h3><i className="fa-solid fa-sliders"></i> Configure Models &amp; Resources</h3>

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
                  <label htmlFor="emb-litellm-url">API Endpoint URL (LiteLLM)</label>
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

            {/* LiteLLM Specific Connection & Discovery Controls */}
            {embProvider === 'api' && (
              <>
                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="emb-litellm-api-key">LiteLLM API Key (Optional / Bearer)</label>
                    <input
                      id="emb-litellm-api-key"
                      type="password"
                      value={embLitellmApiKey}
                      onChange={e => setEmbLitellmApiKey?.(e.target.value)}
                      placeholder="sk-..."
                      autoComplete="off"
                    />
                  </div>

                  <div className="form-group" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      id="btn-discover-models"
                      className="btn btn-secondary"
                      onClick={onDiscoverModels}
                      disabled={isDiscovering}
                      style={{ height: '38px', whiteSpace: 'nowrap' }}
                    >
                      {isDiscovering ? (
                        <><i className="fa-solid fa-spinner fa-spin"></i> Discovering...</>
                      ) : (
                        <><i className="fa-solid fa-bolt"></i> Discover Models</>
                      )}
                    </button>
                  </div>
                </div>

                {/* Discovery Feedback Banner / Status */}
                {discoveryResult && (
                  <div style={{ marginBottom: '16px' }}>
                    {discoveryResult.status === 'success' ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '6px', fontSize: '0.85rem' }}>
                        <i className="fa-solid fa-circle-check" style={{ color: '#10b981' }}></i>
                        <span>
                          Connected to LiteLLM &mdash; <strong>{discoveryResult.total_models} models available</strong> ({embeddingModels.length} embedding, {visionModels.length} vision, {chatModels.length} chat)
                        </span>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '6px', fontSize: '0.85rem' }}>
                        <i className="fa-solid fa-triangle-exclamation" style={{ color: '#ef4444' }}></i>
                        <span>{discoveryResult.message || 'Could not connect to LiteLLM endpoint'}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Dense Model Selection with Discovery Dropdown */}
                <div className="form-group">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <label htmlFor="emb-dense-model" style={{ marginBottom: 0 }}>Dense Embedding Model</label>
                    {embeddingModels.length > 0 && (
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setCustomDense(!customDense)}
                        style={{ fontSize: '0.75rem', background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', padding: 0 }}
                      >
                        {customDense ? '← Select from discovered' : 'Enter custom model →'}
                      </button>
                    )}
                  </div>

                  {!customDense && embeddingModels.length > 0 ? (
                    <select
                      id="emb-dense-model"
                      value={embDenseModel}
                      onChange={e => {
                        if (e.target.value === '__custom__') {
                          setCustomDense(true);
                        } else {
                          setEmbDenseModel(e.target.value);
                        }
                      }}
                    >
                      {embeddingModels.map(m => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                      <option value="__custom__">Custom / Enter manually...</option>
                    </select>
                  ) : (
                    <input
                      id="emb-dense-model"
                      type="text"
                      value={embDenseModel}
                      onChange={e => setEmbDenseModel(e.target.value)}
                      placeholder="gemini-embedding-2"
                    />
                  )}
                </div>
              </>
            )}

            {/* Local Sparse BM25 Model */}
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

            {/* Vision AI OCR Model Selection */}
            <div className="form-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <label htmlFor="emb-vision-ocr-model" style={{ marginBottom: 0 }}>
                  Vision AI OCR Model <span className="text-muted" style={{ fontWeight: 400, fontSize: '0.8rem' }}>(PDF Ingestion Fallback)</span>
                </label>
                {visionModels.length > 0 && (
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setCustomVision(!customVision)}
                    style={{ fontSize: '0.75rem', background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', padding: 0 }}
                  >
                    {customVision ? '← Select from discovered' : 'Enter custom model →'}
                  </button>
                )}
              </div>

              {!customVision && visionModels.length > 0 ? (
                <select
                  id="emb-vision-ocr-model"
                  value={embVisionOcrModel}
                  onChange={e => {
                    if (e.target.value === '__custom__') {
                      setCustomVision(true);
                    } else {
                      setEmbVisionOcrModel?.(e.target.value);
                    }
                  }}
                >
                  {visionModels.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  <option value="__custom__">Custom / Enter manually...</option>
                </select>
              ) : (
                <input
                  id="emb-vision-ocr-model"
                  type="text"
                  value={embVisionOcrModel}
                  onChange={e => setEmbVisionOcrModel?.(e.target.value)}
                  placeholder="gemini-2.5-flash"
                />
              )}
            </div>

            {/* General Chat / Completion Model Selection */}
            <div className="form-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <label htmlFor="emb-chat-model" style={{ marginBottom: 0 }}>
                  General Chat &amp; Synthesis Model
                </label>
                {chatModels.length > 0 && (
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setCustomChat(!customChat)}
                    style={{ fontSize: '0.75rem', background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', padding: 0 }}
                  >
                    {customChat ? '← Select from discovered' : 'Enter custom model →'}
                  </button>
                )}
              </div>

              {!customChat && chatModels.length > 0 ? (
                <select
                  id="emb-chat-model"
                  value={embChatModel}
                  onChange={e => {
                    if (e.target.value === '__custom__') {
                      setCustomChat(true);
                    } else {
                      setEmbChatModel?.(e.target.value);
                    }
                  }}
                >
                  {chatModels.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  <option value="__custom__">Custom / Enter manually...</option>
                </select>
              ) : (
                <input
                  id="emb-chat-model"
                  type="text"
                  value={embChatModel}
                  onChange={e => setEmbChatModel?.(e.target.value)}
                  placeholder="gemini-2.5-flash"
                />
              )}
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isSavingEmb || isLoadingEmb}
              >
                {isSavingEmb ? (
                  <><i className="fa-solid fa-spinner fa-spin"></i> Saving &amp; Applying...</>
                ) : (
                  <><i className="fa-solid fa-floppy-disk"></i> Save &amp; Apply Embedding Limits &amp; Model Settings</>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
