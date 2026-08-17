"""Encryption for target-database credentials.

Credentials for a user's database are the most sensitive thing this system
stores. They are Fernet-encrypted at rest, decrypted only to open a
connection, and never logged or returned over the API.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class DecryptionError(RuntimeError):
    """Ciphertext could not be decrypted - wrong key, or tampering."""


def _derive_key() -> bytes:
    """Return the Fernet key, deriving one from SECRET_KEY if unset.

    A dedicated CREDENTIAL_ENCRYPTION_KEY is strongly preferred: it can be
    rotated independently of the JWT signing key. The derivation exists so
    development works with no extra setup, and is deterministic so restarts
    can still read what they wrote.
    """
    configured = settings.CREDENTIAL_ENCRYPTION_KEY
    if configured:
        return configured.encode() if isinstance(configured, str) else configured

    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    return Fernet(_derive_key()).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    try:
        return Fernet(_derive_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise DecryptionError(
            "Stored credentials could not be decrypted. The encryption key "
            "has probably changed since they were saved."
        ) from exc


def generate_key() -> str:
    """Mint a fresh key for CREDENTIAL_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode("utf-8")
