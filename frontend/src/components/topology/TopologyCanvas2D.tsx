import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import type { SimNode, TopologyPhysicsConfig } from './types';
import type { TopologyEdge } from '../../types';
import { calculateForceDirectedLayout } from './forceLayout';
import { renderTopologyCanvasFrame } from './canvasFrameRenderer';

export { calculateForceDirectedLayout };

export interface TopologyCanvas2DProps {
  nodes: SimNode[];
  edges: TopologyEdge[];
  selectedNodeId: string | null;
  searchQuery: string;
  onSelectNode: (nodeId: string) => void;
  onNodePositionChange?: (nodeId: string, x: number, y: number) => void;
  autoFitOnMount?: boolean;
  physicsConfig?: TopologyPhysicsConfig;
  relaxTrigger?: number;
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

  const isPanningRef = useRef<boolean>(false);
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const draggedNodeRef = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const dragHasMovedRef = useRef<boolean>(false);

  const nodeMap = useMemo(() => {
    const map = new Map<string, SimNode>();
    for (const n of nodes) map.set(n.id, n);
    return map;
  }, [nodes]);

  const getCanvasCoords = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement> | MouseEvent) => {
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
      return {
        screenX: Number.isFinite(screenX) ? screenX : 0,
        screenY: Number.isFinite(screenY) ? screenY : 0,
        worldX: Number.isFinite(worldX) ? worldX : 0,
        worldY: Number.isFinite(worldY) ? worldY : 0,
      };
    },
    [pan, zoom]
  );

  const findNodeAt = useCallback(
    (worldX: number, worldY: number): SimNode | null => {
      if (!Number.isFinite(worldX) || !Number.isFinite(worldY)) return null;
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i];
        const nx = Number.isFinite(n.x) ? n.x : 0;
        const ny = Number.isFinite(n.y) ? n.y : 0;
        const nr = Number.isFinite(n.radius) && n.radius > 0 ? n.radius : 16;
        const hitRadius = nr + 6;
        const dx = worldX - nx;
        const dy = worldY - ny;
        if (dx * dx + dy * dy <= hitRadius * hitRadius) return n;
      }
      return null;
    },
    [nodes]
  );

  const updateCanvasDimensions = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const rect = container.getBoundingClientRect();
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
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

  useEffect(() => {
    updateCanvasDimensions();
    if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
      const ro = new ResizeObserver(() => updateCanvasDimensions());
      ro.observe(containerRef.current);
      return () => ro.disconnect();
    }
  }, [updateCanvasDimensions]);

  const renderCanvas = useCallback(
    (timestamp: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      renderTopologyCanvasFrame({
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
      });
    },
    [nodes, edges, nodeMap, selectedNodeId, hoveredNodeId, searchQuery, pan, zoom]
  );

  useEffect(() => {
    renderCanvas(typeof performance !== 'undefined' ? performance.now() : Date.now());
  }, [renderCanvas]);

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
    return () => cancelAnimationFrame(animId);
  }, []);

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
      setPan({ x: screenX - panStartRef.current.x, y: screenY - panStartRef.current.y });
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

    setZoom(newZoom);
    setPan({
      x: screenX - (screenX - pan.x) * (newZoom / currentZoom),
      y: screenY - (screenY - pan.y) * (newZoom / currentZoom),
    });
  };

  const handleZoomBy = (factor: number) => {
    const viewW = canvasRef.current?.clientWidth || 1000;
    const viewH = canvasRef.current?.clientHeight || 640;
    const cx = viewW / 2;
    const cy = viewH / 2;
    const currentZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
    const newZoom = Math.min(3.5, Math.max(0.2, currentZoom * factor));
    setZoom(newZoom);
    setPan({
      x: cx - (cx - pan.x) * (newZoom / currentZoom),
      y: cy - (cy - pan.y) * (newZoom / currentZoom),
    });
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

    setZoom(targetZoom);
    setPan({
      x: viewW / 2 - ((minX + maxX) / 2) * targetZoom,
      y: viewH / 2 - ((minY + maxY) / 2) * targetZoom,
    });
  }, [nodes]);

  const prevNodeCountRef = useRef<number>(0);
  useEffect(() => {
    if (autoFitOnMount && nodes.length > 0 && nodes.length !== prevNodeCountRef.current) {
      prevNodeCountRef.current = nodes.length;
      handleFitToView();
    }
  }, [autoFitOnMount, nodes.length, handleFitToView]);

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

  const cursorStyle = isDraggingNodeState || isPanningState ? 'grabbing' : hoveredNodeId ? 'pointer' : 'grab';

  return (
    <div className="topology-canvas-wrapper" ref={containerRef} style={{ cursor: cursorStyle }}>
      <div className="topology-controls-panel">
        <button type="button" className="topology-btn-ctrl" onClick={() => handleZoomBy(1.25)} title="Zoom In" aria-label="Zoom In">
          <i className="fa-solid fa-plus"></i>
        </button>
        <button type="button" className="topology-btn-ctrl" onClick={() => handleZoomBy(1 / 1.25)} title="Zoom Out" aria-label="Zoom Out">
          <i className="fa-solid fa-minus"></i>
        </button>
        <button type="button" className="topology-btn-ctrl" onClick={handleFitToView} title="Fit to View" aria-label="Fit to View">
          <i className="fa-solid fa-expand"></i>
        </button>
        <button type="button" className="topology-btn-ctrl" onClick={() => { setPan({ x: 0, y: 0 }); setZoom(1); }} title="Reset View" aria-label="Reset View">
          <i className="fa-solid fa-arrows-rotate"></i>
        </button>
        <button type="button" className="topology-btn-ctrl" onClick={handleExportPNG} title="Export PNG" aria-label="Export PNG">
          <i className="fa-solid fa-camera"></i>
        </button>
      </div>

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

      {nodes.length === 0 && (
        <div className="topology-empty-state">
          <i className="fa-solid fa-diagram-project fa-3x" style={{ opacity: 0.3 }}></i>
          <p>No graph nodes found matching current filters.</p>
        </div>
      )}
    </div>
  );
}
