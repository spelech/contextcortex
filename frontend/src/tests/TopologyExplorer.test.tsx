import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import TopologyExplorer, { findInitialFocalNode, computeInitialLayout, findMatchingPreset } from '../TopologyExplorer';
import { TopologyMinimap } from '../components/topology/TopologyMinimap';
import type { SimNode } from '../components/topology/types';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { STORAGE_KEY_PHYSICS, DEFAULT_PHYSICS_CONFIG, PHYSICS_PRESETS } from '../components/topology/physicsPresets';

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
    localStorage.clear();

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

  it('renders toolbar, repository selector, view mode switcher, architectural presets, and default neighborhood view', async () => {
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

    // Architectural Presets Toggle
    expect(screen.getByRole('group', { name: /Architectural Presets/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Files Only/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Architecture/i })).toHaveClass('active');
    expect(screen.getByRole('button', { name: /API Surface/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Full Codebase/i })).toBeInTheDocument();

    // Default Neighborhood View should load focal node and breadcrumbs
    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('Incoming Dependencies')).toBeInTheDocument();
    expect(screen.getByText('Outgoing Dependencies')).toBeInTheDocument();
  });

  it('handles switching architectural presets and queries topology with dynamic view_type', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });

    const filesBtn = screen.getByRole('button', { name: /Files Only/i });
    const apiBtn = screen.getByRole('button', { name: /API Surface/i });
    const fullBtn = screen.getByRole('button', { name: /Full Codebase/i });

    // Click API Surface preset (requires both symbols and routes -> view_type=full)
    await act(async () => {
      fireEvent.click(apiBtn);
    });

    await waitFor(() => {
      expect(apiBtn).toHaveClass('active');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('view_type=full')
      );
    });

    // Click Files Only preset
    await act(async () => {
      fireEvent.click(filesBtn);
    });

    await waitFor(() => {
      expect(filesBtn).toHaveClass('active');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('view_type=files')
      );
    });

    // Custom toggle only ROUTE on (file: false, class: false, function: false, route: true) -> view_type=routes
    const fileChip = screen.getByTitle('Toggle file nodes');
    const routeChip = screen.getByTitle('Toggle route nodes');
    await act(async () => {
      fireEvent.click(fileChip); // turns file off
      fireEvent.click(routeChip); // turns route on
    });

    await waitFor(() => {
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('view_type=routes')
      );
    });

    // Click Full Codebase preset
    await act(async () => {
      fireEvent.click(fullBtn);
    });

    await waitFor(() => {
      expect(fullBtn).toHaveClass('active');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('view_type=full')
      );
    });
  });

  it('displays live node counts next to filter chips', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });

    // Node counts for mock data: 2 files, 1 function, 1 route, 0 class
    expect(screen.getByText('FILE (2)')).toBeInTheDocument();
    expect(screen.getByText('CLASS (0)')).toBeInTheDocument();
    expect(screen.getByText('FUNCTION (1)')).toBeInTheDocument();
    expect(screen.getByText('ROUTE (1)')).toBeInTheDocument();
  });

  it('toggles individual filter chips and updates activePreset accordingly', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('main.py').length).toBeGreaterThanOrEqual(1);
    });

    const fileChip = screen.getByTitle('Toggle file nodes');
    const archPresetBtn = screen.getByRole('button', { name: /Architecture/i });
    expect(archPresetBtn).toHaveClass('active');

    // Toggling file node off creates custom filter state -> preset should be inactive
    await act(async () => {
      fireEvent.click(fileChip);
    });

    expect(fileChip).toHaveClass('inactive');
    expect(archPresetBtn).not.toHaveClass('active');

    // Toggling file node back on restores exact Architecture preset
    await act(async () => {
      fireEvent.click(fileChip);
    });

    expect(fileChip).not.toHaveClass('inactive');
    expect(archPresetBtn).toHaveClass('active');
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
    await act(async () => {
      fireEvent.click(canvasModeBtn);
    });

    await waitFor(() => {
      expect(canvasModeBtn).toHaveClass('active');
      expect(neighborhoodModeBtn).not.toHaveClass('active');
      expect(screen.getByTestId('topology-2d-canvas')).toBeInTheDocument();
    });

    // In canvas mode, Node Limit, Hide Orphans, and Physics button should be present
    expect(screen.getByRole('combobox', { name: /Node Limit/i })).toBeInTheDocument();
    expect(screen.getByTitle('Toggle orphan nodes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Physics/i })).toBeInTheDocument();

    // Switch back to Neighborhood view
    await act(async () => {
      fireEvent.click(neighborhoodModeBtn);
    });

    await waitFor(() => {
      expect(neighborhoodModeBtn).toHaveClass('active');
      expect(screen.queryByTestId('topology-2d-canvas')).not.toBeInTheDocument();
      expect(screen.getByText('Incoming Dependencies')).toBeInTheDocument();
    });
  });

  it('opens and closes physics controls popover in 2d canvas mode and handles preset selection & localStorage persistence', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    // Switch to canvas mode
    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    await act(async () => {
      fireEvent.click(canvasModeBtn);
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Physics/i })).toBeInTheDocument();
    });

    // Physics panel not open yet
    expect(screen.queryByRole('region', { name: /Simulation Physics Controls/i })).not.toBeInTheDocument();

    // Open physics panel
    const physicsToggleBtn = screen.getByRole('button', { name: /Physics/i });
    await act(async () => {
      fireEvent.click(physicsToggleBtn);
    });

    expect(screen.getByRole('region', { name: /Simulation Physics Controls/i })).toBeInTheDocument();

    // Presets in physics popover
    const spaciousBtn = screen.getByRole('button', { name: /Spacious Tree/i });
    expect(spaciousBtn).toBeInTheDocument();

    // Click Spacious Tree preset
    await act(async () => {
      fireEvent.click(spaciousBtn);
    });

    expect(spaciousBtn).toHaveClass('active');

    // Stored in localStorage
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY_PHYSICS) || '{}');
    expect(saved.kRepulse).toBe(PHYSICS_PRESETS.spacious.kRepulse);
    expect(saved.springLength).toBe(PHYSICS_PRESETS.spacious.springLength);

    // Adjust a slider
    const repulseSlider = screen.getByRole('slider', { name: /Repulsion Force/i });
    await act(async () => {
      fireEvent.change(repulseSlider, { target: { value: '45000' } });
    });

    const updatedStored = JSON.parse(localStorage.getItem(STORAGE_KEY_PHYSICS) || '{}');
    expect(updatedStored.kRepulse).toBe(45000);

    // Click Re-Relax Layout
    const reRelaxBtn = screen.getByRole('button', { name: /Re-Relax Layout/i });
    await act(async () => {
      fireEvent.click(reRelaxBtn);
    });

    // Click Reset Defaults
    const resetBtn = screen.getByRole('button', { name: /Reset Defaults/i });
    await act(async () => {
      fireEvent.click(resetBtn);
    });

    const resetStored = JSON.parse(localStorage.getItem(STORAGE_KEY_PHYSICS) || '{}');
    expect(resetStored.kRepulse).toBe(DEFAULT_PHYSICS_CONFIG.kRepulse);

    // Close physics panel
    const closeBtn = screen.getByRole('button', { name: /Close Physics Controls/i });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(screen.queryByRole('region', { name: /Simulation Physics Controls/i })).not.toBeInTheDocument();
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
    await act(async () => {
      fireEvent.click(focusUtilsBtn!);
    });

    // Breadcrumb trail should now contain utils.py as active
    await waitFor(() => {
      expect(screen.getByTitle('Navigate to utils.py')).toBeInTheDocument();
    });

    // Click back to main.py breadcrumb
    const mainBreadcrumb = screen.getByTitle('Navigate to main.py');
    await act(async () => {
      fireEvent.click(mainBreadcrumb);
    });

    await waitFor(() => {
      expect(screen.getByTitle('Navigate to main.py')).toHaveClass('active');
      expect(screen.queryByTitle('Navigate to utils.py')).not.toBeInTheDocument();
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
    await act(async () => {
      fireEvent.click(canvasModeBtn);
    });

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /repo-core/i })).toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: /Graph Depth/i })).toBeInTheDocument();
    });

    const repoSelect = screen.getByRole('combobox', { name: /Select Repository/i });
    await act(async () => {
      fireEvent.change(repoSelect, { target: { value: 'repo-core' } });
    });

    const depthSelect = screen.getByRole('combobox', { name: /Graph Depth/i });
    await act(async () => {
      fireEvent.change(depthSelect, { target: { value: '3' } });
    });

    await waitFor(() => {
      expect(repoSelect).toHaveValue('repo-core');
      expect(depthSelect).toHaveValue('3');
    });
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
    await act(async () => {
      fireEvent.click(inspectBtn!);
    });

    await waitFor(() => {
      expect(screen.getByText(/Location & Repository/i)).toBeInTheDocument();
      expect(screen.getByText(/def handle_request/i)).toBeInTheDocument();
      expect(screen.getByText(/Incoming Connections/i)).toBeInTheDocument();
      expect(screen.getByText(/Outgoing Connections/i)).toBeInTheDocument();
      expect(screen.getByText(/Open in Git Provider/i)).toBeInTheDocument();
    });

    // Close drawer
    const closeBtn = screen.getByRole('button', { name: /Close Inspector/i });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

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
    await act(async () => {
      fireEvent.focus(searchInput);
      fireEvent.change(searchInput, { target: { value: 'handle' } });
    });

    await waitFor(() => {
      const matchItems = screen.getAllByText(/handle_request/i);
      expect(matchItems.length).toBeGreaterThanOrEqual(1);
    });

    // Click search match item
    const matchItem = screen.getAllByText(/handle_request/i)[0];
    await act(async () => {
      fireEvent.click(matchItem);
    });

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

    await act(async () => {
      fireEvent.click(svgBtn);
      fireEvent.click(jsonBtn);
    });
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
    await act(async () => {
      fireEvent.click(canvasModeBtn);
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /Node Limit/i })).toBeInTheDocument();
    });

    const limitSelect = screen.getByRole('combobox', { name: /Node Limit/i });
    expect(limitSelect).toHaveValue('150');

    await act(async () => {
      fireEvent.change(limitSelect, { target: { value: '50' } });
    });

    await waitFor(() => {
      expect(limitSelect).toHaveValue('50');
      expect((globalThis as any).fetch).toHaveBeenCalledWith(
        expect.stringContaining('limit=50')
      );
    });

    await act(async () => {
      fireEvent.change(limitSelect, { target: { value: '400' } });
    });

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
    await act(async () => {
      fireEvent.click(canvasModeBtn);
    });

    await waitFor(() => {
      expect(screen.getByTitle('Toggle orphan nodes')).toBeInTheDocument();
    });

    const hideOrphansChip = screen.getByTitle('Toggle orphan nodes');
    expect(hideOrphansChip).toHaveClass('inactive');

    // Click to activate hide orphans
    await act(async () => {
      fireEvent.click(hideOrphansChip);
    });
    expect(hideOrphansChip).not.toHaveClass('inactive');

    // Click again to deactivate hide orphans
    await act(async () => {
      fireEvent.click(hideOrphansChip);
    });
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

  it('findInitialFocalNode prioritizes entrypoints and non-test hub files over test files', () => {
    const nodes = [
      { id: 'test-1', name: 'test_auth.py', type: 'file', filepath: 'tests/test_auth.py', repo: 'repo-core' },
      { id: 'test-2', name: 'test_api.py', type: 'file', filepath: 'tests/test_api.py', repo: 'repo-core' },
      { id: 'helper-1', name: 'helpers.py', type: 'file', filepath: 'src/helpers.py', repo: 'repo-core' },
      { id: 'entry-1', name: 'main.py', type: 'file', filepath: 'src/main.py', repo: 'repo-core' },
    ];
    const edges = [
      { source: 'entry-1', target: 'helper-1', type: 'IMPORTS' },
      { source: 'test-1', target: 'entry-1', type: 'CALLS' },
      { source: 'test-2', target: 'entry-1', type: 'CALLS' },
    ];

    // Even though test_auth.py is index 0, main.py is recognized as primary entrypoint
    const focal = findInitialFocalNode(nodes, edges);
    expect(focal?.id).toBe('entry-1');
    expect(focal?.name).toBe('main.py');

    // If explicit root node query provided, matches that node
    const focalRoot = findInitialFocalNode(nodes, edges, 'helpers.py');
    expect(focalRoot?.id).toBe('helper-1');
  });

  it('computeInitialLayout scales layout bounds dynamically for generous spacing', () => {
    const nodes = Array.from({ length: 50 }, (_, i) => ({
      id: `node-${i}`,
      name: `Node${i}.ts`,
      type: 'file',
      filepath: `src/node-${i}.ts`,
      repo: 'repo-core',
    }));
    const edges = Array.from({ length: 40 }, (_, i) => ({
      source: `node-${i}`,
      target: `node-${i + 1}`,
      type: 'IMPORTS',
    }));

    const simNodes = computeInitialLayout(nodes, edges, 20);
    expect(simNodes.length).toBe(50);
    expect(simNodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);

    // Compute bounding box spread
    const xs = simNodes.map((n) => n.x);
    const ys = simNodes.map((n) => n.y);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);

    // Layout should have a wide spread across canvas rather than being squished into a tight cluster
    expect(spanX).toBeGreaterThan(400);
    expect(spanY).toBeGreaterThan(300);
  });

  it('findMatchingPreset identifies exact matching presets or returns null for custom configurations', () => {
    expect(findMatchingPreset({ file: true, class: false, function: false, route: false, module: false })).toBe('files');
    expect(findMatchingPreset({ file: true, class: true, function: false, route: false, module: true })).toBe('architecture');
    expect(findMatchingPreset({ file: true, class: false, function: true, route: true, module: false })).toBe('api');
    expect(findMatchingPreset({ file: true, class: true, function: true, route: true, module: true })).toBe('full');
    expect(findMatchingPreset({ file: true, class: true, function: true, route: false, module: false })).toBeNull();
  });
});
