import React, { useState, useEffect, useCallback } from 'react';
import type {
  DensityMode,
  NavigatorTreeNode,
  NavigatorTreeResponse,
  FileOutline,
  SymbolOutlineItem,
  SymbolImpact,
  RepoOption,
} from './components/navigator/types';
import { NavigatorToolbar } from './components/navigator/NavigatorToolbar';
import { NavigatorTree } from './components/navigator/NavigatorTree';
import { NavigatorOutline } from './components/navigator/NavigatorOutline';
import { NavigatorInspector } from './components/navigator/NavigatorInspector';

const DENSITY_STORAGE_KEY = 'contextcortex_navigator_density';

export interface CodeNavigatorProps {
  initialRepo?: string;
  initialPath?: string;
  initialSymbolId?: number;
}

export const CodeNavigator: React.FC<CodeNavigatorProps> = ({
  initialRepo = '__all__',
  initialPath,
  initialSymbolId,
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

  // Error state
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 1. Fetch repositories on mount
  useEffect(() => {
    const fetchRepos = async () => {
      try {
        const res = await fetch('/admin/api/repositories');
        if (res.ok) {
          const data = await res.json();
          setRepos(Array.isArray(data) ? data : []);
        } else {
          // Fallback to /admin/api/repos
          const fallbackRes = await fetch('/admin/api/repos');
          if (fallbackRes.ok) {
            const data = await fallbackRes.json();
            setRepos(Array.isArray(data) ? data : []);
          }
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

  // 4. Fetch file outline when selectedPath changes
  const fetchOutline = useCallback(
    async (repoName: string, filePath: string, symbolToAutoSelect?: number | string) => {
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

        // Auto-select symbol
        if (data.symbols && data.symbols.length > 0) {
          let matched: SymbolOutlineItem | undefined;
          if (typeof symbolToAutoSelect === 'number') {
            matched = data.symbols.find((s) => s.id === symbolToAutoSelect);
          } else if (typeof symbolToAutoSelect === 'string') {
            matched = data.symbols.find(
              (s) => s.name === symbolToAutoSelect || s.full_symbol === symbolToAutoSelect
            );
          }
          const targetSymbol = matched || data.symbols[0];
          setSelectedSymbolId(targetSymbol.id);
          await fetchImpact(repoName, targetSymbol.id);
        } else {
          setSelectedSymbolId(null);
          setSymbolImpact(null);
        }

      } catch (err: any) {
        console.error('Error fetching outline:', err);
        setFileOutline(null);
        setSelectedSymbolId(null);
        setSymbolImpact(null);
      } finally {
        setLoadingOutline(false);
      }
    },
    [fetchImpact]
  );


  // Handlers
  const handleSelectRepo = (repo: string) => {
    setSelectedRepo(repo);
    setSelectedPath(null);
    setFileOutline(null);
    setSelectedSymbolId(null);
    setSymbolImpact(null);
  };

  const handleSelectFile = (node: NavigatorTreeNode) => {
    if (node.is_dir) return;
    setSelectedPath(node.path);
    fetchOutline(selectedRepo, node.path);
  };

  const handleSelectSymbol = (symbol: SymbolOutlineItem) => {
    setSelectedSymbolId(symbol.id);
    fetchImpact(selectedRepo, symbol.id);
  };

  // Cross-pane click-through navigation for callers
  const handleSelectCaller = (filePath: string, symbolName?: string, sourceSymbolId?: number) => {
    setSelectedPath(filePath);
    fetchOutline(selectedRepo, filePath, sourceSymbolId ?? symbolName);
  };

  const handleSelectCallee = (filePath?: string, symbolName?: string) => {
    if (filePath) {
      setSelectedPath(filePath);
      fetchOutline(selectedRepo, filePath, symbolName);
    }
  };

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
        totalFiles={treeData?.total_files ?? 0}
        totalSymbols={treeData?.total_symbols ?? 0}
        onRefresh={() => fetchTree(selectedRepo)}
        loading={loadingTree}
      />

      {errorMessage && (
        <div className="nav-error-banner" role="alert">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} className="error-close-btn">
            ✕
          </button>
        </div>
      )}

      {/* 3-Pane Responsive Layout */}
      <div className="nav-panes-layout">
        {/* Pane 1: File & Directory Tree */}
        <section className="nav-pane-column nav-pane-tree" aria-label="File Tree">
          <NavigatorTree
            nodes={treeData?.tree ?? []}
            selectedPath={selectedPath}
            onSelectFile={handleSelectFile}
            filterText={treeSearch}
            onFilterChange={setTreeSearch}
            density={density}
            loading={loadingTree}
          />
        </section>

        {/* Pane 2: Symbol & Route Outline */}
        <section className="nav-pane-column nav-pane-outline" aria-label="Symbol and Route Outline">
          <NavigatorOutline
            outline={fileOutline}
            selectedSymbolId={selectedSymbolId}
            onSelectSymbol={handleSelectSymbol}
            density={density}
            loading={loadingOutline}
          />
        </section>

        {/* Pane 3: Impact & Relationship Inspector */}
        <section className="nav-pane-column nav-pane-inspector" aria-label="Code Intelligence and Impact">
          <NavigatorInspector
            impact={symbolImpact}
            onSelectCaller={handleSelectCaller}
            onSelectCallee={handleSelectCallee}
            density={density}
            loading={loadingImpact}
          />
        </section>
      </div>
    </div>
  );
};

export default CodeNavigator;
