import { useState, useEffect, useMemo, useCallback } from 'react';
import type {
  TopologyNode,
  TopologyEdge,
  TopologyGraphData,
  NodeDetails,
  Repo,
  TopologyViewMode,
  FocalBreadcrumb,
} from './types';
import { useToast } from './ToastContext';
import type { SimNode } from './components/topology/types';
import { TopologyControls } from './components/topology/TopologyControls';
import { NeighborhoodView } from './components/topology/NeighborhoodView';
import { TopologyCanvas2D } from './components/topology/TopologyCanvas2D';
import { TopologyInspector } from './components/topology/TopologyInspector';

export function findInitialFocalNode(
  nodes: TopologyNode[],
  edges: TopologyEdge[] = [],
  rootNodeQuery?: string
): TopologyNode | undefined {
  if (!nodes || nodes.length === 0) return undefined;

  // 1. If explicit rootNode is queried
  if (rootNodeQuery && rootNodeQuery.trim()) {
    const q = rootNodeQuery.trim().toLowerCase();
    const found = nodes.find(
      (n) =>
        n.id.toLowerCase() === q ||
        n.name.toLowerCase() === q ||
        (n.filepath && n.filepath.toLowerCase().endsWith(q))
    );
    if (found) return found;
  }

  // Build degree count map (incoming + outgoing edges)
  const degreeMap = new Map<string, number>();
  edges.forEach((e) => {
    degreeMap.set(e.source, (degreeMap.get(e.source) || 0) + 1);
    degreeMap.set(e.target, (degreeMap.get(e.target) || 0) + 1);
  });

  const isTestNode = (n: TopologyNode) => {
    const name = (n.name || '').toLowerCase();
    const path = (n.filepath || n.id || '').toLowerCase();
    return (
      path.includes('/tests/') ||
      path.includes('/test/') ||
      path.startsWith('tests/') ||
      path.startsWith('test/') ||
      path.includes('test_') ||
      path.includes('.test.') ||
      path.includes('.spec.') ||
      name.startsWith('test_')
    );
  };

  const nonTestNodes = nodes.filter((n) => !isTestNode(n));
  const candidateList = nonTestNodes.length > 0 ? nonTestNodes : nodes;

  // 2. Look for primary entry points first
  const entrypointPatterns = [
    /(^|\/)(main|index|app|server|api|cli)\.(py|ts|tsx|js|jsx|go|rs)$/i,
    /(^|\/)__init__\.py$/i,
  ];
  for (const pat of entrypointPatterns) {
    const entry = candidateList.find((n) => pat.test(n.filepath || n.name || n.id));
    if (entry) return entry;
  }

  // 3. Pick candidate with highest degree of connectivity
  const sortedByDegree = [...candidateList].sort((a, b) => {
    const degA = degreeMap.get(a.id) || 0;
    const degB = degreeMap.get(b.id) || 0;
    return degB - degA;
  });

  return sortedByDegree[0] || nodes[0];
}

export function computeInitialLayout(
  nodes: TopologyNode[],
  edges: TopologyEdge[] | undefined,
  iterations: number = 60
): SimNode[] {
  const nodeCount = nodes.length;
  // Dynamically size layout area so nodes have generous space to breathe
  const width = Math.max(1600, Math.sqrt(nodeCount || 1) * 180);
  const height = Math.max(1000, Math.sqrt(nodeCount || 1) * 120);
  const radius = Math.max(420, Math.min(width, height) * 0.42);

  const simNodes: SimNode[] = nodes.map((node: TopologyNode, idx: number) => {
    const angle = (idx / (nodeCount || 1)) * 2 * Math.PI;
    const dist = radius * (0.5 + 0.5 * Math.random());
    const r = node.type === 'route' ? 24 : node.type === 'class' ? 22 : node.type === 'file' ? 20 : 18;
    return {
      ...node,
      x: width / 2 + dist * Math.cos(angle) + (Math.random() - 0.5) * 60,
      y: height / 2 + dist * Math.sin(angle) + (Math.random() - 0.5) * 60,
      vx: 0,
      vy: 0,
      radius: r,
    };
  });

  const nodeIndex = new Map<string, number>();
  simNodes.forEach((n, i) => nodeIndex.set(n.id, i));

  // Strong repulsion force to prevent clustering
  const kRepulse = Math.max(10000, Math.min(45000, 120000 / Math.sqrt(simNodes.length || 1)));
  const kSpring = 0.025;
  const springLength = 200;
  const centerGravity = 0.002;
  const damping = 0.85;
  const boundK = 0.02;

  // Cap active edges for layout solving to 1200 to bound computational cost
  const activeEdges = edges && edges.length > 1200 ? edges.slice(0, 1200) : edges || [];

  for (let it = 0; it < iterations; it++) {
    // 1. Repulsion
    for (let i = 0; i < simNodes.length; i++) {
      for (let j = i + 1; j < simNodes.length; j++) {
        let dx = simNodes[j].x - simNodes[i].x;
        let dy = simNodes[j].y - simNodes[i].y;
        if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) {
          dx = (Math.random() - 0.5) * 4;
          dy = (Math.random() - 0.5) * 4;
        }
        const distSq = Math.max(64, dx * dx + dy * dy);
        const dist = Math.sqrt(distSq) || 1;
        const force = kRepulse / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        simNodes[i].vx -= fx;
        simNodes[i].vy -= fy;
        simNodes[j].vx += fx;
        simNodes[j].vy += fy;
      }
    }

    // 2. Spring attraction along edges
    for (const edge of activeEdges) {
      const i1 = nodeIndex.get(edge.source);
      const i2 = nodeIndex.get(edge.target);
      if (i1 === undefined || i2 === undefined) continue;

      const n1 = simNodes[i1];
      const n2 = simNodes[i2];
      const dx = n2.x - n1.x;
      const dy = n2.y - n1.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const displacement = dist - springLength;
      const force = displacement * kSpring;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;

      n1.vx += fx;
      n1.vy += fy;
      n2.vx -= fx;
      n2.vy -= fy;
    }

    // 3. Gravity, soft bounds & velocity integration
    for (const node of simNodes) {
      node.vx += (width / 2 - node.x) * centerGravity;
      node.vy += (height / 2 - node.y) * centerGravity;

      if (node.x < 100) node.vx += (100 - node.x) * boundK;
      else if (node.x > width - 100) node.vx += (width - 100 - node.x) * boundK;

      if (node.y < 100) node.vy += (100 - node.y) * boundK;
      else if (node.y > height - 100) node.vy += (height - 100 - node.y) * boundK;

      node.vx *= damping;
      node.vy *= damping;
      node.x += node.vx;
      node.y += node.vy;

      if (!isFinite(node.x)) node.x = width / 2;
      if (!isFinite(node.y)) node.y = height / 2;
    }
  }

  return simNodes;
}

export default function TopologyExplorer() {
  const toast = useToast();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('__all__');
  const [viewMode, setViewMode] = useState<TopologyViewMode>('neighborhood');
  const [focalNodeId, setFocalNodeId] = useState<string>('');
  const [breadcrumbs, setBreadcrumbs] = useState<FocalBreadcrumb[]>([]);
  const [hopRadius, setHopRadius] = useState<1 | 2>(1);

  const [viewType, setViewType] = useState<'files' | 'symbols' | 'routes' | 'full'>('files');
  const [depth, setDepth] = useState<number>(2);
  const [nodeLimit, setNodeLimit] = useState<number>(150);
  const [hideOrphans, setHideOrphans] = useState<boolean>(false);
  const [rootNode, setRootNode] = useState<string>('');

  // Filtering toggles
  const [typeFilters, setTypeFilters] = useState<Record<string, boolean>>({
    file: true,
    class: true,
    function: true,
    route: true,
    module: true,
  });

  const [edgeFilters] = useState<Record<string, boolean>>({
    IMPORTS: true,
    CALLS: true,
    DEFINES: true,
    HANDLES: true,
    ROUTES_TO: true,
    DOC_LINKS_TO: true,
  });

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchFocused, setSearchFocused] = useState<boolean>(false);

  // Graph data & simulation for Canvas 2D
  const [graphData, setGraphData] = useState<TopologyGraphData | null>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Inspector Drawer
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetails, setNodeDetails] = useState<NodeDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState<boolean>(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

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
      let url = `/admin/api/graph/topology?repo=${encodeURIComponent(selectedRepo)}&view_type=${viewType}&depth=${depth}&limit=${nodeLimit}`;
      if (rootNode.trim()) {
        url += `&root_node=${encodeURIComponent(rootNode.trim())}`;
      }
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to load topology');
      }
      setGraphData(data);

      // Compute relaxed force layout synchronously in memory for Canvas 2D
      const computedNodes = computeInitialLayout(data.nodes || [], data.edges || [], 50);
      setSimNodes(computedNodes);

      // Initialize focal node and breadcrumbs using smart selection (entrypoint / highest degree)
      if (data.nodes && data.nodes.length > 0) {
        const focal = findInitialFocalNode(data.nodes, data.edges || [], rootNode) || data.nodes[0];
        setFocalNodeId(focal.id);
        setBreadcrumbs([
          {
            id: focal.id,
            name: focal.name,
            type: focal.type,
            repo: focal.repo || selectedRepo,
          },
        ]);
      } else {
        setFocalNodeId('');
        setBreadcrumbs([]);
      }
    } catch (err: any) {
      setError(err.message);
      toast.error('Topology loading error: ' + err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedRepo, viewType, depth, nodeLimit, rootNode, toast]);

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

  // Focal node selection & breadcrumbs updates
  const handleSelectFocalNode = useCallback((nodeId: string) => {
    const targetNode = graphData?.nodes?.find((n) => n.id === nodeId);
    if (targetNode) {
      setFocalNodeId(nodeId);
      setBreadcrumbs((prev) => {
        if (prev.length > 0 && prev[prev.length - 1].id === nodeId) {
          return prev;
        }
        return [
          ...prev,
          {
            id: targetNode.id,
            name: targetNode.name,
            type: targetNode.type,
            repo: targetNode.repo || selectedRepo,
          },
        ];
      });
    }
  }, [graphData, selectedRepo]);

  // Navigate back to an existing breadcrumb
  const handleNavigateBreadcrumb = useCallback((index: number) => {
    setBreadcrumbs((prev) => {
      if (index < 0 || index >= prev.length) return prev;
      const target = prev[index];
      setFocalNodeId(target.id);
      return prev.slice(0, index + 1);
    });
  }, []);

  // Filtered nodes and edges for 2D Canvas rendering
  const visibleNodes = useMemo(() => {
    let filtered = simNodes.filter((n) => typeFilters[n.type] ?? true);
    if (hideOrphans && graphData?.edges) {
      const connectedNodeIds = new Set<string>();
      graphData.edges.forEach((e) => {
        if (edgeFilters[e.type] ?? true) {
          connectedNodeIds.add(e.source);
          connectedNodeIds.add(e.target);
        }
      });
      filtered = filtered.filter((n) => connectedNodeIds.has(n.id));
    }
    return filtered;
  }, [simNodes, typeFilters, hideOrphans, graphData, edgeFilters]);

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

  // Focus on a specific node from search or inspector
  const focusOnNode = (nodeId: string) => {
    const targetNode = graphData?.nodes?.find((n) => n.id === nodeId);
    if (targetNode) {
      handleSelectFocalNode(nodeId);
      handleSelectNode(nodeId);
      setSearchFocused(false);
    }
  };

  // Export SVG
  const exportSVG = () => {
    const svgElem = document.querySelector('.neighborhood-svg');
    if (!svgElem) {
      toast.error('SVG export is available in Neighborhood View. Use PNG export in 2D Canvas.');
      return;
    }
    const svgData = new XMLSerializer().serializeToString(svgElem);
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
        viewMode={viewMode}
        setViewMode={setViewMode}
        hopRadius={hopRadius}
        setHopRadius={setHopRadius}
        viewType={viewType}
        setViewType={setViewType}
        depth={depth}
        setDepth={setDepth}
        nodeLimit={nodeLimit}
        setNodeLimit={setNodeLimit}
        hideOrphans={hideOrphans}
        setHideOrphans={setHideOrphans}
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

      {loading && (
        <div className="topology-empty-state" style={{ height: '300px' }}>
          <i className="fa-solid fa-spinner fa-spin fa-2xl"></i>
          <p>Generating Topology Graph...</p>
        </div>
      )}

      {!loading && (
        viewMode === 'neighborhood' ? (
          <NeighborhoodView
            graphData={graphData}
            focalNodeId={focalNodeId}
            onSelectFocalNode={handleSelectFocalNode}
            onSelectNodeDetails={handleSelectNode}
            breadcrumbs={breadcrumbs}
            onNavigateBreadcrumb={handleNavigateBreadcrumb}
            hopRadius={hopRadius}
            setHopRadius={setHopRadius}
            typeFilters={typeFilters}
          />
        ) : (
          <TopologyCanvas2D
            nodes={visibleNodes}
            edges={visibleEdges}
            selectedNodeId={selectedNodeId}
            searchQuery={searchQuery}
            onSelectNode={handleSelectNode}
            autoFitOnMount={true}
          />
        )
      )}

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
