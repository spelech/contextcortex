import type { VectorStoreConfig } from '../../types';

interface VectorStoreSettingsProps {
  vectorStore: VectorStoreConfig | null;
  isLoadingVs: boolean;
  testFeedback: { success: boolean; message: string } | null;
  vsProvider: 'qdrant' | 'chroma';
  vsMode: 'embedded' | 'remote';
  vsStoragePath: string;
  setVsStoragePath: (val: string) => void;
  vsUrl: string;
  setVsUrl: (val: string) => void;
  vsCollection: string;
  setVsCollection: (val: string) => void;
  isTestingVs: boolean;
  isSwitchingVs: boolean;
  onProviderChange: (provider: 'qdrant' | 'chroma') => void;
  onModeChange: (mode: 'embedded' | 'remote') => void;
  onTestConnection: () => void;
  onSwitchBackend: () => void;
}

export function VectorStoreSettings({
  vectorStore,
  isLoadingVs,
  testFeedback,
  vsProvider,
  vsMode,
  vsStoragePath,
  setVsStoragePath,
  vsUrl,
  setVsUrl,
  vsCollection,
  setVsCollection,
  isTestingVs,
  isSwitchingVs,
  onProviderChange,
  onModeChange,
  onTestConnection,
  onSwitchBackend,
}: VectorStoreSettingsProps) {
  return (
    <div className="glass-card">
      <h2><i className="fa-solid fa-database"></i> Vector Database Engine</h2>
      <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
        Configure and switch between vector database backends (Qdrant &amp; ChromaDB). Switching backends updates system metadata and triggers full re-indexing.
      </p>

      <div className="vs-config-layout">
        {/* Active Backend Status Box */}
        <div className="vs-box">
          <h3><i className="fa-solid fa-circle-nodes"></i> Active Vector Backend</h3>
          {isLoadingVs && !vectorStore ? (
            <p className="text-muted">Loading vector store configuration...</p>
          ) : vectorStore ? (
            <div className="specs-list" style={{ marginTop: 0 }}>
              <div className="spec-row">
                <span>Provider:</span>
                <span className="badge badge-accent">
                  {vectorStore.provider === 'chroma' ? 'ChromaDB' : 'Qdrant'}
                </span>
              </div>
              <div className="spec-row">
                <span>Operating Mode:</span>
                <span className="badge badge-primary">
                  {vectorStore.mode === 'embedded' ? 'Embedded Disk' : 'Remote Server'}
                </span>
              </div>
              <div className="spec-row">
                <span>{vectorStore.mode === 'embedded' ? 'Storage Path:' : 'Server URL:'}</span>
                <code>{vectorStore.mode === 'embedded' ? (vectorStore.storage_path || 'data/qdrant_db') : (vectorStore.url || 'http://localhost:6333')}</code>
              </div>
              <div className="spec-row">
                <span>Collection Name:</span>
                <code>{vectorStore.collection || 'knowledge_rag_v1'}</code>
              </div>
              <div className="spec-row">
                <span>Points Count:</span>
                <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                  {(vectorStore.points_count || 0).toLocaleString()}
                </span>
              </div>
              <div className="spec-row">
                <span>Health Status:</span>
                {vectorStore.healthy ? (
                  <span className="badge badge-success">
                    <i className="fa-solid fa-circle-check"></i> Healthy
                  </span>
                ) : (
                  <span className="badge badge-danger" title={vectorStore.health_message || 'Unhealthy'}>
                    <i className="fa-solid fa-triangle-exclamation"></i> {vectorStore.health_message ? (vectorStore.health_message.length > 35 ? vectorStore.health_message.slice(0, 35) + '...' : vectorStore.health_message) : 'Unhealthy'}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <p className="text-muted">No vector store configuration found.</p>
          )}
        </div>

        {/* Switch Backend Form Box */}
        <div className="vs-box">
          <h3><i className="fa-solid fa-sliders"></i> Configure &amp; Switch Backend</h3>
          
          {testFeedback && (
            <div className={`vs-feedback-banner ${testFeedback.success ? 'feedback-success' : 'feedback-error'}`}>
              <i className={testFeedback.success ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-exclamation'}></i>
              <span>{testFeedback.message}</span>
            </div>
          )}

          <form onSubmit={e => { e.preventDefault(); onSwitchBackend(); }}>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="vs-provider">Vector Store Provider</label>
                <select
                  id="vs-provider"
                  value={vsProvider}
                  onChange={e => onProviderChange(e.target.value as any)}
                >
                  <option value="qdrant">Qdrant (Hybrid Dense + BM25)</option>
                  <option value="chroma">ChromaDB (Dense Vectors)</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="vs-mode">Operating Mode</label>
                <select
                  id="vs-mode"
                  value={vsMode}
                  onChange={e => onModeChange(e.target.value as any)}
                >
                  <option value="embedded">Embedded Disk Storage</option>
                  <option value="remote">Remote Server URL</option>
                </select>
              </div>
            </div>

            {vsMode === 'embedded' ? (
              <div className="form-group">
                <label htmlFor="vs-storage-path">Storage Directory Path</label>
                <input
                  id="vs-storage-path"
                  type="text"
                  value={vsStoragePath}
                  onChange={e => setVsStoragePath(e.target.value)}
                  placeholder={vsProvider === 'chroma' ? 'data/chroma_db' : 'data/qdrant_db'}
                />
              </div>
            ) : (
              <div className="form-group">
                <label htmlFor="vs-url">Remote Server URL</label>
                <input
                  id="vs-url"
                  type="text"
                  value={vsUrl}
                  onChange={e => setVsUrl(e.target.value)}
                  placeholder={vsProvider === 'chroma' ? 'http://localhost:8000' : 'http://localhost:6333'}
                />
              </div>
            )}

            <div className="form-group">
              <label htmlFor="vs-collection">Collection Name</label>
              <input
                id="vs-collection"
                type="text"
                value={vsCollection}
                onChange={e => setVsCollection(e.target.value)}
                placeholder="knowledge_rag_v1"
              />
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onTestConnection}
                disabled={isTestingVs || isSwitchingVs}
              >
                {isTestingVs ? (
                  <><i className="fa-solid fa-spinner fa-spin"></i> Testing Connection...</>
                ) : (
                  <><i className="fa-solid fa-plug"></i> Test Connection</>
                )}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={onSwitchBackend}
                disabled={isTestingVs || isSwitchingVs}
              >
                {isSwitchingVs ? (
                  <><i className="fa-solid fa-spinner fa-spin"></i> Switching Backend...</>
                ) : (
                  <><i className="fa-solid fa-arrows-rotate"></i> Save &amp; Switch Backend</>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
