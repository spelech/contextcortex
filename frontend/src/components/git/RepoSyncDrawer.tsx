import { useState, useEffect, useRef, useMemo } from 'react';
import type { GitSyncJob } from '../../types';

export interface RepoSyncDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  repoId?: number | null;
  repoName?: string;
  job?: GitSyncJob | null;
  onCancelSync?: (repoId: number) => Promise<void> | void;
}

const STAGES = [
  { step: 1, title: '1. Connecting & Remote Check' },
  { step: 2, title: '2. Shallow Cloning Repository' },
  { step: 3, title: '3. Computing File Delta & Scanning' },
  { step: 4, title: '4. Parsing AST Symbols & API Routes' },
  { step: 5, title: '5. Upserting Embeddings & Finalizing' },
];

export function RepoSyncDrawer({
  isOpen,
  onClose,
  repoId,
  repoName,
  job,
  onCancelSync,
}: RepoSyncDrawerProps) {
  const [filterText, setFilterText] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [cancelling, setCancelling] = useState(false);

  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const logsContainerRef = useRef<HTMLDivElement | null>(null);

  const activeRepoId = repoId ?? job?.repo_id ?? null;
  const displayName = repoName || job?.repo_name || 'Repository';

  // Calculate elapsed time
  useEffect(() => {
    if (!isOpen || !job?.started_at) {
      setElapsed(0);
      return;
    }

    const calcElapsed = () => {
      const startedMs = job.started_at > 1e11 ? job.started_at : job.started_at * 1000;
      const now = Date.now();
      return Math.max(0, Math.floor((now - startedMs) / 1000));
    };

    setElapsed(calcElapsed());

    if (job.status === 'syncing' || job.status === 'pending') {
      const interval = setInterval(() => {
        setElapsed(calcElapsed());
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [isOpen, job?.started_at, job?.status]);

  const formatElapsed = (totalSeconds: number) => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Filter logs
  const jobLogs = job?.logs;
  const filteredLogs = useMemo(() => {
    const logs = jobLogs || [];
    if (!filterText.trim()) return logs;
    const query = filterText.toLowerCase();
    return logs.filter(
      (l) =>
        l.message.toLowerCase().includes(query) ||
        l.level.toLowerCase().includes(query) ||
        l.timestamp.toLowerCase().includes(query)
    );
  }, [jobLogs, filterText]);

  // Autoscroll to bottom
  useEffect(() => {
    if (autoScroll && logsEndRef.current && typeof logsEndRef.current.scrollIntoView === 'function') {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [filteredLogs, autoScroll]);

  const handleCopyLogs = async () => {
    const logs = job?.logs || [];
    const textToCopy = logs
      .map((l) => `[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}`)
      .join('\n');

    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy logs:', err);
    }
  };

  const handleCancel = async () => {
    if (!activeRepoId || !onCancelSync) return;
    try {
      setCancelling(true);
      await onCancelSync(activeRepoId);
    } catch (err) {
      console.error('Failed to cancel sync:', err);
    } finally {
      setCancelling(false);
    }
  };

  if (!isOpen) return null;

  const status = job?.status || 'pending';
  const percent = job?.percent ?? (status === 'synced' ? 100 : 0);
  const currentStep = job?.step ?? (status === 'synced' ? 5 : 1);

  return (
    <div
      className="sync-drawer-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="sync-drawer-backdrop"
    >
      <div className="sync-drawer">
        {/* Header */}
        <div className="sync-drawer-header">
          <div className="sync-drawer-title-group">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 700, color: 'var(--text)' }}>
                <i className="fa-solid fa-code-branch" style={{ marginRight: '8px', color: 'var(--primary)' }} />
                {displayName} Ingestion Progress & Live Logs
              </h2>
              {status === 'syncing' ? (
                <span className="badge badge-warning">
                  <i className="fa-solid fa-spinner fa-spin"></i> Syncing
                </span>
              ) : status === 'synced' ? (
                <span className="badge badge-success">
                  <i className="fa-solid fa-check"></i> Synced
                </span>
              ) : status === 'error' ? (
                <span className="badge badge-danger">
                  <i className="fa-solid fa-circle-exclamation"></i> Error
                </span>
              ) : (
                <span className="badge badge-primary">
                  <i className="fa-solid fa-clock"></i> Pending
                </span>
              )}
            </div>

            <div className="sync-drawer-meta" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '6px', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              <span>
                <i className="fa-regular fa-clock" style={{ marginRight: '4px' }}></i>
                Elapsed: <strong>{formatElapsed(elapsed)}</strong>
              </span>
              {job?.step_name && (
                <span>
                  &bull; Current: <strong>{job.step_name}</strong>
                </span>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {status === 'syncing' && onCancelSync && activeRepoId != null && (
              <button
                type="button"
                className="btn btn-secondary btn-cancel-sync"
                onClick={handleCancel}
                disabled={cancelling}
                style={{
                  fontSize: '0.8rem',
                  padding: '6px 12px',
                  color: 'var(--danger)',
                  borderColor: 'rgba(239, 68, 68, 0.4)',
                }}
              >
                <i className={`fa-solid ${cancelling ? 'fa-spinner fa-spin' : 'fa-stop'}`}></i>
                {cancelling ? 'Cancelling...' : 'Cancel Sync'}
              </button>
            )}
            <button
              className="btn-close"
              onClick={onClose}
              aria-label="Close sync drawer"
              style={{ fontSize: '1.4rem', lineHeight: 1 }}
            >
              &times;
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="sync-drawer-body">
          {/* Progress Overview & Overall Bar */}
          <div className="sync-progress-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', fontSize: '0.85rem' }}>
              <span style={{ fontWeight: 600, color: 'var(--text)' }}>Overall Ingestion</span>
              <span style={{ fontWeight: 700, color: status === 'error' ? 'var(--danger)' : 'var(--primary)' }}>
                {percent}%
              </span>
            </div>
            <div className="sync-progress-bar-container">
              <div
                className={`sync-progress-bar-fill ${status === 'error' ? 'fill-error' : status === 'synced' ? 'fill-success' : 'fill-active'}`}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>

          {/* Stepper Checklist */}
          <div className="sync-stepper-container">
            <h4 style={{ fontSize: '0.82rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '10px' }}>
              Ingestion Stages
            </h4>
            <div className="sync-stepper-list">
              {STAGES.map((s) => {
                const isCompleted = status === 'synced' || (status !== 'error' && currentStep > s.step) || (status === 'error' && currentStep > s.step);
                const isActive = status === 'syncing' && currentStep === s.step;
                const isError = status === 'error' && currentStep === s.step;
                const isPending = !isCompleted && !isActive && !isError;

                return (
                  <div
                    key={s.step}
                    className={`sync-stepper-item ${isCompleted ? 'item-completed' : isActive ? 'item-active' : isError ? 'item-error' : 'item-pending'}`}
                  >
                    <div className="sync-stepper-icon">
                      {isCompleted && <i className="fa-solid fa-circle-check" style={{ color: '#10b981' }} />}
                      {isActive && <i className="fa-solid fa-spinner fa-spin" style={{ color: '#f59e0b' }} />}
                      {isError && <i className="fa-solid fa-circle-xmark" style={{ color: '#ef4444' }} />}
                      {isPending && <i className="fa-regular fa-circle" style={{ color: 'var(--text-muted)' }} />}
                    </div>

                    <div className="sync-stepper-content">
                      <div className="sync-stepper-title" style={{ fontWeight: isActive ? 600 : 500 }}>
                        {s.title}
                      </div>

                      {/* Active Step Details */}
                      {isActive && (
                        <div className="sync-stepper-details">
                          {job?.current_file && (
                            <div className="sync-current-file">
                              <i className="fa-solid fa-file-code" style={{ marginRight: '4px' }} />
                              <code>{job.current_file}</code>
                            </div>
                          )}
                          {job?.total_files != null && job.total_files > 0 && (
                            <div className="sync-file-count" style={{ marginTop: '2px', color: 'var(--text-muted)' }}>
                              {job.processed_files} / {job.total_files} files ({percent}%)
                            </div>
                          )}
                        </div>
                      )}

                      {/* Error Step Details */}
                      {isError && job?.error && (
                        <div className="sync-stepper-error-msg" style={{ marginTop: '4px', color: 'var(--danger)', fontSize: '0.82rem' }}>
                          <i className="fa-solid fa-triangle-exclamation" style={{ marginRight: '4px' }} />
                          {job.error}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Terminal Log Console */}
          <div className="sync-terminal-section">
            <div className="sync-terminal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <i className="fa-solid fa-terminal" style={{ color: 'var(--accent)' }} />
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>Live Terminal Output</span>
                <span className="badge badge-secondary" style={{ fontSize: '0.75rem', padding: '1px 6px' }}>
                  {filteredLogs.length} {filteredLogs.length === 1 ? 'event' : 'events'}
                </span>
              </div>

              <div className="sync-terminal-actions">
                <label className="sync-autoscroll-toggle">
                  <input
                    type="checkbox"
                    checked={autoScroll}
                    onChange={(e) => setAutoScroll(e.target.checked)}
                    aria-label="Autoscroll"
                  />
                  <span>Autoscroll</span>
                </label>

                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleCopyLogs}
                  aria-label="Copy logs"
                  style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                >
                  <i className={`fa-solid ${copied ? 'fa-check' : 'fa-copy'}`}></i>{' '}
                  {copied ? 'Copied!' : 'Copy Logs'}
                </button>
              </div>
            </div>

            {/* Filter Search Bar */}
            <div className="sync-terminal-search">
              <i className="fa-solid fa-magnifying-glass" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }} />
              <input
                type="text"
                placeholder="Filter logs by keyword or level..."
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                style={{
                  width: '100%',
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--text)',
                  fontSize: '0.82rem',
                  padding: '4px 0',
                }}
              />
              {filterText && (
                <button
                  type="button"
                  onClick={() => setFilterText('')}
                  style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
                >
                  &times;
                </button>
              )}
            </div>

            {/* Terminal Logs Output */}
            <div className="sync-terminal-body" ref={logsContainerRef}>
              {filteredLogs.length === 0 ? (
                <div className="sync-terminal-empty">
                  <i className="fa-solid fa-clock-rotate-left" style={{ marginBottom: '6px', fontSize: '1.2rem', opacity: 0.5 }} />
                  <div>{(jobLogs?.length || 0) === 0 ? 'Waiting for sync activity...' : 'No logs matching filter'}</div>
                </div>
              ) : (
                <div className="sync-terminal-lines">
                  {filteredLogs.map((log, idx) => {
                    const level = (log.level || 'INFO').toUpperCase();
                    let levelClass = 'level-info';
                    if (level === 'WARN' || level === 'WARNING') levelClass = 'level-warn';
                    if (level === 'ERROR' || level === 'FATAL') levelClass = 'level-error';

                    return (
                      <div key={idx} className="sync-terminal-line">
                        <span className="log-time">[{log.timestamp}]</span>
                        <span className={`log-badge ${levelClass}`}>{level}</span>
                        <span className="log-msg">{log.message}</span>
                      </div>
                    );
                  })}
                  <div ref={logsEndRef} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
