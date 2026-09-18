# Git Repositories Management

The **Git Repositories** view allows you to register, synchronize, monitor, and configure automated webhooks for repositories across all supported Git providers.

---

![Git Repositories](/assets/desktop_git-repos.png)

## Registering a New Repository

Follow these steps to connect a Git repository to ContextCortex:

1. In the **Git Repositories** tab, click **+ Add Repository**.
2. **Repository Name**: Enter a descriptive alias (e.g. `contextcortex` or `backend-core`).
3. **Clone URL**: Enter the Git clone URL (HTTP or HTTPS).
4. **Branch**: Specify the target branch to index (e.g. `main`, `master`, or `dev`).
5. **Git Provider**: Select your platform:
   - `GitHub`
   - `GitLab` (GitLab Cloud, Enterprise, or Self-Hosted)
   - `Gitea` or `Forgejo`
   - `Bitbucket`
   - `Generic Git` (Any standard HTTP/HTTPS Git service)
6. **Authentication**:
   - Provide an optional personal access token (PAT), or
   - Leave empty to automatically inherit saved domain credentials from the [Git Host Credential Vault](/guide/user-guide/settings).
7. Click **Save Repository**.

---

## Synchronizing Repositories

ContextCortex performs ephemeral shallow clones (`git clone --depth 1`) directly into an isolated workspace, parses AST chunks and docstrings into the vector store, updates the unified catalog, and purges the cloned files immediately from disk.

### Manual Synchronization
Click the **Sync Now** button on any repository card to trigger an immediate update. A live progress drawer displays:
- Git clone phase
- Tree-sitter AST parsing status
- Vector embedding generation progress
- Total vectors created and elapsed time

### Automated Webhooks & Polling
- **Auto-Sync Poller**: Repositories with auto-sync enabled are re-indexed periodically by the background daemon based on the configured interval (default: every 15 minutes).
- **Webhooks**: Click **Webhook** on any repository card to view the pre-configured webhook endpoint (`/api/webhooks/git`) and secret payload for GitHub, GitLab, or Gitea push events.

---

## Next Steps

- Monitor local host directories in [Local Paths and Vaults](/guide/user-guide/local-paths).
- Explore managed file uploads in [Managed Local Storage and PDF Ingestion](/guide/user-guide/local-storage).
