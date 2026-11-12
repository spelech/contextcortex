import { useState, useEffect, useCallback, useRef } from 'react';
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
} from './types';

const DENSITY_STORAGE_KEY = 'contextcortex_navigator_density';

export interface NavigatorHistoryEntry {
  repo: string;
  path: string;
  symbolId?: number | null;
  startLine?: number;
  endLine?: number;
}

export interface NavigatorWorkspaceOptions {
  initialRepo?: string;
  initialPath?: string;
  initialSymbolId?: number;
  initialStartLine?: number;
  initialEndLine?: number;
  onNavigationConsumed?: () => void;
}

export function useNavigatorWorkspace({
  initialRepo = '__all__',
  initialPath,
  initialSymbolId,
  initialStartLine,
  initialEndLine,
  onNavigationConsumed,
}: NavigatorWorkspaceOptions) {
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

  const [repos, setRepos] = useState<RepoOption[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>(initialRepo);

  const [treeData, setTreeData] = useState<NavigatorTreeResponse | null>(null);
  const [loadingTree, setLoadingTree] = useState<boolean>(false);
  const [treeSearch, setTreeSearch] = useState<string>('');

  const [selectedPath, setSelectedPath] = useState<string | null>(initialPath || null);
  const [fileOutline, setFileOutline] = useState<FileOutline | null>(null);
  const [loadingOutline, setLoadingOutline] = useState<boolean>(false);

  const [selectedSymbolId, setSelectedSymbolId] = useState<number | null>(initialSymbolId || null);
  const [symbolImpact, setSymbolImpact] = useState<SymbolImpact | null>(null);
  const [loadingImpact, setLoadingImpact] = useState<boolean>(false);

  const [fileContent, setFileContent] = useState<FileContentResult | null>(null);
  const [loadingContent, setLoadingContent] = useState<boolean>(false);
  const [contentError, setContentError] = useState<string | null>(null);
  const [activeInspectorTab, setActiveInspectorTab] = useState<'intelligence' | 'reader'>('reader');
  const [targetStartLine, setTargetStartLine] = useState<number | undefined>(undefined);
  const [targetEndLine, setTargetEndLine] = useState<number | undefined>(undefined);

  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);
  const [sidebarTab, setSidebarTab] = useState<'files' | 'outline'>('files');
  const [navHistory, setNavHistory] = useState<NavigatorHistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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

  const lastNavRef = useRef<string | null>(null);

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
  }, [
    initialRepo,
    initialPath,
    initialSymbolId,
    initialStartLine,
    initialEndLine,
    fetchFileContent,
    fetchOutline,
    fetchImpact,
    onNavigationConsumed,
  ]);

  const pushHistory = useCallback(
    (item: NavigatorHistoryEntry) => {
      setNavHistory((prev) => {
        const sliced = prev.slice(0, historyIndex + 1);
        return [...sliced, item];
      });
      setHistoryIndex((prev) => prev + 1);
    },
    [historyIndex]
  );

  const applyHistoryItem = (item: NavigatorHistoryEntry, nextIndex: number) => {
    setHistoryIndex(nextIndex);
    setSelectedRepo(item.repo);
    setSelectedPath(item.path);
    setSelectedSymbolId(item.symbolId ?? null);
    setTargetStartLine(item.startLine);
    setTargetEndLine(item.endLine);
    fetchOutline(item.repo, item.path, item.symbolId ?? undefined);
    fetchFileContent(item.repo, item.path);
    if (item.symbolId) fetchImpact(item.repo, item.symbolId);
  };

  const handleGoBack = () => {
    if (historyIndex > 0) {
      applyHistoryItem(navHistory[historyIndex - 1], historyIndex - 1);
    }
  };

  const handleGoForward = () => {
    if (historyIndex < navHistory.length - 1) {
      applyHistoryItem(navHistory[historyIndex + 1], historyIndex + 1);
    }
  };

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
    const filePath = node.abs_path || node.path;
    setSelectedPath(filePath);
    setTargetStartLine(undefined);
    setTargetEndLine(undefined);

    pushHistory({ repo: selectedRepo, path: filePath });
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
        if (selectedRepo) fetchImpact(selectedRepo, first.id);
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

  const handleSelectCaller = (filePath: string, symbolName?: string, sourceSymbolId?: number) => {
    setSelectedPath(filePath);
    setTargetStartLine(undefined);
    setTargetEndLine(undefined);

    pushHistory({ repo: selectedRepo, path: filePath, symbolId: sourceSymbolId });

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
      pushHistory({ repo: selectedRepo, path: filePath });
      fetchOutline(selectedRepo, filePath, symbolName, 'reader');
      fetchFileContent(selectedRepo, filePath);
      setActiveInspectorTab('reader');
    }
  };

  const handleNavigateBreadcrumbPath = (path: string) => {
    setSelectedPath(path);
    const isFile = /\.[a-zA-Z0-9]+$/.test(path);
    if (isFile) {
      fetchFileContent(selectedRepo, path);
      fetchOutline(selectedRepo, path);
    } else {
      setSidebarTab('files');
    }
  };

  const activeSymbolName = fileOutline?.symbols?.find((s) => s.id === selectedSymbolId)?.name || null;

  return {
    density,
    handleDensityChange,
    repos,
    selectedRepo,
    handleSelectRepo,
    treeData,
    loadingTree,
    treeSearch,
    setTreeSearch,
    selectedPath,
    fileOutline,
    loadingOutline,
    selectedSymbolId,
    symbolImpact,
    loadingImpact,
    fileContent,
    loadingContent,
    contentError,
    activeInspectorTab,
    setActiveInspectorTab,
    targetStartLine,
    targetEndLine,
    isSidebarOpen,
    setIsSidebarOpen,
    sidebarTab,
    setSidebarTab,
    navHistory,
    historyIndex,
    errorMessage,
    setErrorMessage,
    fetchTree,
    fetchFileContent,
    handleGoBack,
    handleGoForward,
    handleSelectSearchResult,
    handleSelectFile,
    handleInspectorTabChange,
    handleSelectSymbol,
    handleSelectCaller,
    handleSelectCallee,
    handleNavigateBreadcrumbPath,
    activeSymbolName,
  };
}
