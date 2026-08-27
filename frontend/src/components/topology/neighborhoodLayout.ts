import type { TopologyNode, TopologyEdge, NeighborhoodSubGraph, RadialLayoutResult } from '../../types';

/**
 * Extracts a focused 1-hop or 2-hop neighborhood subgraph centered on a focal node.
 *
 * @param nodes - All available nodes in the topology graph.
 * @param edges - All available edges in the topology graph.
 * @param focalNodeId - The ID of the target focal node.
 * @param hopDepth - Depth of neighborhood extraction (1 = direct neighbors, 2 = includes secondary neighbors).
 * @returns Isolated subgraph containing focal node, categorized incoming/outgoing neighbors, secondary nodes, and edges.
 */
export function buildNeighborhoodGraph(
  nodes: TopologyNode[] = [],
  edges: TopologyEdge[] = [],
  focalNodeId: string,
  hopDepth: number = 1
): NeighborhoodSubGraph {
  const safeNodes = Array.isArray(nodes) ? nodes : [];
  const safeEdges = Array.isArray(edges) ? edges : [];

  const nodeMap = new Map<string, TopologyNode>(safeNodes.map((n) => [n.id, n]));

  // Find focal node or fallback
  let focalNode = nodeMap.get(focalNodeId);
  if (!focalNode && safeNodes.length > 0) {
    focalNode = safeNodes[0];
  }
  if (!focalNode) {
    focalNode = {
      id: focalNodeId || 'unknown',
      name: focalNodeId || 'Unknown',
      type: 'file',
      repo: '',
    };
  }

  const focalId = focalNode.id;

  // 1-hop categorization
  const incoming: NeighborhoodSubGraph['incoming'] = [];
  const outgoing: NeighborhoodSubGraph['outgoing'] = [];
  const hop1NodeIds = new Set<string>();

  for (const edge of safeEdges) {
    if (edge.target === focalId && edge.source !== focalId) {
      const sourceNode = nodeMap.get(edge.source);
      if (sourceNode) {
        incoming.push({
          node: sourceNode,
          edgeType: edge.type,
          label: edge.label,
        });
        hop1NodeIds.add(edge.source);
      }
    } else if (edge.source === focalId && edge.target !== focalId) {
      const targetNode = nodeMap.get(edge.target);
      if (targetNode) {
        outgoing.push({
          node: targetNode,
          edgeType: edge.type,
          label: edge.label,
        });
        hop1NodeIds.add(edge.target);
      }
    }
  }

  // 2-hop secondary nodes
  const secondaryNodeIds = new Set<string>();
  if (hopDepth >= 2) {
    for (const edge of safeEdges) {
      if (
        hop1NodeIds.has(edge.source) &&
        edge.target !== focalId &&
        !hop1NodeIds.has(edge.target)
      ) {
        if (nodeMap.has(edge.target)) {
          secondaryNodeIds.add(edge.target);
        }
      }
      if (
        hop1NodeIds.has(edge.target) &&
        edge.source !== focalId &&
        !hop1NodeIds.has(edge.source)
      ) {
        if (nodeMap.has(edge.source)) {
          secondaryNodeIds.add(edge.source);
        }
      }
    }
  }

  const secondaryNodes: TopologyNode[] = Array.from(secondaryNodeIds)
    .map((id) => nodeMap.get(id)!)
    .filter(Boolean);

  // Subgraph edges
  const includedNodeIds = new Set<string>([
    focalId,
    ...hop1NodeIds,
    ...(hopDepth >= 2 ? secondaryNodeIds : []),
  ]);

  const subEdges = safeEdges.filter(
    (e) => includedNodeIds.has(e.source) && includedNodeIds.has(e.target)
  );

  return {
    focalNode,
    incoming,
    outgoing,
    secondaryNodes,
    edges: subEdges,
  };
}

/**
 * Calculates radial 2D coordinates for the focal node and all neighbors in the subgraph.
 *
 * @param subGraph - The extracted neighborhood subgraph.
 * @param center - The (x, y) center position for the focal node.
 * @param innerRadius - Radius for 1-hop neighbor ring.
 * @param outerRadius - Radius for 2-hop secondary neighbor ring.
 * @returns Focal position and positioned neighbors with angle and ring information.
 */
export function calculateRadialPositions(
  subGraph: NeighborhoodSubGraph,
  center: { x: number; y: number } = { x: 500, y: 320 },
  innerRadius: number = 180,
  outerRadius: number = 300
): RadialLayoutResult {
  const cx = Number.isFinite(center?.x) ? center.x : 500;
  const cy = Number.isFinite(center?.y) ? center.y : 320;
  const innerR = Number.isFinite(innerRadius) ? innerRadius : 180;
  const outerR = Number.isFinite(outerRadius) ? outerRadius : 300;

  const focal = { x: cx, y: cy };
  const neighbors: RadialLayoutResult['neighbors'] = [];

  const incoming = subGraph?.incoming || [];
  const outgoing = subGraph?.outgoing || [];
  const secondary = subGraph?.secondaryNodes || [];

  // Ring 1 - Incoming in left arc [2π/3, 4π/3] (centered at π)
  if (incoming.length === 1) {
    const angle = Math.PI;
    const x = cx + innerR * Math.cos(angle);
    const y = cy + innerR * Math.sin(angle);
    neighbors.push({
      node: incoming[0].node,
      x: Number.isFinite(x) ? x : cx - innerR,
      y: Number.isFinite(y) ? y : cy,
      angle,
      ring: 1,
      direction: 'incoming',
    });
  } else if (incoming.length > 1) {
    const startAngle = (2 * Math.PI) / 3;
    const endAngle = (4 * Math.PI) / 3;
    const step = (endAngle - startAngle) / (incoming.length - 1);
    incoming.forEach((item, index) => {
      const angle = startAngle + index * step;
      const x = cx + innerR * Math.cos(angle);
      const y = cy + innerR * Math.sin(angle);
      neighbors.push({
        node: item.node,
        x: Number.isFinite(x) ? x : cx - innerR,
        y: Number.isFinite(y) ? y : cy,
        angle,
        ring: 1,
        direction: 'incoming',
      });
    });
  }

  // Ring 1 - Outgoing in right arc [-π/3, π/3] (centered at 0)
  if (outgoing.length === 1) {
    const angle = 0;
    const x = cx + innerR * Math.cos(angle);
    const y = cy + innerR * Math.sin(angle);
    neighbors.push({
      node: outgoing[0].node,
      x: Number.isFinite(x) ? x : cx + innerR,
      y: Number.isFinite(y) ? y : cy,
      angle,
      ring: 1,
      direction: 'outgoing',
    });
  } else if (outgoing.length > 1) {
    const startAngle = -Math.PI / 3;
    const endAngle = Math.PI / 3;
    const step = (endAngle - startAngle) / (outgoing.length - 1);
    outgoing.forEach((item, index) => {
      const angle = startAngle + index * step;
      const x = cx + innerR * Math.cos(angle);
      const y = cy + innerR * Math.sin(angle);
      neighbors.push({
        node: item.node,
        x: Number.isFinite(x) ? x : cx + innerR,
        y: Number.isFinite(y) ? y : cy,
        angle,
        ring: 1,
        direction: 'outgoing',
      });
    });
  }

  // Ring 2 - Secondary 2-hop nodes on outer ring
  if (secondary.length === 1) {
    const angle = -Math.PI / 2;
    const x = cx + outerR * Math.cos(angle);
    const y = cy + outerR * Math.sin(angle);
    neighbors.push({
      node: secondary[0],
      x: Number.isFinite(x) ? x : cx,
      y: Number.isFinite(y) ? y : cy - outerR,
      angle,
      ring: 2,
      direction: 'secondary',
    });
  } else if (secondary.length > 1) {
    const step = (2 * Math.PI) / secondary.length;
    secondary.forEach((node, index) => {
      const angle = -Math.PI / 2 + index * step;
      const x = cx + outerR * Math.cos(angle);
      const y = cy + outerR * Math.sin(angle);
      neighbors.push({
        node,
        x: Number.isFinite(x) ? x : cx,
        y: Number.isFinite(y) ? y : cy,
        angle,
        ring: 2,
        direction: 'secondary',
      });
    });
  }

  return {
    focal,
    neighbors,
  };
}
