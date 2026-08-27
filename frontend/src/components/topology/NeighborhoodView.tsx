import React, { useMemo, useCallback } from 'react';
import type { TopologyGraphData, FocalBreadcrumb } from '../../types';
import { buildNeighborhoodGraph, calculateRadialPositions } from './neighborhoodLayout';
import { NODE_COLORS, EDGE_COLORS } from './types';

export interface NeighborhoodViewProps {
  graphData: TopologyGraphData | null;
  focalNodeId: string;
  onSelectFocalNode: (nodeId: string) => void;
  onSelectNodeDetails: (nodeId: string) => void;
  breadcrumbs: FocalBreadcrumb[];
  onNavigateBreadcrumb: (index: number) => void;
  hopRadius: 1 | 2;
  setHopRadius: (hops: 1 | 2) => void;
  typeFilters?: Record<string, boolean>;
}

export function NeighborhoodView({
  graphData,
  focalNodeId,
  onSelectFocalNode,
  onSelectNodeDetails,
  breadcrumbs,
  onNavigateBreadcrumb,
  hopRadius,
  setHopRadius,
  typeFilters,
}: NeighborhoodViewProps) {
  // Helper to check if node type is active according to typeFilters
  const isNodeTypeVisible = useCallback(
    (type: string) => {
      if (!typeFilters) return true;
      return typeFilters[type] !== false;
    },
    [typeFilters]
  );

  // Build isolated neighborhood subgraph
  const subGraph = useMemo(() => {
    if (!graphData?.nodes || graphData.nodes.length === 0) return null;
    return buildNeighborhoodGraph(graphData.nodes, graphData.edges || [], focalNodeId, hopRadius);
  }, [graphData, focalNodeId, hopRadius]);

  // Compute radial layout positions
  const radialPositions = useMemo(() => {
    if (!subGraph) return null;
    return calculateRadialPositions(subGraph, { x: 500, y: 320 }, 180, 300);
  }, [subGraph]);

  // Filtered incoming/outgoing lists for side panels
  const visibleIncoming = useMemo(() => {
    if (!subGraph?.incoming) return [];
    return subGraph.incoming.filter((item) => isNodeTypeVisible(item.node.type));
  }, [subGraph, isNodeTypeVisible]);

  const visibleOutgoing = useMemo(() => {
    if (!subGraph?.outgoing) return [];
    return subGraph.outgoing.filter((item) => isNodeTypeVisible(item.node.type));
  }, [subGraph, isNodeTypeVisible]);

  // Filtered neighbors for canvas
  const visibleNeighbors = useMemo(() => {
    if (!radialPositions?.neighbors) return [];
    return radialPositions.neighbors.filter((item) => isNodeTypeVisible(item.node.type));
  }, [radialPositions, isNodeTypeVisible]);

  // Position lookup map for edge rendering
  const posMap = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    if (subGraph?.focalNode && radialPositions?.focal) {
      if (Number.isFinite(radialPositions.focal.x) && Number.isFinite(radialPositions.focal.y)) {
        map.set(subGraph.focalNode.id, radialPositions.focal);
      }
    }
    visibleNeighbors.forEach((n) => {
      if (Number.isFinite(n.x) && Number.isFinite(n.y)) {
        map.set(n.node.id, { x: n.x, y: n.y });
      }
    });
    return map;
  }, [subGraph, radialPositions, visibleNeighbors]);

  const focalNode = subGraph?.focalNode;
  const focalPos = radialPositions?.focal || { x: 500, y: 320 };
  const focalColor = focalNode ? (NODE_COLORS[focalNode.type] || NODE_COLORS.file) : NODE_COLORS.file;

  return (
    <div className="neighborhood-view">
      {/* Top Breadcrumbs Navigation Bar */}
      <div className="neighborhood-breadcrumbs">
        <div className="neighborhood-breadcrumbs-left">
          <button
            type="button"
            className="btn btn-secondary btn-sm neighborhood-back-btn"
            disabled={breadcrumbs.length <= 1}
            onClick={() => {
              if (breadcrumbs.length > 1) {
                onNavigateBreadcrumb(breadcrumbs.length - 2);
              }
            }}
            aria-label="Back"
          >
            <i className="fa-solid fa-arrow-left"></i> Back
          </button>

          <nav className="neighborhood-breadcrumb-trail" aria-label="Breadcrumb">
            {breadcrumbs.map((bc, index) => {
              const isLast = index === breadcrumbs.length - 1;
              return (
                <React.Fragment key={`${bc.id}-${index}`}>
                  {index > 0 && <span className="neighborhood-breadcrumb-sep">›</span>}
                  <button
                    type="button"
                    className={`neighborhood-breadcrumb-item ${isLast ? 'active' : ''}`}
                    onClick={() => onNavigateBreadcrumb(index)}
                    title={`Navigate to ${bc.name}`}
                  >
                    <span className={`topology-badge-type badge-${bc.type || 'file'} neighborhood-breadcrumb-badge`}>
                      {bc.type || 'file'}
                    </span>
                    <span className="neighborhood-breadcrumb-text">{bc.name}</span>
                  </button>
                </React.Fragment>
              );
            })}
          </nav>
        </div>

        <div className="neighborhood-breadcrumbs-right">
          <div className="neighborhood-hop-selector" role="group" aria-label="Hop Radius">
            <span className="neighborhood-hop-label">Neighborhood:</span>
            <div className="topology-view-btn-group">
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
          </div>
        </div>
      </div>

      {/* Main Neighborhood Layout: Left Column, Central Radial Canvas, Right Column */}
      {(!graphData || !graphData.nodes || graphData.nodes.length === 0 || !focalNode) ? (
        <div className="topology-empty-state neighborhood-empty-state">
          <i className="fa-solid fa-circle-nodes fa-2xl"></i>
          <p>No graph data available for neighborhood view</p>
        </div>
      ) : (
        <div className="neighborhood-panels">
          {/* Left Column: Incoming Dependencies Panel */}
          <div className="neighborhood-panel neighborhood-panel-incoming">
            <div className="neighborhood-panel-header">
              <div className="neighborhood-panel-title">
                <i className="fa-solid fa-arrow-right-to-bracket"></i> Incoming Dependencies
              </div>
              <span className="neighborhood-panel-count">{visibleIncoming.length}</span>
            </div>

            <div className="neighborhood-panel-list">
              {visibleIncoming.length === 0 ? (
                <div className="neighborhood-panel-empty">No incoming dependencies</div>
              ) : (
                visibleIncoming.map((item) => (
                  <div key={`in-${item.node.id}-${item.edgeType}`} className="neighborhood-panel-item">
                    <div className="neighborhood-panel-item-header">
                      <span className={`topology-badge-type badge-${item.node.type}`}>{item.node.type}</span>
                      <span className={`topology-badge-type badge-edge-${(item.edgeType || 'CALLS').toLowerCase().replace(/_/g, '-')}`}>
                        {item.label || item.edgeType}
                      </span>
                    </div>
                    <div className="neighborhood-panel-item-name" title={item.node.name}>
                      {item.node.name}
                    </div>
                    <div className="neighborhood-panel-item-actions">
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => onSelectFocalNode(item.node.id)}
                        title="Focus node"
                      >
                        Focus
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => onSelectNodeDetails(item.node.id)}
                        title="Inspect details"
                      >
                        Inspect
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Central Focused Concentric Canvas Area */}
          <div className="neighborhood-center">
            <div className="neighborhood-canvas-wrapper">
              <svg
                viewBox="0 0 1000 640"
                className="neighborhood-svg"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <marker
                    id="neighborhood-arrow"
                    viewBox="0 0 10 10"
                    refX="20"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse"
                  >
                    <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="#64748b" />
                  </marker>
                  <filter id="focal-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="8" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>

                {/* Orbital Guide Circles */}
                {Number.isFinite(focalPos.x) && Number.isFinite(focalPos.y) && (
                  <g className="neighborhood-orbital-rings">
                    {/* Ring 1 (R = 180) */}
                    <circle
                      cx={focalPos.x}
                      cy={focalPos.y}
                      r={180}
                      className="neighborhood-orbital-ring ring-1"
                    />
                    <text
                      x={focalPos.x}
                      y={focalPos.y - 186}
                      className="neighborhood-orbital-label"
                      textAnchor="middle"
                    >
                      1-Hop Ring
                    </text>

                    {/* Ring 2 (R = 300) when hopRadius == 2 */}
                    {hopRadius >= 2 && (
                      <>
                        <circle
                          cx={focalPos.x}
                          cy={focalPos.y}
                          r={300}
                          className="neighborhood-orbital-ring ring-2"
                        />
                        <text
                          x={focalPos.x}
                          y={focalPos.y - 306}
                          className="neighborhood-orbital-label"
                          textAnchor="middle"
                        >
                          2-Hop Ring
                        </text>
                      </>
                    )}
                  </g>
                )}

                {/* Edges */}
                <g className="neighborhood-edges">
                  {subGraph.edges.map((edge, idx) => {
                    const sourcePos = posMap.get(edge.source);
                    const targetPos = posMap.get(edge.target);
                    if (!sourcePos || !targetPos) return null;
                    if (
                      !Number.isFinite(sourcePos.x) ||
                      !Number.isFinite(sourcePos.y) ||
                      !Number.isFinite(targetPos.x) ||
                      !Number.isFinite(targetPos.y)
                    ) {
                      return null;
                    }

                    // Quadratic curve with slight midpoint offset
                    const mx = (sourcePos.x + targetPos.x) / 2;
                    const my = (sourcePos.y + targetPos.y) / 2;
                    const pathD = `M ${sourcePos.x} ${sourcePos.y} Q ${mx} ${my} ${targetPos.x} ${targetPos.y}`;

                    const edgeColor = EDGE_COLORS[edge.type]?.stroke || '#64748b';
                    const dashArray = EDGE_COLORS[edge.type]?.dasharray;
                    const strokeWidth = EDGE_COLORS[edge.type]?.width || 1.4;

                    return (
                      <path
                        key={`edge-${edge.source}-${edge.target}-${idx}`}
                        d={pathD}
                        fill="none"
                        stroke={edgeColor}
                        strokeWidth={strokeWidth}
                        strokeDasharray={dashArray}
                        strokeOpacity={0.65}
                        markerEnd="url(#neighborhood-arrow)"
                        className="neighborhood-edge-path"
                      />
                    );
                  })}
                </g>

                {/* Neighbor Nodes */}
                <g className="neighborhood-nodes">
                  {visibleNeighbors.map((item) => {
                    if (!Number.isFinite(item.x) || !Number.isFinite(item.y)) return null;
                    const color = NODE_COLORS[item.node.type] || NODE_COLORS.file;
                    const radius = item.ring === 1 ? 22 : 16;
                    const displayName = item.node.name.length > 18
                      ? item.node.name.slice(0, 16) + '…'
                      : item.node.name;

                    return (
                      <g
                        key={`neighbor-${item.node.id}`}
                        data-node-id={item.node.id}
                        className="neighborhood-node-item"
                        transform={`translate(${item.x}, ${item.y})`}
                        onClick={() => onSelectFocalNode(item.node.id)}
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          onSelectNodeDetails(item.node.id);
                        }}
                        style={{ cursor: 'pointer' }}
                      >
                        <title>{`${item.node.name} (${item.node.type}) - Click to focus, double-click to inspect`}</title>
                        <circle
                          r={radius}
                          fill={color.fill}
                          stroke={color.stroke}
                          strokeWidth={2}
                          className="neighborhood-node-circle"
                        />
                        <text
                          textAnchor="middle"
                          dy={item.ring === 1 ? '4' : '3'}
                          fontSize={item.ring === 1 ? '9' : '8'}
                          fill="#ffffff"
                          fontWeight="600"
                          pointerEvents="none"
                        >
                          {item.node.type.slice(0, 3).toUpperCase()}
                        </text>
                        <text
                          textAnchor="middle"
                          dy={radius + 14}
                          className="neighborhood-node-name"
                          fontSize="11"
                          fill="var(--text)"
                          pointerEvents="none"
                        >
                          {displayName}
                        </text>
                      </g>
                    );
                  })}
                </g>

                {/* Center Focal Node */}
                {Number.isFinite(focalPos.x) && Number.isFinite(focalPos.y) && (
                  <g
                    className="neighborhood-focal-node"
                    transform={`translate(${focalPos.x}, ${focalPos.y})`}
                    data-node-id={focalNode.id}
                    onDoubleClick={() => onSelectNodeDetails(focalNode.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <title>{`${focalNode.name} (${focalNode.type}) - Focal Node`}</title>
                    {/* Glowing animated halo */}
                    <circle
                      r={42}
                      className="focal-pulse-ring"
                      fill="none"
                      stroke={focalColor.stroke}
                      strokeWidth={2.5}
                    />
                    {/* Focal main body */}
                    <circle
                      r={32}
                      fill={focalColor.fill}
                      stroke={focalColor.stroke}
                      strokeWidth={3}
                      className="focal-body"
                    />
                    <text
                      textAnchor="middle"
                      dy="4"
                      fontSize="11"
                      fill="#ffffff"
                      fontWeight="700"
                      pointerEvents="none"
                    >
                      {focalNode.type.slice(0, 4).toUpperCase()}
                    </text>
                    {/* Label Badge below Focal Node */}
                    <g transform="translate(0, 48)">
                      <rect
                        x={-(Math.max(focalNode.name.length * 4.5, 50) + 12)}
                        y={-10}
                        width={(Math.max(focalNode.name.length * 4.5, 50) + 12) * 2}
                        height={20}
                        rx={6}
                        fill="rgba(15, 23, 42, 0.85)"
                        stroke="var(--border-card)"
                      />
                      <text
                        textAnchor="middle"
                        dy="4"
                        fontSize="12"
                        fontWeight="600"
                        fill="var(--text)"
                        pointerEvents="none"
                      >
                        {focalNode.name}
                      </text>
                    </g>
                  </g>
                )}
              </svg>
            </div>
          </div>

          {/* Right Column: Outgoing Dependencies Panel */}
          <div className="neighborhood-panel neighborhood-panel-outgoing">
            <div className="neighborhood-panel-header">
              <div className="neighborhood-panel-title">
                <i className="fa-solid fa-arrow-right-from-bracket"></i> Outgoing Dependencies
              </div>
              <span className="neighborhood-panel-count">{visibleOutgoing.length}</span>
            </div>

            <div className="neighborhood-panel-list">
              {visibleOutgoing.length === 0 ? (
                <div className="neighborhood-panel-empty">No outgoing dependencies</div>
              ) : (
                visibleOutgoing.map((item) => (
                  <div key={`out-${item.node.id}-${item.edgeType}`} className="neighborhood-panel-item">
                    <div className="neighborhood-panel-item-header">
                      <span className={`topology-badge-type badge-${item.node.type}`}>{item.node.type}</span>
                      <span className={`topology-badge-type badge-edge-${(item.edgeType || 'CALLS').toLowerCase().replace(/_/g, '-')}`}>
                        {item.label || item.edgeType}
                      </span>
                    </div>
                    <div className="neighborhood-panel-item-name" title={item.node.name}>
                      {item.node.name}
                    </div>
                    <div className="neighborhood-panel-item-actions">
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => onSelectFocalNode(item.node.id)}
                        title="Focus node"
                      >
                        Focus
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => onSelectNodeDetails(item.node.id)}
                        title="Inspect details"
                      >
                        Inspect
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
