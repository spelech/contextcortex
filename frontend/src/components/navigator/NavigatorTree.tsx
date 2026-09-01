import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import type { NavigatorTreeNode, DensityMode } from './types';

interface NavigatorTreeProps {
  nodes: NavigatorTreeNode[];
  selectedPath: string | null;
  onSelectFile: (node: NavigatorTreeNode) => void;
  filterText?: string;
  onFilterChange?: (text: string) => void;
  density?: DensityMode;
  loading?: boolean;
}

// File icon helper
export function getFileIcon(filename: string, language?: string | null): { icon: string; className: string } {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.py') || language === 'python') return { icon: '🐍', className: 'icon-py' };
  if (lower.endsWith('.tsx') || lower.endsWith('.ts') || language === 'typescript') return { icon: '⚡', className: 'icon-ts' };
  if (lower.endsWith('.jsx') || lower.endsWith('.js') || lower.endsWith('.mjs') || language === 'javascript') return { icon: '📜', className: 'icon-js' };
  if (lower.endsWith('.go') || language === 'go') return { icon: '🔷', className: 'icon-go' };
  if (lower.endsWith('.rs') || language === 'rust') return { icon: '🦀', className: 'icon-rs' };
  if (lower.endsWith('.json')) return { icon: '📄', className: 'icon-json' };
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return { icon: '📝', className: 'icon-md' };
  if (lower.endsWith('.css') || lower.endsWith('.scss')) return { icon: '🎨', className: 'icon-css' };
  if (lower.endsWith('.sql')) return { icon: '🗄️', className: 'icon-sql' };
  if (lower.endsWith('.yaml') || lower.endsWith('.yml') || lower.endsWith('.toml')) return { icon: '⚙️', className: 'icon-yaml' };
  return { icon: '📄', className: 'icon-file' };
}

interface FlatVisibleItem {
  node: NavigatorTreeNode;
  depth: number;
  isExpanded: boolean;
  hasChildren: boolean;
}

export const NavigatorTree: React.FC<NavigatorTreeProps> = ({
  nodes,
  selectedPath,
  onSelectFile,
  filterText: externalFilter,
  onFilterChange,
  density = 'balanced',
  loading = false,
}) => {
  const [internalFilter, setInternalFilter] = useState('');
  const filter = externalFilter !== undefined ? externalFilter : internalFilter;
  const setFilter = onFilterChange || setInternalFilter;

  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  // Helper to collect all dir IDs
  const collectAllDirIds = useCallback((items: NavigatorTreeNode[] | null | undefined): string[] => {
    const ids: string[] = [];
    const traverse = (list: NavigatorTreeNode[] | null | undefined) => {
      if (!list || !Array.isArray(list)) return;
      for (const item of list) {
        if (!item) continue;
        if (item.is_dir) {
          ids.push(item.id);
          if (Array.isArray(item.children)) traverse(item.children);
        }
      }
    };
    traverse(items);
    return ids;
  }, []);

  // Filter tree nodes
  const filterNodes = useCallback(
    (items: NavigatorTreeNode[] | null | undefined, query: string): { filteredNodes: NavigatorTreeNode[]; matchedDirIds: Set<string> } => {
      if (!items || !Array.isArray(items)) return { filteredNodes: [], matchedDirIds: new Set<string>() };
      const q = query.toLowerCase().trim();
      const matchedDirIds = new Set<string>();


      const checkNode = (node: NavigatorTreeNode): NavigatorTreeNode | null => {
        if (!node) return null;
        const matchesSelf = (node.name || '').toLowerCase().includes(q) || (node.path || '').toLowerCase().includes(q);

        if (node.is_dir) {
          const rawChildren = Array.isArray(node.children) ? node.children : [];
          const children = rawChildren
            .map(checkNode)
            .filter((c): c is NavigatorTreeNode => c !== null);

          if (children.length > 0 || matchesSelf) {
            matchedDirIds.add(node.id);
            return {
              ...node,
              children: children.length > 0 ? children : rawChildren,
            };
          }
          return null;
        }

        return matchesSelf ? node : null;
      };

      const filtered = items.map(checkNode).filter((n): n is NavigatorTreeNode => n !== null);
      return { filteredNodes: filtered, matchedDirIds };
    },
    []
  );


  const { filteredNodes, matchedDirIds } = useMemo(() => {
    if (!filter.trim()) {
      return { filteredNodes: Array.isArray(nodes) ? nodes : [], matchedDirIds: new Set<string>() };
    }
    return filterNodes(nodes, filter);
  }, [nodes, filter, filterNodes]);

  // When filter changes, expand matching directories
  useEffect(() => {
    if (filter.trim()) {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        matchedDirIds.forEach((id) => next.add(id));
        return next;
      });
    }
  }, [filter, matchedDirIds]);

  // Auto-expand path when selectedPath is set
  useEffect(() => {
    if (selectedPath) {
      const parts = selectedPath.split('/');
      const idsToExpand: string[] = [];
      for (let i = 1; i < parts.length; i++) {
        idsToExpand.push(`dir:${parts.slice(0, i).join('/')}`);
      }
      if (idsToExpand.length > 0) {
        setExpandedIds((prev) => {
          const next = new Set(prev);
          idsToExpand.forEach((id) => next.add(id));
          return next;
        });
      }
    }
  }, [selectedPath]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleExpandAll = useCallback(() => {
    const allIds = collectAllDirIds(nodes);
    setExpandedIds(new Set(allIds));
  }, [nodes, collectAllDirIds]);

  const handleCollapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  // Build flattened visible list for keyboard navigation and rendering
  const flatVisibleItems = useMemo(() => {
    const list: FlatVisibleItem[] = [];
    const hasFilter = Boolean(filter.trim());

    const traverse = (items: NavigatorTreeNode[] | null | undefined, depth: number) => {
      if (!items || !Array.isArray(items)) return;
      for (const item of items) {
        if (!item) continue;
        const hasChildren = Boolean(item.is_dir && Array.isArray(item.children) && item.children.length > 0);
        const isExpanded = expandedIds.has(item.id) || (hasFilter && matchedDirIds.has(item.id));

        list.push({
          node: item,
          depth,
          isExpanded,
          hasChildren,
        });

        if (item.is_dir && isExpanded && Array.isArray(item.children)) {
          traverse(item.children, depth + 1);
        }
      }
    };

    traverse(filteredNodes, 0);
    return list;
  }, [filteredNodes, expandedIds, filter, matchedDirIds]);



  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (flatVisibleItems.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev < flatVisibleItems.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev > 0 ? prev - 1 : flatVisibleItems.length - 1));
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      if (focusedIndex >= 0 && focusedIndex < flatVisibleItems.length) {
        const item = flatVisibleItems[focusedIndex];
        if (item.node.is_dir && !item.isExpanded) {
          toggleExpand(item.node.id);
        }
      }
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      if (focusedIndex >= 0 && focusedIndex < flatVisibleItems.length) {
        const item = flatVisibleItems[focusedIndex];
        if (item.node.is_dir && item.isExpanded) {
          toggleExpand(item.node.id);
        }
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (focusedIndex >= 0 && focusedIndex < flatVisibleItems.length) {
        const item = flatVisibleItems[focusedIndex];
        if (item.node.is_dir) {
          toggleExpand(item.node.id);
        } else {
          onSelectFile(item.node);
        }
      }
    }
  };

  return (
    <div
      className={`nav-tree-pane density-${density}`}
      data-testid="navigator-tree-container"
      tabIndex={0}
      ref={containerRef}
      onKeyDown={handleKeyDown}
    >
      <div className="nav-tree-header">
        <div className="nav-tree-title-row">
          <div className="nav-tree-title">
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" />
            </svg>
            <span>Files & Modules</span>
          </div>
          <div className="nav-tree-actions">
            <button
              type="button"
              className="nav-icon-btn"
              title="Expand All"
              aria-label="Expand All"
              onClick={handleExpandAll}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m7 15 5 5 5-5M7 9l5-5 5 5" />
              </svg>
            </button>
            <button
              type="button"
              className="nav-icon-btn"
              title="Collapse All"
              aria-label="Collapse All"
              onClick={handleCollapseAll}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m7 20 5-5 5 5M7 4l5 5 5-5" />
              </svg>
            </button>
          </div>
        </div>

        <div className="nav-tree-search-bar">
          <svg className="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            type="text"
            className="nav-tree-search-input"
            placeholder="Search files..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {filter && (
            <button
              type="button"
              className="nav-tree-clear-btn"
              onClick={() => setFilter('')}
              aria-label="Clear filter"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="nav-tree-content">
        {loading ? (
          <div className="nav-loading-wrapper" data-testid="tree-loading-spinner">
            <div className="nav-spinner"></div>
            <span>Loading codebase tree...</span>
          </div>
        ) : flatVisibleItems.length === 0 ? (
          <div className="nav-empty-state">
            <p>No matching files found</p>
            {filter && (
              <button
                type="button"
                className="nav-clear-filter-btn"
                onClick={() => setFilter('')}
              >
                Clear filter
              </button>
            )}
          </div>
        ) : (
          <div className="nav-tree-list" role="tree">
            {flatVisibleItems.map((item, idx) => {
              const { node, depth, isExpanded } = item;
              const isSelected = !node.is_dir && node.path === selectedPath;
              const isFocused = idx === focusedIndex;

              const { icon, className: iconClass } = node.is_dir
                ? { icon: isExpanded ? '📂' : '📁', className: 'icon-dir' }
                : getFileIcon(node.name, node.language);

              return (
                <div
                  key={node.id}
                  role="treeitem"
                  aria-expanded={node.is_dir ? isExpanded : undefined}
                  aria-selected={isSelected}
                  className={`nav-tree-item ${node.is_dir ? 'dir-item' : 'file-item'} ${isSelected ? 'selected' : ''} ${isFocused ? 'focused' : ''}`}
                  style={{ paddingLeft: `${depth * 14 + 10}px` }}
                  onClick={() => {
                    setFocusedIndex(idx);
                    if (node.is_dir) {
                      toggleExpand(node.id);
                    } else {
                      onSelectFile(node);
                    }
                  }}
                >
                  <span className="tree-chevron">
                    {node.is_dir ? (
                      <span className={`chevron-arrow ${isExpanded ? 'open' : ''}`}>▶</span>
                    ) : (
                      <span className="chevron-spacer"></span>
                    )}
                  </span>

                  <span className={`tree-icon ${iconClass}`} aria-hidden="true">
                    {icon}
                  </span>

                  <span className="tree-label" title={node.path}>
                    {node.name}
                  </span>

                  <div className="tree-badges">
                    {node.symbol_count > 0 && (
                      <span className="badge-symbols" title={`${node.symbol_count} AST Symbols`}>
                        {node.symbol_count} sym
                      </span>
                    )}
                    {node.route_count > 0 && (
                      <span className="badge-routes" title={`${node.route_count} API Routes`}>
                        {node.route_count} rts
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
