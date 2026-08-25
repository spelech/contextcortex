import type { FormEvent } from 'react';

interface AddRepoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (e: FormEvent) => void;
  alias: string;
  setAlias: (val: string) => void;
  url: string;
  setUrl: (val: string) => void;
  branch: string;
  setBranch: (val: string) => void;
  provider: string;
  setProvider: (val: string) => void;
  authUser: string;
  setAuthUser: (val: string) => void;
  token: string;
  setToken: (val: string) => void;
  isSaving: boolean;
}

export function AddRepoModal({
  isOpen,
  onClose,
  onSave,
  alias,
  setAlias,
  url,
  setUrl,
  branch,
  setBranch,
  provider,
  setProvider,
  authUser,
  setAuthUser,
  token,
  setToken,
  isSaving,
}: AddRepoModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="glass-card modal-card">
        <div className="modal-header">
          <h2>
            <i className="fa-solid fa-code-branch"></i> Register Git Repository
          </h2>
          <button className="btn-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <form onSubmit={onSave}>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="repo-alias">Repository Alias / Identifier</label>
              <input
                type="text"
                id="repo-alias"
                required
                placeholder="e.g. backend-api or contextcortex"
                value={alias}
                onChange={(e) => setAlias(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label htmlFor="repo-provider">Git Provider</label>
              <select
                id="repo-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="auto">Auto-Detect</option>
                <option value="github">GitHub / GitHub Enterprise</option>
                <option value="gitlab">GitLab (Cloud / Self-Hosted)</option>
                <option value="gitea">Gitea / Forgejo</option>
                <option value="bitbucket">Bitbucket</option>
                <option value="generic">Generic Git (HTTP / HTTPS)</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="repo-url">Git Clone URL (HTTP / HTTPS)</label>
            <input
              type="text"
              id="repo-url"
              required
              placeholder="https://github.com/owner/repo.git or http://git.lan:3000/repo.git"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="form-row form-row-3col">
            <div className="form-group">
              <label htmlFor="repo-branch">Branch / Tag</label>
              <input
                type="text"
                id="repo-branch"
                placeholder="main"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label htmlFor="repo-user">Auth User (Optional)</label>
              <input
                type="text"
                id="repo-user"
                placeholder="e.g. oauth2"
                value={authUser}
                onChange={(e) => setAuthUser(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label htmlFor="repo-token">Auth Token (Optional)</label>
              <input
                type="password"
                id="repo-token"
                placeholder="Token override"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSaving}>
              {isSaving ? (
                <>
                  <i className="fa-solid fa-spinner fa-spin"></i> Adding & Syncing...
                </>
              ) : (
                'Add & Start Sync'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
