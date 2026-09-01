import React, { useState } from 'react';
import type { SymbolImpact, DensityMode } from './types';
import { getMethodBadgeClass, getKindBadgeClass } from './NavigatorOutline';

interface NavigatorInspectorProps {
  impact: SymbolImpact | null;
  onSelectCaller?: (filePath: string, symbolName?: string, sourceSymbolId?: number) => void;
  onSelectCallee?: (filePath?: string, symbolName?: string) => void;
  density?: DensityMode;
  loading?: boolean;
}

export const NavigatorInspector: React.FC<NavigatorInspectorProps> = ({
  impact,
  onSelectCaller,
  onSelectCallee,
  density = 'balanced',
  loading = false,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopyPermalink = async () => {
    if (!impact?.symbol) return;
    const { filepath, start_line, end_line } = impact.symbol;
    const permalink = `${filepath}#L${start_line}${end_line && end_line !== start_line ? `-L${end_line}` : ''}`;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(permalink);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const symbol = impact?.symbol;
  const route = impact?.route;
  const callers = impact?.callers || [];
  const callees = impact?.callees || [];
  const imports = impact?.imports || [];

  return (
    <div className={`nav-inspector-pane density-${density}`} data-testid="navigator-inspector-container">
      <div className="nav-inspector-header">
        <div className="nav-inspector-title">
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
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4M12 8h.01" />
          </svg>
          <span>Code Intelligence & Impact</span>
        </div>

        {symbol && (
          <button
            type="button"
            className="nav-copy-permalink-btn"
            onClick={handleCopyPermalink}
            title="Copy file path & line range permalink"
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
                <span>Copy Permalink</span>
              </>
            )}
          </button>
        )}
      </div>

      <div className="nav-inspector-content">
        {loading ? (
          <div className="nav-inspector-skeleton" data-testid="inspector-loading-skeleton">
            <div className="skeleton-header shimmer"></div>
            <div className="skeleton-metrics shimmer"></div>
            <div className="skeleton-block shimmer"></div>
            <div className="skeleton-block shimmer"></div>
          </div>
        ) : !impact || !symbol ? (
          <div className="nav-empty-state">
            <div className="empty-icon">🔍</div>
            <h4>No Symbol Selected</h4>
            <p>Select a symbol from the outline to inspect its callers, dependencies, and impact.</p>
          </div>
        ) : (
          <div className="nav-inspector-body">
            {/* Symbol Title & Location Card */}
            <div className="inspector-card symbol-summary-card">
              <div className="summary-title-row">
                <span className={`symbol-kind-badge ${getKindBadgeClass(symbol.kind)}`}>{symbol.kind}</span>
                <h3 className="summary-name" title={symbol.full_symbol || symbol.name}>
                  {symbol.name}
                </h3>
              </div>

              <div className="summary-location-row">
                <span className="summary-file-path">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                    <polyline points="13 2 13 9 20 9" />
                  </svg>
                  {symbol.filepath}
                </span>
                <span className="summary-line-range">
                  L{symbol.start_line} - L{symbol.end_line}
                </span>
              </div>
            </div>

            {/* Metrics 4-Grid */}
            <div className="inspector-metrics-grid">
              <div className="metric-box">
                <span className="metric-label">Incoming Callers</span>
                <span className="metric-value" data-testid="metric-callers">
                  {callers.length}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Outgoing Callees</span>
                <span className="metric-value" data-testid="metric-callees">
                  {callees.length}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Total Imports</span>
                <span className="metric-value" data-testid="metric-imports">
                  {imports.length}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Language</span>
                <span className="metric-value metric-lang" data-testid="metric-scope">
                  {symbol.language || 'code'}
                </span>
              </div>
            </div>

            {/* API Route Mapping Card */}
            {route && (
              <div className="inspector-card route-card">
                <div className="card-section-title">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="2" y1="12" x2="22" y2="12" />
                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                  </svg>
                  <span>API Route Mapping</span>
                </div>
                <div className="route-detail-row">
                  <span className={`route-method-badge ${getMethodBadgeClass(route.http_method)}`}>
                    {route.http_method}
                  </span>
                  <span className="route-path-code">{route.path_pattern}</span>
                  {route.framework && (
                    <span className="route-framework-tag">{route.framework}</span>
                  )}
                </div>
              </div>
            )}

            {/* Signature & Docstring */}
            {symbol.signature && (
              <div className="inspector-card code-preview-card">
                <div className="card-section-title">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                  </svg>
                  <span>Signature</span>
                </div>
                <pre className="signature-code-block">
                  <code>{symbol.signature}</code>
                </pre>
              </div>
            )}

            {symbol.docstring && (
              <div className="inspector-card docstring-card">
                <div className="card-section-title">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                  <span>Documentation</span>
                </div>
                <p className="docstring-text">{symbol.docstring}</p>
              </div>
            )}

            {/* Incoming Callers */}
            <div className="inspector-card relations-card callers-section">
              <div className="card-section-title">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
                <span>Incoming Callers ({callers.length})</span>
              </div>

              {callers.length === 0 ? (
                <div className="nav-no-items-text">No incoming callers found in this repository.</div>
              ) : (
                <div className="relation-list">
                  {callers.map((c, idx) => (
                    <div
                      key={c.id ?? idx}
                      data-testid={`caller-item-${c.id ?? idx}`}
                      className="relation-item caller-item"
                      onClick={() => {
                        if (c.source_filepath && onSelectCaller) {
                          onSelectCaller(c.source_filepath, c.source_symbol, c.source_symbol_id ?? undefined);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      title={`Jump to ${c.source_symbol || 'caller'} in ${c.source_filepath || ''}`}
                    >
                      <div className="relation-top">
                        <span className="rel-symbol-name">{c.source_symbol || 'Unknown Caller'}</span>
                        <span className="rel-jump-hint" aria-hidden="true">
                          Jump ↗
                        </span>
                      </div>
                      <div className="relation-bottom">
                        {c.source_filepath && (
                          <span className="rel-filepath">{c.source_filepath}</span>
                        )}
                        {c.line_number && (
                          <span className="rel-line">L{c.line_number}</span>
                        )}
                        {c.relationship_type && (
                          <span className="rel-type-tag">{c.relationship_type}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Outgoing Dependencies */}
            <div className="inspector-card relations-card dependencies-section">
              <div className="card-section-title">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12l7 7 7-7" />
                </svg>
                <span>Outgoing Dependencies ({callees.length + imports.length})</span>
              </div>

              {callees.length === 0 && imports.length === 0 ? (
                <div className="nav-no-items-text">No outgoing calls or imports.</div>
              ) : (
                <div className="relation-list">
                  {callees.map((callee, idx) => (
                    <div
                      key={callee.id ?? `callee-${idx}`}
                      className="relation-item callee-item"
                      onClick={() => {
                        if (onSelectCallee) {
                          onSelectCallee(callee.target_filepath, callee.target_symbol);
                        }
                      }}
                    >
                      <div className="relation-top">
                        <span className="rel-symbol-name">{callee.target_symbol}</span>
                        <span className="rel-type-badge">{callee.relationship_type || 'CALLS'}</span>
                      </div>
                      <div className="relation-bottom">
                        {callee.target_filepath && (
                          <span className="rel-filepath">{callee.target_filepath}</span>
                        )}
                        {callee.line_number && (
                          <span className="rel-line">L{callee.line_number}</span>
                        )}
                      </div>
                    </div>
                  ))}

                  {imports.map((imp, idx) => (
                    <div key={imp.id ?? `import-${idx}`} className="relation-item import-item">
                      <div className="relation-top">
                        <span className="rel-symbol-name">{imp.target_symbol}</span>
                        <span className="rel-type-badge import-badge">IMPORTS</span>
                      </div>
                      {imp.line_number && (
                        <div className="relation-bottom">
                          <span className="rel-line">L{imp.line_number}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
