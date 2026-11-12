import React from 'react';
import type { FormEvent } from 'react';

export type CatalogSourceType = 'all' | 'git' | 'monitored_path' | 'local_storage';
export type CatalogDetailLevel = 'summary' | 'detailed';

export interface CatalogFilterBarProps {
  sourceType: CatalogSourceType;
  detailLevel: CatalogDetailLevel;
  repoName: string;
  pathPrefix: string;
  fileExtension: string;
  onSourceTypeChange: (source: CatalogSourceType) => void;
  onDetailLevelChange: (level: CatalogDetailLevel) => void;
  onRepoNameChange: (value: string) => void;
  onPathPrefixChange: (value: string) => void;
  onFileExtensionChange: (value: string) => void;
  onApplyFilters: (e?: FormEvent) => void;
  onClearFilters: () => void;
}

export const CatalogFilterBar: React.FC<CatalogFilterBarProps> = ({
  sourceType,
  detailLevel,
  repoName,
  pathPrefix,
  fileExtension,
  onSourceTypeChange,
  onDetailLevelChange,
  onRepoNameChange,
  onPathPrefixChange,
  onFileExtensionChange,
  onApplyFilters,
  onClearFilters,
}) => {
  return (
    <div className="catalog-filter-bar">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          marginBottom: '14px',
        }}
      >
        <div className="log-filter-pills" role="group" aria-label="Source Type Filters">
          <button
            type="button"
            className={`log-filter-btn ${sourceType === 'all' ? 'active' : ''}`}
            onClick={() => onSourceTypeChange('all')}
          >
            <i className="fa-solid fa-layer-group"></i> All Sources
          </button>
          <button
            type="button"
            className={`log-filter-btn ${sourceType === 'git' ? 'active' : ''}`}
            onClick={() => onSourceTypeChange('git')}
          >
            <i className="fa-brands fa-github"></i> Git Repositories
          </button>
          <button
            type="button"
            className={`log-filter-btn ${sourceType === 'monitored_path' ? 'active' : ''}`}
            onClick={() => onSourceTypeChange('monitored_path')}
          >
            <i className="fa-solid fa-folder-tree"></i> Monitored Paths
          </button>
          <button
            type="button"
            className={`log-filter-btn ${sourceType === 'local_storage' ? 'active' : ''}`}
            onClick={() => onSourceTypeChange('local_storage')}
          >
            <i className="fa-solid fa-hard-drive"></i> Local Storage
          </button>
        </div>

        <div style={{ display: 'flex', gap: '6px' }} role="group" aria-label="Detail Level Switch">
          <button
            type="button"
            className={`btn ${detailLevel === 'summary' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '5px 12px', fontSize: '0.8rem' }}
            onClick={() => onDetailLevelChange('summary')}
          >
            <i className="fa-solid fa-list"></i> Summary
          </button>
          <button
            type="button"
            className={`btn ${detailLevel === 'detailed' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '5px 12px', fontSize: '0.8rem' }}
            onClick={() => onDetailLevelChange('detailed')}
          >
            <i className="fa-solid fa-network-wired"></i> Detailed File Tree
          </button>
        </div>
      </div>

      <form onSubmit={onApplyFilters}>
        <div className="catalog-filter-inputs">
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="catalog-repo-filter" style={{ fontSize: '0.8rem' }}>
              Repository / Alias
            </label>
            <input
              id="catalog-repo-filter"
              type="text"
              placeholder="Filter by repo name..."
              value={repoName}
              onChange={(e) => onRepoNameChange(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="catalog-prefix-filter" style={{ fontSize: '0.8rem' }}>
              Path Prefix
            </label>
            <input
              id="catalog-prefix-filter"
              type="text"
              placeholder="e.g. app/api or docs/"
              value={pathPrefix}
              onChange={(e) => onPathPrefixChange(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="catalog-ext-filter" style={{ fontSize: '0.8rem' }}>
              File Extension
            </label>
            <input
              id="catalog-ext-filter"
              type="text"
              placeholder="e.g. .md, .py, .ts, .cs, .cbl"
              value={fileExtension}
              onChange={(e) => onFileExtensionChange(e.target.value)}
            />
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ padding: '6px 12px', fontSize: '0.85rem' }}
            onClick={onClearFilters}
          >
            Clear
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            style={{ padding: '6px 14px', fontSize: '0.85rem' }}
          >
            <i className="fa-solid fa-filter"></i> Apply
          </button>
        </div>
      </form>
    </div>
  );
};
