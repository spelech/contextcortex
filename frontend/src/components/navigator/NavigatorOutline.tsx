import React, { useState, useMemo } from 'react';
import type { FileOutline, SymbolOutlineItem, DensityMode, OutlineCategory } from './types';

interface NavigatorOutlineProps {
  outline: FileOutline | null;
  selectedSymbolId: number | null;
  onSelectSymbol: (symbol: SymbolOutlineItem) => void;
  density?: DensityMode;
  loading?: boolean;
}

export function getMethodBadgeClass(method: string): string {
  switch (method.toUpperCase()) {
    case 'GET':
      return 'method-get';
    case 'POST':
      return 'method-post';
    case 'PUT':
      return 'method-put';
    case 'DELETE':
      return 'method-delete';
    case 'PATCH':
      return 'method-patch';
    default:
      return 'method-other';
  }
}

export function getKindBadgeClass(kind: string): string {
  switch (kind.toLowerCase()) {
    case 'class':
      return 'kind-class';
    case 'function':
    case 'method':
    case 'async function':
      return 'kind-function';
    case 'variable':
    case 'constant':
      return 'kind-variable';
    case 'interface':
    case 'type':
      return 'kind-type';
    default:
      return 'kind-default';
  }
}

export const NavigatorOutline: React.FC<NavigatorOutlineProps> = ({
  outline,
  selectedSymbolId,
  onSelectSymbol,
  density = 'balanced',
  loading = false,
}) => {
  const [activeCategory, setActiveCategory] = useState<OutlineCategory>('all');
  const [filterQuery, setFilterQuery] = useState('');

  const symbols = outline?.symbols || [];

  // Compute counts for category chips
  const counts = useMemo(() => {
    let routes = 0;
    let classes = 0;
    let functions = 0;

    for (const s of symbols) {
      if (s.route) routes++;
      const k = s.kind.toLowerCase();
      if (k === 'class' || k === 'interface') classes++;
      else if (k.includes('func') || k === 'method') {
        if (!s.route) functions++;
      }
    }

    return {
      all: symbols.length,
      routes,
      classes,
      functions,
    };
  }, [symbols]);

  // Filter symbols based on category & search query
  const filteredSymbols = useMemo(() => {
    return symbols.filter((s) => {
      // Category filter
      if (activeCategory === 'routes') {
        if (!s.route) return false;
      } else if (activeCategory === 'classes') {
        const k = s.kind.toLowerCase();
        if (k !== 'class' && k !== 'interface') return false;
      } else if (activeCategory === 'functions') {
        const k = s.kind.toLowerCase();
        if (!k.includes('func') && k !== 'method') return false;
        if (s.route) return false;
      }

      // Search query
      if (filterQuery.trim()) {
        const q = filterQuery.toLowerCase();
        const matchesName = s.name.toLowerCase().includes(q);
        const matchesSig = (s.signature || '').toLowerCase().includes(q);
        const matchesRoute = s.route
          ? s.route.path_pattern.toLowerCase().includes(q) || s.route.http_method.toLowerCase().includes(q)
          : false;
        if (!matchesName && !matchesSig && !matchesRoute) return false;
      }

      return true;
    });
  }, [symbols, activeCategory, filterQuery]);

  const basename = outline?.filepath ? outline.filepath.split('/').pop() : '';

  return (
    <div className={`nav-outline-pane density-${density}`} data-testid="navigator-outline-container">
      <div className="nav-outline-header">
        <div className="nav-outline-title-row">
          <div className="nav-outline-title">
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
              <line x1="8" y1="6" x2="21" y2="6" />
              <line x1="8" y1="12" x2="21" y2="12" />
              <line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" />
              <line x1="3" y1="12" x2="3.01" y2="12" />
              <line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
            <span>Symbols & Routes</span>
          </div>
          {outline && (
            <div className="nav-file-badge" title={outline.filepath}>
              <span className="file-name">{basename}</span>
            </div>
          )}
        </div>

        {outline && (
          <>
            <div className="nav-outline-search-bar">
              <svg className="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <input
                type="text"
                className="nav-outline-search-input"
                placeholder="Filter symbols..."
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
              />
              {filterQuery && (
                <button
                  type="button"
                  className="nav-outline-clear-btn"
                  onClick={() => setFilterQuery('')}
                  aria-label="Clear symbol search"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="nav-category-chips" role="tablist" aria-label="Symbol Category Filter">
              <button
                type="button"
                role="button"
                className={`category-chip ${activeCategory === 'all' ? 'active' : ''}`}
                onClick={() => setActiveCategory('all')}
              >
                All <span className="chip-count">{counts.all}</span>
              </button>
              <button
                type="button"
                role="button"
                className={`category-chip ${activeCategory === 'routes' ? 'active' : ''}`}
                onClick={() => setActiveCategory('routes')}
              >
                Routes <span className="chip-count">{counts.routes}</span>
              </button>
              <button
                type="button"
                role="button"
                className={`category-chip ${activeCategory === 'classes' ? 'active' : ''}`}
                onClick={() => setActiveCategory('classes')}
              >
                Classes <span className="chip-count">{counts.classes}</span>
              </button>
              <button
                type="button"
                role="button"
                className={`category-chip ${activeCategory === 'functions' ? 'active' : ''}`}
                onClick={() => setActiveCategory('functions')}
              >
                Functions <span className="chip-count">{counts.functions}</span>
              </button>
            </div>
          </>
        )}
      </div>

      <div className="nav-outline-content">
        {loading ? (
          <div className="nav-outline-skeleton" data-testid="outline-loading-skeleton">
            <div className="skeleton-item shimmer"></div>
            <div className="skeleton-item shimmer"></div>
            <div className="skeleton-item shimmer"></div>
            <div className="skeleton-item shimmer"></div>
          </div>
        ) : !outline ? (
          <div className="nav-empty-state">
            <div className="empty-icon">📂</div>
            <h4>No File Selected</h4>
            <p>Select a file from the tree to inspect its symbols and routes.</p>
          </div>
        ) : symbols.length === 0 ? (
          <div className="nav-empty-state">
            <div className="empty-icon">⚡</div>
            <h4>No Symbols Found</h4>
            <p>No symbols found in this file.</p>
          </div>
        ) : filteredSymbols.length === 0 ? (
          <div className="nav-empty-state">
            <h4>No Matching Symbols</h4>
            <p>No symbols match the current category and search filters.</p>
            <button
              type="button"
              className="nav-clear-filter-btn"
              onClick={() => {
                setActiveCategory('all');
                setFilterQuery('');
              }}
            >
              Reset Filters
            </button>
          </div>
        ) : (
          <div className="nav-symbol-list" role="list">
            {filteredSymbols.map((s) => {
              const isSelected = s.id === selectedSymbolId;
              const kindClass = getKindBadgeClass(s.kind);

              return (
                <div
                  key={s.id}
                  data-testid={`symbol-item-${s.id}`}
                  className={`nav-symbol-item ${isSelected ? 'active' : ''}`}
                  onClick={() => onSelectSymbol(s)}
                  role="listitem"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelectSymbol(s);
                    }
                  }}
                >
                  <div className="symbol-header-row">
                    <div className="symbol-name-col">
                      <span className={`symbol-kind-badge ${kindClass}`}>{s.kind}</span>
                      <span className="symbol-name-text" title={s.full_symbol || s.name}>
                        {s.name}
                      </span>
                    </div>

                    <div className="symbol-meta-col">
                      <span className="symbol-line-badge">
                        L{s.start_line}
                        {s.end_line && s.end_line !== s.start_line ? ` - L${s.end_line}` : ''}
                      </span>
                    </div>
                  </div>

                  {s.route && (
                    <div className="symbol-route-row">
                      <span className={`route-method-badge ${getMethodBadgeClass(s.route.http_method)}`}>
                        {s.route.http_method}
                      </span>
                      <span className="route-path-text" title={s.route.path_pattern}>
                        {s.route.path_pattern}
                      </span>
                      {s.route.framework && (
                        <span className="route-framework-tag">{s.route.framework}</span>
                      )}
                    </div>
                  )}

                  {s.signature && (
                    <div className="symbol-signature-snippet">
                      <code>{s.signature}</code>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
