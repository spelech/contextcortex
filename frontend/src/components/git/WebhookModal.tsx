import type { Repo } from '../../types';

interface WebhookModalProps {
  repo: Repo | null;
  onClose: () => void;
  onCopyUrl: (text: string) => void;
  copiedUrl: boolean;
}

export function WebhookModal({ repo, onClose, onCopyUrl, copiedUrl }: WebhookModalProps) {
  if (!repo) return null;

  const currentOrigin = typeof window !== 'undefined' ? window.location.origin : '';
  const webhookEndpoint = `${currentOrigin}/api/webhooks/git`;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="webhook-modal-backdrop"
    >
      <div className="glass-card modal-card" style={{ maxWidth: '650px' }}>
        <div className="modal-header">
          <h2>
            <i className="fa-solid fa-bolt"></i> Webhook Setup: {repo.name}
          </h2>
          <button
            className="btn-close"
            onClick={onClose}
            aria-label="Close webhook modal"
          >
            &times;
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '0.9rem' }}>
          <p className="text-muted">
            Configure a webhook in your Git repository provider to automatically trigger synchronization on every push event.
          </p>

          <div className="form-group">
            <label>Webhook URL (Payload URL)</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                readOnly
                value={webhookEndpoint}
                style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                aria-label="Webhook Payload URL"
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => onCopyUrl(webhookEndpoint)}
                style={{ minWidth: '95px' }}
                aria-label="Copy Webhook URL"
              >
                <i className={`fa-solid ${copiedUrl ? 'fa-check' : 'fa-copy'}`}></i>{' '}
                {copiedUrl ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </div>

          {repo.webhook_secret && (
            <div className="form-group">
              <label>Repository Secret Token (HMAC)</label>
              <input
                type="text"
                readOnly
                value={repo.webhook_secret}
                style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                aria-label="Repository Secret Token"
              />
            </div>
          )}

          <div
            style={{
              background: 'rgba(0, 0, 0, 0.25)',
              border: '1px solid var(--border-card)',
              borderRadius: '8px',
              padding: '14px',
            }}
          >
            <h3 style={{ fontSize: '0.95rem', marginBottom: '10px', color: 'var(--text)' }}>
              <i className="fa-solid fa-list-check"></i> Provider Setup Instructions
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.85rem' }}>
              <div>
                <strong style={{ color: '#fff' }}>
                  <i className="fa-brands fa-github" style={{ marginRight: '6px' }} /> GitHub:
                </strong>
                <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                  Navigate to <code>Settings &gt; Webhooks &gt; Add webhook</code> &rarr; set <em>Payload URL</em> to the URL above &rarr; set <em>Content type</em> to <code>application/json</code> &rarr; select <em>Push events</em> &rarr; click <strong>Add webhook</strong>.
                </div>
              </div>

              <div>
                <strong style={{ color: '#fff' }}>
                  <i className="fa-brands fa-gitlab" style={{ color: '#fc6d26', marginRight: '6px' }} /> GitLab:
                </strong>
                <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                  Navigate to <code>Settings &gt; Webhooks</code> (or <code>Settings &gt; Integrations</code>) &rarr; set <em>URL</em> &rarr; select <em>Push events</em> &rarr; click <strong>Add webhook</strong>.
                </div>
              </div>

              <div>
                <strong style={{ color: '#fff' }}>
                  <i className="fa-solid fa-mug-hot" style={{ color: '#609926', marginRight: '6px' }} /> Gitea / Forgejo:
                </strong>
                <div style={{ color: 'var(--text-muted)', marginTop: '2px', marginLeft: '18px' }}>
                  Navigate to <code>Settings &gt; Webhooks &gt; Add Webhook &gt; Gitea</code> &rarr; set <em>Target URL</em> &rarr; set <em>HTTP Method</em> to <code>POST</code> &rarr; select <em>Push Events</em> &rarr; click <strong>Add Webhook</strong>.
                </div>
              </div>
            </div>
          </div>

          <div className="modal-footer" style={{ marginTop: '8px', padding: 0 }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
