import { useState, useEffect } from 'react';
import type { FormEvent } from 'react';
import type { ModelDiscoveryResult } from '../../types';
import { useToast } from '../../ToastContext';

export interface AIGatewayConfig {
  url: string;
  has_api_key: boolean;
  masked_api_key: string;
  chat_model: string;
  vision_ocr_model: string;
  embedding_model: string;
}

export interface AIGatewaySettingsProps {
  config: AIGatewayConfig | null;
  isLoading: boolean;
  isSaving: boolean;
  onSave: (payload: {
    url?: string;
    api_key?: string;
    chat_model?: string;
    vision_ocr_model?: string;
    embedding_model?: string;
  }) => Promise<void>;
  onTestConnection?: (url: string, apiKey?: string) => Promise<ModelDiscoveryResult | null>;
}

export function AIGatewaySettings({
  config,
  isLoading,
  isSaving,
  onSave,
  onTestConnection,
}: AIGatewaySettingsProps) {
  const toast = useToast();

  const [url, setUrl] = useState(config?.url || 'http://litellm:4000/v1');
  const [apiKey, setApiKey] = useState('');
  const [isChangingKey, setIsChangingKey] = useState(false);
  const [showKeyText, setShowKeyText] = useState(false);

  const [chatModel, setChatModel] = useState(config?.chat_model || 'gemini-2.5-flash');
  const [visionModel, setVisionModel] = useState(config?.vision_ocr_model || 'gemini-2.5-flash');
  const [embeddingModel, setEmbeddingModel] = useState(config?.embedding_model || 'BAAI/bge-small-en-v1.5');

  const [customChat, setCustomChat] = useState(false);
  const [customVision, setCustomVision] = useState(false);
  const [customEmbedding, setCustomEmbedding] = useState(false);

  // Model discovery state
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveryResult, setDiscoveryResult] = useState<ModelDiscoveryResult | null>(null);

  useEffect(() => {
    if (config) {
      setUrl(config.url);
      setChatModel(config.chat_model);
      setVisionModel(config.vision_ocr_model);
      setEmbeddingModel(config.embedding_model);
    }
  }, [config]);

  const handleDiscover = async () => {
    setIsDiscovering(true);
    try {
      if (onTestConnection) {
        const res = await onTestConnection(url, isChangingKey ? apiKey : undefined);
        setDiscoveryResult(res);
      } else {
        const params = new URLSearchParams();
        if (url) params.set('url', url);
        if (isChangingKey && apiKey.trim()) params.set('api_key', apiKey.trim());
        const res = await fetch(`/admin/api/models/discover?${params.toString()}`);
        const data: ModelDiscoveryResult = await res.json();
        setDiscoveryResult(data);
        if (data.status === 'success') {
          toast.success(`Connected to gateway: ${data.total_models} models available`);
        } else {
          toast.error(data.message || 'Failed to connect to gateway');
        }
      }
    } catch (e: any) {
      toast.error('Discovery error: ' + e.message);
      setDiscoveryResult({
        status: 'error',
        total_models: 0,
        models: [],
        embedding_models: [],
        vision_models: [],
        chat_models: [],
        message: e.message,
      });
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await onSave({
        url: url.trim(),
        api_key: isChangingKey ? apiKey.trim() : undefined,
        chat_model: chatModel.trim(),
        vision_ocr_model: visionModel.trim(),
        embedding_model: embeddingModel.trim(),
      });
      setIsChangingKey(false);
      setApiKey('');
    } catch (err: any) {
      toast.error('Save failed: ' + err.message);
    }
  };

  const handleClearKey = async () => {
    if (!window.confirm('Clear stored API key from database?')) return;
    try {
      await onSave({ api_key: '' });
      setIsChangingKey(false);
      setApiKey('');
      toast.success('API key cleared');
    } catch (err: any) {
      toast.error('Failed to clear key: ' + err.message);
    }
  };

  const normalizeModelList = (list?: any[]): string[] => {
    if (!Array.isArray(list)) return [];
    return list.map((m) => (typeof m === 'string' ? m : (m?.id || m?.name || ''))).filter(Boolean);
  };

  const chatOptions = normalizeModelList(discoveryResult?.chat_models);
  const visionOptions = normalizeModelList(discoveryResult?.vision_models);
  const embOptions = normalizeModelList(discoveryResult?.embedding_models);

  return (
    <div className="glass-card" data-testid="ai-gateway-settings-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <h2>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: '8px', verticalAlign: 'middle' }}>
            <rect x="3" y="11" width="18" height="10" rx="2" />
            <circle cx="12" cy="5" r="2" />
            <path d="M12 7v4" />
            <line x1="8" y1="16" x2="8.01" y2="16" />
            <line x1="16" y1="16" x2="16.01" y2="16" />
          </svg>
          AI &amp; Model Gateway (OpenAI-Compatible)
        </h2>
      </div>

      <p className="text-muted" style={{ fontSize: '0.85rem', marginBottom: '18px' }}>
        Connect universal OpenAI-compatible LLM gateways such as <strong>LiteLLM</strong>, <strong>Ollama</strong>, <strong>vLLM</strong>, <strong>LocalAI</strong>, <strong>OpenAI</strong>, or <strong>OpenRouter</strong>. Settings are managed directly from the UI and persisted to the database.
      </p>

      {isLoading ? (
        <p className="text-muted">Loading gateway configuration...</p>
      ) : (
        <form onSubmit={handleSubmit}>
          <div className="form-group" style={{ marginBottom: '16px' }}>
            <label htmlFor="ai-gateway-url" style={{ fontWeight: 600 }}>API Endpoint URL</label>
            <input
              id="ai-gateway-url"
              type="text"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://litellm:4000/v1"
            />
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>
              Base OpenAI-compatible API endpoint root (including /v1).
            </span>
          </div>

          <div className="form-group" style={{ marginBottom: '16px' }}>
            <label htmlFor="ai-gateway-key" style={{ fontWeight: 600 }}>API Key / Bearer Token</label>
            {config?.has_api_key && !isChangingKey ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ flex: 1, padding: '8px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-card)', borderRadius: '6px', fontFamily: 'var(--font-mono)' }}>
                  <span>{config.masked_api_key || '••••••••'}</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setIsChangingKey(true)}
                  style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                >
                  Change Key
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleClearKey}
                  style={{ fontSize: '0.82rem', padding: '6px 12px', color: 'var(--danger)' }}
                >
                  Clear Key
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '8px' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <input
                    id="ai-gateway-key"
                    type={showKeyText ? 'text' : 'password'}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="Enter API key (e.g. sk-...)"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKeyText(!showKeyText)}
                    style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                    title={showKeyText ? 'Hide Key' : 'Show Key'}
                  >
                    {showKeyText ? 'Hide' : 'Show'}
                  </button>
                </div>
                {config?.has_api_key && isChangingKey && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      setIsChangingKey(false);
                      setApiKey('');
                    }}
                    style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                  >
                    Cancel
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Test & Discover Models Action */}
          <div style={{ marginBottom: '22px' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleDiscover}
              disabled={isDiscovering}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', padding: '7px 14px' }}
            >
              {isDiscovering ? (
                <>
                  <svg className="nav-svg-spinner animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="rgba(255,255,255,0.25)" strokeWidth="3" />
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                  </svg>
                  <span>Connecting &amp; Discovering...</span>
                </>
              ) : (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <span>Test Connection &amp; Discover Models</span>
                </>
              )}
            </button>

            {discoveryResult && (
              <div
                style={{
                  marginTop: '10px',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  fontSize: '0.82rem',
                  background: discoveryResult.status === 'success' ? 'rgba(20, 184, 166, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                  border: `1px solid ${discoveryResult.status === 'success' ? 'rgba(20, 184, 166, 0.4)' : 'rgba(239, 68, 68, 0.4)'}`,
                  color: discoveryResult.status === 'success' ? 'var(--accent)' : 'var(--danger)',
                }}
              >
                {discoveryResult.status === 'success'
                  ? `Connected successfully (${discoveryResult.total_models} models available)`
                  : `Connection error: ${discoveryResult.message}`}
              </div>
            )}
          </div>

          {/* Model Assignments */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '22px' }}>
            {/* Chat Model */}
            <div className="form-group" style={{ margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <label style={{ fontWeight: 600, fontSize: '0.84rem' }}>Chat Completion Model</label>
                <button
                  type="button"
                  onClick={() => setCustomChat(!customChat)}
                  style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.74rem' }}
                >
                  {customChat ? 'Use Discovered List' : 'Custom Input'}
                </button>
              </div>
              {customChat || chatOptions.length === 0 ? (
                <input
                  type="text"
                  value={chatModel}
                  onChange={(e) => setChatModel(e.target.value)}
                  placeholder="e.g. gemini-2.5-flash or gpt-4o"
                />
              ) : (
                <select value={chatModel} onChange={(e) => setChatModel(e.target.value)}>
                  {chatOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {!chatOptions.includes(chatModel) && (
                    <option value={chatModel}>{chatModel} (Current)</option>
                  )}
                </select>
              )}
            </div>

            {/* Vision Model */}
            <div className="form-group" style={{ margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <label style={{ fontWeight: 600, fontSize: '0.84rem' }}>Vision OCR Model</label>
                <button
                  type="button"
                  onClick={() => setCustomVision(!customVision)}
                  style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.74rem' }}
                >
                  {customVision ? 'Use Discovered List' : 'Custom Input'}
                </button>
              </div>
              {customVision || visionOptions.length === 0 ? (
                <input
                  type="text"
                  value={visionModel}
                  onChange={(e) => setVisionModel(e.target.value)}
                  placeholder="e.g. gemini-2.5-flash or gpt-4o-mini"
                />
              ) : (
                <select value={visionModel} onChange={(e) => setVisionModel(e.target.value)}>
                  {visionOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {!visionOptions.includes(visionModel) && (
                    <option value={visionModel}>{visionModel} (Current)</option>
                  )}
                </select>
              )}
            </div>

            {/* Embedding Model */}
            <div className="form-group" style={{ margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <label style={{ fontWeight: 600, fontSize: '0.84rem' }}>API Embedding Model</label>
                <button
                  type="button"
                  onClick={() => setCustomEmbedding(!customEmbedding)}
                  style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.74rem' }}
                >
                  {customEmbedding ? 'Use Discovered List' : 'Custom Input'}
                </button>
              </div>
              {customEmbedding || embOptions.length === 0 ? (
                <input
                  type="text"
                  value={embeddingModel}
                  onChange={(e) => setEmbeddingModel(e.target.value)}
                  placeholder="e.g. text-embedding-3-small"
                />
              ) : (
                <select value={embeddingModel} onChange={(e) => setEmbeddingModel(e.target.value)}>
                  {embOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {!embOptions.includes(embeddingModel) && (
                    <option value={embeddingModel}>{embeddingModel} (Current)</option>
                  )}
                </select>
              )}
            </div>
          </div>


          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSaving}
              style={{ padding: '8px 20px', fontSize: '0.88rem' }}
            >
              {isSaving ? 'Saving Settings...' : 'Save AI Gateway Settings'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export default AIGatewaySettings;
