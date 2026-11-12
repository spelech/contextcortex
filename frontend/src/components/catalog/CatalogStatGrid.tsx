import React from 'react';

export interface CatalogStatGridProps {
  gitRepoCount: number;
  totalGitFiles: number;
  monitoredPathCount: number;
  totalMonitoredFiles: number;
  totalStorageFiles: number;
  totalFiles: number;
}

export const CatalogStatGrid: React.FC<CatalogStatGridProps> = ({
  gitRepoCount,
  totalGitFiles,
  monitoredPathCount,
  totalMonitoredFiles,
  totalStorageFiles,
  totalFiles,
}) => {
  return (
    <div className="stats-grid">
      <div className="stat-card" data-testid="catalog-stat-card">
        <div className="stat-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="6" y1="3" x2="6" y2="15"></line>
            <circle cx="18" cy="6" r="3"></circle>
            <circle cx="6" cy="18" r="3"></circle>
            <path d="M18 9a9 9 0 0 1-9 9"></path>
          </svg>
        </div>
        <div className="stat-info">
          <span className="stat-label">Git Repositories</span>
          <span className="stat-value">
            {gitRepoCount}{' '}
            <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>
              ({totalGitFiles} files)
            </small>
          </span>
        </div>
      </div>

      <div className="stat-card" data-testid="catalog-stat-card">
        <div className="stat-icon" aria-hidden="true" style={{ background: 'rgba(251, 191, 36, 0.12)', color: '#fbbf24' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            <line x1="12" y1="11" x2="12" y2="17"></line>
            <line x1="9" y1="14" x2="15" y2="14"></line>
          </svg>
        </div>
        <div className="stat-info">
          <span className="stat-label">Monitored Paths</span>
          <span className="stat-value">
            {monitoredPathCount}{' '}
            <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>
              ({totalMonitoredFiles} files)
            </small>
          </span>
        </div>
      </div>

      <div className="stat-card" data-testid="catalog-stat-card">
        <div className="stat-icon" aria-hidden="true" style={{ background: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="12" x2="2" y2="12"></line>
            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
            <line x1="6" y1="16" x2="6.01" y2="16"></line>
            <line x1="10" y1="16" x2="10.01" y2="16"></line>
          </svg>
        </div>
        <div className="stat-info">
          <span className="stat-label">Local Storage</span>
          <span className="stat-value">
            {totalStorageFiles}{' '}
            <small style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>
              files
            </small>
          </span>
        </div>
      </div>

      <div className="stat-card" data-testid="catalog-stat-card">
        <div className="stat-icon" aria-hidden="true" style={{ background: 'rgba(168, 85, 247, 0.12)', color: '#a855f7' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
          </svg>
        </div>
        <div className="stat-info">
          <span className="stat-label">Total Cataloged Files</span>
          <span className="stat-value">{totalFiles}</span>
        </div>
      </div>
    </div>
  );
};
