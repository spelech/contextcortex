import type { TopologyEdge } from '../../types';
import type { SimNode } from './types';
import { NODE_COLORS } from './types';

interface TopologyMinimapProps {
  visibleNodes: SimNode[];
  visibleEdges?: TopologyEdge[];
  nodePosMap: Map<string, { x: number; y: number; radius: number }>;
}

export function TopologyMinimap({ visibleNodes }: TopologyMinimapProps) {
  if (visibleNodes.length === 0) return null;

  // Calculate bounding box of visible nodes with padding
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const n of visibleNodes) {
    if (!isFinite(n.x) || !isFinite(n.y)) continue;
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

  const nodesToRender = visibleNodes.length > 200 ? visibleNodes.slice(0, 200) : visibleNodes;

  return (
    <div className="topology-minimap">
      <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet">
        {nodesToRender.map((n) => {
          if (!isFinite(n.x) || !isFinite(n.y)) return null;
          const colors = NODE_COLORS[n.type] || NODE_COLORS.file;
          return (
            <circle
              key={`mini-n-${n.id}`}
              cx={n.x}
              cy={n.y}
              r={3.5}
              fill={colors.stroke}
              opacity={0.85}
            />
          );
        })}
      </svg>
    </div>
  );
}

