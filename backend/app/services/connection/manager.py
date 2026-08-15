"""Target-database connection management.

Builds SQLAlchemy engines for a user's database from encrypted credentials,
and tests reachability. Engines are opened read-only wherever the dialect can
express that; the hard guarantee comes from a SELECT-only database role,
provisioned in phase 3.
"""

import json
import time
from dataclasses import dataclass
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.models.connection import Connection, Dialect

log = get_logger(__name__)

DEFAULT_PORTS = {
    Dialect.POSTGRES: 5432,
    Dialect.MYSQL: 3306,
    Dialect.SQLITE: 0,
}

DRIVERS = {
    Dialect.POSTGRES: "postgresql+psycopg",
    Dialect.MYSQL: "mysql+pymysql",
    Dialect.SQLITE: "sqlite+pysqlite",
}

CONNECT_TIMEOUT_SECONDS = 10


@dataclass
class Credentials:
    username: str = ""
    password: str = ""

    def to_json(self) -> str:
        return json.dumps({"username": self.username, "password": self.password})

    @classmethod
    def from_json(cls, raw: str) -> "Credentials":
        data = json.loads(raw)
        return cls(username=data.get("username", ""), password=data.get("password", ""))


def encrypt_credentials(credentials: Credentials) -> str:
    return encrypt(credentials.to_json())


def decrypt_credentials(connection: Connection) -> Credentials:
    return Credentials.from_json(decrypt(connection.encrypted_credentials))


def build_url(connection: Connection, credentials: Credentials) -> str:
    """Assemble a SQLAlchemy URL.

    Username and password are percent-encoded: passwords routinely contain
    ``@``, ``/`` and ``:``, which would otherwise corrupt the URL.
    """
    driver = DRIVERS[connection.dialect]

    if connection.dialect is Dialect.SQLITE:
        # No host or credentials; `database` is a filesystem path.
        return f"{driver}:///{connection.database}"

    user = quote_plus(credentials.username)
    secret = quote_plus(credentials.password)
    auth = f"{user}:{secret}@" if credentials.password else f"{user}@"

    return f"{driver}://{auth}{connection.host}:{connection.port}/{connection.database}"


def _connect_args(dialect: Dialect) -> dict:
    if dialect is Dialect.POSTGRES:
        return {
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            # Refuses writes at the session level. Defence in depth, not the
            # primary control.
            "options": "-c default_transaction_read_only=on",
        }
    if dialect is Dialect.MYSQL:
        return {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    return {"check_same_thread": False}


def create_target_engine(
    connection: Connection, credentials: Credentials | None = None
) -> Engine:
    """Open an engine against the user's database."""
    credentials = credentials or decrypt_credentials(connection)
    url = build_url(connection, credentials)

    kwargs: dict = {
        "connect_args": _connect_args(connection.dialect),
        "pool_pre_ping": True,
    }
    if connection.dialect is not Dialect.SQLITE:
        kwargs |= {"pool_size": 5, "max_overflow": 5, "pool_recycle": 1800}

    return create_engine(url, echo=False, **kwargs)


@dataclass
class ConnectionTestResult:
    ok: bool
    latency_ms: float
    server_version: str | None = None
    error: str | None = None


VERSION_QUERY = {
    Dialect.POSTGRES: "SHOW server_version",
    Dialect.MYSQL: "SELECT VERSION()",
    Dialect.SQLITE: "SELECT sqlite_version()",
}


def check_connection(
    connection: Connection, credentials: Credentials | None = None
) -> ConnectionTestResult:
    """Open a connection, read the server version, and close it.

    Never raises: a failed test is a normal outcome the UI needs to show, not
    an exception the API should surface as a 500.
    """
    started = time.perf_counter()
    engine = None
    try:
        engine = create_target_engine(connection, credentials)
        with engine.connect() as conn:
            version = conn.execute(text(VERSION_QUERY[connection.dialect])).scalar()
        elapsed = (time.perf_counter() - started) * 1000
        return ConnectionTestResult(
            ok=True, latency_ms=round(elapsed, 2), server_version=str(version)
        )
    except SQLAlchemyError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        # Driver errors embed the DSN, which contains the password.
        message = _redact(str(exc), credentials)
        log.warning("connection_test_failed", connection_id=connection.id)
        return ConnectionTestResult(
            ok=False, latency_ms=round(elapsed, 2), error=message[:500]
        )
    finally:
        if engine is not None:
            engine.dispose()


def _redact(message: str, credentials: Credentials | None) -> str:
    if credentials and credentials.password:
        message = message.replace(credentials.password, "***")
        message = message.replace(quote_plus(credentials.password), "***")
    return message
