import type { NodeDetails } from '../../types';

interface TopologyInspectorProps {
  isOpen: boolean;
  onClose: () => void;
  loadingDetails: boolean;
  nodeDetails: NodeDetails | null;
  onFocusNode: (id: string) => void;
  onSetRootNode: (name: string) => void;
}

export function TopologyInspector({
  isOpen,
  onClose,
  loadingDetails,
  nodeDetails,
  onFocusNode,
  onSetRootNode,
}: TopologyInspectorProps) {
  if (!isOpen) return null;

  return (
    <div className="topology-drawer">
      <div className="topology-drawer-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className={`topology-badge-type badge-${nodeDetails?.type || 'file'}`}>
            {nodeDetails?.type || 'NODE'}
          </span>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text)' }}>
            {nodeDetails?.name || 'Inspecting Node'}
          </h3>
        </div>
        <button
          className="btn btn-secondary btn-sm"
          onClick={onClose}
          aria-label="Close Inspector"
        >
          <i className="fa-solid fa-xmark"></i>
        </button>
      </div>

      <div className="topology-drawer-body">
        {loadingDetails && (
          <div className="topology-empty-state" style={{ height: '200px' }}>
            <i className="fa-solid fa-spinner fa-spin fa-lg"></i>
            <p>Loading node details...</p>
          </div>
        )}

        {!loadingDetails && nodeDetails && (
          <>
            {/* Location & Repo */}
            <div className="topology-drawer-section">
              <span className="topology-drawer-section-title">Location & Repository</span>
              <div style={{ fontSize: '0.85rem', color: 'var(--text)' }}>
                <div><strong>Repo:</strong> <span className="code">{nodeDetails.repo}</span></div>
                {nodeDetails.filepath && (
                  <div style={{ marginTop: '4px' }}>
                    <strong>File:</strong> <span className="code">{nodeDetails.filepath}</span>
                  </div>
                )}
                {nodeDetails.start_line && (
                  <div style={{ marginTop: '4px' }}>
                    <strong>Lines:</strong> {nodeDetails.start_line} – {nodeDetails.end_line || nodeDetails.start_line}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
                {nodeDetails.permalink && (
                  <a
                    href={nodeDetails.permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-secondary btn-sm"
                  >
                    <i className="fa-solid fa-arrow-up-right-from-square"></i> Open in Git Provider
                  </a>
                )}
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    onSetRootNode(nodeDetails.name);
                    onClose();
                  }}
                  title="Focus subgraph from this root node"
                >
                  <i className="fa-solid fa-crosshairs"></i> Set as Root Node
                </button>
              </div>
            </div>

            {/* Signature / Code Preview */}
            {(nodeDetails.signature || nodeDetails.code_preview) && (
              <div className="topology-drawer-section">
                <span className="topology-drawer-section-title">Source Code / Signature</span>
                <pre className="topology-code-snippet">
                  {nodeDetails.code_preview || nodeDetails.signature}
                </pre>
              </div>
            )}

            {/* Incoming Connections */}
            <div className="topology-drawer-section">
              <span className="topology-drawer-section-title">
                Incoming Connections ({nodeDetails.incoming.length})
              </span>
              {nodeDetails.incoming.length === 0 ? (
                <p className="text-muted" style={{ fontSize: '0.8rem' }}>No incoming connections detected.</p>
              ) : (
                <div className="topology-neighbor-list">
                  {nodeDetails.incoming.map((inc, i) => (
                    <div
                      key={`inc-${i}`}
                      className="topology-neighbor-item"
                      onClick={() => onFocusNode(inc.id)}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className={`topology-badge-type badge-edge-${inc.edge_type.toLowerCase()}`}>
                          {inc.edge_type}
                        </span>
                        <span style={{ fontWeight: 500 }}>{inc.name}</span>
                      </div>
                      {inc.line_number && <span className="text-muted">L{inc.line_number}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Outgoing Connections */}
            <div className="topology-drawer-section">
              <span className="topology-drawer-section-title">
                Outgoing Connections ({nodeDetails.outgoing.length})
              </span>
              {nodeDetails.outgoing.length === 0 ? (
                <p className="text-muted" style={{ fontSize: '0.8rem' }}>No outgoing connections detected.</p>
              ) : (
                <div className="topology-neighbor-list">
                  {nodeDetails.outgoing.map((out, i) => (
                    <div
                      key={`out-${i}`}
                      className="topology-neighbor-item"
                      onClick={() => onFocusNode(out.id)}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className={`topology-badge-type badge-edge-${out.edge_type.toLowerCase()}`}>
                          {out.edge_type}
                        </span>
                        <span style={{ fontWeight: 500 }}>{out.name}</span>
                      </div>
                      {out.line_number && <span className="text-muted">L{out.line_number}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
