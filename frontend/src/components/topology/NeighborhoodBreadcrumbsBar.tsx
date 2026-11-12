import React from 'react';
import type { TopologyNode, FocalBreadcrumb } from '../../types';

interface NeighborhoodBreadcrumbsBarProps {
  breadcrumbs: FocalBreadcrumb[];
  onNavigateBreadcrumb: (index: number) => void;
  focalNodeId: string;
  onSelectFocalNode: (nodeId: string) => void;
  groupedNodes: Record<string, TopologyNode[]>;
  hopRadius: 1 | 2;
  setHopRadius: (hops: 1 | 2) => void;
}

export function NeighborhoodBreadcrumbsBar({
  breadcrumbs,
  onNavigateBreadcrumb,
  focalNodeId,
  onSelectFocalNode,
  groupedNodes,
  hopRadius,
  setHopRadius,
}: NeighborhoodBreadcrumbsBarProps) {
  return (
    <div className="neighborhood-breadcrumbs">
      <div className="neighborhood-breadcrumbs-left">
        <button
          type="button"
          className="btn btn-secondary btn-sm neighborhood-back-btn"
          disabled={breadcrumbs.length <= 1}
          onClick={() => {
            if (breadcrumbs.length > 1) {
              onNavigateBreadcrumb(breadcrumbs.length - 2);
            }
          }}
          aria-label="Back"
        >
          <i className="fa-solid fa-arrow-left"></i> Back
        </button>

        <nav className="neighborhood-breadcrumb-trail" aria-label="Breadcrumb">
          {breadcrumbs.map((bc, index) => {
            const isLast = index === breadcrumbs.length - 1;
            return (
              <React.Fragment key={`${bc.id}-${index}`}>
                {index > 0 && <span className="neighborhood-breadcrumb-sep">&rsaquo;</span>}
                <button
                  type="button"
                  className={`neighborhood-breadcrumb-item ${isLast ? 'active' : ''}`}
                  onClick={() => onNavigateBreadcrumb(index)}
                  title={`Navigate to ${bc.name}`}
                >
                  <span className={`topology-badge-type badge-${bc.type || 'file'} neighborhood-breadcrumb-badge`}>
                    {bc.type || 'file'}
                  </span>
                  <span className="neighborhood-breadcrumb-text">{bc.name}</span>
                </button>
              </React.Fragment>
            );
          })}
        </nav>
      </div>

      <div className="neighborhood-breadcrumbs-right">
        <div className="neighborhood-focal-selector-wrap">
          <label htmlFor="neighborhood-focal-select" className="neighborhood-focal-label">
            <i className="fa-solid fa-crosshairs"></i> Focus:
          </label>
          <select
            id="neighborhood-focal-select"
            className="topology-select neighborhood-focal-select"
            value={focalNodeId}
            onChange={(e) => onSelectFocalNode(e.target.value)}
            aria-label="Select Focal File or Node"
          >
            {Object.entries(groupedNodes).map(([groupName, groupNodes]) => (
              <optgroup key={groupName} label={groupName}>
                {groupNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name} {n.filepath && n.filepath !== n.name ? `(${n.filepath})` : ''}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        <div className="neighborhood-hop-selector" role="group" aria-label="Hop Radius">
          <span className="neighborhood-hop-label">Radius:</span>
          <div className="topology-view-btn-group">
            <button
              type="button"
              className={`topology-view-btn ${hopRadius === 1 ? 'active' : ''}`}
              onClick={() => setHopRadius(1)}
            >
              1-Hop
            </button>
            <button
              type="button"
              className={`topology-view-btn ${hopRadius === 2 ? 'active' : ''}`}
              onClick={() => setHopRadius(2)}
            >
              2-Hop
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
