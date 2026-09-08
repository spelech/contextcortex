import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LocalStorageManager from '../LocalStorageManager';
import { ToastProvider } from '../ToastContext';
import type { StorageTreeData, StorageFileContent } from '../types';

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

const mockDocsTree: StorageTreeData = {
  root: '/app/data/storage',
  current_folder: 'docs',
  directories: [],
  files: [
    { name: 'architecture.md', rel_path: 'docs/architecture.md', abs_path: '/app/data/storage/docs/architecture.md', size_bytes: 2048, mtime: 1700001000 }
  ]
};

const mockFileContent: StorageFileContent = {
  rel_path: 'guide.md',
  abs_path: '/app/data/storage/guide.md',
  content: '# Local Storage Guide\nWelcome to ContextCortex local storage.',
  size_bytes: 1024,
  mtime: 1700000000
};

describe('LocalStorageManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders storage header, upload button, and tree view', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    expect(await screen.findByText('Local Storage Explorer')).toBeInTheDocument();
    expect(screen.getByText('Upload File')).toBeInTheDocument();
    expect(screen.getAllByText('guide.md')[0]).toBeInTheDocument();
    expect(screen.getAllByText('docs')[0]).toBeInTheDocument();
    expect(screen.getAllByText('scripts')[0]).toBeInTheDocument();
  });

  it('supports folder navigation drilling and climbing back', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('folder=docs')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockDocsTree
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('docs')[0]).toBeInTheDocument();
    });

    // Click into docs folder
    const openDocsBtn = screen.getAllByRole('button', { name: /open docs/i })[0];
    fireEvent.click(openDocsBtn);

    await waitFor(() => {
      expect(screen.getAllByText('architecture.md')[0]).toBeInTheDocument();
      expect(screen.getByText('.. (Parent Directory)')).toBeInTheDocument();
    });

    // Click back to parent
    fireEvent.click(screen.getByText('.. (Parent Directory)'));

    await waitFor(() => {
      expect(screen.getAllByText('guide.md')[0]).toBeInTheDocument();
    });
  });

  it('opens upload modal, submits new file with custom category, and refreshes stats', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/storage/upload') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            rel_path: 'notes.md',
            abs_path: '/app/data/storage/notes.md',
            size_bytes: 50,
            chunks_indexed: 2,
            symbols_indexed: 0
          })
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Upload File')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Upload File/i }));

    expect(screen.getByText('Upload to Local Storage')).toBeInTheDocument();

    // Fill form
    fireEvent.change(screen.getByLabelText(/Relative File Path/i), { target: { value: 'notes.md' } });
    fireEvent.change(screen.getByLabelText(/Category Override/i), { target: { value: 'daily-notes' } });
    fireEvent.change(screen.getByLabelText(/File Content/i), { target: { value: '# Meeting Notes\nDiscussion on indexing.' } });

    fireEvent.click(screen.getByRole('button', { name: /Upload & Index/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/storage/upload',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: 'notes.md',
            content: '# Meeting Notes\nDiscussion on indexing.',
            repo: 'local_storage',
            category: 'daily-notes'
          })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText(/File uploaded and indexed \(2 chunks\)/i)).toBeInTheDocument();
    });
  });

  it('opens preview modal, displays file text, and closes modal', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/storage/file?path=guide.md')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockFileContent
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('guide.md')[0]).toBeInTheDocument();
    });

    const previewBtn = screen.getAllByTitle('Preview File')[0];
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(screen.getByText('File Preview: guide.md')).toBeInTheDocument();
      expect(screen.getByText(/Welcome to ContextCortex local storage/i)).toBeInTheDocument();
    });

    // Close preview
    fireEvent.click(screen.getByRole('button', { name: /Close/i }));
    expect(screen.queryByText('File Preview: guide.md')).not.toBeInTheDocument();
  });

  it('replaces file content, updates vector store, and provides feedback', async () => {
    const refreshStats = vi.fn();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/storage/file?path=guide.md') && (!opts || opts.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockFileContent
        } as Response);
      }
      if (url.includes('/admin/api/storage/file') && opts?.method === 'PUT') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            rel_path: 'guide.md',
            chunks_indexed: 4,
            symbols_indexed: 1
          })
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('guide.md')[0]).toBeInTheDocument();
    });

    const replaceBtn = screen.getAllByTitle('Replace File')[0];
    fireEvent.click(replaceBtn);

    await waitFor(() => {
      expect(screen.getByText('Replace File: guide.md')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/File Content/i), {
      target: { value: '# Updated Guide Content' }
    });

    fireEvent.click(screen.getByRole('button', { name: /Save & Re-Index/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/admin/api/storage/file',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            path: 'guide.md',
            content: '# Updated Guide Content',
            repo: 'local_storage',
            category: ''
          })
        })
      );
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText(/File updated and indexed \(4 chunks\)/i)).toBeInTheDocument();
    });
  });

  it('deletes file upon confirmation and refreshes list and stats', async () => {
    const refreshStats = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/admin/api/storage/file?path=guide.md') && opts?.method === 'DELETE') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success', deleted: true, rel_path: 'guide.md' })
        } as Response);
      }
      if (url.includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRootTree
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager refreshStats={refreshStats} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('guide.md')[0]).toBeInTheDocument();
    });

    const deleteBtn = screen.getAllByTitle('Delete File')[0];
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(globalThis.fetch).toHaveBeenCalledWith('/admin/api/storage/file?path=guide.md', { method: 'DELETE' });
      expect(refreshStats).toHaveBeenCalled();
      expect(screen.getByText(/File deleted successfully/i)).toBeInTheDocument();
    });
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
        <LocalStorageManager refreshStats={vi.fn()} />
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
        <LocalStorageManager refreshStats={refreshStats} />
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
});

