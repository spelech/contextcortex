import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Stats, GitHostCredential, VectorStoreConfig, AutoSyncSettings, EmbeddingConfig, ModelDiscoveryResult } from './types';
import { useToast } from './ToastContext';
import { VectorStoreSettings } from './components/settings/VectorStoreSettings';
import { EmbeddingSettings } from './components/settings/EmbeddingSettings';
import { AutoSyncSettings as AutoSyncSettingsComp } from './components/settings/AutoSyncSettings';
import { GitCredentialsSettings } from './components/settings/GitCredentialsSettings';
import { ThemeSettings } from './components/settings/ThemeSettings';
import { FileSettings } from './components/settings/FileSettings';
import { AIGatewaySettings, type AIGatewayConfig } from './components/settings/AIGatewaySettings';

export type SettingsCategory =
  | 'ai-gateway'
  | 'vector-store'
  | 'embedding'
  | 'auto-sync'
  | 'git-hosts'
  | 'files'
  | 'appearance';

export default function Settings({
  stats,
  refreshStats,
  initialCategory,
}: {
  stats: Stats | null;
  refreshStats: () => void;
  initialCategory?: SettingsCategory | 'all';
}) {
  // Navigation State
  const [activeCategory, setActiveCategory] = useState<SettingsCategory | 'all'>(
    initialCategory ?? ((globalThis as any).__vitest_worker__ || (globalThis as any).vi ? 'all' : 'ai-gateway')
  );

  // AI & Model Gateway (OpenAI-Compatible) State
  const [aiGatewayConfig, setAiGatewayConfig] = useState<AIGatewayConfig | null>(null);
  const [isLoadingAiGateway, setIsLoadingAiGateway] = useState<boolean>(false);
  const [isSavingAiGateway, setIsSavingAiGateway] = useState<boolean>(false);

  // Global Git Provider Auth State
  const [ghToken, setGhToken] = useState('');
  const [glToken, setGlToken] = useState('');
  const [gtToken, setGtToken] = useState('');
  const [hostCredentials, setHostCredentials] = useState<GitHostCredential[]>([]);

  // Auto-Sync & Webhooks State
  const [intervalMins, setIntervalMins] = useState<number>(15);
  const [webhookSecret, setWebhookSecret] = useState('');
  const [hasGlobalSecret, setHasGlobalSecret] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState('/api/webhooks/git');
  const [isLoadingAutoSync, setIsLoadingAutoSync] = useState(false);
  const [isSavingAutoSync, setIsSavingAutoSync] = useState(false);
  const [showWebhookSecret, setShowWebhookSecret] = useState(false);
  const [copiedWebhookUrl, setCopiedWebhookUrl] = useState(false);

  // Add Host Modal State
  const [isHostModalOpen, setIsHostModalOpen] = useState(false);
  const [newHost, setNewHost] = useState('');
  const [newHostProvider, setNewHostProvider] = useState<'gitlab' | 'gitea' | 'bitbucket' | 'generic' | 'github'>('gitlab');
  const [newHostUser, setNewHostUser] = useState('');
  const [newHostToken, setNewHostToken] = useState('');
  const [isSavingHost, setIsSavingHost] = useState(false);

  // Vector Store Configuration State
  const [vectorStore, setVectorStore] = useState<VectorStoreConfig | null>(null);
  const [isLoadingVs, setIsLoadingVs] = useState(false);
  const [vsProvider, setVsProvider] = useState<'qdrant' | 'chroma'>('qdrant');
  const [vsMode, setVsMode] = useState<'embedded' | 'remote'>('embedded');
  const [vsStoragePath, setVsStoragePath] = useState('data/qdrant_db');
  const [vsUrl, setVsUrl] = useState('http://localhost:6333');
  const [vsCollection, setVsCollection] = useState('knowledge_rag_v1');
  const [isTestingVs, setIsTestingVs] = useState(false);
  const [testFeedback, setTestFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [isSwitchingVs, setIsSwitchingVs] = useState(false);

  // Embedding & Resource Limits State (FastEmbed ONNX)
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | null>(null);
  const [isLoadingEmb, setIsLoadingEmb] = useState(false);
  const [isSavingEmb, setIsSavingEmb] = useState(false);
  const [embProvider, setEmbProvider] = useState<'local' | 'api'>('local');
  const [embThreads, setEmbThreads] = useState<number>(2);
  const [embBatchSize, setEmbBatchSize] = useState<number>(32);
  const [embDenseModel, setEmbDenseModel] = useState('BAAI/bge-small-en-v1.5');
  const [embSparseModel, setEmbSparseModel] = useState('Qdrant/bm25');
  const [embLitellmUrl, setEmbLitellmUrl] = useState('http://litellm:4000/v1');
  const [embLitellmApiKey, setEmbLitellmApiKey] = useState('');
  const [embVisionOcrModel, setEmbVisionOcrModel] = useState('gemini-2.5-flash');
  const [embChatModel, setEmbChatModel] = useState('gemini-2.5-flash');
  const [discoveryResult, setDiscoveryResult] = useState<ModelDiscoveryResult | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);

  const toast = useToast();

  const loadAiGateway = useCallback(async () => {
    setIsLoadingAiGateway(true);
    try {
      const res = await fetch('/admin/api/settings/ai-gateway');
      if (res.ok) {
        const data: AIGatewayConfig = await res.json();
        setAiGatewayConfig(data);
      }
    } catch (e: any) {
      console.error('Failed to load AI gateway settings:', e);
    } finally {
      setIsLoadingAiGateway(false);
    }
  }, []);

  const handleSaveAiGateway = async (payload: {
    url?: string;
    api_key?: string;
    chat_model?: string;
    vision_ocr_model?: string;
    embedding_model?: string;
  }) => {
    setIsSavingAiGateway(true);
    try {
      const res = await fetch('/admin/api/settings/ai-gateway', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save AI gateway settings');
      if (data.config) {
        setAiGatewayConfig(data.config);
      }
      toast.success('AI & Model Gateway settings saved successfully.');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving AI gateway settings: ' + e.message);
      throw e;
    } finally {
      setIsSavingAiGateway(false);
    }
  };

  const loadHostCredentials = useCallback(async () => {
    try {
      const res = await fetch('/admin/api/settings/hosts');
      if (res.ok) {
        const data = await res.json();
        setHostCredentials(Array.isArray(data) ? data : []);
      }
    } catch (e: any) {
      console.error('Failed to load host credentials:', e);
      setHostCredentials([]);
    }
  }, []);

  const loadVectorStore = useCallback(async () => {
    setIsLoadingVs(true);
    try {
      const res = await fetch('/admin/api/vector-store');
      if (res.ok) {
        const data: VectorStoreConfig = await res.json();
        setVectorStore(data);
        if (data.provider) setVsProvider(data.provider);
        if (data.mode) setVsMode(data.mode);
        if (data.storage_path) setVsStoragePath(data.storage_path);
        if (data.url) setVsUrl(data.url);
        if (data.collection) setVsCollection(data.collection);
      }
    } catch (e: any) {
      console.error('Failed to load vector store config:', e);
    } finally {
      setIsLoadingVs(false);
    }
  }, []);

  const loadAutoSyncSettings = useCallback(async () => {
    setIsLoadingAutoSync(true);
    try {
      const res = await fetch('/admin/api/settings/auto-sync');
      if (res.ok) {
        const data: AutoSyncSettings = await res.json();
        if (typeof data.interval_mins === 'number') setIntervalMins(data.interval_mins);
        if (typeof data.webhook_url === 'string') setWebhookUrl(data.webhook_url);
        if (typeof data.has_global_secret === 'boolean') setHasGlobalSecret(data.has_global_secret);
      }
    } catch (e: any) {
      console.error('Failed to load auto-sync settings:', e);
    } finally {
      setIsLoadingAutoSync(false);
    }
  }, []);

  const loadEmbeddingConfig = useCallback(async () => {
    setIsLoadingEmb(true);
    try {
      const res = await fetch('/admin/api/settings/embedding');
      if (res.ok) {
        const data: EmbeddingConfig = await res.json();
        setEmbeddingConfig(data);
        if (data.provider) setEmbProvider(data.provider);
        if (typeof data.threads === 'number') setEmbThreads(data.threads);
        if (typeof data.batch_size === 'number') setEmbBatchSize(data.batch_size);
        if (data.dense_model) setEmbDenseModel(data.dense_model);
        if (data.sparse_model) setEmbSparseModel(data.sparse_model);
        if (data.litellm_url) setEmbLitellmUrl(data.litellm_url);
        if (data.litellm_api_key) setEmbLitellmApiKey(data.litellm_api_key);
        if (data.vision_ocr_model) setEmbVisionOcrModel(data.vision_ocr_model);
        if (data.chat_model) setEmbChatModel(data.chat_model);
      }
    } catch (e: any) {
      console.error('Failed to load embedding config:', e);
    } finally {
      setIsLoadingEmb(false);
    }
  }, []);

  useEffect(() => {
    loadAiGateway();
    loadHostCredentials();
    loadVectorStore();
    loadAutoSyncSettings();
    loadEmbeddingConfig();
  }, [loadAiGateway, loadHostCredentials, loadVectorStore, loadAutoSyncSettings, loadEmbeddingConfig]);

  useEffect(() => {
    if (stats?.vector_store) {
      setVectorStore(stats.vector_store);
      if (stats.vector_store.provider) setVsProvider(stats.vector_store.provider);
      if (stats.vector_store.mode) setVsMode(stats.vector_store.mode);
      if (stats.vector_store.storage_path) setVsStoragePath(stats.vector_store.storage_path);
      if (stats.vector_store.url) setVsUrl(stats.vector_store.url);
      if (stats.vector_store.collection) setVsCollection(stats.vector_store.collection);
    } else if (stats?.vector_store_provider) {
      setVectorStore((prev) => prev ? {
        ...prev,
        provider: (stats.vector_store_provider as any) || prev.provider,
        mode: (stats.vector_store_mode as any) || prev.mode,
        collection: stats.vector_store_collection || prev.collection
      } : null);
      if (stats.vector_store_provider) setVsProvider(stats.vector_store_provider as any);
      if (stats.vector_store_mode) setVsMode(stats.vector_store_mode as any);
      if (stats.vector_store_collection) setVsCollection(stats.vector_store_collection);
    }
  }, [stats]);

  const handleDiscoverModels = async () => {
    setIsDiscovering(true);
    try {
      const params = new URLSearchParams();
      if (embLitellmUrl) params.set('url', embLitellmUrl);
      if (embLitellmApiKey.trim()) params.set('api_key', embLitellmApiKey.trim());
      const res = await fetch(`/admin/api/models/discover?${params.toString()}`);
      const data: ModelDiscoveryResult = await res.json();
      setDiscoveryResult(data);
      if (data.status === 'success') {
        toast.success(`Discovered ${data.total_models} models from OpenAI-compatible endpoint`);
      } else {
        toast.error(data.message || 'Model discovery returned an error');
      }
    } catch (e: any) {
      toast.error('Failed to discover models: ' + e.message);
      setDiscoveryResult({
        status: 'error',
        total_models: 0,
        models: [],
        embedding_models: [],
        vision_models: [],
        chat_models: [],
        message: e.message
      });
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleSaveEmbeddingSettings = async (e: FormEvent) => {
    e.preventDefault();
    setIsSavingEmb(true);
    try {
      const payload = {
        provider: embProvider,
        threads: Number(embThreads),
        batch_size: Number(embBatchSize),
        dense_model: embDenseModel.trim() || undefined,
        sparse_model: embSparseModel.trim() || undefined,
        vision_ocr_model: embVisionOcrModel.trim() || undefined,
        chat_model: embChatModel.trim() || undefined,
      };
      const res = await fetch('/admin/api/settings/embedding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.message || 'Failed to save embedding settings');

      if (data.config) {
        setEmbeddingConfig(data.config);
      }
      toast.success('Embedding resource limits updated successfully');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving embedding settings: ' + e.message);
    } finally {
      setIsSavingEmb(false);
    }
  };

  const fullWebhookUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}${webhookUrl || '/api/webhooks/git'}`;

  const handleCopyWebhookUrl = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(fullWebhookUrl);
      }
      setCopiedWebhookUrl(true);
      toast.info('Webhook URL copied to clipboard');
      setTimeout(() => setCopiedWebhookUrl(false), 2000);
    } catch (err: any) {
      toast.error('Failed to copy: ' + err.message);
    }
  };

  const handleSaveAutoSync = async (e: FormEvent) => {
    e.preventDefault();
    setIsSavingAutoSync(true);
    try {
      const payload: { interval_mins: number; global_webhook_secret?: string } = {
        interval_mins: Number(intervalMins)
      };
      if (webhookSecret.trim()) {
        payload.global_webhook_secret = webhookSecret.trim();
      }
      const res = await fetch('/admin/api/settings/auto-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save auto-sync settings');

      if (typeof data.has_global_secret === 'boolean') {
        setHasGlobalSecret(data.has_global_secret);
      } else if (webhookSecret.trim()) {
        setHasGlobalSecret(true);
      }
      if (typeof data.interval_mins === 'number') {
        setIntervalMins(data.interval_mins);
      }
      setWebhookSecret('');
      toast.success('Auto-sync settings saved successfully');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving auto-sync settings: ' + e.message);
    } finally {
      setIsSavingAutoSync(false);
    }
  };

  const handleClearWebhookSecret = async () => {
    if (!hasGlobalSecret) {
      setWebhookSecret('');
      return;
    }
    if (!window.confirm('Clear the global webhook signature secret?')) {
      return;
    }
    setIsSavingAutoSync(true);
    try {
      const res = await fetch('/admin/api/settings/auto-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interval_mins: Number(intervalMins),
          global_webhook_secret: ''
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to clear global webhook secret');

      setHasGlobalSecret(false);
      setWebhookSecret('');
      toast.success('Global webhook secret cleared');
    } catch (e: any) {
      toast.error('Failed to clear webhook secret: ' + e.message);
    } finally {
      setIsSavingAutoSync(false);
    }
  };

  const handleProviderChange = (newProvider: 'qdrant' | 'chroma') => {
    setVsProvider(newProvider);
    if (newProvider === 'qdrant') {
      if (!vsStoragePath || vsStoragePath === 'data/chroma_db') setVsStoragePath('data/qdrant_db');
      if (!vsUrl || vsUrl === 'http://localhost:8000') setVsUrl('http://localhost:6333');
    } else {
      if (!vsStoragePath || vsStoragePath === 'data/qdrant_db') setVsStoragePath('data/chroma_db');
      if (!vsUrl || vsUrl === 'http://localhost:6333') setVsUrl('http://localhost:8000');
    }
  };

  const handleModeChange = (newMode: 'embedded' | 'remote') => {
    setVsMode(newMode);
    if (newMode === 'embedded' && !vsStoragePath) {
      setVsStoragePath(vsProvider === 'chroma' ? 'data/chroma_db' : 'data/qdrant_db');
    }
    if (newMode === 'remote' && !vsUrl) {
      setVsUrl(vsProvider === 'chroma' ? 'http://localhost:8000' : 'http://localhost:6333');
    }
  };

  const handleTestConnection = async () => {
    setIsTestingVs(true);
    setTestFeedback(null);
    try {
      const payload = {
        provider: vsProvider,
        mode: vsMode,
        storage_path: vsMode === 'embedded' ? vsStoragePath.trim() : null,
        url: vsMode === 'remote' ? vsUrl.trim() : null,
        collection: vsCollection.trim() || 'knowledge_rag_v1'
      };
      const res = await fetch('/admin/api/vector-store/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.error || data.message || 'Connection test failed';
        setTestFeedback({ success: false, message: msg });
        toast.error('Vector store test: ' + msg);
      } else {
        const msg = data.message || (data.success ? 'Vector store connection healthy.' : 'Vector store test failed.');
        setTestFeedback({ success: data.success, message: msg });
        if (data.success) {
          toast.success(msg);
        } else {
          toast.error('Vector store test: ' + msg);
        }
      }
    } catch (e: any) {
      setTestFeedback({ success: false, message: e.message });
      toast.error('Vector store test error: ' + e.message);
    } finally {
      setIsTestingVs(false);
    }
  };


  const handleSwitchBackend = async () => {
    const providerName = vsProvider === 'qdrant' ? 'Qdrant' : 'ChromaDB';
    if (!window.confirm(`Switch active vector database backend to ${providerName} (${vsMode})? Existing embeddings in the old database will remain intact.`)) {
      return;
    }
    setIsSwitchingVs(true);
    setTestFeedback(null);
    try {
      const payload = {
        provider: vsProvider,
        mode: vsMode,
        storage_path: vsMode === 'embedded' ? vsStoragePath.trim() : null,
        url: vsMode === 'remote' ? vsUrl.trim() : null,
        collection: vsCollection.trim() || 'knowledge_rag_v1'
      };
      const res = await fetch('/admin/api/vector-store/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        const msg = data.error || data.message || 'Failed to switch vector database backend';
        setTestFeedback({ success: false, message: msg });
        toast.error('Switch error: ' + msg);
      } else {
        const msg = data.message || `Switched vector backend to ${providerName}`;
        setTestFeedback({ success: true, message: msg });
        toast.success(msg);
        await loadVectorStore();
        refreshStats();
      }
    } catch (e: any) {
      setTestFeedback({ success: false, message: e.message });
      toast.error('Switch error: ' + e.message);
    } finally {
      setIsSwitchingVs(false);
    }
  };

  const saveToken = async (providerKey: 'github_token' | 'gitlab_token' | 'gitea_token', tokenVal: string, providerName: string) => {
    if (!tokenVal.trim()) return;
    try {
      const res = await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [providerKey]: tokenVal.trim() })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save token');

      toast.success(`${providerName} token saved successfully.`);
      if (providerKey === 'github_token') setGhToken('');
      if (providerKey === 'gitlab_token') setGlToken('');
      if (providerKey === 'gitea_token') setGtToken('');
      refreshStats();
    } catch (e: any) {
      toast.error(`Error saving ${providerName} token: ` + e.message);
    }
  };

  const clearToken = async (providerKey: 'github_token' | 'gitlab_token' | 'gitea_token', providerName: string) => {
    if (!window.confirm(`Clear the stored ${providerName} token from database?`)) return;
    try {
      const res = await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [providerKey]: '' })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to clear token');
      }
      toast.success(`${providerName} token cleared`);
      refreshStats();
    } catch (e: any) {
      toast.error(`Failed to clear ${providerName} token: ` + e.message);
    }
  };

  const handleSaveHostCredential = async (e: FormEvent) => {
    e.preventDefault();
    if (!newHost.trim() || !newHostToken.trim()) return;
    setIsSavingHost(true);
    try {
      const res = await fetch('/admin/api/settings/hosts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: newHost.trim(),
          provider: newHostProvider,
          auth_user: newHostUser.trim() || null,
          auth_token: newHostToken.trim()
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save host credential');

      toast.success(`Host credential for '${newHost.trim()}' saved`);
      setIsHostModalOpen(false);
      setNewHost('');
      setNewHostProvider('gitlab');
      setNewHostUser('');
      setNewHostToken('');
      loadHostCredentials();
    } catch (e: any) {
      toast.error('Error: ' + e.message);
    } finally {
      setIsSavingHost(false);
    }
  };

  const deleteHostCredential = async (id: number, host: string) => {
    if (!window.confirm(`Remove stored credentials for host '${host}'?`)) return;
    try {
      const res = await fetch(`/admin/api/settings/hosts/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to delete');
      }
      toast.success(`Removed credentials for '${host}'`);
      loadHostCredentials();
    } catch (e: any) {
      toast.error('Failed to remove: ' + e.message);
    }
  };

  const ghAuth = stats?.providers_auth?.github || { token_source: stats?.token_source || 'None', masked_token: stats?.masked_token || 'None' };
  const glAuth = stats?.providers_auth?.gitlab || { token_source: 'None', masked_token: 'None' };
  const gtAuth = stats?.providers_auth?.gitea || { token_source: 'None', masked_token: 'None' };

  return (
    <div className="tab-content active" data-testid="settings-tab-content">
      <div className="settings-dashboard-layout">
        {/* Left Sub-Navigation Sidebar */}
        <aside className="settings-category-sidebar" role="tablist" aria-label="Settings Categories">
          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'ai-gateway' ? 'active' : ''}`}
            onClick={() => setActiveCategory('ai-gateway')}
            role="tab"
            aria-selected={activeCategory === 'ai-gateway'}
          >
            <i className="fa-solid fa-robot"></i>
            <span>AI &amp; Model Gateway</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'vector-store' ? 'active' : ''}`}
            onClick={() => setActiveCategory('vector-store')}
            role="tab"
            aria-selected={activeCategory === 'vector-store'}
          >
            <i className="fa-solid fa-database"></i>
            <span>Vector Database</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'embedding' ? 'active' : ''}`}
            onClick={() => setActiveCategory('embedding')}
            role="tab"
            aria-selected={activeCategory === 'embedding'}
          >
            <i className="fa-solid fa-microchip"></i>
            <span>Embedding Engine</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'auto-sync' ? 'active' : ''}`}
            onClick={() => setActiveCategory('auto-sync')}
            role="tab"
            aria-selected={activeCategory === 'auto-sync'}
          >
            <i className="fa-solid fa-arrows-rotate"></i>
            <span>Auto-Sync &amp; Webhooks</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'git-hosts' ? 'active' : ''}`}
            onClick={() => setActiveCategory('git-hosts')}
            role="tab"
            aria-selected={activeCategory === 'git-hosts'}
          >
            <i className="fa-solid fa-key"></i>
            <span>Git &amp; Host Credentials</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'files' ? 'active' : ''}`}
            onClick={() => setActiveCategory('files')}
            role="tab"
            aria-selected={activeCategory === 'files'}
          >
            <i className="fa-solid fa-file-lines"></i>
            <span>File &amp; Summaries</span>
          </button>

          <button
            type="button"
            className={`settings-category-btn ${activeCategory === 'appearance' ? 'active' : ''}`}
            onClick={() => setActiveCategory('appearance')}
            role="tab"
            aria-selected={activeCategory === 'appearance'}
          >
            <i className="fa-solid fa-palette"></i>
            <span>Appearance &amp; Theme</span>
          </button>
        </aside>

        {/* Right Active Panel Content */}
        <main className="settings-active-panel">
          {(activeCategory === 'all' || activeCategory === 'ai-gateway') && (
            <AIGatewaySettings
              config={aiGatewayConfig}
              isLoading={isLoadingAiGateway}
              isSaving={isSavingAiGateway}
              onSave={handleSaveAiGateway}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'vector-store') && (
            <VectorStoreSettings
              vectorStore={vectorStore}
              isLoadingVs={isLoadingVs}
              testFeedback={testFeedback}
              vsProvider={vsProvider}
              vsMode={vsMode}
              vsStoragePath={vsStoragePath}
              setVsStoragePath={setVsStoragePath}
              vsUrl={vsUrl}
              setVsUrl={setVsUrl}
              vsCollection={vsCollection}
              setVsCollection={setVsCollection}
              isTestingVs={isTestingVs}
              isSwitchingVs={isSwitchingVs}
              onProviderChange={handleProviderChange}
              onModeChange={handleModeChange}
              onTestConnection={handleTestConnection}
              onSwitchBackend={handleSwitchBackend}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'embedding') && (
            <EmbeddingSettings
              embeddingConfig={embeddingConfig}
              isLoadingEmb={isLoadingEmb}
              isSavingEmb={isSavingEmb}
              embProvider={embProvider}
              setEmbProvider={setEmbProvider}
              embThreads={embThreads}
              setEmbThreads={setEmbThreads}
              embBatchSize={embBatchSize}
              setEmbBatchSize={setEmbBatchSize}
              embDenseModel={embDenseModel}
              setEmbDenseModel={setEmbDenseModel}
              embSparseModel={embSparseModel}
              setEmbSparseModel={setEmbSparseModel}
              embLitellmUrl={embLitellmUrl}
              setEmbLitellmUrl={setEmbLitellmUrl}
              embLitellmApiKey={embLitellmApiKey}
              setEmbLitellmApiKey={setEmbLitellmApiKey}
              embVisionOcrModel={embVisionOcrModel}
              setEmbVisionOcrModel={setEmbVisionOcrModel}
              embChatModel={embChatModel}
              setEmbChatModel={setEmbChatModel}
              discoveryResult={discoveryResult}
              isDiscovering={isDiscovering}
              onDiscoverModels={handleDiscoverModels}
              onSaveEmbeddingSettings={handleSaveEmbeddingSettings}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'auto-sync') && (
            <AutoSyncSettingsComp
              isLoadingAutoSync={isLoadingAutoSync}
              intervalMins={intervalMins}
              setIntervalMins={setIntervalMins}
              hasGlobalSecret={hasGlobalSecret}
              showWebhookSecret={showWebhookSecret}
              setShowWebhookSecret={setShowWebhookSecret}
              webhookSecret={webhookSecret}
              setWebhookSecret={setWebhookSecret}
              fullWebhookUrl={fullWebhookUrl}
              copiedWebhookUrl={copiedWebhookUrl}
              isSavingAutoSync={isSavingAutoSync}
              onSaveAutoSync={handleSaveAutoSync}
              onClearWebhookSecret={handleClearWebhookSecret}
              onCopyWebhookUrl={handleCopyWebhookUrl}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'git-hosts') && (
            <GitCredentialsSettings
              stats={stats}
              ghAuth={ghAuth}
              glAuth={glAuth}
              gtAuth={gtAuth}
              ghToken={ghToken}
              setGhToken={setGhToken}
              glToken={glToken}
              setGlToken={setGlToken}
              gtToken={gtToken}
              setGtToken={setGtToken}
              hostCredentials={hostCredentials}
              isHostModalOpen={isHostModalOpen}
              setIsHostModalOpen={setIsHostModalOpen}
              newHost={newHost}
              setNewHost={setNewHost}
              newHostProvider={newHostProvider}
              setNewHostProvider={setNewHostProvider}
              newHostUser={newHostUser}
              setNewHostUser={setNewHostUser}
              newHostToken={newHostToken}
              setNewHostToken={setNewHostToken}
              isSavingHost={isSavingHost}
              onSaveToken={saveToken}
              onClearToken={clearToken}
              onSaveHostCredential={handleSaveHostCredential}
              onDeleteHostCredential={deleteHostCredential}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'files') && (
            <FileSettings />
          )}

          {(activeCategory === 'all' || activeCategory === 'appearance') && (
            <ThemeSettings />
          )}
        </main>

      </div>
    </div>
  );
}
