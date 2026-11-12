"""
Unit and integration tests for API Key issuance/revocation and OIDC/JWT
token validation, JWKS discovery, and cache refresh sessions.
"""

import base64
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.auth.jwt_validator import JwtValidator
from app.services.auth.key_service import ApiKeyService
from app.services.auth.models import Role
from app.services.auth.service import (
    ExpiredTokenError,
    InvalidTokenError,
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
    db_file = tmp_path / "test_auth_tokens.db"
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
# 1. ApiKeyService Unit Tests
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
    key_service.issue_api_key(name="Valid Key", role=Role.EDITOR)

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
    key_service.issue_api_key(name="Key 1", role=Role.ADMIN)
    key_service.issue_api_key(name="Key 2", role=Role.EDITOR)
    key_service.issue_api_key(name="Key 3", role=Role.VIEWER)

    keys = key_service.list_api_keys()
    assert len(keys) == 3
    names = {k.name for k in keys}
    assert names == {"Key 1", "Key 2", "Key 3"}
    for k in keys:
        assert k.secret_key is None  # Masks secret key in listing


def test_api_key_get_nonexistent(db_engine):
    key_service = ApiKeyService(engine=db_engine)
    assert key_service.get_api_key(99999) is None
    assert key_service.revoke_api_key(99999) is False
    assert key_service.delete_api_key(99999) is False


# ==========================================
# 2. JwtValidator Unit Tests
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
