import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import type { MouseEvent, WheelEvent } from 'react';
import type { TopologyNode, TopologyGraphData, NodeDetails, Repo } from './types';
import { useToast } from './ToastContext';
import type { SimNode } from './components/topology/types';
import { TopologyControls } from './components/topology/TopologyControls';
import { TopologyCanvas } from './components/topology/TopologyCanvas';
import { TopologyInspector } from './components/topology/TopologyInspector';

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

        node.vx += (width / 2 - node.x) * centerGravity;
        node.vy += (height / 2 - node.y) * centerGravity;
        node.vx *= damping;
        node.vy *= damping;
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
      <TopologyControls
        repos={repos}
        selectedRepo={selectedRepo}
        setSelectedRepo={setSelectedRepo}
        viewType={viewType}
        setViewType={setViewType}
        depth={depth}
        setDepth={setDepth}
        rootNode={rootNode}
        setRootNode={setRootNode}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        searchFocused={searchFocused}
        setSearchFocused={setSearchFocused}
        searchMatches={searchMatches}
        onFocusNode={focusOnNode}
        typeFilters={typeFilters}
        setTypeFilters={setTypeFilters}
        onExportSVG={exportSVG}
        onExportJSON={exportJSON}
      />

      {error && (
        <div className="vs-feedback-banner feedback-error">
          <i className="fa-solid fa-circle-exclamation"></i>
          <span>{error}</span>
        </div>
      )}

      <TopologyCanvas
        canvasRef={canvasRef}
        visibleNodes={visibleNodes}
        visibleEdges={visibleEdges}
        nodePosMap={nodePosMap}
        pan={pan}
        zoom={zoom}
        setZoom={setZoom}
        setPan={setPan}
        isSimPaused={isSimPaused}
        setIsSimPaused={setIsSimPaused}
        loading={loading}
        edgeFilters={edgeFilters}
        setEdgeFilters={setEdgeFilters}
        selectedNodeId={selectedNodeId}
        searchQuery={searchQuery}
        onSelectNode={handleSelectNode}
        setDraggedNodeId={setDraggedNodeId}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
      />

      <TopologyInspector
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        loadingDetails={loadingDetails}
        nodeDetails={nodeDetails}
        onFocusNode={focusOnNode}
        onSetRootNode={setRootNode}
      />
    </div>
  );
}
