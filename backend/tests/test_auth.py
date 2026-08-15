"""Authentication flow: register, login, token verification, role assignment."""

import uuid

from fastapi.testclient import TestClient


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def test_register_returns_token_and_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": _email(), "password": "correct-horse-battery", "full_name": "A"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["role"] in {"admin", "analyst"}
    assert "hashed_password" not in body["user"]


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    email = _email()
    payload = {"email": email, "password": "correct-horse-battery"}

    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    conflict = client.post("/api/v1/auth/register", json=payload)
    assert conflict.status_code == 409


def test_short_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": "short"}
    )
    assert response.status_code == 422


def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    email = _email()
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_fails_with_wrong_password(client: TestClient) -> None:
    email = _email()
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_unknown_email_gives_same_error_as_wrong_password(client: TestClient) -> None:
    # Identical responses prevent account enumeration.
    response = client.post(
        "/api/v1/auth/login",
        json={"email": _email(), "password": "correct-horse-battery"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_me_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


def test_me_returns_the_authenticated_user(
    client: TestClient, auth_headers: dict
) -> None:
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is True
