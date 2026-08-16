"""URL construction, credential handling, and connection testing."""

from app.models.connection import Connection, Dialect
from app.services.connection.manager import (
    Credentials,
    build_url,
    check_connection,
    decrypt_credentials,
    encrypt_credentials,
)


def _connection(**kwargs) -> Connection:
    defaults = {
        "user_id": "u1",
        "name": "test",
        "dialect": Dialect.POSTGRES,
        "host": "db.example.com",
        "port": 5432,
        "database": "analytics",
        "encrypted_credentials": "",
    }
    return Connection(**{**defaults, **kwargs})


def test_postgres_url_uses_the_psycopg_driver() -> None:
    url = build_url(_connection(), Credentials("analyst", "hunter2"))
    assert url == "postgresql+psycopg://analyst:hunter2@db.example.com:5432/analytics"


def test_mysql_url_uses_the_pymysql_driver() -> None:
    url = build_url(
        _connection(dialect=Dialect.MYSQL, port=3306), Credentials("root", "pw")
    )
    assert url.startswith("mysql+pymysql://root:pw@db.example.com:3306/")


def test_special_characters_in_password_are_encoded() -> None:
    # An unencoded '@' or '/' would silently corrupt the host and database.
    url = build_url(_connection(), Credentials("analyst", "p@ss/w:rd"))

    assert "p%40ss%2Fw%3Ard" in url
    assert url.endswith("@db.example.com:5432/analytics")


def test_password_free_connection_omits_the_colon() -> None:
    url = build_url(_connection(), Credentials("analyst", ""))
    assert url == "postgresql+psycopg://analyst@db.example.com:5432/analytics"


def test_sqlite_url_is_a_file_path_with_no_credentials() -> None:
    url = build_url(
        _connection(dialect=Dialect.SQLITE, database="/tmp/demo.db"),
        Credentials("ignored", "ignored"),
    )
    assert url.startswith("sqlite+pysqlite:///file:/tmp/demo.db")
    assert "ignored" not in url


def test_sqlite_url_is_opened_read_only() -> None:
    # SQLite has no roles to grant, so the mode=ro URI is what stands in for
    # the SELECT-only database user the other dialects use.
    url = build_url(
        _connection(dialect=Dialect.SQLITE, database="/tmp/demo.db"), Credentials()
    )
    assert "mode=ro" in url
    assert "uri=true" in url


def test_sqlite_windows_path_is_usable_in_a_uri() -> None:
    url = build_url(
        _connection(dialect=Dialect.SQLITE, database=r"C:\data\demo.db"),
        Credentials(),
    )
    assert "\\" not in url
    assert "C:/data/demo.db" in url


def test_credentials_survive_encryption_roundtrip() -> None:
    connection = _connection(
        encrypted_credentials=encrypt_credentials(Credentials("analyst", "hunter2"))
    )
    recovered = decrypt_credentials(connection)

    assert recovered.username == "analyst"
    assert recovered.password == "hunter2"


def test_stored_credentials_are_not_readable_as_plaintext() -> None:
    blob = encrypt_credentials(Credentials("analyst", "hunter2"))
    assert "hunter2" not in blob
    assert "analyst" not in blob


def test_check_connection_succeeds_against_the_demo_database(demo_db_path: str) -> None:
    connection = _connection(dialect=Dialect.SQLITE, database=demo_db_path)
    result = check_connection(connection, Credentials())

    assert result.ok
    assert result.server_version
    assert result.error is None


def test_check_connection_reports_failure_without_raising() -> None:
    connection = _connection(
        dialect=Dialect.POSTGRES, host="127.0.0.1", port=1, database="nope"
    )
    result = check_connection(connection, Credentials("u", "p"))

    assert not result.ok
    assert result.error


def test_failed_connection_error_does_not_leak_the_password() -> None:
    connection = _connection(
        dialect=Dialect.POSTGRES, host="127.0.0.1", port=1, database="nope"
    )
    result = check_connection(connection, Credentials("u", "supersecret123"))

    assert not result.ok
    assert "supersecret123" not in (result.error or "")
