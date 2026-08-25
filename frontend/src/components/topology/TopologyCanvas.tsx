import React from 'react';
import type { MouseEvent, WheelEvent } from 'react';
import type { TopologyEdge } from '../../types';
import type { SimNode } from './types';
import { NODE_COLORS, EDGE_COLORS } from './types';
import { TopologyMinimap } from './TopologyMinimap';

interface TopologyCanvasProps {
  canvasRef: React.RefObject<SVGSVGElement | null>;
  visibleNodes: SimNode[];
  visibleEdges: TopologyEdge[];
  nodePosMap: Map<string, { x: number; y: number; radius: number }>;
  pan: { x: number; y: number };
  zoom: number;
  setZoom: React.Dispatch<React.SetStateAction<number>>;
  setPan: React.Dispatch<React.SetStateAction<{ x: number; y: number }>>;
  isSimPaused: boolean;
  setIsSimPaused: React.Dispatch<React.SetStateAction<boolean>>;
  loading: boolean;
  edgeFilters: Record<string, boolean>;
  setEdgeFilters: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  selectedNodeId: string | null;
  searchQuery: string;
  onSelectNode: (id: string) => void;
  setDraggedNodeId: (id: string | null) => void;
  onMouseDown: (e: MouseEvent) => void;
  onMouseMove: (e: MouseEvent) => void;
  onMouseUp: () => void;
  onWheel: (e: WheelEvent) => void;
}

export function TopologyCanvas({
  canvasRef,
  visibleNodes,
  visibleEdges,
  nodePosMap,
  pan,
  zoom,
  setZoom,
  setPan,
  isSimPaused,
  setIsSimPaused,
  loading,
  edgeFilters,
  setEdgeFilters,
  selectedNodeId,
  searchQuery,
  onSelectNode,
  setDraggedNodeId,
  onMouseDown,
  onMouseMove,
  onMouseUp,
  onWheel,
}: TopologyCanvasProps) {
  return (
    <div
      className="topology-canvas-wrapper"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onWheel={onWheel}
    >
      {/* Floating Legend / Edge filters */}
      <div className="topology-legend">
        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginRight: '4px' }}>Nodes:</span>
        <span className="topology-badge-type badge-file">File</span>
        <span className="topology-badge-type badge-class">Class</span>
        <span className="topology-badge-type badge-function">Function</span>
        <span className="topology-badge-type badge-route">Route</span>
        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0 4px 0 8px' }}>Edges:</span>
        {(['IMPORTS', 'CALLS', 'DEFINES', 'HANDLES', 'ROUTES_TO'] as const).map((et) => (
          <span
            key={et}
            className={`topology-badge-type badge-edge-${et.toLowerCase().replace('_', '-')} ${edgeFilters[et] ? '' : 'inactive'}`}
            style={{ cursor: 'pointer', opacity: edgeFilters[et] ? 1 : 0.4 }}
            onClick={() => setEdgeFilters((prev) => ({ ...prev, [et]: !prev[et] }))}
            title={`Toggle ${et} edges`}
          >
            {et}
          </span>
        ))}
      </div>

      {/* Floating Canvas Controls */}
      <div className="topology-controls-panel">
        <button className="topology-btn-ctrl" onClick={() => setZoom((z) => Math.min(3.5, z * 1.25))} title="Zoom In">
          <i className="fa-solid fa-plus"></i>
        </button>
        <button className="topology-btn-ctrl" onClick={() => setZoom((z) => Math.max(0.2, z / 1.25))} title="Zoom Out">
          <i className="fa-solid fa-minus"></i>
        </button>
        <button className="topology-btn-ctrl" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} title="Reset View">
          <i className="fa-solid fa-arrows-rotate"></i>
        </button>
        <button
          className="topology-btn-ctrl"
          onClick={() => setIsSimPaused((p) => !p)}
          title={isSimPaused ? 'Resume Physics' : 'Pause Physics'}
        >
          <i className={`fa-solid ${isSimPaused ? 'fa-play' : 'fa-pause'}`}></i>
        </button>
      </div>

      {/* MiniMap Viewport */}
      <TopologyMinimap visibleNodes={visibleNodes} visibleEdges={visibleEdges} nodePosMap={nodePosMap} />

      {/* SVG Interactive Canvas */}
      <svg
        ref={canvasRef}
        viewBox="0 0 1000 640"
        className="topology-svg"
      >
        <defs>
          <marker
            id="arrow-default"
            viewBox="0 0 10 10"
            refX="16"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
          <marker
            id="arrow-HANDLES"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#fbbf24" />
          </marker>
          <marker
            id="arrow-ROUTES_TO"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#fb7185" />
          </marker>
        </defs>

        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {/* Edges */}
          {visibleEdges.map((e, idx) => {
            const p1 = nodePosMap.get(e.source);
            const p2 = nodePosMap.get(e.target);
            if (!p1 || !p2) return null;

            const style = EDGE_COLORS[e.type] || { stroke: '#94a3b8', width: 1.2 };
            const markerId = e.type === 'HANDLES' ? 'url(#arrow-HANDLES)' : e.type === 'ROUTES_TO' ? 'url(#arrow-ROUTES_TO)' : 'url(#arrow-default)';

            return (
              <g key={`edge-${idx}`}>
                <line
                  x1={p1.x}
                  y1={p1.y}
                  x2={p2.x}
                  y2={p2.y}
                  stroke={style.stroke}
                  strokeWidth={style.width}
                  strokeDasharray={style.dasharray}
                  strokeOpacity={0.65}
                  markerEnd={markerId}
                  className="topology-edge"
                />
                {e.label && (
                  <text
                    x={(p1.x + p2.x) / 2}
                    y={(p1.y + p2.y) / 2 - 4}
                    fill="#94a3b8"
                    fontSize="9"
                    textAnchor="middle"
                    opacity={0.7}
                  >
                    {e.label}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {visibleNodes.map((n) => {
            const colors = NODE_COLORS[n.type] || NODE_COLORS.file;
            const isSelected = selectedNodeId === n.id;
            const isHighlighted = searchQuery && n.name && n.name.toLowerCase().includes(searchQuery.toLowerCase());

            return (
              <g
                key={`node-${n.id}`}
                data-testid={`node-${n.id}`}
                role="button"
                aria-label={`Node ${n.name}`}
                tabIndex={0}
                transform={`translate(${n.x}, ${n.y})`}
                className={`topology-node ${isSelected ? 'selected' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectNode(n.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    onSelectNode(n.id);
                  }
                }}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setDraggedNodeId(n.id);
                }}
              >
                <circle
                  data-testid={`circle-${n.id}`}
                  r={n.radius}
                  fill={colors.fill}
                  stroke={colors.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                  filter={`drop-shadow(0 0 6px ${colors.glow})`}
                />
                <text
                  y={n.radius + 14}
                  fill={colors.text}
                  fontSize="11"
                  fontWeight={isSelected ? '700' : '500'}
                  textAnchor="middle"
                >
                  {(n.name || '').length > 22 ? (n.name || '').slice(0, 20) + '…' : (n.name || '')}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {loading && (
        <div className="topology-empty-state">
          <i className="fa-solid fa-spinner fa-spin fa-2x" style={{ color: 'var(--primary)' }}></i>
          <p>Constructing topology graph...</p>
        </div>
      )}

      {!loading && visibleNodes.length === 0 && (
        <div className="topology-empty-state">
          <i className="fa-solid fa-diagram-project fa-3x" style={{ opacity: 0.3 }}></i>
          <p>No graph nodes found matching current filters.</p>
        </div>
      )}
    </div>
  );
}
