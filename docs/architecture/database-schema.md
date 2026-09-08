# Database and Storage Schema

This document details the relational data model, entity relationships, and vector storage structures.

## Entity Relationship Diagram (ERD)

ContextCortex uses a unified SQLAlchemy 2.0 relational schema shared between PostgreSQL 16 and SQLite.

```mermaid
erDiagram
    GIT_REPOSITORIES ||--o{ AST_SYMBOLS : contains
    GIT_REPOSITORIES ||--o{ CODE_ROUTES : declares
    GIT_REPOSITORIES {
        int id PK "Primary Key"
        string name UK "Unique Alias"
        string url "Clone URL"
        string branch "Target Branch"
        string provider "GitHub | GitLab | Gitea | Bitbucket"
        string commit_sha "Latest Indexed Commit"
        string status "pending | syncing | synced | error"
        datetime last_synced "Timestamp"
        int enabled "1=Active, 0=Disabled"
    }

    GIT_HOST_CREDENTIALS {
        int id PK "Primary Key"
        string host UK "Host Domain or IP"
        string provider "GitLab | Gitea | Bitbucket"
        string auth_user "Optional Default User"
        string auth_token "Access Token"
        datetime added_at "Creation Date"
    }

    LOCAL_STORAGE_FILES {
        int id PK "Primary Key"
        string file_path UK "Relative Storage Path"
        int file_size "Size in Bytes"
        string sha256_hash "Content Hash"
        string mime_type "Detected MIME Type"
        string status "pending | indexed | error"
        datetime updated_at "Modification Date"
    }

    AST_SYMBOLS {
        int id PK "Primary Key"
        int repo_id FK "Foreign Key to GIT_REPOSITORIES"
        string file_path "Relative Source File Path"
        string symbol_name "Declared Symbol Name"
        string symbol_type "function | class | method | route"
        string signature "Parameter and Type Signature"
        int start_line "1-Indexed Starting Line"
        int end_line "1-Indexed Ending Line"
        string docstring "Extracted Documentation"
    }

    CODE_ROUTES {
        int id PK "Primary Key"
        int repo_id FK "Foreign Key to GIT_REPOSITORIES"
        string file_path "Source File Path"
        string route_path "HTTP Endpoint Path (e.g. /api/v1/search)"
        string http_method "GET | POST | PUT | DELETE"
        string framework "fastapi | express | aspnet | flask"
        string handler_symbol "Function or Controller Symbol"
    }

    API_KEYS {
        int id PK "Primary Key"
        string key_hash UK "SHA-256 Hash of Key"
        string prefix "Visible Prefix (cc_xxxx)"
        string role "viewer | editor | admin"
        datetime expires_at "Expiration Date"
        int is_active "1=Active, 0=Revoked"
    }

    ARCHITECTURE_ADRS {
        int id PK "Primary Key"
        int adr_number "Sequential Number (e.g. 0001)"
        string title "Decision Record Title"
        string status "proposed | accepted | deprecated"
        string context "Context Description"
        string decision "Architecture Decision"
        string consequences "Expected Consequences"
        datetime record_date "Record Date"
    }
```

---

## Relational Tables Specification

### 1. `git_repositories`
Stores remote repository tracking configurations, clone URLs, authentication overrides, and synchronization states.

### 2. `git_host_credentials`
Stores domain-wide access tokens for internal Git servers. All repositories on a matching host inherit these credentials unless an explicit token override exists.

### 3. `local_storage_files`
Manages files uploaded directly to local storage (`/app/data/storage`). Prevents directory traversal attacks and tracks incremental indexing status.

### 4. `ast_symbols`
Maintains the index of source code symbols extracted by Tree-sitter. Powers instant symbol search (`find_symbol`) and file outlines (`get_file_outline`) without querying vector databases.

### 5. `code_routes`
Indexes REST API endpoint declarations and handler functions across multiple backend frameworks (FastAPI, ASP.NET Core, Express, Flask).

### 6. `api_keys`
Stores cryptographically hashed API keys for client authentication and role-based access control.

---

## Vector Store Payload Schema

Each point in the vector database contains a dense vector embedding, optional sparse lexical tokens, and this metadata payload:

```json
{
  "id": "uuid4-identifier",
  "text": "Extracted source code block or markdown text",
  "metadata": {
    "source_type": "git | local_path | local_storage",
    "repo_name": "contextcortex",
    "filepath": "app/services/embeddings.py",
    "start_line": 45,
    "end_line": 85,
    "symbol_name": "FastEmbedEngine",
    "symbol_type": "class",
    "language": "python",
    "commit_sha": "4bcf9e8"
  }
}
```
