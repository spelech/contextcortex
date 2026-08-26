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

  // Calculate bounding box of visible nodes with padding
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const n of visibleNodes) {
    if (n.x < minX) minX = n.x;
    if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.y > maxY) maxY = n.y;
  }

  const padding = 40;
  const clampedMinX = isFinite(minX) ? minX - padding : 0;
  const clampedMaxX = isFinite(maxX) ? maxX + padding : 1000;
  const clampedMinY = isFinite(minY) ? minY - padding : 0;
  const clampedMaxY = isFinite(maxY) ? maxY + padding : 640;

  const boxWidth = Math.max(clampedMaxX - clampedMinX, 200);
  const boxHeight = Math.max(clampedMaxY - clampedMinY, 150);
  const viewBox = `${clampedMinX} ${clampedMinY} ${boxWidth} ${boxHeight}`;

  return (
    <div className="topology-minimap">
      <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet">
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
              strokeWidth="1.2"
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
