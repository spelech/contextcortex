document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadRepos();
    loadPaths();
    
    // Auto-refresh every 8s
    setInterval(loadStats, 8000);
    setInterval(loadRepos, 8000);
    setInterval(loadPaths, 8000);
});

// State
window.allRepos = [];
window.allPaths = [];
window.currentBrowserPath = "/";

// Tab Switching
function switchTab(tabId) {
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = Array.from(document.querySelectorAll('.nav-tab')).find(b => b.getAttribute('onclick')?.includes(tabId));
    if (activeBtn) activeBtn.classList.add('active');

    const contentEl = document.getElementById(`tab-${tabId}`);
    if (contentEl) contentEl.classList.add('active');

    if (tabId === 'settings') {
        loadSettings();
    }
}

// Stats & Overview
async function loadStats() {
    try {
        const response = await fetch('/admin/api/stats');
        if (!response.ok) return;
        const data = await response.json();

        document.getElementById('stat-repos').textContent = data.repos_count || 0;
        document.getElementById('stat-symbols').textContent = data.symbols_count || 0;
        document.getElementById('stat-files').textContent = data.files_count || 0;
        document.getElementById('stat-vectors').textContent = data.points_count || 0;
        document.getElementById('stat-last-indexed').textContent = data.last_indexed || 'Never';

        if (data.dense_model) document.getElementById('spec-dense').textContent = data.dense_model;
        if (data.sparse_model) document.getElementById('spec-sparse').textContent = `${data.sparse_model} (FastEmbed)`;

        // Rate Limit Pill
        const ratePill = document.getElementById('rate-limit-text');
        if (data.rate_limit && data.rate_limit.limit) {
            ratePill.textContent = `${data.rate_limit.remaining} / ${data.rate_limit.limit} reqs`;
        } else {
            ratePill.textContent = 'Active';
        }

        // Tag cloud
        const cloud = document.getElementById('topics-tag-cloud');
        if (cloud && data.top_keywords) {
            if (data.top_keywords.length === 0) {
                cloud.innerHTML = '<span class="text-muted">No topics extracted yet. Sync repositories to populate.</span>';
            } else {
                cloud.innerHTML = data.top_keywords.map(kw => `<span class="topic-tag">${escapeHtml(kw)}</span>`).join('');
            }
        }

        // Indexing indicator
        const indicator = document.getElementById('indexing-indicator');
        const reindexBtn = document.getElementById('btn-reindex');
        if (data.is_indexing) {
            indicator.innerHTML = '<span class="indicator indexing"></span> Syncing...';
            if (reindexBtn) {
                reindexBtn.disabled = true;
                reindexBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Syncing...';
            }
        } else {
            indicator.innerHTML = '<span class="indicator online"></span> Idle';
            if (reindexBtn) {
                reindexBtn.disabled = false;
                reindexBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Reindex All Sources';
            }
        }
    } catch (e) {
        console.error('Error loading stats:', e);
    }
}

// ----------------------------------------------------
// GIT REPOSITORIES
// ----------------------------------------------------

async function loadRepos() {
    try {
        const response = await fetch('/admin/api/repos');
        if (!response.ok) return;
        const repos = await response.json();
        window.allRepos = repos;
        renderRepos(repos);
    } catch (e) {
        console.error('Error loading repos:', e);
    }
}

function renderRepos(repos) {
    const tbody = document.getElementById('repos-list-body');
    if (!tbody) return;

    if (!repos || repos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-state">No Git repositories registered. Click "Add Repository" to index a remote repo.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = repos.map(r => {
        let statusBadge = `<span class="badge badge-success"><i class="fa-solid fa-check"></i> Synced</span>`;
        if (r.status === 'syncing') {
            statusBadge = `<span class="badge badge-warning"><i class="fa-solid fa-spinner fa-spin"></i> Syncing</span>`;
        } else if (r.status === 'error') {
            statusBadge = `<span class="badge badge-danger"><i class="fa-solid fa-circle-exclamation"></i> Error</span>`;
        } else if (r.status === 'pending') {
            statusBadge = `<span class="badge badge-primary"><i class="fa-solid fa-clock"></i> Pending</span>`;
        }

        const shaDisplay = r.commit_sha ? `<code>${r.commit_sha.substring(0, 8)}</code>` : '<span class="text-muted">-</span>';

        return `
            <tr>
                <td><strong>${escapeHtml(r.name)}</strong></td>
                <td><a href="${escapeHtml(r.url)}" target="_blank" style="color: var(--primary); text-decoration: none; font-size: 0.85rem;"><i class="fa-solid fa-arrow-up-right-from-square"></i> ${escapeHtml(r.url)}</a></td>
                <td><code>${escapeHtml(r.branch)}</code></td>
                <td>${shaDisplay}</td>
                <td>${statusBadge}</td>
                <td>${r.file_count || 0} files</td>
                <td style="font-size: 0.8rem; color: var(--text-muted);">${r.last_synced || 'Never'}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.8rem;" onclick="syncRepo(${r.id})" title="Trigger Sync">
                            <i class="fa-solid fa-arrows-rotate"></i> Sync
                        </button>
                        <button class="btn-icon btn-delete" onclick="deleteRepo(${r.id}, '${escapeHtml(r.name)}')" title="Delete Repo">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function openAddRepoModal() {
    document.getElementById('repo-form').reset();
    document.getElementById('repo-modal').style.display = 'flex';
}

function closeRepoModal() {
    document.getElementById('repo-modal').style.display = 'none';
}

async function saveGitRepo(event) {
    event.preventDefault();
    const name = document.getElementById('repo-alias').value.trim();
    const url = document.getElementById('repo-url').value.trim();
    const branch = document.getElementById('repo-branch').value.trim() || 'main';
    const token = document.getElementById('repo-token').value.trim() || null;

    const btn = document.getElementById('btn-save-repo');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Adding & Syncing...';

    try {
        const res = await fetch('/admin/api/repos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url, branch, auth_token: token })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to add repository');

        closeRepoModal();
        loadRepos();
        loadStats();
    } catch (err) {
        alert(`Error: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Add & Start Sync';
    }
}

async function syncRepo(id) {
    try {
        await fetch(`/admin/api/repos/sync/${id}`, { method: 'POST' });
        loadRepos();
        loadStats();
    } catch (e) {
        alert('Failed to trigger sync: ' + e.message);
    }
}

async function deleteRepo(id, name) {
    if (!confirm(`Are you sure you want to delete repository '${name}'? All vectors and indexed symbols for this repo will be permanently purged.`)) {
        return;
    }
    try {
        await fetch(`/admin/api/repos/${id}`, { method: 'DELETE' });
        loadRepos();
        loadStats();
    } catch (e) {
        alert('Failed to delete repo: ' + e.message);
    }
}

// ----------------------------------------------------
// LOCAL PATHS
// ----------------------------------------------------

async function loadPaths() {
    try {
        const response = await fetch('/admin/api/paths');
        if (!response.ok) return;
        const paths = await response.json();
        window.allPaths = paths;
        renderPaths(paths);
    } catch (e) {
        console.error('Error loading paths:', e);
    }
}

function renderPaths(paths) {
    const tbody = document.getElementById('paths-list-body');
    if (!tbody) return;

    if (!paths || paths.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="empty-state">No local paths configured. Defaulting to standard vault.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = paths.map(p => `
        <tr>
            <td><code>${escapeHtml(p.path)}</code></td>
            <td><strong>${escapeHtml(p.repo || 'local')}</strong></td>
            <td><span class="badge badge-primary">${p.type}</span></td>
            <td>${p.recursive ? 'Yes' : 'No'}</td>
            <td>${p.category ? `<span class="badge badge-accent">${escapeHtml(p.category)}</span>` : '<span class="text-muted">-</span>'}</td>
            <td>${p.enabled ? '<span class="badge badge-success">Enabled</span>' : '<span class="badge badge-danger">Disabled</span>'}</td>
            <td>
                <button class="btn-icon btn-delete" onclick="deletePath(${p.id})">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function openAddPathModal() {
    document.getElementById('path-form').reset();
    document.getElementById('path-modal').style.display = 'flex';
}

function closePathModal() {
    document.getElementById('path-modal').style.display = 'none';
}

async function saveLocalPath(event) {
    event.preventDefault();
    const path = document.getElementById('selected-path').value.trim();
    const repo = document.getElementById('path-repo-alias').value.trim() || 'local';
    const category = document.getElementById('path-category').value.trim() || null;
    const type = document.getElementById('path-type').value;
    const recursive = parseInt(document.getElementById('path-recursive').value, 10);

    try {
        const res = await fetch('/admin/api/paths', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, repo, category, type, recursive, enabled: 1 })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to add path');

        closePathModal();
        loadPaths();
        loadStats();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deletePath(id) {
    if (!confirm('Are you sure you want to delete this local search path?')) return;
    try {
        await fetch(`/admin/api/paths/${id}`, { method: 'DELETE' });
        loadPaths();
        loadStats();
    } catch (e) {
        alert('Failed to delete path: ' + e.message);
    }
}

// ----------------------------------------------------
// DIRECTORY BROWSER
// ----------------------------------------------------

function openBrowser() {
    document.getElementById('browser-modal').style.display = 'flex';
    browseDir(window.currentBrowserPath || '/');
}

function closeBrowser() {
    document.getElementById('browser-modal').style.display = 'none';
}

async function browseDir(path) {
    try {
        const res = await fetch(`/admin/api/browse?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (!res.ok) return;

        window.currentBrowserPath = data.current_path;
        document.getElementById('current-browser-path').textContent = data.current_path;

        const list = document.getElementById('browser-list');
        list.innerHTML = '';

        if (data.parent_path) {
            const li = document.createElement('li');
            li.className = 'browser-item';
            li.innerHTML = `<i class="fa-solid fa-level-up-alt" style="color: var(--accent);"></i> <span>.. (Parent Directory)</span>`;
            li.onclick = () => browseDir(data.parent_path);
            list.appendChild(li);
        }

        data.directories.forEach(d => {
            const li = document.createElement('li');
            li.className = 'browser-item';
            li.innerHTML = `<i class="fa-solid fa-folder" style="color: #fbbf24;"></i> <span>${escapeHtml(d.name)}</span>`;
            li.onclick = () => browseDir(d.path);
            list.appendChild(li);
        });

        data.files.forEach(f => {
            const li = document.createElement('li');
            li.className = 'browser-item';
            li.innerHTML = `<i class="fa-solid fa-file-code" style="color: var(--text-muted);"></i> <span>${escapeHtml(f.name)}</span>`;
            li.onclick = () => {
                document.getElementById('selected-path').value = f.path;
                document.getElementById('path-type').value = 'file';
                closeBrowser();
            };
            list.appendChild(li);
        });
    } catch (e) {
        console.error('Browse error:', e);
    }
}

function selectBrowserPath() {
    document.getElementById('selected-path').value = window.currentBrowserPath;
    document.getElementById('path-type').value = 'directory';
    closeBrowser();
}

// ----------------------------------------------------
// SEARCH & INSPECTOR
// ----------------------------------------------------

async function runSearchTest(event) {
    event.preventDefault();
    const query = document.getElementById('test-query').value.trim();
    const type = document.getElementById('test-type').value;
    const repo = document.getElementById('test-repo').value.trim() || null;

    const area = document.getElementById('search-results-area');
    const btn = document.getElementById('btn-run-search');

    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Searching...';
    area.innerHTML = '<div class="empty-state">Running hybrid retrieval with Reciprocal Rank Fusion (RRF)...</div>';

    try {
        const res = await fetch('/admin/api/search/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, type, repo })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Search failed');

        if (!data.results || data.results.length === 0) {
            area.innerHTML = '<div class="empty-state">No matching results found in index.</div>';
            return;
        }

        area.innerHTML = data.results.map((hit, idx) => {
            const p = hit.payload;
            const link = p.github_url ? `<a href="${escapeHtml(p.github_url)}" target="_blank" style="color: var(--primary); font-size: 0.8rem; margin-left: 8px;"><i class="fa-solid fa-arrow-up-right-from-square"></i> View on GitHub</a>` : '';
            const symbolBadge = p.symbol ? `<span class="badge badge-accent" style="margin-left: 6px;">${escapeHtml(p.symbol)}</span>` : '';

            return `
                <div class="search-hit-card">
                    <div class="search-hit-header">
                        <div>
                            <span class="badge badge-primary">${escapeHtml(p.repo)}</span>
                            <strong style="margin-left: 6px;">${escapeHtml(p.rel_path)}</strong>
                            ${symbolBadge}
                            <span class="text-muted" style="font-size: 0.8rem; margin-left: 6px;">(Lines ${p.start_line}-${p.end_line})</span>
                            ${link}
                        </div>
                        <div>
                            <span class="badge badge-success">RRF Score: ${hit.score}</span>
                        </div>
                    </div>
                    <pre class="search-hit-code">${escapeHtml(p.content)}</pre>
                </div>
            `;
        }).join('');

    } catch (e) {
        area.innerHTML = `<div class="empty-state" style="color: var(--danger);">Search error: ${escapeHtml(e.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Search';
    }
}

// ----------------------------------------------------
// SETTINGS
// ----------------------------------------------------

async function loadSettings() {
    try {
        const res = await fetch('/admin/api/stats');
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('settings-token-source').textContent = data.token_source || 'None';
        document.getElementById('settings-masked-token').textContent = data.masked_token || 'None';
    } catch (e) {
        console.error('Failed loading settings:', e);
    }
}

async function saveGitHubToken(event) {
    event.preventDefault();
    const token = document.getElementById('github-token-input').value.trim();
    if (!token) return;

    try {
        const res = await fetch('/admin/api/settings/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ github_token: token })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to save token');

        alert('GitHub Token saved successfully.');
        document.getElementById('github-token-input').value = '';
        loadSettings();
        loadStats();
    } catch (e) {
        alert('Error saving token: ' + e.message);
    }
}

async function clearGitHubToken() {
    if (!confirm('Clear the stored GitHub token from database?')) return;
    try {
        await fetch('/admin/api/settings/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ github_token: '' })
        });
        loadSettings();
        loadStats();
    } catch (e) {
        alert('Failed to clear token: ' + e.message);
    }
}

function triggerReindex() {
    fetch('/admin/api/reindex', { method: 'POST' })
        .then(() => { loadStats(); loadRepos(); loadPaths(); })
        .catch(e => alert('Reindex error: ' + e.message));
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
