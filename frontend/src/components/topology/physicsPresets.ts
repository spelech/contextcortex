import type { TopologyPhysicsConfig, ArchitecturePreset } from './types';

export const STORAGE_KEY_PHYSICS = 'contextcortex_topology_physics';

export const DEFAULT_PHYSICS_CONFIG: TopologyPhysicsConfig = {
  kRepulse: 25000,
  springLength: 190,
  kSpring: 0.025,
  centerGravity: 0.002,
  collisionRadius: 20,
  iterations: 60,
};

export const PHYSICS_PRESETS: Record<'balanced' | 'spacious' | 'dense' | 'compact', TopologyPhysicsConfig> = {
  balanced: DEFAULT_PHYSICS_CONFIG,
  spacious: {
    kRepulse: 55000,
    springLength: 260,
    kSpring: 0.018,
    centerGravity: 0.0005,
    collisionRadius: 24,
    iterations: 75,
  },
  dense: {
    kRepulse: 10000,
    springLength: 110,
    kSpring: 0.040,
    centerGravity: 0.006,
    collisionRadius: 16,
    iterations: 50,
  },
  compact: {
    kRepulse: 16000,
    springLength: 140,
    kSpring: 0.030,
    centerGravity: 0.0035,
    collisionRadius: 18,
    iterations: 60,
  },
};

export const ARCHITECTURE_PRESET_MAP: Record<ArchitecturePreset, Record<string, boolean>> = {
  files: {
    file: true,
    class: false,
    function: false,
    route: false,
    module: false,
  },
  architecture: {
    file: true,
    class: true,
    function: false,
    route: false,
    module: true,
  },
  api: {
    file: true,
    class: false,
    function: true,
    route: true,
    module: false,
  },
  full: {
    file: true,
    class: true,
    function: true,
    route: true,
    module: true,
  },
};

export function resolveBackendViewType(typeFilters: Record<string, boolean>): 'files' | 'symbols' | 'routes' | 'full' {
  const hasRoute = Boolean(typeFilters?.route);
  const hasSymbols = Boolean(typeFilters?.class || typeFilters?.function);

  if (hasRoute && hasSymbols) {
    return 'full';
  }
  if (hasRoute) {
    return 'routes';
  }
  if (hasSymbols) {
    return 'symbols';
  }
  return 'files';
}

export function getStoredPhysicsConfig(): TopologyPhysicsConfig {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return { ...DEFAULT_PHYSICS_CONFIG };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PHYSICS);
    if (!raw) {
      return { ...DEFAULT_PHYSICS_CONFIG };
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return { ...DEFAULT_PHYSICS_CONFIG };
    }

    const parseNum = (val: unknown, fallback: number): number => {
      return typeof val === 'number' && Number.isFinite(val) ? val : fallback;
    };

    return {
      kRepulse: parseNum(parsed.kRepulse, DEFAULT_PHYSICS_CONFIG.kRepulse),
      springLength: parseNum(parsed.springLength, DEFAULT_PHYSICS_CONFIG.springLength),
      kSpring: parseNum(parsed.kSpring, DEFAULT_PHYSICS_CONFIG.kSpring),
      centerGravity: parseNum(parsed.centerGravity, DEFAULT_PHYSICS_CONFIG.centerGravity),
      collisionRadius: parseNum(parsed.collisionRadius, DEFAULT_PHYSICS_CONFIG.collisionRadius),
      iterations: parseNum(parsed.iterations, DEFAULT_PHYSICS_CONFIG.iterations),
    };
  } catch {
    return { ...DEFAULT_PHYSICS_CONFIG };
  }
}

export function setStoredPhysicsConfig(config: TopologyPhysicsConfig): void {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return;
  }
  try {
    localStorage.setItem(STORAGE_KEY_PHYSICS, JSON.stringify(config));
  } catch {
    // Gracefully handle storage errors (e.g. quota exceeded)
  }
}
