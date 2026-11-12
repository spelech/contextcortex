import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LocalStorageView from '../LocalStorageManager';
import { ToastProvider } from '../ToastContext';
import type { StorageTreeData } from '../types';

const mockRootTree: StorageTreeData = {
  root: '/app/data/storage',
  current_folder: '',
  directories: [
    { name: 'docs', rel_path: 'docs', abs_path: '/app/data/storage/docs' },
    { name: 'scripts', rel_path: 'scripts', abs_path: '/app/data/storage/scripts' }
  ],
  files: [
    { name: 'guide.md', rel_path: 'guide.md', abs_path: '/app/data/storage/guide.md', size_bytes: 1024, mtime: 1700000000 }
  ]
};

describe('LocalStorage PDF & Modal Flows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders PDF files with red PDF icon in files table', async () => {
    const mockTreeWithPdf: StorageTreeData = {
      root: '/app/data/storage',
      current_folder: '',
      directories: [],
      files: [
        { name: 'document.pdf', rel_path: 'document.pdf', abs_path: '/app/data/storage/document.pdf', size_bytes: 8192, mtime: 1700005000 }
      ]
    };

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockTreeWithPdf
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageView refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('document.pdf')[0]).toBeInTheDocument();
    });

    // Check that fa-file-pdf icon is rendered
    const pdfIcons = document.querySelectorAll('.fa-file-pdf');
    expect(pdfIcons.length).toBeGreaterThan(0);
  });

  it('intercepts .pdf upload, fetches preview data, opens PdfPreviewModal, and ingests on confirm', async () => {
    const refreshStats = vi.fn();
    const mockPdfPreview = {
      filename: 'sample.pdf',
      total_pages: 2,
      total_characters: 2400,
      ocr_pages_count: 0,
      pages: [
        { page_number: 1, text: 'First page content', char_count: 1200, ocr_applied: false },
        { page_number: 2, text: 'Second page content', char_count: 1200, ocr_applied: false }
      ],
      sample_chunks: [
        { chunk_index: 0, page_number: 1, heading: 'Page 1', char_count: 400, preview: 'First page chunk preview' }
      ]
    };

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/storage/pdf/preview') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => mockPdfPreview
        } as Response);
      }
      if (url.includes('/admin/api/storage/upload') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            rel_path: 'sample.pdf',
            chunks_indexed: 3
          })
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint: ' + url));
    });

    render(
      <ToastProvider>
        <LocalStorageView refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Upload File')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Upload File/i }));
    expect(screen.getByText('Upload to Local Storage')).toBeInTheDocument();

    const fileInput = document.getElementById('storage-file-input') as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();
    expect(fileInput.getAttribute('accept')).toContain('.pdf');

    const pdfFile = new File(['%PDF-1.4 dummy pdf content'], 'sample.pdf', { type: 'application/pdf' });
    fireEvent.change(fileInput, { target: { files: [pdfFile] } });

    // Verify preview endpoint was invoked
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/storage/pdf/preview',
        expect.objectContaining({ method: 'POST' })
      );
    });

    // PdfPreviewModal should now be displayed
    await waitFor(() => {
      expect(screen.getByText('PDF Extraction Preview')).toBeInTheDocument();
      expect(screen.getByText('sample.pdf')).toBeInTheDocument();
      expect(screen.getByText('First page content')).toBeInTheDocument();
    });

    // Confirm ingestion
    const confirmBtn = screen.getByTestId('confirm-ingest-btn');
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/storage/upload',
        expect.objectContaining({ method: 'POST' })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText(/PDF uploaded and indexed \(3 chunks\)/i)).toBeInTheDocument();
    });
  });

  it('displays PDF notice and hides text textarea when upload path is a PDF', async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRootTree
    });

    render(
      <ToastProvider>
        <LocalStorageView />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Upload File')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Upload File/i }));
    expect(screen.getByLabelText(/File Content/i)).toBeInTheDocument();

    // Type a .pdf path
    const pathInput = screen.getByLabelText(/Relative File Path/i);
    fireEvent.change(pathInput, { target: { value: 'docs/ASD-STE100.pdf' } });

    // The textarea should now be hidden and the PDF alert displayed
    expect(screen.queryByLabelText(/File Content/i)).not.toBeInTheDocument();
    expect(screen.getByText(/PDF Document Selected:/i)).toBeInTheDocument();
    expect(screen.getByText(/Binary PDF content cannot be edited manually as text/i)).toBeInTheDocument();
  });

  it('prevents direct text replacement of PDF files in replace modal', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ...mockRootTree,
            files: [
              {
                name: 'ASD-STE100.pdf',
                rel_path: 'ASD-STE100.pdf',
                size_bytes: 3200000,
                mtime: 1700000000,
                category: 'docs',
                repo: 'local_storage',
                is_dir: false
              }
            ]
          })
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint: ' + url));
    });

    render(
      <ToastProvider>
        <LocalStorageView />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('ASD-STE100.pdf')[0]).toBeInTheDocument();
    });

    // Open replace modal for ASD-STE100.pdf
    const replaceBtn = screen.getAllByTitle('Replace File')[0];
    fireEvent.click(replaceBtn);

    expect(screen.getByText('Replace File: ASD-STE100.pdf')).toBeInTheDocument();
    expect(screen.getByText(/PDF Replacement:/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot be edited as plain text/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/File Content/i)).not.toBeInTheDocument();

    // Save button should be disabled
    const saveBtn = screen.getByRole('button', { name: /Save & Re-Index/i });
    expect(saveBtn).toBeDisabled();
  });
});
