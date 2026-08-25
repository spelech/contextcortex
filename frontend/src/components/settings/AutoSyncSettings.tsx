import React from 'react';
import type { FormEvent } from 'react';

interface AutoSyncSettingsProps {
  isLoadingAutoSync: boolean;
  intervalMins: number;
  setIntervalMins: (val: number) => void;
  hasGlobalSecret: boolean;
  showWebhookSecret: boolean;
  setShowWebhookSecret: React.Dispatch<React.SetStateAction<boolean>>;
  webhookSecret: string;
  setWebhookSecret: (val: string) => void;
  fullWebhookUrl: string;
  copiedWebhookUrl: boolean;
  isSavingAutoSync: boolean;
  onSaveAutoSync: (e: FormEvent) => void;
  onClearWebhookSecret: () => void;
  onCopyWebhookUrl: () => void;
}

export function AutoSyncSettings({
  isLoadingAutoSync,
  intervalMins,
  setIntervalMins,
  hasGlobalSecret,
  showWebhookSecret,
  setShowWebhookSecret,
  webhookSecret,
  setWebhookSecret,
  fullWebhookUrl,
  copiedWebhookUrl,
  isSavingAutoSync,
  onSaveAutoSync,
  onClearWebhookSecret,
  onCopyWebhookUrl,
}: AutoSyncSettingsProps) {
  return (
    <div className="glass-card">
      <h2><i className="fa-solid fa-arrows-rotate"></i> Auto-Sync &amp; Webhooks</h2>
      <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
        Configure scheduled background repository polling interval and global incoming webhook triggers.
      </p>

      {isLoadingAutoSync && !intervalMins ? (
        <p className="text-muted" style={{ marginTop: '12px' }}>Loading auto-sync settings...</p>
      ) : (
        <form onSubmit={onSaveAutoSync} style={{ marginTop: '16px' }}>
          <div className="form-row">
            <div className="form-group" style={{ flex: 1 }}>
              <label htmlFor="auto-sync-interval">Repository Polling Interval</label>
              <select
                id="auto-sync-interval"
                value={intervalMins}
                onChange={e => setIntervalMins(Number(e.target.value))}
                style={{ width: '100%' }}
              >
                <option value={0}>Disabled (0m)</option>
                <option value={5}>5 minutes</option>
                <option value={15}>15 minutes (Default)</option>
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
                <option value={360}>6 hours</option>
                {![0, 5, 15, 30, 60, 360].includes(intervalMins) && (
                  <option value={intervalMins}>{intervalMins} minutes (Custom)</option>
                )}
              </select>
            </div>

            <div className="form-group" style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <label htmlFor="auto-sync-secret" style={{ marginBottom: 0 }}>Global Webhook Secret (HMAC / Token)</label>
                {hasGlobalSecret ? (
                  <span className="badge badge-accent">Secret Active</span>
                ) : (
                  <span className="badge badge-secondary" style={{ color: 'var(--text-muted)' }}>None</span>
                )}
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  id="auto-sync-secret"
                  type={showWebhookSecret ? 'text' : 'password'}
                  value={webhookSecret}
                  onChange={e => setWebhookSecret(e.target.value)}
                  placeholder={hasGlobalSecret ? 'Secret configured (enter new to change)' : 'Enter webhook secret (optional)'}
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowWebhookSecret(!showWebhookSecret)}
                  title={showWebhookSecret ? 'Hide secret' : 'Reveal secret'}
                  aria-label={showWebhookSecret ? 'Hide secret' : 'Reveal secret'}
                  style={{ minWidth: '42px', padding: '0 12px' }}
                >
                  <i className={`fa-solid ${showWebhookSecret ? 'fa-eye-slash' : 'fa-eye'}`}></i>
                </button>
                {(hasGlobalSecret || webhookSecret) && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={onClearWebhookSecret}
                    title="Clear secret"
                    aria-label="Clear secret"
                    disabled={isSavingAutoSync}
                    style={{ padding: '0 12px' }}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="form-group" style={{ marginTop: '14px' }}>
            <label htmlFor="auto-sync-webhook-url">Incoming Webhook Payload URL</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                id="auto-sync-webhook-url"
                type="text"
                readOnly
                value={fullWebhookUrl}
                style={{ fontFamily: 'monospace', fontSize: '0.85rem', flex: 1 }}
                aria-label="Webhook Payload URL"
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onCopyWebhookUrl}
                style={{ minWidth: '95px' }}
                aria-label="Copy Webhook URL"
              >
                <i className={`fa-solid ${copiedWebhookUrl ? 'fa-check' : 'fa-copy'}`}></i>{' '}
                {copiedWebhookUrl ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: '6px' }}>
              Payload URL for repository push webhooks. Webhooks trigger immediate background synchronization for registered repositories.
            </p>
          </div>

          <div style={{ display: 'flex', gap: '10px', marginTop: '18px' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSavingAutoSync}
            >
              {isSavingAutoSync ? (
                <><i className="fa-solid fa-spinner fa-spin"></i> Saving...</>
              ) : (
                <><i className="fa-solid fa-floppy-disk"></i> Save Auto-Sync Settings</>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
