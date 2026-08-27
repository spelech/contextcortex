import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  DEFAULT_PHYSICS_CONFIG,
  PHYSICS_PRESETS,
  ARCHITECTURE_PRESET_MAP,
  resolveBackendViewType,
  getStoredPhysicsConfig,
  setStoredPhysicsConfig,
  STORAGE_KEY_PHYSICS,
} from '../components/topology/physicsPresets';
import type { TopologyPhysicsConfig, ArchitecturePreset } from '../components/topology/types';

describe('physicsPresets and viewType resolution', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('PHYSICS_PRESETS and DEFAULT_PHYSICS_CONFIG', () => {
    it('defines DEFAULT_PHYSICS_CONFIG with valid defaults', () => {
      expect(DEFAULT_PHYSICS_CONFIG).toEqual({
        kRepulse: 25000,
        springLength: 190,
        kSpring: 0.025,
        centerGravity: 0.002,
        collisionRadius: 20,
        iterations: 60,
      });
    });

    it('contains balanced, spacious, dense, and compact presets with correct values', () => {
      expect(PHYSICS_PRESETS.balanced).toEqual(DEFAULT_PHYSICS_CONFIG);

      expect(PHYSICS_PRESETS.spacious).toEqual({
        kRepulse: 55000,
        springLength: 260,
        kSpring: 0.018,
        centerGravity: 0.0005,
        collisionRadius: 24,
        iterations: 75,
      });

      expect(PHYSICS_PRESETS.dense).toEqual({
        kRepulse: 10000,
        springLength: 110,
        kSpring: 0.040,
        centerGravity: 0.006,
        collisionRadius: 16,
        iterations: 50,
      });

      expect(PHYSICS_PRESETS.compact).toEqual({
        kRepulse: 16000,
        springLength: 140,
        kSpring: 0.030,
        centerGravity: 0.0035,
        collisionRadius: 18,
        iterations: 60,
      });
    });

    it('ensures all physics presets contain finite, positive numbers and no NaN or Infinity', () => {
      const presetKeys = Object.keys(PHYSICS_PRESETS) as Array<keyof typeof PHYSICS_PRESETS>;
      presetKeys.forEach((key) => {
        const config = PHYSICS_PRESETS[key];
        expect(Number.isFinite(config.kRepulse)).toBe(true);
        expect(config.kRepulse).toBeGreaterThan(0);

        expect(Number.isFinite(config.springLength)).toBe(true);
        expect(config.springLength).toBeGreaterThan(0);

        expect(Number.isFinite(config.kSpring)).toBe(true);
        expect(config.kSpring).toBeGreaterThan(0);

        expect(Number.isFinite(config.centerGravity)).toBe(true);
        expect(config.centerGravity).toBeGreaterThan(0);

        expect(Number.isFinite(config.collisionRadius)).toBe(true);
        expect(config.collisionRadius).toBeGreaterThan(0);

        expect(Number.isFinite(config.iterations)).toBe(true);
        expect(config.iterations).toBeGreaterThan(0);
      });
    });
  });

  describe('ARCHITECTURE_PRESET_MAP', () => {
    it('maps all architecture presets to correct filter sets', () => {
      expect(ARCHITECTURE_PRESET_MAP.files).toEqual({
        file: true,
        class: false,
        function: false,
        route: false,
        module: false,
      });

      expect(ARCHITECTURE_PRESET_MAP.architecture).toEqual({
        file: true,
        class: true,
        function: false,
        route: false,
        module: true,
      });

      expect(ARCHITECTURE_PRESET_MAP.api).toEqual({
        file: true,
        class: false,
        function: true,
        route: true,
        module: false,
      });

      expect(ARCHITECTURE_PRESET_MAP.full).toEqual({
        file: true,
        class: true,
        function: true,
        route: true,
        module: true,
      });
    });
  });

  describe('resolveBackendViewType', () => {
    it('resolves to "files" when only file or no filters active', () => {
      expect(resolveBackendViewType({})).toBe('files');
      expect(resolveBackendViewType({ file: true })).toBe('files');
      expect(resolveBackendViewType({ file: true, module: true })).toBe('files');
      expect(resolveBackendViewType({ file: true, class: false, function: false, route: false })).toBe('files');
      expect(resolveBackendViewType({ file: false, class: false, function: false, route: false })).toBe('files');
    });

    it('resolves to "routes" when route is active and no class/function', () => {
      expect(resolveBackendViewType({ route: true })).toBe('routes');
      expect(resolveBackendViewType({ route: true, file: true })).toBe('routes');
      expect(resolveBackendViewType({ route: true, file: true, module: true, class: false, function: false })).toBe('routes');
    });

    it('resolves to "symbols" when class or function is active and no route', () => {
      expect(resolveBackendViewType({ class: true })).toBe('symbols');
      expect(resolveBackendViewType({ function: true })).toBe('symbols');
      expect(resolveBackendViewType({ class: true, function: true })).toBe('symbols');
      expect(resolveBackendViewType({ class: true, file: true, route: false })).toBe('symbols');
      expect(resolveBackendViewType({ function: true, module: true, route: false })).toBe('symbols');
      expect(resolveBackendViewType(ARCHITECTURE_PRESET_MAP.architecture)).toBe('symbols');
    });

    it('resolves to "full" when route AND (class or function) are active', () => {
      expect(resolveBackendViewType({ route: true, class: true })).toBe('full');
      expect(resolveBackendViewType({ route: true, function: true })).toBe('full');
      expect(resolveBackendViewType({ route: true, class: true, function: true })).toBe('full');
      expect(resolveBackendViewType(ARCHITECTURE_PRESET_MAP.api)).toBe('full');
      expect(resolveBackendViewType(ARCHITECTURE_PRESET_MAP.full)).toBe('full');
    });
  });

  describe('localStorage physics persistence', () => {
    it('returns DEFAULT_PHYSICS_CONFIG if localStorage has no stored value', () => {
      const config = getStoredPhysicsConfig();
      expect(config).toEqual(DEFAULT_PHYSICS_CONFIG);
    });

    it('stores and retrieves physics configuration accurately', () => {
      const customConfig: TopologyPhysicsConfig = {
        kRepulse: 32000,
        springLength: 210,
        kSpring: 0.022,
        centerGravity: 0.0015,
        collisionRadius: 22,
        iterations: 65,
      };

      setStoredPhysicsConfig(customConfig);
      expect(localStorage.getItem(STORAGE_KEY_PHYSICS)).toBe(JSON.stringify(customConfig));

      const retrieved = getStoredPhysicsConfig();
      expect(retrieved).toEqual(customConfig);
    });

    it('gracefully handles corrupted JSON in localStorage', () => {
      localStorage.setItem(STORAGE_KEY_PHYSICS, 'invalid-json{');
      const retrieved = getStoredPhysicsConfig();
      expect(retrieved).toEqual(DEFAULT_PHYSICS_CONFIG);
    });

    it('gracefully handles non-object JSON values in localStorage', () => {
      localStorage.setItem(STORAGE_KEY_PHYSICS, '12345');
      expect(getStoredPhysicsConfig()).toEqual(DEFAULT_PHYSICS_CONFIG);

      localStorage.setItem(STORAGE_KEY_PHYSICS, '"string-value"');
      expect(getStoredPhysicsConfig()).toEqual(DEFAULT_PHYSICS_CONFIG);

      localStorage.setItem(STORAGE_KEY_PHYSICS, 'null');
      expect(getStoredPhysicsConfig()).toEqual(DEFAULT_PHYSICS_CONFIG);
    });

    it('falls back individual invalid/NaN properties to DEFAULT_PHYSICS_CONFIG values', () => {
      const partialConfig = {
        kRepulse: 40000,
        springLength: 'invalid', // should fallback
        kSpring: NaN, // should fallback
        centerGravity: 0.005,
        // collisionRadius omitted -> should fallback
        iterations: Infinity, // should fallback
      };
      localStorage.setItem(STORAGE_KEY_PHYSICS, JSON.stringify(partialConfig));

      const retrieved = getStoredPhysicsConfig();
      expect(retrieved.kRepulse).toBe(40000);
      expect(retrieved.springLength).toBe(DEFAULT_PHYSICS_CONFIG.springLength);
      expect(retrieved.kSpring).toBe(DEFAULT_PHYSICS_CONFIG.kSpring);
      expect(retrieved.centerGravity).toBe(0.005);
      expect(retrieved.collisionRadius).toBe(DEFAULT_PHYSICS_CONFIG.collisionRadius);
      expect(retrieved.iterations).toBe(DEFAULT_PHYSICS_CONFIG.iterations);
    });

    it('handles localStorage errors gracefully without throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('Access denied');
      });
      expect(() => getStoredPhysicsConfig()).not.toThrow();
      expect(getStoredPhysicsConfig()).toEqual(DEFAULT_PHYSICS_CONFIG);

      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('Quota exceeded');
      });
      expect(() => setStoredPhysicsConfig(DEFAULT_PHYSICS_CONFIG)).not.toThrow();
    });
  });
});
