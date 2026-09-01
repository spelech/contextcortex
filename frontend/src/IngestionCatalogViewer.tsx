import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type {
  IngestionCatalogData,
  IngestionGitRepo,
  IngestionMonitoredPath,
  IngestionDetailedFile
} from './types';
import { useToast } from './ToastContext';

export default function IngestionCatalogViewer() {
  const toast = useToast();
  const [catalogData, setCatalogData] = useState<IngestionCatalogData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  // Filter state
  const [sourceType, setSourceType] = useState<'all' | 'git' | 'monitored_path' | 'local_storage'>('all');
  const [detailLevel, setDetailLevel] = useState<'summary' | 'detailed'>('summary');
  const [repoName, setRepoName] = useState<string>('');
  const [pathPrefix, setPathPrefix] = useState<string>('');
  const [fileExtension, setFileExtension] = useState<string>('');
  const [fileSearchFilter, setFileSearchFilter] = useState<string>('');

  const loadCatalog = useCallback(async (
    st = sourceType,
    dl = detailLevel,
    rn = repoName,
    pp = pathPrefix,
    fe = fileExtension
  ) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('source_type', st);
      params.set('detail_level', dl);
      if (rn.trim()) params.set('repo_name', rn.trim());
      if (pp.trim()) params.set('path_prefix', pp.trim());
      if (fe.trim()) params.set('file_extension', fe.trim());

      const res = await fetch(`/admin/api/ingestion/catalog?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to load ingestion catalog');
      }
      const data: IngestionCatalogData = await res.json();
      setCatalogData(data);
    } catch (e: any) {
      toast.error('Error loading catalog: ' + e.message);
      console.error('Error loading ingestion catalog:', e);
    } finally {
      setLoading(false);
    }
  }, [sourceType, detailLevel, repoName, pathPrefix, fileExtension, toast]);

  useEffect(() => {
    loadCatalog(sourceType, detailLevel, repoName, pathPrefix, fileExtension);
  }, [sourceType, detailLevel]);

  const handleApplyFilters = (e?: FormEvent) => {
    if (e) e.preventDefault();
    loadCatalog(sourceType, detailLevel, repoName, pathPrefix, fileExtension);
  };

  const handleClearFilters = () => {
    setRepoName('');
    setPathPrefix('');
    setFileExtension('');
    setFileSearchFilter('');
    loadCatalog(sourceType, detailLevel, '', '', '');
  };

  const handleSourceTypeChange = (newSource: 'all' | 'git' | 'monitored_path' | 'local_storage') => {
    setSourceType(newSource);
  };

  const handleDetailLevelChange = (newLevel: 'summary' | 'detailed') => {
    setDetailLevel(newLevel);
  };

  const formatDate = (timestamp: number | string | undefined) => {
    if (!timestamp) return '-';
    if (typeof timestamp === 'string') {
      try {
        return new Date(timestamp).toLocaleString();
      } catch {
        return timestamp;
      }
    }
    const timeMs = timestamp < 1e11 ? timestamp * 1000 : timestamp;
    return new Date(timeMs).toLocaleString();
  };

  const gitRepos = catalogData?.git_repositories || [];
  const monitoredPaths = catalogData?.monitored_paths || [];
  const localStorageInfo = catalogData?.local_storage;
  const detailedFiles = catalogData?.files || [];

  // Client-side search within detailed files
  const filteredDetailedFiles = detailedFiles.filter((f: IngestionDetailedFile) => {
    if (!fileSearchFilter.trim()) return true;
    const term = fileSearchFilter.toLowerCase();
    return (
      f.filepath.toLowerCase().includes(term) ||
      f.repo.toLowerCase().includes(term) ||
      (f.language && f.language.toLowerCase().includes(term))
    );
  });

  const totalGitFiles = gitRepos.reduce((acc, r) => acc + (r.file_count || 0), 0);
  const totalMonitoredFiles = monitoredPaths.reduce((acc, p) => acc + (p.file_count || 0), 0);
  const totalStorageFiles = localStorageInfo?.file_count || 0;
  const totalFiles = totalGitFiles + totalMonitoredFiles + totalStorageFiles;

  return (
    <div className="tab-content active">
      <div className="glass-card">
        {/* Header */}
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-book-bookmark"></i> Unified Ingestion Catalog</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Inspect all indexed Git repositories, monitored local workspaces, and uploaded local storage documents.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              className="btn btn-secondary"
              onClick={() => handleApplyFilters()}
              disabled={loading}
              title="Refresh catalog"
            >
              <i className={`fa-solid fa-arrows-rotate ${loading ? 'fa-spin' : ''}`}></i> Refresh
            </button>
          </div>
        </div>

        {/* Overview Stat Counters */}
        <div className="stats-grid" style={{ marginBottom: '20px' }}>
          <div className="stat-card">
            <div className="stat-icon"><i className="fa-brands fa-github"></i></div>
            <div className="stat-info">
              <span className="stat-label">Git Repositories</span>
              <span className="stat-value">{gitRepos.length} <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>({totalGitFiles} files)</small></span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><i className="fa-solid fa-folder-tree"></i></div>
            <div className="stat-info">
              <span className="stat-label">Monitored Paths</span>
              <span className="stat-value">{monitoredPaths.length} <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>({totalMonitoredFiles} files)</small></span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><i className="fa-solid fa-hard-drive"></i></div>
            <div className="stat-info">
              <span className="stat-label">Local Storage</span>
              <span className="stat-value">{totalStorageFiles} <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>files</small></span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><i className="fa-solid fa-database"></i></div>
            <div className="stat-info">
              <span className="stat-label">Total Cataloged Files</span>
              <span className="stat-value">{totalFiles}</span>
            </div>
          </div>
        </div>

        {/* Filter Controls Toolbar */}
        <div style={{ background: 'rgba(0, 0, 0, 0.2)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border-card)', marginBottom: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
            {/* Source Type Pills */}
            <div className="log-filter-pills" role="group" aria-label="Source Type Filters">
              <button
                className={`log-filter-btn ${sourceType === 'all' ? 'active' : ''}`}
                onClick={() => handleSourceTypeChange('all')}
              >
                <i className="fa-solid fa-layer-group"></i> All Sources
              </button>
              <button
                className={`log-filter-btn ${sourceType === 'git' ? 'active' : ''}`}
                onClick={() => handleSourceTypeChange('git')}
              >
                <i className="fa-brands fa-github"></i> Git Repositories
              </button>
              <button
                className={`log-filter-btn ${sourceType === 'monitored_path' ? 'active' : ''}`}
                onClick={() => handleSourceTypeChange('monitored_path')}
              >
                <i className="fa-solid fa-folder-tree"></i> Monitored Paths
              </button>
              <button
                className={`log-filter-btn ${sourceType === 'local_storage' ? 'active' : ''}`}
                onClick={() => handleSourceTypeChange('local_storage')}
              >
                <i className="fa-solid fa-hard-drive"></i> Local Storage
              </button>
            </div>

            {/* Detail Level Toggle */}
            <div style={{ display: 'flex', gap: '6px' }} role="group" aria-label="Detail Level Switch">
              <button
                className={`btn ${detailLevel === 'summary' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '5px 12px', fontSize: '0.8rem' }}
                onClick={() => handleDetailLevelChange('summary')}
              >
                <i className="fa-solid fa-list"></i> Summary
              </button>
              <button
                className={`btn ${detailLevel === 'detailed' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '5px 12px', fontSize: '0.8rem' }}
                onClick={() => handleDetailLevelChange('detailed')}
              >
                <i className="fa-solid fa-network-wired"></i> Detailed File Tree
              </button>
            </div>
          </div>

          {/* Form input filters */}
          <form onSubmit={handleApplyFilters}>
            <div className="form-row-3col" style={{ alignItems: 'flex-end' }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="catalog-repo-filter" style={{ fontSize: '0.8rem' }}>Repository / Alias</label>
                <input
                  id="catalog-repo-filter"
                  type="text"
                  placeholder="Filter by repo name..."
                  value={repoName}
                  onChange={(e) => setRepoName(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="catalog-prefix-filter" style={{ fontSize: '0.8rem' }}>Path Prefix</label>
                <input
                  id="catalog-prefix-filter"
                  type="text"
                  placeholder="e.g. app/api or docs/"
                  value={pathPrefix}
                  onChange={(e) => setPathPrefix(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="catalog-ext-filter" style={{ fontSize: '0.8rem' }}>File Extension</label>
                <input
                  id="catalog-ext-filter"
                  type="text"
                  placeholder="e.g. .md, .py, .ts"
                  value={fileExtension}
                  onChange={(e) => setFileExtension(e.target.value)}
                />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
              <button type="button" className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.85rem' }} onClick={handleClearFilters}>
                Clear
              </button>
              <button type="submit" className="btn btn-primary" style={{ padding: '6px 14px', fontSize: '0.85rem' }}>
                <i className="fa-solid fa-filter"></i> Apply
              </button>
            </div>
          </form>
        </div>

        {/* Section 1: Git Repositories */}
        {(sourceType === 'all' || sourceType === 'git') && (
          <div style={{ marginBottom: '28px' }}>
            <h3 style={{ fontSize: '1.05rem', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <i className="fa-brands fa-github" style={{ color: 'var(--primary)' }}></i> Git Repositories
              <span className="badge badge-primary">{gitRepos.length}</span>
            </h3>

            <div className="table-container desktop-table-view">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Branch / Commit</th>
                    <th>Status</th>
                    <th>Files</th>
                    <th>Provider</th>
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  {gitRepos.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="empty-state">No Git repositories match criteria.</td>
                    </tr>
                  ) : (
                    gitRepos.map((r: IngestionGitRepo) => (
                      <tr key={r.id}>
                        <td><strong>{r.name}</strong></td>
                        <td>
                          <code>{r.branch}</code>
                          {r.commit_sha && (
                            <span className="text-muted" style={{ marginLeft: '6px', fontSize: '0.8rem' }}>
                              @{r.commit_sha.substring(0, 7)}
                            </span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${r.status === 'synced' ? 'badge-success' : r.status === 'syncing' ? 'badge-warning' : 'badge-danger'}`}>
                            {r.status}
                          </span>
                        </td>
                        <td><strong>{r.file_count ?? 0}</strong></td>
                        <td><span className="badge badge-primary">{r.provider || 'git'}</span></td>
                        <td><span className="text-muted" style={{ fontSize: '0.82rem', wordBreak: 'break-all' }}>{r.url}</span></td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mobile-card-list">
              {gitRepos.length === 0 ? (
                <div className="empty-state">No Git repositories match criteria.</div>
              ) : (
                gitRepos.map((r: IngestionGitRepo) => (
                  <div key={`gm-${r.id}`} className="data-mobile-card">
                    <div className="data-mobile-card-header">
                      <strong>{r.name}</strong>
                      <span className={`badge ${r.status === 'synced' ? 'badge-success' : 'badge-warning'}`}>{r.status}</span>
                    </div>
                    <div className="data-mobile-card-body">
                      <div><span className="text-muted">Branch: </span><code>{r.branch}</code></div>
                      <div><span className="text-muted">Files: </span><strong>{r.file_count ?? 0}</strong></div>
                      <div><span className="text-muted">URL: </span><span style={{ wordBreak: 'break-all' }}>{r.url}</span></div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Section 2: Monitored Paths */}
        {(sourceType === 'all' || sourceType === 'monitored_path') && (
          <div style={{ marginBottom: '28px' }}>
            <h3 style={{ fontSize: '1.05rem', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <i className="fa-solid fa-folder-tree" style={{ color: '#fbbf24' }}></i> Monitored Local Paths
              <span className="badge badge-primary">{monitoredPaths.length}</span>
            </h3>

            <div className="table-container desktop-table-view">
              <table>
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Repo Alias</th>
                    <th>Category</th>
                    <th>Files Indexed</th>
                  </tr>
                </thead>
                <tbody>
                  {monitoredPaths.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="empty-state">No monitored paths match criteria.</td>
                    </tr>
                  ) : (
                    monitoredPaths.map((p: IngestionMonitoredPath, idx: number) => (
                      <tr key={`${p.path}-${idx}`}>
                        <td><code>{p.path}</code></td>
                        <td><strong>{p.repo}</strong></td>
                        <td>{p.category ? <span className="badge badge-accent">{p.category}</span> : <span className="text-muted">-</span>}</td>
                        <td><strong>{p.file_count ?? 0}</strong></td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mobile-card-list">
              {monitoredPaths.length === 0 ? (
                <div className="empty-state">No monitored paths match criteria.</div>
              ) : (
                monitoredPaths.map((p: IngestionMonitoredPath, idx: number) => (
                  <div key={`mpm-${idx}`} className="data-mobile-card">
                    <div className="data-mobile-card-header">
                      <strong>{p.repo}</strong>
                      <span className="badge badge-primary">{p.file_count ?? 0} files</span>
                    </div>
                    <div className="data-mobile-card-body">
                      <div><span className="text-muted">Path: </span><code>{p.path}</code></div>
                      {p.category && <div><span className="text-muted">Category: </span><span className="badge badge-accent">{p.category}</span></div>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Section 3: Local Storage Vault */}
        {(sourceType === 'all' || sourceType === 'local_storage') && localStorageInfo && (
          <div style={{ marginBottom: '28px' }}>
            <h3 style={{ fontSize: '1.05rem', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <i className="fa-solid fa-hard-drive" style={{ color: 'var(--accent)' }}></i> Local Storage
              <span className="badge badge-primary">{localStorageInfo.file_count} files</span>
            </h3>

            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-card)' }}>
              <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '12px' }}>
                <div>
                  <span className="text-muted" style={{ fontSize: '0.85rem' }}>Storage Root: </span>
                  <code>{localStorageInfo.root_path}</code>
                </div>
                <div>
                  <span className="text-muted" style={{ fontSize: '0.85rem' }}>Total Files: </span>
                  <strong>{localStorageInfo.file_count}</strong>
                </div>
              </div>

              {localStorageInfo.tree && (
                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  Top-level Subfolders: <strong>{localStorageInfo.tree.directories?.length || 0}</strong> &bull; Top-level Files: <strong>{localStorageInfo.tree.files?.length || 0}</strong>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Section 4: Detailed Ingested Files */}
        {detailLevel === 'detailed' && (
          <div style={{ marginTop: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
              <h3 style={{ fontSize: '1.05rem', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <i className="fa-solid fa-file-code" style={{ color: 'var(--primary)' }}></i> Ingested Files Details
                <span className="badge badge-primary">{filteredDetailedFiles.length}</span>
              </h3>

              <div className="log-search-wrapper" style={{ maxWidth: '320px' }}>
                <i className="fa-solid fa-magnifying-glass search-icon"></i>
                <input
                  type="text"
                  className="log-search-input"
                  placeholder="Search in loaded files..."
                  value={fileSearchFilter}
                  onChange={(e) => setFileSearchFilter(e.target.value)}
                />
                {fileSearchFilter && (
                  <button className="clear-search-btn" onClick={() => setFileSearchFilter('')}>&times;</button>
                )}
              </div>
            </div>

            <div className="table-container desktop-table-view">
              <table>
                <thead>
                  <tr>
                    <th>Filepath</th>
                    <th>Repository</th>
                    <th>Type</th>
                    <th>Language</th>
                    <th>Last Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDetailedFiles.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="empty-state">No detailed files match current search or filters.</td>
                    </tr>
                  ) : (
                    filteredDetailedFiles.map((f: IngestionDetailedFile, idx: number) => (
                      <tr key={`${f.filepath}-${idx}`}>
                        <td><code style={{ wordBreak: 'break-all' }}>{f.filepath}</code></td>
                        <td><strong>{f.repo}</strong></td>
                        <td><span className="badge badge-primary">{f.doc_type}</span></td>
                        <td><span className="badge badge-accent">{f.language || 'text'}</span></td>
                        <td style={{ fontSize: '0.85rem' }}>{formatDate(f.mtime)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mobile-card-list">
              {filteredDetailedFiles.length === 0 ? (
                <div className="empty-state">No detailed files match current search or filters.</div>
              ) : (
                filteredDetailedFiles.map((f: IngestionDetailedFile, idx: number) => (
                  <div key={`dfm-${idx}`} className="data-mobile-card">
                    <div className="data-mobile-card-header">
                      <strong>{f.repo}</strong>
                      <span className="badge badge-accent">{f.language || 'text'}</span>
                    </div>
                    <div className="data-mobile-card-body">
                      <div>
                        <span className="text-muted">Path: </span>
                        <code style={{ wordBreak: 'break-all' }}>{f.filepath}</code>
                      </div>
                      <div>
                        <span className="text-muted">Type: </span>
                        <span className="badge badge-primary">{f.doc_type}</span>
                      </div>
                      <div>
                        <span className="text-muted">Modified: </span>
                        <span>{formatDate(f.mtime)}</span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
