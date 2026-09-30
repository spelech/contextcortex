import React, { useState, useEffect, useRef, useMemo } from 'react';
import type { SymbolImpact, DensityMode } from './types';
import { getMethodBadgeClass, getKindBadgeClass } from './NavigatorOutline';

export interface NavigatorCodeViewerProps {
  filepath: string;
  content: string;
  totalLines: number;
  sizeBytes?: number;
  targetStartLine?: number;
  targetEndLine?: number;
  impact?: SymbolImpact | null;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  onSelectCaller?: (filePath: string, symbolName?: string, sourceSymbolId?: number) => void;
  onSelectCallee?: (filePath?: string, symbolName?: string) => void;
  density?: DensityMode;
}

export const NavigatorCodeViewer: React.FC<NavigatorCodeViewerProps> = ({
  filepath,
  content,
  totalLines,
  sizeBytes,
  targetStartLine,
  targetEndLine,
  impact,
  loading = false,
  error = null,
  onRefresh,
  onSelectCaller,
  onSelectCallee,
  density = 'balanced',
}) => {
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const targetLineRef = useRef<HTMLDivElement | null>(null);

  // Split content into lines safely
  const lines = useMemo(() => {
    return content ? content.split('\n') : [];
  }, [content]);

  // Auto-scroll to targetStartLine
  useEffect(() => {
    if (targetStartLine && targetLineRef.current) {
      targetLineRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [targetStartLine, filepath]);

  const handleCopyCode = async () => {
    if (!content) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
        setCopiedCode(true);
        setTimeout(() => setCopiedCode(false), 2000);
      }
    } catch {
      // Fallback
    }
  };

  const handleCopyPermalink = async () => {
    if (!filepath) return;
    const lineHash = targetStartLine
      ? `#L${targetStartLine}${targetEndLine && targetEndLine !== targetStartLine ? `-L${targetEndLine}` : ''}`
      : '';
    const permalink = `${filepath}${lineHash}`;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(permalink);
        setCopiedLink(true);
        setTimeout(() => setCopiedLink(false), 2000);
      }
    } catch {
      // Fallback
    }
  };

  const formatSize = (bytes?: number): string => {
    if (bytes === undefined || bytes === null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const callers = impact?.callers || [];
  const callees = impact?.callees || [];
  const totalImpact = callers.length + callees.length;

  return (
    <div
      className={`nav-code-viewer-container density-${density}`}
      data-testid="navigator-code-viewer"
    >
      {/* Header Toolbar */}
      <div className="nav-code-viewer-header">
        <div className="nav-code-viewer-meta">
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="nav-code-file-icon"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span className="nav-code-filename" title={filepath}>
            {filepath}
          </span>
          <span className="nav-code-stat-chip">
            {totalLines || lines.length} lines
          </span>
          {sizeBytes !== undefined && sizeBytes > 0 && (
            <span className="nav-code-stat-chip">{formatSize(sizeBytes)}</span>
          )}
        </div>

        <div className="nav-code-viewer-actions">
          {/* Impact Drawer Toggle */}
          {impact?.symbol && (
            <button
              type="button"
              className={`nav-code-impact-toggle-btn nav-code-drawer-toggle ${drawerOpen ? 'active' : ''}`}
              onClick={() => setDrawerOpen((prev) => !prev)}
              aria-label="Callers & Impact"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              <span>Callers & Impact ({totalImpact})</span>
            </button>
          )}

          {/* Copy Permalink */}
          <button
            type="button"
            className="nav-code-action-btn"
            onClick={handleCopyPermalink}
            title="Copy path and line permalink"
            aria-label="Copy Permalink"
          >
            {copiedLink ? 'Link Copied!' : 'Copy Link'}
          </button>

          {/* Copy Full Code */}
          <button
            type="button"
            className="nav-code-action-btn"
            onClick={handleCopyCode}
            title="Copy entire file contents"
            aria-label="Copy File Code"
          >
            {copiedCode ? 'Copied!' : 'Copy Code'}
          </button>

          {onRefresh && (
            <button
              type="button"
              className="nav-code-action-btn"
              onClick={onRefresh}
              title="Refresh file"
              aria-label="Refresh File"
            >
              ↻
            </button>
          )}
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="nav-code-error-banner" role="alert">
          <span>Failed to load file: {error}</span>
        </div>
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="nav-code-loading-overlay">
          <div className="nav-omni-spinner" />
          <span>Loading source code...</span>
        </div>
      )}

      {/* Main Code Table */}
      <div className="nav-code-body" tabIndex={0}>
        {lines.length === 0 && !loading && !error ? (
          <div className="nav-code-empty-state" style={{ padding: '24px', color: '#64748b', textAlign: 'center' }}>
            File is empty.
          </div>
        ) : (
          <div className="nav-code-lines-wrapper">
          {lines.map((line, idx) => {
            const lineNum = idx + 1;
            const isTarget =
              targetStartLine !== undefined &&
              lineNum >= targetStartLine &&
              lineNum <= (targetEndLine || targetStartLine);

            const isFirstTarget = targetStartLine !== undefined && lineNum === targetStartLine;

            return (
              <div
                key={lineNum}
                ref={isFirstTarget ? targetLineRef : undefined}
                className={`nav-code-line-row ${isTarget ? 'nav-code-line-target' : ''}`}
                data-testid={`code-line-${lineNum}`}
              >
                <div className="nav-code-line-number select-none">
                  {lineNum}
                </div>
                <div className="nav-code-line-content font-mono">
                  {line || ' '}
                </div>
              </div>
            );
          })}
        </div>
        )}
      </div>

      {/* Docked Symbol Impact Drawer */}
      {drawerOpen && impact?.symbol && (
        <div className="nav-code-impact-drawer" data-testid="code-impact-drawer">
          <div className="nav-impact-drawer-header">
            <div className="nav-impact-drawer-title">
              <span className={`outline-kind-badge ${getKindBadgeClass(impact.symbol.kind)}`}>
                {impact.symbol.kind}
              </span>
              <strong className="nav-impact-symbol-name">{impact.symbol.name}</strong>
              <span className="nav-impact-symbol-lines">
                Lines {impact.symbol.start_line}–{impact.symbol.end_line}
              </span>
              {impact.route && (
                <span className={`outline-method-badge ${getMethodBadgeClass(impact.route.http_method)}`}>
                  {impact.route.http_method} {impact.route.path_pattern}
                </span>
              )}
            </div>
            <button
              type="button"
              className="nav-impact-close-btn"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close Impact Drawer"
            >
              ✕
            </button>
          </div>

          <div className="nav-impact-drawer-body">
            {/* Incoming Callers */}
            <div className="nav-impact-column">
              <div className="nav-impact-column-title">
                Incoming Callers ({callers.length})
              </div>
              {callers.length === 0 ? (
                <div className="nav-impact-empty">No incoming callers detected</div>
              ) : (
                <div className="nav-impact-chips-list">
                  {callers.map((c, i) => (
                    <button
                      key={c.id || i}
                      type="button"
                      className="nav-impact-chip caller"
                      onClick={() =>
                        onSelectCaller &&
                        onSelectCaller(c.source_filepath || filepath, c.source_symbol, c.source_symbol_id || undefined)
                      }
                    >
                      <span className="chip-name">{c.source_symbol || 'anonymous'}</span>
                      <span className="chip-path">{c.source_filepath}</span>
                      {c.line_number && <span className="chip-line">:{c.line_number}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Outgoing Callees */}
            <div className="nav-impact-column">
              <div className="nav-impact-column-title">
                Outgoing Callees ({callees.length})
              </div>
              {callees.length === 0 ? (
                <div className="nav-impact-empty">No outgoing callees detected</div>
              ) : (
                <div className="nav-impact-chips-list">
                  {callees.map((c, i) => (
                    <button
                      key={c.id || i}
                      type="button"
                      className="nav-impact-chip callee"
                      onClick={() =>
                        onSelectCallee &&
                        onSelectCallee(c.target_filepath, c.target_symbol)
                      }
                    >
                      <span className="chip-name">{c.target_symbol}</span>
                      {c.target_filepath && <span className="chip-path">{c.target_filepath}</span>}
                      {c.line_number && <span className="chip-line">:{c.line_number}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
