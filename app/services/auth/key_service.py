"""
Database-backed API Key Management Service for MCP 2026-07-28 Auth & RBAC.
Handles generation, hashing (SHA-256), DB storage, last_used tracking,
revocation, and validation of `cc_live_...` API keys.
"""

import os
import hashlib
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional, List, Union

from sqlalchemy import Engine, select, update, delete, func
from app.services.database.engine import get_db_engine, get_connection
from app.services.database.schema import TABLES
from app.services.auth.models import (
    Role,
    AuthContext,
    ApiKeyOut,
    InvalidTokenError,
    ExpiredTokenError,
)

logger = logging.getLogger("contextcortex.auth.key_service")

# Standard ContextCortex API key prefix
API_KEY_PREFIX = "cc_live_"


class ApiKeyService:
    """
    Manages generation, storage, hashing, and validation of database API keys.
    """

    def __init__(self, engine: Optional[Engine] = None):
        self._engine = engine

    def _get_engine(self, engine: Optional[Engine] = None) -> Engine:
        return engine or self._engine or get_db_engine()

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """Computes deterministic SHA-256 hash of secret key string."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def issue_api_key(
        self,
        name: str,
        role: Union[Role, str] = Role.VIEWER,
        group_name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        engine: Optional[Engine] = None,
    ) -> ApiKeyOut:
        """
        Generates a new secure API key, persists its SHA-256 hash in the database,
        and returns an ApiKeyOut model containing the plaintext `secret_key`.
        """
        eng = self._get_engine(engine)
        assigned_role = Role.from_str(role)

        # Generate 32 bytes random entropy URL-safe string
        token_entropy = secrets.token_urlsafe(32)
        secret_key = f"{API_KEY_PREFIX}{token_entropy}"
        
        # Key prefix for identification and indexing (max 16 chars, e.g. "cc_live_a1b2c3d4")
        key_prefix = secret_key[:16]
        key_hash = self.hash_key(secret_key)

        now = datetime.now(timezone.utc)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            stmt = api_keys_table.insert().values(
                name=name.strip(),
                key_prefix=key_prefix,
                key_hash=key_hash,
                role=assigned_role.value,
                group_name=group_name.strip() if group_name else None,
                expires_at=expires_at,
                created_at=now,
                last_used_at=None,
                is_active=True,
            )
            result = conn.execute(stmt)
            conn.commit()

            # Retrieve inserted primary key
            inserted_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
            if inserted_id is None:
                # Fallback query for engines without inserted_primary_key
                row = conn.execute(
                    select(api_keys_table.c.id).where(api_keys_table.c.key_hash == key_hash)
                ).first()
                inserted_id = row[0] if row else 0

        logger.info(f"Issued new API key '{name}' (id={inserted_id}, prefix={key_prefix}, role={assigned_role.value})")

        return ApiKeyOut(
            id=inserted_id,
            name=name.strip(),
            key_prefix=key_prefix,
            role=assigned_role.value,
            group_name=group_name.strip() if group_name else None,
            expires_at=expires_at,
            created_at=now,
            last_used_at=None,
            is_active=True,
            secret_key=secret_key,
        )

    def validate_api_key(
        self,
        raw_key: str,
        engine: Optional[Engine] = None,
    ) -> AuthContext:
        """
        Validates a plaintext API key against the database hash.
        Checks active status, expiration timestamp, updates `last_used_at`,
        and returns an AuthContext with appropriate Role and scopes.
        """
        if not raw_key or not isinstance(raw_key, str):
            raise InvalidTokenError("API key must be a non-empty string.")

        raw_key = raw_key.strip()
        if not raw_key.startswith("cc_"):
            raise InvalidTokenError("Invalid API key format (expected 'cc_...' prefix).")

        key_hash = self.hash_key(raw_key)
        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            query = select(api_keys_table).where(api_keys_table.c.key_hash == key_hash)
            row = conn.execute(query).mappings().fetchone()

            if not row:
                raise InvalidTokenError("Invalid API key.")

            if not row["is_active"]:
                raise InvalidTokenError("API key is deactivated or revoked.")

            expires_at = row["expires_at"]
            now_utc = datetime.now(timezone.utc)
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    # SQLite stores naive UTC
                    now_naive = now_utc.replace(tzinfo=None)
                    if expires_at < now_naive:
                        raise ExpiredTokenError("API key has expired.")
                else:
                    if expires_at < now_utc:
                        raise ExpiredTokenError("API key has expired.")

            # Update last_used_at timestamp
            conn.execute(
                update(api_keys_table)
                .where(api_keys_table.c.id == row["id"])
                .values(last_used_at=now_utc)
            )
            conn.commit()

        role = Role.from_str(row["role"])
        return AuthContext(
            user_id=f"key_{row['id']}",
            name=row["name"],
            role=role,
            scopes=[f"mcp:{role.value}"],
            auth_type="api_key",
            key_id=row["id"],
            group_name=row["group_name"],
            is_authenticated=True,
        )

    def revoke_api_key(
        self,
        key_id: int,
        engine: Optional[Engine] = None,
    ) -> bool:
        """
        Deactivates an API key by setting `is_active = False`.
        """
        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            stmt = (
                update(api_keys_table)
                .where(api_keys_table.c.id == key_id)
                .values(is_active=False)
            )
            result = conn.execute(stmt)
            conn.commit()
            return (result.rowcount or 0) > 0

    def delete_api_key(
        self,
        key_id: int,
        engine: Optional[Engine] = None,
    ) -> bool:
        """
        Permanently deletes an API key record from the database.
        """
        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            stmt = delete(api_keys_table).where(api_keys_table.c.id == key_id)
            result = conn.execute(stmt)
            conn.commit()
            return (result.rowcount or 0) > 0

    def get_api_key(
        self,
        key_id: int,
        engine: Optional[Engine] = None,
    ) -> Optional[ApiKeyOut]:
        """
        Fetches an API key by ID (with secret_key masked as None).
        """
        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            query = select(api_keys_table).where(api_keys_table.c.id == key_id)
            row = conn.execute(query).mappings().fetchone()
            if not row:
                return None

            return ApiKeyOut(
                id=row["id"],
                name=row["name"],
                key_prefix=row["key_prefix"],
                role=row["role"],
                group_name=row["group_name"],
                expires_at=row["expires_at"],
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
                is_active=bool(row["is_active"]),
                secret_key=None,
            )

    def list_api_keys(
        self,
        engine: Optional[Engine] = None,
    ) -> List[ApiKeyOut]:
        """
        Lists all registered API keys in the system (with secret_key masked as None).
        """
        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        with get_connection(eng) as conn:
            query = select(api_keys_table).order_by(api_keys_table.c.id.desc())
            rows = conn.execute(query).mappings().fetchall()

            return [
                ApiKeyOut(
                    id=row["id"],
                    name=row["name"],
                    key_prefix=row["key_prefix"],
                    role=row["role"],
                    group_name=row["group_name"],
                    expires_at=row["expires_at"],
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                    is_active=bool(row["is_active"]),
                    secret_key=None,
                )
                for row in rows
            ]

    def bootstrap_admin_key(
        self,
        initial_key: Optional[str] = None,
        name: str = "Initial Admin Key",
        engine: Optional[Engine] = None,
    ) -> Optional[ApiKeyOut]:
        """
        Bootstraps an initial admin API key if initial_key (or ADMIN_INITIAL_KEY env var) is set.
        - If 'auto', 'true', '1', or 'generate': auto-issues a new admin key if no active admin key exists.
        - If a custom key string is given: idempotently registers/ensures the key exists in the database.
        """
        raw_val = (initial_key or os.getenv("ADMIN_INITIAL_KEY") or "").strip()
        if not raw_val:
            return None

        eng = self._get_engine(engine)
        api_keys_table = TABLES["api_keys"]

        if raw_val.lower() in ("auto", "true", "1", "generate", "yes"):
            with get_connection(eng) as conn:
                existing_admin = conn.execute(
                    select(api_keys_table.c.id).where(
                        api_keys_table.c.role == Role.ADMIN.value,
                        api_keys_table.c.is_active == True,
                    )
                ).first()
                if existing_admin:
                    logger.info("Active admin API key already exists; skipping auto-generation.")
                    return None
            key = self.issue_api_key(
                name=name,
                role=Role.ADMIN,
                group_name="admin",
                engine=eng,
            )
            logger.info(f"Auto-bootstrapped initial admin API key (prefix: {key.key_prefix})")
            return key

        # Custom explicit secret key specified
        secret_key = raw_val if raw_val.startswith("cc_") else f"{API_KEY_PREFIX}{raw_val}"
        key_prefix = secret_key[:16]
        key_hash = self.hash_key(secret_key)

        with get_connection(eng) as conn:
            row = conn.execute(
                select(api_keys_table).where(api_keys_table.c.key_hash == key_hash)
            ).mappings().fetchone()

            if row:
                logger.info(f"Bootstrap admin key already registered (id={row['id']}, prefix={key_prefix})")
                return ApiKeyOut(
                    id=row["id"],
                    name=row["name"],
                    key_prefix=row["key_prefix"],
                    role=row["role"],
                    group_name=row["group_name"],
                    expires_at=row["expires_at"],
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                    is_active=bool(row["is_active"]),
                    secret_key=secret_key,
                )

            now = datetime.now(timezone.utc)
            stmt = api_keys_table.insert().values(
                name=name.strip(),
                key_prefix=key_prefix,
                key_hash=key_hash,
                role=Role.ADMIN.value,
                group_name="admin",
                expires_at=None,
                created_at=now,
                last_used_at=None,
                is_active=True,
            )
            result = conn.execute(stmt)
            conn.commit()

            inserted_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
            if inserted_id is None:
                r = conn.execute(
                    select(api_keys_table.c.id).where(api_keys_table.c.key_hash == key_hash)
                ).first()
                inserted_id = r[0] if r else 0

        logger.info(f"Bootstrapped configured initial admin key (id={inserted_id}, prefix={key_prefix})")
        return ApiKeyOut(
            id=inserted_id,
            name=name.strip(),
            key_prefix=key_prefix,
            role=Role.ADMIN.value,
            group_name="admin",
            expires_at=None,
            created_at=now,
            last_used_at=None,
            is_active=True,
            secret_key=secret_key,
        )

