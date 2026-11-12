import type { SimNode } from './types';
import type { TopologyEdge } from '../../types';
import { NODE_COLORS, EDGE_COLORS } from './types';

export interface CanvasFrameOptions {
  canvas: HTMLCanvasElement;
  nodes: SimNode[];
  edges: TopologyEdge[];
  nodeMap: Map<string, SimNode>;
  selectedNodeId: string | null;
  hoveredNodeId: string | null;
  searchQuery: string;
  pan: { x: number; y: number };
  zoom: number;
  timestamp: number;
}

export function renderTopologyCanvasFrame({
  canvas,
  nodes,
  edges,
  nodeMap,
  selectedNodeId,
  hoveredNodeId,
  searchQuery,
  pan,
  zoom,
  timestamp,
}: CanvasFrameOptions): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
  const width = (canvas.width > 0 ? canvas.width : 1000) / dpr;
  const height = (canvas.height > 0 ? canvas.height : 640) / dpr;

  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const safePanX = Number.isFinite(pan.x) ? pan.x : 0;
  const safePanY = Number.isFinite(pan.y) ? pan.y : 0;
  const safeZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;

  ctx.save();
  ctx.translate(safePanX, safePanY);
  ctx.scale(safeZoom, safeZoom);

  const gridSpacing = 40;
  const startX = Math.floor((-safePanX / safeZoom) / gridSpacing) * gridSpacing;
  const endX = Math.ceil(((width - safePanX) / safeZoom) / gridSpacing) * gridSpacing;
  const startY = Math.floor((-safePanY / safeZoom) / gridSpacing) * gridSpacing;
  const endY = Math.ceil(((height - safePanY) / safeZoom) / gridSpacing) * gridSpacing;

  ctx.fillStyle = 'rgba(148, 163, 184, 0.12)';
  for (let gx = startX; gx <= endX; gx += gridSpacing) {
    for (let gy = startY; gy <= endY; gy += gridSpacing) {
      ctx.fillRect(gx - 1, gy - 1, 2, 2);
    }
  }

  const edgesByType = new Map<string, TopologyEdge[]>();
  for (const e of edges) {
    const list = edgesByType.get(e.type) || [];
    list.push(e);
    edgesByType.set(e.type, list);
  }

  edgesByType.forEach((typeEdges, edgeType) => {
    const edgeStyle = EDGE_COLORS[edgeType] || { stroke: '#94a3b8', width: 1.2 };
    ctx.save();
    ctx.strokeStyle = edgeStyle.stroke;
    ctx.fillStyle = edgeStyle.stroke;
    ctx.lineWidth = edgeStyle.width || 1.2;

    if (edgeStyle.dasharray) {
      const dashes = edgeStyle.dasharray.split(/\s+/).map(Number).filter(Number.isFinite);
      if (dashes.length > 0) ctx.setLineDash(dashes);
    } else {
      ctx.setLineDash([]);
    }

    ctx.beginPath();
    for (const e of typeEdges) {
      const p1 = nodeMap.get(e.source);
      const p2 = nodeMap.get(e.target);
      if (!p1 || !p2) continue;

      const x1 = Number.isFinite(p1.x) ? p1.x : 0;
      const y1 = Number.isFinite(p1.y) ? p1.y : 0;
      const x2 = Number.isFinite(p2.x) ? p2.x : 0;
      const y2 = Number.isFinite(p2.y) ? p2.y : 0;

      const dx = x2 - x1;
      const dy = y2 - y1;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist === 0) continue;

      const r1 = Number.isFinite(p1.radius) && p1.radius > 0 ? p1.radius : 16;
      const r2 = Number.isFinite(p2.radius) && p2.radius > 0 ? p2.radius : 16;
      const ux = dx / dist;
      const uy = dy / dist;

      ctx.moveTo(x1 + ux * (r1 + 2), y1 + uy * (r1 + 2));
      ctx.lineTo(x2 - ux * (r2 + 4), y2 - uy * (r2 + 4));
    }
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.beginPath();
    for (const e of typeEdges) {
      const p1 = nodeMap.get(e.source);
      const p2 = nodeMap.get(e.target);
      if (!p1 || !p2) continue;

      const x1 = Number.isFinite(p1.x) ? p1.x : 0;
      const y1 = Number.isFinite(p1.y) ? p1.y : 0;
      const x2 = Number.isFinite(p2.x) ? p2.x : 0;
      const y2 = Number.isFinite(p2.y) ? p2.y : 0;

      const dx = x2 - x1;
      const dy = y2 - y1;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist === 0) continue;

      const r2 = Number.isFinite(p2.radius) && p2.radius > 0 ? p2.radius : 16;
      const ux = dx / dist;
      const uy = dy / dist;

      const tipX = x2 - ux * (r2 + 2);
      const tipY = y2 - uy * (r2 + 2);
      const arrowLen = 7;
      const arrowWidth = 4.5;

      const baseX = tipX - ux * arrowLen;
      const baseY = tipY - uy * arrowLen;
      const px = -uy * arrowWidth;
      const py = ux * arrowWidth;

      ctx.moveTo(tipX, tipY);
      ctx.lineTo(baseX + px, baseY + py);
      ctx.lineTo(baseX - px, baseY - py);
      ctx.closePath();
    }
    ctx.fill();
    ctx.restore();

    if (edges.length < 80) {
      ctx.save();
      ctx.font = '500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      for (const e of typeEdges) {
        if (!e.label) continue;
        const p1 = nodeMap.get(e.source);
        const p2 = nodeMap.get(e.target);
        if (!p1 || !p2) continue;
        const x1 = Number.isFinite(p1.x) ? p1.x : 0;
        const y1 = Number.isFinite(p1.y) ? p1.y : 0;
        const x2 = Number.isFinite(p2.x) ? p2.x : 0;
        const y2 = Number.isFinite(p2.y) ? p2.y : 0;
        ctx.fillText(e.label, (x1 + x2) / 2, (y1 + y2) / 2 - 3);
      }
      ctx.restore();
    }
  });

  const pulsePhase = Math.sin(timestamp / 220);

  for (const n of nodes) {
    const nx = Number.isFinite(n.x) ? n.x : 0;
    const ny = Number.isFinite(n.y) ? n.y : 0;
    const nr = Number.isFinite(n.radius) && n.radius > 0 ? n.radius : 16;
    const colors = NODE_COLORS[n.type] || NODE_COLORS.file;
    const isSelected = selectedNodeId === n.id;
    const isHovered = hoveredNodeId === n.id;
    const isMatch = Boolean(searchQuery && n.name && n.name.toLowerCase().includes(searchQuery.toLowerCase()));

    if (isMatch) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(nx, ny, nr + 7 + pulsePhase * 2, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.95)';
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.restore();
    }

    if (isSelected) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(nx, ny, nr + 5 + Math.max(0, pulsePhase * 2.5), 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(20, 184, 166, 0.95)';
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.restore();
    }

    if (isHovered && !isSelected) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(nx, ny, nr + 4, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.85)';
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.restore();
    }

    ctx.beginPath();
    ctx.arc(nx, ny, nr, 0, Math.PI * 2);
    ctx.fillStyle = colors.fill;
    ctx.fill();
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.strokeStyle = colors.stroke;
    ctx.stroke();

    const displayName = (n.name || '').length > 22 ? (n.name || '').slice(0, 20) + '\u2026' : (n.name || '');
    ctx.font = isSelected
      ? '700 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      : '500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillStyle = colors.text || '#e2e8f0';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(displayName, nx, ny + nr + 5);
  }

  ctx.restore();
  ctx.restore();
}
