import type { SimNode, TopologyPhysicsConfig } from './types';
import type { TopologyEdge, TopologyNode } from '../../types';
import { DEFAULT_PHYSICS_CONFIG } from './physicsPresets';

/**
 * Calculates a fully relaxed force-directed layout for the supplied nodes and edges.
 * Uses configurable repulsion, spring stiffness, center gravity, collision radius, and iterations.
 */
export function calculateForceDirectedLayout(
  nodes: (TopologyNode | SimNode)[],
  edges: TopologyEdge[] = [],
  width?: number,
  height?: number,
  physicsConfig?: TopologyPhysicsConfig
): SimNode[] {
  if (!nodes || nodes.length === 0) return [];

  const cfg = {
    kRepulse: physicsConfig?.kRepulse ?? DEFAULT_PHYSICS_CONFIG.kRepulse,
    springLength: physicsConfig?.springLength ?? DEFAULT_PHYSICS_CONFIG.springLength,
    kSpring: physicsConfig?.kSpring ?? DEFAULT_PHYSICS_CONFIG.kSpring,
    centerGravity: physicsConfig?.centerGravity ?? DEFAULT_PHYSICS_CONFIG.centerGravity,
    collisionRadius: physicsConfig?.collisionRadius ?? DEFAULT_PHYSICS_CONFIG.collisionRadius,
    iterations: physicsConfig?.iterations ?? DEFAULT_PHYSICS_CONFIG.iterations,
  };

  const kRepulse = Number.isFinite(cfg.kRepulse) && cfg.kRepulse > 0 ? cfg.kRepulse : DEFAULT_PHYSICS_CONFIG.kRepulse;
  const springLength = Number.isFinite(cfg.springLength) && cfg.springLength > 0 ? cfg.springLength : DEFAULT_PHYSICS_CONFIG.springLength;
  const kSpring = Number.isFinite(cfg.kSpring) && cfg.kSpring > 0 ? cfg.kSpring : DEFAULT_PHYSICS_CONFIG.kSpring;
  const centerGravity = Number.isFinite(cfg.centerGravity) && cfg.centerGravity >= 0 ? cfg.centerGravity : DEFAULT_PHYSICS_CONFIG.centerGravity;
  const collisionRadius = Number.isFinite(cfg.collisionRadius) && cfg.collisionRadius > 0 ? cfg.collisionRadius : DEFAULT_PHYSICS_CONFIG.collisionRadius;
  const iterations = Number.isFinite(cfg.iterations) && cfg.iterations > 0 ? Math.round(cfg.iterations) : DEFAULT_PHYSICS_CONFIG.iterations;

  const nodeCount = nodes.length;
  const defaultW = Math.max(1600, Math.sqrt(nodeCount || 1) * 180);
  const defaultH = Math.max(1000, Math.sqrt(nodeCount || 1) * 120);
  const layoutW = typeof width === 'number' && Number.isFinite(width) && width > 0 ? width : defaultW;
  const layoutH = typeof height === 'number' && Number.isFinite(height) && height > 0 ? height : defaultH;
  const radius = Math.max(420, Math.min(layoutW, layoutH) * 0.42);

  const simNodes: SimNode[] = nodes.map((node, idx) => {
    const hasExistingPos = 'x' in node && Number.isFinite(node.x) && 'y' in node && Number.isFinite(node.y);
    const angle = (idx / (nodeCount || 1)) * 2 * Math.PI;
    const dist = radius * (0.5 + 0.5 * Math.random());
    const r =
      collisionRadius > 0
        ? node.type === 'route'
          ? collisionRadius * 1.2
          : node.type === 'class'
          ? collisionRadius * 1.1
          : node.type === 'file'
          ? collisionRadius
          : collisionRadius * 0.9
        : node.type === 'route'
        ? 24
        : node.type === 'class'
        ? 22
        : node.type === 'file'
        ? 20
        : 18;

    return {
      ...node,
      x: hasExistingPos ? (node as SimNode).x : layoutW / 2 + dist * Math.cos(angle) + (Math.random() - 0.5) * 60,
      y: hasExistingPos ? (node as SimNode).y : layoutH / 2 + dist * Math.sin(angle) + (Math.random() - 0.5) * 60,
      vx: 0,
      vy: 0,
      radius: r,
    };
  });

  const nodeIndex = new Map<string, number>();
  simNodes.forEach((n, i) => nodeIndex.set(n.id, i));

  const damping = 0.85;
  const boundK = 0.02;
  const activeEdges = edges && edges.length > 1200 ? edges.slice(0, 1200) : edges || [];

  for (let it = 0; it < iterations; it++) {
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

    for (const node of simNodes) {
      node.vx += (layoutW / 2 - node.x) * centerGravity;
      node.vy += (layoutH / 2 - node.y) * centerGravity;

      if (node.x < 100) node.vx += (100 - node.x) * boundK;
      else if (node.x > layoutW - 100) node.vx += (layoutW - 100 - node.x) * boundK;

      if (node.y < 100) node.vx += (100 - node.y) * boundK;
      else if (node.y > layoutH - 100) node.vy += (layoutH - 100 - node.y) * boundK;

      node.vx *= damping;
      node.vy *= damping;
      node.x += node.vx;
      node.y += node.vy;

      if (!Number.isFinite(node.x)) node.x = layoutW / 2;
      if (!Number.isFinite(node.y)) node.y = layoutH / 2;
    }
  }

  return simNodes;
}
