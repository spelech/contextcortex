import React, { useState, useEffect, useMemo, useCallback } from 'react';
import type {
  TopologyNode,
  TopologyEdge,
  TopologyGraphData,
  NodeDetails,
  Repo,
  TopologyViewMode,
  FocalBreadcrumb,
  ArchitecturePreset,
  TopologyPhysicsConfig,
} from './types';
import { useToast } from './ToastContext';
import type { SimNode } from './components/topology/types';
import { TopologyControls } from './components/topology/TopologyControls';
import { NeighborhoodView } from './components/topology/NeighborhoodView';
import { TopologyCanvas2D, calculateForceDirectedLayout } from './components/topology/TopologyCanvas2D';
import { TopologyInspector } from './components/topology/TopologyInspector';
import { TopologyPhysicsControls } from './components/topology/TopologyPhysicsControls';
import {
  DEFAULT_PHYSICS_CONFIG,
  PHYSICS_PRESETS,
  ARCHITECTURE_PRESET_MAP,
  resolveBackendViewType,
  getStoredPhysicsConfig,
  setStoredPhysicsConfig,
} from './components/topology/physicsPresets';

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
  iterationsOrConfig: number | TopologyPhysicsConfig = 60
): SimNode[] {
  const config =
    typeof iterationsOrConfig === 'number'
      ? { ...DEFAULT_PHYSICS_CONFIG, iterations: iterationsOrConfig }
      : iterationsOrConfig;
  return calculateForceDirectedLayout(nodes, edges, undefined, undefined, config);
}

export function findMatchingPreset(filters: Record<string, boolean>): ArchitecturePreset | null {
  for (const [key, presetFilters] of Object.entries(ARCHITECTURE_PRESET_MAP) as [
    ArchitecturePreset,
    Record<string, boolean>
  ][]) {
    const allKeys = new Set([...Object.keys(filters), ...Object.keys(presetFilters)]);
    let match = true;
    for (const k of allKeys) {
      if (Boolean(filters[k]) !== Boolean(presetFilters[k])) {
        match = false;
        break;
      }
    }
    if (match) return key;
  }
  return null;
}

export default function TopologyExplorer() {
  const toast = useToast();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('__all__');
  const [viewMode, setViewMode] = useState<TopologyViewMode>('neighborhood');
  const [focalNodeId, setFocalNodeId] = useState<string>('');
  const [breadcrumbs, setBreadcrumbs] = useState<FocalBreadcrumb[]>([]);
  const [hopRadius, setHopRadius] = useState<1 | 2>(1);

  const [depth, setDepth] = useState<number>(2);
  const [nodeLimit, setNodeLimit] = useState<number>(150);
  const [hideOrphans, setHideOrphans] = useState<boolean>(false);
  const [rootNode, setRootNode] = useState<string>('');

  // Architectural Preset and Filtering toggles
  const [activePreset, setActivePreset] = useState<ArchitecturePreset | null>('architecture');
  const [typeFilters, setTypeFilters] = useState<Record<string, boolean>>({
    ...ARCHITECTURE_PRESET_MAP.architecture,
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

  // Force-Directed Physics State
  const [physicsConfig, setPhysicsConfig] = useState<TopologyPhysicsConfig>(() => getStoredPhysicsConfig());
  const [isPhysicsOpen, setIsPhysicsOpen] = useState<boolean>(false);
  const [relaxTrigger, setRelaxTrigger] = useState<number>(0);

  // Dynamic backend view_type based on active filters
  const activeViewType = useMemo(() => {
    return resolveBackendViewType(typeFilters);
  }, [typeFilters]);

  // Compute live node counts per type
  const nodeCounts = useMemo(() => {
    const counts = { file: 0, class: 0, function: 0, route: 0 };
    if (!graphData?.nodes) return counts;
    for (const n of graphData.nodes) {
      if (n.type in counts) {
        counts[n.type as keyof typeof counts]++;
      }
    }
    return counts;
  }, [graphData]);

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

  // Fetch graph data using dynamic activeViewType
  const loadTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = `/admin/api/graph/topology?repo=${encodeURIComponent(selectedRepo)}&view_type=${activeViewType}&depth=${depth}&limit=${nodeLimit}`;
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
      const computedNodes = calculateForceDirectedLayout(
        data.nodes || [],
        data.edges || [],
        undefined,
        undefined,
        physicsConfig
      );
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
  }, [selectedRepo, activeViewType, depth, nodeLimit, rootNode, physicsConfig, toast]);

  useEffect(() => {
    loadTopology();
  }, [loadTopology]);

  // Handle architectural preset selection
  const handleSelectPreset = useCallback((preset: ArchitecturePreset) => {
    setActivePreset(preset);
    setTypeFilters({ ...ARCHITECTURE_PRESET_MAP[preset] });
  }, []);

  // Handle manual filter chip toggle, updating activePreset if needed
  const handleSetTypeFilters = useCallback<React.Dispatch<React.SetStateAction<Record<string, boolean>>>>(
    (action) => {
      setTypeFilters((prev) => {
        const next = typeof action === 'function' ? action(prev) : action;
        setActivePreset(findMatchingPreset(next));
        return next;
      });
    },
    []
  );

  // Physics handlers
  const handleChangePhysicsConfig = useCallback((newConfig: TopologyPhysicsConfig) => {
    setPhysicsConfig(newConfig);
    setStoredPhysicsConfig(newConfig);
  }, []);

  const handleSelectPhysicsPreset = useCallback(
    (presetKey: string) => {
      const preset = PHYSICS_PRESETS[presetKey as keyof typeof PHYSICS_PRESETS];
      if (preset) {
        setPhysicsConfig(preset);
        setStoredPhysicsConfig(preset);
        if (graphData?.nodes && graphData.nodes.length > 0) {
          const reRelaxed = calculateForceDirectedLayout(
            graphData.nodes,
            graphData.edges || [],
            undefined,
            undefined,
            preset
          );
          setSimNodes(reRelaxed);
          setRelaxTrigger((prev) => prev + 1);
        }
      }
    },
    [graphData]
  );

  const handleResetPhysicsDefaults = useCallback(() => {
    setPhysicsConfig(DEFAULT_PHYSICS_CONFIG);
    setStoredPhysicsConfig(DEFAULT_PHYSICS_CONFIG);
    if (graphData?.nodes && graphData.nodes.length > 0) {
      const reRelaxed = calculateForceDirectedLayout(
        graphData.nodes,
        graphData.edges || [],
        undefined,
        undefined,
        DEFAULT_PHYSICS_CONFIG
      );
      setSimNodes(reRelaxed);
      setRelaxTrigger((prev) => prev + 1);
    }
  }, [graphData]);

  const handleReRelax = useCallback(() => {
    if (graphData?.nodes && graphData.nodes.length > 0) {
      const reRelaxed = calculateForceDirectedLayout(
        simNodes.length > 0 ? simNodes : graphData.nodes,
        graphData.edges || [],
        undefined,
        undefined,
        physicsConfig
      );
      setSimNodes(reRelaxed);
      setRelaxTrigger((prev) => prev + 1);
      toast.success('Layout re-relaxed');
    }
  }, [graphData, simNodes, physicsConfig, toast]);

  const handleTogglePhysics = useCallback(() => {
    setIsPhysicsOpen((prev) => !prev);
  }, []);

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
  const handleSelectFocalNode = useCallback(
    (nodeId: string) => {
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
    },
    [graphData, selectedRepo]
  );

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
    return graphData.nodes
      .filter(
        (n) =>
          n.name.toLowerCase().includes(q) ||
          (n.filepath && n.filepath.toLowerCase().includes(q)) ||
          (n.path_pattern && n.path_pattern.toLowerCase().includes(q))
      )
      .slice(0, 10);
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
    link.download = `topology-${selectedRepo}-${activeViewType}.svg`;
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
    link.download = `topology-${selectedRepo}-${activeViewType}.json`;
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
        setTypeFilters={handleSetTypeFilters}
        activePreset={activePreset || undefined}
        onSelectPreset={handleSelectPreset}
        nodeCounts={nodeCounts}
        onTogglePhysics={handleTogglePhysics}
        isPhysicsOpen={isPhysicsOpen}
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

      {!loading &&
        (viewMode === 'neighborhood' ? (
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
          <div style={{ position: 'relative', width: '100%' }}>
            <TopologyCanvas2D
              nodes={visibleNodes}
              edges={visibleEdges}
              selectedNodeId={selectedNodeId}
              searchQuery={searchQuery}
              onSelectNode={handleSelectNode}
              autoFitOnMount={true}
              physicsConfig={physicsConfig}
              relaxTrigger={relaxTrigger}
            />
            {isPhysicsOpen && (
              <TopologyPhysicsControls
                config={physicsConfig}
                onChangeConfig={handleChangePhysicsConfig}
                onSelectPreset={handleSelectPhysicsPreset}
                onReRelax={handleReRelax}
                onResetDefaults={handleResetPhysicsDefaults}
                onClose={() => setIsPhysicsOpen(false)}
                isOpen={isPhysicsOpen}
              />
            )}
          </div>
        ))}

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
