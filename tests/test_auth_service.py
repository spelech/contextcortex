"""
Unit and integration tests for MCP 2026-07-28 Auth & RBAC Security Engine.
Tests models, ApiKeyService, JwtValidator, AuthService routing, role hierarchy,
and bypass modes.
"""

import time
import json
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from unittest.mock import patch, MagicMock

import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.services.database.engine import get_db_engine, init_db
from app.services.auth.models import (
    Role,
    AuthContext,
    AuthUser,
    ApiKeyCreate,
    ApiKeyOut,
)
from app.services.auth.key_service import ApiKeyService
from app.services.auth.jwt_validator import JwtValidator
from app.services.auth.service import (
    AuthService,
    get_auth_service,
    AuthException,
    AuthenticationError,
    InvalidTokenError,
    ExpiredTokenError,
    ForbiddenError,
)


@pytest.fixture(autouse=True)
def reset_auth_singleton():
    """Ensures AuthService singleton is clean and resets to auth_enabled=False after each test."""
    yield
    get_auth_service(reset=True, auth_enabled=False)


@pytest.fixture
def db_engine(tmp_path):
    """Provides a fresh isolated SQLite database engine for testing."""
    db_file = tmp_path / "test_auth.db"
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    return engine


@pytest.fixture
def rsa_keypair():
    """Generates an ephemeral RSA private/public key pair for JWT testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # Export JWK format
    public_numbers = public_key.public_numbers()
    def int_to_b64(val):
        bytes_val = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(bytes_val).decode("utf-8").rstrip("=")

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "test-key-id-1",
        "n": int_to_b64(public_numbers.n),
        "e": int_to_b64(public_numbers.e),
    }

    return {
        "private_pem": private_pem,
        "public_pem": public_pem,
        "jwk": jwk,
        "jwks": {"keys": [jwk]},
        "kid": "test-key-id-1",
    }


# ==========================================
# 1. Role and Model Unit Tests
# ==========================================

def test_role_enum_values_and_hierarchy():
    assert Role.ADMIN == "admin"
    assert Role.EDITOR == "editor"
    assert Role.VIEWER == "viewer"

    # Hierarchy comparison: ADMIN > EDITOR > VIEWER
    assert Role.ADMIN >= Role.ADMIN
    assert Role.ADMIN >= Role.EDITOR
    assert Role.ADMIN >= Role.VIEWER

    assert Role.EDITOR >= Role.EDITOR
    assert Role.EDITOR >= Role.VIEWER
    assert not (Role.EDITOR >= Role.ADMIN)

    assert Role.VIEWER >= Role.VIEWER
    assert not (Role.VIEWER >= Role.EDITOR)
    assert not (Role.VIEWER >= Role.ADMIN)


def test_role_from_str():
    assert Role.from_str("admin") == Role.ADMIN
    assert Role.from_str("ADMIN") == Role.ADMIN
    assert Role.from_str("editor") == Role.EDITOR
    assert Role.from_str("Editor") == Role.EDITOR
    assert Role.from_str("viewer") == Role.VIEWER
    assert Role.from_str("unknown") == Role.VIEWER
    assert Role.from_str(None) == Role.VIEWER
    assert Role.from_str(Role.ADMIN) == Role.ADMIN


def test_auth_context_and_user_alias():
    ctx = AuthContext(
        user_id="alice",
        name="Alice Dev",
        role=Role.ADMIN,
        scopes=["mcp:admin", "mcp:editor"],
        auth_type="api_key",
        key_id=1,
        group_name="Engineering",
    )
    assert ctx.user_id == "alice"
    assert ctx.role == Role.ADMIN
    assert ctx.has_role(Role.EDITOR) is True
    assert ctx.has_role(Role.ADMIN) is True
    assert ctx.is_authenticated is True

    # AuthUser is alias / compatible model
    user = AuthUser(user_id="bob", role=Role.VIEWER)
    assert user.role == Role.VIEWER
    assert user.has_role(Role.EDITOR) is False


def test_api_key_create_and_out_models():
    req = ApiKeyCreate(name="Test Key", role=Role.EDITOR, group_name="Devs")
    assert req.name == "Test Key"
    assert req.role == Role.EDITOR

    out = ApiKeyOut(
        id=1,
        name="Test Key",
        key_prefix="cc_live_1234",
        role="editor",
        group_name="Devs",
        secret_key="cc_live_1234secret",
    )
    assert out.id == 1
    assert out.secret_key == "cc_live_1234secret"


# ==========================================
# 2. ApiKeyService Unit Tests
# ==========================================

def test_api_key_issue_and_validate(db_engine):
    key_service = ApiKeyService(engine=db_engine)

    # Issue a key
    issued = key_service.issue_api_key(
        name="Cursor IDE Key",
        role=Role.ADMIN,
        group_name="DevOps",
    )

    assert issued.id is not None
    assert issued.name == "Cursor IDE Key"
    assert issued.role == "admin"
    assert issued.group_name == "DevOps"
    assert issued.secret_key is not None
    assert issued.secret_key.startswith("cc_live_")
    assert issued.key_prefix in issued.secret_key

    # Validate valid key
    auth_ctx = key_service.validate_api_key(issued.secret_key)
    assert auth_ctx is not None
    assert auth_ctx.role == Role.ADMIN
    assert auth_ctx.auth_type == "api_key"
    assert auth_ctx.key_id == issued.id
    assert auth_ctx.group_name == "DevOps"
    assert auth_ctx.is_authenticated is True
    assert "mcp:admin" in auth_ctx.scopes

    # Verify last_used_at was updated
    key_record = key_service.get_api_key(issued.id)
    assert key_record is not None
    assert key_record.last_used_at is not None
    assert key_record.secret_key is None  # Never expose secret_key in lookup


def test_api_key_validate_invalid_and_tampered_key(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    issued = key_service.issue_api_key(name="Valid Key", role=Role.EDITOR)

    # Completely wrong key
    with pytest.raises(InvalidTokenError):
        key_service.validate_api_key("cc_live_totally_fake_key_1234567890")

    # Non-prefixed string
    with pytest.raises(InvalidTokenError):
        key_service.validate_api_key("invalid_prefix_random_token")

    # Empty or None key
    with pytest.raises(InvalidTokenError):
        key_service.validate_api_key("")


def test_api_key_expiration(db_engine):
    key_service = ApiKeyService(engine=db_engine)

    # Key expired in the past
    past_time = datetime.now(timezone.utc) - timedelta(hours=1)
    expired_key = key_service.issue_api_key(
        name="Expired Key",
        role=Role.VIEWER,
        expires_at=past_time,
    )

    with pytest.raises(ExpiredTokenError):
        key_service.validate_api_key(expired_key.secret_key)

    # Key valid in the future
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    future_key = key_service.issue_api_key(
        name="Future Key",
        role=Role.VIEWER,
        expires_at=future_time,
    )
    ctx = key_service.validate_api_key(future_key.secret_key)
    assert ctx is not None
    assert ctx.role == Role.VIEWER


def test_api_key_revocation_and_deletion(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    issued = key_service.issue_api_key(name="To Revoke", role=Role.EDITOR)

    # Revoke key (is_active = False)
    revoked = key_service.revoke_api_key(issued.id)
    assert revoked is True

    # Validating revoked key raises InvalidTokenError
    with pytest.raises(InvalidTokenError):
        key_service.validate_api_key(issued.secret_key)

    # List keys shows is_active=False
    keys = key_service.list_api_keys()
    assert len(keys) == 1
    assert keys[0].is_active is False

    # Delete key completely
    deleted = key_service.delete_api_key(issued.id)
    assert deleted is True
    assert len(key_service.list_api_keys()) == 0


def test_api_key_list_multiple(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    k1 = key_service.issue_api_key(name="Key 1", role=Role.ADMIN)
    k2 = key_service.issue_api_key(name="Key 2", role=Role.EDITOR)
    k3 = key_service.issue_api_key(name="Key 3", role=Role.VIEWER)

    keys = key_service.list_api_keys()
    assert len(keys) == 3
    names = {k.name for k in keys}
    assert names == {"Key 1", "Key 2", "Key 3"}
    for k in keys:
        assert k.secret_key is None  # Masks secret key in listing


# ==========================================
# 3. JwtValidator Unit Tests
# ==========================================

def test_jwt_validator_with_valid_token(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        jwks_uri="https://auth.example.com/.well-known/jwks.json",
        resource_indicator="https://contextcortex.local",
    )

    # Create payload
    now = int(time.time())
    payload = {
        "sub": "user_12345",
        "name": "Alice Admin",
        "iss": "https://auth.example.com",
        "aud": "https://contextcortex.local",
        "exp": now + 3600,
        "iat": now,
        "scope": "openid profile mcp:admin",
    }

    token = jwt.encode(
        payload,
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    # Mock JWKS fetcher
    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        auth_ctx = validator.validate_jwt(token)
        assert auth_ctx.user_id == "user_12345"
        assert auth_ctx.name == "Alice Admin"
        assert auth_ctx.role == Role.ADMIN
        assert "mcp:admin" in auth_ctx.scopes
        assert auth_ctx.auth_type == "jwt"
        assert auth_ctx.is_authenticated is True


def test_jwt_validator_role_extraction_sources(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        resource_indicator="https://contextcortex.local",
    )

    now = int(time.time())

    def create_token(extra_claims):
        p = {
            "sub": "user_test",
            "iss": "https://auth.example.com",
            "aud": "https://contextcortex.local",
            "exp": now + 3600,
            **extra_claims,
        }
        return jwt.encode(
            p,
            rsa_keypair["private_pem"],
            algorithm="RS256",
            headers={"kid": rsa_keypair["kid"]},
        )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        # 1. Extract from roles list
        token_roles = create_token({"roles": ["editor"]})
        assert validator.validate_jwt(token_roles).role == Role.EDITOR

        # 2. Extract from realm_access (Keycloak)
        token_keycloak = create_token({"realm_access": {"roles": ["admin", "default-roles"]}})
        assert validator.validate_jwt(token_keycloak).role == Role.ADMIN

        # 3. Extract from groups list
        token_groups = create_token({"groups": ["mcp-viewers", "viewer"]})
        assert validator.validate_jwt(token_groups).role == Role.VIEWER

        # 4. Default to viewer if no explicit role claim
        token_default = create_token({})
        assert validator.validate_jwt(token_default).role == Role.VIEWER


def test_jwt_validator_expired_and_invalid_signature(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        resource_indicator="https://contextcortex.local",
    )

    now = int(time.time())

    # Expired token
    expired_token = jwt.encode(
        {
            "sub": "user_expired",
            "iss": "https://auth.example.com",
            "aud": "https://contextcortex.local",
            "exp": now - 300,
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        with pytest.raises(ExpiredTokenError):
            validator.validate_jwt(expired_token)

    # Invalid signature (signed with different key)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    tampered_token = jwt.encode(
        {
            "sub": "user_tampered",
            "iss": "https://auth.example.com",
            "aud": "https://contextcortex.local",
            "exp": now + 3600,
        },
        other_pem,
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        with pytest.raises(InvalidTokenError):
            validator.validate_jwt(tampered_token)


def test_jwt_validator_issuer_and_audience_mismatch(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        resource_indicator="https://contextcortex.local",
    )
    now = int(time.time())

    # Wrong issuer
    wrong_iss_token = jwt.encode(
        {
            "sub": "user_1",
            "iss": "https://evil.com",
            "aud": "https://contextcortex.local",
            "exp": now + 3600,
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        with pytest.raises(InvalidTokenError):
            validator.validate_jwt(wrong_iss_token)

    # Wrong audience
    wrong_aud_token = jwt.encode(
        {
            "sub": "user_1",
            "iss": "https://auth.example.com",
            "aud": "https://other-service.com",
            "exp": now + 3600,
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        with pytest.raises(InvalidTokenError):
            validator.validate_jwt(wrong_aud_token)


# ==========================================
# 4. Master AuthService Routing & RBAC Tests
# ==========================================

def test_auth_service_bypass_when_disabled():
    # When AUTH_ENABLED is False (or default)
    auth_service = AuthService(auth_enabled=False)
    assert auth_service.is_auth_enabled() is False

    # Empty token, random token, or Bearer token implicitly returns admin context
    ctx = auth_service.authenticate_token(None)
    assert ctx.role == Role.ADMIN
    assert ctx.auth_type == "bypass"
    assert ctx.is_authenticated is True

    ctx2 = auth_service.authenticate_token("Bearer random_string")
    assert ctx2.role == Role.ADMIN
    assert ctx2.auth_type == "bypass"


def test_auth_service_routes_api_key(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    issued = key_service.issue_api_key(name="AuthService Test Key", role=Role.EDITOR)

    auth_service = AuthService(
        auth_enabled=True,
        key_service=key_service,
    )

    # Authenticate with Bearer prefix
    ctx = auth_service.authenticate_token(f"Bearer {issued.secret_key}")
    assert ctx.role == Role.EDITOR
    assert ctx.auth_type == "api_key"
    assert ctx.key_id == issued.id

    # Authenticate without Bearer prefix
    ctx2 = auth_service.authenticate_token(issued.secret_key)
    assert ctx2.role == Role.EDITOR
    assert ctx2.key_id == issued.id


def test_auth_service_routes_jwt(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        resource_indicator="https://contextcortex.local",
    )
    auth_service = AuthService(
        auth_enabled=True,
        jwt_validator=validator,
    )

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "jwt_user",
            "iss": "https://auth.example.com",
            "aud": "https://contextcortex.local",
            "exp": now + 3600,
            "scope": "mcp:admin",
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_get_jwks", return_value=rsa_keypair["jwks"]):
        ctx = auth_service.authenticate_token(f"Bearer {token}")
        assert ctx.user_id == "jwt_user"
        assert ctx.role == Role.ADMIN
        assert ctx.auth_type == "jwt"


def test_auth_service_rejects_missing_token_when_enabled():
    auth_service = AuthService(auth_enabled=True)

    with pytest.raises(AuthenticationError):
        auth_service.authenticate_token(None)

    with pytest.raises(AuthenticationError):
        auth_service.authenticate_token("")

    with pytest.raises(AuthenticationError):
        auth_service.authenticate_token("Bearer ")


def test_auth_service_rbac_permissions():
    auth_service = AuthService(auth_enabled=True)

    admin_ctx = AuthContext(user_id="admin_user", role=Role.ADMIN)
    editor_ctx = AuthContext(user_id="editor_user", role=Role.EDITOR)
    viewer_ctx = AuthContext(user_id="viewer_user", role=Role.VIEWER)

    # Role permission checks
    assert auth_service.check_role_permission(admin_ctx, Role.ADMIN) is True
    assert auth_service.check_role_permission(admin_ctx, Role.EDITOR) is True
    assert auth_service.check_role_permission(admin_ctx, Role.VIEWER) is True

    assert auth_service.check_role_permission(editor_ctx, Role.ADMIN) is False
    assert auth_service.check_role_permission(editor_ctx, Role.EDITOR) is True
    assert auth_service.check_role_permission(editor_ctx, Role.VIEWER) is True

    assert auth_service.check_role_permission(viewer_ctx, Role.ADMIN) is False
    assert auth_service.check_role_permission(viewer_ctx, Role.EDITOR) is False
    assert auth_service.check_role_permission(viewer_ctx, Role.VIEWER) is True

    # require_role raises ForbiddenError on insufficient privileges
    auth_service.require_role(admin_ctx, Role.ADMIN)  # Should not raise
    auth_service.require_role(editor_ctx, Role.EDITOR)  # Should not raise
    auth_service.require_role(viewer_ctx, Role.VIEWER)  # Should not raise

    with pytest.raises(ForbiddenError):
        auth_service.require_role(editor_ctx, Role.ADMIN)

    with pytest.raises(ForbiddenError):
        auth_service.require_role(viewer_ctx, Role.EDITOR)


def test_auth_service_proxies_key_management(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    auth_service = AuthService(auth_enabled=True, key_service=key_service)

    # Issue key via auth_service
    key = auth_service.issue_api_key("Proxy Key", role=Role.ADMIN)
    assert key.name == "Proxy Key"
    assert key.role == "admin"

    # List keys via auth_service
    keys = auth_service.list_api_keys()
    assert len(keys) == 1

    # Revoke key via auth_service
    assert auth_service.revoke_api_key(key.id) is True
    assert auth_service.list_api_keys()[0].is_active is False

    # Delete key via auth_service
    assert auth_service.delete_api_key(key.id) is True
    assert len(auth_service.list_api_keys()) == 0


def test_auth_service_singleton_getter():
    s1 = get_auth_service(reset=True, auth_enabled=False)
    s2 = get_auth_service()
    assert s1 is s2

    s3 = get_auth_service(reset=True, auth_enabled=True)
    assert s3 is not s1
    assert s3.is_auth_enabled() is True


def test_auth_context_has_scope_admin_override():
    admin_ctx = AuthContext(role=Role.ADMIN, scopes=["mcp:admin"])
    viewer_ctx = AuthContext(role=Role.VIEWER, scopes=["mcp:viewer"])

    assert admin_ctx.has_scope("mcp:custom_scope") is True
    assert viewer_ctx.has_scope("mcp:viewer") is True
    assert viewer_ctx.has_scope("mcp:admin") is False


def test_api_key_get_nonexistent(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    assert key_service.get_api_key(99999) is None
    assert key_service.revoke_api_key(99999) is False
    assert key_service.delete_api_key(99999) is False


def test_jwt_validator_oidc_discovery_resolution(rsa_keypair):
    validator = JwtValidator(oidc_issuer="https://auth.example.com")
    
    mock_discovery_resp = MagicMock()
    mock_discovery_resp.json.return_value = {
        "issuer": "https://auth.example.com",
        "jwks_uri": "https://auth.example.com/oauth2/v1/keys",
    }
    mock_discovery_resp.raise_for_status = MagicMock()

    mock_jwks_resp = MagicMock()
    mock_jwks_resp.json.return_value = rsa_keypair["jwks"]
    mock_jwks_resp.raise_for_status = MagicMock()

    def mock_get(url, *args, **kwargs):
        if ".well-known/openid-configuration" in url:
            return mock_discovery_resp
        elif "oauth2/v1/keys" in url:
            return mock_jwks_resp
        raise ValueError(f"Unexpected url {url}")

    with patch("httpx.Client.get", side_effect=mock_get):
        jwks = validator._get_jwks()
        assert jwks == rsa_keypair["jwks"]
        assert validator.jwks_uri == "https://auth.example.com/oauth2/v1/keys"


def test_jwt_validator_stale_cache_refresh(rsa_keypair):
    validator = JwtValidator(
        oidc_issuer="https://auth.example.com",
        jwks_uri="https://auth.example.com/keys",
    )
    
    # Pre-populate with empty JWKS
    validator._cached_jwks = {"keys": []}
    validator._jwks_fetched_at = time.time()

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "user_refresh",
            "iss": "https://auth.example.com",
            "exp": now + 3600,
        },
        rsa_keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )

    with patch.object(validator, "_resolve_jwks_uri", return_value="https://auth.example.com/keys"):
        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = rsa_keypair["jwks"]
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            # Token validation should detect missing kid in cache, refresh cache, and succeed
            ctx = validator.validate_jwt(token)
            assert ctx.user_id == "user_refresh"

