import { useState, useEffect, useCallback, useRef } from 'react';
import type { GitSyncJob, SyncLogEntry } from '../types';

export interface UseGitSyncStreamReturn {
  syncStates: Record<number, GitSyncJob>;
  isConnected: boolean;
  cancelSync: (repoId: number) => Promise<any>;
}

export function useGitSyncStream(): UseGitSyncStreamReturn {
  const [syncStates, setSyncStates] = useState<Record<number, GitSyncJob>>({});
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchInitialStatus = useCallback(async () => {
    try {
      const res = await fetch('/admin/api/repos/sync-status');
      if (res && res.ok) {
        const snapshot = await res.json();
        if (snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot)) {
          const states: Record<number, GitSyncJob> = {};
          Object.entries(snapshot).forEach(([id, job]) => {
            const j = job as any;
            if (j && (j.repo_id != null || j.step != null || j.status != null)) {
              states[Number(id)] = j as GitSyncJob;
            }
          });
          setSyncStates((prev) => ({ ...prev, ...states }));
        } else if (Array.isArray(snapshot)) {
          const states: Record<number, GitSyncJob> = {};
          snapshot.forEach((item: any) => {
            if (item && item.repo_id != null && (item.step != null || item.status === 'syncing')) {
              states[item.repo_id] = item as GitSyncJob;
            }
          });
          if (Object.keys(states).length > 0) {
            setSyncStates((prev) => ({ ...prev, ...states }));
          }
        }
      }
    } catch (err) {
      console.error('Failed to fetch initial sync status snapshot:', err);
    }
  }, []);

  useEffect(() => {
    fetchInitialStatus();

    if (typeof EventSource === 'undefined') {
      return;
    }

    let es: EventSource | null = null;
    try {
      es = new EventSource('/admin/api/repos/sync/stream');
      eventSourceRef.current = es;

      es.onopen = () => {
        setIsConnected(true);
      };

      es.onerror = () => {
        setIsConnected(false);
      };

      const handleInit = (e: MessageEvent) => {
        try {
          const snapshot = JSON.parse(e.data);
          if (snapshot && typeof snapshot === 'object') {
            const states: Record<number, GitSyncJob> = {};
            Object.entries(snapshot).forEach(([id, job]) => {
              states[Number(id)] = job as GitSyncJob;
            });
            setSyncStates(states);
            setIsConnected(true);
          }
        } catch (err) {
          console.error('Failed to parse init sync stream event:', err);
        }
      };

      const handleProgress = (e: MessageEvent) => {
        try {
          const payload = JSON.parse(e.data);
          const job = (payload.data || payload) as GitSyncJob;
          if (job && job.repo_id != null) {
            setSyncStates((prev) => {
              const existing = prev[job.repo_id];
              return {
                ...prev,
                [job.repo_id]: {
                  ...(existing || {}),
                  ...job,
                  logs: job.logs ?? existing?.logs ?? [],
                },
              };
            });
            setIsConnected(true);
          }
        } catch (err) {
          console.error('Failed to parse progress event:', err);
        }
      };

      const handleLog = (e: MessageEvent) => {
        try {
          const payload = JSON.parse(e.data);
          const repoId = payload.repo_id ?? payload.data?.repo_id;
          const logEntry = (payload.data && !payload.data.repo_id ? payload.data : payload.log || payload.data) as SyncLogEntry;
          if (repoId != null && logEntry) {
            setSyncStates((prev) => {
              const existing = prev[repoId];
              if (!existing) return prev;
              const currentLogs = existing.logs || [];
              return {
                ...prev,
                [repoId]: {
                  ...existing,
                  logs: [...currentLogs, logEntry],
                },
              };
            });
          }
        } catch (err) {
          console.error('Failed to parse log event:', err);
        }
      };

      es.addEventListener('init', handleInit);
      es.addEventListener('progress', handleProgress);
      es.addEventListener('log', handleLog);
    } catch (err) {
      console.error('Failed to initialize EventSource:', err);
      setIsConnected(false);
    }

    return () => {
      if (es) {
        es.close();
        eventSourceRef.current = null;
      }
    };
  }, [fetchInitialStatus]);

  const cancelSync = useCallback(async (repoId: number) => {
    try {
      const res = await fetch(`/admin/api/repos/${repoId}/cancel-sync`, {
        method: 'POST',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `Failed to cancel sync: ${res.statusText}`);
      }
      return await res.json();
    } catch (err) {
      console.error(`Error cancelling sync for repo ${repoId}:`, err);
      throw err;
    }
  }, []);

  return {
    syncStates,
    isConnected,
    cancelSync,
  };
}
