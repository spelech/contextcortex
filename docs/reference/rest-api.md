# Admin REST API Reference

The ContextCortex backend exposes REST API endpoints for administration, repository synchronization, settings management, and diagnostics.

All administrative routes are prefixed with `/admin/api`.

---

## Health and Metadata Endpoints

### 1. Health Status
- **Method**: `GET`
- **Path**: `/healthz`
- **Authentication**: None
- **Response**:
  ```json
  {
    "status": "ok",
    "version": "2.12.0",
    "database": "connected",
    "vector_store": "healthy"
  }
  ```

### 2. RFC 9728 OAuth 2.1 Protected Resource Metadata
- **Method**: `GET`
- **Path**: `/.well-known/oauth-protected-resource`
- **Authentication**: None
- **Response**: Returns authorization servers, supported scopes, and resource indicators.

---

## Repositories API

### 1. List Repositories
- **Method**: `GET`
- **Path**: `/admin/api/repositories`
- **Response**: Array of registered Git repositories, commit SHAs, and sync statuses.

### 2. Register Repository
- **Method**: `POST`
- **Path**: `/admin/api/repositories`
- **Request Body**:
  ```json
  {
    "name": "my-service",
    "url": "https://github.com/org/my-service.git",
    "branch": "main",
    "provider": "github",
    "auth_token": "ghp_optional_override_token"
  }
  ```

### 3. Synchronize Repository
- **Method**: `POST`
- **Path**: `/admin/api/repositories/{id}/sync`
- **Response**: Triggers an asynchronous shallow clone and returns the task ID.

### 4. Delete Repository
- **Method**: `DELETE`
- **Path**: `/admin/api/repositories/{id}`
- **Response**: Purges repository metadata and associated vector points.

---

## Local Storage and PDF API

### 1. List Storage Files
- **Method**: `GET`
- **Path**: `/admin/api/storage/files`
- **Response**: Hierarchical list of files, sizes, and indexing states.

### 2. Preview PDF Document
- **Method**: `POST`
- **Path**: `/admin/api/storage/pdf/preview`
- **Content-Type**: `multipart/form-data`
- **Response**: Extracted page text, sample semantic chunks, and OCR flags.

### 3. Upload File
- **Method**: `POST`
- **Path**: `/admin/api/storage/upload`
- **Content-Type**: `multipart/form-data`
- **Response**: Uploads file to `/app/data/storage` and triggers immediate indexing.

---

## Settings API

### 1. Get Settings
- **Method**: `GET`
- **Path**: `/admin/api/settings`
- **Response**: Returns vector database configuration, embedding model parameters, and token statuses.

### 2. Discover LiteLLM Models
- **Method**: `GET`
- **Path**: `/admin/api/settings/models/discover`
- **Response**:
  ```json
  {
    "status": "success",
    "total_models": 12,
    "embedding_models": ["gemini-embedding-2", "text-embedding-3-small"],
    "vision_models": ["gemini-2.5-flash", "qwen3-vl-32b-instruct"],
    "chat_models": ["gemini-2.5-pro", "deepseek-v3.2"]
  }
  ```

### 3. Test Vector Store Connection
- **Method**: `POST`
- **Path**: `/admin/api/settings/vector-store/test`
- **Request Body**:
  ```json
  {
    "provider": "qdrant",
    "host": "qdrant",
    "port": 6333
  }
  ```

---

## Diagnostics API

### 1. Retrieve Recent Logs
- **Method**: `GET`
- **Path**: `/admin/api/logs?level=ERROR&limit=50`
- **Response**: Array of log events with timestamps, log levels, messages, and stack traces.

### 2. Clear Log Buffer
- **Method**: `DELETE`
- **Path**: `/admin/api/logs`
- **Response**: Resets the in-memory ring buffer.
