"""
OIDC and JWKS JWT Validator for MCP 2026-07-28 Auth.
Handles JWKS key discovery & caching, signature verification, RFC 8707 resource matching,
and 3-tier role extraction from OIDC/OAuth claims.
"""

import time
import logging
from typing import Optional, List, Dict, Any, Union

import httpx
import jwt
from jwt import PyJWKSet

from app.services.auth.models import (
    Role,
    AuthContext,
    InvalidTokenError,
    ExpiredTokenError,
)

logger = logging.getLogger("contextcortex.auth.jwt")


class JwtValidator:
    """
    Validates incoming OIDC OAuth 2.1 JWT tokens using JWKS and extracts RBAC roles.
    """

    def __init__(
        self,
        oidc_issuer: Optional[str] = None,
        jwks_uri: Optional[str] = None,
        resource_indicator: Optional[str] = None,
        algorithms: Optional[List[str]] = None,
        jwks_cache_ttl: int = 3600,
    ):
        self.oidc_issuer = oidc_issuer.rstrip("/") if oidc_issuer else None
        self.jwks_uri = jwks_uri
        self.resource_indicator = resource_indicator
        self.algorithms = algorithms or ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"]
        self.jwks_cache_ttl = jwks_cache_ttl

        self._cached_jwks: Optional[Dict[str, Any]] = None
        self._jwks_fetched_at: float = 0.0

    def _resolve_jwks_uri(self) -> str:
        """Discovers JWKS URI via OIDC discovery endpoint if not explicitly provided."""
        if self.jwks_uri:
            return self.jwks_uri

        if not self.oidc_issuer:
            raise InvalidTokenError("Neither AUTH_JWKS_URI nor AUTH_OIDC_ISSUER is configured.")

        discovery_url = f"{self.oidc_issuer}/.well-known/openid-configuration"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(discovery_url)
                resp.raise_for_status()
                data = resp.json()
                discovered_uri = data.get("jwks_uri")
                if not discovered_uri:
                    raise InvalidTokenError("OIDC discovery response missing 'jwks_uri'.")
                self.jwks_uri = discovered_uri
                return self.jwks_uri
        except Exception as exc:
            logger.error(f"Failed to discover JWKS URI from {discovery_url}: {exc}")
            raise InvalidTokenError(f"OIDC discovery failed: {exc}") from exc

    def _get_jwks(self) -> Dict[str, Any]:
        """Fetches and caches JWKS document from the authorization server."""
        now = time.time()
        if self._cached_jwks and (now - self._jwks_fetched_at) < self.jwks_cache_ttl:
            return self._cached_jwks

        uri = self._resolve_jwks_uri()
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(uri)
                resp.raise_for_status()
                jwks_data = resp.json()
                self._cached_jwks = jwks_data
                self._jwks_fetched_at = now
                return jwks_data
        except Exception as exc:
            logger.error(f"Failed to fetch JWKS from {uri}: {exc}")
            raise InvalidTokenError(f"Failed to fetch JWKS: {exc}") from exc

    def _find_signing_key(self, token: str) -> Any:
        """Extracts token header kid and finds matching public key in JWKS."""
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise InvalidTokenError(f"Malformed JWT header: {exc}") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg")

        if alg and alg not in self.algorithms:
            raise InvalidTokenError(f"Unsupported JWT algorithm: {alg}")

        jwks_data = self._get_jwks()
        jwk_set = None
        try:
            jwk_set = PyJWKSet.from_dict(jwks_data)
        except Exception:
            pass

        if jwk_set and jwk_set.keys:
            if kid:
                for jwk in jwk_set.keys:
                    if jwk.key_id == kid:
                        return jwk.key
            else:
                return jwk_set.keys[0].key

        # Key not found or JWKS empty; if cached, clear cache and retry once
        if self._cached_jwks is not None:
            self._cached_jwks = None
            fresh_jwks = self._get_jwks()
            try:
                fresh_set = PyJWKSet.from_dict(fresh_jwks)
                if fresh_set.keys:
                    if kid:
                        for jwk in fresh_set.keys:
                            if jwk.key_id == kid:
                                return jwk.key
                    else:
                        return fresh_set.keys[0].key
            except Exception as exc:
                raise InvalidTokenError(f"Invalid JWKS format: {exc}") from exc

        if kid:
            raise InvalidTokenError(f"Key with kid '{kid}' not found in JWKS.")
        raise InvalidTokenError("JWKS contains no keys.")

    def _extract_roles_and_scopes(self, payload: Dict[str, Any]) -> tuple[Role, List[str]]:
        """
        Extracts role and scopes from token payload across major identity providers
        (Keycloak, Entra ID, Auth0, Cognito, standard OAuth 2.1).
        """
        scopes: List[str] = []
        raw_scope = payload.get("scope") or payload.get("scp")
        if isinstance(raw_scope, str):
            scopes.extend(raw_scope.split())
        elif isinstance(raw_scope, list):
            scopes.extend([str(s) for s in raw_scope])

        # Candidate roles collected from standard claim locations
        candidates: List[str] = []

        # 1. Direct scopes (e.g. 'mcp:admin', 'mcp:editor', 'mcp:viewer')
        for sc in scopes:
            if sc.startswith("mcp:"):
                candidates.append(sc[4:])

        # 2. 'roles' or 'role' claim
        roles_claim = payload.get("roles") or payload.get("role")
        if isinstance(roles_claim, list):
            candidates.extend([str(r) for r in roles_claim])
        elif isinstance(roles_claim, str):
            candidates.append(roles_claim)

        # 3. Keycloak 'realm_access.roles'
        realm_access = payload.get("realm_access")
        if isinstance(realm_access, dict):
            realm_roles = realm_access.get("roles")
            if isinstance(realm_roles, list):
                candidates.extend([str(r) for r in realm_roles])

        # 4. Groups / Cognito groups
        groups = payload.get("groups") or payload.get("cognito:groups")
        if isinstance(groups, list):
            candidates.extend([str(g) for g in groups])

        # Determine highest role level
        resolved_role = Role.VIEWER
        for cand in candidates:
            cand_role = Role.from_str(cand)
            if cand_role > resolved_role:
                resolved_role = cand_role

        if f"mcp:{resolved_role.value}" not in scopes:
            scopes.append(f"mcp:{resolved_role.value}")

        return resolved_role, scopes

    def validate_jwt(self, token: str) -> AuthContext:
        """
        Validates token signature, expiration, issuer, audience, and extracts claims.
        """
        if not token or not isinstance(token, str):
            raise InvalidTokenError("JWT token must be a non-empty string.")

        signing_key = self._find_signing_key(token)

        try:
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": False,  # Manual check below for flexible trailing slashes
                    "verify_aud": False,  # Manual RFC 8707 resource matching check below
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredTokenError("JWT token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError(f"Invalid JWT token: {exc}") from exc
        except Exception as exc:
            raise InvalidTokenError(f"JWT verification error: {exc}") from exc

        # Verify Issuer if configured
        if self.oidc_issuer:
            token_iss = (payload.get("iss") or "").rstrip("/")
            if token_iss != self.oidc_issuer:
                raise InvalidTokenError(f"Issuer mismatch: expected '{self.oidc_issuer}', got '{token_iss}'.")

        # Verify Audience / RFC 8707 Resource Indicator if configured
        if self.resource_indicator:
            aud = payload.get("aud")
            resource = payload.get("resource")
            aud_list = [aud] if isinstance(aud, str) else (aud if isinstance(aud, list) else [])
            res_list = [resource] if isinstance(resource, str) else (resource if isinstance(resource, list) else [])

            all_targets = aud_list + res_list
            if self.resource_indicator not in all_targets and not any(
                isinstance(t, str) and t.rstrip("/") == self.resource_indicator.rstrip("/") for t in all_targets
            ):
                raise InvalidTokenError(
                    f"Audience/Resource mismatch: token does not target '{self.resource_indicator}'."
                )

        role, scopes = self._extract_roles_and_scopes(payload)

        return AuthContext(
            user_id=payload.get("sub") or payload.get("oid") or "jwt_user",
            name=payload.get("name") or payload.get("preferred_username"),
            role=role,
            scopes=scopes,
            auth_type="jwt",
            is_authenticated=True,
            raw_claims=payload,
        )
