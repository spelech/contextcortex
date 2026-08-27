import type { TopologyNode } from '../../types';

export interface SimNode extends TopologyNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
}

export const NODE_COLORS: Record<string, { fill: string; stroke: string; glow: string; text: string }> = {
  file: { fill: '#0369a1', stroke: '#38bdf8', glow: 'rgba(56, 189, 248, 0.4)', text: '#e0f2fe' },
  class: { fill: '#7e22ce', stroke: '#c084fc', glow: 'rgba(192, 132, 252, 0.4)', text: '#f3e8ff' },
  function: { fill: '#047857', stroke: '#34d399', glow: 'rgba(52, 211, 153, 0.4)', text: '#ecfdf5' },
  route: { fill: '#b45309', stroke: '#fbbf24', glow: 'rgba(251, 191, 36, 0.4)', text: '#fffbeb' },
  module: { fill: '#4338ca', stroke: '#818cf8', glow: 'rgba(129, 140, 248, 0.4)', text: '#e0e7ff' },
};

export const EDGE_COLORS: Record<string, { stroke: string; dasharray?: string; width: number }> = {
  IMPORTS: { stroke: '#38bdf8', dasharray: '4 3', width: 1.5 },
  CALLS: { stroke: '#34d399', width: 1.2 },
  DEFINES: { stroke: '#c084fc', dasharray: '3 3', width: 1.0 },
  HANDLES: { stroke: '#fbbf24', width: 1.8 },
  ROUTES_TO: { stroke: '#fb7185', dasharray: '5 3', width: 2.0 },
  DOC_LINKS_TO: { stroke: '#a78bfa', dasharray: '4 2', width: 1.4 },
};

export type {
  TopologyViewMode,
  FocalBreadcrumb,
  NeighborhoodSubGraph,
  RadialLayoutResult,
  TopologyPhysicsConfig,
  ArchitecturePreset,
} from '../../types';

