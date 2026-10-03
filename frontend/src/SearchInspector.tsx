import { useState, useEffect } from 'react';
import type { FormEvent } from 'react';
import type { SearchHit } from './types';
import { useToast } from './ToastContext';
import { getKindBadgeClass } from './components/navigator/NavigatorOutline';

export interface SearchInspectorProps {
  onOpenInNavigator?: (repo: string, path: string, symbolId?: number, startLine?: number, endLine?: number) => void;
}

export function cleanKind(kind?: string): string {
  if (!kind) return '';
  const k = kind.toLowerCase();
  if (k.includes('class')) return 'class';
  if (k.includes('method')) return 'method';
  if (k.includes('func')) return 'func';
  if (k.includes('interface')) return 'interface';
  if (k.includes('struct')) return 'struct';
  if (k.includes('enum')) return 'enum';
  if (k.includes('module')) return 'module';
  return kind.replace(/_declaration|_item/g, '');
}

export default function SearchInspector({ onOpenInNavigator }: SearchInspectorProps = {}) {
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [type, setType] = useState('code');
  const [repo, setRepo] = useState('');
  const [limit, setLimit] = useState(5);
  const [searchMode, setSearchMode] = useState<'hybrid' | 'semantic' | 'lexical'>('hybrid');
  const [denseWeight, setDenseWeight] = useState(0.5);

  const [availableRepos, setAvailableRepos] = useState<string[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  useEffect(() => {
    const fetchRepos = async () => {
      try {
        const res = await fetch('/admin/api/repos');
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data)) {
            setAvailableRepos(data.map((r: any) => typeof r === 'string' ? r : r.name).filter(Boolean));
          }
        }
      } catch (e) {
        console.error('Failed to load repositories list:', e);
      }
    };
    fetchRepos();
  }, []);

  const runSearchTest = async (e?: FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setIsSearching(true);
    setError(null);
    setResults(null);

    try {
      const payload: Record<string, any> = {
        query: query.trim(),
        type,
        repo: repo.trim() || null,
        limit,
        search_mode: searchMode,
        dense_weight: searchMode === 'hybrid' ? denseWeight : (searchMode === 'semantic' ? 1.0 : 0.0)
      };

      const res = await fetch('/admin/api/search/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Search failed');

      setResults(data.results || []);
    } catch (err: any) {
      setError(err.message);
      toast.error('Search failed: ' + err.message);
    } finally {
      setIsSearching(false);
    }
  };

  const handleCopyCode = async (idx: number, content: string) => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
        setCopiedIdx(idx);
        setTimeout(() => setCopiedIdx(null), 2000);
      }
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  };

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <h2><i className="fa-solid fa-magnifying-glass"></i> Live Hybrid Search Inspector</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
          Test hybrid, semantic, and lexical search results with configurable scoring calibration and AST context.
        </p>

        {/* Search Mode Segmented Control */}
        <div style={{ marginTop: '16px' }}>
          <div className="search-mode-segmented" role="group" aria-label="Search Mode">
            <button
              type="button"
              className={`search-mode-btn ${searchMode === 'hybrid' ? 'active' : ''}`}
              onClick={() => setSearchMode('hybrid')}
              data-testid="mode-hybrid-btn"
            >
              <i className="fa-solid fa-code-merge"></i> Hybrid Fusion
            </button>
            <button
              type="button"
              className={`search-mode-btn ${searchMode === 'semantic' ? 'active' : ''}`}
              onClick={() => setSearchMode('semantic')}
              data-testid="mode-semantic-btn"
            >
              <i className="fa-solid fa-brain"></i> Semantic (Dense)
            </button>
            <button
              type="button"
              className={`search-mode-btn ${searchMode === 'lexical' ? 'active' : ''}`}
              onClick={() => setSearchMode('lexical')}
              data-testid="mode-lexical-btn"
            >
              <i className="fa-solid fa-font"></i> Lexical (BM25)
            </button>
          </div>
        </div>

        {/* Configurable Hybrid Split Slider (only shown in hybrid mode) */}
        {searchMode === 'hybrid' && (
          <div className="hybrid-slider-container">
            <div className="hybrid-slider-header">
              <span><strong>Hybrid Scoring Split:</strong></span>
              <span className="hybrid-split-value">
                Semantic: {Math.round(denseWeight * 100)}% / Lexical: {Math.round((1 - denseWeight) * 100)}%
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={denseWeight}
              onChange={e => setDenseWeight(parseFloat(e.target.value))}
              className="hybrid-range-input"
              aria-label="Hybrid dense weight slider"
            />
            <div className="hybrid-presets">
              <button
                type="button"
                className={`btn-preset ${denseWeight === 0.5 ? 'active' : ''}`}
                onClick={() => setDenseWeight(0.5)}
              >
                Balanced (50/50)
              </button>
              <button
                type="button"
                className={`btn-preset ${denseWeight === 0.7 ? 'active' : ''}`}
                onClick={() => setDenseWeight(0.7)}
              >
                Semantic Bias (70/30)
              </button>
              <button
                type="button"
                className={`btn-preset ${denseWeight === 0.3 ? 'active' : ''}`}
                onClick={() => setDenseWeight(0.3)}
              >
                Keyword Bias (30/70)
              </button>
              <button
                type="button"
                className={`btn-preset ${denseWeight === 1.0 ? 'active' : ''}`}
                onClick={() => setDenseWeight(1.0)}
              >
                Pure Semantic (100/0)
              </button>
              <button
                type="button"
                className={`btn-preset ${denseWeight === 0.0 ? 'active' : ''}`}
                onClick={() => setDenseWeight(0.0)}
              >
                Pure Keyword (0/100)
              </button>
            </div>
          </div>
        )}

        <form onSubmit={runSearchTest} style={{ marginTop: '14px' }}>
          <div className="form-row">
            <div className="form-group" style={{ flex: 2 }}>
              <label>Search Query</label>
              <input
                type="text"
                required
                placeholder="e.g. JWT token authentication or chunk_markdown"
                value={query}
                onChange={e => setQuery(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Target Type</label>
              <select aria-label="Target Type" value={type} onChange={e => setType(e.target.value)}>
                <option value="code">Code Snippets &amp; Symbols</option>
                <option value="doc">Documentation &amp; Notes</option>
              </select>
            </div>
            <div className="form-group">
              <label>Repo Filter</label>
              <input
                type="text"
                list="search-inspector-repos"
                placeholder="All Repos"
                value={repo}
                onChange={e => setRepo(e.target.value)}
              />
              <datalist id="search-inspector-repos">
                <option value="">All Repos</option>
                {availableRepos.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </datalist>
            </div>
            <div className="form-group" style={{ maxWidth: '110px' }}>
              <label>Limit</label>
              <select aria-label="Result Limit" value={limit} onChange={e => setLimit(Number(e.target.value))}>
                <option value={5}>Top 5</option>
                <option value={10}>Top 10</option>
                <option value={25}>Top 25</option>
              </select>
            </div>
            <div className="form-group search-form-btn-group" style={{ alignSelf: 'flex-end' }}>
              <button type="submit" className="btn btn-primary" disabled={isSearching}>
                {isSearching ? (
                  <>
                    <svg
                      className="nav-svg-spinner animate-spin"
                      data-testid="search-inspector-spinner"
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      style={{ marginRight: '6px', verticalAlign: 'middle', display: 'inline-block' }}
                    >
                      <circle cx="12" cy="12" r="10" stroke="rgba(255,255,255,0.25)" strokeWidth="3" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                    Searching...
                  </>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                    Search
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        <div style={{ marginTop: '20px' }}>
          {isSearching && <div className="empty-state">Running hybrid retrieval with Normalized Weighted Fusion...</div>}
          {error && <div className="empty-state" style={{ color: 'var(--danger)' }}>Search error: {error}</div>}
          {!isSearching && !error && results === null && (
            <div className="empty-state">Enter a query above to test hybrid retrieval.</div>
          )}
          {!isSearching && !error && results !== null && results.length === 0 && (
            <div className="empty-state">No matching results found in index.</div>
          )}
          {!isSearching && !error && results !== null && results.length > 0 && (
            results.map((hit, idx) => {
              const p = hit.payload;
              const hasDense = hit.dense_score !== undefined && hit.dense_score !== null;
              const hasSparse = hit.sparse_score !== undefined && hit.sparse_score !== null;
              const displayKind = cleanKind(p.kind);

              return (
                <div className="search-hit-card" key={idx}>
                  <div className="search-hit-header">
                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                      <span className="badge badge-primary">{p.repo}</span>
                      <strong>{p.rel_path}</strong>
                      {displayKind && (
                        <span className={`badge ${getKindBadgeClass(displayKind)}`}>
                          {displayKind}
                        </span>
                      )}
                      {p.symbol && <span className="badge badge-accent">{p.full_symbol || p.symbol}</span>}
                      <span className="text-muted" style={{ fontSize: '0.8rem' }}>(Lines {p.start_line}-{p.end_line})</span>
                      {p.github_url && (() => {
                        let hostname = '';
                        try {
                          hostname = new URL(p.github_url).hostname.toLowerCase();
                        } catch {
                          // Ignore invalid URL
                        }
                        const u = p.github_url.toLowerCase();
                        let label = 'View Source';
                        let icon = 'fa-solid fa-code-branch';
                        if (hostname === 'gitlab.com' || hostname.endsWith('.gitlab.com') || u.includes('/-/blob/')) {
                          label = 'View on GitLab';
                          icon = 'fa-brands fa-gitlab';
                        } else if (hostname.includes('gitea') || hostname.includes('forgejo')) {
                          label = 'View on Gitea';
                          icon = 'fa-solid fa-mug-hot';
                        } else if (hostname === 'bitbucket.org' || hostname.endsWith('.bitbucket.org')) {
                          label = 'View on Bitbucket';
                          icon = 'fa-brands fa-bitbucket';
                        } else if (hostname === 'github.com' || hostname.endsWith('.github.com')) {
                          label = 'View on GitHub';
                          icon = 'fa-brands fa-github';
                        }
                        return (
                          <a href={p.github_url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontSize: '0.8rem' }}>
                            <i className={icon} style={{ marginRight: '4px' }}></i>{label}
                          </a>
                        );
                      })()}
                    </div>

                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
                      {/* Score Badges */}
                      <span className="badge badge-success" title="Overall relevance score">
                        Score: {(hit.score * 100).toFixed(1)}% ({hit.score.toFixed(4)})
                      </span>
                      {hasDense && (
                        <span className="badge badge-info" title="Dense semantic vector similarity">
                          Semantic: {((hit.dense_score || 0) * 100).toFixed(1)}%
                        </span>
                      )}
                      {hasSparse && (
                        <span className="badge badge-warning" title="Sparse lexical BM25 similarity">
                          Lexical: {((hit.sparse_score || 0) * 100).toFixed(1)}%
                        </span>
                      )}

                      {/* Header Actions */}
                      <div className="search-hit-actions">
                        {onOpenInNavigator && p.rel_path && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-xs"
                            onClick={() => onOpenInNavigator(p.repo, p.rel_path, p.ast_symbol_id, p.start_line, p.end_line)}
                            title="Open in Code Navigator"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '2px 8px' }}
                          >
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                              <polyline points="15 3 21 3 21 9" />
                              <line x1="10" y1="14" x2="21" y2="3" />
                            </svg>
                            Open in Navigator
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-secondary btn-xs"
                          onClick={() => handleCopyCode(idx, p.content)}
                          title="Copy snippet"
                          style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '2px 8px' }}
                        >
                          {copiedIdx === idx ? (
                            <>
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                              Copied
                            </>
                          ) : (
                            <>
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                              </svg>
                              Copy
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* AST Signature snippet if present */}
                  {p.signature && (
                    <div className="search-hit-signature">
                      <span style={{ opacity: 0.7, marginRight: '6px' }}>Signature:</span>
                      <code>{p.signature}</code>
                    </div>
                  )}

                  <pre className="search-hit-code">{p.content}</pre>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
