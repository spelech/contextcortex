import type { TopologyEdge } from '../../types';
import type { SimNode } from './types';
import { NODE_COLORS } from './types';

interface TopologyMinimapProps {
  visibleNodes: SimNode[];
  visibleEdges: TopologyEdge[];
  nodePosMap: Map<string, { x: number; y: number; radius: number }>;
}

export function TopologyMinimap({ visibleNodes, visibleEdges, nodePosMap }: TopologyMinimapProps) {
  if (visibleNodes.length === 0) return null;

  return (
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
  );
}
