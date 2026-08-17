import { useState, useEffect } from 'react';
import './index.css';
import Overview from './Overview';
import GitRepoManager from './GitRepoManager';
import LocalPathManager from './LocalPathManager';
import SearchInspector from './SearchInspector';
import Settings from './Settings';
import DiagnosticsViewer from './DiagnosticsViewer';
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
      <div className="background-decor">
        <div className="circle circle-1"></div>
        <div className="circle circle-2"></div>
      </div>
      
      <div className="dashboard-container">
        <header className="dashboard-header">
          <div className="header-top-row">
            <div className="header-logo">
              <i className="fa-solid fa-layer-group logo-icon"></i>
              <div className="header-title">
                <h1>Knowledge RAG Hub</h1>
                <span className="badge badge-primary">v2.5.0</span>
              </div>
            </div>
            <button
              className="menu-toggle-btn"
              aria-label="Toggle navigation"
              onClick={() => setIsMobileNavOpen(!isMobileNavOpen)}
            >
              <i className={`fa-solid ${isMobileNavOpen ? 'fa-xmark' : 'fa-bars'}`}></i>
            </button>
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
              </span>
            </div>
            <div className="status-item">
              <span className="label">Collection</span>
              <span className="value code">{stats?.vector_store_collection || 'knowledge_rag_v1'}</span>
            </div>
          </div>
        </header>

        <nav className={`dashboard-nav ${isMobileNavOpen ? 'drawer-open' : ''}`}>
          <button className={`nav-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => { setActiveTab('overview'); setIsMobileNavOpen(false); }}><i className="fa-solid fa-chart-pie"></i> Overview</button>
          <button className={`nav-tab ${activeTab === 'git-repos' ? 'active' : ''}`} onClick={() => { setActiveTab('git-repos'); setIsMobileNavOpen(false); }}><i className="fa-brands fa-github"></i> Git Repositories</button>
          <button className={`nav-tab ${activeTab === 'local-paths' ? 'active' : ''}`} onClick={() => { setActiveTab('local-paths'); setIsMobileNavOpen(false); }}><i className="fa-solid fa-folder-tree"></i> Local Paths</button>
          <button className={`nav-tab ${activeTab === 'search-inspector' ? 'active' : ''}`} onClick={() => { setActiveTab('search-inspector'); setIsMobileNavOpen(false); }}><i className="fa-solid fa-magnifying-glass"></i> Search & Inspector</button>
          <button className={`nav-tab ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => { setActiveTab('settings'); setIsMobileNavOpen(false); }}><i className="fa-solid fa-gear"></i> Settings</button>
          <button className={`nav-tab ${activeTab === 'diagnostics' ? 'active' : ''}`} onClick={() => { setActiveTab('diagnostics'); setIsMobileNavOpen(false); }}><i className="fa-solid fa-terminal"></i> Diagnostics & Logs</button>
        </nav>

        <main className="dashboard-main">
          {activeTab === 'overview' && <Overview stats={stats} refreshStats={loadStats} />}
          {activeTab === 'git-repos' && <GitRepoManager refreshStats={loadStats} />}
          {activeTab === 'local-paths' && <LocalPathManager refreshStats={loadStats} />}
          {activeTab === 'search-inspector' && <SearchInspector />}
          {activeTab === 'settings' && <Settings stats={stats} refreshStats={loadStats} />}
          {activeTab === 'diagnostics' && <DiagnosticsViewer />}
        </main>


        <footer className="dashboard-footer">
          <p>Knowledge RAG MCP &bull; High Precision Tree-sitter & Hybrid Search &bull; 2026</p>
        </footer>
      </div>
    </>
  );
}

export default App;
