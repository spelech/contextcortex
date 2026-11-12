import React from 'react';
import type { SymbolImpact } from './types';
import { getMethodBadgeClass, getKindBadgeClass } from './NavigatorOutline';
import { formatSymbolKind } from './syntaxSemantics';

export interface CodeImpactDrawerProps {
  impact: SymbolImpact;
  filepath: string;
  onClose: () => void;
  onSelectCaller?: (filePath: string, symbolName?: string, sourceSymbolId?: number) => void;
  onSelectCallee?: (filePath?: string, symbolName?: string) => void;
}

export const CodeImpactDrawer: React.FC<CodeImpactDrawerProps> = ({
  impact,
  filepath,
  onClose,
  onSelectCaller,
  onSelectCallee,
}) => {
  const symbol = impact.symbol;
  if (!symbol) return null;

  const callers = impact.callers || [];
  const callees = impact.callees || [];

  return (
    <div className="nav-code-impact-drawer" data-testid="code-impact-drawer">
      <div className="nav-impact-drawer-header">
        <div className="nav-impact-drawer-title">
          <span className={`outline-kind-badge ${getKindBadgeClass(symbol.kind)}`}>
            {formatSymbolKind(symbol.kind)}
          </span>
          <strong className="nav-impact-symbol-name">{symbol.name}</strong>
          <span className="nav-impact-symbol-lines">
            Lines {symbol.start_line}–{symbol.end_line}
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
          onClick={onClose}
          aria-label="Close Impact Drawer"
        >
          ✕
        </button>
      </div>

      <div className="nav-impact-drawer-body">
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
  );
};
