import type { Stats } from './types';
import { useToast } from './ToastContext';

export default function Overview({ stats, refreshStats }: { stats: Stats | null, refreshStats: () => void }) {
  const toast = useToast();

  if (!stats) return <div className="tab-content active"><p>Loading...</p></div>;

  const triggerReindex = async () => {
    try {
      const res = await fetch('/admin/api/reindex', { method: 'POST' });
      if (!res.ok) {
         const data = await res.json().catch(() => ({}));
         throw new Error(data.error || 'Failed to trigger reindex');
      }
      toast.success('Re-indexing triggered successfully');
      refreshStats();
    } catch (e: any) {
      toast.error('Reindex error: ' + e.message);
    }
  };

  return (
    <div className="tab-content active">
      <div className="overview-grid">
        <div className="glass-card stat-metric">
          <div className="metric-icon"><i className="fa-brands fa-github"></i></div>
          <div className="metric-info">
            <span className="stat-number">{(stats.repos_count ?? (stats as any).git_repos ?? 0).toLocaleString()}</span>
            <span className="stat-label">Git Repositories</span>
          </div>
        </div>
        <div className="glass-card stat-metric">
          <div className="metric-icon"><i className="fa-solid fa-code"></i></div>
          <div className="metric-info">
            <span className="stat-number">{(stats.symbols_count || 0).toLocaleString()}</span>
            <span className="stat-label">AST Code Symbols</span>
          </div>
        </div>
        <div className="glass-card stat-metric">
          <div className="metric-icon"><i className="fa-solid fa-file-code"></i></div>
          <div className="metric-info">
            <span className="stat-number">{(stats.files_count || 0).toLocaleString()}</span>
            <span className="stat-label">Indexed Files</span>
          </div>
        </div>
        <div className="glass-card stat-metric">
          <div className="metric-icon"><i className="fa-solid fa-network-wired"></i></div>
          <div className="metric-info">
            <span className="stat-number">{(stats.points_count || 0).toLocaleString()}</span>
            <span className="stat-label">
              {(stats.vector_store_provider || 'Qdrant').toUpperCase()} ({(stats.vector_store_mode || 'embedded') === 'embedded' ? 'Embedded' : 'Remote'}) Vectors
            </span>
          </div>
        </div>
      </div>

      <div className="two-col-layout" style={{ marginTop: '20px' }}>
        <div className="glass-card">
          <h2><i className="fa-solid fa-server"></i> System & Embedding Specs</h2>
          <div className="specs-list">
            <div className="spec-row">
              <span>Vector Database:</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="badge badge-accent">
                  {stats.vector_store_provider === 'chroma' ? 'ChromaDB' : 'Qdrant'} ({(stats.vector_store_mode || 'embedded') === 'embedded' ? 'Embedded Disk' : 'Remote Server'})
                </span>
                {stats.vector_db_status && (
                  <span
                    className={`badge ${stats.vector_db_status === 'Healthy' ? 'badge-success' : 'badge-danger'}`}
                    data-testid="overview-vector-db-status"
                  >
                    {stats.vector_db_status}
                  </span>
                )}
              </div>
            </div>
            <div className="spec-row">
              <span>Dense Embedding Model:</span>
              <code>{stats.dense_model || 'bge-small-en-v1.5 (384d)'}</code>
            </div>
            <div className="spec-row">
              <span>Sparse BM25 Model:</span>
              <code>{stats.sparse_model ? `${stats.sparse_model} (FastEmbed)` : 'Qdrant/bm25 (FastEmbed)'}</code>
            </div>
            <div className="spec-row">
              <span>Retrieval Strategy:</span>
              <span className="badge badge-accent">
                {stats.vector_store_provider === 'chroma'
                  ? 'Dense Vector Cosine Similarity'
                  : 'Dense + BM25 Reciprocal Rank Fusion (RRF)'}
              </span>
            </div>

            <div className="spec-row">
              <span>AST Chunker:</span>
              <span>Tree-sitter AST (Classes, Functions, Methods)</span>
            </div>
            <div className="spec-row">
              <span>Last Global Index:</span>
              <span className="code">{stats.last_indexed || 'Never'}</span>
            </div>
          </div>
          <div style={{ marginTop: '20px' }}>
            <button 
              className="btn btn-primary" 
              onClick={triggerReindex} 
              disabled={stats.is_indexing}
            >
              {stats.is_indexing ? (
                <><i className="fa-solid fa-spinner fa-spin"></i> Syncing...</>
              ) : (
                <><i className="fa-solid fa-arrows-rotate"></i> Reindex All Sources</>
              )}
            </button>
          </div>
        </div>

        <div className="glass-card">
          <h2><i className="fa-solid fa-tags"></i> Top Extracted Topics & Symbols</h2>
          <div className="tag-cloud">
            {(!stats.top_keywords || stats.top_keywords.length === 0) ? (
              <span className="text-muted">No topics extracted yet. Sync repositories to populate.</span>
            ) : (
              stats.top_keywords.map(kw => (
                <span key={kw} className="topic-tag">{kw}</span>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
