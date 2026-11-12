import type { TopologyNode } from '../../types';

export interface DependencyNeighborItem {
  node: TopologyNode;
  edgeType?: string;
  label?: string;
}

interface NeighborhoodDependencyPanelProps {
  direction: 'incoming' | 'outgoing';
  items: DependencyNeighborItem[];
  onSelectFocalNode: (nodeId: string) => void;
  onSelectNodeDetails: (nodeId: string) => void;
}

export function NeighborhoodDependencyPanel({
  direction,
  items,
  onSelectFocalNode,
  onSelectNodeDetails,
}: NeighborhoodDependencyPanelProps) {
  const isIncoming = direction === 'incoming';
  const title = isIncoming ? 'Incoming Dependencies' : 'Outgoing Dependencies';
  const icon = isIncoming ? 'fa-arrow-right-to-bracket' : 'fa-arrow-right-from-bracket';
  const emptyText = isIncoming ? 'No incoming dependencies' : 'No outgoing dependencies';
  const keyPrefix = isIncoming ? 'in' : 'out';

  return (
    <div className={`neighborhood-panel neighborhood-panel-${direction}`}>
      <div className="neighborhood-panel-header">
        <div className="neighborhood-panel-title">
          <i className={`fa-solid ${icon}`}></i> {title}
        </div>
        <span className="neighborhood-panel-count">{items.length}</span>
      </div>

      <div className="neighborhood-panel-list">
        {items.length === 0 ? (
          <div className="neighborhood-panel-empty">{emptyText}</div>
        ) : (
          items.map((item) => (
            <div key={`${keyPrefix}-${item.node.id}-${item.edgeType}`} className="neighborhood-panel-item">
              <div className="neighborhood-panel-item-header">
                <span className={`topology-badge-type badge-${item.node.type}`}>{item.node.type}</span>
                <span
                  className={`topology-badge-type badge-edge-${(item.edgeType || 'CALLS')
                    .toLowerCase()
                    .replace(/_/g, '-')}`}
                >
                  {item.label || item.edgeType}
                </span>
              </div>
              <div className="neighborhood-panel-item-name" title={item.node.name}>
                {item.node.name}
              </div>
              <div className="neighborhood-panel-item-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-xs"
                  onClick={() => onSelectFocalNode(item.node.id)}
                  title="Focus node"
                >
                  Focus
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-xs"
                  onClick={() => onSelectNodeDetails(item.node.id)}
                  title="Inspect details"
                >
                  Inspect
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
