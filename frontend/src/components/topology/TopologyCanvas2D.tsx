import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import type { SimNode } from './types';
import type { TopologyEdge } from '../../types';
import { NODE_COLORS, EDGE_COLORS } from './types';

export interface TopologyCanvas2DProps {
  nodes: SimNode[];
  edges: TopologyEdge[];
  selectedNodeId: string | null;
  searchQuery: string;
  onSelectNode: (nodeId: string) => void;
  onNodePositionChange?: (nodeId: string, x: number, y: number) => void;
  autoFitOnMount?: boolean;
}

export function TopologyCanvas2D({
  nodes,
  edges,
  selectedNodeId,
  searchQuery,
  onSelectNode,
  onNodePositionChange,
  autoFitOnMount = false,
}: TopologyCanvas2DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState<number>(1);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [isPanningState, setIsPanningState] = useState<boolean>(false);
  const [isDraggingNodeState, setIsDraggingNodeState] = useState<boolean>(false);

  // References for mouse drag interactions
  const isPanningRef = useRef<boolean>(false);
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const draggedNodeRef = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const dragHasMovedRef = useRef<boolean>(false);

  // Fast lookup map for nodes
  const nodeMap = useMemo(() => {
    const map = new Map<string, SimNode>();
    for (const n of nodes) {
      map.set(n.id, n);
    }
    return map;
  }, [nodes]);

  // Coordinate conversion helper
  const getCanvasCoords = useCallback((e: React.MouseEvent<HTMLCanvasElement> | MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return { screenX: 0, screenY: 0, worldX: 0, worldY: 0 };
    const rect = canvas.getBoundingClientRect();
    const screenX = e.clientX - rect.left;
    const screenY = e.clientY - rect.top;
    const currentZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
    const currentPanX = Number.isFinite(pan.x) ? pan.x : 0;
    const currentPanY = Number.isFinite(pan.y) ? pan.y : 0;
    const worldX = (screenX - currentPanX) / currentZoom;
    const worldY = (screenY - currentPanY) / currentZoom;
    return { screenX, screenY, worldX, worldY };
  }, [pan, zoom]);

  // Spatial hit-testing to find node under cursor
  const findNodeAt = useCallback((worldX: number, worldY: number): SimNode | null => {
    if (!Number.isFinite(worldX) || !Number.isFinite(worldY)) return null;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const nx = Number.isFinite(n.x) ? n.x : 0;
      const ny = Number.isFinite(n.y) ? n.y : 0;
      const nr = Number.isFinite(n.radius) && n.radius > 0 ? n.radius : 16;
      const hitRadius = nr + 6;
      const dx = worldX - nx;
      const dy = worldY - ny;
      if (dx * dx + dy * dy <= hitRadius * hitRadius) {
        return n;
      }
    }
    return null;
  }, [nodes]);

  // Canvas size and DPR synchronization
  const updateCanvasDimensions = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const rect = container.getBoundingClientRect();
    const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1;
    const w = rect.width > 0 ? rect.width : 1000;
    const h = rect.height > 0 ? rect.height : 640;

    const targetWidth = Math.floor(w * dpr);
    const targetHeight = Math.floor(h * dpr);

    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
  }, []);

  // Resize observer to adapt to container layout changes
  useEffect(() => {
    updateCanvasDimensions();
    if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
      const ro = new ResizeObserver(() => {
        updateCanvasDimensions();
      });
      ro.observe(containerRef.current);
      return () => ro.disconnect();
    }
  }, [updateCanvasDimensions]);

  // Main Canvas Render Routine
  const renderCanvas = useCallback((timestamp: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1;
    const width = (canvas.width > 0 ? canvas.width : 1000) / dpr;
    const height = (canvas.height > 0 ? canvas.height : 640) / dpr;

    ctx.save();
    ctx.scale(dpr, dpr);

    // 1. Clear Viewport
    ctx.clearRect(0, 0, width, height);

    const safePanX = Number.isFinite(pan.x) ? pan.x : 0;
    const safePanY = Number.isFinite(pan.y) ? pan.y : 0;
    const safeZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;

    // 2. Transformed World Space
    ctx.save();
    ctx.translate(safePanX, safePanY);
    ctx.scale(safeZoom, safeZoom);

    // Subtle background grid dots
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

    // 3. Batched Edges
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
        if (dashes.length > 0) {
          ctx.setLineDash(dashes);
        }
      } else {
        ctx.setLineDash([]);
      }

      // Draw edge lines
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

        const sx = x1 + ux * (r1 + 2);
        const sy = y1 + uy * (r1 + 2);
        const tx = x2 - ux * (r2 + 4);
        const ty = y2 - uy * (r2 + 4);

        ctx.moveTo(sx, sy);
        ctx.lineTo(tx, ty);
      }
      ctx.stroke();

      // Draw arrowheads
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

      // Optional edge labels for sparse graphs
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

    // 4. Nodes and Highlights
    const pulsePhase = Math.sin(timestamp / 220);

    for (const n of nodes) {
      const nx = Number.isFinite(n.x) ? n.x : 0;
      const ny = Number.isFinite(n.y) ? n.y : 0;
      const nr = Number.isFinite(n.radius) && n.radius > 0 ? n.radius : 16;
      const colors = NODE_COLORS[n.type] || NODE_COLORS.file;
      const isSelected = selectedNodeId === n.id;
      const isHovered = hoveredNodeId === n.id;
      const isMatch = Boolean(searchQuery && n.name && n.name.toLowerCase().includes(searchQuery.toLowerCase()));

      // A. Search Highlight Ring
      if (isMatch) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(nx, ny, nr + 7 + pulsePhase * 2, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(245, 158, 11, 0.95)';
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.restore();
      }

      // B. Selected Node Glowing Pulse Ring
      if (isSelected) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(nx, ny, nr + 5 + Math.max(0, pulsePhase * 2.5), 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(20, 184, 166, 0.95)';
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.restore();
      }

      // C. Hover Ring
      if (isHovered && !isSelected) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(nx, ny, nr + 4, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.85)';
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.restore();
      }

      // D. Node Base Circular Glyph
      ctx.beginPath();
      ctx.arc(nx, ny, nr, 0, Math.PI * 2);
      ctx.fillStyle = colors.fill;
      ctx.fill();
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeStyle = colors.stroke;
      ctx.stroke();

      // E. Node Label Text
      const displayName = (n.name || '').length > 22 ? (n.name || '').slice(0, 20) + '…' : (n.name || '');
      ctx.font = isSelected
        ? '700 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
        : '500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      ctx.fillStyle = colors.text || '#e2e8f0';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(displayName, nx, ny + nr + 5);
    }

    ctx.restore(); // Restore world transform
    ctx.restore(); // Restore dpr scale
  }, [nodes, edges, nodeMap, selectedNodeId, hoveredNodeId, searchQuery, pan, zoom]);

  // Synchronous render on state / prop changes
  useEffect(() => {
    renderCanvas(typeof performance !== 'undefined' ? performance.now() : Date.now());
  }, [renderCanvas]);

  // Continuous animation loop for 60 FPS smoothness
  const renderRef = useRef<(time: number) => void>(renderCanvas);
  useEffect(() => {
    renderRef.current = renderCanvas;
  }, [renderCanvas]);

  useEffect(() => {
    let animId: number;
    const tick = (time: number) => {
      renderRef.current(time);
      animId = requestAnimationFrame(tick);
    };
    animId = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(animId);
    };
  }, []);

  // Mouse & Gesture Handlers
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { screenX, screenY, worldX, worldY } = getCanvasCoords(e);
    const hit = findNodeAt(worldX, worldY);

    if (hit) {
      draggedNodeRef.current = {
        id: hit.id,
        offsetX: worldX - (Number.isFinite(hit.x) ? hit.x : 0),
        offsetY: worldY - (Number.isFinite(hit.y) ? hit.y : 0),
      };
      dragHasMovedRef.current = false;
      setIsDraggingNodeState(true);
    } else {
      isPanningRef.current = true;
      panStartRef.current = { x: screenX - pan.x, y: screenY - pan.y };
      setIsPanningState(true);
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { screenX, screenY, worldX, worldY } = getCanvasCoords(e);

    if (draggedNodeRef.current) {
      dragHasMovedRef.current = true;
      const targetNode = nodeMap.get(draggedNodeRef.current.id);
      const newX = worldX - draggedNodeRef.current.offsetX;
      const newY = worldY - draggedNodeRef.current.offsetY;

      if (targetNode) {
        targetNode.x = newX;
        targetNode.y = newY;
      }
      if (onNodePositionChange) {
        onNodePositionChange(draggedNodeRef.current.id, newX, newY);
      }
    } else if (isPanningRef.current) {
      const newPanX = screenX - panStartRef.current.x;
      const newPanY = screenY - panStartRef.current.y;
      setPan({ x: newPanX, y: newPanY });
    } else {
      const hit = findNodeAt(worldX, worldY);
      setHoveredNodeId(hit ? hit.id : null);
    }
  };

  const handleMouseUp = () => {
    if (draggedNodeRef.current) {
      if (!dragHasMovedRef.current) {
        onSelectNode(draggedNodeRef.current.id);
      }
      draggedNodeRef.current = null;
      setIsDraggingNodeState(false);
    }
    isPanningRef.current = false;
    setIsPanningState(false);
  };

  const handleMouseLeave = () => {
    handleMouseUp();
    setHoveredNodeId(null);
  };

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const { screenX, screenY } = getCanvasCoords(e);
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
    const currentZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
    const newZoom = Math.min(3.5, Math.max(0.2, currentZoom * zoomFactor));

    const newPanX = screenX - (screenX - pan.x) * (newZoom / currentZoom);
    const newPanY = screenY - (screenY - pan.y) * (newZoom / currentZoom);

    setZoom(newZoom);
    setPan({ x: newPanX, y: newPanY });
  };

  // Built-in Controls Handlers
  const handleZoomIn = () => {
    const viewW = canvasRef.current?.clientWidth || 1000;
    const viewH = canvasRef.current?.clientHeight || 640;
    const centerScreenX = viewW / 2;
    const centerScreenY = viewH / 2;
    const currentZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
    const newZoom = Math.min(3.5, currentZoom * 1.25);
    const newPanX = centerScreenX - (centerScreenX - pan.x) * (newZoom / currentZoom);
    const newPanY = centerScreenY - (centerScreenY - pan.y) * (newZoom / currentZoom);
    setZoom(newZoom);
    setPan({ x: newPanX, y: newPanY });
  };

  const handleZoomOut = () => {
    const viewW = canvasRef.current?.clientWidth || 1000;
    const viewH = canvasRef.current?.clientHeight || 640;
    const centerScreenX = viewW / 2;
    const centerScreenY = viewH / 2;
    const currentZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
    const newZoom = Math.max(0.2, currentZoom / 1.25);
    const newPanX = centerScreenX - (centerScreenX - pan.x) * (newZoom / currentZoom);
    const newPanY = centerScreenY - (centerScreenY - pan.y) * (newZoom / currentZoom);
    setZoom(newZoom);
    setPan({ x: newPanX, y: newPanY });
  };

  const handleFitToView = useCallback(() => {
    if (nodes.length === 0) {
      setPan({ x: 0, y: 0 });
      setZoom(1);
      return;
    }

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    let validCount = 0;

    for (const n of nodes) {
      if (Number.isFinite(n.x) && Number.isFinite(n.y)) {
        const nr = Number.isFinite(n.radius) && n.radius > 0 ? n.radius : 16;
        minX = Math.min(minX, n.x - nr);
        maxX = Math.max(maxX, n.x + nr);
        minY = Math.min(minY, n.y - nr);
        maxY = Math.max(maxY, n.y + nr);
        validCount++;
      }
    }

    if (validCount === 0) {
      setPan({ x: 0, y: 0 });
      setZoom(1);
      return;
    }

    const padding = 90;
    const boxW = maxX - minX + padding * 2;
    const boxH = maxY - minY + padding * 2;
    const viewW = canvasRef.current?.clientWidth || 1000;
    const viewH = canvasRef.current?.clientHeight || 640;

    let targetZoom = Math.min(viewW / Math.max(boxW, 50), viewH / Math.max(boxH, 50));
    targetZoom = Math.max(0.15, Math.min(1.2, targetZoom));

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const targetPanX = viewW / 2 - centerX * targetZoom;
    const targetPanY = viewH / 2 - centerY * targetZoom;

    setZoom(targetZoom);
    setPan({ x: targetPanX, y: targetPanY });
  }, [nodes]);

  // Automatically fit graph to view when nodes are first loaded or replaced
  const prevNodeCountRef = useRef<number>(0);
  useEffect(() => {
    if (autoFitOnMount && nodes.length > 0 && nodes.length !== prevNodeCountRef.current) {
      prevNodeCountRef.current = nodes.length;
      handleFitToView();
    }
  }, [autoFitOnMount, nodes.length, handleFitToView]);

  const handleResetView = () => {
    setPan({ x: 0, y: 0 });
    setZoom(1);
  };

  const handleExportPNG = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const dataUrl = canvas.toDataURL('image/png');
      const a = document.createElement('a');
      a.href = dataUrl;
      a.download = 'topology-graph-2d.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      console.error('Failed to export canvas PNG:', err);
    }
  };

  const cursorStyle = isDraggingNodeState
    ? 'grabbing'
    : isPanningState
    ? 'grabbing'
    : hoveredNodeId
    ? 'pointer'
    : 'grab';

  return (
    <div
      className="topology-canvas-wrapper"
      ref={containerRef}
      style={{ cursor: cursorStyle }}
    >
      {/* Floating Canvas Controls Overlay */}
      <div className="topology-controls-panel">
        <button
          type="button"
          className="topology-btn-ctrl"
          onClick={handleZoomIn}
          title="Zoom In"
          aria-label="Zoom In"
        >
          <i className="fa-solid fa-plus"></i>
        </button>
        <button
          type="button"
          className="topology-btn-ctrl"
          onClick={handleZoomOut}
          title="Zoom Out"
          aria-label="Zoom Out"
        >
          <i className="fa-solid fa-minus"></i>
        </button>
        <button
          type="button"
          className="topology-btn-ctrl"
          onClick={handleFitToView}
          title="Fit to View"
          aria-label="Fit to View"
        >
          <i className="fa-solid fa-expand"></i>
        </button>
        <button
          type="button"
          className="topology-btn-ctrl"
          onClick={handleResetView}
          title="Reset View"
          aria-label="Reset View"
        >
          <i className="fa-solid fa-arrows-rotate"></i>
        </button>
        <button
          type="button"
          className="topology-btn-ctrl"
          onClick={handleExportPNG}
          title="Export PNG"
          aria-label="Export PNG"
        >
          <i className="fa-solid fa-camera"></i>
        </button>
      </div>

      {/* HTML5 2D Canvas */}
      <canvas
        ref={canvasRef}
        data-testid="topology-2d-canvas"
        className="topology-2d-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onWheel={handleWheel}
      />

      {/* Empty State */}
      {nodes.length === 0 && (
        <div className="topology-empty-state">
          <i className="fa-solid fa-diagram-project fa-3x" style={{ opacity: 0.3 }}></i>
          <p>No graph nodes found matching current filters.</p>
        </div>
      )}
    </div>
  );
}
