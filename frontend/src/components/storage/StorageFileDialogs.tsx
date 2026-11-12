import type { FormEvent } from 'react';
import type { StorageFileItem, StorageFileContent } from '../../types';
import { formatStorageBytes, formatStorageDate } from './storageFormatters';

interface StoragePreviewDialogProps {
  isOpen: boolean;
  isLoading: boolean;
  previewData: StorageFileContent | null;
  onClose: () => void;
}

export function StoragePreviewDialog({
  isOpen,
  isLoading,
  previewData,
  onClose,
}: StoragePreviewDialogProps) {
  if (!isOpen) return null;

  return (
    <div className="modal-backdrop">
      <div
        className="glass-card modal-card"
        style={{ maxWidth: '750px', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
      >
        <div className="modal-header">
          <div>
            <h2><i className="fa-solid fa-file-code"></i> File Preview: {previewData?.rel_path || 'Loading...'}</h2>
            {previewData && (
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                Size: {formatStorageBytes(previewData.size_bytes)} &bull; Modified: {formatStorageDate(previewData.mtime)}
              </span>
            )}
          </div>
          <button className="btn-close" onClick={onClose}>&times;</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', margin: '10px 0' }}>
          {isLoading ? (
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
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

interface StorageReplaceDialogProps {
  isOpen: boolean;
  targetFile: StorageFileItem | null;
  replaceCategory: string;
  setReplaceCategory: (val: string) => void;
  replaceContent: string;
  setReplaceContent: (val: string) => void;
  isReplacing: boolean;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
}

export function StorageReplaceDialog({
  isOpen,
  targetFile,
  replaceCategory,
  setReplaceCategory,
  replaceContent,
  setReplaceContent,
  isReplacing,
  onClose,
  onSubmit,
}: StorageReplaceDialogProps) {
  if (!isOpen || !targetFile) return null;

  const isPdf = targetFile.rel_path.toLowerCase().endsWith('.pdf');

  return (
    <div className="modal-backdrop">
      <div className="glass-card modal-card" style={{ maxWidth: '680px' }}>
        <div className="modal-header">
          <h2><i className="fa-solid fa-file-pen"></i> Replace File: {targetFile.name}</h2>
          <button className="btn-close" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={onSubmit}>
          <div className="form-group">
            <label>Target File Path</label>
            <input type="text" readOnly value={targetFile.rel_path} />
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

          {isPdf ? (
            <div
              className="alert alert-warning"
              style={{
                margin: '14px 0',
                padding: '12px',
                background: 'rgba(245, 158, 11, 0.1)',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                borderRadius: '6px',
                fontSize: '0.85rem',
              }}
            >
              <i className="fa-solid fa-triangle-exclamation" style={{ marginRight: '8px', color: '#f59e0b' }}></i>
              <strong>PDF Replacement:</strong> PDF documents contain binary page streams and cannot be edited as plain text. To replace this document, please upload a new <code>.pdf</code> file using the "Upload File" tool.
            </div>
          ) : (
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
          )}

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isReplacing || isPdf}>
              <i className={`fa-solid ${isReplacing ? 'fa-spinner fa-spin' : 'fa-save'}`}></i> Save & Re-Index
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
