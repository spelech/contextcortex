import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TopologyExplorer from '../TopologyExplorer';
import { TopologyMinimap } from '../components/topology/TopologyMinimap';
import type { SimNode } from '../components/topology/types';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockRepos = [
  { id: 1, name: 'repo-core', url: 'https://github.com/org/repo-core.git', branch: 'main', status: 'synced' },
  { id: 2, name: 'repo-web', url: 'https://github.com/org/repo-web.git', branch: 'main', status: 'synced' }
];

const mockTopologyData = {
  nodes: [
    { id: 'file:repo-core:app/main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'app/main.py' },
    { id: 'file:repo-core:app/utils.py', name: 'utils.py', type: 'file', repo: 'repo-core', filepath: 'app/utils.py' },
    { id: 'symbol:1', name: 'handle_request', type: 'function', repo: 'repo-core', filepath: 'app/main.py', start_line: 10, end_line: 25 },
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', repo: 'repo-core', filepath: 'app/main.py', method: 'GET', path_pattern: '/api/v1/status' }
  ],
  edges: [
    { source: 'file:repo-core:app/main.py', target: 'file:repo-core:app/utils.py', type: 'IMPORTS' },
    { source: 'file:repo-core:app/main.py', target: 'symbol:1', type: 'DEFINES' },
    { source: 'route:1', target: 'symbol:1', type: 'HANDLES' }
  ],
  stats: { node_count: 4, edge_count: 3 }
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
    { id: 'route:1', name: 'GET /api/v1/status', type: 'route', edge_type: 'HANDLES', line_number: 10 }
  ],
  outgoing: [
    { id: 'symbol:2', name: 'format_response', type: 'function', edge_type: 'CALLS', line_number: 18 }
  ],
  metadata: { kind: 'function', language: 'python' }
};

describe('TopologyExplorer Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/admin/api/repos')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockRepos
        } as Response);
      }
      if (url.includes('/admin/api/graph/topology')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockTopologyData
        } as Response);
      }
      if (url.includes('/admin/api/graph/node-details')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockNodeDetails
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({})
      } as Response);
    });
  });

  it('renders toolbar, repository selector, view type toggles, and graph canvas', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    expect(screen.getByRole('group', { name: /View Type/i })).toBeInTheDocument();
    expect(screen.getByText('FILES')).toBeInTheDocument();
    expect(screen.getByText('SYMBOLS')).toBeInTheDocument();
    expect(screen.getByText('ROUTES')).toBeInTheDocument();
    expect(screen.getByText('FULL')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('main.py')).toBeInTheDocument();
      expect(screen.getByText('utils.py')).toBeInTheDocument();
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

  it('handles changing repository selection and depth', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /repo-core/i })).toBeInTheDocument();
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

  it('opens slide-over inspector drawer on node click and renders details', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Node handle_request' })).toBeInTheDocument();
    });

    // Click on node
    const nodeBtn = screen.getByRole('button', { name: 'Node handle_request' });
    fireEvent.click(nodeBtn);

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
      expect(screen.getByRole('button', { name: 'Node handle_request' })).toBeInTheDocument();
    });

    const searchInput = screen.getByRole('textbox', { name: /Search nodes/i });
    fireEvent.focus(searchInput);
    fireEvent.change(searchInput, { target: { value: 'handle' } });

    await waitFor(() => {
      const matchItems = screen.getAllByText(/handle_request/i);
      expect(matchItems.length).toBeGreaterThanOrEqual(1);
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
          json: async () => ({ error: 'Repository index not found' })
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
      expect(screen.getByText(/No graph nodes found/i)).toBeInTheDocument();
    });
  });

  it('renders DOC_LINKS_TO edge badge in legend and allows toggling', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByTitle('Toggle DOC_LINKS_TO edges')).toBeInTheDocument();
    });

    const docLinkChip = screen.getByTitle('Toggle DOC_LINKS_TO edges');
    expect(docLinkChip).not.toHaveClass('inactive');
    expect(docLinkChip).toHaveTextContent('DOC_LINKS_TO');

    fireEvent.click(docLinkChip);
    expect(docLinkChip).toHaveClass('inactive');

    fireEvent.click(docLinkChip);
    expect(docLinkChip).not.toHaveClass('inactive');
  });

  it('handles dragging a node with SVG viewBox coordinate scaling', async () => {
    // Mock getBoundingClientRect on SVGSVGElement to simulate a 500x320 element (scaling factor 2x relative to 1000x640 viewBox)
    vi.spyOn(SVGSVGElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      top: 50,
      width: 500,
      height: 320,
      right: 600,
      bottom: 370,
      x: 100,
      y: 50,
      toJSON: () => {}
    });

    const { container } = render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('node-symbol:1')).toBeInTheDocument();
    });

    const node = screen.getByTestId('node-symbol:1');
    const canvasWrapper = container.querySelector('.topology-canvas-wrapper');
    expect(canvasWrapper).not.toBeNull();

    // Start drag on node
    fireEvent.mouseDown(node);

    // Move to screen position (200, 150)
    // svgX = (200 - 100) * (1000 / 500) = 200
    // svgY = (150 - 50) * (640 / 320) = 200
    fireEvent.mouseMove(canvasWrapper!, { clientX: 200, clientY: 150 });

    // Verify node position has been updated to 200, 200
    expect(node).toHaveAttribute('transform', 'translate(200, 200)');

    fireEvent.mouseUp(canvasWrapper!);
  });

  it('handles canvas background panning on wrapper', async () => {
    const { container } = render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('node-symbol:1')).toBeInTheDocument();
    });

    const canvasWrapper = container.querySelector('.topology-canvas-wrapper');
    const svg = container.querySelector('.topology-svg');
    expect(canvasWrapper).not.toBeNull();
    expect(svg).not.toBeNull();

    // The root <g> inside <svg> contains the transform
    const mainGroup = svg!.querySelector('g');
    expect(mainGroup).toHaveAttribute('transform', 'translate(0, 0) scale(1)');

    // Mouse down on wrapper to start panning
    fireEvent.mouseDown(canvasWrapper!, { clientX: 100, clientY: 100 });
    fireEvent.mouseMove(canvasWrapper!, { clientX: 160, clientY: 140 });

    // Pan should be (60, 40)
    expect(mainGroup).toHaveAttribute('transform', 'translate(60, 40) scale(1)');

    fireEvent.mouseUp(canvasWrapper!);
  });

  it('triggers Fit to View auto-fit calculation and updates canvas transform', async () => {
    const { container } = render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByTitle('Fit to View')).toBeInTheDocument();
    });

    const fitBtn = screen.getByTitle('Fit to View');
    fireEvent.click(fitBtn);

    const svg = container.querySelector('.topology-svg');
    const mainGroup = svg!.querySelector('g');
    // Transform should have updated zoom & pan based on bounding box
    expect(mainGroup?.getAttribute('transform')).toMatch(/translate\([^,]+,\s*[^)]+\)\s+scale\([^)]+\)/);

    // Test Reset View
    const resetBtn = screen.getByTitle('Reset View');
    fireEvent.click(resetBtn);
    expect(mainGroup).toHaveAttribute('transform', 'translate(0, 0) scale(1)');
  });

  it('handles changing node limit in toolbar and queries topology with limit parameter', async () => {
    render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

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

  it('toggles hide orphans to filter disconnected nodes', async () => {
    const topologyWithOrphan = {
      nodes: [
        { id: 'file:repo-core:app/main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'app/main.py' },
        { id: 'file:repo-core:app/utils.py', name: 'utils.py', type: 'file', repo: 'repo-core', filepath: 'app/utils.py' },
        { id: 'file:repo-core:app/orphan.py', name: 'orphan.py', type: 'file', repo: 'repo-core', filepath: 'app/orphan.py' }
      ],
      edges: [
        { source: 'file:repo-core:app/main.py', target: 'file:repo-core:app/utils.py', type: 'IMPORTS' }
      ],
      stats: { node_count: 3, edge_count: 1 }
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

    await waitFor(() => {
      expect(screen.getByText('orphan.py')).toBeInTheDocument();
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    const hideOrphansChip = screen.getByTitle('Toggle orphan nodes');
    expect(hideOrphansChip).toHaveClass('inactive');

    // Click to activate hide orphans
    fireEvent.click(hideOrphansChip);
    expect(hideOrphansChip).not.toHaveClass('inactive');

    await waitFor(() => {
      expect(screen.queryByText('orphan.py')).not.toBeInTheDocument();
      expect(screen.getByText('main.py')).toBeInTheDocument();
    });

    // Click again to deactivate hide orphans
    fireEvent.click(hideOrphansChip);
    expect(hideOrphansChip).toHaveClass('inactive');

    await waitFor(() => {
      expect(screen.getByText('orphan.py')).toBeInTheDocument();
    });
  });

  it('renders TopologyMinimap with dynamic bounding box viewBox', () => {
    const customNodes: SimNode[] = [
      { id: 'n1', name: 'Node 1', type: 'file', repo: 'r1', x: 100, y: 80, vx: 0, vy: 0, radius: 20 },
      { id: 'n2', name: 'Node 2', type: 'file', repo: 'r1', x: 500, y: 400, vx: 0, vy: 0, radius: 20 }
    ];
    const customEdges = [{ source: 'n1', target: 'n2', type: 'IMPORTS' }];
    const posMap = new Map([
      ['n1', { x: 100, y: 80, radius: 20 }],
      ['n2', { x: 500, y: 400, radius: 20 }]
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
    // minX: 100 - 40 = 60, maxX: 500 + 40 = 540 => width = 480
    // minY: 80 - 40 = 40, maxY: 400 + 40 = 440 => height = 400
    expect(svg?.getAttribute('viewBox')).toBe('60 40 480 400');
  });

  it('triggers toolbar Fit Graph button and updates canvas transform', async () => {
    const { container } = render(
      <ToastProvider>
        <TopologyExplorer />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByTitle('Fit Graph')).toBeInTheDocument();
    });

    const toolbarFitBtn = screen.getByTitle('Fit Graph');
    fireEvent.click(toolbarFitBtn);

    const svg = container.querySelector('.topology-svg');
    const mainGroup = svg!.querySelector('g');
    expect(mainGroup?.getAttribute('transform')).toMatch(/translate\([^,]+,\s*[^)]+\)\s+scale\([^)]+\)/);
  });
});
