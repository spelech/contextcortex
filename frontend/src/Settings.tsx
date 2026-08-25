import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Stats, GitHostCredential, VectorStoreConfig, AutoSyncSettings } from './types';
import { useToast } from './ToastContext';
import { VectorStoreSettings } from './components/settings/VectorStoreSettings';
import { AutoSyncSettings as AutoSyncSettingsComp } from './components/settings/AutoSyncSettings';
import { GitCredentialsSettings } from './components/settings/GitCredentialsSettings';

export default function Settings({ stats, refreshStats }: { stats: Stats | null; refreshStats: () => void }) {
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

  const toast = useToast();

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

  useEffect(() => {
    loadHostCredentials();
    loadVectorStore();
    loadAutoSyncSettings();
  }, [loadHostCredentials, loadVectorStore, loadAutoSyncSettings]);

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
    } catch (e: any) {
      toast.error('Error saving auto-sync settings: ' + e.message);
    } finally {
      setIsSavingAutoSync(false);
    }
  };

  const handleClearWebhookSecret = async () => {
    if (webhookSecret && !hasGlobalSecret) {
      setWebhookSecret('');
      return;
    }
    if (!window.confirm('Clear the global webhook secret? Incoming webhook payloads will no longer require secret verification unless configured per-repository.')) {
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
      if (!res.ok || !data.success) {
        const msg = data.message || data.error || 'Vector store connection test failed';
        setTestFeedback({ success: false, message: msg });
        toast.error('Vector store test: ' + msg);
      } else {
        const msg = data.message || 'Vector store connection test successful';
        setTestFeedback({ success: true, message: msg });
        toast.success(msg);
      }
    } catch (e: any) {
      const msg = e.message || 'Connection error';
      setTestFeedback({ success: false, message: msg });
      toast.error('Vector store test error: ' + msg);
    } finally {
      setIsTestingVs(false);
    }
  };

  const handleSwitchBackend = async () => {
    const providerName = vsProvider === 'chroma' ? 'ChromaDB' : 'Qdrant';
    const modeName = vsMode === 'embedded' ? 'Embedded Disk' : 'Remote Server';
    if (!window.confirm(`Switch active vector database backend to ${providerName} (${modeName})? This will update settings and trigger a full re-indexing of all sources.`)) {
      return;
    }
    setIsSwitchingVs(true);
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
    <div className="tab-content active" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
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
    </div>
  );
}
