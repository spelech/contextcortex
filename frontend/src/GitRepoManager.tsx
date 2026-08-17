import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Repo } from './types';
import { useToast } from './ToastContext';

export default function GitRepoManager({ refreshStats }: { refreshStats: () => void }) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const toast = useToast();
  
  // Modal state
  const [alias, setAlias] = useState('');
  const [url, setUrl] = useState('');
  const [branch, setBranch] = useState('main');
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
        body: JSON.stringify({ name: alias.trim(), url: url.trim(), branch: branch.trim() || 'main', auth_token: token.trim() || null })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to add repository');

      setIsModalOpen(false);
      setAlias('');
      setUrl('');
      setBranch('main');
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

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-brands fa-github"></i> Registered Git Repositories</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>Repositories are shallow-cloned, parsed into AST chunks, and immediately pruned from disk.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Repository
          </button>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Repo Alias</th>
                <th>Git URL</th>
                <th>Branch</th>
                <th>Commit SHA</th>
                <th>Status</th>
                <th>Files</th>
                <th>Last Synced</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {repos.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-state">No Git repositories registered. Click "Add Repository" to index a remote repo.</td>
                </tr>
              ) : (
                repos.map(r => (
                  <tr key={r.id}>
                    <td><strong>{r.name}</strong></td>
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
                    <td>{(r.file_count || 0).toLocaleString()} files</td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{r.last_synced || 'Never'}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.8rem' }} onClick={() => syncRepo(r.id)} title="Trigger Sync">
                          <i className="fa-solid fa-arrows-rotate"></i> Sync
                        </button>
                        <button className="btn-icon btn-delete" onClick={() => deleteRepo(r.id, r.name)} title="Delete Repo">
                          <i className="fa-solid fa-trash-can"></i>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {isModalOpen && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card">
            <div className="modal-header">
              <h2><i className="fa-brands fa-github"></i> Register Git Repository</h2>
              <button className="btn-close" onClick={() => setIsModalOpen(false)}>&times;</button>
            </div>
            
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label htmlFor="repo-alias">Repository Alias / Identifier</label>
                <input type="text" id="repo-alias" required placeholder="e.g. backend-api or notes-rag-mcp" value={alias} onChange={e => setAlias(e.target.value)} />
              </div>

              <div className="form-group">
                <label htmlFor="repo-url">Git Clone URL (HTTPS)</label>
                <input type="url" id="repo-url" required placeholder="https://github.com/owner/repository.git" value={url} onChange={e => setUrl(e.target.value)} />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="repo-branch">Branch / Tag</label>
                  <input type="text" id="repo-branch" placeholder="main" value={branch} onChange={e => setBranch(e.target.value)} />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-token">Per-Repo Auth Token (Optional)</label>
                  <input type="password" id="repo-token" placeholder="Optional token override" value={token} onChange={e => setToken(e.target.value)} />
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
    </div>
  );
}
