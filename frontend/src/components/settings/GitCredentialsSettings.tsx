import type { FormEvent } from 'react';
import type { Stats, GitHostCredential } from '../../types';

interface GitCredentialsSettingsProps {
  stats: Stats | null;
  ghAuth: { token_source: string; masked_token: string };
  glAuth: { token_source: string; masked_token: string };
  gtAuth: { token_source: string; masked_token: string };
  ghToken: string;
  setGhToken: (val: string) => void;
  glToken: string;
  setGlToken: (val: string) => void;
  gtToken: string;
  setGtToken: (val: string) => void;
  hostCredentials: GitHostCredential[];
  isHostModalOpen: boolean;
  setIsHostModalOpen: (val: boolean) => void;
  newHost: string;
  setNewHost: (val: string) => void;
  newHostProvider: 'gitlab' | 'gitea' | 'bitbucket' | 'generic' | 'github';
  setNewHostProvider: (val: 'gitlab' | 'gitea' | 'bitbucket' | 'generic' | 'github') => void;
  newHostUser: string;
  setNewHostUser: (val: string) => void;
  newHostToken: string;
  setNewHostToken: (val: string) => void;
  isSavingHost: boolean;
  onSaveToken: (key: 'github_token' | 'gitlab_token' | 'gitea_token', val: string, name: string) => void;
  onClearToken: (key: 'github_token' | 'gitlab_token' | 'gitea_token', name: string) => void;
  onSaveHostCredential: (e: FormEvent) => void;
  onDeleteHostCredential: (id: number, host: string) => void;
}

export function GitCredentialsSettings({
  stats,
  ghAuth,
  glAuth,
  gtAuth,
  ghToken,
  setGhToken,
  glToken,
  setGlToken,
  gtToken,
  setGtToken,
  hostCredentials,
  isHostModalOpen,
  setIsHostModalOpen,
  newHost,
  setNewHost,
  newHostProvider,
  setNewHostProvider,
  newHostUser,
  setNewHostUser,
  newHostToken,
  setNewHostToken,
  isSavingHost,
  onSaveToken,
  onClearToken,
  onSaveHostCredential,
  onDeleteHostCredential,
}: GitCredentialsSettingsProps) {
  return (
    <>
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
            <form onSubmit={e => { e.preventDefault(); onSaveToken('github_token', ghToken, 'GitHub'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="ghp_xxxxxxxxxxxx" value={ghToken} onChange={e => setGhToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => onClearToken('github_token', 'GitHub')}>Clear</button>
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
            <form onSubmit={e => { e.preventDefault(); onSaveToken('gitlab_token', glToken, 'GitLab'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="glpat-xxxxxxxxxxxx" value={glToken} onChange={e => setGlToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => onClearToken('gitlab_token', 'GitLab')}>Clear</button>
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
            <form onSubmit={e => { e.preventDefault(); onSaveToken('gitea_token', gtToken, 'Gitea'); }}>
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <input type="password" placeholder="Token / Personal Token" value={gtToken} onChange={e => setGtToken(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.8rem' }}>Save</button>
                <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.8rem' }} onClick={() => onClearToken('gitea_token', 'Gitea')}>Clear</button>
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
                      <button className="btn-icon btn-delete" onClick={() => onDeleteHostCredential(hc.id, hc.host)} title="Delete Credential">
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
                  <button className="btn btn-secondary btn-delete" onClick={() => onDeleteHostCredential(hc.id, hc.host)} title="Delete Credential">
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

            <form onSubmit={onSaveHostCredential}>
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
    </>
  );
}
