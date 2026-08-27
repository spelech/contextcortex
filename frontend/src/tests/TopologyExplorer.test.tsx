import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TopologyExplorer from '../TopologyExplorer';
import { TopologyMinimap } from '../components/topology/TopologyMinimap';
import type { SimNode } from '../components/topology/types';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockRepos = [
  { id: 1, name: 'repo-core', url: 'https://github.com/org/repo-core.git', branch: 'main', status: 'synced' },
  { id: 2, name: 'repo-web', url: 'https://github.com/org/repo-web.git', branch: 'main', status: 'synced' },
];

const mockTopologyData = {
  nodes: [
    { id: 'file:repo-core:app/main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'app/main.py' },
    { id: 'file:repo-core:app/utils.py', name: 'utils.py', type: 'file', repo: 'repo-core', filepath: 'app/utils.py' },
    { id: 'symbol:1', name: 'handle_request', type: 'function', repo: 'repo-core', filepath: 'app/main.py', start_line: 10, end_line: 25 },
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', repo: 'repo-core', filepath: 'app/main.py', method: 'GET', path_pattern: '/api/v1/status' },
  ],
  edges: [
    { source: 'file:repo-core:app/main.py', target: 'file:repo-core:app/utils.py', type: 'IMPORTS' },
    { source: 'file:repo-core:app/main.py', target: 'symbol:1', type: 'DEFINES' },
    { source: 'route:1', target: 'symbol:1', type: 'HANDLES' },
  ],
  stats: { node_count: 4, edge_count: 3 },
};

const mockNodeDetails = {
  id: 'symbol:1',
  name: 'handle_request',
  type: 'function',
  repo: 'repo-core',
  filepath: 'app/main.py',
  start_line: 10,
  end_line: 25,
  signature: 'def handle_request(req):',
  code_preview: 'def handle_request(req):\n    return {"status": "ok"}',
  permalink: 'https://github.com/org/repo-core/blob/c0ffee1/app/main.py#L10-L25',
  incoming: [
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', edge_type: 'HANDLES', line_number: 10 },
  ],
  outgoing: [
    { id: 'symbol:2', name: 'format_response', type: 'function', edge_type: 'CALLS', line_number: 18 },
  ],
  metadata: { kind: 'function', language: 'python' },
};

describe('TopologyExplorer Component', () => {
  let mockCtx: any;
  let originalGetContext: any;
  let originalToDataURL: any;
  let originalResizeObserver: any;

  beforeEach(() => {
    vi.clearAllMocks();

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

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/repos')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRepos,
        } as Response);
      }
      if (url.includes('/admin/api/graph/topology')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockTopologyData,
        } as Response);
      }
      if (url.includes('/admin/api/graph/node-details')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockNodeDetails,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      } as Response);
    });
  });

  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
    window.ResizeObserver = originalResizeObserver;
  });

  it('renders toolbar, repository selector, view mode switcher, and default neighborhood view', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    // View Mode Toggle
    expect(screen.getByRole('group', { name: /View Mode/i })).toBeInTheDocument();
    const neighborhoodModeBtn = screen.getByRole('button', { name: /Neighborhood View/i });
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    expect(neighborhoodModeBtn).toBeInTheDocument();
    expect(canvasModeBtn).toBeInTheDocument();
    expect(neighborhoodModeBtn).toHaveClass('active');

    // View Type Toggle
    expect(screen.getByRole('group', { name: /View Type/i })).toBeInTheDocument();
    expect(screen.getByText('FILES')).toBeInTheDocument();
    expect(screen.getByText('SYMBOLS')).toBeInTheDocument();
    expect(screen.getByText('ROUTES')).toBeInTheDocument();
    expect(screen.getByText('FULL')).toBeInTheDocument();

    // Default Neighborhood View should load focal node and breadcrumbs
    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('Incoming Dependencies')).toBeInTheDocument();
    expect(screen.getByText('Outgoing Dependencies')).toBeInTheDocument();
  });

  it('handles toggling between neighborhood view and global 2d canvas view', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    const neighborhoodModeBtn = screen.getByRole('button', { name: /Neighborhood View/i });
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });

    // Initial state: neighborhood mode with hop radius selector
    expect(neighborhoodModeBtn).toHaveClass('active');
    expect(screen.getAllByRole('group', { name: /Hop Radius/i }).length).toBeGreaterThanOrEqual(1);

    // Switch to Canvas mode
    fireEvent.click(canvasModeBtn);

    await waitFor(() => {
      expect(canvasModeBtn).toHaveClass('active');
      expect(neighborhoodModeBtn).not.toHaveClass('active');
      expect(screen.getByTestId('topology-2d-canvas')).toBeInTheDocument();
    });

    // In canvas mode, Node Limit and Hide Orphans should be present
    expect(screen.getByRole('combobox', { name: /Node Limit/i })).toBeInTheDocument();
    expect(screen.getByTitle('Toggle orphan nodes')).toBeInTheDocument();

    // Switch back to Neighborhood view
    fireEvent.click(neighborhoodModeBtn);

    await waitFor(() => {
      expect(neighborhoodModeBtn).toHaveClass('active');
      expect(screen.queryByTestId('topology-2d-canvas')).not.toBeInTheDocument();
      expect(screen.getByText('Incoming Dependencies')).toBeInTheDocument();
    });
  });

  it('handles breadcrumb navigation and focal node selection in neighborhood view', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('utils.py').length).toBeGreaterThanOrEqual(1);
    });

    // Initial breadcrumb has main.py
    const initialBreadcrumb = screen.getByTitle('Navigate to main.py');
    expect(initialBreadcrumb).toBeInTheDocument();

    // In Outgoing Dependencies panel, find Focus button for utils.py
    const outgoingSection = screen.getByText('Outgoing Dependencies').closest('.neighborhood-panel');
    expect(outgoingSection).not.toBeNull();

    const focusUtilsBtn = outgoingSection!.querySelector('button[title="Focus node"]');
    expect(focusUtilsBtn).not.toBeNull();
    fireEvent.click(focusUtilsBtn!);

    // Breadcrumb trail should now contain utils.py as active
    await waitFor(() => {
      expect(screen.getByTitle('Navigate to utils.py')).toBeInTheDocument();
    });

    // Click back to main.py breadcrumb
    const mainBreadcrumb = screen.getByTitle('Navigate to main.py');
    fireEvent.click(mainBreadcrumb);

    await waitFor(() => {
      expect(screen.getByTitle('Navigate to main.py')).toHaveClass('active');
      expect(screen.queryByTitle('Navigate to utils.py')).not.toBeInTheDocument();
    });
  });

  it('handles switching view type between FILES, SYMBOLS, ROUTES, and FULL', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    const symbolsBtn = screen.getByRole('button', { name: 'SYMBOLS' });
    fireEvent.click(symbolsBtn);

    await waitFor(() => {
      expect(symbolsBtn).toHaveClass('active');
    });

    const routesBtn = screen.getByRole('button', { name: 'ROUTES' });
    fireEvent.click(routesBtn);

    await waitFor(() => {
      expect(routesBtn).toHaveClass('active');
    });
  });

  it('handles changing repository selection and depth in canvas mode', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    // Switch to canvas mode
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    fireEvent.click(canvasModeBtn);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /repo-core/i })).toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: /Graph Depth/i })).toBeInTheDocument();
    });

    const repoSelect = screen.getByRole('combobox', { name: /Select Repository/i });
    fireEvent.change(repoSelect, { target: { value: 'repo-core' } });

    const depthSelect = screen.getByRole('combobox', { name: /Graph Depth/i });
    fireEvent.change(depthSelect, { target: { value: '3' } });

    await waitFor(() => {
      expect(repoSelect).toHaveValue('repo-core');
      expect(depthSelect).toHaveValue('3');
    });
  });

  it('toggles node type filter chips', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    const fileChip = screen.getByTitle('Toggle file nodes');
    expect(fileChip).not.toHaveClass('inactive');

    fireEvent.click(fileChip);
    expect(fileChip).toHaveClass('inactive');

    fireEvent.click(fileChip);
    expect(fileChip).not.toHaveClass('inactive');
  });

  it('opens slide-over inspector drawer on node inspect click and renders details', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('utils.py').length).toBeGreaterThanOrEqual(1);
    });

    // In outgoing dependencies panel, click "Inspect" on the first outgoing node
    const outgoingSection = screen.getByText('Outgoing Dependencies').closest('.neighborhood-panel');
    const inspectBtn = outgoingSection!.querySelector('button[title="Inspect details"]');
    expect(inspectBtn).not.toBeNull();
    fireEvent.click(inspectBtn!);

    await waitFor(() => {
      expect(screen.getByText(/Location & Repository/i)).toBeInTheDocument();
      expect(screen.getByText(/def handle_request/i)).toBeInTheDocument();
      expect(screen.getByText(/Incoming Connections/i)).toBeInTheDocument();
      expect(screen.getByText(/Outgoing Connections/i)).toBeInTheDocument();
      expect(screen.getByText(/Open in Git Provider/i)).toBeInTheDocument();
    });

    // Close drawer
    const closeBtn = screen.getByRole('button', { name: /Close Inspector/i });
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByText(/Location & Repository/i)).not.toBeInTheDocument();
    });
  });

  it('filters search matches and focuses on matching node', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });

    const searchInput = screen.getByRole('textbox', { name: /Search nodes/i });
    fireEvent.focus(searchInput);
    fireEvent.change(searchInput, { target: { value: 'handle' } });

    await waitFor(() => {
      const matchItems = screen.getAllByText(/handle_request/i);
      expect(matchItems.length).toBeGreaterThanOrEqual(1);
    });

    // Click search match item
    const matchItem = screen.getAllByText(/handle_request/i)[0];
    fireEvent.click(matchItem);

    // Inspector drawer should open with details
    await waitFor(() => {
      expect(screen.getByText(/Location & Repository/i)).toBeInTheDocument();
    });
  });

  it('triggers SVG and JSON exports on button click', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    const svgBtn = screen.getByTitle('Export as SVG');
    const jsonBtn = screen.getByTitle('Export as JSON');

    expect(svgBtn).toBeInTheDocument();
    expect(jsonBtn).toBeInTheDocument();

    fireEvent.click(svgBtn);
    fireEvent.click(jsonBtn);
  });

  it('handles error state when topology API fails', async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/graph/topology')) {
        return Promise.resolve({
          ok: false,
          json: async () => ({ error: 'Repository index not found' }),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/No graph data available for neighborhood view/i)).toBeInTheDocument();
    });
  });

  it('handles changing node limit in canvas mode and queries topology with limit parameter', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    // Switch to canvas mode
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    fireEvent.click(canvasModeBtn);

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /Node Limit/i })).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole('combobox', { name: /Node Limit/i });
    expect(limitSelect).toHaveValue('150');

    fireEvent.change(limitSelect, { target: { value: '50' } });

    await waitFor(() => {
      expect(limitSelect).toHaveValue('50');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('limit=50')
      );
    });

    fireEvent.change(limitSelect, { target: { value: '400' } });

    await waitFor(() => {
      expect(limitSelect).toHaveValue('400');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('limit=400')
      );
    });
  });

  it('toggles hide orphans to filter disconnected nodes in canvas mode', async () => {
    const topologyWithOrphan = {
      nodes: [
        { id: 'file:repo-core:app/main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'app/main.py' },
        { id: 'file:repo-core:app/utils.py', name: 'utils.py', type: 'file', repo: 'repo-core', filepath: 'app/utils.py' },
        { id: 'file:repo-core:app/orphan.py', name: 'orphan.py', type: 'file', repo: 'repo-core', filepath: 'app/orphan.py' },
      ],
      edges: [
        { source: 'file:repo-core:app/main.py', target: 'file:repo-core:app/utils.py', type: 'IMPORTS' },
      ],
      stats: { node_count: 3, edge_count: 1 },
    };

    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/repos')) {
        return Promise.resolve({ ok: true, json: async () => mockRepos } as Response);
      }
      if (url.includes('/admin/api/graph/topology')) {
        return Promise.resolve({ ok: true, json: async () => topologyWithOrphan } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });

    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    // Switch to canvas mode
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    fireEvent.click(canvasModeBtn);

    await waitFor(() => {
      expect(screen.getByTitle('Toggle orphan nodes')).toBeInTheDocument();
    });

    const hideOrphansChip = screen.getByTitle('Toggle orphan nodes');
    expect(hideOrphansChip).toHaveClass('inactive');

    // Click to activate hide orphans
    fireEvent.click(hideOrphansChip);
    expect(hideOrphansChip).not.toHaveClass('inactive');

    // Click again to deactivate hide orphans
    fireEvent.click(hideOrphansChip);
    expect(hideOrphansChip).toHaveClass('inactive');
  });

  it('renders TopologyMinimap with dynamic bounding box viewBox', () => {
    const customNodes: SimNode[] = [
      { id: 'n1', name: 'Node 1', type: 'file', repo: 'r1', x: 100, y: 80, vx: 0, vy: 0, radius: 20 },
      { id: 'n2', name: 'Node 2', type: 'file', repo: 'r1', x: 500, y: 400, vx: 0, vy: 0, radius: 20 },
    ];
    const customEdges = [{ source: 'n1', target: 'n2', type: 'IMPORTS' }];
    const posMap = new Map([
      ['n1', { x: 100, y: 80, radius: 20 }],
      ['n2', { x: 500, y: 400, radius: 20 }],
    ]);

    const { container } = render(
      <TopologyMinimap
        visibleNodes={customNodes}
        visibleEdges={customEdges}
        nodePosMap={posMap}
      />
    );

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('viewBox')).toBe('60 40 480 400');
  });
});
