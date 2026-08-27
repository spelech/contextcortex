import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { TopologyCanvas2D } from '../components/topology/TopologyCanvas2D';
import type { SimNode } from '../components/topology/types';
import type { TopologyEdge } from '../types';

const mockNodes: SimNode[] = [
  { id: 'node-1', name: 'OrderService.cs', type: 'class', repo: 'backend', x: 200, y: 150, vx: 0, vy: 0, radius: 18 },
  { id: 'node-2', name: 'OrderController.cs', type: 'class', repo: 'backend', x: 400, y: 150, vx: 0, vy: 0, radius: 18 },
  { id: 'node-3', name: 'GET /api/orders', type: 'route', repo: 'backend', x: 400, y: 300, vx: 0, vy: 0, radius: 16 },
  { id: 'node-4', name: 'utils.ts', type: 'file', repo: 'frontend', x: 600, y: 300, vx: 0, vy: 0, radius: 14 },
];

const mockEdges: TopologyEdge[] = [
  { source: 'node-2', target: 'node-1', type: 'CALLS', label: 'processOrder' },
  { source: 'node-3', target: 'node-2', type: 'ROUTES_TO' },
  { source: 'node-4', target: 'node-1', type: 'IMPORTS' },
];

describe('TopologyCanvas2D Component', () => {
  let mockCtx: any;
  let originalGetContext: any;
  let originalToDataURL: any;
  let originalResizeObserver: any;

  beforeEach(() => {
    mockCtx = {
      clearRect: vi.fn(),
      fillRect: vi.fn(),
      beginPath: vi.fn(),
      closePath: vi.fn(),
      arc: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      fill: vi.fn(),
      fillText: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      setLineDash: vi.fn(),
      measureText: vi.fn(() => ({ width: 50 })),
      canvas: { width: 1000, height: 640 },
    };

    originalGetContext = HTMLCanvasElement.prototype.getContext;
    originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    originalResizeObserver = window.ResizeObserver;

    HTMLCanvasElement.prototype.getContext = vi.fn(function (this: HTMLCanvasElement, contextId: string) {
      if (contextId === '2d') {
        mockCtx.canvas = this;
        return mockCtx;
      }
      return null;
    }) as any;

    HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/png;base64,mockpngdata');

    window.ResizeObserver = class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    } as any;
  });

  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
    window.ResizeObserver = originalResizeObserver;
    vi.restoreAllMocks();
  });

  it('renders canvas element with data-testid and built-in control buttons', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');
    expect(canvas).toBeInTheDocument();
    expect(canvas.tagName.toLowerCase()).toBe('canvas');

    // Controls
    expect(screen.getByRole('button', { name: /Zoom In/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Zoom Out/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Fit to View/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reset View/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Export PNG/i })).toBeInTheDocument();
  });

  it('invokes canvas rendering pipeline with clearRect, transforms, edges, and nodes', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId="node-1"
        searchQuery="order"
        onSelectNode={vi.fn()}
      />
    );

    expect(mockCtx.clearRect).toHaveBeenCalled();
    expect(mockCtx.translate).toHaveBeenCalled();
    expect(mockCtx.scale).toHaveBeenCalled();
    expect(mockCtx.arc).toHaveBeenCalled();
    expect(mockCtx.fill).toHaveBeenCalled();
    expect(mockCtx.stroke).toHaveBeenCalled();
    expect(mockCtx.fillText).toHaveBeenCalled();
  });

  it('sets line dash for styled dashed edges like IMPORTS and ROUTES_TO', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    expect(mockCtx.setLineDash).toHaveBeenCalled();
  });

  it('clicking Zoom In, Zoom Out, and Reset View triggers viewport transformations', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const zoomInBtn = screen.getByRole('button', { name: /Zoom In/i });
    const zoomOutBtn = screen.getByRole('button', { name: /Zoom Out/i });
    const resetBtn = screen.getByRole('button', { name: /Reset View/i });

    mockCtx.scale.mockClear();
    fireEvent.click(zoomInBtn);
    expect(mockCtx.scale).toHaveBeenCalled();

    mockCtx.scale.mockClear();
    fireEvent.click(zoomOutBtn);
    expect(mockCtx.scale).toHaveBeenCalled();

    mockCtx.translate.mockClear();
    fireEvent.click(resetBtn);
    expect(mockCtx.translate).toHaveBeenCalledWith(0, 0);
  });

  it('clicking Fit to View calculates bounding box and adjusts zoom and pan', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const fitBtn = screen.getByRole('button', { name: /Fit to View/i });
    mockCtx.translate.mockClear();
    mockCtx.scale.mockClear();

    fireEvent.click(fitBtn);
    expect(mockCtx.translate).toHaveBeenCalled();
    expect(mockCtx.scale).toHaveBeenCalled();
  });

  it('clicking Export PNG generates data URL and triggers download', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const exportBtn = screen.getByRole('button', { name: /Export PNG/i });
    fireEvent.click(exportBtn);
    expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith('image/png');
  });

  it('spatial hit-testing clicks on a node and calls onSelectNode', () => {
    const onSelectNode = vi.fn();
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={onSelectNode}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');

    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1000,
      bottom: 640,
      width: 1000,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    // Node 1 is at x: 200, y: 150
    fireEvent.mouseDown(canvas, { clientX: 200, clientY: 150 });
    fireEvent.mouseUp(canvas, { clientX: 200, clientY: 150 });

    expect(onSelectNode).toHaveBeenCalledWith('node-1');
  });

  it('hovering over a node updates hover state without selecting', () => {
    const onSelectNode = vi.fn();
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={onSelectNode}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1000,
      bottom: 640,
      width: 1000,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    // Hover over node 2 (400, 150)
    fireEvent.mouseMove(canvas, { clientX: 400, clientY: 150 });
    expect(onSelectNode).not.toHaveBeenCalled();
  });

  it('supports background panning when dragging empty canvas space', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1000,
      bottom: 640,
      width: 1000,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    mockCtx.translate.mockClear();
    // Drag background from (50, 50) to (100, 120)
    fireEvent.mouseDown(canvas, { clientX: 50, clientY: 50 });
    fireEvent.mouseMove(canvas, { clientX: 100, clientY: 120 });
    fireEvent.mouseUp(canvas, { clientX: 100, clientY: 120 });

    expect(mockCtx.translate).toHaveBeenCalled();
  });

  it('supports dragging nodes and triggers onNodePositionChange', () => {
    const onNodePositionChange = vi.fn();
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
        onNodePositionChange={onNodePositionChange}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1000,
      bottom: 640,
      width: 1000,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    // Start drag on Node 1 (200, 150)
    fireEvent.mouseDown(canvas, { clientX: 200, clientY: 150 });
    // Move to 250, 180
    fireEvent.mouseMove(canvas, { clientX: 250, clientY: 180 });
    fireEvent.mouseUp(canvas, { clientX: 250, clientY: 180 });

    expect(onNodePositionChange).toHaveBeenCalledWith('node-1', 250, 180);
  });

  it('handles wheel events to zoom around mouse cursor', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={mockEdges}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    const canvas = screen.getByTestId('topology-2d-canvas');
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1000,
      bottom: 640,
      width: 1000,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    mockCtx.scale.mockClear();
    fireEvent.wheel(canvas, { clientX: 500, clientY: 320, deltaY: -100 });
    expect(mockCtx.scale).toHaveBeenCalled();
  });

  it('renders empty state when node list is empty', () => {
    render(
      <TopologyCanvas2D
        nodes={[]}
        edges={[]}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    expect(screen.getByText(/No graph nodes found matching current filters/i)).toBeInTheDocument();
  });

  it('guards coordinates with isFinite to prevent NaN rendering errors', () => {
    const invalidNodes: SimNode[] = [
      { id: 'node-nan', name: 'Broken.cs', type: 'class', repo: 'backend', x: NaN, y: Infinity, vx: 0, vy: 0, radius: NaN },
    ];
    const invalidEdges: TopologyEdge[] = [
      { source: 'node-nan', target: 'node-nan', type: 'CALLS' },
    ];

    expect(() => {
      render(
        <TopologyCanvas2D
          nodes={invalidNodes}
          edges={invalidEdges}
          selectedNodeId={null}
          searchQuery=""
          onSelectNode={vi.fn()}
        />
      );
    }).not.toThrow();

    expect(mockCtx.clearRect).toHaveBeenCalled();
  });
});
