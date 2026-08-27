# HTML5 2D Canvas & Focused Neighborhood Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two high-performance, non-crashing view modes for ContextCortex topology exploration: a **Focused Neighborhood Drill-Down View** (with concentric radial layout, 1-hop/2-hop radius, and breadcrumbs navigation) and a **Global HTML5 2D Canvas Engine** (rendering thousands of nodes/edges at 60 FPS with zero DOM overhead).

**Architecture:** 
- `neighborhoodLayout.ts`: Pure geometric engine calculating 1-hop/2-hop subgraphs and radial coordinates.
- `NeighborhoodView.tsx`: Interactive focal view rendering concentric neighbor rings, breadcrumbs navigation trail, and categorized incoming/outgoing dependency cards.
- `TopologyCanvas2D.tsx`: Hardware-accelerated HTML5 2D Canvas component rendering batched edges and nodes, supporting high-DPI scaling, smooth pan/zoom, and spatial mouse hit-testing.
- `TopologyExplorer.tsx` & `TopologyControls.tsx`: Orchestrator managing mode switching (`'neighborhood'` vs `'canvas'`), focal node state, breadcrumb history, and shared inspector drawer.

**Tech Stack:** React 19, TypeScript, HTML5 2D Canvas, Vitest, FastMCP / FastAPI backend.

## Global Constraints
- Preserve all existing topology endpoint compatibility (`/admin/api/graph/topology`, `/admin/api/graph/node-details`).
- Zero DOM element generation for graph nodes/edges in 2D Canvas mode.
- All coordinate calculations must be guarded with `isFinite()` to prevent `NaN` layout corruptions.
- All backend tests (`pytest`) and frontend tests (`npm --prefix frontend test`) must pass with 0 regressions.

---

### Task 1: Type Definitions & Concentric Neighborhood Layout Engine

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/topology/types.ts`
- Create: `frontend/src/components/topology/neighborhoodLayout.ts`
- Create: `frontend/src/tests/neighborhoodLayout.test.ts`

**Interfaces:**
- Produces:
  - `TopologyViewMode = 'neighborhood' | 'canvas'`
  - `FocalBreadcrumb = { id: string; name: string; type: string; repo: string }`
  - `NeighborhoodSubGraph = { focalNode: TopologyNode; incoming: Array<{ node: TopologyNode; edgeType: string }>; outgoing: Array<{ node: TopologyNode; edgeType: string }>; secondaryNodes: TopologyNode[]; edges: TopologyEdge[] }`
  - `buildNeighborhoodGraph(nodes, edges, focalId, hopDepth)`
  - `calculateRadialPositions(subGraph, center, innerRadius, outerRadius)`

- [ ] **Step 1: Write failing unit test for `neighborhoodLayout.ts`**

```typescript
// frontend/src/tests/neighborhoodLayout.test.ts
import { describe, it, expect } from 'vitest';
import { buildNeighborhoodGraph, calculateRadialPositions } from '../components/topology/neighborhoodLayout';
import type { TopologyNode, TopologyEdge } from '../types';

describe('neighborhoodLayout', () => {
  const nodes: TopologyNode[] = [
    { id: 'focal', name: 'FocalService.cs', type: 'file', repo: 'core' },
    { id: 'caller', name: 'MainController.cs', type: 'file', repo: 'core' },
    { id: 'callee', name: 'Logger.cs', type: 'file', repo: 'core' },
    { id: 'secondary', name: 'Formatter.cs', type: 'file', repo: 'core' },
    { id: 'orphan', name: 'Unrelated.cs', type: 'file', repo: 'core' },
  ];

  const edges: TopologyEdge[] = [
    { source: 'caller', target: 'focal', type: 'CALLS' },
    { source: 'focal', target: 'callee', type: 'IMPORTS' },
    { source: 'callee', target: 'secondary', type: 'CALLS' },
  ];

  it('builds 1-hop neighborhood subgraph correctly', () => {
    const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
    expect(sub.focalNode.id).toBe('focal');
    expect(sub.incoming.map(i => i.node.id)).toContain('caller');
    expect(sub.outgoing.map(o => o.node.id)).toContain('callee');
    expect(sub.secondaryNodes.length).toBe(0);
    expect(sub.edges.length).toBe(2);
  });

  it('builds 2-hop neighborhood with secondary nodes', () => {
    const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 2);
    expect(sub.secondaryNodes.map(s => s.id)).toContain('secondary');
    expect(sub.edges.length).toBe(3);
  });

  it('calculates finite radial positions without NaN', () => {
    const sub = buildNeighborhoodGraph(nodes, edges, 'focal', 1);
    const layout = calculateRadialPositions(sub, { x: 500, y: 320 }, 180, 300);
    expect(layout.focal.x).toBe(500);
    expect(layout.focal.y).toBe(320);
    layout.neighbors.forEach(n => {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test frontend/src/tests/neighborhoodLayout.test.ts`  
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `types.ts` and `neighborhoodLayout.ts`**

Update `frontend/src/types.ts` and `frontend/src/components/topology/types.ts`, then create `frontend/src/components/topology/neighborhoodLayout.ts` implementing `buildNeighborhoodGraph` and `calculateRadialPositions`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/neighborhoodLayout.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/components/topology/types.ts frontend/src/components/topology/neighborhoodLayout.ts frontend/src/tests/neighborhoodLayout.test.ts
git commit -m "feat(topology): add neighborhood layout algorithm and types"
```

---

### Task 2: Focused Neighborhood View UI Component (`NeighborhoodView.tsx`)

**Files:**
- Create: `frontend/src/components/topology/NeighborhoodView.tsx`
- Modify: `frontend/src/styles/topology.css`
- Create: `frontend/src/tests/NeighborhoodView.test.tsx`

**Interfaces:**
- Consumes: `NeighborhoodSubGraph`, `calculateRadialPositions` from Task 1.
- Produces: `NeighborhoodView` React component accepting `{ graphData, focalNodeId, onSelectFocalNode, onSelectNodeDetails, breadcrumbs, onNavigateBreadcrumb, hopRadius, setHopRadius }`.

- [ ] **Step 1: Write failing unit test for `NeighborhoodView.tsx`**

```typescript
// frontend/src/tests/NeighborhoodView.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NeighborhoodView } from '../components/topology/NeighborhoodView';
import type { TopologyGraphData, FocalBreadcrumb } from '../types';

describe('NeighborhoodView Component', () => {
  const mockGraphData: TopologyGraphData = {
    nodes: [
      { id: 'focal', name: 'FocalService.cs', type: 'file', repo: 'core' },
      { id: 'caller', name: 'MainController.cs', type: 'file', repo: 'core' },
      { id: 'callee', name: 'Logger.cs', type: 'file', repo: 'core' },
    ],
    edges: [
      { source: 'caller', target: 'focal', type: 'CALLS' },
      { source: 'focal', target: 'callee', type: 'IMPORTS' },
    ],
    stats: { node_count: 3, edge_count: 2 },
  };

  const mockBreadcrumbs: FocalBreadcrumb[] = [
    { id: 'caller', name: 'MainController.cs', type: 'file', repo: 'core' },
    { id: 'focal', name: 'FocalService.cs', type: 'file', repo: 'core' },
  ];

  it('renders breadcrumb trail, focal node, and incoming/outgoing columns', () => {
    const onSelectFocal = vi.fn();
    const onNavigateBreadcrumb = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal"
        onSelectFocalNode={onSelectFocal}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={onNavigateBreadcrumb}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    expect(screen.getByText('FocalService.cs')).toBeInTheDocument();
    expect(screen.getByText('MainController.cs')).toBeInTheDocument();
    expect(screen.getByText('Logger.cs')).toBeInTheDocument();
    expect(screen.getByText('Incoming (Callers / Importers)')).toBeInTheDocument();
    expect(screen.getByText('Outgoing (Callees / Dependencies)')).toBeInTheDocument();
  });

  it('triggers onNavigateBreadcrumb when clicking breadcrumb item', () => {
    const onNavigateBreadcrumb = vi.fn();
    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={onNavigateBreadcrumb}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /MainController\.cs/i }));
    expect(onNavigateBreadcrumb).toHaveBeenCalledWith(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test frontend/src/tests/NeighborhoodView.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement `NeighborhoodView.tsx` and styling in `topology.css`**

Create `frontend/src/components/topology/NeighborhoodView.tsx` with:
- Top breadcrumbs bar with clickable historical ancestors.
- Central SVG/Canvas concentric layout rendering focal node, orbital rings, directional curves, and animated pulse for active focus.
- Left column: Incoming dependencies list with 1-click focus jump and inspect buttons.
- Right column: Outgoing dependencies list with 1-click focus jump and inspect buttons.
- Hop radius toggle buttons (`1-Hop` / `2-Hop`).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/NeighborhoodView.test.tsx`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/NeighborhoodView.tsx frontend/src/styles/topology.css frontend/src/tests/NeighborhoodView.test.tsx
git commit -m "feat(topology): add NeighborhoodView component with breadcrumbs and dependency columns"
```

---

### Task 3: HTML5 2D Canvas Engine (`TopologyCanvas2D.tsx`)

**Files:**
- Create: `frontend/src/components/topology/TopologyCanvas2D.tsx`
- Create: `frontend/src/tests/TopologyCanvas2D.test.tsx`

**Interfaces:**
- Produces: `TopologyCanvas2D` React component replacing SVG canvas in `'canvas'` mode.
- Supports:
  - HiDPI double-buffered rendering on `<canvas>`.
  - Batch line drawing by edge type color.
  - Circular nodes with border, fill, icon, and truncated labels.
  - Spatial hit testing for hover highlights, click selection, and dragging.
  - Smooth pan, zoom, auto-fit, and PNG image export.

- [ ] **Step 1: Write failing unit test for `TopologyCanvas2D.tsx`**

```typescript
// frontend/src/tests/TopologyCanvas2D.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TopologyCanvas2D } from '../components/topology/TopologyCanvas2D';
import type { SimNode } from '../components/topology/types';

describe('TopologyCanvas2D Component', () => {
  const mockNodes: SimNode[] = [
    { id: 'node-1', name: 'App.tsx', type: 'file', repo: 'core', x: 100, y: 100, vx: 0, vy: 0, radius: 20 },
    { id: 'node-2', name: 'Utils.ts', type: 'file', repo: 'core', x: 300, y: 200, vx: 0, vy: 0, radius: 20 },
  ];

  beforeEach(() => {
    // Mock HTMLCanvasElement getContext
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      fillText: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      setLineDash: vi.fn(),
    });
  });

  it('renders canvas element and toolbar controls', () => {
    render(
      <TopologyCanvas2D
        nodes={mockNodes}
        edges={[]}
        selectedNodeId={null}
        searchQuery=""
        onSelectNode={vi.fn()}
      />
    );

    expect(screen.getByTestId('topology-2d-canvas')).toBeInTheDocument();
    expect(screen.getByTitle('Zoom In')).toBeInTheDocument();
    expect(screen.getByTitle('Fit to View')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test frontend/src/tests/TopologyCanvas2D.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement `TopologyCanvas2D.tsx`**

Build `TopologyCanvas2D.tsx` with:
- `<canvas data-testid="topology-2d-canvas" />`
- `requestAnimationFrame` render loop with `devicePixelRatio` scaling.
- Batch drawing of edges by style color.
- Coordinate conversion and spatial distance hit-testing `(worldX - node.x)**2 + (worldY - node.y)**2 <= (node.radius + 4)**2`.
- Mouse handlers for hover tooltip, click selection, pan, and dragging.
- Built-in canvas toolbar for zoom in/out, fit to view, reset, and PNG export.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/TopologyCanvas2D.test.tsx`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyCanvas2D.tsx frontend/src/tests/TopologyCanvas2D.test.tsx
git commit -m "feat(topology): add high-performance HTML5 2D Canvas topology renderer"
```

---

### Task 4: TopologyExplorer Integration & Mode Switcher

**Files:**
- Modify: `frontend/src/components/topology/TopologyControls.tsx`
- Modify: `frontend/src/TopologyExplorer.tsx`
- Modify: `frontend/src/tests/TopologyExplorer.test.tsx`

**Interfaces:**
- Connects: `TopologyControls.tsx` mode toggle with `TopologyExplorer.tsx`.
- Switches between `<NeighborhoodView />` (when `viewMode === 'neighborhood'`) and `<TopologyCanvas2D />` (when `viewMode === 'canvas'`).
- Manages breadcrumb state and focal node selection on repository change.

- [ ] **Step 1: Write failing unit test in `TopologyExplorer.test.tsx` for view mode switching**

Add tests verifying:
- Switching between "Focal Neighborhood" and "Global 2D Canvas" view modes.
- Selecting a node in Neighborhood view updates the Inspector drawer and breadcrumbs.
- Filtering nodes in Canvas mode updates visible node count.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test frontend/src/tests/TopologyExplorer.test.tsx`  
Expected: FAIL (missing viewMode toggle props).

- [ ] **Step 3: Update `TopologyControls.tsx` and `TopologyExplorer.tsx`**

1. In `TopologyControls.tsx`, add a clean View Mode segmented control:
   - `Neighborhood View` (Icon: `fa-crosshairs`)
   - `Global 2D Canvas` (Icon: `fa-network-wired`)
2. In `TopologyExplorer.tsx`, wire `viewMode` state:
   - When `'neighborhood'`: Render `<NeighborhoodView />` with breadcrumbs and focal selection.
   - When `'canvas'`: Render `<TopologyCanvas2D />` with 60 FPS Canvas rendering.
   - Sync `selectedNodeId` and Inspector drawer seamlessly between both modes.

- [ ] **Step 4: Run all frontend tests to verify they pass**

Run: `npm --prefix frontend test`  
Expected: All test suites PASS (105+ tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/TopologyExplorer.tsx frontend/src/components/topology/TopologyControls.tsx frontend/src/tests/TopologyExplorer.test.tsx
git commit -m "feat(topology): integrate NeighborhoodView and TopologyCanvas2D into TopologyExplorer"
```

---

### Task 5: Production Build, Test Suite Verification & Live Container Preview

**Files:**
- Build: `frontend/dist/`
- Container: `contextcortex:branch-preview` (Port 8085)

- [ ] **Step 1: Run full frontend build**

Run: `npm --prefix frontend run build`  
Expected: Clean build with 0 TypeScript/Vite errors.

- [ ] **Step 2: Run full backend pytest test suite**

Run: `pytest`  
Expected: 307 tests pass.

- [ ] **Step 3: Rebuild Docker preview image & restart container**

```bash
docker build -t contextcortex:branch-preview /containers/dev/contexthub
docker rm -f contextcortex-preview
docker run -d --name contextcortex-preview -p 8085:3000 -v /tmp/contextcortex-preview-data:/app/data:rw -v /containers:/containers:ro --restart unless-stopped contextcortex:branch-preview
```

- [ ] **Step 4: Test live endpoints**

```bash
curl -s http://127.0.0.1:8085/health
curl -s http://127.0.0.1:8085/admin/api/stats
```

- [ ] **Step 5: Commit and push changes to branch**

```bash
git add frontend/dist/
git commit -m "chore(release): build production bundle with 2D Canvas and Neighborhood topology views"
git push origin fix/topology-and-repo-stats
```
