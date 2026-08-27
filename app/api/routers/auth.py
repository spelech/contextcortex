"""
Auth Router for ContextCortex.
Provides RFC 9728 Protected Resource Metadata (/.well-known/oauth-protected-resource)
and API Key Lifecycle Management REST Endpoints (/admin/api/auth/keys).
"""

import logging
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.services.auth.models import (
    Role,
    AuthContext,
    ApiKeyCreate,
    ApiKeyOut,
    AuthenticationError,
    ForbiddenError,
)
from app.services.auth.service import (
    AuthService,
    get_auth_service,
    get_current_auth_context,
)

logger = logging.getLogger("contextcortex.api.auth")

router = APIRouter()


def get_current_auth(request: Request) -> AuthContext:
    """
    FastAPI dependency for authenticating incoming requests.
    Inspects ContextVar first, then request Authorization header, falling back to dev bypass.
    Raises 401 with WWW-Authenticate header on authentication failure.
    """
    ctx = get_current_auth_context()
    if ctx is not None:
        return ctx

    auth_service = get_auth_service()
    if not auth_service.is_auth_enabled():
        return auth_service.authenticate_token(None)

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    try:
        return auth_service.authenticate_token(auth_header)
    except AuthenticationError as e:
        resource_indicator = auth_service.resource_indicator
        res_meta = f"{resource_indicator}/.well-known/oauth-protected-resource"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={
                "WWW-Authenticate": f'Bearer error="invalid_token", error_description="{str(e)}", resource_metadata="{res_meta}"'
            },
        )
    except ForbiddenError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


def require_role(required_role: Union[Role, str]):
    """
    FastAPI dependency factory enforcing a minimum Role level.
    Admin (30) >= Editor (20) >= Viewer (10).
    """
    def _role_checker(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        req = Role.from_str(required_role)
        if not auth.has_role(req):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: required role '{req.value}', current role '{auth.role.value}'.",
            )
        return auth
    return _role_checker


# =============================================================================
# 1. RFC 9728 Protected Resource Metadata (Public Endpoint)
# =============================================================================

@router.get("/.well-known/oauth-protected-resource")
async def get_oauth_protected_resource():
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata.
    Exposes resource URI, supported authorization servers, and MCP scopes.
    """
    auth_service = get_auth_service()
    return auth_service.get_protected_resource_metadata()


# =============================================================================
# 2. Admin API Key Management Endpoints
# =============================================================================

@router.get(
    "/admin/api/auth/keys",
    response_model=List[ApiKeyOut],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_api_keys():
    """
    Lists all registered API keys with masked secret hashes.
    Requires Role.ADMIN.
    """
    auth_service = get_auth_service()
    return auth_service.list_api_keys()


@router.post(
    "/admin/api/auth/keys",
    response_model=ApiKeyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_api_key(payload: ApiKeyCreate):
    """
    Issues a new API key with the requested role and optional expiration.
    Returns the key metadata and the plaintext secret_key (one-time presentation).
    Requires Role.ADMIN.
    """
    auth_service = get_auth_service()
    try:
        new_key = auth_service.issue_api_key(
            name=payload.name,
            role=payload.role,
            group_name=payload.group_name,
            expires_at=payload.expires_at,
        )
        return new_key
    except Exception as e:
        logger.error(f"Error issuing API key: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to issue API key: {str(e)}")


@router.delete(
    "/admin/api/auth/keys/{key_id}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def revoke_api_key(key_id: int):
    """
    Revokes an existing API key by ID, preventing further authentication.
    Requires Role.ADMIN.
    """
    auth_service = get_auth_service()
    existing = auth_service.get_api_key(key_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key with ID {key_id} not found.",
        )
    success = auth_service.revoke_api_key(key_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke API key {key_id}.",
        )
    return {"success": True, "status": "revoked", "id": key_id}
