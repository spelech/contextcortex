import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { TopologyControls, ARCHITECTURE_PRESET_OPTIONS } from '../components/topology/TopologyControls';
import type { TopologyControlsProps } from '../components/topology/TopologyControls';
import type { Repo, TopologyNode } from '../types';

const mockRepos: Repo[] = [
  { id: 1, name: 'repo-core', url: 'https://github.com/org/repo-core.git', branch: 'main', status: 'synced' },
  { id: 2, name: 'repo-web', url: 'https://github.com/org/repo-web.git', branch: 'main', status: 'synced' },
];

const mockSearchMatches: TopologyNode[] = [
  { id: 'file:repo-core:main.py', name: 'main.py', type: 'file', repo: 'repo-core', filepath: 'main.py' },
  { id: 'route:1', name: 'GET /api/v1/health', type: 'route', repo: 'repo-core', filepath: 'main.py' },
];

function createDefaultProps(overrides?: Partial<TopologyControlsProps>): TopologyControlsProps {
  return {
    repos: mockRepos,
    selectedRepo: 'repo-core',
    setSelectedRepo: vi.fn(),
    viewMode: 'canvas',
    setViewMode: vi.fn(),
    hopRadius: 1,
    setHopRadius: vi.fn(),
    depth: 2,
    setDepth: vi.fn(),
    nodeLimit: 150,
    setNodeLimit: vi.fn(),
    typeFilters: { file: true, class: true, function: true, route: true },
    setTypeFilters: vi.fn(),
    activePreset: 'full',
    onSelectPreset: vi.fn(),
    nodeCounts: undefined,
    hideOrphans: false,
    setHideOrphans: vi.fn(),
    rootNode: '',
    setRootNode: vi.fn(),
    searchQuery: '',
    setSearchQuery: vi.fn(),
    searchMatches: [],
    onFocusNode: vi.fn(),
    onAutoFit: vi.fn(),
    onExportSVG: vi.fn(),
    onExportJSON: vi.fn(),
    onTogglePhysics: vi.fn(),
    isPhysicsOpen: false,
    ...overrides,
  };
}

describe('TopologyControls Component', () => {
  it('exports ARCHITECTURE_PRESET_OPTIONS with 4 predefined presets', () => {
    expect(ARCHITECTURE_PRESET_OPTIONS).toHaveLength(4);
    const ids = ARCHITECTURE_PRESET_OPTIONS.map((p) => p.id);
    expect(ids).toEqual(['files', 'architecture', 'api', 'full']);
  });

  it('renders all 4 architectural presets in the toolbar', () => {
    const props = createDefaultProps({ activePreset: 'architecture' });
    render(<TopologyControls {...props} />);

    expect(screen.getByRole('group', { name: /Architectural Presets/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Files Only/i })).toBeInTheDocument();
    const archBtn = screen.getByRole('button', { name: /Architecture/i });
    expect(archBtn).toBeInTheDocument();
    expect(archBtn).toHaveClass('active');
    expect(screen.getByRole('button', { name: /API Surface/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Full Codebase/i })).toBeInTheDocument();
  });

  it('clicking a preset triggers onSelectPreset with the correct preset key', () => {
    const onSelectPreset = vi.fn();
    const props = createDefaultProps({ onSelectPreset, activePreset: 'files' });
    render(<TopologyControls {...props} />);

    const apiBtn = screen.getByRole('button', { name: /API Surface/i });
    fireEvent.click(apiBtn);
    expect(onSelectPreset).toHaveBeenCalledWith('api');

    const fullBtn = screen.getByRole('button', { name: /Full Codebase/i });
    fireEvent.click(fullBtn);
    expect(onSelectPreset).toHaveBeenCalledWith('full');

    const archBtn = screen.getByRole('button', { name: /Architecture/i });
    fireEvent.click(archBtn);
    expect(onSelectPreset).toHaveBeenCalledWith('architecture');

    const filesBtn = screen.getByRole('button', { name: /Files Only/i });
    fireEvent.click(filesBtn);
    expect(onSelectPreset).toHaveBeenCalledWith('files');
  });

  it('renders filter chips with live node counts when nodeCounts is provided', () => {
    const nodeCounts = { file: 42, class: 12, function: 88, route: 7 };
    const props = createDefaultProps({ nodeCounts });
    render(<TopologyControls {...props} />);

    expect(screen.getByText('FILE (42)')).toBeInTheDocument();
    expect(screen.getByText('CLASS (12)')).toBeInTheDocument();
    expect(screen.getByText('FUNCTION (88)')).toBeInTheDocument();
    expect(screen.getByText('ROUTE (7)')).toBeInTheDocument();
  });

  it('renders filter chips without count badges when nodeCounts is not provided', () => {
    const props = createDefaultProps({ nodeCounts: undefined });
    render(<TopologyControls {...props} />);

    expect(screen.getByText('FILE')).toBeInTheDocument();
    expect(screen.getByText('CLASS')).toBeInTheDocument();
    expect(screen.getByText('FUNCTION')).toBeInTheDocument();
    expect(screen.getByText('ROUTE')).toBeInTheDocument();
  });

  it('toggles filter chips and triggers setTypeFilters updater', () => {
    const setTypeFilters = vi.fn();
    const props = createDefaultProps({ setTypeFilters });
    render(<TopologyControls {...props} />);

    const fileChip = screen.getByTitle('Toggle file nodes');
    fireEvent.click(fileChip);

    expect(setTypeFilters).toHaveBeenCalledTimes(1);
    const updater = setTypeFilters.mock.calls[0][0];
    expect(typeof updater).toBe('function');
    const updated = updater({ file: true, class: true });
    expect(updated.file).toBe(false);
  });

  it('renders Physics button and triggers onTogglePhysics when in canvas mode', () => {
    const onTogglePhysics = vi.fn();
    const props = createDefaultProps({
      viewMode: 'canvas',
      onTogglePhysics,
      isPhysicsOpen: false,
    });
    render(<TopologyControls {...props} />);

    const physicsBtn = screen.getByTitle('Layout & Physics Settings');
    expect(physicsBtn).toBeInTheDocument();
    expect(physicsBtn).not.toHaveClass('active');

    fireEvent.click(physicsBtn);
    expect(onTogglePhysics).toHaveBeenCalledTimes(1);
  });

  it('adds active class to Physics button when isPhysicsOpen is true', () => {
    const props = createDefaultProps({
      viewMode: 'canvas',
      onTogglePhysics: vi.fn(),
      isPhysicsOpen: true,
    });
    render(<TopologyControls {...props} />);

    const physicsBtn = screen.getByTitle('Layout & Physics Settings');
    expect(physicsBtn).toHaveClass('active');
  });

  it('renders canvas-specific controls in canvas mode (depth, nodeLimit, hideOrphans, autoFit)', () => {
    const onAutoFit = vi.fn();
    const setHideOrphans = vi.fn();
    const setDepth = vi.fn();
    const setNodeLimit = vi.fn();

    const props = createDefaultProps({
      viewMode: 'canvas',
      onAutoFit,
      setHideOrphans,
      setDepth,
      setNodeLimit,
      depth: 3,
      nodeLimit: 200,
    });
    render(<TopologyControls {...props} />);

    expect(screen.getByRole('combobox', { name: /Graph Depth/i })).toHaveValue('3');
    expect(screen.getByRole('combobox', { name: /Node Limit/i })).toHaveValue('200');

    const depthSelect = screen.getByRole('combobox', { name: /Graph Depth/i });
    fireEvent.change(depthSelect, { target: { value: '4' } });
    expect(setDepth).toHaveBeenCalledWith(4);

    const nodeLimitSelect = screen.getByRole('combobox', { name: /Node Limit/i });
    fireEvent.change(nodeLimitSelect, { target: { value: '400' } });
    expect(setNodeLimit).toHaveBeenCalledWith(400);

    const hideOrphansChip = screen.getByTitle('Toggle orphan nodes');
    fireEvent.click(hideOrphansChip);
    expect(setHideOrphans).toHaveBeenCalledTimes(1);

    const fitBtn = screen.getByTitle('Fit Graph');
    fireEvent.click(fitBtn);
    expect(onAutoFit).toHaveBeenCalledTimes(1);
  });

  it('renders neighborhood-specific controls in neighborhood mode (hopRadius toggle)', () => {
    const setHopRadius = vi.fn();
    const props = createDefaultProps({
      viewMode: 'neighborhood',
      hopRadius: 1,
      setHopRadius,
    });
    render(<TopologyControls {...props} />);

    expect(screen.getByRole('group', { name: /Hop Radius/i })).toBeInTheDocument();
    const twoHopBtn = screen.getByRole('button', { name: '2-Hop' });
    fireEvent.click(twoHopBtn);
    expect(setHopRadius).toHaveBeenCalledWith(2);

    expect(screen.queryByRole('combobox', { name: /Graph Depth/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /Node Limit/i })).not.toBeInTheDocument();
    expect(screen.queryByTitle('Toggle orphan nodes')).not.toBeInTheDocument();
  });

  it('handles switching viewMode between neighborhood and canvas', () => {
    const setViewMode = vi.fn();
    const props = createDefaultProps({
      viewMode: 'neighborhood',
      setViewMode,
    });
    render(<TopologyControls {...props} />);

    const canvasModeBtn = screen.getByRole('button', { name: /Global 2D Canvas/i });
    fireEvent.click(canvasModeBtn);
    expect(setViewMode).toHaveBeenCalledWith('canvas');

    const neighborhoodModeBtn = screen.getByRole('button', { name: /Neighborhood View/i });
    fireEvent.click(neighborhoodModeBtn);
    expect(setViewMode).toHaveBeenCalledWith('neighborhood');
  });

  it('handles repository selection change', () => {
    const setSelectedRepo = vi.fn();
    const props = createDefaultProps({ setSelectedRepo });
    render(<TopologyControls {...props} />);

    const repoSelect = screen.getByRole('combobox', { name: /Select Repository/i });
    fireEvent.change(repoSelect, { target: { value: '__all__' } });
    expect(setSelectedRepo).toHaveBeenCalledWith('__all__');
  });

  it('renders root node indicator and allows clearing root focus', () => {
    const setRootNode = vi.fn();
    const props = createDefaultProps({ rootNode: 'main.py', setRootNode });
    render(<TopologyControls {...props} />);

    expect(screen.getByText(/Root: main.py/i)).toBeInTheDocument();
    const clearBtn = screen.getByTitle('Clear Root Focus');
    fireEvent.click(clearBtn);
    expect(setRootNode).toHaveBeenCalledWith('');
  });

  it('handles search input, autocomplete list, and node focusing', () => {
    const setSearchQuery = vi.fn();
    const onFocusNode = vi.fn();
    const props = createDefaultProps({
      searchQuery: 'main',
      setSearchQuery,
      searchMatches: mockSearchMatches,
      onFocusNode,
    });
    render(<TopologyControls {...props} />);

    const searchInput = screen.getByRole('textbox', { name: /Search nodes/i });
    fireEvent.change(searchInput, { target: { value: 'health' } });
    expect(setSearchQuery).toHaveBeenCalledWith('health');

    fireEvent.focus(searchInput);

    const matchItem = screen.getByText('GET /api/v1/health');
    fireEvent.click(matchItem);
    expect(onFocusNode).toHaveBeenCalledWith('route:1');
  });

  it('triggers SVG and JSON export callbacks', () => {
    const onExportSVG = vi.fn();
    const onExportJSON = vi.fn();
    const props = createDefaultProps({ onExportSVG, onExportJSON });
    render(<TopologyControls {...props} />);

    const svgBtn = screen.getByTitle('Export as SVG');
    fireEvent.click(svgBtn);
    expect(onExportSVG).toHaveBeenCalledTimes(1);

    const jsonBtn = screen.getByTitle('Export as JSON');
    fireEvent.click(jsonBtn);
    expect(onExportJSON).toHaveBeenCalledTimes(1);
  });

  it('falls back to legacy viewType buttons when onSelectPreset is not provided', () => {
    const setViewType = vi.fn();
    const legacyProps: any = {
      repos: mockRepos,
      selectedRepo: 'repo-core',
      setSelectedRepo: vi.fn(),
      viewMode: 'canvas',
      setViewMode: vi.fn(),
      viewType: 'symbols',
      setViewType,
      depth: 2,
      setDepth: vi.fn(),
      nodeLimit: 150,
      setNodeLimit: vi.fn(),
      hideOrphans: false,
      setHideOrphans: vi.fn(),
      rootNode: '',
      setRootNode: vi.fn(),
      searchQuery: '',
      setSearchQuery: vi.fn(),
      searchMatches: [],
      onFocusNode: vi.fn(),
      typeFilters: {},
      setTypeFilters: vi.fn(),
      onExportSVG: vi.fn(),
      onExportJSON: vi.fn(),
    };

    render(<TopologyControls {...legacyProps} />);

    expect(screen.getByRole('group', { name: /View Type/i })).toBeInTheDocument();
    const symbolsBtn = screen.getByRole('button', { name: 'SYMBOLS' });
    expect(symbolsBtn).toHaveClass('active');

    const routesBtn = screen.getByRole('button', { name: 'ROUTES' });
    fireEvent.click(routesBtn);
    expect(setViewType).toHaveBeenCalledWith('routes');
  });
});
