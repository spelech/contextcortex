"""
MCP 2026-07-28 Auth & RBAC Security Models.
Defines role hierarchies, authentication context, and API key exchange models.
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


# ==========================================
# Auth Exceptions
# ==========================================

class AuthException(Exception):
    """Base exception for authentication and authorization errors."""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)
        self.message = message


class AuthenticationError(AuthException):
    """Raised when authentication fails (missing or invalid credentials -> 401)."""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a token or API key is malformed, unrecognized, or revoked."""
    pass


class ExpiredTokenError(AuthenticationError):
    """Raised when a token or API key has expired."""
    pass


class ForbiddenError(AuthException):
    """Raised when an authenticated principal lacks required role/scopes -> 403."""
    pass


# ==========================================
# Role Hierarchy & RBAC Models
# ==========================================

class Role(str, Enum):
    """
    3-Tier Role-Based Access Control hierarchy for ContextCortex MCP & REST APIs:
    - admin (mcp:admin): Full control over settings, credentials, keys, syncs, & tools.
    - editor (mcp:editor): Mutation & sync operations, ADR management, plus search tools.
    - viewer (mcp:viewer): Read-only knowledge retrieval, catalog queries, & code search.
    """
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def level(self) -> int:
        levels = {
            Role.ADMIN: 30,
            Role.EDITOR: 20,
            Role.VIEWER: 10,
        }
        return levels.get(self, 0)

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, (Role, str)):
            return self.level >= Role.from_str(other).level
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, (Role, str)):
            return self.level > Role.from_str(other).level
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, (Role, str)):
            return self.level <= Role.from_str(other).level
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, (Role, str)):
            return self.level < Role.from_str(other).level
        return NotImplemented

    @classmethod
    def from_str(cls, val: Any) -> "Role":
        """Converts strings or existing Role instances to a Role safely, defaulting to VIEWER."""
        if isinstance(val, cls):
            return val
        if not val or not isinstance(val, str):
            return cls.VIEWER
        norm = val.strip().lower()
        for role in cls:
            if role.value == norm:
                return role
        return cls.VIEWER


class AuthContext(BaseModel):
    """
    Principal and authorization context for the current authenticated request.
    """
    user_id: Optional[str] = None
    name: Optional[str] = None
    role: Role = Role.VIEWER
    scopes: List[str] = Field(default_factory=list)
    auth_type: str = "api_key"  # 'api_key', 'jwt', 'bypass'
    key_id: Optional[int] = None
    group_name: Optional[str] = None
    is_authenticated: bool = True
    raw_claims: Dict[str, Any] = Field(default_factory=dict)

    def has_role(self, required_role: Union[Role, str]) -> bool:
        """Returns True if the authenticated role satisfies the required role level."""
        return self.role >= Role.from_str(required_role)

    def has_scope(self, scope: str) -> bool:
        """Returns True if scope is held or user is admin."""
        if self.role == Role.ADMIN:
            return True
        return scope in self.scopes


# Alias for backward compatibility / caller convenience
AuthUser = AuthContext


class ApiKeyCreate(BaseModel):
    """Payload for generating a new database-backed API key."""
    name: str = Field(..., min_length=1, max_length=100, description="Descriptive label for the key")
    role: Role = Field(default=Role.VIEWER, description="Role level assigned to this key")
    group_name: Optional[str] = Field(default=None, max_length=100, description="Optional team or group")
    expires_at: Optional[datetime] = Field(default=None, description="Optional UTC expiration timestamp")


class ApiKeyOut(BaseModel):
    """Public representation of an API key."""
    id: int
    name: str
    key_prefix: str
    role: str
    group_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool = True
    secret_key: Optional[str] = None  # Only populated when key is initially generated
