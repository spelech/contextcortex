import React from 'react';
import type { Repo, TopologyNode } from '../../types';

interface TopologyControlsProps {
  repos: Repo[];
  selectedRepo: string;
  setSelectedRepo: (val: string) => void;
  viewType: 'files' | 'symbols' | 'routes' | 'full';
  setViewType: (val: 'files' | 'symbols' | 'routes' | 'full') => void;
  depth: number;
  setDepth: (val: number) => void;
  rootNode: string;
  setRootNode: (val: string) => void;
  searchQuery: string;
  setSearchQuery: (val: string) => void;
  searchFocused: boolean;
  setSearchFocused: (val: boolean) => void;
  searchMatches: TopologyNode[];
  onFocusNode: (id: string) => void;
  typeFilters: Record<string, boolean>;
  setTypeFilters: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  onExportSVG: () => void;
  onExportJSON: () => void;
}

export function TopologyControls({
  repos,
  selectedRepo,
  setSelectedRepo,
  viewType,
  setViewType,
  depth,
  setDepth,
  rootNode,
  setRootNode,
  searchQuery,
  setSearchQuery,
  searchFocused,
  setSearchFocused,
  searchMatches,
  onFocusNode,
  typeFilters,
  setTypeFilters,
  onExportSVG,
  onExportJSON,
}: TopologyControlsProps) {
  return (
    <div className="topology-toolbar">
      <div className="topology-toolbar-group">
        {/* Repo selector */}
        <select
          className="topology-select"
          value={selectedRepo}
          onChange={(e) => setSelectedRepo(e.target.value)}
          aria-label="Select Repository"
        >
          <option value="__all__">🌐 All Repositories (__all__)</option>
          {repos.map((r) => (
            <option key={r.id || r.name} value={r.name}>
              📁 {r.name}
            </option>
          ))}
        </select>

        {/* View Type Toggle */}
        <div className="topology-view-btn-group" role="group" aria-label="View Type">
          {(['files', 'symbols', 'routes', 'full'] as const).map((vt) => (
            <button
              key={vt}
              className={`topology-view-btn ${viewType === vt ? 'active' : ''}`}
              onClick={() => setViewType(vt)}
            >
              {vt.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Depth Selector */}
        <select
          className="topology-select"
          value={depth}
          onChange={(e) => setDepth(Number(e.target.value))}
          aria-label="Graph Depth"
        >
          <option value={1}>Depth: 1 Hop</option>
          <option value={2}>Depth: 2 Hops</option>
          <option value={3}>Depth: 3 Hops</option>
          <option value={4}>Depth: 4 Hops</option>
          <option value={5}>Depth: 5 Hops</option>
        </select>

        {/* Root node active indicator */}
        {rootNode && (
          <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            Root: {rootNode}
            <button
              style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}
              onClick={() => setRootNode('')}
              title="Clear Root Focus"
            >
              <i className="fa-solid fa-xmark"></i>
            </button>
          </span>
        )}
      </div>

      {/* Search Bar & Autocomplete */}
      <div className="topology-toolbar-group" style={{ position: 'relative', flex: 1, maxWidth: '320px' }}>
        <input
          type="text"
          className="topology-input"
          style={{ width: '100%' }}
          placeholder="Search nodes or routes..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={() => setSearchFocused(true)}
          aria-label="Search nodes"
        />
        {searchFocused && searchMatches.length > 0 && (
          <div className="topology-search-results">
            {searchMatches.map((m) => (
              <div
                key={m.id}
                className="topology-search-item"
                onClick={() => onFocusNode(m.id)}
              >
                <span style={{ fontWeight: 600 }}>{m.name}</span>
                <span className={`topology-badge-type badge-${m.type}`}>{m.type}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Node Type Filters & Exports */}
      <div className="topology-toolbar-group">
        {(['file', 'class', 'function', 'route'] as const).map((t) => (
          <span
            key={t}
            className={`topology-filter-chip chip-${t} ${typeFilters[t] ? '' : 'inactive'}`}
            onClick={() => setTypeFilters((prev) => ({ ...prev, [t]: !prev[t] }))}
            title={`Toggle ${t} nodes`}
          >
            <i className={`fa-solid ${t === 'file' ? 'fa-file-code' : t === 'class' ? 'fa-cube' : t === 'function' ? 'fa-bolt' : 'fa-network-wired'}`}></i>
            {t.toUpperCase()}
          </span>
        ))}

        <button className="btn btn-secondary btn-sm" onClick={onExportSVG} title="Export as SVG">
          <i className="fa-solid fa-file-image"></i> SVG
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onExportJSON} title="Export as JSON">
          <i className="fa-solid fa-code"></i> JSON
        </button>
      </div>
    </div>
  );
}
