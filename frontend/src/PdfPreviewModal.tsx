import { useState } from 'react';
import type { PdfPreviewData } from './types';

interface PdfPreviewModalProps {
  data: PdfPreviewData;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
  isIngesting?: boolean;
}

export default function PdfPreviewModal({
  data,
  onConfirm,
  onCancel,
  isIngesting = false
}: PdfPreviewModalProps) {
  const [viewMode, setViewMode] = useState<'pages' | 'chunks'>('pages');
  const [currentPageIndex, setCurrentPageIndex] = useState(0);

  const totalPages = data.total_pages || data.pages.length || 1;
  const currentPage = data.pages[currentPageIndex] || {
    page_number: 1,
    text: '',
    char_count: 0,
    ocr_applied: false
  };

  const handlePrevPage = () => {
    if (currentPageIndex > 0) {
      setCurrentPageIndex((prev) => prev - 1);
    }
  };

  const handleNextPage = () => {
    if (currentPageIndex < data.pages.length - 1) {
      setCurrentPageIndex((prev) => prev + 1);
    }
  };

  const handlePageSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const idx = parseInt(e.target.value, 10);
    if (!isNaN(idx) && idx >= 0 && idx < data.pages.length) {
      setCurrentPageIndex(idx);
    }
  };

  return (
    <div className="modal-backdrop" data-testid="pdf-preview-modal-backdrop">
      <div
        className="glass-card modal-card"
        style={{
          maxWidth: '850px',
          width: '95%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column'
        }}
        data-testid="pdf-preview-modal"
      >
        {/* Modal Header */}
        <div className="modal-header" style={{ marginBottom: '12px' }}>
          <div>
            <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0, fontSize: '1.25rem' }}>
              <i className="fa-solid fa-file-pdf text-red-500 mr-2" style={{ color: '#ef4444' }}></i>
              <span>PDF Extraction Preview</span>
            </h2>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              <code>{data.filename}</code>
            </div>
          </div>
          <button
            type="button"
            className="btn-close"
            onClick={onCancel}
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>

        {/* Metrics Banner */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '10px',
            padding: '10px 14px',
            background: 'rgba(255, 255, 255, 0.04)',
            borderRadius: '6px',
            marginBottom: '14px',
            border: '1px solid var(--border-card)'
          }}
        >
          <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', alignItems: 'center', fontSize: '0.85rem' }}>
            <span>
              <strong>Total Pages:</strong> <span className="badge badge-primary" data-testid="total-pages-badge">{data.total_pages}</span>
            </span>
            <span>
              <strong>Total Characters:</strong> <span className="badge badge-primary" data-testid="total-chars-badge">{data.total_characters.toLocaleString()}</span>
            </span>
            <span>
              <strong>OCR Applied:</strong>{' '}
              <span
                className={`badge ${data.ocr_pages_count > 0 ? 'badge-warning' : 'badge-secondary'}`}
                data-testid="ocr-count-badge"
              >
                {data.ocr_pages_count} {data.ocr_pages_count === 1 ? 'page' : 'pages'}
              </span>
            </span>
          </div>

          {/* View mode toggle */}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              type="button"
              className={`btn ${viewMode === 'pages' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '4px 10px', fontSize: '0.82rem' }}
              onClick={() => setViewMode('pages')}
              data-testid="tab-pages-btn"
            >
              <i className="fa-solid fa-file-lines" style={{ marginRight: '5px' }}></i> Page Text
            </button>
            <button
              type="button"
              className={`btn ${viewMode === 'chunks' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '4px 10px', fontSize: '0.82rem' }}
              onClick={() => setViewMode('chunks')}
              data-testid="tab-chunks-btn"
            >
              <i className="fa-solid fa-layer-group" style={{ marginRight: '5px' }}></i> Sample Chunks ({data.sample_chunks?.length || 0})
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div style={{ flex: 1, overflowY: 'auto', minHeight: '320px', display: 'flex', flexDirection: 'column' }}>
          {viewMode === 'pages' ? (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Page Navigator toolbar */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '8px',
                  marginBottom: '10px',
                  padding: '6px 10px',
                  background: 'rgba(0, 0, 0, 0.2)',
                  borderRadius: '6px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ padding: '3px 8px', fontSize: '0.8rem' }}
                    onClick={handlePrevPage}
                    disabled={currentPageIndex <= 0}
                    aria-label="Previous Page"
                  >
                    <i className="fa-solid fa-chevron-left"></i> Prev
                  </button>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem' }}>
                    <span>Page</span>
                    <select
                      value={currentPageIndex}
                      onChange={handlePageSelect}
                      style={{
                        padding: '2px 6px',
                        background: 'var(--bg-card)',
                        color: 'var(--text)',
                        border: '1px solid var(--border-card)',
                        borderRadius: '4px',
                        fontSize: '0.85rem'
                      }}
                      aria-label="Select Page"
                    >
                      {data.pages.map((p, idx) => (
                        <option key={p.page_number} value={idx}>
                          {p.page_number} {p.ocr_applied ? '(OCR)' : ''}
                        </option>
                      ))}
                    </select>
                    <span>of {totalPages}</span>
                  </div>

                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ padding: '3px 8px', fontSize: '0.8rem' }}
                    onClick={handleNextPage}
                    disabled={currentPageIndex >= data.pages.length - 1}
                    aria-label="Next Page"
                  >
                    Next <i className="fa-solid fa-chevron-right"></i>
                  </button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {currentPage.ocr_applied ? (
                    <span
                      className="badge badge-warning"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                      data-testid="page-ocr-applied-badge"
                    >
                      <i className="fa-solid fa-eye"></i> OCR Fallback
                    </span>
                  ) : (
                    <span
                      className="badge badge-secondary"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                      data-testid="page-digital-badge"
                    >
                      <i className="fa-solid fa-font"></i> Digital
                    </span>
                  )}
                  <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                    {currentPage.char_count.toLocaleString()} chars
                  </span>
                </div>
              </div>

              {/* Page Text Viewer */}
              <div style={{ flex: 1, minHeight: '260px', position: 'relative' }}>
                {currentPage.text ? (
                  <pre
                    className="search-hit-code"
                    style={{
                      maxHeight: '400px',
                      overflowY: 'auto',
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: '0.85rem',
                      lineHeight: '1.5',
                      padding: '12px',
                      background: 'rgba(0, 0, 0, 0.3)',
                      borderRadius: '6px'
                    }}
                    data-testid="page-text-content"
                  >
                    {currentPage.text}
                  </pre>
                ) : (
                  <div
                    className="empty-state"
                    style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)' }}
                    data-testid="page-empty-text"
                  >
                    <i className="fa-solid fa-file-circle-question" style={{ fontSize: '1.5rem', marginBottom: '8px', display: 'block' }}></i>
                    No text extracted from Page {currentPage.page_number}.
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* Chunks View */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }} data-testid="chunks-container">
              <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                Simulated chunking for vector ingestion (approx. 1000 chars / chunk with 200 char overlap):
              </div>
              {!data.sample_chunks || data.sample_chunks.length === 0 ? (
                <div className="empty-state" style={{ padding: '24px' }}>
                  No vector chunks generated for this document.
                </div>
              ) : (
                data.sample_chunks.map((chunk) => (
                  <div
                    key={chunk.chunk_index}
                    style={{
                      border: '1px solid var(--border-card)',
                      borderRadius: '6px',
                      background: 'rgba(0, 0, 0, 0.25)',
                      padding: '10px 12px'
                    }}
                    data-testid={`chunk-card-${chunk.chunk_index}`}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.8rem',
                        marginBottom: '6px'
                      }}
                    >
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <span className="badge badge-primary">Chunk #{chunk.chunk_index + 1}</span>
                        <span className="text-muted">{chunk.heading} (Page {chunk.page_number})</span>
                      </div>
                      <span className="badge badge-secondary">{chunk.char_count} chars</span>
                    </div>
                    <pre
                      style={{
                        margin: 0,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontFamily: 'var(--font-family-mono)',
                        fontSize: '0.8rem',
                        color: 'var(--text)',
                        lineHeight: '1.4',
                        background: 'rgba(0, 0, 0, 0.2)',
                        padding: '8px',
                        borderRadius: '4px'
                      }}
                    >
                      {chunk.preview}
                    </pre>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div
          className="modal-footer"
          style={{
            marginTop: '16px',
            paddingTop: '12px',
            borderTop: '1px solid var(--border-card)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '10px'
          }}
        >
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={isIngesting}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onConfirm}
            disabled={isIngesting}
            data-testid="confirm-ingest-btn"
          >
            <i className={`fa-solid ${isIngesting ? 'fa-spinner fa-spin' : 'fa-database'}`} style={{ marginRight: '6px' }}></i>
            {isIngesting ? 'Ingesting...' : 'Confirm & Ingest to Vector DB'}
          </button>
        </div>
      </div>
    </div>
  );
}
