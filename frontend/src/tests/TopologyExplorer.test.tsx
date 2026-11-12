import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import TopologyExplorer, { findInitialFocalNode, computeInitialLayout } from '../TopologyExplorer';
import { TopologyMinimap } from '../components/topology/TopologyMinimap';
import type { SimNode } from '../components/topology/types';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { installTopologyCanvasAndFetchMocks, type CanvasTestHarness } from './fixtures/topologyFixtures';

describe('TopologyExplorer Component', () => {
  let harness: CanvasTestHarness;

  beforeEach(() => {
    harness = installTopologyCanvasAndFetchMocks();
  });

  afterEach(() => {
    harness.cleanup();
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
});
