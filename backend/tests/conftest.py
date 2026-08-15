"""Test fixtures.

Every test runs against an isolated file-backed SQLite database so tests
never touch a developer's working data and never depend on Docker.
"""

import contextlib
import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture(scope="session")
def _sqlite_path() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="nlq_test_")
    os.close(fd)
    yield path
    # Windows sometimes still holds the handle; a leaked temp file is not
    # worth failing the run over.
    with contextlib.suppress(OSError):
        os.unlink(path)


@pytest.fixture(scope="session")
def engine(_sqlite_path: str):
    import app.models  # noqa: F401 - registers models
    from app.core.database import Base

    eng = create_engine(
        f"sqlite+pysqlite:///{_sqlite_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    """A session wrapped in a transaction that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(engine) -> Generator[TestClient, None, None]:
    from app.core.database import get_db
    from app.main import app

    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict:
    """Register a throwaway user and return its bearer header."""
    import uuid

    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "full_name": "Test"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
