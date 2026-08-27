"""
Master AuthService for MCP 2026-07-28 Auth & RBAC Security Engine.
Coordinates token routing (API Key vs JWT vs local dev bypass), role enforcement,
and key management delegations.
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Union

from app.services.auth.models import (
    Role,
    AuthContext,
    AuthUser,
    ApiKeyOut,
    AuthException,
    AuthenticationError,
    InvalidTokenError,
    ExpiredTokenError,
    ForbiddenError,
)
from app.services.auth.key_service import ApiKeyService
from app.services.auth.jwt_validator import JwtValidator

logger = logging.getLogger("contextcortex.auth.service")

_GLOBAL_AUTH_SERVICE: Optional["AuthService"] = None


class AuthService:
    """
    Master authentication and RBAC service.
    Handles token authentication, role validation, and key lifecycle.
    """

    def __init__(
        self,
        auth_enabled: Optional[bool] = None,
        oidc_issuer: Optional[str] = None,
        jwks_uri: Optional[str] = None,
        resource_indicator: Optional[str] = None,
        key_service: Optional[ApiKeyService] = None,
        jwt_validator: Optional[JwtValidator] = None,
    ):
        if auth_enabled is None:
            raw_enabled = os.getenv("AUTH_ENABLED", "false").strip().lower()
            self._auth_enabled = raw_enabled in ("true", "1", "yes", "on")
        else:
            self._auth_enabled = bool(auth_enabled)

        self.oidc_issuer = oidc_issuer or os.getenv("AUTH_OIDC_ISSUER")
        self.jwks_uri = jwks_uri or os.getenv("AUTH_JWKS_URI")
        self.resource_indicator = resource_indicator or os.getenv(
            "AUTH_RESOURCE_INDICATOR", "https://contextcortex.local"
        )

        self.key_service = key_service or ApiKeyService()
        self._jwt_validator = jwt_validator

    @property
    def jwt_validator(self) -> JwtValidator:
        """Lazily creates or returns the JwtValidator instance."""
        if self._jwt_validator is None:
            self._jwt_validator = JwtValidator(
                oidc_issuer=self.oidc_issuer,
                jwks_uri=self.jwks_uri,
                resource_indicator=self.resource_indicator,
            )
        return self._jwt_validator

    def is_auth_enabled(self) -> bool:
        """Returns True if authentication is actively enforced."""
        return self._auth_enabled

    def authenticate_token(self, token_or_header: Optional[str]) -> AuthContext:
        """
        Authenticates an incoming bearer token or API key.
        If authentication is disabled (local dev default), implicitly returns an admin AuthContext.
        """
        if not self._auth_enabled:
            return AuthContext(
                user_id="anonymous",
                name="Anonymous Local Dev",
                role=Role.ADMIN,
                scopes=["mcp:admin", "mcp:editor", "mcp:viewer"],
                auth_type="bypass",
                is_authenticated=True,
            )

        if not token_or_header or not isinstance(token_or_header, str):
            raise AuthenticationError("Missing authentication credentials.")

        raw_token = token_or_header.strip()
        if raw_token.lower().startswith("bearer "):
            raw_token = raw_token[7:].strip()

        if not raw_token:
            raise AuthenticationError("Missing bearer token in authorization header.")

        # Route based on token format
        if raw_token.startswith("cc_"):
            return self.key_service.validate_api_key(raw_token)
        else:
            return self.jwt_validator.validate_jwt(raw_token)

    def check_role_permission(
        self,
        context: AuthContext,
        required_role: Union[Role, str],
    ) -> bool:
        """
        Returns True if the authenticated principal has a role equal to or higher than required.
        Admin (30) >= Editor (20) >= Viewer (10).
        """
        return context.has_role(required_role)

    def require_role(
        self,
        context: AuthContext,
        required_role: Union[Role, str],
    ) -> AuthContext:
        """
        Ensures the authenticated context possesses the required role level,
        raising ForbiddenError if permission is insufficient.
        """
        req = Role.from_str(required_role)
        if not context.has_role(req):
            raise ForbiddenError(
                f"Insufficient permissions: required role '{req.value}', current role '{context.role.value}'."
            )
        return context

    # -------------------------------------------------------------------------
    # Delegated API Key Management Methods
    # -------------------------------------------------------------------------

    def issue_api_key(
        self,
        name: str,
        role: Union[Role, str] = Role.VIEWER,
        group_name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> ApiKeyOut:
        return self.key_service.issue_api_key(
            name=name,
            role=role,
            group_name=group_name,
            expires_at=expires_at,
        )

    def revoke_api_key(self, key_id: int) -> bool:
        return self.key_service.revoke_api_key(key_id)

    def delete_api_key(self, key_id: int) -> bool:
        return self.key_service.delete_api_key(key_id)

    def get_api_key(self, key_id: int) -> Optional[ApiKeyOut]:
        return self.key_service.get_api_key(key_id)

    def list_api_keys(self) -> List[ApiKeyOut]:
        return self.key_service.list_api_keys()


def get_auth_service(reset: bool = False, **kwargs) -> AuthService:
    """
    Returns the singleton AuthService instance or initializes a new one.
    """
    global _GLOBAL_AUTH_SERVICE
    if reset or _GLOBAL_AUTH_SERVICE is None or kwargs:
        _GLOBAL_AUTH_SERVICE = AuthService(**kwargs)
    return _GLOBAL_AUTH_SERVICE
