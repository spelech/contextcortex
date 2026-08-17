import { useState } from 'react';
import type { FormEvent } from 'react';
import type { SearchHit } from './types';
import { useToast } from './ToastContext';

export default function SearchInspector() {
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [type, setType] = useState('code');
  const [repo, setRepo] = useState('');
  
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runSearchTest = async (e: FormEvent) => {
    e.preventDefault();
    setIsSearching(true);
    setError(null);
    setResults(null);

    try {
      const res = await fetch('/admin/api/search/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), type, repo: repo.trim() || null })
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

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <h2><i className="fa-solid fa-magnifying-glass"></i> Live Hybrid Search Inspector</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>Test RRF search results across code and documentation directly from the browser.</p>

        <form onSubmit={runSearchTest} style={{ marginTop: '16px' }}>
          <div className="form-row">
            <div className="form-group" style={{ flex: 2 }}>
              <label>Search Query</label>
              <input type="text" required placeholder="e.g. JWT token authentication or chunk_markdown" value={query} onChange={e => setQuery(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Target Type</label>
              <select value={type} onChange={e => setType(e.target.value)}>
                <option value="code">Code Snippets & Symbols</option>
                <option value="doc">Documentation & Notes</option>
              </select>
            </div>
            <div className="form-group">
              <label>Repo Filter (Optional)</label>
              <input type="text" placeholder="All Repos" value={repo} onChange={e => setRepo(e.target.value)} />
            </div>
            <div className="form-group search-form-btn-group" style={{ alignSelf: 'flex-end' }}>
              <button type="submit" className="btn btn-primary" disabled={isSearching}>
                {isSearching ? <><i className="fa-solid fa-spinner fa-spin"></i> Searching...</> : <><i className="fa-solid fa-play"></i> Search</>}
              </button>
            </div>
          </div>
        </form>

        <div style={{ marginTop: '20px' }}>
          {isSearching && <div className="empty-state">Running hybrid retrieval with Reciprocal Rank Fusion (RRF)...</div>}
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
              return (
                <div className="search-hit-card" key={idx}>
                  <div className="search-hit-header">
                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                      <span className="badge badge-primary">{p.repo}</span>
                      <strong>{p.rel_path}</strong>
                      {p.symbol && <span className="badge badge-accent">{p.symbol}</span>}
                      <span className="text-muted" style={{ fontSize: '0.8rem' }}>(Lines {p.start_line}-{p.end_line})</span>
                      {p.github_url && (() => {
                        const u = p.github_url.toLowerCase();
                        let label = 'View Source';
                        let icon = 'fa-solid fa-code-branch';
                        if (u.includes('gitlab') || u.includes('/-/blob/')) {
                          label = 'View on GitLab';
                          icon = 'fa-brands fa-gitlab';
                        } else if (u.includes('gitea') || u.includes('forgejo')) {
                          label = 'View on Gitea';
                          icon = 'fa-solid fa-mug-hot';
                        } else if (u.includes('bitbucket')) {
                          label = 'View on Bitbucket';
                          icon = 'fa-brands fa-bitbucket';
                        } else if (u.includes('github.com')) {
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
                    <div>
                      <span className="badge badge-success">RRF Score: {hit.score.toFixed(4)}</span>
                    </div>
                  </div>
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
