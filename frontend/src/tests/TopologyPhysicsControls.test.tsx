import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import {
  TopologyPhysicsControls,
  PHYSICS_PRESET_ITEMS,
  PHYSICS_SLIDER_DEFS,
} from '../components/topology/TopologyPhysicsControls';
import type { TopologyPhysicsControlsProps } from '../components/topology/TopologyPhysicsControls';
import { DEFAULT_PHYSICS_CONFIG, PHYSICS_PRESETS } from '../components/topology/physicsPresets';
import type { TopologyPhysicsConfig } from '../components/topology/types';

function createDefaultProps(overrides?: Partial<TopologyPhysicsControlsProps>): TopologyPhysicsControlsProps {
  return {
    config: { ...DEFAULT_PHYSICS_CONFIG },
    onChangeConfig: vi.fn(),
    onSelectPreset: vi.fn(),
    onReRelax: vi.fn(),
    onResetDefaults: vi.fn(),
    onClose: vi.fn(),
    isOpen: true,
    ...overrides,
  };
}

describe('TopologyPhysicsControls Component', () => {
  describe('Rendering & Visibility', () => {
    it('renders header, preset buttons, sliders, and action buttons when open', () => {
      const props = createDefaultProps();
      render(<TopologyPhysicsControls {...props} />);

      expect(screen.getByText('Force-Directed Simulation Physics')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Default Balanced/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Spacious Tree/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Dense Cluster/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Compact Radial/i })).toBeInTheDocument();

      expect(screen.getByRole('button', { name: /Re-Relax Layout/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Reset Defaults/i })).toBeInTheDocument();
    });

    it('renders nothing when isOpen is false', () => {
      const props = createDefaultProps({ isOpen: false });
      const { container } = render(<TopologyPhysicsControls {...props} />);
      expect(container.firstChild).toBeNull();
    });

    it('renders when isOpen is undefined (defaults to open)', () => {
      const props = createDefaultProps({ isOpen: undefined });
      render(<TopologyPhysicsControls {...props} />);
      expect(screen.getByText('Force-Directed Simulation Physics')).toBeInTheDocument();
    });

    it('renders close button when onClose is provided and triggers callback on click', () => {
      const onClose = vi.fn();
      const props = createDefaultProps({ onClose });
      render(<TopologyPhysicsControls {...props} />);

      const closeBtn = screen.getByRole('button', { name: /Close Physics Controls/i });
      expect(closeBtn).toBeInTheDocument();
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does not render close button when onClose is not provided', () => {
      const props = createDefaultProps({ onClose: undefined });
      render(<TopologyPhysicsControls {...props} />);
      expect(screen.queryByRole('button', { name: /Close Physics Controls/i })).not.toBeInTheDocument();
    });
  });

  describe('Physics Presets', () => {
    it('exports PHYSICS_PRESET_ITEMS with 4 items', () => {
      expect(PHYSICS_PRESET_ITEMS).toHaveLength(4);
      const keys = PHYSICS_PRESET_ITEMS.map((p) => p.key);
      expect(keys).toEqual(['balanced', 'spacious', 'dense', 'compact']);
    });

    it('marks the active preset with active class when config matches preset values', () => {
      const balancedProps = createDefaultProps({ config: PHYSICS_PRESETS.balanced });
      const { rerender } = render(<TopologyPhysicsControls {...balancedProps} />);
      expect(screen.getByRole('button', { name: /Default Balanced/i })).toHaveClass('active');
      expect(screen.getByRole('button', { name: /Spacious Tree/i })).not.toHaveClass('active');

      const spaciousProps = createDefaultProps({ config: PHYSICS_PRESETS.spacious });
      rerender(<TopologyPhysicsControls {...spaciousProps} />);
      expect(screen.getByRole('button', { name: /Spacious Tree/i })).toHaveClass('active');
      expect(screen.getByRole('button', { name: /Default Balanced/i })).not.toHaveClass('active');
    });

    it('calls onSelectPreset with the correct key when a preset button is clicked', () => {
      const onSelectPreset = vi.fn();
      const props = createDefaultProps({ onSelectPreset });
      render(<TopologyPhysicsControls {...props} />);

      fireEvent.click(screen.getByRole('button', { name: /Spacious Tree/i }));
      expect(onSelectPreset).toHaveBeenCalledWith('spacious');

      fireEvent.click(screen.getByRole('button', { name: /Dense Cluster/i }));
      expect(onSelectPreset).toHaveBeenCalledWith('dense');

      fireEvent.click(screen.getByRole('button', { name: /Compact Radial/i }));
      expect(onSelectPreset).toHaveBeenCalledWith('compact');

      fireEvent.click(screen.getByRole('button', { name: /Default Balanced/i }));
      expect(onSelectPreset).toHaveBeenCalledWith('balanced');
    });
  });

  describe('Sliders & Configuration', () => {
    it('exports PHYSICS_SLIDER_DEFS with all 6 required force-directed parameters', () => {
      expect(PHYSICS_SLIDER_DEFS).toHaveLength(6);
      const keys = PHYSICS_SLIDER_DEFS.map((s) => s.key);
      expect(keys).toEqual([
        'kRepulse',
        'springLength',
        'kSpring',
        'centerGravity',
        'collisionRadius',
        'iterations',
      ]);
    });

    it('renders all 6 sliders with initial values, bounds, and step attributes', () => {
      const initialConfig: TopologyPhysicsConfig = {
        kRepulse: 30000,
        springLength: 200,
        kSpring: 0.035,
        centerGravity: 0.004,
        collisionRadius: 22,
        iterations: 70,
      };
      const props = createDefaultProps({ config: initialConfig });
      render(<TopologyPhysicsControls {...props} />);

      const repulseSlider = screen.getByRole('slider', { name: /Repulsion Force/i });
      expect(repulseSlider).toHaveAttribute('min', '5000');
      expect(repulseSlider).toHaveAttribute('max', '75000');
      expect(repulseSlider).toHaveAttribute('step', '1000');
      expect(repulseSlider).toHaveValue('30000');

      const springLengthSlider = screen.getByRole('slider', { name: /Spring Distance/i });
      expect(springLengthSlider).toHaveAttribute('min', '80');
      expect(springLengthSlider).toHaveAttribute('max', '350');
      expect(springLengthSlider).toHaveAttribute('step', '5');
      expect(springLengthSlider).toHaveValue('200');

      const kSpringSlider = screen.getByRole('slider', { name: /Spring Stiffness/i });
      expect(kSpringSlider).toHaveAttribute('min', '0.01');
      expect(kSpringSlider).toHaveAttribute('max', '0.08');
      expect(kSpringSlider).toHaveAttribute('step', '0.005');
      expect(kSpringSlider).toHaveValue('0.035');

      const gravitySlider = screen.getByRole('slider', { name: /Center Gravity/i });
      expect(gravitySlider).toHaveAttribute('min', '0');
      expect(gravitySlider).toHaveAttribute('max', '0.01');
      expect(gravitySlider).toHaveAttribute('step', '0.0005');
      expect(gravitySlider).toHaveValue('0.004');

      const collisionSlider = screen.getByRole('slider', { name: /Collision Radius/i });
      expect(collisionSlider).toHaveAttribute('min', '12');
      expect(collisionSlider).toHaveAttribute('max', '36');
      expect(collisionSlider).toHaveAttribute('step', '2');
      expect(collisionSlider).toHaveValue('22');

      const iterationsSlider = screen.getByRole('slider', { name: /Simulation Iterations/i });
      expect(iterationsSlider).toHaveAttribute('min', '20');
      expect(iterationsSlider).toHaveAttribute('max', '120');
      expect(iterationsSlider).toHaveAttribute('step', '5');
      expect(iterationsSlider).toHaveValue('70');
    });

    it('displays formatted readout values for each slider (including px and decimal precision)', () => {
      const config: TopologyPhysicsConfig = {
        kRepulse: 45000,
        springLength: 220,
        kSpring: 0.025,
        centerGravity: 0.0025,
        collisionRadius: 26,
        iterations: 80,
      };
      const props = createDefaultProps({ config });
      render(<TopologyPhysicsControls {...props} />);

      expect(screen.getByText('45000')).toBeInTheDocument();
      expect(screen.getByText('220px')).toBeInTheDocument();
      expect(screen.getByText('0.025')).toBeInTheDocument();
      expect(screen.getByText('0.0025')).toBeInTheDocument();
      expect(screen.getByText('26px')).toBeInTheDocument();
      expect(screen.getByText('80')).toBeInTheDocument();
    });

    it('triggers onChangeConfig when slider values change', () => {
      const onChangeConfig = vi.fn();
      const props = createDefaultProps({ onChangeConfig });
      render(<TopologyPhysicsControls {...props} />);

      const repulseSlider = screen.getByRole('slider', { name: /Repulsion Force/i });
      fireEvent.change(repulseSlider, { target: { value: '42000' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        kRepulse: 42000,
      });

      const springLengthSlider = screen.getByRole('slider', { name: /Spring Distance/i });
      fireEvent.change(springLengthSlider, { target: { value: '250' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        springLength: 250,
      });

      const kSpringSlider = screen.getByRole('slider', { name: /Spring Stiffness/i });
      fireEvent.change(kSpringSlider, { target: { value: '0.045' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        kSpring: 0.045,
      });

      const gravitySlider = screen.getByRole('slider', { name: /Center Gravity/i });
      fireEvent.change(gravitySlider, { target: { value: '0.008' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        centerGravity: 0.008,
      });

      const collisionSlider = screen.getByRole('slider', { name: /Collision Radius/i });
      fireEvent.change(collisionSlider, { target: { value: '28' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        collisionRadius: 28,
      });

      const iterSlider = screen.getByRole('slider', { name: /Simulation Iterations/i });
      fireEvent.change(iterSlider, { target: { value: '95' } });
      expect(onChangeConfig).toHaveBeenCalledWith({
        ...DEFAULT_PHYSICS_CONFIG,
        iterations: 95,
      });
    });

    it('safely parses numeric values and ensures numbers rather than strings are emitted', () => {
      const onChangeConfig = vi.fn();
      const props = createDefaultProps({ onChangeConfig });
      render(<TopologyPhysicsControls {...props} />);

      const repulseSlider = screen.getByRole('slider', { name: /Repulsion Force/i });
      fireEvent.change(repulseSlider, { target: { value: '45000' } });
      expect(onChangeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          kRepulse: 45000,
        })
      );
      const updatedConfig = onChangeConfig.mock.calls[0][0];
      expect(typeof updatedConfig.kRepulse).toBe('number');
      expect(Number.isFinite(updatedConfig.kRepulse)).toBe(true);
      expect(Number.isNaN(updatedConfig.kRepulse)).toBe(false);
    });
  });

  describe('Action Buttons', () => {
    it('calls onReRelax when clicking Re-Relax Layout button', () => {
      const onReRelax = vi.fn();
      const props = createDefaultProps({ onReRelax });
      render(<TopologyPhysicsControls {...props} />);

      const reRelaxBtn = screen.getByRole('button', { name: /Re-Relax Layout/i });
      fireEvent.click(reRelaxBtn);
      expect(onReRelax).toHaveBeenCalledTimes(1);
    });

    it('calls onResetDefaults when clicking Reset Defaults button', () => {
      const onResetDefaults = vi.fn();
      const props = createDefaultProps({ onResetDefaults });
      render(<TopologyPhysicsControls {...props} />);

      const resetBtn = screen.getByRole('button', { name: /Reset Defaults/i });
      fireEvent.click(resetBtn);
      expect(onResetDefaults).toHaveBeenCalledTimes(1);
    });
  });
});
