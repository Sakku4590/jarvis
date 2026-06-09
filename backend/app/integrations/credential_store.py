"""Credential store.

Persists per-(user, provider) OAuth token dicts. The Postgres implementation
encrypts the token JSON before it ever touches the database and decrypts on
load, so the `integrations` table only ever holds ciphertext. An in-memory
implementation backs tests.
"""

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.db.models import Integration
from app.db.session import SessionLocal

log = get_logger(__name__)


class CredentialStore(ABC):
    @abstractmethod
    async def save(self, user_id: str, provider: str, token: dict) -> None: ...

    @abstractmethod
    async def load(self, user_id: str, provider: str) -> dict | None: ...

    @abstractmethod
    async def delete(self, user_id: str, provider: str) -> None: ...


class EncryptedPgCredentialStore(CredentialStore):
    async def save(self, user_id: str, provider: str, token: dict) -> None:
        blob = encrypt(json.dumps(token))
        expiry = token.get("expiry")
        async with SessionLocal() as session:
            stmt = pg_insert(Integration).values(
                user_id=uuid.UUID(user_id),
                provider=provider,
                credentials_encrypted=blob,
                scopes=token.get("scopes"),
                status="active",
                expires_at=_parse_dt(expiry),
            ).on_conflict_do_update(
                index_elements=["user_id", "provider"],
                set_={
                    "credentials_encrypted": blob,
                    "scopes": token.get("scopes"),
                    "status": "active",
                    "expires_at": _parse_dt(expiry),
                },
            )
            await session.execute(stmt)
            await session.commit()
        log.info("integration.saved", provider=provider, user_id=user_id)

    async def load(self, user_id: str, provider: str) -> dict | None:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(Integration).where(
                    Integration.user_id == uuid.UUID(user_id),
                    Integration.provider == provider,
                ))).scalar_one_or_none()
        if row is None:
            return None
        return json.loads(decrypt(row.credentials_encrypted))

    async def delete(self, user_id: str, provider: str) -> None:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(Integration).where(
                    Integration.user_id == uuid.UUID(user_id),
                    Integration.provider == provider,
                ))).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()


class InMemoryCredentialStore(CredentialStore):
    def __init__(self) -> None:
        self._d: dict[tuple[str, str], dict] = {}

    async def save(self, user_id, provider, token) -> None:
        self._d[(user_id, provider)] = dict(token)

    async def load(self, user_id, provider) -> dict | None:
        return self._d.get((user_id, provider))

    async def delete(self, user_id, provider) -> None:
        self._d.pop((user_id, provider), None)


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def get_credential_store() -> CredentialStore:
    return EncryptedPgCredentialStore()
