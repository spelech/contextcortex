import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Repo } from './types';
import { useToast } from './ToastContext';

export default function GitRepoManager({ refreshStats }: { refreshStats: () => void }) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [webhookModalRepo, setWebhookModalRepo] = useState<Repo | null>(null);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const toast = useToast();
  
  // Modal state
  const [alias, setAlias] = useState('');
  const [url, setUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [provider, setProvider] = useState('auto');
  const [authUser, setAuthUser] = useState('');
  const [token, setToken] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const loadRepos = useCallback(async () => {
    try {
      const response = await fetch('/admin/api/repos');
      if (!response.ok) {
        toast.error('Failed to load repositories');
        return;
      }
      const data = await response.json();
      setRepos(data);
    } catch (e: any) {
      toast.error('Error loading repos: ' + e.message);
      console.error('Error loading repos:', e);
    }
  }, [toast]);

  useEffect(() => {
    loadRepos();
    const interval = setInterval(loadRepos, 8000);
    return () => clearInterval(interval);
  }, [loadRepos]);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const res = await fetch('/admin/api/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          name: alias.trim(), 
          url: url.trim(), 
          branch: branch.trim() || 'main', 
          provider: provider === 'auto' ? undefined : provider,
          auth_user: authUser.trim() || null,
          auth_token: token.trim() || null 
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to add repository');

      setIsModalOpen(false);
      setAlias('');
      setUrl('');
      setBranch('main');
      setProvider('auto');
      setAuthUser('');
      setToken('');
      loadRepos();
      refreshStats();
      toast.success(`Repository '${alias.trim()}' added successfully`);
    } catch (err: any) {
      toast.error(`Error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const syncRepo = async (id: number) => {
    // Optimistic status update
    setRepos((prev) => prev.map((r) => (r.id === id ? { ...r, status: 'syncing' } : r)));
    try {
      const res = await fetch(`/admin/api/repos/sync/${id}`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to trigger sync');
      }
      loadRepos();
      refreshStats();
      toast.info('Sync triggered successfully');
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to trigger sync: ' + e.message);
    }
  };

  const toggleAutoSync = async (repoId: number, currentState: boolean) => {
    const nextState = !currentState;
    // Optimistic update
    setRepos((prev) =>
      prev.map((r) => (r.id === repoId ? { ...r, auto_sync: nextState } : r))
    );

    try {
      const res = await fetch(`/admin/api/repos/${repoId}/auto-sync`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_sync: nextState })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || data.detail || 'Failed to update auto-sync');
      }
      toast.info(`Auto-sync ${nextState ? 'enabled' : 'disabled'}`);
      loadRepos();
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to update auto-sync: ' + e.message);
    }
  };

  const handleCopyUrl = async (text: string) => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      }
      setCopiedUrl(true);
      toast.info('Webhook URL copied to clipboard');
      setTimeout(() => setCopiedUrl(false), 2000);
    } catch (err: any) {
      toast.error('Failed to copy: ' + err.message);
    }
  };

  const deleteRepo = async (id: number, name: string) => {
    if (!window.confirm(`Are you sure you want to delete repository '${name}'? All vectors and indexed symbols for this repo will be permanently purged.`)) {
      return;
    }
    // Optimistic removal from list
    setRepos((prev) => prev.filter((r) => r.id !== id));
    try {
      const res = await fetch(`/admin/api/repos/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to delete repo');
      }
      loadRepos();
      refreshStats();
      toast.success(`Repository '${name}' deleted successfully`);
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to delete repo: ' + e.message);
    }
  };

  const getProviderIcon = (prov?: string) => {
    const p = (prov || 'github').toLowerCase();
    if (p === 'gitlab') return <i className="fa-brands fa-gitlab" style={{ color: '#fc6d26', marginRight: '6px' }} title="GitLab" />;
    if (p === 'gitea' || p === 'forgejo') return <i className="fa-solid fa-mug-hot" style={{ color: '#609926', marginRight: '6px' }} title="Gitea / Forgejo" />;
    if (p === 'bitbucket') return <i className="fa-brands fa-bitbucket" style={{ color: '#2684ff', marginRight: '6px' }} title="Bitbucket" />;
    if (p === 'generic') return <i className="fa-solid fa-code-branch" style={{ color: 'var(--accent)', marginRight: '6px' }} title="Generic Git" />;
    return <i className="fa-brands fa-github" style={{ marginRight: '6px' }} title="GitHub" />;
  };

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-code-branch"></i> Registered Git Repositories</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>Supports GitHub, GitLab, Gitea, Bitbucket, and custom self-hosted Git repositories over HTTP/HTTPS.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Repository
          </button>
        </div>

        <div className="table-container desktop-table-view">
          <table>
            <thead>
              <tr>
                <th>Repo Alias</th>
                <th>Git URL</th>
                <th>Branch</th>
                <th>Commit SHA</th>
                <th>Status</th>
                <th>Auto-Sync</th>
                <th>Files</th>
                <th>Last Synced</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {repos.length === 0 ? (
                <tr>
                  <td colSpan={9} className="empty-state">No Git repositories registered. Click "Add Repository" to index a remote repo.</td>
                </tr>
              ) : (
                repos.map(r => {
                  const isAutoSync = r.auto_sync !== false && r.auto_sync !== 0;
                  return (
                    <tr key={r.id}>
                      <td>
                        {getProviderIcon(r.provider)}
                        <strong>{r.name}</strong>
                      </td>
                      <td>
                        <a href={r.url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none', fontSize: '0.85rem' }}>
                          <i className="fa-solid fa-arrow-up-right-from-square"></i> {r.url}
                        </a>
                      </td>
                      <td><code>{r.branch}</code></td>
                      <td>{r.commit_sha ? <code>{r.commit_sha.substring(0, 8)}</code> : <span className="text-muted">-</span>}</td>
                      <td>
                        {r.status === 'syncing' ? <span className="badge badge-warning"><i className="fa-solid fa-spinner fa-spin"></i> Syncing</span> :
                         r.status === 'error' ? (
                           <div>
                             <span className="badge badge-danger" title={r.last_error || 'Sync failed'}>
                               <i className="fa-solid fa-circle-exclamation"></i> Error
                             </span>
                             {r.last_error && (
                               <div style={{ fontSize: '0.75rem', color: 'var(--danger)', marginTop: '4px', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.last_error}>
                                 {r.last_error}
                               </div>
                             )}
                           </div>
                         ) :
                         r.status === 'pending' ? <span className="badge badge-primary"><i className="fa-solid fa-clock"></i> Pending</span> :
                         <span className="badge badge-success"><i className="fa-solid fa-check"></i> Synced</span>}
                      </td>
                      <td>
                        <button
                          type="button"
                          className={`badge ${isAutoSync ? 'badge-success' : 'badge-danger'}`}
                          style={{
                            cursor: 'pointer',
                            background: isAutoSync ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                            border: isAutoSync ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(239, 68, 68, 0.4)',
                            color: isAutoSync ? '#6ee7b7' : '#fca5a5',
                            padding: '4px 8px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px'
                          }}
                          onClick={() => toggleAutoSync(r.id, isAutoSync)}
                          title={`Auto-Sync: ${isAutoSync ? 'ON' : 'OFF'} (Click to toggle)`}
                          aria-label={`Toggle auto-sync for ${r.name}`}
                        >
                          <i className={`fa-solid ${isAutoSync ? 'fa-toggle-on' : 'fa-toggle-off'}`}></i>
                          Auto-Sync: {isAutoSync ? 'ON' : 'OFF'}
                        </button>
                      </td>
                      <td>{(r.file_count || 0).toLocaleString()} files</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{r.last_synced || 'Never'}</td>
                      <td>
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.8rem' }} onClick={() => syncRepo(r.id)} title="Trigger Sync">
                            <i className="fa-solid fa-arrows-rotate"></i> Sync
                          </button>
                          <button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.8rem' }} onClick={() => setWebhookModalRepo(r)} title="Webhook Setup">
                            <i className="fa-solid fa-bolt"></i> Webhook
                          </button>
                          <button className="btn-icon btn-delete" onClick={() => deleteRepo(r.id, r.name)} title="Delete Repo">
                            <i className="fa-solid fa-trash-can"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="mobile-card-list">
          {repos.length === 0 ? (
            <div className="empty-state">No Git repositories registered. Click "Add Repository" to index a remote repo.</div>
          ) : (
            repos.map(r => {
              const isAutoSync = r.auto_sync !== false && r.auto_sync !== 0;
              return (
                <div key={`card-${r.id}`} className="data-mobile-card">
                  <div className="data-mobile-card-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {getProviderIcon(r.provider)}
                      <strong style={{ fontSize: '1rem' }}>{r.name}</strong>
                    </div>
                    {r.status === 'syncing' ? <span className="badge badge-warning"><i className="fa-solid fa-spinner fa-spin"></i> Syncing</span> :
                     r.status === 'error' ? (
                       <span className="badge badge-danger" title={r.last_error || 'Sync failed'}>
                         <i className="fa-solid fa-circle-exclamation"></i> Error
                       </span>
                     ) :
                     r.status === 'pending' ? <span className="badge badge-primary"><i className="fa-solid fa-clock"></i> Pending</span> :
                     <span className="badge badge-success"><i className="fa-solid fa-check"></i> Synced</span>}
                  </div>

                  <div className="data-mobile-card-body">
                    <div>
                      <span className="text-muted">URL: </span>
                      <a href={r.url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none', fontSize: '0.85rem' }}>
                        <i className="fa-solid fa-arrow-up-right-from-square"></i> {r.url}
                      </a>
                    </div>
                    <div>
                      <span className="text-muted">Branch: </span>
                      <code>{r.branch}</code>
                    </div>
                    <div>
                      <span className="text-muted">Commit: </span>
                      {r.commit_sha ? <code>{r.commit_sha.substring(0, 8)}</code> : <span className="text-muted">-</span>}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="text-muted">Auto-Sync: </span>
                      <button
                        type="button"
                        className={`badge ${isAutoSync ? 'badge-success' : 'badge-danger'}`}
                        style={{
                          cursor: 'pointer',
                          background: isAutoSync ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                          border: isAutoSync ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(239, 68, 68, 0.4)',
                          color: isAutoSync ? '#6ee7b7' : '#fca5a5',
                          padding: '4px 8px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px'
                        }}
                        onClick={() => toggleAutoSync(r.id, isAutoSync)}
                        title={`Auto-Sync: ${isAutoSync ? 'ON' : 'OFF'} (Click to toggle)`}
                        aria-label={`Toggle auto-sync for ${r.name}`}
                      >
                        <i className={`fa-solid ${isAutoSync ? 'fa-toggle-on' : 'fa-toggle-off'}`}></i>
                        Auto-Sync: {isAutoSync ? 'ON' : 'OFF'}
                      </button>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>
                        <span className="text-muted">Files: </span>
                        {(r.file_count || 0).toLocaleString()} files
                      </span>
                      <span>
                        <span className="text-muted">Last Synced: </span>
                        <span style={{ color: 'var(--text-muted)' }}>{r.last_synced || 'Never'}</span>
                      </span>
                    </div>
                    {r.status === 'error' && r.last_error && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--danger)', marginTop: '2px' }}>
                        {r.last_error}
                      </div>
                    )}
                  </div>

                  <div className="data-mobile-card-actions">
                    <button className="btn btn-secondary" onClick={() => syncRepo(r.id)} title="Trigger Sync">
                      <i className="fa-solid fa-arrows-rotate"></i> Sync
                    </button>
                    <button className="btn btn-secondary" onClick={() => setWebhookModalRepo(r)} title="Webhook Setup">
                      <i className="fa-solid fa-bolt"></i> Webhook
                    </button>
                    <button className="btn btn-secondary btn-delete" onClick={() => deleteRepo(r.id, r.name)} title="Delete Repo">
                      <i className="fa-solid fa-trash-can"></i> Delete
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {isModalOpen && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsModalOpen(false);
          }}
        >
          <div className="glass-card modal-card">
            <div className="modal-header">
              <h2><i className="fa-solid fa-code-branch"></i> Register Git Repository</h2>
              <button className="btn-close" onClick={() => setIsModalOpen(false)}>&times;</button>
            </div>
            
            <form onSubmit={handleSave}>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="repo-alias">Repository Alias / Identifier</label>
                  <input type="text" id="repo-alias" required placeholder="e.g. backend-api or contextcortex" value={alias} onChange={e => setAlias(e.target.value)} />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-provider">Git Provider</label>
                  <select id="repo-provider" value={provider} onChange={e => setProvider(e.target.value)}>
                    <option value="auto">Auto-Detect</option>
                    <option value="github">GitHub / GitHub Enterprise</option>
                    <option value="gitlab">GitLab (Cloud / Self-Hosted)</option>
                    <option value="gitea">Gitea / Forgejo</option>
                    <option value="bitbucket">Bitbucket</option>
                    <option value="generic">Generic Git (HTTP / HTTPS)</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="repo-url">Git Clone URL (HTTP / HTTPS)</label>
                <input type="text" id="repo-url" required placeholder="https://github.com/owner/repo.git or http://git.lan:3000/repo.git" value={url} onChange={e => setUrl(e.target.value)} />
              </div>

              <div className="form-row form-row-3col">
                <div className="form-group">
                  <label htmlFor="repo-branch">Branch / Tag</label>
                  <input type="text" id="repo-branch" placeholder="main" value={branch} onChange={e => setBranch(e.target.value)} />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-user">Auth User (Optional)</label>
                  <input type="text" id="repo-user" placeholder="e.g. oauth2" value={authUser} onChange={e => setAuthUser(e.target.value)} />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-token">Auth Token (Optional)</label>
                  <input type="password" id="repo-token" placeholder="Token override" value={token} onChange={e => setToken(e.target.value)} />
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isSaving}>
                  {isSaving ? <><i className="fa-solid fa-spinner fa-spin"></i> Adding & Syncing...</> : 'Add & Start Sync'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {webhookModalRepo && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setWebhookModalRepo(null);
          }}
          data-testid="webhook-modal-backdrop"
        >
          <div className="glass-card modal-card" style={{ maxWidth: '650px' }}>
            <div className="modal-header">
              <h2>
                <i className="fa-solid fa-bolt"></i> Webhook Setup: {webhookModalRepo.name}
              </h2>
              <button
                className="btn-close"
                onClick={() => setWebhookModalRepo(null)}
                aria-label="Close webhook modal"
              >
                &times;
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '0.9rem' }}>
              <p className="text-muted">
                Configure a webhook in your Git repository provider to automatically trigger synchronization on every push event.
              </p>

              <div className="form-group">
                <label>Webhook URL (Payload URL)</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    type="text"
                    readOnly
                    value={`${typeof window !== 'undefined' ? window.location.origin : ''}/api/webhooks/git`}
                    style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                    aria-label="Webhook Payload URL"
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() =>
                      handleCopyUrl(
                        `${typeof window !== 'undefined' ? window.location.origin : ''}/api/webhooks/git`
                      )
                    }
                    style={{ minWidth: '95px' }}
                    aria-label="Copy Webhook URL"
                  >
                    <i className={`fa-solid ${copiedUrl ? 'fa-check' : 'fa-copy'}`}></i>{' '}
                    {copiedUrl ? 'Copied!' : 'Copy'}
                  </button>
                </div>
              </div>

              {webhookModalRepo.webhook_secret && (
                <div className="form-group">
                  <label>Repository Secret Token (HMAC)</label>
                  <input
                    type="text"
                    readOnly
                    value={webhookModalRepo.webhook_secret}
                    style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                    aria-label="Repository Secret Token"
                  />
                </div>
              )}

              <div
                style={{
                  background: 'rgba(0, 0, 0, 0.25)',
                  border: '1px solid var(--border-card)',
                  borderRadius: '8px',
                  padding: '14px'
                }}
              >
                <h3 style={{ fontSize: '0.95rem', marginBottom: '10px', color: 'var(--text)' }}>
                  <i className="fa-solid fa-list-check"></i> Provider Setup Instructions
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.85rem' }}>
                  <div>
                    <strong style={{ color: '#fff' }}>
                      <i className="fa-brands fa-github" style={{ marginRight: '6px' }} /> GitHub:
                    </strong>
                    <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                      Navigate to <code>Settings &gt; Webhooks &gt; Add webhook</code> &rarr; set <em>Payload URL</em> to the URL above &rarr; set <em>Content type</em> to <code>application/json</code> &rarr; select <em>Push events</em> &rarr; click <strong>Add webhook</strong>.
                    </div>
                  </div>

                  <div>
                    <strong style={{ color: '#fff' }}>
                      <i className="fa-brands fa-gitlab" style={{ color: '#fc6d26', marginRight: '6px' }} /> GitLab:
                    </strong>
                    <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                      Navigate to <code>Settings &gt; Webhooks</code> (or <code>Settings &gt; Integrations</code>) &rarr; set <em>URL</em> &rarr; select <em>Push events</em> &rarr; click <strong>Add webhook</strong>.
                    </div>
                  </div>

                  <div>
                    <strong style={{ color: '#fff' }}>
                      <i className="fa-solid fa-mug-hot" style={{ color: '#609926', marginRight: '6px' }} /> Gitea / Forgejo:
                    </strong>
                    <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                      Navigate to <code>Settings &gt; Webhooks &gt; Add Webhook &gt; Gitea</code> &rarr; set <em>Target URL</em> &rarr; set <em>HTTP Method</em> to <code>POST</code> &rarr; select <em>Push Events</em> &rarr; click <strong>Add Webhook</strong>.
                    </div>
                  </div>
                </div>
              </div>

              <div className="modal-footer" style={{ marginTop: '8px', padding: 0 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setWebhookModalRepo(null)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
