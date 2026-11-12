import type { FormEvent, DragEvent, ChangeEvent } from 'react';
import { formatStorageBytes } from './storageFormatters';

interface StorageUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
  uploadPath: string;
  setUploadPath: (val: string) => void;
  uploadCategory: string;
  setUploadCategory: (val: string) => void;
  uploadContent: string;
  setUploadContent: (val: string) => void;
  selectedFileObj: File | null;
  isDragging: boolean;
  setIsDragging: (val: boolean) => void;
  isUploading: boolean;
  isPdfPreviewLoading: boolean;
  onFileDrop: (e: DragEvent<HTMLDivElement>) => void;
  onFileInputChange: (e: ChangeEvent<HTMLInputElement>) => void;
}

export function StorageUploadModal({
  isOpen,
  onClose,
  onSubmit,
  uploadPath,
  setUploadPath,
  uploadCategory,
  setUploadCategory,
  uploadContent,
  setUploadContent,
  selectedFileObj,
  isDragging,
  setIsDragging,
  isUploading,
  isPdfPreviewLoading,
  onFileDrop,
  onFileInputChange,
}: StorageUploadModalProps) {
  if (!isOpen) return null;

  const isPdfSelected =
    selectedFileObj?.name.toLowerCase().endsWith('.pdf') ||
    selectedFileObj?.type === 'application/pdf' ||
    uploadPath.trim().toLowerCase().endsWith('.pdf');

  return (
    <div className="modal-backdrop">
      <div className="glass-card modal-card" style={{ maxWidth: '640px' }}>
        <div className="modal-header">
          <h2><i className="fa-solid fa-cloud-arrow-up"></i> Upload to Local Storage</h2>
          <button className="btn-close" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={onSubmit}>
          <div
            style={{
              border: isDragging ? '2px dashed var(--primary)' : '2px dashed rgba(255, 255, 255, 0.15)',
              borderRadius: '8px',
              padding: '20px',
              textAlign: 'center',
              background: isDragging ? 'rgba(59, 130, 246, 0.08)' : 'rgba(0, 0, 0, 0.15)',
              marginBottom: '16px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onFileDrop}
            onClick={() => document.getElementById('storage-file-input')?.click()}
          >
            <i className="fa-solid fa-file-arrow-up" style={{ fontSize: '2rem', color: 'var(--primary)', marginBottom: '8px' }}></i>
            <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
              {selectedFileObj
                ? `Selected: ${selectedFileObj.name} (${formatStorageBytes(selectedFileObj.size)})`
                : 'Drag & drop a file here, or click to browse'}
            </p>
            <span className="text-muted" style={{ fontSize: '0.75rem' }}>
              Supports Markdown, Python, TypeScript, C#, COBOL, JSON, YAML, plain text, PDF (up to 50MB)
            </span>
            {isPdfPreviewLoading && (
              <div style={{ marginTop: '8px', fontSize: '0.85rem', color: 'var(--primary)' }}>
                <i className="fa-solid fa-spinner fa-spin" style={{ marginRight: '6px' }}></i>
                Extracting and analyzing PDF preview...
              </div>
            )}
            <input
              id="storage-file-input"
              type="file"
              accept=".md,.markdown,.txt,.json,.yaml,.yml,.sql,.html,.css,.pdf,.py,.ts,.tsx,.js,.jsx,.cs,.cbl,.cob,.cpy"
              style={{ display: 'none' }}
              onChange={onFileInputChange}
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

          {isPdfSelected ? (
            <div
              className="alert alert-info"
              style={{
                margin: '12px 0',
                padding: '12px',
                background: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid var(--primary)',
                borderRadius: '6px',
                fontSize: '0.85rem',
              }}
            >
              <i className="fa-solid fa-file-pdf" style={{ color: '#ef4444', marginRight: '8px' }}></i>
              <strong>PDF Document Selected:</strong> Binary PDF content cannot be edited manually as text. Extracted text, page segmentation, and vector chunks will be previewed in the extraction modal before ingestion.
            </div>
          ) : (
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
          )}

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isUploading}>
              <i className={`fa-solid ${isUploading ? 'fa-spinner fa-spin' : 'fa-upload'}`}></i> Upload & Index
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
