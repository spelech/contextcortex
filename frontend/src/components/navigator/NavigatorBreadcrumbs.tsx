import React, { useState } from 'react';

export interface NavigatorBreadcrumbsProps {
  repo: string;
  path: string | null;
  symbol: string | null;
  onNavigatePath: (path: string) => void;
  canGoBack: boolean;
  canGoForward: boolean;
  onGoBack: () => void;
  onGoForward: () => void;
  onToggleSidebar: () => void;
  isSidebarOpen: boolean;
}

export const NavigatorBreadcrumbs: React.FC<NavigatorBreadcrumbsProps> = ({
  repo,
  path,
  symbol,
  onNavigatePath,
  canGoBack,
  canGoForward,
  onGoBack,
  onGoForward,
  onToggleSidebar,
  isSidebarOpen,
}) => {
  const [copied, setCopied] = useState(false);

  const pathSegments = React.useMemo(() => {
    if (!path) return [];
    // Strip repo:// prefix for display
    const clean = path.replace(/\\/g, '/').replace(/^[^/]+:\/\//, '').replace(/^\/+/, '');
    return clean.split('/').filter(Boolean);
  }, [path]);

  const handleCopyPermalink = async () => {
    if (!path) return;
    const lineRef = symbol ? `#${symbol}` : '';
    const permalink = `${path}${lineRef}`;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(permalink);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Fallback: ignore
    }
  };

  return (
    <div className="nav-breadcrumbs-bar" data-testid="navigator-breadcrumbs">
      <div className="nav-breadcrumbs-left">
        <button
          type="button"
          className="nav-breadcrumb-btn nav-sidebar-toggle-btn"
          onClick={onToggleSidebar}
          title={isSidebarOpen ? 'Collapse Sidebar (Ctrl+B)' : 'Expand Sidebar (Ctrl+B)'}
          aria-label={isSidebarOpen ? 'Collapse Sidebar' : 'Expand Sidebar'}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        </button>

        <div className="nav-history-controls" role="group" aria-label="Navigation History">
          <button
            type="button"
            className="nav-history-btn"
            onClick={onGoBack}
            disabled={!canGoBack}
            title="Go Back"
            aria-label="Go Back"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <button
            type="button"
            className="nav-history-btn"
            onClick={onGoForward}
            disabled={!canGoForward}
            title="Go Forward"
            aria-label="Go Forward"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>

        <nav className="nav-breadcrumb-trail" aria-label="Breadcrumb">
          <span className="breadcrumb-repo-badge" title="Repository">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
            <span className="crumb-repo-text">{repo}</span>
          </span>

          {pathSegments.length > 0 && <span className="breadcrumb-separator">/</span>}

          {pathSegments.map((segment, index) => {
            const isLast = index === pathSegments.length - 1 && !symbol;
            const subPath = pathSegments.slice(0, index + 1).join('/');

            return (
              <React.Fragment key={subPath}>
                {index > 0 && <span className="breadcrumb-separator">/</span>}
                <button
                  type="button"
                  className={`breadcrumb-segment ${isLast ? 'active' : ''}`}
                  onClick={() => onNavigatePath(subPath)}
                  title={`Navigate to ${subPath}`}
                >
                  {segment}
                </button>
              </React.Fragment>
            );
          })}

          {symbol && (
            <>
              <span className="breadcrumb-separator">#</span>
              <span className="breadcrumb-symbol-badge" title={`Active Symbol: ${symbol}`}>
                {symbol}
              </span>
            </>
          )}
        </nav>
      </div>

      {/* Right side: Copy Permalink — always visible when a file is open */}
      {path && (
        <div className="nav-breadcrumbs-right">
          <button
            type="button"
            className={`nav-breadcrumb-btn nav-permalink-btn ${copied ? 'copied' : ''}`}
            onClick={handleCopyPermalink}
            title="Copy path permalink"
            aria-label="Copy Permalink"
          >
            {copied ? (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span>Copied!</span>
              </>
            ) : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
                <span>Copy Link</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
};
