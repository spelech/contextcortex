import React from 'react';
import type { Repo, TopologyNode, TopologyViewMode } from '../../types';

export interface TopologyControlsProps {
  repos: Repo[];
  selectedRepo: string;
  setSelectedRepo: (val: string) => void;
  viewMode: TopologyViewMode;
  setViewMode: (val: TopologyViewMode) => void;
  hopRadius?: 1 | 2;
  setHopRadius?: (val: 1 | 2) => void;
  viewType: 'files' | 'symbols' | 'routes' | 'full';
  setViewType: (val: 'files' | 'symbols' | 'routes' | 'full') => void;
  depth: number;
  setDepth: (val: number) => void;
  nodeLimit: number;
  setNodeLimit: (val: number) => void;
  hideOrphans: boolean;
  setHideOrphans: React.Dispatch<React.SetStateAction<boolean>>;
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
  onAutoFit?: () => void;
  onExportSVG: () => void;
  onExportJSON: () => void;
}

export function TopologyControls({
  repos,
  selectedRepo,
  setSelectedRepo,
  viewMode,
  setViewMode,
  hopRadius = 1,
  setHopRadius,
  viewType,
  setViewType,
  depth,
  setDepth,
  nodeLimit,
  setNodeLimit,
  hideOrphans,
  setHideOrphans,
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
  onAutoFit,
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

        {/* View Mode Segmented Toggle */}
        <div className="topology-view-btn-group" role="group" aria-label="View Mode">
          <button
            type="button"
            className={`topology-view-btn ${viewMode === 'neighborhood' ? 'active' : ''}`}
            onClick={() => setViewMode('neighborhood')}
            title="Focused neighborhood drill-down with concentric radial layout and breadcrumbs"
          >
            <i className="fa-solid fa-crosshairs"></i> Neighborhood View
          </button>
          <button
            type="button"
            className={`topology-view-btn ${viewMode === 'canvas' ? 'active' : ''}`}
            onClick={() => setViewMode('canvas')}
            title="High-performance full graph 2D canvas engine"
          >
            <i className="fa-solid fa-network-wired"></i> Global 2D Canvas
          </button>
        </div>

        {/* View Type Toggle */}
        <div className="topology-view-btn-group" role="group" aria-label="View Type">
          {(['files', 'symbols', 'routes', 'full'] as const).map((vt) => (
            <button
              key={vt}
              type="button"
              className={`topology-view-btn ${viewType === vt ? 'active' : ''}`}
              onClick={() => setViewType(vt)}
            >
              {vt.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Contextual Controls based on viewMode */}
        {viewMode === 'neighborhood' ? (
          setHopRadius && (
            <div className="topology-view-btn-group" role="group" aria-label="Hop Radius">
              <button
                type="button"
                className={`topology-view-btn ${hopRadius === 1 ? 'active' : ''}`}
                onClick={() => setHopRadius(1)}
              >
                1-Hop
              </button>
              <button
                type="button"
                className={`topology-view-btn ${hopRadius === 2 ? 'active' : ''}`}
                onClick={() => setHopRadius(2)}
              >
                2-Hop
              </button>
            </div>
          )
        ) : (
          <>
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

            {/* Node Limit Selector */}
            <select
              className="topology-select"
              value={nodeLimit}
              onChange={(e) => setNodeLimit(Number(e.target.value))}
              aria-label="Node Limit"
            >
              <option value={50}>50 nodes</option>
              <option value={100}>100 nodes</option>
              <option value={150}>150 nodes</option>
              <option value={200}>200 nodes</option>
              <option value={400}>400 nodes</option>
              <option value={800}>800 nodes</option>
            </select>
          </>
        )}

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

        {/* Hide Orphans Toggle Chip - shown in canvas mode */}
        {viewMode === 'canvas' && (
          <span
            className={`topology-filter-chip chip-orphan ${hideOrphans ? '' : 'inactive'}`}
            onClick={() => setHideOrphans((prev) => !prev)}
            title="Toggle orphan nodes"
            role="button"
          >
            <i className="fa-solid fa-filter"></i>
            HIDE ORPHANS
          </span>
        )}

        {onAutoFit && viewMode === 'canvas' && (
          <button className="btn btn-secondary btn-sm" onClick={onAutoFit} title="Fit Graph">
            <i className="fa-solid fa-expand"></i> Fit Graph
          </button>
        )}

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
