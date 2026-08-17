import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Stats, GitHostCredential, VectorStoreConfig } from './types';
import { useToast } from './ToastContext';

export default function Settings({ stats, refreshStats }: { stats: Stats | null, refreshStats: () => void }) {
  // Global Git Provider Auth State
  const [ghToken, setGhToken] = useState('');
  const [glToken, setGlToken] = useState('');
  const [gtToken, setGtToken] = useState('');
  const [hostCredentials, setHostCredentials] = useState<GitHostCredential[]>([]);

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

  useEffect(() => {
    loadHostCredentials();
    loadVectorStore();
  }, [loadHostCredentials, loadVectorStore]);

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
      
      {/* Vector Store Engine & Backend Configuration */}
      <div className="glass-card">
        <h2><i className="fa-solid fa-database"></i> Vector Database Engine</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
          Configure and switch between vector database backends (Qdrant &amp; ChromaDB). Switching backends updates system metadata and triggers full re-indexing.
        </p>

        <div className="vs-config-layout">
          
          {/* Active Backend Status Box */}
          <div className="vs-box">
            <h3><i className="fa-solid fa-circle-nodes"></i> Active Vector Backend</h3>
            {isLoadingVs && !vectorStore ? (
              <p className="text-muted">Loading vector store configuration...</p>
            ) : vectorStore ? (
              <div className="specs-list" style={{ marginTop: 0 }}>
                <div className="spec-row">
                  <span>Provider:</span>
                  <span className="badge badge-accent">
                    {vectorStore.provider === 'chroma' ? 'ChromaDB' : 'Qdrant'}
                  </span>
                </div>
                <div className="spec-row">
                  <span>Operating Mode:</span>
                  <span className="badge badge-primary">
                    {vectorStore.mode === 'embedded' ? 'Embedded Disk' : 'Remote Server'}
                  </span>
                </div>
                <div className="spec-row">
                  <span>{vectorStore.mode === 'embedded' ? 'Storage Path:' : 'Server URL:'}</span>
                  <code>{vectorStore.mode === 'embedded' ? (vectorStore.storage_path || 'data/qdrant_db') : (vectorStore.url || 'http://localhost:6333')}</code>
                </div>
                <div className="spec-row">
                  <span>Collection Name:</span>
                  <code>{vectorStore.collection || 'knowledge_rag_v1'}</code>
                </div>
                <div className="spec-row">
                  <span>Points Count:</span>
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                    {(vectorStore.points_count || 0).toLocaleString()}
                  </span>
                </div>
                <div className="spec-row">
                  <span>Health Status:</span>
                  {vectorStore.healthy ? (
                    <span className="badge badge-success">
                      <i className="fa-solid fa-circle-check"></i> Healthy
                    </span>
                  ) : (
                    <span className="badge badge-danger" title={vectorStore.health_message || 'Unhealthy'}>
                      <i className="fa-solid fa-triangle-exclamation"></i> {vectorStore.health_message ? (vectorStore.health_message.length > 35 ? vectorStore.health_message.slice(0, 35) + '...' : vectorStore.health_message) : 'Unhealthy'}
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-muted">No vector store configuration found.</p>
            )}
          </div>

          {/* Switch Backend Form Box */}
          <div className="vs-box">
            <h3><i className="fa-solid fa-sliders"></i> Configure &amp; Switch Backend</h3>
            
            {testFeedback && (
              <div className={`vs-feedback-banner ${testFeedback.success ? 'feedback-success' : 'feedback-error'}`}>
                <i className={testFeedback.success ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-exclamation'}></i>
                <span>{testFeedback.message}</span>
              </div>
            )}

            <form onSubmit={e => { e.preventDefault(); handleSwitchBackend(); }}>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="vs-provider">Vector Store Provider</label>
                  <select
                    id="vs-provider"
                    value={vsProvider}
                    onChange={e => handleProviderChange(e.target.value as any)}
                  >
                    <option value="qdrant">Qdrant (Hybrid Dense + BM25)</option>
                    <option value="chroma">ChromaDB (Dense Vectors)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="vs-mode">Operating Mode</label>
                  <select
                    id="vs-mode"
                    value={vsMode}
                    onChange={e => handleModeChange(e.target.value as any)}
                  >
                    <option value="embedded">Embedded Disk Storage</option>
                    <option value="remote">Remote Server URL</option>
                  </select>
                </div>
              </div>

              {vsMode === 'embedded' ? (
                <div className="form-group">
                  <label htmlFor="vs-storage-path">Storage Directory Path</label>
                  <input
                    id="vs-storage-path"
                    type="text"
                    value={vsStoragePath}
                    onChange={e => setVsStoragePath(e.target.value)}
                    placeholder={vsProvider === 'chroma' ? 'data/chroma_db' : 'data/qdrant_db'}
                  />
                </div>
              ) : (
                <div className="form-group">
                  <label htmlFor="vs-url">Remote Server URL</label>
                  <input
                    id="vs-url"
                    type="text"
                    value={vsUrl}
                    onChange={e => setVsUrl(e.target.value)}
                    placeholder={vsProvider === 'chroma' ? 'http://localhost:8000' : 'http://localhost:6333'}
                  />
                </div>
              )}

              <div className="form-group">
                <label htmlFor="vs-collection">Collection Name</label>
                <input
                  id="vs-collection"
                  type="text"
                  value={vsCollection}
                  onChange={e => setVsCollection(e.target.value)}
                  placeholder="knowledge_rag_v1"
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleTestConnection}
                  disabled={isTestingVs || isSwitchingVs}
                >
                  {isTestingVs ? (
                    <><i className="fa-solid fa-spinner fa-spin"></i> Testing Connection...</>
                  ) : (
                    <><i className="fa-solid fa-plug"></i> Test Connection</>
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSwitchBackend}
                  disabled={isTestingVs || isSwitchingVs}
                >
                  {isSwitchingVs ? (
                    <><i className="fa-solid fa-spinner fa-spin"></i> Switching Backend...</>
                  ) : (
                    <><i className="fa-solid fa-arrows-rotate"></i> Save &amp; Switch Backend</>
                  )}
                </button>
              </div>
            </form>
          </div>

        </div>
      </div>

      {/* Global Provider Tokens Card */}
      <div className="glass-card">
        <h2><i className="fa-solid fa-key"></i> Global Git Provider Authentication</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
          Default tokens are automatically applied to repositories matching these providers when no per-repo or host-specific override exists.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))', gap: '20px', marginTop: '20px' }}>
          
          {/* GitHub Token Box */}
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border-card)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-brands fa-github fa-lg"></i> GitHub
              </div>
              <span className="badge badge-accent">{ghAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px', wordBreak: 'break-all' }}>
              Active Token: <code style={{ wordBreak: 'break-all' }}>{ghAuth.masked_token}</code>
            </div>
            {stats?.rate_limit && (
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
                Rate Limit: {stats.rate_limit.remaining} / {stats.rate_limit.limit} requests
              </div>
            )}
            <form onSubmit={e => { e.preventDefault(); saveToken('github_token', ghToken, 'GitHub'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="ghp_xxxxxxxxxxxx" value={ghToken} onChange={e => setGhToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => clearToken('github_token', 'GitHub')}>Clear</button>
              </div>
            </form>
          </div>

          {/* GitLab Token Box */}
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border-card)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-brands fa-gitlab fa-lg" style={{ color: '#fc6d26' }}></i> GitLab (Global)
              </div>
              <span className="badge badge-accent">{glAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px', wordBreak: 'break-all' }}>
              Active Token: <code style={{ wordBreak: 'break-all' }}>{glAuth.masked_token}</code>
            </div>
            <form onSubmit={e => { e.preventDefault(); saveToken('gitlab_token', glToken, 'GitLab'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="glpat-xxxxxxxxxxxx" value={glToken} onChange={e => setGlToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => clearToken('gitlab_token', 'GitLab')}>Clear</button>
              </div>
            </form>
          </div>

          {/* Gitea Token Box */}
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border-card)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-solid fa-mug-hot fa-lg" style={{ color: '#609926' }}></i> Gitea / Forgejo
              </div>
              <span className="badge badge-accent">{gtAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px', wordBreak: 'break-all' }}>
              Active Token: <code style={{ wordBreak: 'break-all' }}>{gtAuth.masked_token}</code>
            </div>
            <form onSubmit={e => { e.preventDefault(); saveToken('gitea_token', gtToken, 'Gitea'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="Token / Personal Token" value={gtToken} onChange={e => setGtToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => clearToken('gitea_token', 'Gitea')}>Clear</button>
              </div>
            </form>
          </div>

        </div>
      </div>

      {/* Self-Hosted & Custom Git Host Vault */}
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-shield-halved"></i> Custom &amp; Self-Hosted Git Host Vault</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Define credentials for self-hosted GitLab Enterprise, Gitea, or custom servers (e.g. <code>gitlab.mycorp.com</code> or <code>git.lan:3000</code>).
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsHostModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Host Credential
          </button>
        </div>

        <div className="table-container desktop-table-view" style={{ marginTop: '16px' }}>
          <table>
            <thead>
              <tr>
                <th>Host Domain / Address</th>
                <th>Provider Type</th>
                <th>Auth User</th>
                <th>Masked Token</th>
                <th>Added At</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {hostCredentials.length === 0 ? (
                <tr>
                  <td colSpan={6} className="empty-state">No custom host credentials configured. Add a host domain to authenticate self-hosted instances.</td>
                </tr>
              ) : (
                hostCredentials.map(hc => (
                  <tr key={hc.id}>
                    <td><code>{hc.host}</code></td>
                    <td>
                      <span className="badge badge-accent">
                        {hc.provider.toUpperCase()}
                      </span>
                    </td>
                    <td>{hc.auth_user ? <code>{hc.auth_user}</code> : <span className="text-muted">Default</span>}</td>
                    <td><code style={{ wordBreak: 'break-all' }}>{hc.masked_token}</code></td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{hc.added_at}</td>
                    <td>
                      <button className="btn-icon btn-delete" onClick={() => deleteHostCredential(hc.id, hc.host)} title="Delete Credential">
                        <i className="fa-solid fa-trash-can"></i>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="mobile-card-list">
          {hostCredentials.length === 0 ? (
            <div className="empty-state">No custom host credentials configured. Add a host domain to authenticate self-hosted instances.</div>
          ) : (
            hostCredentials.map(hc => (
              <div key={`card-${hc.id}`} className="data-mobile-card">
                <div className="data-mobile-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <code style={{ fontSize: '0.95rem' }}>{hc.host}</code>
                  </div>
                  <span className="badge badge-accent">
                    {hc.provider.toUpperCase()}
                  </span>
                </div>

                <div className="data-mobile-card-body">
                  <div>
                    <span className="text-muted">Auth User: </span>
                    {hc.auth_user ? <code>{hc.auth_user}</code> : <span className="text-muted">Default</span>}
                  </div>
                  <div>
                    <span className="text-muted">Masked Token: </span>
                    <code style={{ wordBreak: 'break-all' }}>{hc.masked_token}</code>
                  </div>
                  <div>
                    <span className="text-muted">Added At: </span>
                    <span style={{ color: 'var(--text-muted)' }}>{hc.added_at}</span>
                  </div>
                </div>

                <div className="data-mobile-card-actions">
                  <button className="btn btn-secondary btn-delete" onClick={() => deleteHostCredential(hc.id, hc.host)} title="Delete Credential">
                    <i className="fa-solid fa-trash-can"></i> Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Add Host Credential Modal */}
      {isHostModalOpen && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card">
            <div className="modal-header">
              <h2><i className="fa-solid fa-shield-halved"></i> Add Host Credential</h2>
              <button className="btn-close" onClick={() => setIsHostModalOpen(false)}>&times;</button>
            </div>

            <form onSubmit={handleSaveHostCredential}>
              <div className="form-group">
                <label htmlFor="host-domain">Host Domain / IP</label>
                <input type="text" id="host-domain" required placeholder="e.g. gitlab.mycorp.internal or git.lan:3000" value={newHost} onChange={e => setNewHost(e.target.value)} />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="host-provider">Provider Type</label>
                  <select id="host-provider" value={newHostProvider} onChange={e => setNewHostProvider(e.target.value as any)}>
                    <option value="gitlab">GitLab Enterprise / Self-Hosted</option>
                    <option value="gitea">Gitea / Forgejo</option>
                    <option value="github">GitHub Enterprise</option>
                    <option value="bitbucket">Bitbucket Server / Cloud</option>
                    <option value="generic">Generic Git (HTTP / HTTPS)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="host-user">Auth User (Optional)</label>
                  <input type="text" id="host-user" placeholder="e.g. oauth2 or gitlab-ci-token" value={newHostUser} onChange={e => setNewHostUser(e.target.value)} />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="host-token">Personal Access Token / Password</label>
                <input type="password" id="host-token" required placeholder="Token or password" value={newHostToken} onChange={e => setNewHostToken(e.target.value)} />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsHostModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isSavingHost}>
                  {isSavingHost ? <><i className="fa-solid fa-spinner fa-spin"></i> Saving...</> : 'Save Host Credential'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
