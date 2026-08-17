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
    enabled: bool = True

class LocalPathConfig(BaseModel):
    id: Optional[int] = None
    path: str
    type: Optional[str] = "directory"
    recursive: bool = True
    category: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True

# Code Analysis Models
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
    outline: List[str]

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
    github_token: str

class FindSymbolRequest(BaseModel):
    name: str
    repo: Optional[str] = None
    exact: bool = True
    limit: int = 10

class GetFileOutlineRequest(BaseModel):
    filepath: str
    repo: Optional[str] = None
