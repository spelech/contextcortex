import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import type { MouseEvent, WheelEvent } from 'react';
import type { TopologyNode, TopologyGraphData, NodeDetails, Repo } from './types';
import { useToast } from './ToastContext';

interface SimNode extends TopologyNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
}

const NODE_COLORS: Record<string, { fill: string; stroke: string; glow: string; text: string }> = {
  file: { fill: '#0369a1', stroke: '#38bdf8', glow: 'rgba(56, 189, 248, 0.4)', text: '#e0f2fe' },
  class: { fill: '#7e22ce', stroke: '#c084fc', glow: 'rgba(192, 132, 252, 0.4)', text: '#f3e8ff' },
  function: { fill: '#047857', stroke: '#34d399', glow: 'rgba(52, 211, 153, 0.4)', text: '#ecfdf5' },
  route: { fill: '#b45309', stroke: '#fbbf24', glow: 'rgba(251, 191, 36, 0.4)', text: '#fffbeb' },
  module: { fill: '#4338ca', stroke: '#818cf8', glow: 'rgba(129, 140, 248, 0.4)', text: '#e0e7ff' },
};

const EDGE_COLORS: Record<string, { stroke: string; dasharray?: string; width: number }> = {
  IMPORTS: { stroke: '#38bdf8', dasharray: '4 3', width: 1.5 },
  CALLS: { stroke: '#34d399', width: 1.5 },
  DEFINES: { stroke: '#c084fc', width: 1.2 },
  HANDLES: { stroke: '#fbbf24', width: 2 },
  ROUTES_TO: { stroke: '#fb7185', dasharray: '5 3', width: 2 },
};

export default function TopologyExplorer() {
  const toast = useToast();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('__all__');
  const [viewType, setViewType] = useState<'files' | 'symbols' | 'routes' | 'full'>('files');
  const [depth, setDepth] = useState<number>(2);
  const [rootNode, setRootNode] = useState<string>('');
  
  // Filtering toggles
  const [typeFilters, setTypeFilters] = useState<Record<string, boolean>>({
    file: true,
    class: true,
    function: true,
    route: true,
    module: true,
  });
  
  const [edgeFilters, setEdgeFilters] = useState<Record<string, boolean>>({
    IMPORTS: true,
    CALLS: true,
    DEFINES: true,
    HANDLES: true,
    ROUTES_TO: true,
  });

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchFocused, setSearchFocused] = useState<boolean>(false);

  // Graph data & simulation
  const [graphData, setGraphData] = useState<TopologyGraphData | null>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Canvas pan & zoom
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState<number>(1);
  const [isPanning, setIsPanning] = useState<boolean>(false);
  const [panStart, setPanStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [isSimPaused, setIsSimPaused] = useState<boolean>(false);

  // Inspector Drawer
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetails, setNodeDetails] = useState<NodeDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState<boolean>(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  const canvasRef = useRef<SVGSVGElement | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  simNodesRef.current = simNodes;

  // Load repositories on mount
  useEffect(() => {
    const fetchRepos = async () => {
      try {
        const res = await fetch('/admin/api/repos');
        if (res.ok) {
          const data = await res.json();
          setRepos(data || []);
        }
      } catch (e) {
        console.error('Failed to load repos:', e);
      }
    };
    fetchRepos();
  }, []);

  // Fetch graph data
  const loadTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = `/admin/api/graph/topology?repo=${encodeURIComponent(selectedRepo)}&view_type=${viewType}&depth=${depth}&limit=400`;
      if (rootNode.trim()) {
        url += `&root_node=${encodeURIComponent(rootNode.trim())}`;
      }
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to load topology');
      }
      setGraphData(data);

      // Initialize simulation node positions
      const width = 1000;
      const height = 640;
      const nodeCount = data.nodes.length;
      const radius = Math.min(width, height) * 0.38;

      const initialSimNodes: SimNode[] = data.nodes.map((node: TopologyNode, idx: number) => {
        const angle = (idx / (nodeCount || 1)) * 2 * Math.PI;
        const dist = radius * (0.4 + 0.6 * Math.random());
        const r = node.type === 'route' ? 24 : node.type === 'class' ? 22 : node.type === 'file' ? 20 : 18;
        return {
          ...node,
          x: width / 2 + dist * Math.cos(angle) + (Math.random() - 0.5) * 40,
          y: height / 2 + dist * Math.sin(angle) + (Math.random() - 0.5) * 40,
          vx: 0,
          vy: 0,
          radius: r,
        };
      });

      setSimNodes(initialSimNodes);
      setPan({ x: 0, y: 0 });
      setZoom(1);
    } catch (err: any) {
      setError(err.message);
      toast.error('Topology loading error: ' + err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedRepo, viewType, depth, rootNode, toast]);

  useEffect(() => {
    loadTopology();
  }, [loadTopology]);

  // Load Node Details
  const handleSelectNode = async (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setIsDrawerOpen(true);
    setLoadingDetails(true);
    try {
      const res = await fetch(`/admin/api/graph/node-details?id=${encodeURIComponent(nodeId)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Node details not found');
      setNodeDetails(data);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setLoadingDetails(false);
    }
  };

  // Filtered nodes and edges for rendering
  const visibleNodes = useMemo(() => {
    return simNodes.filter((n) => typeFilters[n.type] ?? true);
  }, [simNodes, typeFilters]);

  const visibleNodeIds = useMemo(() => {
    return new Set(visibleNodes.map((n) => n.id));
  }, [visibleNodes]);

  const visibleEdges = useMemo(() => {
    if (!graphData?.edges) return [];
    return graphData.edges.filter(
      (e) =>
        (edgeFilters[e.type] ?? true) &&
        visibleNodeIds.has(e.source) &&
        visibleNodeIds.has(e.target)
    );
  }, [graphData, edgeFilters, visibleNodeIds]);

  // Node position lookup
  const nodePosMap = useMemo(() => {
    const map = new Map<string, { x: number; y: number; radius: number }>();
    visibleNodes.forEach((n) => map.set(n.id, { x: n.x, y: n.y, radius: n.radius }));
    return map;
  }, [visibleNodes]);

  // Physics Simulation Step
  useEffect(() => {
    if (isSimPaused || visibleNodes.length === 0) return;

    let iteration = 0;
    const maxIterations = 250;

    const stepSimulation = () => {
      iteration++;
      const nodes = [...simNodesRef.current];
      if (nodes.length === 0) return;

      const width = 1000;
      const height = 640;
      const kRepulse = 3800;
      const kSpring = 0.04;
      const springLength = 110;
      const centerGravity = 0.015;
      const damping = 0.85;

      const nodeIndex = new Map<string, number>();
      nodes.forEach((n, i) => nodeIndex.set(n.id, i));

      // 1. Repulsion between all node pairs
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x;
          const dy = nodes[j].y - nodes[i].y;
          const distSq = dx * dx + dy * dy + 100;
          const dist = Math.sqrt(distSq);
          const force = kRepulse / distSq;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (nodes[i].id !== draggedNodeId) {
            nodes[i].vx -= fx;
            nodes[i].vy -= fy;
          }
          if (nodes[j].id !== draggedNodeId) {
            nodes[j].vx += fx;
            nodes[j].vy += fy;
          }
        }
      }

      // 2. Spring attraction along edges
      if (graphData?.edges) {
        for (const edge of graphData.edges) {
          const i1 = nodeIndex.get(edge.source);
          const i2 = nodeIndex.get(edge.target);
          if (i1 === undefined || i2 === undefined) continue;

          const n1 = nodes[i1];
          const n2 = nodes[i2];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const displacement = dist - springLength;
          const force = displacement * kSpring;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (n1.id !== draggedNodeId) {
            n1.vx += fx;
            n1.vy += fy;
          }
          if (n2.id !== draggedNodeId) {
            n2.vx += fx;
            n2.vy += fy;
          }
        }
      }

      // 3. Gravity towards center and position update
      let totalKineticEnergy = 0;
      for (const node of nodes) {
        if (node.id === draggedNodeId) continue;

        // Center pull
        node.vx += (width / 2 - node.x) * centerGravity;
        node.vy += (height / 2 - node.y) * centerGravity;

        // Apply damping
        node.vx *= damping;
        node.vy *= damping;

        // Update pos
        node.x += node.vx;
        node.y += node.vy;

        totalKineticEnergy += node.vx * node.vx + node.vy * node.vy;
      }

      setSimNodes([...nodes]);

      if (iteration < maxIterations && totalKineticEnergy > 0.5) {
        animFrameRef.current = requestAnimationFrame(stepSimulation);
      }
    };

    animFrameRef.current = requestAnimationFrame(stepSimulation);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [graphData, isSimPaused, draggedNodeId]);

  // Mouse pan and zoom handlers
  const handleMouseDown = (e: MouseEvent) => {
    if (e.target === canvasRef.current || (e.target as HTMLElement).tagName === 'svg') {
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    } else if (draggedNodeId) {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const mouseX = (e.clientX - rect.left - pan.x) / zoom;
      const mouseY = (e.clientY - rect.top - pan.y) / zoom;

      setSimNodes((prev) =>
        prev.map((n) => (n.id === draggedNodeId ? { ...n, x: mouseX, y: mouseY, vx: 0, vy: 0 } : n))
      );
    }
  };

  const handleMouseUp = () => {
    setIsPanning(false);
    setDraggedNodeId(null);
  };

  const handleWheel = (e: WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.88;
    setZoom((prev) => Math.max(0.2, Math.min(3.5, prev * zoomFactor)));
  };

  // Search filter matches
  const searchMatches = useMemo(() => {
    if (!searchQuery.trim() || !graphData?.nodes) return [];
    const q = searchQuery.toLowerCase().trim();
    return graphData.nodes.filter(
      (n) =>
        n.name.toLowerCase().includes(q) ||
        (n.filepath && n.filepath.toLowerCase().includes(q)) ||
        (n.path_pattern && n.path_pattern.toLowerCase().includes(q))
    ).slice(0, 10);
  }, [searchQuery, graphData]);

  // Center canvas on a specific node
  const focusOnNode = (nodeId: string) => {
    const node = simNodes.find((n) => n.id === nodeId);
    if (node) {
      const width = 1000;
      const height = 640;
      setZoom(1.4);
      setPan({
        x: width / 2 - node.x * 1.4,
        y: height / 2 - node.y * 1.4,
      });
      handleSelectNode(nodeId);
      setSearchFocused(false);
    }
  };

  // Export SVG
  const exportSVG = () => {
    if (!canvasRef.current) return;
    const svgData = new XMLSerializer().serializeToString(canvasRef.current);
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `topology-${selectedRepo}-${viewType}.svg`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success('Topology SVG exported successfully');
  };

  // Export JSON
  const exportJSON = () => {
    if (!graphData) return;
    const jsonStr = JSON.stringify(graphData, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `topology-${selectedRepo}-${viewType}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success('Topology JSON exported successfully');
  };

  return (
    <div className="topology-container tab-content active">
      {/* Top Toolbar */}
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
                  onClick={() => focusOnNode(m.id)}
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

          <button className="btn btn-secondary btn-sm" onClick={exportSVG} title="Export as SVG">
            <i className="fa-solid fa-file-image"></i> SVG
          </button>
          <button className="btn btn-secondary btn-sm" onClick={exportJSON} title="Export as JSON">
            <i className="fa-solid fa-code"></i> JSON
          </button>
        </div>
      </div>

      {error && (
        <div className="vs-feedback-banner feedback-error">
          <i className="fa-solid fa-circle-exclamation"></i>
          <span>{error}</span>
        </div>
      )}

      {/* Main Interactive Canvas Wrapper */}
      <div
        className="topology-canvas-wrapper"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
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
        {visibleNodes.length > 0 && (
          <div className="topology-minimap">
            <svg viewBox="0 0 1000 640">
              {visibleEdges.map((e, idx) => {
                const p1 = nodePosMap.get(e.source);
                const p2 = nodePosMap.get(e.target);
                if (!p1 || !p2) return null;
                return (
                  <line
                    key={`mini-e-${idx}`}
                    x1={p1.x}
                    y1={p1.y}
                    x2={p2.x}
                    y2={p2.y}
                    stroke="rgba(255,255,255,0.15)"
                    strokeWidth="1"
                  />
                );
              })}
              {visibleNodes.map((n) => {
                const colors = NODE_COLORS[n.type] || NODE_COLORS.file;
                return (
                  <circle
                    key={`mini-n-${n.id}`}
                    cx={n.x}
                    cy={n.y}
                    r={4}
                    fill={colors.stroke}
                  />
                );
              })}
            </svg>
          </div>
        )}

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
              const isHighlighted = searchQuery && n.name.toLowerCase().includes(searchQuery.toLowerCase());

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
                    handleSelectNode(n.id);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      handleSelectNode(n.id);
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
                    {n.name.length > 22 ? n.name.slice(0, 20) + '…' : n.name}
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

      {/* Slide-over Inspector Drawer */}
      {isDrawerOpen && (
        <div className="topology-drawer">
          <div className="topology-drawer-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className={`topology-badge-type badge-${nodeDetails?.type || 'file'}`}>
                {nodeDetails?.type || 'NODE'}
              </span>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text)' }}>
                {nodeDetails?.name || 'Inspecting Node'}
              </h3>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setIsDrawerOpen(false)}
              aria-label="Close Inspector"
            >
              <i className="fa-solid fa-xmark"></i>
            </button>
          </div>

          <div className="topology-drawer-body">
            {loadingDetails && (
              <div className="topology-empty-state" style={{ height: '200px' }}>
                <i className="fa-solid fa-spinner fa-spin fa-lg"></i>
                <p>Loading node details...</p>
              </div>
            )}

            {!loadingDetails && nodeDetails && (
              <>
                {/* Location & Repo */}
                <div className="topology-drawer-section">
                  <span className="topology-drawer-section-title">Location & Repository</span>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text)' }}>
                    <div><strong>Repo:</strong> <span className="code">{nodeDetails.repo}</span></div>
                    {nodeDetails.filepath && (
                      <div style={{ marginTop: '4px' }}>
                        <strong>File:</strong> <span className="code">{nodeDetails.filepath}</span>
                      </div>
                    )}
                    {nodeDetails.start_line && (
                      <div style={{ marginTop: '4px' }}>
                        <strong>Lines:</strong> {nodeDetails.start_line} – {nodeDetails.end_line || nodeDetails.start_line}
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
                    {nodeDetails.permalink && (
                      <a
                        href={nodeDetails.permalink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-secondary btn-sm"
                      >
                        <i className="fa-solid fa-arrow-up-right-from-square"></i> Open in Git Provider
                      </a>
                    )}
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => {
                        setRootNode(nodeDetails.name);
                        setIsDrawerOpen(false);
                      }}
                      title="Focus subgraph from this root node"
                    >
                      <i className="fa-solid fa-crosshairs"></i> Set as Root Node
                    </button>
                  </div>
                </div>

                {/* Signature / Code Preview */}
                {(nodeDetails.signature || nodeDetails.code_preview) && (
                  <div className="topology-drawer-section">
                    <span className="topology-drawer-section-title">Source Code / Signature</span>
                    <pre className="topology-code-snippet">
                      {nodeDetails.code_preview || nodeDetails.signature}
                    </pre>
                  </div>
                )}

                {/* Incoming Connections */}
                <div className="topology-drawer-section">
                  <span className="topology-drawer-section-title">
                    Incoming Connections ({nodeDetails.incoming.length})
                  </span>
                  {nodeDetails.incoming.length === 0 ? (
                    <p className="text-muted" style={{ fontSize: '0.8rem' }}>No incoming connections detected.</p>
                  ) : (
                    <div className="topology-neighbor-list">
                      {nodeDetails.incoming.map((inc, i) => (
                        <div
                          key={`inc-${i}`}
                          className="topology-neighbor-item"
                          onClick={() => focusOnNode(inc.id)}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span className={`topology-badge-type badge-edge-${inc.edge_type.toLowerCase()}`}>
                              {inc.edge_type}
                            </span>
                            <span style={{ fontWeight: 500 }}>{inc.name}</span>
                          </div>
                          {inc.line_number && <span className="text-muted">L{inc.line_number}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Outgoing Connections */}
                <div className="topology-drawer-section">
                  <span className="topology-drawer-section-title">
                    Outgoing Connections ({nodeDetails.outgoing.length})
                  </span>
                  {nodeDetails.outgoing.length === 0 ? (
                    <p className="text-muted" style={{ fontSize: '0.8rem' }}>No outgoing connections detected.</p>
                  ) : (
                    <div className="topology-neighbor-list">
                      {nodeDetails.outgoing.map((out, i) => (
                        <div
                          key={`out-${i}`}
                          className="topology-neighbor-item"
                          onClick={() => focusOnNode(out.id)}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span className={`topology-badge-type badge-edge-${out.edge_type.toLowerCase()}`}>
                              {out.edge_type}
                            </span>
                            <span style={{ fontWeight: 500 }}>{out.name}</span>
                          </div>
                          {out.line_number && <span className="text-muted">L{out.line_number}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
