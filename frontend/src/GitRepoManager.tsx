import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { Repo } from './types';
import { useToast } from './ToastContext';
import { AddRepoModal } from './components/git/AddRepoModal';
import { WebhookModal } from './components/git/WebhookModal';
import { RepoListTable } from './components/git/RepoListTable';

export default function GitRepoManager({ refreshStats }: { refreshStats: () => void }) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [webhookModalRepo, setWebhookModalRepo] = useState<Repo | null>(null);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const toast = useToast();

  // Modal form fields
  const [alias, setAlias] = useState('');
  const [url, setUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [provider, setProvider] = useState('auto');
  const [authUser, setAuthUser] = useState('');
  const [token, setToken] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const loadRepos = useCallback(async () => {
    try {
      const response = await fetch('/admin/api/repos');
      if (!response.ok) {
        toast.error('Failed to load repositories');
        return;
      }
      const data = await response.json();
      setRepos(data);
    } catch (e: any) {
      toast.error('Error loading repos: ' + e.message);
      console.error('Error loading repos:', e);
    }
  }, [toast]);

  useEffect(() => {
    loadRepos();
    const interval = setInterval(loadRepos, 8000);
    return () => clearInterval(interval);
  }, [loadRepos]);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const res = await fetch('/admin/api/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: alias.trim(),
          url: url.trim(),
          branch: branch.trim() || 'main',
          provider: provider === 'auto' ? undefined : provider,
          auth_user: authUser.trim() || null,
          auth_token: token.trim() || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to add repository');

      setIsModalOpen(false);
      setAlias('');
      setUrl('');
      setBranch('main');
      setProvider('auto');
      setAuthUser('');
      setToken('');
      loadRepos();
      refreshStats();
      toast.success(`Repository '${alias.trim()}' added successfully`);
    } catch (err: any) {
      toast.error(`Error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const syncRepo = async (id: number) => {
    setRepos((prev) => prev.map((r) => (r.id === id ? { ...r, status: 'syncing' } : r)));
    try {
      const res = await fetch(`/admin/api/repos/sync/${id}`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to trigger sync');
      }
      loadRepos();
      refreshStats();
      toast.info('Sync triggered successfully');
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to trigger sync: ' + e.message);
    }
  };

  const toggleAutoSync = async (repoId: number, currentState: boolean) => {
    const nextState = !currentState;
    setRepos((prev) =>
      prev.map((r) => (r.id === repoId ? { ...r, auto_sync: nextState } : r))
    );

    try {
      const res = await fetch(`/admin/api/repos/${repoId}/auto-sync`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_sync: nextState }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || data.detail || 'Failed to update auto-sync');
      }
      toast.info(`Auto-sync ${nextState ? 'enabled' : 'disabled'}`);
      loadRepos();
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to update auto-sync: ' + e.message);
    }
  };

  const handleCopyUrl = async (text: string) => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      }
      setCopiedUrl(true);
      toast.info('Webhook URL copied to clipboard');
      setTimeout(() => setCopiedUrl(false), 2000);
    } catch (err: any) {
      toast.error('Failed to copy: ' + err.message);
    }
  };

  const deleteRepo = async (id: number, name: string) => {
    if (
      !window.confirm(
        `Are you sure you want to delete repository '${name}'? All vectors and indexed symbols for this repo will be permanently purged.`
      )
    ) {
      return;
    }
    setRepos((prev) => prev.filter((r) => r.id !== id));
    try {
      const res = await fetch(`/admin/api/repos/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to delete repo');
      }
      loadRepos();
      refreshStats();
      toast.success(`Repository '${name}' deleted successfully`);
    } catch (e: any) {
      loadRepos();
      toast.error('Failed to delete repo: ' + e.message);
    }
  };

  return (
    <div className="tab-content active">
      <div className="glass-card">
        <div className="card-header-btn">
          <div>
            <h2><i className="fa-solid fa-code-branch"></i> Registered Git Repositories</h2>
            <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
              Supports GitHub, GitLab, Gitea, Bitbucket, and custom self-hosted Git repositories over HTTP/HTTPS.
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
            <i className="fa-solid fa-plus"></i> Add Repository
          </button>
        </div>

        <RepoListTable
          repos={repos}
          onSync={syncRepo}
          onToggleAutoSync={toggleAutoSync}
          onOpenWebhook={(repo) => setWebhookModalRepo(repo)}
          onDelete={deleteRepo}
        />

        <AddRepoModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          onSave={handleSave}
          alias={alias}
          setAlias={setAlias}
          url={url}
          setUrl={setUrl}
          branch={branch}
          setBranch={setBranch}
          provider={provider}
          setProvider={setProvider}
          authUser={authUser}
          setAuthUser={setAuthUser}
          token={token}
          setToken={setToken}
          isSaving={isSaving}
        />

        <WebhookModal
          repo={webhookModalRepo}
          onClose={() => setWebhookModalRepo(null)}
          onCopyUrl={handleCopyUrl}
          copiedUrl={copiedUrl}
        />
      </div>
    </div>
  );
}
