# User Guide

This user guide describes how to operate the ContextCortex Web Admin Dashboard. Follow these instructions to manage repositories, inspect codebases, execute searches, and configure models.

---

## 1. Overview Dashboard

The **Overview** view provides a high-level summary of system health, indexed vector counts, model configurations, and repository statuses.

![Overview Dashboard](/assets/desktop_overview.png)

### Dashboard Metrics

The Overview dashboard displays these primary metrics:
- **Total Vectors**: The number of dense and sparse vector embeddings stored across active collections.
- **AST Symbols**: The count of indexed functions, classes, methods, and interfaces.
- **Tracked Repositories**: The number of active Git repositories and monitored local directories.
- **Embedding Model**: The active embedding model name, dimension size, and execution device.

### Actions on the Overview Page

1. To trigger a full re-synchronization of all repositories, click **Reindex All Sources**.
2. To refresh system health metrics, click the **Refresh** button in the header.
3. Review the **Topic Tag Cloud** to observe primary concepts extracted from code docstrings.

---

## 2. 3-Pane Codebase Navigator

The **Codebase Navigator** provides high-performance exploration of project structures, AST declarations, and code relationships.

![Codebase Navigator](/assets/desktop_codebase-navigator.png)

The Navigator interface contains three synchronized panes:

### Pane 1: Files and Modules Tree
- Browse directory hierarchies and file paths.
- View symbol counts and REST route badges on each file item.
- Use the quick filter bar to locate specific filenames instantly.

### Pane 2: Symbols and Routes Outline
- View all declared functions, classes, interfaces, and API endpoints.
- Filter by category chips: **All**, **Functions**, **Classes**, or **Routes**.
- Inspect parameter signatures, return types, and source line numbers.

### Pane 3: Code Intelligence and Impact Analysis
- Inspect incoming callers and outgoing callees identified by AST static analysis.
- View HTTP route mappings (such as `GET /api/v1/search` or `POST /upload`).
- Examine full function docstrings and implementation code blocks.
- Click any caller symbol to navigate directly to its definition.

### Layout Density Settings
You can select three display densities in the upper right control:
- **Compact**: Maximizes screen space for dense code inspection.
- **Balanced**: Provides standard spacing for general development.
- **Spacious**: Formats records as readable cards.

---

## 3. Search and Inspector

The **Search and Inspector** view allows administrators to test hybrid semantic and keyword retrieval queries interactively.

![Search and Inspector](/assets/desktop_search-inspector.png)

### Executing a Search Query

Follow these steps to test search retrieval:

1. Click the **Search & Inspector** tab in the main navigation.
2. Enter your query in the search input box (for example, `vector database connection pool`).
3. Select the target search category:
   - **Code**: Searches source code chunks with syntax formatting.
   - **Docs**: Searches markdown documents, architecture notes, and specifications.
4. Set the optional **Repository** filter to restrict results to a specific codebase.
5. Click **Run Search**.

### Interpreting Search Results

Each result card displays:
- **RRF Score**: Combined score calculated from Dense Cosine similarity and BM25 rank.
- **Source Link**: Clickable permalink directly to the file and line range in the upstream Git provider.
- **Syntax Preview**: Code block with syntax highlighting and line numbers.

---

## 4. Git Repositories Management

The **Git Repositories** view allows you to register, synchronize, and monitor remote repositories across all supported Git providers.

![Git Repositories](/assets/desktop_git-repos.png)

### Registering a New Git Repository

Follow these steps to add a repository:

1. Click **Add Repository**.
2. Enter a unique repository alias in the **Name** field.
3. Enter the Git clone URL in the **URL** field.
4. Specify the branch name to track (for example, `main` or `master`).
5. Select the Git provider:
   - `GitHub`
   - `GitLab` (Cloud, Enterprise, or Self-Hosted)
   - `Gitea` or `Forgejo`
   - `Bitbucket`
   - `Generic Git` (Any standard HTTP or HTTPS Git endpoint)
6. If authentication is required, provide an override token or select a saved credential from the vault.
7. Click **Save Repository**.

### Synchronizing a Repository

1. Locate the repository card in the list.
2. Click the **Sync Now** button.
3. ContextCortex executes an authenticated shallow clone (`git clone --depth 1`).
4. The system parses AST symbols, generates vector embeddings, and removes cloned files from disk.

---

## 5. Local Paths and Vaults

The **Local Paths** view enables direct monitoring of local directories on the host server, such as Obsidian vaults, architectural records, and monorepos.

![Local Paths](/assets/desktop_local-paths.png)

### Adding a Monitored Local Path

1. Click the **Local Paths** tab in the dashboard.
2. Click **Add Local Path**.
3. Use the filesystem browser modal to navigate to the target directory, or enter the absolute path manually.
4. Set the **Recursive** toggle:
   - Enable to scan all nested subdirectories.
   - Disable to scan only top-level files.
5. Click **Register Path**.
6. The background file watcher indexes all markdown documents and source code files.

---

## 6. Managed Local Storage and PDF Ingestion

ContextCortex provides a managed storage service (`/app/data/storage`) for direct document uploads.

### Supported File Formats
- Markdown and text files (`.md`, `.txt`, `.json`, `.yaml`)
- Source code files (`.py`, `.ts`, `.tsx`, `.js`, `.cs`, `.go`, `.rs`)
- PDF documents (`.pdf`) up to 50 megabytes in size

### Uploading and Processing a PDF Document

1. Navigate to the **Local Storage** view.
2. Click **Upload File**.
3. Select your `.pdf` document.
4. The system opens the **PDF Preview Modal**.
5. Inspect the extracted page text, sample semantic chunks, and OCR flags.
6. When the preview is accurate, click **Confirm & Ingest to Vector DB**.
7. ContextCortex splits the document into semantic chunks and updates vector storage.

---

## 7. System Settings and Model Discovery

The **Settings** view manages vector database engines, embedding providers, dynamic LiteLLM models, and Git credentials.

![Settings](/assets/desktop_settings.png)

### Vector Database Management
- **Switch Engine**: Select `Qdrant`, `pgvector`, or `ChromaDB` dynamically.
- **Test Connection**: Click **Test Connection** to verify database health before switching.
- **Vector Dimension**: Verify that the dimension matches your active embedding model (for example, `384` for BAAI/bge-small-en-v1.5).

### LiteLLM Dynamic Model Discovery
When using a LiteLLM proxy, ContextCortex discovers and classifies available models automatically:
- **Embedding Models**: Filtered by embedding capabilities (such as `gemini-embedding-2` or `text-embedding-3-small`).
- **Vision OCR Models**: Models with vision capabilities used to extract text from images in PDF files (such as `gemini-2.5-flash` or `qwen3-vl`).
- **Chat Models**: General reasoning models for guided agent prompts.

### Custom Git Host Credential Vault
Store domain-level credentials for internal and self-hosted Git instances:
1. Scroll to the **Git Host Credentials** table.
2. Click **Add Host Credential**.
3. Enter the hostname (for example, `gitlab.internal.company.com`).
4. Enter the default username and access token.
5. Save the record. All repositories under that domain inherit these credentials automatically.

---

## 8. Diagnostics and System Logs

The **Diagnostics** view provides real-time observability into indexing lifecycle events, warning conditions, and errors.

![Diagnostics and Logs](/assets/desktop_diagnostics.png)

### Inspecting Log Events
- The system stores up to 500 recent events in an in-memory ring buffer.
- Filter events by log level: **ALL**, **INFO**, **WARNING**, **ERROR**, or **DEBUG**.
- Use the search bar to filter log messages by keyword.
- Click any error event to open the detailed traceback drawer.
- Click **Clear Logs** to reset the active memory buffer.

---

## 9. Appearance and Theme Customization

ContextCortex includes four polished visual themes designed for dark and light environments.

| Deep Ocean *(Dark Default)* | Midnight Blue *(Dark Space)* |
|:---:|:---:|
| ![Deep Ocean](/assets/theme_deep_ocean.png) | ![Midnight Blue](/assets/theme_midnight_blue.png) |
| *Petrol spruce `#07181b` with vibrant cyan & mint accents* | *Obsidian navy `#0a0f1d` with royal blue & teal accents* |

| Lavender Haze *(Light Purple)* | Amber Warmth *(Light Sandstone)* |
|:---:|:---:|
| ![Lavender Haze](/assets/theme_lavender_haze.png) | ![Amber Warmth](/assets/theme_amber_warmth.png) |
| *Lilac canvas `#f5f3ff` with purple & fuchsia accents* | *Sandstone `#fdf8f4` with terracotta & amber accents* |

### Changing the Active Theme
1. Click the theme palette selector in the upper right header of the dashboard.
2. Select your preferred color palette.
3. The interface updates instantly without a page reload.
4. Your preference is saved to your browser local storage.
