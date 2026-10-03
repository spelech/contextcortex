import React, { useState, useEffect, useCallback, useRef } from 'react';
import type {
  DensityMode,
  NavigatorTreeNode,
  NavigatorTreeResponse,
  FileOutline,
  SymbolOutlineItem,
  SymbolImpact,
  RepoOption,
  FileContentResult,
  OmniSearchResultItem,
} from './components/navigator/types';
import { NavigatorToolbar } from './components/navigator/NavigatorToolbar';
import { NavigatorBreadcrumbs } from './components/navigator/NavigatorBreadcrumbs';
import { NavigatorTree } from './components/navigator/NavigatorTree';
import { NavigatorOutline } from './components/navigator/NavigatorOutline';
import { NavigatorInspector } from './components/navigator/NavigatorInspector';

const DENSITY_STORAGE_KEY = 'contextcortex_navigator_density';

export interface CodeNavigatorProps {
  initialRepo?: string;
  initialPath?: string;
  initialSymbolId?: number;
  initialStartLine?: number;
  initialEndLine?: number;
  onNavigationConsumed?: () => void;
}

interface HistoryItem {
  repo: string;
  path: string;
  symbolId?: number | null;
  startLine?: number;
  endLine?: number;
}

export const CodeNavigator: React.FC<CodeNavigatorProps> = ({
  initialRepo = '__all__',
  initialPath,
  initialSymbolId,
  initialStartLine,
  initialEndLine,
  onNavigationConsumed,
}) => {
  // Persistence for density mode
  const [density, setDensity] = useState<DensityMode>(() => {
    const saved = localStorage.getItem(DENSITY_STORAGE_KEY);
    if (saved === 'compact' || saved === 'balanced' || saved === 'spacious') {
      return saved;
    }
    return 'balanced';
  });

  const handleDensityChange = (newDensity: DensityMode) => {
    setDensity(newDensity);
    localStorage.setItem(DENSITY_STORAGE_KEY, newDensity);
  };

  // Repositories
  const [repos, setRepos] = useState<RepoOption[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>(initialRepo);

  // Tree data & search
  const [treeData, setTreeData] = useState<NavigatorTreeResponse | null>(null);
  const [loadingTree, setLoadingTree] = useState<boolean>(false);
  const [treeSearch, setTreeSearch] = useState<string>('');

  // Selected file and outline data
  const [selectedPath, setSelectedPath] = useState<string | null>(initialPath || null);
  const [fileOutline, setFileOutline] = useState<FileOutline | null>(null);
  const [loadingOutline, setLoadingOutline] = useState<boolean>(false);

  // Selected symbol and impact data
  const [selectedSymbolId, setSelectedSymbolId] = useState<number | null>(initialSymbolId || null);
  const [symbolImpact, setSymbolImpact] = useState<SymbolImpact | null>(null);
  const [loadingImpact, setLoadingImpact] = useState<boolean>(false);

  // Full File / Document Content state
  const [fileContent, setFileContent] = useState<FileContentResult | null>(null);
  const [loadingContent, setLoadingContent] = useState<boolean>(false);
  const [contentError, setContentError] = useState<string | null>(null);
  const [activeInspectorTab, setActiveInspectorTab] = useState<'intelligence' | 'reader'>('reader');
  const [targetStartLine, setTargetStartLine] = useState<number | undefined>(undefined);
  const [targetEndLine, setTargetEndLine] = useState<number | undefined>(undefined);

  // Workspace Layout & Navigation History State
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);
  const [sidebarTab, setSidebarTab] = useState<'files' | 'outline'>('files');
  const [navHistory, setNavHistory] = useState<HistoryItem[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);

  // Error state
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Keyboard shortcut Ctrl+B / Cmd+B to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setIsSidebarOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 1. Fetch repositories on mount
  useEffect(() => {
    const fetchRepos = async () => {
      try {
        const res = await fetch('/admin/api/repos');
        if (res.ok) {
          const data = await res.json();
          setRepos(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        console.error('Error fetching repositories:', err);
      }
    };
    fetchRepos();
  }, []);

  // 2. Fetch navigator tree when selectedRepo changes
  const fetchTree = useCallback(async (repoName: string) => {
    setLoadingTree(true);
    setErrorMessage(null);
    try {
      const res = await fetch(`/admin/api/navigator/tree?repo=${encodeURIComponent(repoName)}`);
      if (!res.ok) {
        throw new Error(`Failed to load tree: ${res.status} ${res.statusText}`);
      }
      const data: NavigatorTreeResponse = await res.json();
      setTreeData(data);
    } catch (err: any) {
      console.error('Error fetching codebase tree:', err);
      setErrorMessage(err.message || 'Failed to load codebase tree');
    } finally {
      setLoadingTree(false);
    }
  }, []);

  useEffect(() => {
    fetchTree(selectedRepo);
  }, [selectedRepo, fetchTree]);

  // 3. Fetch symbol impact
  const fetchImpact = useCallback(async (repoName: string, symbolId: number) => {
    setLoadingImpact(true);
    try {
      const res = await fetch(
        `/admin/api/navigator/symbol-impact?repo=${encodeURIComponent(repoName)}&symbol_id=${symbolId}`
      );
      if (!res.ok) {
        throw new Error(`Failed to load symbol impact: ${res.status}`);
      }
      const data: SymbolImpact = await res.json();
      setSymbolImpact(data);
    } catch (err: any) {
      console.error('Error fetching symbol impact:', err);
      setSymbolImpact(null);
    } finally {
      setLoadingImpact(false);
    }
  }, []);

  // 4. Fetch full file content for document reading
  const fetchFileContent = useCallback(async (repoName: string, filePath: string) => {
    setLoadingContent(true);
    setContentError(null);
    try {
      const res = await fetch(
        `/admin/api/files/read?path=${encodeURIComponent(filePath)}&repo=${encodeURIComponent(repoName)}`
      );
      if (!res.ok) {
        throw new Error(`Failed to read file: ${res.statusText}`);
      }
      const data: FileContentResult = await res.json();
      setFileContent(data);
    } catch (err: any) {
      console.error('Error fetching file content:', err);
      setContentError(err.message || 'Failed to read file content');
      setFileContent(null);
    } finally {
      setLoadingContent(false);
    }
  }, []);

  // 5. Fetch file outline when selectedPath changes
  const fetchOutline = useCallback(
    async (
      repoName: string,
      filePath: string,
      symbolToAutoSelect?: number | string,
      tabToActivate?: 'intelligence' | 'reader'
    ) => {
      setLoadingOutline(true);
      try {
        const res = await fetch(
          `/admin/api/navigator/file-outline?repo=${encodeURIComponent(repoName)}&filepath=${encodeURIComponent(filePath)}`
        );
        if (!res.ok) {
          throw new Error(`Failed to load file outline: ${res.status}`);
        }
        const data: FileOutline = await res.json();
        setFileOutline(data);

        // Auto-select symbol or switch to reader mode
        if (data.symbols && data.symbols.length > 0) {
          let matched: SymbolOutlineItem | undefined;
          if (typeof symbolToAutoSelect === 'number') {
            matched = data.symbols.find((s) => s.id === symbolToAutoSelect);
          } else if (typeof symbolToAutoSelect === 'string') {
            matched = data.symbols.find(
              (s) => s.name === symbolToAutoSelect || s.full_symbol === symbolToAutoSelect
            );
          }
          if (!matched) {
            matched = data.symbols[0];
          }
          if (matched) {
            setSelectedSymbolId(matched.id);
            if (tabToActivate === 'intelligence' || symbolToAutoSelect !== undefined) {
              setTargetStartLine(matched.start_line);
              setTargetEndLine(matched.end_line);
            }
            await fetchImpact(repoName, matched.id);
          }
        } else {
          setSelectedSymbolId(null);
          setSymbolImpact(null);
        }
        setActiveInspectorTab(tabToActivate || 'reader');
      } catch (err: any) {
        console.error('Error fetching outline:', err);
        setFileOutline(null);
        setSelectedSymbolId(null);
        setSymbolImpact(null);
        setActiveInspectorTab('reader');
      } finally {
        setLoadingOutline(false);
      }
    },
    [fetchImpact]
  );

  // Track last consumed external navigation to prevent navigation trap
  const lastNavRef = useRef<string | null>(null);

  // Handle external navigation (e.g. from SearchInspector)
  useEffect(() => {
    if (!initialPath && !initialSymbolId && (!initialRepo || initialRepo === '__all__')) {
      return;
    }
    const navKey = `${initialRepo || ''}:${initialPath || ''}:${initialSymbolId || ''}:${initialStartLine || ''}:${initialEndLine || ''}`;
    if (lastNavRef.current === navKey) {
      return;
    }
    lastNavRef.current = navKey;

    const targetRepo = initialRepo && initialRepo !== '__all__' ? initialRepo : selectedRepo;
    if (initialRepo && initialRepo !== '__all__' && initialRepo !== selectedRepo) {
      setSelectedRepo(initialRepo);
    }
    if (initialPath) {
      setSelectedPath(initialPath);
      fetchFileContent(targetRepo, initialPath);
      fetchOutline(targetRepo, initialPath);
      if (initialStartLine !== undefined) setTargetStartLine(initialStartLine);
      if (initialEndLine !== undefined) setTargetEndLine(initialEndLine);
      setActiveInspectorTab('reader');
    }
    if (initialSymbolId) {
      setSelectedSymbolId(initialSymbolId);
      fetchImpact(targetRepo, initialSymbolId);
      setActiveInspectorTab('intelligence');
    }
    onNavigationConsumed?.();
  }, [initialRepo, initialPath, initialSymbolId, initialStartLine, initialEndLine, fetchFileContent, fetchOutline, fetchImpact, onNavigationConsumed]);

  // Push item into navigation history
  const pushHistory = useCallback(
    (item: HistoryItem) => {
      setNavHistory((prev) => {
        const sliced = prev.slice(0, historyIndex + 1);
        return [...sliced, item];
      });
      setHistoryIndex((prev) => prev + 1);
    },
    [historyIndex]
  );

  // Navigate back / forward in history
  const handleGoBack = () => {
    if (historyIndex > 0) {
      const prevItem = navHistory[historyIndex - 1];
      setHistoryIndex(historyIndex - 1);
      setSelectedRepo(prevItem.repo);
      setSelectedPath(prevItem.path);
      setSelectedSymbolId(prevItem.symbolId ?? null);
      setTargetStartLine(prevItem.startLine);
      setTargetEndLine(prevItem.endLine);
      fetchOutline(prevItem.repo, prevItem.path, prevItem.symbolId ?? undefined);
      fetchFileContent(prevItem.repo, prevItem.path);
      if (prevItem.symbolId) fetchImpact(prevItem.repo, prevItem.symbolId);
    }
  };

  const handleGoForward = () => {
    if (historyIndex < navHistory.length - 1) {
      const nextItem = navHistory[historyIndex + 1];
      setHistoryIndex(historyIndex + 1);
      setSelectedRepo(nextItem.repo);
      setSelectedPath(nextItem.path);
      setSelectedSymbolId(nextItem.symbolId ?? null);
      setTargetStartLine(nextItem.startLine);
      setTargetEndLine(nextItem.endLine);
      fetchOutline(nextItem.repo, nextItem.path, nextItem.symbolId ?? undefined);
      fetchFileContent(nextItem.repo, nextItem.path);
      if (nextItem.symbolId) fetchImpact(nextItem.repo, nextItem.symbolId);
    }
  };

  // Handlers
  const handleSelectRepo = (repo: string) => {
    setSelectedRepo(repo);
    setSelectedPath(null);
    setFileOutline(null);
    setSelectedSymbolId(null);
    setSymbolImpact(null);
    setFileContent(null);
    setTargetStartLine(undefined);
    setTargetEndLine(undefined);
  };

  const handleSelectSearchResult = (result: OmniSearchResultItem) => {
    const targetRepo = result.repo && result.repo !== '__all__' ? result.repo : selectedRepo;
    if (result.repo && result.repo !== selectedRepo && selectedRepo !== '__all__') {
      setSelectedRepo(result.repo);
    }
    setSelectedPath(result.filepath);
    setTargetStartLine(result.start_line);
    setTargetEndLine(result.end_line);

    pushHistory({
      repo: targetRepo,
      path: result.filepath,
      symbolId: result.symbol_id,
      startLine: result.start_line,
      endLine: result.end_line,
    });

    fetchFileContent(targetRepo, result.filepath);

    if (result.type === 'symbol' && result.symbol_id) {
      setSelectedSymbolId(result.symbol_id);
      fetchOutline(targetRepo, result.filepath, result.symbol_id, 'reader');
      fetchImpact(targetRepo, result.symbol_id);
    } else {
      fetchOutline(targetRepo, result.filepath, undefined, 'reader');
    }
    setActiveInspectorTab('reader');
  };

  const handleSelectFile = (node: NavigatorTreeNode) => {
    if (node.is_dir) return;
    // Use abs_path (original DB filepath) when available — handles local absolute paths correctly
    const filePath = node.abs_path || node.path;
    setSelectedPath(filePath);
    setTargetStartLine(undefined);
    setTargetEndLine(undefined);

    pushHistory({
      repo: selectedRepo,
      path: filePath,
    });

    fetchOutline(selectedRepo, filePath, undefined, 'reader');
    fetchFileContent(selectedRepo, filePath);
    setActiveInspectorTab('reader');
    setSidebarTab('outline');
  };

  const handleInspectorTabChange = (tab: 'intelligence' | 'reader') => {
    setActiveInspectorTab(tab);
    if (tab === 'intelligence') {
      if (!selectedSymbolId && fileOutline?.symbols && fileOutline.symbols.length > 0) {
        const first = fileOutline.symbols[0];
        setSelectedSymbolId(first.id);
        setTargetStartLine(first.start_line);
        setTargetEndLine(first.end_line);
        if (selectedRepo) {
          fetchImpact(selectedRepo, first.id);
        }
      } else if (selectedSymbolId && !symbolImpact && selectedRepo) {
        fetchImpact(selectedRepo, selectedSymbolId);
      }
    }
  };

  const handleSelectSymbol = (symbol: SymbolOutlineItem) => {
    setSelectedSymbolId(symbol.id);
    setTargetStartLine(symbol.start_line);
    setTargetEndLine(symbol.end_line);
    setActiveInspectorTab('intelligence');
    fetchImpact(selectedRepo, symbol.id);

    if (selectedPath) {
      pushHistory({
        repo: selectedRepo,
        path: selectedPath,
        symbolId: symbol.id,
        startLine: symbol.start_line,
        endLine: symbol.end_line,
      });
    }
  };

  // Cross-pane click-through navigation for callers
  const handleSelectCaller = (filePath: string, symbolName?: string, sourceSymbolId?: number) => {
    setSelectedPath(filePath);
    setTargetStartLine(undefined);
    setTargetEndLine(undefined);

    pushHistory({
      repo: selectedRepo,
      path: filePath,
      symbolId: sourceSymbolId,
    });

    const targetTab = sourceSymbolId ? 'intelligence' : 'reader';
    fetchOutline(selectedRepo, filePath, sourceSymbolId ?? symbolName, targetTab);
    fetchFileContent(selectedRepo, filePath);
    setActiveInspectorTab(targetTab);
    setSidebarTab('outline');
    if (sourceSymbolId) {
      setSelectedSymbolId(sourceSymbolId);
      fetchImpact(selectedRepo, sourceSymbolId);
    }
  };

  const handleSelectCallee = (filePath?: string, symbolName?: string) => {
    if (filePath) {
      setSelectedPath(filePath);
      setTargetStartLine(undefined);
      setTargetEndLine(undefined);

      pushHistory({
        repo: selectedRepo,
        path: filePath,
      });

      fetchOutline(selectedRepo, filePath, symbolName, 'reader');
      fetchFileContent(selectedRepo, filePath);
      setActiveInspectorTab('reader');
    }
  };

  const activeSymbolName = fileOutline?.symbols?.find((s) => s.id === selectedSymbolId)?.name || null;

  return (
    <div
      className={`code-navigator-container density-${density}`}
      data-testid="code-navigator-container"
    >
      {/* Top Navigation Toolbar */}
      <NavigatorToolbar
        repos={repos}
        selectedRepo={selectedRepo}
        onSelectRepo={handleSelectRepo}
        density={density}
        onChangeDensity={handleDensityChange}
        searchQuery={treeSearch}
        onSearchChange={setTreeSearch}
        onSelectSearchResult={handleSelectSearchResult}
        totalFiles={treeData?.total_files ?? 0}
        totalSymbols={treeData?.total_symbols ?? 0}
        onRefresh={() => fetchTree(selectedRepo)}
        loading={loadingTree}
      />

      {/* Breadcrumbs & Navigation History Bar */}
      <NavigatorBreadcrumbs
        repo={selectedRepo}
        path={selectedPath}
        symbol={activeSymbolName}
        onNavigatePath={(path) => {
          setSelectedPath(path);
          const isFile = /\.[a-zA-Z0-9]+$/.test(path);
          if (isFile) {
            fetchFileContent(selectedRepo, path);
            fetchOutline(selectedRepo, path);
          } else {
            setSidebarTab('files');
          }
        }}
        canGoBack={historyIndex > 0}
        canGoForward={historyIndex < navHistory.length - 1}
        onGoBack={handleGoBack}
        onGoForward={handleGoForward}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        isSidebarOpen={isSidebarOpen}
      />

      {errorMessage && (
        <div className="nav-error-banner" role="alert">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} className="error-close-btn" aria-label="Dismiss error">
            ✕
          </button>
        </div>
      )}

      {/* Code-First Hero Workspace Layout */}
      <div className="nav-hero-layout" data-testid="nav-hero-layout">
        {/* Left Collapsible Sidebar: Files & Outline */}
        <aside
          className={`nav-sidebar-column ${!isSidebarOpen ? 'collapsed' : ''}`}
          aria-label="Codebase Navigator Sidebar"
        >
          <div className="nav-sidebar-tabs" role="tablist">
            <button
              type="button"
              className={`nav-sidebar-tab-btn ${sidebarTab === 'files' ? 'active' : ''}`}
              onClick={() => setSidebarTab('files')}
              role="tab"
              aria-selected={sidebarTab === 'files'}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <span>Files</span>
            </button>
            <button
              type="button"
              className={`nav-sidebar-tab-btn ${sidebarTab === 'outline' ? 'active' : ''}`}
              onClick={() => setSidebarTab('outline')}
              role="tab"
              aria-selected={sidebarTab === 'outline'}
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
                display: sidebarTab === 'files' ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <NavigatorTree
                nodes={treeData?.tree ?? []}
                selectedPath={selectedPath}
                onSelectFile={handleSelectFile}
                filterText={treeSearch}
                onFilterChange={setTreeSearch}
                density={density}
                loading={loadingTree}
                repo={selectedRepo}
                autoExpandRoot={true}
              />
            </div>
            <div
              style={{
                flex: 1,
                minHeight: 0,
                display: sidebarTab === 'outline' ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <NavigatorOutline
                outline={fileOutline}
                selectedSymbolId={selectedSymbolId}
                onSelectSymbol={handleSelectSymbol}
                onReadDoc={() => {
                  setActiveInspectorTab('reader');
                }}
                density={density}
                loading={loadingOutline}
              />
            </div>
          </div>
        </aside>

        {/* Center Hero Code & Document Viewer (~75–80% width) */}
        <main
          className="nav-hero-viewer"
          aria-label="Code and Document Hero Viewport"
        >
          <NavigatorInspector
            impact={symbolImpact}
            fileContent={fileContent}
            loadingContent={loadingContent}
            contentError={contentError}
            targetStartLine={targetStartLine}
            targetEndLine={targetEndLine}
            activeInspectorTab={activeInspectorTab}
            onChangeInspectorTab={handleInspectorTabChange}
            onSelectCaller={handleSelectCaller}
            onSelectCallee={handleSelectCallee}
            density={density}
            loading={loadingImpact}
            onRefreshContent={() => selectedPath && fetchFileContent(selectedRepo, selectedPath)}
          />
        </main>
      </div>
    </div>
  );
};

export default CodeNavigator;
