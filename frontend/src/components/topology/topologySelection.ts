import type {
  TopologyNode,
  TopologyEdge,
  TopologyGraphData,
  ArchitecturePreset,
  TopologyPhysicsConfig,
} from '../../types';
import type { SimNode } from './types';
import { calculateForceDirectedLayout } from './forceLayout';
import { DEFAULT_PHYSICS_CONFIG, ARCHITECTURE_PRESET_MAP } from './physicsPresets';
import { isCompiledBundlePath } from '../navigator/syntaxSemantics';

export function filterTopologyBundles(data: TopologyGraphData): TopologyGraphData {
  if (!data || !Array.isArray(data.nodes)) return data;
  const keptNodes = data.nodes.filter((n) => !isCompiledBundlePath(n.filepath || n.id));
  if (keptNodes.length === data.nodes.length) return data;
  const keptIds = new Set(keptNodes.map((n) => n.id));
  const keptEdges = (data.edges || []).filter(
    (e) => keptIds.has(e.source) && keptIds.has(e.target)
  );
  return {
    ...data,
    nodes: keptNodes,
    edges: keptEdges,
    stats: {
      node_count: keptNodes.length,
      edge_count: keptEdges.length,
    },
  };
}

export function findInitialFocalNode(
  nodes: TopologyNode[],
  edges: TopologyEdge[] = [],
  rootNodeQuery?: string
): TopologyNode | undefined {
  if (!nodes || nodes.length === 0) return undefined;

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

  const entrypointPatterns = [
    /(^|\/)(main|index|app|server|api|cli|program)\.(py|ts|tsx|js|jsx|cs|cbl|cob|go|rs)$/i,
    /(^|\/)__init__\.py$/i,
  ];
  for (const pat of entrypointPatterns) {
    const entry = candidateList.find((n) => pat.test(n.filepath || n.name || n.id));
    if (entry) return entry;
  }

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

export function exportTopologySvgFile(
  selectedRepo: string,
  activeViewType: string,
  onSuccess: (msg: string) => void,
  onError: (msg: string) => void
): void {
  const svgElem = document.querySelector('.neighborhood-svg');
  if (!svgElem) {
    onError('SVG export is available in Neighborhood View. Use PNG export in 2D Canvas.');
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
  onSuccess('Topology SVG exported successfully');
}

export function exportTopologyJsonFile(
  graphData: TopologyGraphData | null,
  selectedRepo: string,
  activeViewType: string,
  onSuccess: (msg: string) => void
): void {
  if (!graphData) return;
  const jsonStr = JSON.stringify(graphData, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `topology-${selectedRepo}-${activeViewType}.json`;
  link.click();
  URL.revokeObjectURL(url);
  onSuccess('Topology JSON exported successfully');
}
