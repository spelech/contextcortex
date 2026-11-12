import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { IngestionCatalogData, IngestionDetailedFile } from './types';
import { useToast } from './ToastContext';
import { CatalogStatGrid } from './components/catalog/CatalogStatGrid';
import {
  CatalogFilterBar,
  type CatalogSourceType,
  type CatalogDetailLevel,
} from './components/catalog/CatalogFilterBar';
import { CatalogSourceTables } from './components/catalog/CatalogSourceTables';
import { formatLanguageLabel } from './components/navigator/syntaxSemantics';

export default function IngestionCatalogViewer() {
  const toast = useToast();
  const [catalogData, setCatalogData] = useState<IngestionCatalogData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const [sourceType, setSourceType] = useState<CatalogSourceType>('all');
  const [detailLevel, setDetailLevel] = useState<CatalogDetailLevel>('summary');
  const [repoName, setRepoName] = useState<string>('');
  const [pathPrefix, setPathPrefix] = useState<string>('');
  const [fileExtension, setFileExtension] = useState<string>('');
  const [fileSearchFilter, setFileSearchFilter] = useState<string>('');

  const loadCatalog = useCallback(
    async (
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
    },
    [sourceType, detailLevel, repoName, pathPrefix, fileExtension, toast]
  );

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

  const gitRepos = catalogData?.git_repositories || [];
  const monitoredPaths = catalogData?.monitored_paths || [];
  const localStorageInfo = catalogData?.local_storage;
  const detailedFiles = catalogData?.files || [];

  const filteredDetailedFiles = detailedFiles.filter((f: IngestionDetailedFile) => {
    if (!fileSearchFilter.trim()) return true;
    const term = fileSearchFilter.toLowerCase();
    const formattedLang = formatLanguageLabel(f.language, f.filepath).toLowerCase();
    return (
      f.filepath.toLowerCase().includes(term) ||
      f.repo.toLowerCase().includes(term) ||
      Boolean(f.language && f.language.toLowerCase().includes(term)) ||
      formattedLang.includes(term)
    );
  });

  const totalGitFiles = gitRepos.reduce((acc, r) => acc + (r.file_count || 0), 0);
  const totalMonitoredFiles = monitoredPaths.reduce((acc, p) => acc + (p.file_count || 0), 0);
  const totalStorageFiles = localStorageInfo?.file_count || 0;
  const totalFiles = totalGitFiles + totalMonitoredFiles + totalStorageFiles;

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-book-bookmark"></i> Unified Ingestion Catalog</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Inspect all indexed Git repositories, monitored local workspaces, and uploaded local storage documents.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => handleApplyFilters()}
              disabled={loading}
              title="Refresh catalog"
            >
              <i className={`fa-solid fa-arrows-rotate ${loading ? 'fa-spin' : ''}`}></i> Refresh
            </button>
          </div>
        </div>

        <CatalogStatGrid
          gitRepoCount={gitRepos.length}
          totalGitFiles={totalGitFiles}
          monitoredPathCount={monitoredPaths.length}
          totalMonitoredFiles={totalMonitoredFiles}
          totalStorageFiles={totalStorageFiles}
          totalFiles={totalFiles}
        />

        <CatalogFilterBar
          sourceType={sourceType}
          detailLevel={detailLevel}
          repoName={repoName}
          pathPrefix={pathPrefix}
          fileExtension={fileExtension}
          onSourceTypeChange={setSourceType}
          onDetailLevelChange={setDetailLevel}
          onRepoNameChange={setRepoName}
          onPathPrefixChange={setPathPrefix}
          onFileExtensionChange={setFileExtension}
          onApplyFilters={handleApplyFilters}
          onClearFilters={handleClearFilters}
        />

        <CatalogSourceTables
          sourceType={sourceType}
          detailLevel={detailLevel}
          gitRepos={gitRepos}
          monitoredPaths={monitoredPaths}
          localStorageInfo={localStorageInfo}
          filteredDetailedFiles={filteredDetailedFiles}
          fileSearchFilter={fileSearchFilter}
          onFileSearchFilterChange={setFileSearchFilter}
        />
      </div>
    </div>
  );
}
