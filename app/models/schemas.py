from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple

# Database & Sync Models
class RepoConfig(BaseModel):
    id: Optional[int] = None
    name: str
    url: str
    branch: Optional[str] = "main"
    commit_sha: Optional[str] = None
    status: Optional[str] = "pending"
    last_error: Optional[str] = None
    last_synced: Optional[str] = None
    auth_token: Optional[str] = None
    provider: Optional[str] = "github"
    auth_user: Optional[str] = None
    enabled: bool = True
    auto_sync: bool = True
    webhook_secret: Optional[str] = None

class LocalPathConfig(BaseModel):
    id: Optional[int] = None
    path: str
    type: Optional[str] = "directory"
    recursive: bool = True
    category: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True

# Code Analysis Models
# API Route Discovery & Linking Models
class ApiRouteRecord(BaseModel):
    id: Optional[int] = None
    repo: str
    filepath: str
    framework: str
    http_method: str
    path_pattern: str
    handler_symbol: Optional[str] = None
    start_line: int
    end_line: int
    created_at: Optional[str] = None

class ApiClientCallRecord(BaseModel):
    id: Optional[int] = None
    repo: str
    filepath: str
    http_method: Optional[str] = None
    url_pattern: str
    caller_symbol: Optional[str] = None
    line_number: int
    created_at: Optional[str] = None

class CodeSymbol(BaseModel):
    name: str
    full_symbol: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    language: str
    repo: Optional[str] = None
    filepath: Optional[str] = None

class CodeRelationship(BaseModel):
    id: Optional[int] = None
    repo: str
    source_symbol_id: Optional[int] = None
    source_filepath: str
    source_symbol: str
    target_symbol: str
    relationship_type: str # 'CALLS', 'IMPORTS', 'INHERITS', 'IMPLEMENTS'
    line_number: int

class CodeChunk(BaseModel):
    content: str
    start_line: int
    end_line: int
    symbol: Optional[str] = None
    kind: Optional[str] = "code"

class MarkdownChunk(BaseModel):
    content: str
    heading: str
    start_line: int
    end_line: int

class ExtractionResult(BaseModel):
    chunks: List[CodeChunk]
    symbols: List[CodeSymbol]
    outline: List[str] = Field(default_factory=list)
    relationships: List[CodeRelationship] = Field(default_factory=list)
    api_routes: List[ApiRouteRecord] = Field(default_factory=list)
    api_client_calls: List[ApiClientCallRecord] = Field(default_factory=list)

class CloneResult(BaseModel):
    temp_dir: Optional[str]
    commit_sha: Optional[str]
    error: Optional[str]

# API Request/Response Models
class SearchRequest(BaseModel):
    query: str
    type: str = "code"
    repo: Optional[str] = None
    language: Optional[str] = None
    category: Optional[str] = None
    tag: Optional[str] = None
    limit: int = 5
    exact: bool = True

class SyncRequest(BaseModel):
    repo: Optional[str] = None

class TokenRequest(BaseModel):
    github_token: Optional[str] = None
    gitlab_token: Optional[str] = None
    gitea_token: Optional[str] = None

class HostCredentialRequest(BaseModel):
    id: Optional[int] = None
    host: str
    provider: str = "generic"
    auth_user: Optional[str] = None
    auth_token: str

class FindSymbolRequest(BaseModel):
    name: str
    repo: Optional[str] = None
    exact: bool = True
    limit: int = 10

class GetFileOutlineRequest(BaseModel):
    filepath: str
    repo: Optional[str] = None

class VectorStoreTestRequest(BaseModel):
    provider: str
    mode: Optional[str] = "embedded"
    storage_path: Optional[str] = None
    url: Optional[str] = None
    collection: Optional[str] = None

class VectorStoreSwitchRequest(BaseModel):
    provider: str
    mode: Optional[str] = "embedded"
    storage_path: Optional[str] = None
    url: Optional[str] = None
    collection: Optional[str] = None

class VectorStoreConfigRequest(BaseModel):
    provider: str
    mode: Optional[str] = "embedded"
    storage_path: Optional[str] = None
    url: Optional[str] = None
    collection: Optional[str] = None

class AutoSyncToggleRequest(BaseModel):
    auto_sync: bool

class AutoSyncSettingsRequest(BaseModel):
    interval_mins: int
    global_webhook_secret: Optional[str] = None

# Topology Graph Models
class TopologyNode(BaseModel):
    id: str
    name: str
    type: str  # 'file', 'module', 'class', 'function', 'route'
    repo: str
    filepath: Optional[str] = None
    language: Optional[str] = None
    kind: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    signature: Optional[str] = None
    method: Optional[str] = None
    path_pattern: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class TopologyEdge(BaseModel):
    source: str
    target: str
    type: str  # 'IMPORTS', 'CALLS', 'DEFINES', 'HANDLES', 'ROUTES_TO'
    label: Optional[str] = None
    line_number: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class TopologyStats(BaseModel):
    node_count: int
    edge_count: int

class TopologyResponse(BaseModel):
    nodes: List[TopologyNode]
    edges: List[TopologyEdge]
    stats: TopologyStats

class NeighborDetail(BaseModel):
    id: str
    name: str
    type: str
    edge_type: str
    filepath: Optional[str] = None
    line_number: Optional[int] = None
    permalink: Optional[str] = None

class NodeDetailsResponse(BaseModel):
    id: str
    name: str
    type: str
    repo: str
    filepath: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    signature: Optional[str] = None
    code_preview: Optional[str] = None
    permalink: Optional[str] = None
    incoming: List[NeighborDetail] = Field(default_factory=list)
    outgoing: List[NeighborDetail] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None



