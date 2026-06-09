"""Credential encryption.

OAuth tokens are the most sensitive data the system holds, so they are never
stored in plaintext. This wraps Fernet (authenticated symmetric encryption). The
key comes from CREDENTIAL_ENCRYPTION_KEY when set; otherwise it is derived from
SECRET_KEY so the system runs in development. In production, set a dedicated key
managed by a secrets manager / KMS and rotate it deliberately.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class DecryptionError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.credential_encryption_key:
        key = s.credential_encryption_key.encode()
    else:
        # Derive a valid 32-byte urlsafe-base64 key from the app secret.
        digest = hashlib.sha256(s.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # tampered or wrong key
        raise DecryptionError("could not decrypt credential") from exc
