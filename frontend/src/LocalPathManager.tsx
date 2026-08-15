import { useState, useEffect } from 'react';
import type { FormEvent } from 'react';
import type { LocalPath, BrowseData } from './types';

export default function LocalPathManager({ refreshStats }: { refreshStats: () => void }) {
  const [paths, setPaths] = useState<LocalPath[]>([]);
  const [isPathModalOpen, setIsPathModalOpen] = useState(false);
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);
  
  // Path modal state
  const [selectedPath, setSelectedPath] = useState('');
  const [repoAlias, setRepoAlias] = useState('local');
  const [category, setCategory] = useState('');
  const [pathType, setPathType] = useState('directory');
  const [recursive, setRecursive] = useState(1);

  // Browser state
  const [browseData, setBrowseData] = useState<BrowseData | null>(null);

  const loadPaths = async () => {
    try {
      const response = await fetch('/admin/api/paths');
      if (!response.ok) return;
      const data = await response.json();
      setPaths(data);
    } catch (e) {
      console.error('Error loading paths:', e);
    }
  };

  useEffect(() => {
    loadPaths();
    const interval = setInterval(loadPaths, 8000);
    return () => clearInterval(interval);
  }, []);

  const handleSavePath = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/admin/api/paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          path: selectedPath.trim(), 
          repo: repoAlias.trim() || 'local', 
          category: category.trim() || null, 
          type: pathType, 
          recursive, 
          enabled: 1 
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to add path');

      setIsPathModalOpen(false);
      setSelectedPath('');
      setRepoAlias('local');
      setCategory('');
      setPathType('directory');
      setRecursive(1);
      
      loadPaths();
      refreshStats();
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  };

  const deletePath = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this local search path?')) return;
    try {
      await fetch(`/admin/api/paths/${id}`, { method: 'DELETE' });
      loadPaths();
      refreshStats();
    } catch (e: any) {
      alert('Failed to delete path: ' + e.message);
    }
  };

  const openBrowser = (path: string = '/') => {
    setIsBrowserOpen(true);
    browseDir(path);
  };

  const browseDir = async (path: string) => {
    try {
      const res = await fetch(`/admin/api/browse?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (!res.ok) return;
      setBrowseData(data);
    } catch (e) {
      console.error('Browse error:', e);
    }
  };

  const selectBrowserPath = () => {
    if (browseData) {
      setSelectedPath(browseData.current_path);
      setPathType('directory');
      setIsBrowserOpen(false);
    }
  };

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-folder-tree"></i> Monitored Local Paths</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>Mounted documentation vaults and local workspaces scanned for changes.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsPathModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Local Path
          </button>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Path</th>
                <th>Repo Alias</th>
                <th>Type</th>
                <th>Recursive</th>
                <th>Category</th>
                <th>Enabled</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paths.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty-state">No local search paths configured.</td>
                </tr>
              ) : (
                paths.map(p => (
                  <tr key={p.id}>
                    <td><code>{p.path}</code></td>
                    <td><strong>{p.repo || 'local'}</strong></td>
                    <td><span className="badge badge-primary">{p.type}</span></td>
                    <td>{p.recursive ? 'Yes' : 'No'}</td>
                    <td>{p.category ? <span className="badge badge-accent">{p.category}</span> : <span className="text-muted">-</span>}</td>
                    <td>{p.enabled ? <span className="badge badge-success">Enabled</span> : <span className="badge badge-danger">Disabled</span>}</td>
                    <td>
                      <button className="btn-icon btn-delete" onClick={() => deletePath(p.id)}>
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

      {isPathModalOpen && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card">
            <div className="modal-header">
              <h2><i className="fa-solid fa-folder-open"></i> Add Monitored Local Path</h2>
              <button className="btn-close" onClick={() => setIsPathModalOpen(false)}>&times;</button>
            </div>
            
            <form onSubmit={handleSavePath}>
              <div className="form-group">
                <label>Selected Directory / File</label>
                <div className="path-input-row">
                  <input type="text" readOnly required placeholder="Browse workspace directories..." value={selectedPath} />
                  <button type="button" className="btn btn-secondary" onClick={() => openBrowser(browseData?.current_path || '/')}><i className="fa-solid fa-magnifying-glass"></i> Browse</button>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="path-repo-alias">Repo / Vault Alias</label>
                  <input type="text" id="path-repo-alias" placeholder="local" value={repoAlias} onChange={e => setRepoAlias(e.target.value)} />
                </div>
                <div className="form-group">
                  <label htmlFor="path-category">Category Override</label>
                  <input type="text" id="path-category" placeholder="Optional category" value={category} onChange={e => setCategory(e.target.value)} />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="path-type">Path Type</label>
                  <select id="path-type" value={pathType} onChange={e => setPathType(e.target.value)}>
                    <option value="directory">Directory</option>
                    <option value="file">Single File</option>
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="path-recursive">Scan Subfolders</label>
                  <select id="path-recursive" value={recursive} onChange={e => setRecursive(parseInt(e.target.value))}>
                    <option value={1}>Yes (Recursive)</option>
                    <option value={0}>No (Top-level only)</option>
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsPathModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">Save Path</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isBrowserOpen && browseData && (
        <div className="modal-backdrop" style={{ zIndex: 1100 }}>
          <div className="glass-card modal-card browser-card">
            <div className="modal-header">
              <h2><i className="fa-solid fa-search"></i> Browse Workspace Files</h2>
              <button className="btn-close" onClick={() => setIsBrowserOpen(false)}>&times;</button>
            </div>
            
            <div className="browser-body">
              <div className="browser-breadcrumbs">
                <span className="label">Current:</span>
                <span className="code">{browseData.current_path}</span>
              </div>
              <div className="browser-list-container">
                <ul className="browser-list">
                  {browseData.parent_path && (
                    <li className="browser-item" onClick={() => browseDir(browseData.parent_path as string)}>
                      <i className="fa-solid fa-level-up-alt" style={{ color: 'var(--accent)' }}></i> <span>.. (Parent Directory)</span>
                    </li>
                  )}
                  {browseData.directories.map(d => (
                    <li key={d.path} className="browser-item" onClick={() => browseDir(d.path)}>
                      <i className="fa-solid fa-folder" style={{ color: '#fbbf24' }}></i> <span>{d.name}</span>
                    </li>
                  ))}
                  {browseData.files.map(f => (
                    <li key={f.path} className="browser-item" onClick={() => {
                      setSelectedPath(f.path);
                      setPathType('file');
                      setIsBrowserOpen(false);
                    }}>
                      <i className="fa-solid fa-file-code" style={{ color: 'var(--text-muted)' }}></i> <span>{f.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setIsBrowserOpen(false)}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={selectBrowserPath}>Select Current Folder</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
