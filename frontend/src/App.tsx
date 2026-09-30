import { useState, useEffect } from 'react';
import './index.css';
import Overview from './Overview';
import GitRepoManager from './GitRepoManager';
import FilesAndStorage from './FilesAndStorage';
import SearchInspector from './SearchInspector';
import Settings from './Settings';
import DiagnosticsViewer from './DiagnosticsViewer';
import CodeNavigator from './CodeNavigator';
import IngestionCatalogViewer from './IngestionCatalogViewer';
import type { Stats } from './types';

function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);

  const loadStats = async () => {
    try {
      const response = await fetch('/admin/api/stats');
      if (!response.ok) return;
      const data = await response.json();
      setStats(data);
    } catch (e) {
      console.error('Error loading stats:', e);
    }
  };

  useEffect(() => {
    loadStats();
    const interval = setInterval(loadStats, 8000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      <div className="dashboard-container">
        <header className="dashboard-header">
          <div className="header-brand">
            <div className="header-logo">
              <i className="fa-solid fa-layer-group logo-icon"></i>
              <div className="header-title">
                <h1>ContextCortex</h1>
                <span className="badge badge-primary">v2.16.0</span>
              </div>
            </div>
          </div>

          <div className="header-status">
            <div className="status-item">
              <span className="label">Engine State</span>
              <span className="value">
                {stats?.is_indexing ? (
                  <><span className="indicator indexing"></span> Syncing...</>
                ) : (
                  <><span className="indicator online"></span> Idle</>
                )}
              </span>
            </div>
            <div className="status-item">
              <span className="label">Vector Backend</span>
              <span className="value">
                <i className="fa-solid fa-database" style={{ marginRight: '5px' }}></i>
                <span>
                  {stats?.vector_store_provider === 'chroma' ? 'ChromaDB' : 'Qdrant'} ({(stats?.vector_store_mode || 'embedded') === 'embedded' ? 'Embedded' : 'Remote'})
                </span>
                {stats?.vector_db_status && (
                  <span
                    className={`badge ${stats.vector_db_status === 'Healthy' ? 'badge-success' : 'badge-danger'}`}
                    style={{ marginLeft: '6px', fontSize: '0.75rem', padding: '2px 6px' }}
                    data-testid="vector-db-status-badge"
                  >
                    {stats.vector_db_status}
                  </span>
                )}
              </span>
            </div>
            <div className="status-item header-collection-item">
              <span className="label">Collection</span>
              <span className="value code">{stats?.vector_store_collection || 'knowledge_rag_v1'}</span>
            </div>
          </div>

          <button
            className="menu-toggle-btn"
            aria-label="Toggle navigation"
            onClick={() => setIsMobileNavOpen(!isMobileNavOpen)}
          >
            <i className={`fa-solid ${isMobileNavOpen ? 'fa-xmark' : 'fa-bars'}`}></i>
          </button>
        </header>

        <nav className={`dashboard-nav ${isMobileNavOpen ? 'drawer-open' : ''}`} aria-label="Main Navigation">
          <button className={`nav-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => { setActiveTab('overview'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-chart-pie"></i>
            <span>Overview</span>
          </button>
          <button className={`nav-tab ${activeTab === 'navigator' || activeTab === 'topology' ? 'active' : ''}`} onClick={() => { setActiveTab('navigator'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-code-fork"></i>
            <span>Navigator</span>
          </button>
          <button className={`nav-tab ${activeTab === 'git-repos' ? 'active' : ''}`} onClick={() => { setActiveTab('git-repos'); setIsMobileNavOpen(false); }}>
            <i className="fa-brands fa-github"></i>
            <span>Git Repositories</span>
          </button>
          <button className={`nav-tab ${activeTab === 'files-storage' ? 'active' : ''}`} onClick={() => { setActiveTab('files-storage'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-folder-tree"></i>
            <span>Files &amp; Storage</span>
          </button>
          <button className={`nav-tab ${activeTab === 'ingestion-catalog' ? 'active' : ''}`} onClick={() => { setActiveTab('ingestion-catalog'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-book-bookmark"></i>
            <span>Ingestion Catalog</span>
          </button>
          <button className={`nav-tab ${activeTab === 'search-inspector' ? 'active' : ''}`} onClick={() => { setActiveTab('search-inspector'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-magnifying-glass"></i>
            <span>Search & Inspector</span>
          </button>
          <button className={`nav-tab ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => { setActiveTab('settings'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-gear"></i>
            <span>Settings</span>
          </button>
          <button className={`nav-tab ${activeTab === 'diagnostics' ? 'active' : ''}`} onClick={() => { setActiveTab('diagnostics'); setIsMobileNavOpen(false); }}>
            <i className="fa-solid fa-terminal"></i>
            <span>Diagnostics & Logs</span>
          </button>
        </nav>

        <main className="dashboard-main">
          {activeTab === 'overview' && <Overview stats={stats} refreshStats={loadStats} />}
          {(activeTab === 'navigator' || activeTab === 'topology') && <CodeNavigator />}
          {activeTab === 'git-repos' && <GitRepoManager refreshStats={loadStats} />}
          {activeTab === 'files-storage' && <FilesAndStorage refreshStats={loadStats} />}
          {activeTab === 'ingestion-catalog' && <IngestionCatalogViewer />}
          {activeTab === 'search-inspector' && <SearchInspector />}
          {activeTab === 'settings' && <Settings stats={stats} refreshStats={loadStats} />}
          {activeTab === 'diagnostics' && <DiagnosticsViewer />}
        </main>



        <footer className="dashboard-footer">
          <p>ContextCortex MCP &bull; Universal Code & Knowledge RAG &bull; 2026</p>
        </footer>
      </div>
    </>
  );
}

export default App;
