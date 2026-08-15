import { useState } from 'react';
import type { FormEvent } from 'react';
import type { Stats } from './types';

export default function Settings({ stats, refreshStats }: { stats: Stats | null, refreshStats: () => void }) {
  const [token, setToken] = useState('');

  const saveGitHubToken = async (e: FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;

    try {
      const res = await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ github_token: token.trim() })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save token');

      alert('GitHub Token saved successfully.');
      setToken('');
      refreshStats();
    } catch (e: any) {
      alert('Error saving token: ' + e.message);
    }
  };

  const clearGitHubToken = async () => {
    if (!window.confirm('Clear the stored GitHub token from database?')) return;
    try {
      await fetch('/admin/api/settings/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ github_token: '' })
      });
      refreshStats();
    } catch (e: any) {
      alert('Failed to clear token: ' + e.message);
    }
  };

  return (
    <div className="tab-content active">
      <div className="glass-card" style={{ maxWidth: '700px' }}>
        <h2><i className="fa-solid fa-key"></i> GitHub Authentication & Rate Limits</h2>
        <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>Providing a GitHub Personal Access Token increases API rate limits from 60 to 5,000 requests/hr and enables indexing private repositories.</p>

        <div className="form-group" style={{ marginTop: '20px' }}>
          <label>Active Token Source</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="badge badge-accent">{stats?.token_source || 'None'}</span>
            <span className="code">{stats?.masked_token || 'None'}</span>
          </div>
        </div>

        <form onSubmit={saveGitHubToken} style={{ marginTop: '16px' }}>
          <div className="form-group">
            <label htmlFor="github-token-input">Update GitHub Token</label>
            <input type="password" id="github-token-input" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" value={token} onChange={e => setToken(e.target.value)} />
          </div>
          <div className="form-actions" style={{ display: 'flex', gap: '10px', marginTop: '15px' }}>
            <button type="submit" className="btn btn-primary">Save Token to DB</button>
            <button type="button" className="btn btn-secondary" onClick={clearGitHubToken}>Clear Token</button>
          </div>
        </form>
      </div>
    </div>
  );
}
