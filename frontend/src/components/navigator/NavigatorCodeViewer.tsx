import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Highlight } from 'prism-react-renderer';
import type { SymbolImpact, DensityMode } from './types';
import { Prism, universalIDETheme, getPrismLanguage, formatCodeSize } from './codeSyntaxConfig';
import { CodeImpactDrawer } from './CodeImpactDrawer';
import { resolveLanguageDescriptor } from './syntaxSemantics';

export interface NavigatorCodeViewerProps {
  filepath: string;
  content: string;
  totalLines: number;
  sizeBytes?: number;
  language?: string | null;
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
  language,
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

  const lines = useMemo(() => (content ? content.split('\n') : []), [content]);
  const langDescriptor = useMemo(
    () => resolveLanguageDescriptor(language || impact?.symbol?.language, filepath),
    [language, impact?.symbol?.language, filepath]
  );

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
      // Clipboard unavailable
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
      // Clipboard unavailable
    }
  };

  const callers = impact?.callers || [];
  const callees = impact?.callees || [];
  const totalImpact = callers.length + callees.length;

  return (
    <div
      className={`nav-code-viewer-container density-${density}`}
      data-testid="navigator-code-viewer"
    >
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
          {langDescriptor && (
            <span
              className={`nav-code-stat-chip ${langDescriptor.badgeClass}`}
              data-testid="code-viewer-language-badge"
            >
              {langDescriptor.label}
            </span>
          )}
          <span className="nav-code-stat-chip">
            {totalLines || lines.length} lines
          </span>
          {sizeBytes !== undefined && sizeBytes > 0 && (
            <span className="nav-code-stat-chip">{formatCodeSize(sizeBytes)}</span>
          )}
        </div>

        <div className="nav-code-viewer-actions">
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

          <button
            type="button"
            className="nav-code-action-btn"
            onClick={handleCopyPermalink}
            title="Copy path and line permalink"
            aria-label="Copy Permalink"
          >
            {copiedLink ? 'Link Copied!' : 'Copy Link'}
          </button>

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

      {error && (
        <div className="nav-code-error-banner" role="alert">
          <span>Failed to load file: {error}</span>
        </div>
      )}

      {loading && (
        <div className="nav-code-loading-overlay">
          <div className="nav-omni-spinner" />
          <span>Loading source code...</span>
        </div>
      )}

      <div className="nav-code-body" tabIndex={0}>
        {lines.length === 0 && !loading && !error ? (
          <div className="nav-code-empty-state" style={{ padding: '24px', color: '#64748b', textAlign: 'center' }}>
            File is empty.
          </div>
        ) : (
          <Highlight prism={Prism} theme={universalIDETheme} code={content || ''} language={getPrismLanguage(filepath)}>
            {({ tokens, getTokenProps }) => (
              <div className="nav-code-lines-wrapper">
                {tokens.map((lineTokens, idx) => {
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
                      className={`nav-code-line-row ${isTarget ? 'nav-code-line-target' : ''} ${isFirstTarget ? 'nav-code-line-primary' : ''}`}
                      data-testid={`code-line-${lineNum}`}
                    >
                      <div className="nav-code-line-number select-none">
                        {lineNum}
                      </div>
                      <div className="nav-code-line-content font-mono">
                        {lineTokens.length === 0 || (lineTokens.length === 1 && lineTokens[0].content === '') ? (
                          ' '
                        ) : (
                          lineTokens.map((token, key) => (
                            <span key={key} {...getTokenProps({ token })} />
                          ))
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Highlight>
        )}
      </div>

      {drawerOpen && impact?.symbol && (
        <CodeImpactDrawer
          impact={impact}
          filepath={filepath}
          onClose={() => setDrawerOpen(false)}
          onSelectCaller={onSelectCaller}
          onSelectCallee={onSelectCallee}
        />
      )}
    </div>
  );
};
