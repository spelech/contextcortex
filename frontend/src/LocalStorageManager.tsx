import { useState, useEffect, useCallback } from 'react';
import type { FormEvent, DragEvent, ChangeEvent } from 'react';
import type {
  StorageTreeData,
  StorageFileItem,
  StorageFileContent,
  PdfPreviewData,
} from './types';
import { useToast } from './ToastContext';
import PdfPreviewModal from './PdfPreviewModal';
import { StorageBrowserPanel } from './components/storage/StorageBrowserPanel';
import { StorageUploadModal } from './components/storage/StorageUploadModal';
import { StoragePreviewDialog, StorageReplaceDialog } from './components/storage/StorageFileDialogs';

interface LocalStorageManagerProps {
  refreshStats?: () => void;
}

export default function LocalStorageManager({ refreshStats }: LocalStorageManagerProps) {
  const toast = useToast();
  const [treeData, setTreeData] = useState<StorageTreeData | null>(null);
  const [currentFolder, setCurrentFolder] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadPath, setUploadPath] = useState('');
  const [uploadCategory, setUploadCategory] = useState('');
  const [uploadRepo, setUploadRepo] = useState('local_storage');
  const [uploadContent, setUploadContent] = useState('');
  const [selectedFileObj, setSelectedFileObj] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false);
  const [previewData, setPreviewData] = useState<StorageFileContent | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);

  const [isReplaceModalOpen, setIsReplaceModalOpen] = useState(false);
  const [replaceTargetFile, setReplaceTargetFile] = useState<StorageFileItem | null>(null);
  const [replaceContent, setReplaceContent] = useState('');
  const [replaceCategory, setReplaceCategory] = useState('');
  const [isReplacing, setIsReplacing] = useState(false);

  const [isPdfPreviewModalOpen, setIsPdfPreviewModalOpen] = useState(false);
  const [isPdfPreviewLoading, setIsPdfPreviewLoading] = useState(false);
  const [pdfPreviewData, setPdfPreviewData] = useState<PdfPreviewData | null>(null);
  const [pendingPdfFile, setPendingPdfFile] = useState<File | null>(null);
  const [pendingPdfPath, setPendingPdfPath] = useState('');
  const [pendingPdfRepo, setPendingPdfRepo] = useState('local_storage');
  const [pendingPdfCategory, setPendingPdfCategory] = useState('');
  const [isPdfIngesting, setIsPdfIngesting] = useState(false);

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

  const previewPdfUpload = async (file: File, targetPath?: string, repo?: string, category?: string) => {
    setIsPdfPreviewLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('ocr_fallback', 'true');

      const res = await fetch('/admin/api/storage/pdf/preview', { method: 'POST', body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to generate PDF preview');

      setPendingPdfFile(file);
      setPendingPdfPath(targetPath || (currentFolder ? `${currentFolder}/${file.name}` : file.name));
      setPendingPdfRepo(repo || uploadRepo || 'local_storage');
      setPendingPdfCategory(category || uploadCategory || '');
      setPdfPreviewData(data);
      setIsUploadModalOpen(false);
      setIsPdfPreviewModalOpen(true);
    } catch (err: any) {
      toast.error(`PDF preview error: ${err.message}`);
    } finally {
      setIsPdfPreviewLoading(false);
    }
  };

  const handleConfirmPdfIngest = async () => {
    if (!pendingPdfFile) return;
    setIsPdfIngesting(true);
    try {
      const formData = new FormData();
      formData.append('file', pendingPdfFile);
      formData.append('path', pendingPdfPath || pendingPdfFile.name);
      formData.append('repo', pendingPdfRepo || 'local_storage');
      if (pendingPdfCategory) formData.append('category', pendingPdfCategory);

      const res = await fetch('/admin/api/storage/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to ingest PDF');

      setIsPdfPreviewModalOpen(false);
      setPendingPdfFile(null);
      setPdfPreviewData(null);
      toast.success(`PDF uploaded and indexed (${data.chunks_indexed ?? 0} chunks)`);
      loadTree(currentFolder);
      if (refreshStats) refreshStats();
    } catch (err: any) {
      toast.error(`PDF ingestion error: ${err.message}`);
    } finally {
      setIsPdfIngesting(false);
    }
  };

  const handleSelectedFile = (file: File) => {
    setSelectedFileObj(file);
    const target = currentFolder ? `${currentFolder}/${file.name}` : file.name;
    setUploadPath(target);

    if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
      setUploadContent('');
      previewPdfUpload(file, target, uploadRepo, uploadCategory);
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      if (typeof event.target?.result === 'string') setUploadContent(event.target.result);
    };
    reader.readAsText(file);
  };

  const handleFileDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleSelectedFile(e.target.files[0]);
    }
  };

  const handleSaveUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!uploadPath.trim()) {
      toast.error('File path is required');
      return;
    }
    if (selectedFileObj && selectedFileObj.name.toLowerCase().endsWith('.pdf')) {
      await previewPdfUpload(selectedFileObj, uploadPath.trim(), uploadRepo.trim(), uploadCategory.trim());
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
        if (uploadCategory.trim()) formData.append('category', uploadCategory.trim());
        res = await fetch('/admin/api/storage/upload', { method: 'POST', body: formData });
      } else {
        res = await fetch('/admin/api/storage/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: uploadPath.trim(),
            content: uploadContent,
            repo: uploadRepo.trim() || 'local_storage',
            category: uploadCategory.trim() || null,
          }),
        });
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to upload file');

      setIsUploadModalOpen(false);
      toast.success(`File uploaded and indexed (${data.chunks_indexed ?? 0} chunks)`);
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
    if (file.rel_path.toLowerCase().endsWith('.pdf')) {
      setReplaceContent('');
      return;
    }
    try {
      const res = await fetch(`/admin/api/storage/file?path=${encodeURIComponent(file.rel_path)}`);
      const data = await res.json();
      setReplaceContent(res.ok && data.content !== undefined ? data.content : '');
    } catch {
      setReplaceContent('');
    }
  };

  const handleSaveReplace = async (e: FormEvent) => {
    e.preventDefault();
    if (!replaceTargetFile) return;
    if (replaceTargetFile.rel_path.toLowerCase().endsWith('.pdf')) {
      toast.error('PDF files cannot be edited directly via text editor. Upload a new PDF file instead.');
      return;
    }

    setIsReplacing(true);
    try {
      const res = await fetch('/admin/api/storage/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: replaceTargetFile.rel_path,
          content: replaceContent,
          repo: 'local_storage',
          category: replaceCategory.trim() || '',
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to update file');

      setIsReplaceModalOpen(false);
      toast.success(`File updated and indexed (${data.chunks_indexed ?? 0} chunks)`);
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
      const res = await fetch(`/admin/api/storage/file?path=${encodeURIComponent(file.rel_path)}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to delete file');

      toast.success(`File deleted successfully: ${file.name}`);
      loadTree(currentFolder);
      if (refreshStats) refreshStats();
    } catch (err: any) {
      toast.error(`Delete error: ${err.message}`);
    }
  };

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

        <StorageBrowserPanel
          treeData={treeData}
          currentFolder={currentFolder}
          onNavigateFolder={navigateToFolder}
          onNavigateParent={navigateToParent}
          onPreviewFile={openPreviewModal}
          onReplaceFile={openReplaceModal}
          onDeleteFile={handleDeleteFile}
        />
      </div>

      <StorageUploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onSubmit={handleSaveUpload}
        uploadPath={uploadPath}
        setUploadPath={setUploadPath}
        uploadCategory={uploadCategory}
        setUploadCategory={setUploadCategory}
        uploadContent={uploadContent}
        setUploadContent={setUploadContent}
        selectedFileObj={selectedFileObj}
        isDragging={isDragging}
        setIsDragging={setIsDragging}
        isUploading={isUploading}
        isPdfPreviewLoading={isPdfPreviewLoading}
        onFileDrop={handleFileDrop}
        onFileInputChange={handleFileInputChange}
      />

      <StoragePreviewDialog
        isOpen={isPreviewModalOpen}
        isLoading={isPreviewLoading}
        previewData={previewData}
        onClose={() => setIsPreviewModalOpen(false)}
      />

      <StorageReplaceDialog
        isOpen={isReplaceModalOpen}
        targetFile={replaceTargetFile}
        replaceCategory={replaceCategory}
        setReplaceCategory={setReplaceCategory}
        replaceContent={replaceContent}
        setReplaceContent={setReplaceContent}
        isReplacing={isReplacing}
        onClose={() => setIsReplaceModalOpen(false)}
        onSubmit={handleSaveReplace}
      />

      {isPdfPreviewModalOpen && pdfPreviewData && (
        <PdfPreviewModal
          data={pdfPreviewData}
          onConfirm={handleConfirmPdfIngest}
          onCancel={() => {
            setIsPdfPreviewModalOpen(false);
            setPendingPdfFile(null);
            setPdfPreviewData(null);
          }}
          isIngesting={isPdfIngesting}
        />
      )}
    </div>
  );
}
