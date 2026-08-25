import type { Repo } from '../../types';

interface RepoListTableProps {
  repos: Repo[];
  onSync: (id: number) => void;
  onToggleAutoSync: (id: number, current: boolean) => void;
  onOpenWebhook: (repo: Repo) => void;
  onDelete: (id: number, name: string) => void;
}

export function RepoListTable({
  repos,
  onSync,
  onToggleAutoSync,
  onOpenWebhook,
  onDelete,
}: RepoListTableProps) {
  const getProviderIcon = (prov?: string) => {
    const p = (prov || 'github').toLowerCase();
    if (p === 'gitlab') return <i className="fa-brands fa-gitlab" style={{ color: '#fc6d26', marginRight: '6px' }} title="GitLab" />;
    if (p === 'gitea' || p === 'forgejo') return <i className="fa-solid fa-mug-hot" style={{ color: '#609926', marginRight: '6px' }} title="Gitea / Forgejo" />;
    if (p === 'bitbucket') return <i className="fa-brands fa-bitbucket" style={{ color: '#2684ff', marginRight: '6px' }} title="Bitbucket" />;
    if (p === 'generic') return <i className="fa-solid fa-code-branch" style={{ color: 'var(--accent)', marginRight: '6px' }} title="Generic Git" />;
    return <i className="fa-brands fa-github" style={{ marginRight: '6px' }} title="GitHub" />;
  };

  return (
    <>
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
                <td colSpan={9} className="empty-state">
                  No Git repositories registered. Click "Add Repository" to index a remote repo.
                </td>
              </tr>
            ) : (
              repos.map((r) => {
                const isAutoSync = r.auto_sync !== false && r.auto_sync !== 0;
                return (
                  <tr key={r.id}>
                    <td>
                      {getProviderIcon(r.provider)}
                      <strong>{r.name}</strong>
                    </td>
                    <td>
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: 'var(--primary)', textDecoration: 'none', fontSize: '0.85rem' }}
                      >
                        <i className="fa-solid fa-arrow-up-right-from-square"></i> {r.url}
                      </a>
                    </td>
                    <td>
                      <code>{r.branch}</code>
                    </td>
                    <td>
                      {r.commit_sha ? (
                        <code>{r.commit_sha.substring(0, 8)}</code>
                      ) : (
                        <span className="text-muted">-</span>
                      )}
                    </td>
                    <td>
                      {r.status === 'syncing' ? (
                        <span className="badge badge-warning">
                          <i className="fa-solid fa-spinner fa-spin"></i> Syncing
                        </span>
                      ) : r.status === 'error' ? (
                        <div>
                          <span className="badge badge-danger" title={r.last_error || 'Sync failed'}>
                            <i className="fa-solid fa-circle-exclamation"></i> Error
                          </span>
                          {r.last_error && (
                            <div
                              style={{
                                fontSize: '0.75rem',
                                color: 'var(--danger)',
                                marginTop: '4px',
                                maxWidth: '180px',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={r.last_error}
                            >
                              {r.last_error}
                            </div>
                          )}
                        </div>
                      ) : r.status === 'pending' ? (
                        <span className="badge badge-primary">
                          <i className="fa-solid fa-clock"></i> Pending
                        </span>
                      ) : (
                        <span className="badge badge-success">
                          <i className="fa-solid fa-check"></i> Synced
                        </span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`badge ${isAutoSync ? 'badge-success' : 'badge-danger'}`}
                        style={{
                          cursor: 'pointer',
                          background: isAutoSync ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                          border: isAutoSync
                            ? '1px solid rgba(16, 185, 129, 0.4)'
                            : '1px solid rgba(239, 68, 68, 0.4)',
                          color: isAutoSync ? '#6ee7b7' : '#fca5a5',
                          padding: '4px 8px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                        onClick={() => onToggleAutoSync(r.id, isAutoSync)}
                        title={`Auto-Sync: ${isAutoSync ? 'ON' : 'OFF'} (Click to toggle)`}
                        aria-label={`Toggle auto-sync for ${r.name}`}
                      >
                        <i className={`fa-solid ${isAutoSync ? 'fa-toggle-on' : 'fa-toggle-off'}`}></i>
                        Auto-Sync: {isAutoSync ? 'ON' : 'OFF'}
                      </button>
                    </td>
                    <td>{(r.file_count || 0).toLocaleString()} files</td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {r.last_synced || 'Never'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          className="btn btn-secondary"
                          style={{ padding: '4px 8px', fontSize: '0.8rem' }}
                          onClick={() => onSync(r.id)}
                          title="Trigger Sync"
                        >
                          <i className="fa-solid fa-arrows-rotate"></i> Sync
                        </button>
                        <button
                          className="btn btn-secondary"
                          style={{ padding: '4px 8px', fontSize: '0.8rem' }}
                          onClick={() => onOpenWebhook(r)}
                          title="Webhook Setup"
                        >
                          <i className="fa-solid fa-bolt"></i> Webhook
                        </button>
                        <button
                          className="btn-icon btn-delete"
                          onClick={() => onDelete(r.id, r.name)}
                          title="Delete Repo"
                        >
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
          <div className="empty-state">
            No Git repositories registered. Click "Add Repository" to index a remote repo.
          </div>
        ) : (
          repos.map((r) => {
            const isAutoSync = r.auto_sync !== false && r.auto_sync !== 0;
            return (
              <div key={`card-${r.id}`} className="data-mobile-card">
                <div className="data-mobile-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {getProviderIcon(r.provider)}
                    <strong style={{ fontSize: '1rem' }}>{r.name}</strong>
                  </div>
                  {r.status === 'syncing' ? (
                    <span className="badge badge-warning">
                      <i className="fa-solid fa-spinner fa-spin"></i> Syncing
                    </span>
                  ) : r.status === 'error' ? (
                    <span className="badge badge-danger" title={r.last_error || 'Sync failed'}>
                      <i className="fa-solid fa-circle-exclamation"></i> Error
                    </span>
                  ) : r.status === 'pending' ? (
                    <span className="badge badge-primary">
                      <i className="fa-solid fa-clock"></i> Pending
                    </span>
                  ) : (
                    <span className="badge badge-success">
                      <i className="fa-solid fa-check"></i> Synced
                    </span>
                  )}
                </div>

                <div className="data-mobile-card-body">
                  <div>
                    <span className="data-label">URL:</span>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: 'var(--primary)', textDecoration: 'none' }}
                    >
                      {r.url}
                    </a>
                  </div>
                  <div>
                    <span className="data-label">Branch:</span>
                    <code>{r.branch}</code>
                  </div>
                  <div>
                    <span className="data-label">Commit:</span>
                    {r.commit_sha ? <code>{r.commit_sha.substring(0, 8)}</code> : '-'}
                  </div>
                  <div>
                    <span className="data-label">Auto-Sync:</span>
                    <button
                      type="button"
                      className={`badge ${isAutoSync ? 'badge-success' : 'badge-danger'}`}
                      style={{ cursor: 'pointer', padding: '2px 6px', fontSize: '0.75rem' }}
                      onClick={() => onToggleAutoSync(r.id, isAutoSync)}
                    >
                      {isAutoSync ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <div>
                    <span className="data-label">Files:</span>
                    {(r.file_count || 0).toLocaleString()}
                  </div>
                  <div>
                    <span className="data-label">Last Synced:</span>
                    {r.last_synced || 'Never'}
                  </div>
                  {r.last_error && (
                    <div style={{ color: 'var(--danger)', fontSize: '0.75rem' }}>
                      <span className="data-label">Error:</span>
                      {r.last_error}
                    </div>
                  )}
                </div>

                <div className="data-mobile-card-actions">
                  <button
                    className="btn btn-secondary"
                    onClick={() => onSync(r.id)}
                    title="Trigger Sync"
                  >
                    <i className="fa-solid fa-arrows-rotate"></i> Sync
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => onOpenWebhook(r)}
                    title="Webhook Setup"
                  >
                    <i className="fa-solid fa-bolt"></i> Webhook
                  </button>
                  <button
                    className="btn btn-secondary btn-delete"
                    onClick={() => onDelete(r.id, r.name)}
                    title="Delete Repo"
                  >
                    <i className="fa-solid fa-trash-can"></i> Delete
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
