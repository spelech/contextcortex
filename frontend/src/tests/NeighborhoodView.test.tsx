import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NeighborhoodView } from '../components/topology/NeighborhoodView';
import type { TopologyGraphData, FocalBreadcrumb } from '../types';

const mockGraphData: TopologyGraphData = {
  nodes: [
    { id: 'focal-1', name: 'OrderService.cs', type: 'class', repo: 'core-backend', filepath: 'src/Services/OrderService.cs' },
    { id: 'caller-1', name: 'OrderController.cs', type: 'class', repo: 'core-backend', filepath: 'src/Controllers/OrderController.cs' },
    { id: 'caller-2', name: 'POST /api/orders', type: 'route', repo: 'core-backend', filepath: 'src/Controllers/OrderController.cs' },
    { id: 'callee-1', name: 'IPaymentGateway.cs', type: 'class', repo: 'core-backend', filepath: 'src/Interfaces/IPaymentGateway.cs' },
    { id: 'callee-2', name: 'OrderRepository.cs', type: 'class', repo: 'core-backend', filepath: 'src/Data/OrderRepository.cs' },
    { id: 'secondary-1', name: 'StripeClient.cs', type: 'class', repo: 'core-backend', filepath: 'src/Integrations/StripeClient.cs' },
  ],
  edges: [
    { source: 'caller-1', target: 'focal-1', type: 'CALLS', label: 'creates order' },
    { source: 'caller-2', target: 'focal-1', type: 'ROUTES_TO' },
    { source: 'focal-1', target: 'callee-1', type: 'CALLS', label: 'charges card' },
    { source: 'focal-1', target: 'callee-2', type: 'IMPORTS' },
    { source: 'callee-1', target: 'secondary-1', type: 'CALLS' },
  ],
  stats: { node_count: 6, edge_count: 5 },
};

const mockBreadcrumbs: FocalBreadcrumb[] = [
  { id: 'repo:core-backend', name: 'core-backend', type: 'file', repo: 'core-backend' },
  { id: 'caller-1', name: 'OrderController.cs', type: 'class', repo: 'core-backend' },
  { id: 'focal-1', name: 'OrderService.cs', type: 'class', repo: 'core-backend' },
];

describe('NeighborhoodView Component', () => {
  it('renders breadcrumb trail, focal node, and incoming/outgoing columns', () => {
    const onSelectFocalNode = vi.fn();
    const onSelectNodeDetails = vi.fn();
    const onNavigateBreadcrumb = vi.fn();
    const setHopRadius = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={onSelectFocalNode}
        onSelectNodeDetails={onSelectNodeDetails}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={onNavigateBreadcrumb}
        hopRadius={1}
        setHopRadius={setHopRadius}
      />
    );

    // Breadcrumbs
    expect(screen.getByText('core-backend')).toBeInTheDocument();
    expect(screen.getAllByText('OrderController.cs').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('OrderService.cs').length).toBeGreaterThanOrEqual(1);

    // Dependencies Panels
    expect(screen.getByText(/Incoming Dependencies/i)).toBeInTheDocument();
    expect(screen.getByText(/Outgoing Dependencies/i)).toBeInTheDocument();

    // Check incoming node items
    expect(screen.getAllByText('POST /api/orders').length).toBeGreaterThanOrEqual(1);

    // Check outgoing node items
    expect(screen.getAllByText('IPaymentGateway.cs').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('OrderRepository.cs').length).toBeGreaterThanOrEqual(1);
  });

  it('clicking a breadcrumb calls onNavigateBreadcrumb with index', () => {
    const onNavigateBreadcrumb = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={onNavigateBreadcrumb}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const firstBreadcrumb = screen.getByRole('button', { name: /core-backend/i });
    fireEvent.click(firstBreadcrumb);
    expect(onNavigateBreadcrumb).toHaveBeenCalledWith(0);

    const secondBreadcrumb = screen.getByRole('button', { name: /OrderController\.cs/i });
    fireEvent.click(secondBreadcrumb);
    expect(onNavigateBreadcrumb).toHaveBeenCalledWith(1);
  });

  it('clicking the Back button jumps to the previous breadcrumb', () => {
    const onNavigateBreadcrumb = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={onNavigateBreadcrumb}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const backButton = screen.getByRole('button', { name: /^back$/i });
    fireEvent.click(backButton);
    // Since breadcrumbs.length is 3, previous index is 1
    expect(onNavigateBreadcrumb).toHaveBeenCalledWith(1);
  });

  it('clicking hop radius toggle calls setHopRadius', () => {
    const setHopRadius = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={setHopRadius}
      />
    );

    const hop2Button = screen.getByRole('button', { name: /2-Hop/i });
    fireEvent.click(hop2Button);
    expect(setHopRadius).toHaveBeenCalledWith(2);

    const hop1Button = screen.getByRole('button', { name: /1-Hop/i });
    fireEvent.click(hop1Button);
    expect(setHopRadius).toHaveBeenCalledWith(1);
  });

  it('clicking a neighbor node in the canvas calls onSelectFocalNode', () => {
    const onSelectFocalNode = vi.fn();

    const { container } = render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={onSelectFocalNode}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const neighborElement = container.querySelector('[data-node-id="callee-1"]');
    expect(neighborElement).toBeInTheDocument();

    if (neighborElement) {
      fireEvent.click(neighborElement);
      expect(onSelectFocalNode).toHaveBeenCalledWith('callee-1');
    }
  });

  it('clicking Focus and Inspect quick action buttons in sidebar columns calls callbacks', () => {
    const onSelectFocalNode = vi.fn();
    const onSelectNodeDetails = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={onSelectFocalNode}
        onSelectNodeDetails={onSelectNodeDetails}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const focusButtons = screen.getAllByRole('button', { name: /Focus/i });
    expect(focusButtons.length).toBeGreaterThan(0);
    fireEvent.click(focusButtons[0]);
    expect(onSelectFocalNode).toHaveBeenCalled();

    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    expect(inspectButtons.length).toBeGreaterThan(0);
    fireEvent.click(inspectButtons[0]);
    expect(onSelectNodeDetails).toHaveBeenCalled();
  });

  it('double clicking a neighbor node in canvas calls onSelectNodeDetails', () => {
    const onSelectNodeDetails = vi.fn();

    const { container } = render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={onSelectNodeDetails}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const neighborElement = container.querySelector('[data-node-id="callee-1"]');
    expect(neighborElement).toBeInTheDocument();

    if (neighborElement) {
      fireEvent.doubleClick(neighborElement);
      expect(onSelectNodeDetails).toHaveBeenCalledWith('callee-1');
    }
  });

  it('handles null and empty graphData gracefully', () => {
    const { rerender } = render(
      <NeighborhoodView
        graphData={null}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    expect(screen.getByText(/No graph data available/i)).toBeInTheDocument();

    rerender(
      <NeighborhoodView
        graphData={{ nodes: [], edges: [], stats: { node_count: 0, edge_count: 0 } }}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    expect(screen.getByText(/No graph data available/i)).toBeInTheDocument();
  });

  it('filters neighbor nodes when typeFilters are provided', () => {
    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={vi.fn()}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
        typeFilters={{ class: true, route: false, file: true, function: true }}
      />
    );

    // Route 'POST /api/orders' should be filtered out
    expect(screen.queryByText('POST /api/orders')).not.toBeInTheDocument();
    // Class 'OrderController.cs' should still be visible in panel / canvas
    expect(screen.getAllByText('OrderController.cs').length).toBeGreaterThanOrEqual(1);
  });

  it('renders direct focal node selector and allows picking any file/node', () => {
    const onSelectFocalNode = vi.fn();

    render(
      <NeighborhoodView
        graphData={mockGraphData}
        focalNodeId="focal-1"
        onSelectFocalNode={onSelectFocalNode}
        onSelectNodeDetails={vi.fn()}
        breadcrumbs={mockBreadcrumbs}
        onNavigateBreadcrumb={vi.fn()}
        hopRadius={1}
        setHopRadius={vi.fn()}
      />
    );

    const select = screen.getByRole('combobox', { name: /Select Focal File or Node/i });
    expect(select).toBeInTheDocument();
    expect(select).toHaveValue('focal-1');

    fireEvent.change(select, { target: { value: 'caller-1' } });
    expect(onSelectFocalNode).toHaveBeenCalledWith('caller-1');
  });
});
