"""Password hashing and JWT issuance/verification."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_TYPE = "access"


def hash_password(plain: str) -> str:
    # bcrypt silently truncates past 72 bytes; refuse rather than hash a
    # prefix and give the user a false sense of password strength.
    if len(plain.encode("utf-8")) > 72:
        raise ValueError("Password exceeds bcrypt's 72-byte limit")
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # Malformed hash in the database — treat as a failed login, not a 500.
        return False


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    **claims: Any,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": TOKEN_TYPE,
        **claims,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Return the token payload, or ``None`` if it is invalid or expired."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None
    if payload.get("type") != TOKEN_TYPE:
        return None
    return payload
