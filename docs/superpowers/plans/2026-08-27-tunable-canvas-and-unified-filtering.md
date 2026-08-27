# Tunable 2D Canvas Physics & Unified Filter Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real-time tunable 2D node physics/layout controls and unify toolbar architecture presets with multi-select entity filter chips.

**Architecture:** A pure physics presets and query resolution module (`physicsPresets.ts`), an updated toolbar (`TopologyControls.tsx`) with architectural presets and live count chips, a physics tuning popover (`TopologyPhysicsControls.tsx`) in the 2D canvas, and integrated state synchronization in `TopologyExplorer.tsx` and `TopologyCanvas2D.tsx`.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, HTML5 2D Canvas.

## Global Constraints
- Preserve all existing types and functionality in `frontend/src/types.ts` and `frontend/src/components/topology/types.ts`.
- All coordinate, velocity, and force calculations must remain protected with `isFinite()` checks (zero `NaN` or `Infinity`).
- Settings must persist in `localStorage` key `contextcortex_topology_physics`.
- All Vitest and backend Pytest suites must pass with zero errors.

---

### Task 1: Physics Engine Presets & Smart ViewType Resolver

**Files:**
- Create: `frontend/src/components/topology/physicsPresets.ts`
- Modify: `frontend/src/components/topology/types.ts`
- Test: `frontend/src/tests/physicsPresets.test.ts`

**Interfaces:**
- Produces: `TopologyPhysicsConfig`, `PHYSICS_PRESETS`, `resolveBackendViewType(typeFilters: Record<string, boolean>): 'files' | 'symbols' | 'routes' | 'full'`, `getStoredPhysicsConfig()`, `setStoredPhysicsConfig(config: TopologyPhysicsConfig)`.

- [ ] **Step 1: Write failing tests in `frontend/src/tests/physicsPresets.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import {
  PHYSICS_PRESETS,
  resolveBackendViewType,
  getStoredPhysicsConfig,
  setStoredPhysicsConfig,
  DEFAULT_PHYSICS_CONFIG,
} from '../components/topology/physicsPresets';

describe('physicsPresets and viewType resolution', () => {
  it('resolves backend view_type based on active typeFilters', () => {
    expect(resolveBackendViewType({ file: true, class: false, function: false, route: false })).toBe('files');
    expect(resolveBackendViewType({ file: true, class: false, function: false, route: true })).toBe('routes');
    expect(resolveBackendViewType({ file: true, class: true, function: false, route: false })).toBe('symbols');
    expect(resolveBackendViewType({ file: true, class: true, function: false, route: true })).toBe('full');
    expect(resolveBackendViewType({})).toBe('files');
  });

  it('provides all 4 distinct physics presets with valid numeric properties', () => {
    const presets = Object.values(PHYSICS_PRESETS);
    expect(presets.length).toBe(4);
    for (const p of presets) {
      expect(p.kRepulse).toBeGreaterThan(1000);
      expect(p.springLength).toBeGreaterThan(50);
      expect(p.kSpring).toBeGreaterThan(0);
      expect(p.centerGravity).toBeGreaterThanOrEqual(0);
      expect(p.collisionRadius).toBeGreaterThan(5);
    }
  });

  it('handles loading and saving stored physics config to localStorage', () => {
    localStorage.clear();
    const config = getStoredPhysicsConfig();
    expect(config).toEqual(DEFAULT_PHYSICS_CONFIG);

    setStoredPhysicsConfig(PHYSICS_PRESETS.spacious);
    expect(getStoredPhysicsConfig()).toEqual(PHYSICS_PRESETS.spacious);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test frontend/src/tests/physicsPresets.test.ts`
Expected: FAIL (cannot find module `physicsPresets`)

- [ ] **Step 3: Implement `frontend/src/components/topology/types.ts` and `physicsPresets.ts`**

Add `TopologyPhysicsConfig` and `ArchitecturePreset` types in `frontend/src/components/topology/types.ts`.
Create `frontend/src/components/topology/physicsPresets.ts` implementing `PHYSICS_PRESETS`, `DEFAULT_PHYSICS_CONFIG`, `resolveBackendViewType`, `getStoredPhysicsConfig`, and `setStoredPhysicsConfig`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/physicsPresets.test.ts`
Expected: PASS (3/3 tests passing)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/types.ts frontend/src/components/topology/physicsPresets.ts frontend/src/tests/physicsPresets.test.ts
git commit -m "feat(topology): add physics presets and smart viewType resolution helper"
```

---

### Task 2: Unified Architectural Presets & Filter Toolbar (`TopologyControls.tsx`)

**Files:**
- Modify: `frontend/src/components/topology/TopologyControls.tsx`
- Test: `frontend/src/tests/TopologyControls.test.tsx`

**Interfaces:**
- Consumes: `resolveBackendViewType` from `physicsPresets.ts`
- Produces: Updated `TopologyControlsProps` with `nodeCounts?: Record<string, number>`, `activePreset?: string`, `onSelectPreset: (preset: 'files' | 'architecture' | 'api' | 'full') => void`.

- [ ] **Step 1: Write failing/updated tests in `frontend/src/tests/TopologyControls.test.tsx`**

Test quick preset buttons (`Files Only`, `Architecture`, `API Surface`, `Full Codebase`) and clicking a preset triggers `onSelectPreset`.
Test that filter chips show node counts when provided.

- [ ] **Step 2: Run test to verify failure**

Run: `npm --prefix frontend test frontend/src/tests/TopologyControls.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement updated `TopologyControls.tsx`**

Replace the redundant `viewType` group with the Presets bar and live count badges on type filter chips.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/TopologyControls.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyControls.tsx frontend/src/tests/TopologyControls.test.tsx
git commit -m "feat(topology): unify toolbar with architectural presets and live count chips"
```

---

### Task 3: Tunable Physics & Layout Controls Popover (`TopologyPhysicsControls.tsx`)

**Files:**
- Create: `frontend/src/components/topology/TopologyPhysicsControls.tsx`
- Modify: `frontend/src/styles/topology.css`
- Test: `frontend/src/tests/TopologyPhysicsControls.test.tsx`

**Interfaces:**
- Consumes: `TopologyPhysicsConfig` from `types.ts`, `PHYSICS_PRESETS` from `physicsPresets.ts`
- Produces: `TopologyPhysicsControls` component with sliders (`Repulsion`, `Spring Length`, `Spring Stiffness`, `Center Gravity`, `Collision Buffer`), preset buttons, Re-relax button, and Reset button.

- [ ] **Step 1: Write failing tests in `frontend/src/tests/TopologyPhysicsControls.test.tsx`**

Test rendering sliders, selecting preset buttons, dragging a slider, clicking Re-relax (`onRecomputeLayout`), and resetting physics defaults.

- [ ] **Step 2: Run test to verify failure**

Run: `npm --prefix frontend test frontend/src/tests/TopologyPhysicsControls.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement `TopologyPhysicsControls.tsx` and CSS styles in `topology.css`**

Create `TopologyPhysicsControls.tsx` with floating popover design, responsive sliders, quick presets, and action triggers.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test frontend/src/tests/TopologyPhysicsControls.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyPhysicsControls.tsx frontend/src/styles/topology.css frontend/src/tests/TopologyPhysicsControls.test.tsx
git commit -m "feat(topology): add TopologyPhysicsControls component with real-time sliders and presets"
```

---

### Task 4: TopologyExplorer & Canvas 2D Integration

**Files:**
- Modify: `frontend/src/TopologyExplorer.tsx`
- Modify: `frontend/src/components/topology/TopologyCanvas2D.tsx`
- Test: `frontend/src/tests/TopologyExplorer.test.tsx`
- Test: `frontend/src/tests/TopologyCanvas2D.test.tsx`

**Interfaces:**
- Consumes: `TopologyPhysicsControls`, `physicsPresets.ts`
- Produces: Seamless physics tuning, dynamic query fetching on filter preset changes, real-time in-memory re-relaxation, and auto-fit preservation.

- [ ] **Step 1: Update unit tests in `TopologyExplorer.test.tsx` and `TopologyCanvas2D.test.tsx`**

Test preset selection triggering updated topology fetch with resolved `view_type`.
Test physics parameter updates triggering layout re-relaxation.

- [ ] **Step 2: Run tests to verify failure**

Run: `npm --prefix frontend test frontend/src/tests/TopologyExplorer.test.tsx`
Expected: FAIL

- [ ] **Step 3: Update `TopologyExplorer.tsx` and `TopologyCanvas2D.tsx`**

Hook up `physicsConfig` state, `resolveBackendViewType`, node counts calculation, physics popover button on the 2D canvas overlay, and in-memory relaxation handler.

- [ ] **Step 4: Run all frontend unit tests**

Run: `npm --prefix frontend test`
Expected: PASS (all 14 test suites, 140+ unit tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/TopologyExplorer.tsx frontend/src/components/topology/TopologyCanvas2D.tsx frontend/src/tests/TopologyExplorer.test.tsx frontend/src/tests/TopologyCanvas2D.test.tsx
git commit -m "feat(topology): integrate physics tuner and unified presets into TopologyExplorer and Canvas2D"
```

---

### Task 5: Production Build, Test Suite Verification & Live Container Preview

**Files:**
- Modify: `REQUIREMENTS.md`
- Rebuild: `frontend/dist/`
- Docker: `contextcortex:branch-preview` container `contextcortex-preview`

- [ ] **Step 1: Build production frontend bundle**

Run: `npm --prefix frontend run build`
Expected: Clean build (`dist/` generated without type errors).

- [ ] **Step 2: Run full test verification suites**

Run: `python3 scripts/generate_requirements.py`
Run: `pytest`
Run: `npm --prefix frontend test`

- [ ] **Step 3: Rebuild Docker image & restart preview container**

Run: `docker build -t contextcortex:branch-preview . && docker stop contextcortex-preview && docker rm contextcortex-preview && docker run -d --name contextcortex-preview -p 8085:3000 -v /tmp/contextcortex-preview-data:/app/data -v /containers:/containers:ro contextcortex:branch-preview`
Publish static preview: `agent-preview publish contextcortex-topology frontend/dist --title "ContextCortex - Canvas & Neighborhood Topology UI" --category "Web App" --tags "React,Vite,Canvas,Topology"`

- [ ] **Step 4: Commit and push**

```bash
git add REQUIREMENTS.md frontend/dist/
git commit -m "docs(requirements): sync automated test baseline and topology test catalog"
git push origin fix/topology-and-repo-stats
```
