"""
Unit and integration tests for MCP 2026-07-28 Auth & RBAC Security Engine.
Tests models, AuthService routing, role hierarchy, RBAC enforcement,
key management proxies, and bypass modes.
"""

import base64
import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.auth.jwt_validator import JwtValidator
from app.services.auth.key_service import ApiKeyService
from app.services.auth.models import (
    ApiKeyCreate,
    ApiKeyOut,
    AuthContext,
    AuthUser,
    Role,
)
from app.services.auth.service import (
    AuthenticationError,
    AuthService,
    ForbiddenError,
    get_auth_service,
)
from app.services.database.engine import get_db_engine, init_db


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


def test_auth_context_has_scope_admin_override():
    admin_ctx = AuthContext(role=Role.ADMIN, scopes=["mcp:admin"])
    viewer_ctx = AuthContext(role=Role.VIEWER, scopes=["mcp:viewer"])

    assert admin_ctx.has_scope("mcp:custom_scope") is True
    assert viewer_ctx.has_scope("mcp:viewer") is True
    assert viewer_ctx.has_scope("mcp:admin") is False


# ==========================================
# 2. Master AuthService Routing & RBAC Tests
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
