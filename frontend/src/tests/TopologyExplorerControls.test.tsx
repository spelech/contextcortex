import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import TopologyExplorer, { findMatchingPreset } from '../TopologyExplorer';
import { ToastProvider } from '../ToastContext';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { STORAGE_KEY_PHYSICS, DEFAULT_PHYSICS_CONFIG, PHYSICS_PRESETS } from '../components/topology/physicsPresets';
import {
  installTopologyCanvasAndFetchMocks,
  mockTopologyRepos,
  type CanvasTestHarness,
} from './fixtures/topologyFixtures';

describe('TopologyExplorer Controls, Presets & Filters', () => {
  let harness: CanvasTestHarness;

  beforeEach(() => {
    harness = installTopologyCanvasAndFetchMocks();
  });

  afterEach(() => {
    harness.cleanup();
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

    // Node counts for mock payload: 2 files, 1 function, 1 route, 0 class
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
        return Promise.resolve({ ok: true, json: async () => mockTopologyRepos } as Response);
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

  it('findMatchingPreset identifies exact matching presets or returns null for custom configurations', () => {
    expect(findMatchingPreset({ file: true, class: false, function: false, route: false, module: false })).toBe('files');
    expect(findMatchingPreset({ file: true, class: true, function: false, route: false, module: true })).toBe('architecture');
    expect(findMatchingPreset({ file: true, class: false, function: true, route: true, module: false })).toBe('api');
    expect(findMatchingPreset({ file: true, class: true, function: true, route: true, module: true })).toBe('full');
    expect(findMatchingPreset({ file: true, class: true, function: true, route: false, module: false })).toBeNull();
  });
});
