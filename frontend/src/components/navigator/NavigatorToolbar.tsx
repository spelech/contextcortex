import React from 'react';
import type { DensityMode, RepoOption } from './types';

interface NavigatorToolbarProps {
  repos: RepoOption[];
  selectedRepo: string;
  onSelectRepo: (repo: string) => void;
  density: DensityMode;
  onChangeDensity: (density: DensityMode) => void;
  searchQuery?: string;
  onSearchChange?: (query: string) => void;
  totalFiles?: number;
  totalSymbols?: number;
  onRefresh?: () => void;
  loading?: boolean;
}

export const NavigatorToolbar: React.FC<NavigatorToolbarProps> = ({
  repos,
  selectedRepo,
  onSelectRepo,
  density,
  onChangeDensity,
  searchQuery = '',
  onSearchChange,
  totalFiles = 0,
  totalSymbols = 0,
  onRefresh,
  loading = false,
}) => {
  return (
    <div className="nav-toolbar" data-testid="navigator-toolbar">
      <div className="nav-toolbar-left">
        <div className="nav-repo-selector-wrapper">
          <label htmlFor="nav-repo-select" className="nav-repo-label">
            Repository:
          </label>
          <select
            id="nav-repo-select"
            aria-label="Repository"
            className="nav-repo-select"
            value={selectedRepo}
            onChange={(e) => onSelectRepo(e.target.value)}
            disabled={loading}
          >
            <option value="__all__">All Repositories (__all__)</option>
            {repos
              .filter((r) => r.name !== '__all__')
              .map((repo) => (
                <option key={repo.id ?? repo.name} value={repo.name}>
                  {repo.name}
                </option>
              ))}
          </select>
        </div>

        <div className="nav-stats-badges">
          <span className="nav-stat-badge" title="Total Indexed Files">
            <span className="stat-num">{totalFiles}</span> files
          </span>
          <span className="nav-stat-badge" title="Total Extracted AST Symbols">
            <span className="stat-num">{totalSymbols}</span> symbols
          </span>
        </div>
      </div>

      <div className="nav-toolbar-center">
        {onSearchChange && (
          <div className="nav-global-search">
            <svg
              className="search-icon"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              className="nav-search-input"
              placeholder="Search files (Ctrl+P / /)..."
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              aria-label="Quick search files"
            />
            {searchQuery && (
              <button
                type="button"
                className="nav-search-clear-btn"
                onClick={() => onSearchChange('')}
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>
        )}
      </div>

      <div className="nav-toolbar-right">
        <div className="nav-density-switcher" role="group" aria-label="Density mode">
          <span className="density-label">Density:</span>
          <button
            type="button"
            className={`density-btn ${density === 'compact' ? 'active' : ''}`}
            onClick={() => onChangeDensity('compact')}
            title="Compact (20px rows - IDE mode)"
            aria-pressed={density === 'compact'}
          >
            Compact
          </button>
          <button
            type="button"
            className={`density-btn ${density === 'balanced' ? 'active' : ''}`}
            onClick={() => onChangeDensity('balanced')}
            title="Balanced (28px rows - Default)"
            aria-pressed={density === 'balanced'}
          >
            Balanced
          </button>
          <button
            type="button"
            className={`density-btn ${density === 'spacious' ? 'active' : ''}`}
            onClick={() => onChangeDensity('spacious')}
            title="Spacious (36px rows - Cards)"
            aria-pressed={density === 'spacious'}
          >
            Spacious
          </button>
        </div>

        {onRefresh && (
          <button
            type="button"
            className={`nav-refresh-btn ${loading ? 'spinning' : ''}`}
            onClick={onRefresh}
            title="Refresh codebase tree"
            disabled={loading}
            aria-label="Refresh codebase tree"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
};
