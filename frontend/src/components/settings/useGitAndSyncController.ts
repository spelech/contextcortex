import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { GitHostCredential, AutoSyncSettings } from '../../types';

interface ToastApi {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
}

export function useGitAndSyncController(refreshStats: () => void, toast: ToastApi) {
  const [ghToken, setGhToken] = useState('');
  const [glToken, setGlToken] = useState('');
  const [gtToken, setGtToken] = useState('');
  const [hostCredentials, setHostCredentials] = useState<GitHostCredential[]>([]);

  const [intervalMins, setIntervalMins] = useState<number>(15);
  const [webhookSecret, setWebhookSecret] = useState('');
  const [hasGlobalSecret, setHasGlobalSecret] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState('/api/webhooks/git');
  const [isLoadingAutoSync, setIsLoadingAutoSync] = useState(false);
  const [isSavingAutoSync, setIsSavingAutoSync] = useState(false);
  const [showWebhookSecret, setShowWebhookSecret] = useState(false);
  const [copiedWebhookUrl, setCopiedWebhookUrl] = useState(false);

  const [isHostModalOpen, setIsHostModalOpen] = useState(false);
  const [newHost, setNewHost] = useState('');
  const [newHostProvider, setNewHostProvider] = useState<
    'gitlab' | 'gitea' | 'bitbucket' | 'generic' | 'github'
  >('gitlab');
  const [newHostUser, setNewHostUser] = useState('');
  const [newHostToken, setNewHostToken] = useState('');
  const [isSavingHost, setIsSavingHost] = useState(false);

  const loadHostCredentials = useCallback(async () => {
    try {
      const res = await fetch('/admin/api/settings/hosts');
      if (res.ok) {
        const data = await res.json();
        setHostCredentials(Array.isArray(data) ? data : []);
      }
    } catch (e: any) {
      console.error('Failed to load host credentials:', e);
      setHostCredentials([]);
    }
  }, []);

  const loadAutoSyncSettings = useCallback(async () => {
    setIsLoadingAutoSync(true);
    try {
      const res = await fetch('/admin/api/settings/auto-sync');
      if (res.ok) {
        const data: AutoSyncSettings = await res.json();
        if (typeof data.interval_mins === 'number') setIntervalMins(data.interval_mins);
        if (typeof data.webhook_url === 'string') setWebhookUrl(data.webhook_url);
        if (typeof data.has_global_secret === 'boolean') setHasGlobalSecret(data.has_global_secret);
      }
    } catch (e: any) {
      console.error('Failed to load auto-sync settings:', e);
    } finally {
      setIsLoadingAutoSync(false);
    }
  }, []);

  useEffect(() => {
    loadHostCredentials();
    loadAutoSyncSettings();
  }, [loadHostCredentials, loadAutoSyncSettings]);

  const fullWebhookUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}${webhookUrl || '/api/webhooks/git'}`;

  const handleCopyWebhookUrl = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(fullWebhookUrl);
      }
      setCopiedWebhookUrl(true);
      toast.info('Webhook URL copied to clipboard');
      setTimeout(() => setCopiedWebhookUrl(false), 2000);
    } catch (err: any) {
      toast.error('Failed to copy: ' + err.message);
    }
  };

  const handleSaveAutoSync = async (e: FormEvent) => {
    e.preventDefault();
    setIsSavingAutoSync(true);
    try {
      const payload: { interval_mins: number; global_webhook_secret?: string } = {
        interval_mins: Number(intervalMins),
      };
      if (webhookSecret.trim()) {
        payload.global_webhook_secret = webhookSecret.trim();
      }
      const res = await fetch('/admin/api/settings/auto-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save auto-sync settings');

      if (typeof data.has_global_secret === 'boolean') {
        setHasGlobalSecret(data.has_global_secret);
      } else if (webhookSecret.trim()) {
        setHasGlobalSecret(true);
      }
      if (typeof data.interval_mins === 'number') {
        setIntervalMins(data.interval_mins);
      }
      setWebhookSecret('');
      toast.success('Auto-sync settings saved successfully');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving auto-sync settings: ' + e.message);
    } finally {
      setIsSavingAutoSync(false);
    }
  };

  const handleClearWebhookSecret = async () => {
    if (!hasGlobalSecret) {
      setWebhookSecret('');
      return;
    }
    if (!window.confirm('Clear the global webhook signature secret?')) {
      return;
    }
    setIsSavingAutoSync(true);
    try {
      const res = await fetch('/admin/api/settings/auto-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interval_mins: Number(intervalMins),
          global_webhook_secret: '',
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to clear global webhook secret');

      setHasGlobalSecret(false);
      setWebhookSecret('');
      toast.success('Global webhook secret cleared');
    } catch (e: any) {
      toast.error('Failed to clear webhook secret: ' + e.message);
    } finally {
      setIsSavingAutoSync(false);
    }
  };

  const saveToken = async (
    providerKey: 'github_token' | 'gitlab_token' | 'gitea_token',
    tokenVal: string,
    providerName: string
  ) => {
    if (!tokenVal.trim()) return;
    try {
      const res = await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [providerKey]: tokenVal.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save token');

      toast.success(`${providerName} token saved successfully.`);
      if (providerKey === 'github_token') setGhToken('');
      if (providerKey === 'gitlab_token') setGlToken('');
      if (providerKey === 'gitea_token') setGtToken('');
      refreshStats();
    } catch (e: any) {
      toast.error(`Error saving ${providerName} token: ` + e.message);
    }
  };

  const clearToken = async (
    providerKey: 'github_token' | 'gitlab_token' | 'gitea_token',
    providerName: string
  ) => {
    if (!window.confirm(`Clear the stored ${providerName} token from database?`)) return;
    try {
      const res = await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [providerKey]: '' }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to clear token');
      }
      toast.success(`${providerName} token cleared`);
      refreshStats();
    } catch (e: any) {
      toast.error(`Failed to clear ${providerName} token: ` + e.message);
    }
  };

  const handleSaveHostCredential = async (e: FormEvent) => {
    e.preventDefault();
    if (!newHost.trim() || !newHostToken.trim()) return;
    setIsSavingHost(true);
    try {
      const res = await fetch('/admin/api/settings/hosts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: newHost.trim(),
          provider: newHostProvider,
          auth_user: newHostUser.trim() || null,
          auth_token: newHostToken.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save host credential');

      toast.success(`Host credential for '${newHost.trim()}' saved`);
      setIsHostModalOpen(false);
      setNewHost('');
      setNewHostProvider('gitlab');
      setNewHostUser('');
      setNewHostToken('');
      loadHostCredentials();
    } catch (e: any) {
      toast.error('Error: ' + e.message);
    } finally {
      setIsSavingHost(false);
    }
  };

  const deleteHostCredential = async (id: number, host: string) => {
    if (!window.confirm(`Remove stored credentials for host '${host}'?`)) return;
    try {
      const res = await fetch(`/admin/api/settings/hosts/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to delete');
      }
      toast.success(`Removed credentials for '${host}'`);
      loadHostCredentials();
    } catch (e: any) {
      toast.error('Failed to remove: ' + e.message);
    }
  };

  return {
    ghToken,
    setGhToken,
    glToken,
    setGlToken,
    gtToken,
    setGtToken,
    hostCredentials,
    intervalMins,
    setIntervalMins,
    webhookSecret,
    setWebhookSecret,
    hasGlobalSecret,
    fullWebhookUrl,
    isLoadingAutoSync,
    isSavingAutoSync,
    showWebhookSecret,
    setShowWebhookSecret,
    copiedWebhookUrl,
    isHostModalOpen,
    setIsHostModalOpen,
    newHost,
    setNewHost,
    newHostProvider,
    setNewHostProvider,
    newHostUser,
    setNewHostUser,
    newHostToken,
    setNewHostToken,
    isSavingHost,
    handleCopyWebhookUrl,
    handleSaveAutoSync,
    handleClearWebhookSecret,
    saveToken,
    clearToken,
    handleSaveHostCredential,
    deleteHostCredential,
  };
}
