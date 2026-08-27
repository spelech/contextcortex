"""
MCP 2026-07-28 Auth & RBAC Security Engine for ContextCortex.
Provides Role hierarchies, AuthContext / AuthUser principals, API key lifecycle management,
OIDC/JWKS JWT validation, and the master AuthService.
"""

from app.services.auth.models import (
    Role,
    AuthContext,
    AuthUser,
    ApiKeyCreate,
    ApiKeyOut,
    AuthException,
    AuthenticationError,
    InvalidTokenError,
    ExpiredTokenError,
    ForbiddenError,
)
from app.services.auth.key_service import ApiKeyService, API_KEY_PREFIX
from app.services.auth.jwt_validator import JwtValidator
from app.services.auth.service import (
    AuthService,
    get_auth_service,
    get_current_auth_context,
    set_current_auth_context,
    enforce_tool_permission,
)

__all__ = [
    # Models & Principals
    "Role",
    "AuthContext",
    "AuthUser",
    "ApiKeyCreate",
    "ApiKeyOut",
    # Services
    "ApiKeyService",
    "JwtValidator",
    "AuthService",
    "get_auth_service",
    "get_current_auth_context",
    "set_current_auth_context",
    "enforce_tool_permission",
    # Constants
    "API_KEY_PREFIX",
    # Exceptions
    "AuthException",
    "AuthenticationError",
    "InvalidTokenError",
    "ExpiredTokenError",
    "ForbiddenError",
]
