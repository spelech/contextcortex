import type {
  StorageTreeData,
  StorageFileItem,
  StorageDirectoryItem,
} from '../../types';
import { formatStorageBytes, formatStorageDate } from './storageFormatters';

interface StorageBrowserPanelProps {
  treeData: StorageTreeData | null;
  currentFolder: string;
  onNavigateFolder: (folderPath: string) => void;
  onNavigateParent: () => void;
  onPreviewFile: (file: StorageFileItem) => void;
  onReplaceFile: (file: StorageFileItem) => void;
  onDeleteFile: (file: StorageFileItem) => void;
}

export function StorageBrowserPanel({
  treeData,
  currentFolder,
  onNavigateFolder,
  onNavigateParent,
  onPreviewFile,
  onReplaceFile,
  onDeleteFile,
}: StorageBrowserPanelProps) {
  const folderSegments = currentFolder ? currentFolder.split('/').filter(Boolean) : [];
  const isEmpty = !treeData || (treeData.directories.length === 0 && treeData.files.length === 0);

  return (
    <>
      <div
        className="browser-breadcrumbs"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <span className="label" style={{ fontWeight: 600 }}>Location:</span>
          <button
            className="btn-icon"
            style={{ padding: '2px 6px', fontSize: '0.85rem', color: currentFolder === '' ? 'var(--primary)' : 'var(--text)' }}
            onClick={() => onNavigateFolder('')}
          >
            <i className="fa-solid fa-house"></i> root
          </button>
          {folderSegments.map((seg, idx) => {
            const subPath = folderSegments.slice(0, idx + 1).join('/');
            const isLast = idx === folderSegments.length - 1;
            return (
              <span key={subPath} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                <span className="text-muted">/</span>
                <button
                  className="btn-icon"
                  style={{
                    padding: '2px 6px',
                    fontSize: '0.85rem',
                    fontWeight: isLast ? 'bold' : 'normal',
                    color: isLast ? 'var(--primary)' : 'var(--text)',
                  }}
                  onClick={() => onNavigateFolder(subPath)}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </div>

        <div style={{ display: 'flex', gap: '8px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          <span>Directories: <strong>{treeData?.directories.length || 0}</strong></span>
          <span>&bull;</span>
          <span>Files: <strong>{treeData?.files.length || 0}</strong></span>
        </div>
      </div>

      {currentFolder !== '' && (
        <div style={{ marginTop: '8px', marginBottom: '8px' }}>
          <button
            className="btn btn-secondary"
            style={{ padding: '4px 10px', fontSize: '0.82rem' }}
            onClick={onNavigateParent}
          >
            <i className="fa-solid fa-level-up-alt"></i> .. (Parent Directory)
          </button>
        </div>
      )}

      <div className="table-container desktop-table-view">
        <table>
          <thead>
            <tr>
              <th style={{ width: '40%' }}>Name</th>
              <th>Path</th>
              <th>Size</th>
              <th>Modified</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isEmpty ? (
              <tr>
                <td colSpan={5} className="empty-state">
                  No files or subdirectories found in this storage directory. Click "Upload File" to add documents.
                </td>
              </tr>
            ) : (
              <>
                {treeData!.directories.map((d: StorageDirectoryItem) => (
                  <tr key={d.rel_path}>
                    <td>
                      <button
                        className="btn-icon"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', textAlign: 'left', color: 'var(--text)' }}
                        onClick={() => onNavigateFolder(d.rel_path)}
                        aria-label={`open ${d.name}`}
                      >
                        <i className="fa-solid fa-folder" style={{ color: '#fbbf24', fontSize: '1.05rem' }}></i>
                        <strong>{d.name}</strong>
                      </button>
                    </td>
                    <td><code>{d.rel_path}</code></td>
                    <td><span className="text-muted">-</span></td>
                    <td><span className="text-muted">-</span></td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '3px 8px', fontSize: '0.8rem' }}
                        onClick={() => onNavigateFolder(d.rel_path)}
                        title={`Open ${d.name}`}
                        aria-label={`open ${d.name}`}
                      >
                        <i className="fa-solid fa-folder-open"></i> Open
                      </button>
                    </td>
                  </tr>
                ))}

                {treeData!.files.map((f: StorageFileItem) => {
                  const isPdf = f.name.toLowerCase().endsWith('.pdf');
                  return (
                    <tr key={f.rel_path}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {isPdf ? (
                            <i className="fa-solid fa-file-pdf text-red-500 mr-2" style={{ color: '#ef4444', fontSize: '1.05rem' }}></i>
                          ) : (
                            <i className="fa-solid fa-file-lines" style={{ color: 'var(--primary)', fontSize: '1.05rem' }}></i>
                          )}
                          <span>{f.name}</span>
                        </div>
                      </td>
                      <td><code>{f.rel_path}</code></td>
                      <td><span className="badge badge-primary">{formatStorageBytes(f.size_bytes)}</span></td>
                      <td style={{ fontSize: '0.85rem' }}>{formatStorageDate(f.mtime)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '6px' }}>
                          <button className="btn-icon" onClick={() => onPreviewFile(f)} title="Preview File" aria-label="Preview File">
                            <i className="fa-solid fa-eye"></i>
                          </button>
                          <button className="btn-icon" onClick={() => onReplaceFile(f)} title="Replace File" aria-label="Replace File">
                            <i className="fa-solid fa-file-pen"></i>
                          </button>
                          <button className="btn-icon btn-delete" onClick={() => onDeleteFile(f)} title="Delete File" aria-label="Delete File">
                            <i className="fa-solid fa-trash-can"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </>
            )}
          </tbody>
        </table>
      </div>

      <div className="mobile-card-list">
        {isEmpty ? (
          <div className="empty-state">No files or subdirectories found.</div>
        ) : (
          <>
            {treeData!.directories.map((d: StorageDirectoryItem) => (
              <div key={`m-${d.rel_path}`} className="data-mobile-card">
                <div className="data-mobile-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <i className="fa-solid fa-folder" style={{ color: '#fbbf24' }}></i>
                    <strong>{d.name}</strong>
                  </div>
                  <span className="badge badge-warning">Directory</span>
                </div>
                <div className="data-mobile-card-body">
                  <div><span className="text-muted">Path: </span><code>{d.rel_path}</code></div>
                </div>
                <div className="data-mobile-card-actions">
                  <button className="btn btn-secondary" onClick={() => onNavigateFolder(d.rel_path)} aria-label={`open ${d.name}`}>
                    <i className="fa-solid fa-folder-open"></i> Open Folder
                  </button>
                </div>
              </div>
            ))}

            {treeData!.files.map((f: StorageFileItem) => {
              const isPdf = f.name.toLowerCase().endsWith('.pdf');
              return (
                <div key={`m-${f.rel_path}`} className="data-mobile-card">
                  <div className="data-mobile-card-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {isPdf ? (
                        <i className="fa-solid fa-file-pdf text-red-500 mr-2" style={{ color: '#ef4444' }}></i>
                      ) : (
                        <i className="fa-solid fa-file-lines" style={{ color: 'var(--primary)' }}></i>
                      )}
                      <strong>{f.name}</strong>
                    </div>
                    <span className="badge badge-primary">{formatStorageBytes(f.size_bytes)}</span>
                  </div>
                  <div className="data-mobile-card-body">
                    <div><span className="text-muted">Path: </span><code>{f.rel_path}</code></div>
                    <div><span className="text-muted">Modified: </span><span>{formatStorageDate(f.mtime)}</span></div>
                  </div>
                  <div className="data-mobile-card-actions">
                    <button className="btn btn-secondary" onClick={() => onPreviewFile(f)} title="Preview File">
                      <i className="fa-solid fa-eye"></i> Preview
                    </button>
                    <button className="btn btn-secondary" onClick={() => onReplaceFile(f)} title="Replace File">
                      <i className="fa-solid fa-file-pen"></i> Replace
                    </button>
                    <button className="btn btn-secondary btn-delete" onClick={() => onDeleteFile(f)} title="Delete File">
                      <i className="fa-solid fa-trash-can"></i> Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </>
  );
}
