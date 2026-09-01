import { useState, useEffect, useCallback } from 'react';
import type { FormEvent, DragEvent, ChangeEvent } from 'react';
import type {
  StorageTreeData,
  StorageFileItem,
  StorageDirectoryItem,
  StorageFileContent
} from './types';
import { useToast } from './ToastContext';

interface LocalStorageManagerProps {
  refreshStats?: () => void;
}

export default function LocalStorageManager({ refreshStats }: LocalStorageManagerProps) {
  const toast = useToast();
  const [treeData, setTreeData] = useState<StorageTreeData | null>(null);
  const [currentFolder, setCurrentFolder] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  // Upload modal state
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadPath, setUploadPath] = useState('');
  const [uploadCategory, setUploadCategory] = useState('');
  const [uploadRepo, setUploadRepo] = useState('local_storage');
  const [uploadContent, setUploadContent] = useState('');
  const [selectedFileObj, setSelectedFileObj] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  // Preview modal state
  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false);
  const [previewData, setPreviewData] = useState<StorageFileContent | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);

  // Replace modal state
  const [isReplaceModalOpen, setIsReplaceModalOpen] = useState(false);
  const [replaceTargetFile, setReplaceTargetFile] = useState<StorageFileItem | null>(null);
  const [replaceContent, setReplaceContent] = useState('');
  const [replaceCategory, setReplaceCategory] = useState('');
  const [isReplacing, setIsReplacing] = useState(false);

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatDate = (timestamp: number) => {
    if (!timestamp) return '-';
    // If timestamp is in seconds, convert to ms
    const timeMs = timestamp < 1e11 ? timestamp * 1000 : timestamp;
    return new Date(timeMs).toLocaleString();
  };

  const loadTree = useCallback(async (folder: string = currentFolder) => {
    setLoading(true);
    try {
      const url = folder
        ? `/admin/api/storage/tree?folder=${encodeURIComponent(folder)}`
        : '/admin/api/storage/tree';
      const res = await fetch(url);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to load storage tree');
      }
      const data: StorageTreeData = await res.json();
      setTreeData(data);
      setCurrentFolder(data.current_folder || '');
    } catch (e: any) {
      toast.error('Error loading storage: ' + e.message);
      console.error('Error loading storage tree:', e);
    } finally {
      setLoading(false);
    }
  }, [currentFolder, toast]);

  useEffect(() => {
    loadTree('');
  }, []);

  const navigateToFolder = (folderPath: string) => {
    loadTree(folderPath);
  };

  const navigateToParent = () => {
    if (!currentFolder) return;
    const parts = currentFolder.split('/').filter(Boolean);
    parts.pop();
    navigateToFolder(parts.join('/'));
  };

  const openUploadModal = (folderPrefix?: string) => {
    const base = folderPrefix !== undefined ? folderPrefix : currentFolder;
    setUploadPath(base ? `${base}/` : '');
    setUploadCategory('');
    setUploadRepo('local_storage');
    setUploadContent('');
    setSelectedFileObj(null);
    setIsUploadModalOpen(true);
  };

  const handleFileDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      handleSelectedFile(file);
    }
  };

  const handleFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleSelectedFile(e.target.files[0]);
    }
  };

  const handleSelectedFile = (file: File) => {
    setSelectedFileObj(file);
    const target = currentFolder ? `${currentFolder}/${file.name}` : file.name;
    setUploadPath(target);

    // Read text preview into uploadContent if file is text/readable
    const reader = new FileReader();
    reader.onload = (event) => {
      if (typeof event.target?.result === 'string') {
        setUploadContent(event.target.result);
      }
    };
    reader.readAsText(file);
  };

  const handleSaveUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!uploadPath.trim()) {
      toast.error('File path is required');
      return;
    }

    setIsUploading(true);
    try {
      let res: Response;
      if (selectedFileObj && !uploadContent) {
        const formData = new FormData();
        formData.append('file', selectedFileObj);
        formData.append('path', uploadPath.trim());
        formData.append('repo', uploadRepo.trim() || 'local_storage');
        if (uploadCategory.trim()) {
          formData.append('category', uploadCategory.trim());
        }
        res = await fetch('/admin/api/storage/upload', {
          method: 'POST',
          body: formData
        });
      } else {
        res = await fetch('/admin/api/storage/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: uploadPath.trim(),
            content: uploadContent,
            repo: uploadRepo.trim() || 'local_storage',
            category: uploadCategory.trim() || null
          })
        });
      }

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to upload file');
      }

      setIsUploadModalOpen(false);
      const chunksIndexed = data.chunks_indexed ?? 0;
      toast.success(`File uploaded and indexed (${chunksIndexed} chunks)`);
      loadTree(currentFolder);
      if (refreshStats) refreshStats();
    } catch (err: any) {
      toast.error(`Upload error: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const openPreviewModal = async (file: StorageFileItem) => {
    setIsPreviewLoading(true);
    setIsPreviewModalOpen(true);
    try {
      const res = await fetch(`/admin/api/storage/file?path=${encodeURIComponent(file.rel_path)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to read file');
      setPreviewData(data);
    } catch (err: any) {
      toast.error(`Preview error: ${err.message}`);
      setIsPreviewModalOpen(false);
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const openReplaceModal = async (file: StorageFileItem) => {
    setReplaceTargetFile(file);
    setReplaceCategory('');
    setIsReplaceModalOpen(true);
    try {
      const res = await fetch(`/admin/api/storage/file?path=${encodeURIComponent(file.rel_path)}`);
      const data = await res.json();
      if (res.ok && data.content !== undefined) {
        setReplaceContent(data.content);
      } else {
        setReplaceContent('');
      }
    } catch {
      setReplaceContent('');
    }
  };

  const handleSaveReplace = async (e: FormEvent) => {
    e.preventDefault();
    if (!replaceTargetFile) return;

    setIsReplacing(true);
    try {
      const res = await fetch('/admin/api/storage/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: replaceTargetFile.rel_path,
          content: replaceContent,
          repo: 'local_storage',
          category: replaceCategory.trim() || ''
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to update file');

      setIsReplaceModalOpen(false);
      const chunks = data.chunks_indexed ?? 0;
      toast.success(`File updated and indexed (${chunks} chunks)`);
      loadTree(currentFolder);
      if (refreshStats) refreshStats();
    } catch (err: any) {
      toast.error(`Replace error: ${err.message}`);
    } finally {
      setIsReplacing(false);
    }
  };

  const handleDeleteFile = async (file: StorageFileItem) => {
    if (!window.confirm(`Are you sure you want to delete '${file.name}' from local storage and purge its vector embeddings?`)) {
      return;
    }

    try {
      const res = await fetch(`/admin/api/storage/file?path=${encodeURIComponent(file.rel_path)}`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to delete file');

      toast.success(`File deleted successfully: ${file.name}`);
      loadTree(currentFolder);
      if (refreshStats) refreshStats();
    } catch (err: any) {
      toast.error(`Delete error: ${err.message}`);
    }
  };

  // Breadcrumb segment helper
  const folderSegments = currentFolder ? currentFolder.split('/').filter(Boolean) : [];

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-hard-drive"></i> Local Storage Explorer</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Upload, browse, inspect, replace, and delete managed documents in ContextCortex local storage with real-time vector indexing.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button className="btn btn-secondary" onClick={() => loadTree(currentFolder)} title="Refresh directory" disabled={loading}>
              <i className={`fa-solid fa-arrows-rotate ${loading ? 'fa-spin' : ''}`}></i> Refresh
            </button>
            <button className="btn btn-primary" onClick={() => openUploadModal()}>
              <i className="fa-solid fa-upload"></i> Upload File
            </button>
          </div>
        </div>

        {/* Breadcrumb path toolbar */}
        <div className="browser-breadcrumbs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <span className="label" style={{ fontWeight: 600 }}>Location:</span>
            <button
              className="btn-icon"
              style={{ padding: '2px 6px', fontSize: '0.85rem', color: currentFolder === '' ? 'var(--primary)' : 'var(--text)' }}
              onClick={() => navigateToFolder('')}
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
                    style={{ padding: '2px 6px', fontSize: '0.85rem', fontWeight: isLast ? 'bold' : 'normal', color: isLast ? 'var(--primary)' : 'var(--text)' }}
                    onClick={() => navigateToFolder(subPath)}
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

        {/* Parent Directory Link */}
        {currentFolder !== '' && (
          <div style={{ marginTop: '8px', marginBottom: '8px' }}>
            <button
              className="btn btn-secondary"
              style={{ padding: '4px 10px', fontSize: '0.82rem' }}
              onClick={navigateToParent}
            >
              <i className="fa-solid fa-level-up-alt"></i> .. (Parent Directory)
            </button>
          </div>
        )}

        {/* Desktop Table View */}
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
              {!treeData || (treeData.directories.length === 0 && treeData.files.length === 0) ? (
                <tr>
                  <td colSpan={5} className="empty-state">
                    No files or subdirectories found in this storage directory. Click "Upload File" to add documents.
                  </td>
                </tr>
              ) : (
                <>
                  {/* Directories */}
                  {treeData.directories.map((d: StorageDirectoryItem) => (
                    <tr key={d.rel_path}>
                      <td>
                        <button
                          className="btn-icon"
                          style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', textAlign: 'left', color: 'var(--text)' }}
                          onClick={() => navigateToFolder(d.rel_path)}
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
                          onClick={() => navigateToFolder(d.rel_path)}
                          title={`Open ${d.name}`}
                          aria-label={`open ${d.name}`}
                        >
                          <i className="fa-solid fa-folder-open"></i> Open
                        </button>
                      </td>
                    </tr>
                  ))}

                  {/* Files */}
                  {treeData.files.map((f: StorageFileItem) => (
                    <tr key={f.rel_path}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <i className="fa-solid fa-file-lines" style={{ color: 'var(--primary)', fontSize: '1.05rem' }}></i>
                          <span>{f.name}</span>
                        </div>
                      </td>
                      <td><code>{f.rel_path}</code></td>
                      <td><span className="badge badge-primary">{formatBytes(f.size_bytes)}</span></td>
                      <td style={{ fontSize: '0.85rem' }}>{formatDate(f.mtime)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '6px' }}>
                          <button
                            className="btn-icon"
                            onClick={() => openPreviewModal(f)}
                            title="Preview File"
                            aria-label="Preview File"
                          >
                            <i className="fa-solid fa-eye"></i>
                          </button>
                          <button
                            className="btn-icon"
                            onClick={() => openReplaceModal(f)}
                            title="Replace File"
                            aria-label="Replace File"
                          >
                            <i className="fa-solid fa-file-pen"></i>
                          </button>
                          <button
                            className="btn-icon btn-delete"
                            onClick={() => handleDeleteFile(f)}
                            title="Delete File"
                            aria-label="Delete File"
                          >
                            <i className="fa-solid fa-trash-can"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile Card List */}
        <div className="mobile-card-list">
          {!treeData || (treeData.directories.length === 0 && treeData.files.length === 0) ? (
            <div className="empty-state">No files or subdirectories found.</div>
          ) : (
            <>
              {treeData.directories.map((d: StorageDirectoryItem) => (
                <div key={`m-${d.rel_path}`} className="data-mobile-card">
                  <div className="data-mobile-card-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <i className="fa-solid fa-folder" style={{ color: '#fbbf24' }}></i>
                      <strong>{d.name}</strong>
                    </div>
                    <span className="badge badge-warning">Directory</span>
                  </div>
                  <div className="data-mobile-card-body">
                    <div>
                      <span className="text-muted">Path: </span>
                      <code>{d.rel_path}</code>
                    </div>
                  </div>
                  <div className="data-mobile-card-actions">
                    <button className="btn btn-secondary" onClick={() => navigateToFolder(d.rel_path)} aria-label={`open ${d.name}`}>
                      <i className="fa-solid fa-folder-open"></i> Open Folder
                    </button>
                  </div>
                </div>
              ))}

              {treeData.files.map((f: StorageFileItem) => (
                <div key={`m-${f.rel_path}`} className="data-mobile-card">
                  <div className="data-mobile-card-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <i className="fa-solid fa-file-lines" style={{ color: 'var(--primary)' }}></i>
                      <strong>{f.name}</strong>
                    </div>
                    <span className="badge badge-primary">{formatBytes(f.size_bytes)}</span>
                  </div>
                  <div className="data-mobile-card-body">
                    <div>
                      <span className="text-muted">Path: </span>
                      <code>{f.rel_path}</code>
                    </div>
                    <div>
                      <span className="text-muted">Modified: </span>
                      <span>{formatDate(f.mtime)}</span>
                    </div>
                  </div>
                  <div className="data-mobile-card-actions">
                    <button className="btn btn-secondary" onClick={() => openPreviewModal(f)} title="Preview File">
                      <i className="fa-solid fa-eye"></i> Preview
                    </button>
                    <button className="btn btn-secondary" onClick={() => openReplaceModal(f)} title="Replace File">
                      <i className="fa-solid fa-file-pen"></i> Replace
                    </button>
                    <button className="btn btn-secondary btn-delete" onClick={() => handleDeleteFile(f)} title="Delete File">
                      <i className="fa-solid fa-trash-can"></i> Delete
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* Upload File Modal */}
      {isUploadModalOpen && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card" style={{ maxWidth: '640px' }}>
            <div className="modal-header">
              <h2><i className="fa-solid fa-cloud-arrow-up"></i> Upload to Local Storage</h2>
              <button className="btn-close" onClick={() => setIsUploadModalOpen(false)}>&times;</button>
            </div>

            <form onSubmit={handleSaveUpload}>
              {/* Drag & Drop area */}
              <div
                style={{
                  border: isDragging ? '2px dashed var(--primary)' : '2px dashed rgba(255, 255, 255, 0.15)',
                  borderRadius: '8px',
                  padding: '20px',
                  textAlign: 'center',
                  background: isDragging ? 'rgba(59, 130, 246, 0.08)' : 'rgba(0, 0, 0, 0.15)',
                  marginBottom: '16px',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
                onClick={() => document.getElementById('storage-file-input')?.click()}
              >
                <i className="fa-solid fa-file-arrow-up" style={{ fontSize: '2rem', color: 'var(--primary)', marginBottom: '8px' }}></i>
                <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                  {selectedFileObj ? `Selected: ${selectedFileObj.name} (${formatBytes(selectedFileObj.size)})` : 'Drag & drop a file here, or click to browse'}
                </p>
                <span className="text-muted" style={{ fontSize: '0.75rem' }}>Supports Markdown, code, JSON, YAML, plain text (up to 500 KB)</span>
                <input
                  id="storage-file-input"
                  type="file"
                  style={{ display: 'none' }}
                  onChange={handleFileInputChange}
                />
              </div>

              <div className="form-row">
                <div className="form-group" style={{ flex: 2 }}>
                  <label htmlFor="upload-path">Relative File Path (e.g. docs/guide.md)</label>
                  <input
                    id="upload-path"
                    type="text"
                    required
                    placeholder="folder/document.md"
                    value={uploadPath}
                    onChange={(e) => setUploadPath(e.target.value)}
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="upload-category">Category Override</label>
                  <input
                    id="upload-category"
                    type="text"
                    placeholder="Optional category"
                    value={uploadCategory}
                    onChange={(e) => setUploadCategory(e.target.value)}
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="upload-content">File Content (Optional if file uploaded directly)</label>
                <textarea
                  id="upload-content"
                  rows={8}
                  placeholder="# Enter or paste text content here..."
                  value={uploadContent}
                  onChange={(e) => setUploadContent(e.target.value)}
                  style={{ fontFamily: 'var(--font-family-mono)', fontSize: '0.85rem' }}
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsUploadModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={isUploading}>
                  <i className={`fa-solid ${isUploading ? 'fa-spinner fa-spin' : 'fa-upload'}`}></i> Upload & Index
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* File Preview Modal */}
      {isPreviewModalOpen && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card" style={{ maxWidth: '750px', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header">
              <div>
                <h2><i className="fa-solid fa-file-code"></i> File Preview: {previewData?.rel_path || 'Loading...'}</h2>
                {previewData && (
                  <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                    Size: {formatBytes(previewData.size_bytes)} &bull; Modified: {formatDate(previewData.mtime)}
                  </span>
                )}
              </div>
              <button className="btn-close" onClick={() => setIsPreviewModalOpen(false)}>&times;</button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', margin: '10px 0' }}>
              {isPreviewLoading ? (
                <div className="empty-state"><i className="fa-solid fa-spinner fa-spin"></i> Loading content...</div>
              ) : (
                <pre
                  className="search-hit-code"
                  style={{ maxHeight: '420px', overflowY: 'auto', margin: 0, whiteSpace: 'pre-wrap' }}
                >
                  {previewData?.content || 'Empty file.'}
                </pre>
              )}
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setIsPreviewModalOpen(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Replace File Modal */}
      {isReplaceModalOpen && replaceTargetFile && (
        <div className="modal-backdrop">
          <div className="glass-card modal-card" style={{ maxWidth: '680px' }}>
            <div className="modal-header">
              <h2><i className="fa-solid fa-file-pen"></i> Replace File: {replaceTargetFile.name}</h2>
              <button className="btn-close" onClick={() => setIsReplaceModalOpen(false)}>&times;</button>
            </div>

            <form onSubmit={handleSaveReplace}>
              <div className="form-group">
                <label>Target File Path</label>
                <input type="text" readOnly value={replaceTargetFile.rel_path} />
              </div>

              <div className="form-group">
                <label htmlFor="replace-category">Category Override</label>
                <input
                  id="replace-category"
                  type="text"
                  placeholder="Optional category"
                  value={replaceCategory}
                  onChange={(e) => setReplaceCategory(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label htmlFor="replace-content">File Content</label>
                <textarea
                  id="replace-content"
                  rows={10}
                  required
                  placeholder="Updated file text..."
                  value={replaceContent}
                  onChange={(e) => setReplaceContent(e.target.value)}
                  style={{ fontFamily: 'var(--font-family-mono)', fontSize: '0.85rem' }}
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsReplaceModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={isReplacing}>
                  <i className={`fa-solid ${isReplacing ? 'fa-spinner fa-spin' : 'fa-save'}`}></i> Save & Re-Index
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
