import { useState, useEffect, useRef, useCallback } from 'react';
import type { DiagnosticLog } from './types';
import { useToast } from './ToastContext';

type LevelFilter = 'ALL' | 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';

export default function DiagnosticsViewer() {
  const toast = useToast();
  const [logs, setLogs] = useState<DiagnosticLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedTracebacks, setExpandedTracebacks] = useState<Set<number>>(new Set());

  const logEndRef = useRef<HTMLDivElement>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/admin/api/logs');
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setLogs(Array.isArray(data) ? data : []);
    } catch (err: any) {
      toast.error(`Failed to load diagnostics logs: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadLogs();
    const interval = setInterval(loadLogs, 8000);
    return () => clearInterval(interval);
  }, [loadLogs]);

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleClearLogs = async () => {
    if (!window.confirm('Are you sure you want to clear all server diagnostics logs?')) {
      return;
    }
    try {
      const res = await fetch('/admin/api/logs', {
        method: 'DELETE'
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      setLogs([]);
      setExpandedTracebacks(new Set());
      toast.success('Diagnostics logs cleared.');
    } catch (err: any) {
      toast.error(`Failed to clear logs: ${err.message}`);
    }
  };

  const toggleTraceback = (idx: number) => {
    setExpandedTracebacks((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  const getLevelBadgeClass = (level: string) => {
    switch (level.toUpperCase()) {
      case 'ERROR':
        return 'badge badge-danger';
      case 'WARNING':
        return 'badge badge-warning';
      case 'INFO':
        return 'badge badge-primary';
      case 'DEBUG':
        return 'badge badge-secondary';
      default:
        return 'badge badge-secondary';
    }
  };

  const filteredLogs = logs.filter((log) => {
    if (levelFilter !== 'ALL' && log.level.toUpperCase() !== levelFilter) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchMsg = log.message?.toLowerCase().includes(q);
      const matchLogger = log.logger?.toLowerCase().includes(q);
      const matchTrace = log.traceback?.toLowerCase().includes(q);
      const matchLevel = log.level?.toLowerCase().includes(q);
      if (!matchMsg && !matchLogger && !matchTrace && !matchLevel) {
        return false;
      }
    }
    return true;
  });

  const levelCounts = {
    ALL: logs.length,
    INFO: logs.filter((l) => l.level === 'INFO').length,
    WARNING: logs.filter((l) => l.level === 'WARNING').length,
    ERROR: logs.filter((l) => l.level === 'ERROR').length,
    DEBUG: logs.filter((l) => l.level === 'DEBUG').length
  };

  return (
    <div className="tab-content active">
      <div className="glass-card log-viewer-container">
        <div className="log-viewer-header">
          <div>
            <h2>
              <i className="fa-solid fa-terminal"></i> Diagnostics & Server Logs
            </h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Inspect real-time server runtime events, tree-sitter AST parsing, background indexing, and MCP tool traces.
            </p>
          </div>
          <div className="log-viewer-actions">
            <label className="log-autoscroll-label">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Auto-scroll
            </label>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={loadLogs}
              disabled={loading}
              title="Refresh logs"
            >
              <i className={`fa-solid fa-rotate ${loading ? 'fa-spin' : ''}`}></i> Refresh
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={handleClearLogs}
              title="Clear all logs"
            >
              <i className="fa-solid fa-trash-can"></i> Clear Logs
            </button>
          </div>
        </div>

        <div className="log-toolbar">
          <div className="log-filter-pills">
            {(['ALL', 'INFO', 'WARNING', 'ERROR', 'DEBUG'] as LevelFilter[]).map((lvl) => (
              <button
                key={lvl}
                type="button"
                className={`log-filter-btn ${levelFilter === lvl ? 'active' : ''} ${lvl.toLowerCase()}`}
                onClick={() => setLevelFilter(lvl)}
              >
                {lvl} <span className="pill-count">{levelCounts[lvl]}</span>
              </button>
            ))}
          </div>
          <div className="log-search-wrapper">
            <i className="fa-solid fa-magnifying-glass search-icon"></i>
            <input
              type="text"
              className="log-search-input"
              placeholder="Search logs by message, logger, or traceback..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                type="button"
                className="clear-search-btn"
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                <i className="fa-solid fa-xmark"></i>
              </button>
            )}
          </div>
        </div>

        <div className="log-stream-container" ref={logContainerRef}>
          {filteredLogs.length === 0 ? (
            <div className="empty-state">
              <i className="fa-solid fa-circle-info" style={{ fontSize: '2rem', marginBottom: '12px', opacity: 0.5 }}></i>
              <p>No logs available {searchQuery || levelFilter !== 'ALL' ? 'matching current filter' : ''}.</p>
            </div>
          ) : (
            <div className="log-stream-list">
              {filteredLogs.map((log, idx) => {
                const hasTraceback = Boolean(log.traceback);
                const isExpanded = expandedTracebacks.has(idx);
                return (
                  <div
                    key={`${log.timestamp}-${idx}`}
                    className={`log-entry log-level-${log.level.toLowerCase()} ${hasTraceback ? 'has-traceback' : ''}`}
                  >
                    <div className="log-entry-main">
                      <span className="log-timestamp">{log.timestamp}</span>
                      <span className={getLevelBadgeClass(log.level)}>{log.level}</span>
                      <span className="log-logger code">{log.logger}</span>
                      <span className="log-message">{log.message}</span>
                      {hasTraceback && (
                        <button
                          type="button"
                          className="btn-traceback-toggle"
                          onClick={() => toggleTraceback(idx)}
                          title="Toggle traceback details"
                        >
                          <i className={`fa-solid ${isExpanded ? 'fa-chevron-down' : 'fa-chevron-right'}`}></i>
                          <span>{isExpanded ? 'Hide Stack Trace' : 'View Stack Trace'}</span>
                        </button>
                      )}
                    </div>
                    {hasTraceback && isExpanded && (
                      <div className="log-traceback-wrapper">
                        <pre className="traceback-box">{log.traceback}</pre>
                      </div>
                    )}
                  </div>
                );
              })}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
