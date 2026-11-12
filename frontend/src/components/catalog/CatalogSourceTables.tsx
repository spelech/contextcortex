import React from 'react';
import type {
  IngestionGitRepo,
  IngestionMonitoredPath,
  IngestionLocalStorage,
  IngestionDetailedFile,
} from '../../types';
import type { CatalogSourceType, CatalogDetailLevel } from './CatalogFilterBar';
import { formatLanguageLabel, resolveLanguageDescriptor } from '../navigator/syntaxSemantics';

export interface CatalogSourceTablesProps {
  sourceType: CatalogSourceType;
  detailLevel: CatalogDetailLevel;
  gitRepos: IngestionGitRepo[];
  monitoredPaths: IngestionMonitoredPath[];
  localStorageInfo?: IngestionLocalStorage | null;
  filteredDetailedFiles: IngestionDetailedFile[];
  fileSearchFilter: string;
  onFileSearchFilterChange: (value: string) => void;
}

function formatCatalogDate(timestamp: number | string | undefined): string {
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
}

export const CatalogSourceTables: React.FC<CatalogSourceTablesProps> = ({
  sourceType,
  detailLevel,
  gitRepos,
  monitoredPaths,
  localStorageInfo,
  filteredDetailedFiles,
  fileSearchFilter,
  onFileSearchFilterChange,
}) => {
  return (
    <>
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
                onChange={(e) => onFileSearchFilterChange(e.target.value)}
              />
              {fileSearchFilter && (
                <button type="button" className="clear-search-btn" onClick={() => onFileSearchFilterChange('')}>
                  &times;
                </button>
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
                  filteredDetailedFiles.map((f: IngestionDetailedFile, idx: number) => {
                    const langDesc = resolveLanguageDescriptor(f.language, f.filepath);
                    const langLabel = formatLanguageLabel(f.language, f.filepath);
                    return (
                      <tr key={`${f.filepath}-${idx}`}>
                        <td><code style={{ wordBreak: 'break-all' }}>{f.filepath}</code></td>
                        <td><strong>{f.repo}</strong></td>
                        <td><span className="badge badge-primary">{f.doc_type}</span></td>
                        <td>
                          <span className={`badge badge-accent ${langDesc ? langDesc.badgeClass : ''}`}>
                            {langLabel}
                          </span>
                        </td>
                        <td style={{ fontSize: '0.85rem' }}>{formatCatalogDate(f.mtime)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="mobile-card-list">
            {filteredDetailedFiles.length === 0 ? (
              <div className="empty-state">No detailed files match current search or filters.</div>
            ) : (
              filteredDetailedFiles.map((f: IngestionDetailedFile, idx: number) => {
                const langDesc = resolveLanguageDescriptor(f.language, f.filepath);
                const langLabel = formatLanguageLabel(f.language, f.filepath);
                return (
                  <div key={`dfm-${idx}`} className="data-mobile-card">
                    <div className="data-mobile-card-header">
                      <strong>{f.repo}</strong>
                      <span className={`badge badge-accent ${langDesc ? langDesc.badgeClass : ''}`}>
                        {langLabel}
                      </span>
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
                        <span>{formatCatalogDate(f.mtime)}</span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </>
  );
};
