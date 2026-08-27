import { describe, it, expect } from 'vitest';
import { buildNeighborhoodGraph, calculateRadialPositions } from '../components/topology/neighborhoodLayout';
import type { TopologyNode, TopologyEdge, NeighborhoodSubGraph } from '../types';

describe('neighborhoodLayout', () => {
  const nodes: TopologyNode[] = [
    { id: 'focal', name: 'FocalService.cs', type: 'file', repo: 'core' },
    { id: 'caller1', name: 'MainController.cs', type: 'file', repo: 'core' },
    { id: 'caller2', name: 'ApiController.cs', type: 'file', repo: 'core' },
    { id: 'callee1', name: 'Logger.cs', type: 'file', repo: 'core' },
    { id: 'callee2', name: 'Database.cs', type: 'file', repo: 'core' },
    { id: 'secondary1', name: 'Formatter.cs', type: 'file', repo: 'core' },
    { id: 'secondary2', name: 'Driver.cs', type: 'file', repo: 'core' },
    { id: 'orphan', name: 'Unrelated.cs', type: 'file', repo: 'core' },
  ];

  const edges: TopologyEdge[] = [
    { source: 'caller1', target: 'focal', type: 'CALLS', label: 'invokes' },
    { source: 'caller2', target: 'focal', type: 'HANDLES' },
    { source: 'focal', target: 'callee1', type: 'IMPORTS' },
    { source: 'focal', target: 'callee2', type: 'CALLS' },
    { source: 'callee1', target: 'secondary1', type: 'CALLS' },
    { source: 'callee2', target: 'secondary2', type: 'CALLS' },
    { source: 'caller1', target: 'callee1', type: 'IMPORTS' }, // edge between 1-hop nodes
  ];

  describe('buildNeighborhoodGraph', () => {
    it('builds 1-hop neighborhood subgraph correctly', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
      expect(sub.focalNode.id).toBe('focal');
      
      const incomingIds = sub.incoming.map(i => i.node.id);
      expect(incomingIds).toContain('caller1');
      expect(incomingIds).toContain('caller2');
      expect(incomingIds).not.toContain('focal');
      expect(incomingIds).not.toContain('orphan');

      const outgoingIds = sub.outgoing.map(o => o.node.id);
      expect(outgoingIds).toContain('callee1');
      expect(outgoingIds).toContain('callee2');
      expect(outgoingIds).not.toContain('focal');
      expect(outgoingIds).not.toContain('orphan');

      expect(sub.secondaryNodes.length).toBe(0);
      
      // Check edges included in 1-hop: incoming, outgoing, and edges between 1-hop nodes
      const edgeSources = sub.edges.map(e => `${e.source}->${e.target}`);
      expect(edgeSources).toContain('caller1->focal');
      expect(edgeSources).toContain('caller2->focal');
      expect(edgeSources).toContain('focal->callee1');
      expect(edgeSources).toContain('focal->callee2');
      expect(edgeSources).toContain('caller1->callee1');
      expect(edgeSources).not.toContain('callee1->secondary1');
    });

    it('builds 2-hop neighborhood with secondary nodes and edges', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 2);
      expect(sub.focalNode.id).toBe('focal');
      
      const secondaryIds = sub.secondaryNodes.map(s => s.id);
      expect(secondaryIds).toContain('secondary1');
      expect(secondaryIds).toContain('secondary2');
      expect(secondaryIds).not.toContain('orphan');
      expect(secondaryIds).not.toContain('focal');
      expect(secondaryIds).not.toContain('caller1');

      const edgeSources = sub.edges.map(e => `${e.source}->${e.target}`);
      expect(edgeSources).toContain('callee1->secondary1');
      expect(edgeSources).toContain('callee2->secondary2');
    });

    it('handles fallback when focalNodeId is not found', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'non-existent-id', 1);
      expect(sub.focalNode.id).toBe(nodes[0].id);
    });

    it('handles empty nodes and edges gracefully', () => {
      const subEmpty = buildNeighborhoodGraph([], [], 'focal', 1);
      expect(subEmpty.focalNode).toBeDefined();
      expect(subEmpty.incoming).toEqual([]);
      expect(subEmpty.outgoing).toEqual([]);
      expect(subEmpty.secondaryNodes).toEqual([]);
      expect(subEmpty.edges).toEqual([]);

      const subUndefinedEdges = buildNeighborhoodGraph(nodes, undefined, 'focal', 1);
      expect(subUndefinedEdges.focalNode.id).toBe('focal');
      expect(subUndefinedEdges.incoming).toEqual([]);
      expect(subUndefinedEdges.outgoing).toEqual([]);
      expect(subUndefinedEdges.secondaryNodes).toEqual([]);
      expect(subUndefinedEdges.edges).toEqual([]);
    });

    it('preserves edge labels and edge types in incoming and outgoing lists', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
      const caller1 = sub.incoming.find(i => i.node.id === 'caller1');
      expect(caller1).toBeDefined();
      expect(caller1?.edgeType).toBe('CALLS');
      expect(caller1?.label).toBe('invokes');
    });
  });

  describe('calculateRadialPositions', () => {
    it('calculates finite radial positions without NaN or Infinity', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 2);
      const layout = calculateRadialPositions(sub, { x: 500, y: 320 }, 180, 300);

      expect(layout.focal.x).toBe(500);
      expect(layout.focal.y).toBe(320);
      expect(Number.isFinite(layout.focal.x)).toBe(true);
      expect(Number.isFinite(layout.focal.y)).toBe(true);

      expect(layout.neighbors.length).toBeGreaterThan(0);
      layout.neighbors.forEach(n => {
        expect(Number.isFinite(n.x)).toBe(true);
        expect(Number.isFinite(n.y)).toBe(true);
        expect(Number.isFinite(n.angle)).toBe(true);
        expect(Number.isNaN(n.x)).toBe(false);
        expect(Number.isNaN(n.y)).toBe(false);
        expect(Number.isNaN(n.angle)).toBe(false);
      });
    });

    it('places incoming neighbors in the left arc (x < focal.x)', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
      const layout = calculateRadialPositions(sub, { x: 500, y: 320 }, 180, 300);

      const incoming = layout.neighbors.filter(n => n.direction === 'incoming');
      expect(incoming.length).toBe(2);
      incoming.forEach(n => {
        expect(n.ring).toBe(1);
        expect(n.x).toBeLessThan(500);
      });
    });

    it('places outgoing neighbors in the right arc (x > focal.x)', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
      const layout = calculateRadialPositions(sub, { x: 500, y: 320 }, 180, 300);

      const outgoing = layout.neighbors.filter(n => n.direction === 'outgoing');
      expect(outgoing.length).toBe(2);
      outgoing.forEach(n => {
        expect(n.ring).toBe(1);
        expect(n.x).toBeGreaterThan(500);
      });
    });

    it('places secondary nodes on the outer ring with ring=2', () => {
      const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 2);
      const layout = calculateRadialPositions(sub, { x: 500, y: 320 }, 180, 300);

      const secondary = layout.neighbors.filter(n => n.direction === 'secondary');
      expect(secondary.length).toBe(2);
      secondary.forEach(n => {
        expect(n.ring).toBe(2);
        const dist = Math.hypot(n.x - 500, n.y - 320);
        expect(Math.round(dist)).toBe(300);
      });
    });

    it('handles single incoming and single outgoing node cleanly', () => {
      const singleNodeGraph: NeighborhoodSubGraph = {
        focalNode: { id: 'focal', name: 'Focal', type: 'file', repo: 'core' },
        incoming: [{ node: { id: 'in1', name: 'In1', type: 'file', repo: 'core' }, edgeType: 'CALLS' }],
        outgoing: [{ node: { id: 'out1', name: 'Out1', type: 'file', repo: 'core' }, edgeType: 'IMPORTS' }],
        secondaryNodes: [],
        edges: [],
      };
      const layout = calculateRadialPositions(singleNodeGraph, { x: 500, y: 320 }, 180, 300);
      expect(layout.neighbors.length).toBe(2);
      
      const inNode = layout.neighbors.find(n => n.direction === 'incoming');
      expect(inNode).toBeDefined();
      expect(inNode!.x).toBeCloseTo(500 - 180, 1);
      expect(inNode!.y).toBeCloseTo(320, 1);

      const outNode = layout.neighbors.find(n => n.direction === 'outgoing');
      expect(outNode).toBeDefined();
      expect(outNode!.x).toBeCloseTo(500 + 180, 1);
      expect(outNode!.y).toBeCloseTo(320, 1);
    });

    it('handles empty neighborhood subgraphs without errors or NaNs', () => {
      const emptyGraph: NeighborhoodSubGraph = {
        focalNode: { id: 'alone', name: 'Alone', type: 'file', repo: 'core' },
        incoming: [],
        outgoing: [],
        secondaryNodes: [],
        edges: [],
      };
      const layout = calculateRadialPositions(emptyGraph, { x: 500, y: 320 }, 180, 300);
      expect(layout.focal).toEqual({ x: 500, y: 320 });
      expect(layout.neighbors).toEqual([]);
    });
  });
});
