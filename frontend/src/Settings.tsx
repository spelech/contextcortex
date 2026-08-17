import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Stats, GitHostCredential } from './types';
import { useToast } from './ToastContext';

export default function Settings({ stats, refreshStats }: { stats: Stats | null, refreshStats: () => void }) {
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

  useEffect(() => {
    loadHostCredentials();
  }, [loadHostCredentials]);

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
      
      {/* Global Provider Tokens Card */}
      <div className="glass-card">
        <h2><i className="fa-solid fa-key"></i> Global Git Provider Authentication</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
          Default tokens are automatically applied to repositories matching these providers when no per-repo or host-specific override exists.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px', marginTop: '20px' }}>
          
          {/* GitHub Token Box */}
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-brands fa-github fa-lg"></i> GitHub
              </div>
              <span className="badge badge-accent">{ghAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>
              Active Token: <code>{ghAuth.masked_token}</code>
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
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-brands fa-gitlab fa-lg" style={{ color: '#fc6d26' }}></i> GitLab (Global)
              </div>
              <span className="badge badge-accent">{glAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Active Token: <code>{glAuth.masked_token}</code>
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
          <div className="settings-provider-box" style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <i className="fa-solid fa-mug-hot fa-lg" style={{ color: '#609926' }}></i> Gitea / Forgejo
              </div>
              <span className="badge badge-accent">{gtAuth.token_source}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Active Token: <code>{gtAuth.masked_token}</code>
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
            <h2><i className="fa-solid fa-shield-halved"></i> Custom & Self-Hosted Git Host Vault</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Define credentials for self-hosted GitLab Enterprise, Gitea, or custom servers (e.g. <code>gitlab.mycorp.com</code> or <code>git.lan:3000</code>).
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsHostModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Host Credential
          </button>
        </div>

        <div className="table-container" style={{ marginTop: '16px' }}>
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
                    <td><code>{hc.masked_token}</code></td>
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
