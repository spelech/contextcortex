import React from 'react';
import { NavigatorToolbar } from './components/navigator/NavigatorToolbar';
import { NavigatorBreadcrumbs } from './components/navigator/NavigatorBreadcrumbs';
import { NavigatorTree } from './components/navigator/NavigatorTree';
import { NavigatorOutline } from './components/navigator/NavigatorOutline';
import { NavigatorInspector } from './components/navigator/NavigatorInspector';
import { useNavigatorWorkspace } from './components/navigator/useNavigatorWorkspace';

export interface CodeNavigatorProps {
  initialRepo?: string;
  initialPath?: string;
  initialSymbolId?: number;
  initialStartLine?: number;
  initialEndLine?: number;
  onNavigationConsumed?: () => void;
}

export const CodeNavigator: React.FC<CodeNavigatorProps> = ({
  initialRepo = '__all__',
  initialPath,
  initialSymbolId,
  initialStartLine,
  initialEndLine,
  onNavigationConsumed,
}) => {
  const ws = useNavigatorWorkspace({
    initialRepo,
    initialPath,
    initialSymbolId,
    initialStartLine,
    initialEndLine,
    onNavigationConsumed,
  });

  return (
    <div
      className={`code-navigator-container density-${ws.density}`}
      data-testid="code-navigator-container"
    >
      <NavigatorToolbar
        repos={ws.repos}
        selectedRepo={ws.selectedRepo}
        onSelectRepo={ws.handleSelectRepo}
        density={ws.density}
        onChangeDensity={ws.handleDensityChange}
        searchQuery={ws.treeSearch}
        onSearchChange={ws.setTreeSearch}
        onSelectSearchResult={ws.handleSelectSearchResult}
        totalFiles={ws.treeData?.total_files ?? 0}
        totalSymbols={ws.treeData?.total_symbols ?? 0}
        onRefresh={() => ws.fetchTree(ws.selectedRepo)}
        loading={ws.loadingTree}
      />

      <NavigatorBreadcrumbs
        repo={ws.selectedRepo}
        path={ws.selectedPath}
        symbol={ws.activeSymbolName}
        onNavigatePath={ws.handleNavigateBreadcrumbPath}
        canGoBack={ws.historyIndex > 0}
        canGoForward={ws.historyIndex < ws.navHistory.length - 1}
        onGoBack={ws.handleGoBack}
        onGoForward={ws.handleGoForward}
        onToggleSidebar={() => ws.setIsSidebarOpen(!ws.isSidebarOpen)}
        isSidebarOpen={ws.isSidebarOpen}
      />

      {ws.errorMessage && (
        <div className="nav-error-banner" role="alert">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{ws.errorMessage}</span>
          <button
            type="button"
            onClick={() => ws.setErrorMessage(null)}
            className="error-close-btn"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}

      <div className="nav-hero-layout" data-testid="nav-hero-layout">
        <aside
          className={`nav-sidebar-column ${!ws.isSidebarOpen ? 'collapsed' : ''}`}
          aria-label="Codebase Navigator Sidebar"
        >
          <div className="nav-sidebar-tabs" role="tablist">
            <button
              type="button"
              className={`nav-sidebar-tab-btn ${ws.sidebarTab === 'files' ? 'active' : ''}`}
              onClick={() => ws.setSidebarTab('files')}
              role="tab"
              aria-selected={ws.sidebarTab === 'files'}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <span>Files</span>
            </button>
            <button
              type="button"
              className={`nav-sidebar-tab-btn ${ws.sidebarTab === 'outline' ? 'active' : ''}`}
              onClick={() => ws.setSidebarTab('outline')}
              role="tab"
              aria-selected={ws.sidebarTab === 'outline'}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="8" y1="6" x2="21" y2="6" />
                <line x1="8" y1="12" x2="21" y2="12" />
                <line x1="8" y1="18" x2="21" y2="18" />
                <line x1="3" y1="6" x2="3.01" y2="6" />
                <line x1="3" y1="12" x2="3.01" y2="12" />
                <line x1="3" y1="18" x2="3.01" y2="18" />
              </svg>
              <span>Symbols</span>
            </button>
          </div>

          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', position: 'relative' }}>
            <div
              style={{
                flex: 1,
                minHeight: 0,
                display: ws.sidebarTab === 'files' ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <NavigatorTree
                nodes={ws.treeData?.tree ?? []}
                selectedPath={ws.selectedPath}
                onSelectFile={ws.handleSelectFile}
                filterText={ws.treeSearch}
                onFilterChange={ws.setTreeSearch}
                density={ws.density}
                loading={ws.loadingTree}
                repo={ws.selectedRepo}
                autoExpandRoot={true}
              />
            </div>
            <div
              style={{
                flex: 1,
                minHeight: 0,
                display: ws.sidebarTab === 'outline' ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <NavigatorOutline
                outline={ws.fileOutline}
                selectedSymbolId={ws.selectedSymbolId}
                onSelectSymbol={ws.handleSelectSymbol}
                onReadDoc={() => ws.setActiveInspectorTab('reader')}
                density={ws.density}
                loading={ws.loadingOutline}
              />
            </div>
          </div>
        </aside>

        <main className="nav-hero-viewer" aria-label="Code and Document Hero Viewport">
          <NavigatorInspector
            impact={ws.symbolImpact}
            fileContent={ws.fileContent}
            loadingContent={ws.loadingContent}
            contentError={ws.contentError}
            targetStartLine={ws.targetStartLine}
            targetEndLine={ws.targetEndLine}
            activeInspectorTab={ws.activeInspectorTab}
            onChangeInspectorTab={ws.handleInspectorTabChange}
            onSelectCaller={ws.handleSelectCaller}
            onSelectCallee={ws.handleSelectCallee}
            density={ws.density}
            loading={ws.loadingImpact}
            onRefreshContent={() => ws.selectedPath && ws.fetchFileContent(ws.selectedRepo, ws.selectedPath)}
          />
        </main>
      </div>
    </div>
  );
};

export default CodeNavigator;
