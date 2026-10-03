import React, { useState, useEffect, useRef, useCallback } from 'react';
import type { OmniSearchResultItem, OmniSearchResponse, OmniSearchMatchKind } from './types';

export interface NavigatorOmniSearchProps {
  repo: string;
  onSelectResult: (result: OmniSearchResultItem) => void;
  placeholder?: string;
}

export function getMatchBadgeClass(type: OmniSearchMatchKind): string {
  switch (type) {
    case 'symbol':
      return 'badge-symbol';
    case 'code':
      return 'badge-code';
    case 'file':
      return 'badge-file';
    case 'route':
      return 'badge-route';
    case 'doc':
      return 'badge-doc';
    default:
      return 'badge-default';
  }
}

export function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query || !query.trim() || !text) {
    return <>{text}</>;
  }
  const trimmed = query.trim();
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(regex);
  if (parts.length <= 1) {
    return <>{text}</>;
  }
  return (
    <>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {parts.map((part, idx) =>
          part.toLowerCase() === trimmed.toLowerCase() ? (
            <mark key={idx} className="nav-omni-match">
              {part}
            </mark>
          ) : (
            <React.Fragment key={idx}>{part}</React.Fragment>
          )
        )}
      </span>
    </>
  );
}

export function formatKind(kind?: string): string {
  if (!kind) return '';
  const k = kind.toLowerCase();
  if (k.includes('method')) return 'method';
  if (k.includes('func')) return 'func';
  if (k.includes('class')) return 'class';
  if (k.includes('interface')) return 'interface';
  if (k.includes('struct')) return 'struct';
  if (k.includes('type')) return 'type';
  if (k.includes('enum')) return 'enum';
  if (k.includes('property') || k.includes('field')) return 'prop';
  if (k === 'route') return 'route';
  if (k === 'file') return 'file';
  if (k === 'code') return 'code';
  return k.replace(/_declaration|_definition|_specifier/g, '');
}

export function formatDisplayPath(path: string): string {
  if (path.includes('://')) {
    return path.split('://')[1];
  }
  return path;
}

export const NavigatorOmniSearch: React.FC<NavigatorOmniSearchProps> = ({
  repo,
  onSelectResult,
  placeholder = 'Search files, symbols, routes, or code text...',
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<OmniSearchResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Global Ctrl+K / Cmd+K listener
  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, []);

  // Debounced search
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setIsOpen(false);
      setActiveIndex(-1);
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `/admin/api/navigator/omni-search?repo=${encodeURIComponent(repo)}&q=${encodeURIComponent(trimmed)}&limit=25`,
          { signal: controller.signal }
        );
        if (res.ok) {
          const data: OmniSearchResponse = await res.json();
          setResults(data.matches || []);
          setIsOpen(true);
          setActiveIndex(-1);
        }
      } catch (err: any) {
        if (err.name !== 'AbortError') {
          console.error('Omni-search error:', err);
        }
      } finally {
        setLoading(false);
      }
    }, 150);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, repo]);

  // Click outside to dismiss
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen || results.length === 0) {
      if (e.key === 'ArrowDown' && results.length > 0) {
        setIsOpen(true);
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev < results.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : results.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < results.length) {
        handleSelect(results[activeIndex]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setIsOpen(false);
    }
  };

  const handleSelect = useCallback(
    (item: OmniSearchResultItem) => {
      setIsOpen(false);
      setQuery('');
      setResults([]);
      onSelectResult(item);
    },
    [onSelectResult]
  );

  const handleClear = () => {
    setQuery('');
    setResults([]);
    setIsOpen(false);
    setActiveIndex(-1);
    inputRef.current?.focus();
  };

  return (
    <div className="nav-omni-container" ref={containerRef} data-testid="navigator-omni-search">
      <div className="nav-omni-input-wrapper">
        <svg
          className="nav-omni-search-icon"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>

        <input
          ref={inputRef}
          type="text"
          className="nav-omni-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (results.length > 0) setIsOpen(true);
          }}
          placeholder={placeholder}
          aria-label="Omni-Search"
          aria-autocomplete="list"
          aria-expanded={isOpen}
        />

        {!query && (
          <span className="nav-omni-kbd" title="Shortcut: Ctrl+K / ⌘K" aria-hidden="true">
            Ctrl K
          </span>
        )}

        {loading && (
          <svg
            className="nav-omni-spinner animate-spin"
            data-testid="omni-search-spinner"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle cx="12" cy="12" r="10" stroke="rgba(8, 145, 178, 0.25)" strokeWidth="3" />
            <path
              d="M12 2a10 10 0 0 1 10 10"
              stroke="var(--primary, #0891b2)"
              strokeWidth="3"
              strokeLinecap="round"
            />
          </svg>
        )}

        {query && (
          <button
            type="button"
            className="nav-omni-clear-btn"
            onClick={handleClear}
            title="Clear search"
            aria-label="Clear Search"
          >
            ✕
          </button>
        )}
      </div>

      {/* Floating Centered Overlay */}
      {isOpen && (
        <div
          className="nav-omni-dropdown"
          data-testid="nav-omni-dropdown"
          role="listbox"
        >
          <div className="nav-omni-dropdown-header">
            <span>
              Matches ({results.length})
            </span>
            <span className="nav-omni-hint">↑↓ Navigate • Enter Select • Esc Close</span>
          </div>

          {results.length === 0 && !loading && (
            <div className="nav-omni-empty">
              No matching files, symbols, or code found for "{query}"
            </div>
          )}

          <div className="nav-omni-list">
            {results.map((item, index) => {
              const isSelected = index === activeIndex;
              const badgeClass = getMatchBadgeClass(item.type);

              // Determine container prefix if full_symbol has parent
              let containerPrefix = '';
              let symbolName = item.name;
              if (item.full_symbol && item.full_symbol.includes('.') && item.type === 'symbol') {
                const lastDot = item.full_symbol.lastIndexOf('.');
                containerPrefix = item.full_symbol.substring(0, lastDot + 1);
                symbolName = item.full_symbol.substring(lastDot + 1);
              }

              return (
                <div
                  key={item.id}
                  className={`nav-omni-item ${isSelected ? 'active' : ''}`}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                  aria-selected={isSelected}
                  title={item.full_symbol || item.name}
                >
                  <div className="nav-omni-item-top">
                    <div className="nav-omni-item-title-group">
                      <span className={`nav-omni-badge ${badgeClass}`}>
                        {item.type.toUpperCase()}
                      </span>
                      {containerPrefix && (
                        <span className="nav-omni-item-container" title={containerPrefix}>
                          <HighlightMatch text={containerPrefix} query={query} />
                        </span>
                      )}
                      <span className="nav-omni-item-name" title={item.full_symbol || item.name}>
                        <HighlightMatch text={symbolName} query={query} />
                      </span>
                      {item.kind && item.kind !== item.type && (
                        <span className="nav-omni-item-kind" title={`Kind: ${item.kind}`}>
                          {formatKind(item.kind)}
                        </span>
                      )}
                    </div>
                    <span className="nav-omni-score-pill" title={item.score_label}>
                      {item.score_label}
                    </span>
                  </div>

                  <div className="nav-omni-item-bottom">
                    <span className="nav-omni-item-path" title={item.filepath}>
                      <HighlightMatch text={formatDisplayPath(item.filepath)} query={query} />
                      {item.start_line > 0 && (
                        <span className="nav-omni-line-badge">:{item.start_line}</span>
                      )}
                    </span>
                    {item.preview && item.preview !== item.name && (
                      <>
                        <span className="nav-omni-sep" aria-hidden="true">•</span>
                        <span className="nav-omni-item-preview" title={item.preview}>
                          <HighlightMatch text={item.preview} query={query} />
                        </span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
