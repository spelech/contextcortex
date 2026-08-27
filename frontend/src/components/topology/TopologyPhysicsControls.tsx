import type { TopologyPhysicsConfig } from './types';
import { PHYSICS_PRESETS } from './physicsPresets';

export interface TopologyPhysicsControlsProps {
  config: TopologyPhysicsConfig;
  onChangeConfig: (newConfig: TopologyPhysicsConfig) => void;
  onSelectPreset: (presetKey: string) => void;
  onReRelax: () => void;
  onResetDefaults: () => void;
  onClose?: () => void;
  isOpen?: boolean;
}

export interface PhysicsPresetItem {
  key: 'balanced' | 'spacious' | 'dense' | 'compact';
  label: string;
  icon: string;
  description: string;
}

export const PHYSICS_PRESET_ITEMS: PhysicsPresetItem[] = [
  {
    key: 'balanced',
    label: 'Default Balanced',
    icon: 'fa-scale-balanced',
    description: 'Balanced forces for general codebases',
  },
  {
    key: 'spacious',
    label: 'Spacious Tree',
    icon: 'fa-diagram-project',
    description: 'Wide separation and long springs',
  },
  {
    key: 'dense',
    label: 'Dense Cluster',
    icon: 'fa-cubes',
    description: 'Tight clustering with high gravity',
  },
  {
    key: 'compact',
    label: 'Compact Radial',
    icon: 'fa-circle-dot',
    description: 'Compact layout for medium graphs',
  },
];

export interface PhysicsSliderDef {
  key: keyof TopologyPhysicsConfig;
  label: string;
  symbol: string;
  min: number;
  max: number;
  step: number;
  unit?: string;
  format?: (val: number) => string;
}

export const PHYSICS_SLIDER_DEFS: PhysicsSliderDef[] = [
  {
    key: 'kRepulse',
    label: 'Repulsion Force',
    symbol: 'k_repulse',
    min: 5000,
    max: 75000,
    step: 1000,
  },
  {
    key: 'springLength',
    label: 'Spring Distance',
    symbol: 'L_spring',
    min: 80,
    max: 350,
    step: 5,
    unit: 'px',
  },
  {
    key: 'kSpring',
    label: 'Spring Stiffness',
    symbol: 'k_spring',
    min: 0.01,
    max: 0.08,
    step: 0.005,
    format: (val: number) => val.toFixed(3),
  },
  {
    key: 'centerGravity',
    label: 'Center Gravity',
    symbol: 'G_center',
    min: 0.000,
    max: 0.010,
    step: 0.0005,
    format: (val: number) => val.toFixed(4),
  },
  {
    key: 'collisionRadius',
    label: 'Collision Radius',
    symbol: 'R_collision',
    min: 12,
    max: 36,
    step: 2,
    unit: 'px',
  },
  {
    key: 'iterations',
    label: 'Simulation Iterations',
    symbol: 'N_iter',
    min: 20,
    max: 120,
    step: 5,
  },
];

export function TopologyPhysicsControls({
  config,
  onChangeConfig,
  onSelectPreset,
  onReRelax,
  onResetDefaults,
  onClose,
  isOpen = true,
}: TopologyPhysicsControlsProps) {
  if (isOpen === false) {
    return null;
  }

  const isPresetActive = (presetKey: keyof typeof PHYSICS_PRESETS) => {
    const preset = PHYSICS_PRESETS[presetKey];
    if (!preset || !config) return false;
    return (
      config.kRepulse === preset.kRepulse &&
      config.springLength === preset.springLength &&
      Math.abs(config.kSpring - preset.kSpring) < 1e-5 &&
      Math.abs(config.centerGravity - preset.centerGravity) < 1e-5 &&
      config.collisionRadius === preset.collisionRadius &&
      config.iterations === preset.iterations
    );
  };

  const handleSliderChange = (key: keyof TopologyPhysicsConfig, rawValue: string) => {
    const parsed = parseFloat(rawValue);
    if (!Number.isFinite(parsed)) return;
    onChangeConfig({
      ...config,
      [key]: parsed,
    });
  };

  const formatValue = (slider: PhysicsSliderDef, val: number): string => {
    if (slider.format) {
      return slider.format(val);
    }
    if (slider.unit) {
      return `${val}${slider.unit}`;
    }
    return String(val);
  };

  return (
    <div className="topology-physics-panel" role="region" aria-label="Simulation Physics Controls">
      <div className="topology-physics-header">
        <div className="topology-physics-title-wrap">
          <i className="fa-solid fa-sliders text-primary"></i>
          <h3 className="topology-physics-title">Force-Directed Simulation Physics</h3>
        </div>
        {onClose && (
          <button
            type="button"
            className="btn btn-secondary btn-sm topology-physics-close-btn"
            onClick={onClose}
            aria-label="Close Physics Controls"
            title="Close"
          >
            <i className="fa-solid fa-xmark"></i>
          </button>
        )}
      </div>

      <div className="topology-physics-body">
        {/* Physics Presets Row */}
        <div className="topology-physics-section">
          <span className="topology-physics-section-title">Physics Presets</span>
          <div className="topology-physics-presets-grid" role="group" aria-label="Physics Presets">
            {PHYSICS_PRESET_ITEMS.map((preset) => {
              const active = isPresetActive(preset.key);
              return (
                <button
                  key={preset.key}
                  type="button"
                  className={`topology-physics-preset-btn ${active ? 'active' : ''}`}
                  onClick={() => onSelectPreset(preset.key)}
                  title={preset.description}
                >
                  <i className={`fa-solid ${preset.icon}`}></i>
                  <span>{preset.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Sliders Grid */}
        <div className="topology-physics-section">
          <span className="topology-physics-section-title">Force Parameters</span>
          <div className="topology-physics-sliders-list">
            {PHYSICS_SLIDER_DEFS.map((slider) => {
              const val = config?.[slider.key] ?? slider.min;
              const displayVal = formatValue(slider, val);
              const sliderId = `physics-slider-${slider.key}`;

              return (
                <div key={slider.key} className="topology-physics-slider-row">
                  <div className="topology-physics-slider-header">
                    <label htmlFor={sliderId} className="topology-physics-slider-label">
                      {slider.label}
                      <span className="topology-physics-symbol">({slider.symbol})</span>
                    </label>
                    <span className="topology-physics-value-chip">{displayVal}</span>
                  </div>
                  <input
                    id={sliderId}
                    type="range"
                    aria-label={slider.label}
                    min={slider.min}
                    max={slider.max}
                    step={slider.step}
                    value={val}
                    onChange={(e) => handleSliderChange(slider.key, e.target.value)}
                    className="topology-physics-range-input"
                  />
                </div>
              );
            })}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="topology-physics-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm topology-physics-action-btn"
            onClick={onReRelax}
          >
            <i className="fa-solid fa-arrows-rotate"></i> Re-Relax Layout
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm topology-physics-action-btn"
            onClick={onResetDefaults}
          >
            <i className="fa-solid fa-rotate-left"></i> Reset Defaults
          </button>
        </div>
      </div>
    </div>
  );
}
