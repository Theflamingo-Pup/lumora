# =============================================================
# Tests for the Lumora API
# =============================================================
# These are unit tests. CI runs them on every push.
# If any test fails, the pipeline fails and the commit is
# marked with a red X on GitHub.
#
# We use pytest (the most popular Python test framework)
# and FastAPI's TestClient which lets us call our API
# WITHOUT actually starting it on a real port.
#
# Important detail: these tests run WITHOUT a real database.
# We monkey-patch (replace) the database connection so the
# tests run fast and offline. This is normal for unit tests.
# =============================================================

import os
# Set JWT_SECRET BEFORE importing main, because auth.py reads it
# at import time. In CI, this env var won't be set, so we provide
# a deterministic test value here.
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production-32-bytes-min")

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# We import "app" from main.py - the FastAPI application object.
from main import app

# Skip the on_startup hook so tests don't try to reach a real DB.
# (Pattern: in real projects you'd structure this more cleanly,
# but this is fine for a learning project.)
app.router.on_startup = []

client = TestClient(app)


# -------------------------------------------------------------
# Helpers - create a fake DB connection that returns canned data
# -------------------------------------------------------------
def make_fake_conn(fetchall_result=None, fetchone_result=None):
    """Build a fake postgres connection object."""
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = fetchall_result or []
    fake_cursor.fetchone.return_value = fetchone_result

    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.execute.return_value = fake_cursor
    return fake_conn


# -------------------------------------------------------------
# Actual tests
# -------------------------------------------------------------

def test_health_endpoint_returns_ok_when_db_is_reachable():
    """The /health endpoint should report 'ok' if it can SELECT 1."""
    with patch("main.get_connection", return_value=make_fake_conn()):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "lumora-api"


def test_health_endpoint_returns_503_when_db_is_down():
    """When the DB is unreachable, /health should fail loudly (503)."""
    with patch("main.get_connection", side_effect=Exception("connection refused")):
        response = client.get("/health")
    assert response.status_code == 503


def test_list_profiles_returns_count_and_list():
    """GET /profiles should return both a count and a profiles list."""
    fake_profiles = [
        {"id": 1, "name": "Emma",   "age": 28, "bio": "Photographer", "distance_mi": 2},
        {"id": 2, "name": "Marcus", "age": 31, "bio": "Engineer",     "distance_mi": 5},
    ]
    with patch("main.get_connection", return_value=make_fake_conn(fetchall_result=fake_profiles)):
        response = client.get("/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert len(body["profiles"]) == 2
    assert body["profiles"][0]["name"] == "Emma"


def test_get_profile_by_id_returns_the_profile():
    """GET /profiles/1 should return that specific profile."""
    fake_profile = {"id": 1, "name": "Emma", "age": 28, "bio": "Photographer", "distance_mi": 2}
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_profile)):
        response = client.get("/profiles/1")

    assert response.status_code == 200
    assert response.json()["name"] == "Emma"


def test_get_profile_returns_404_when_not_found():
    """GET /profiles/9999 should return 404 if no such profile exists."""
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=None)):
        response = client.get("/profiles/9999")

    assert response.status_code == 404


# -------------------------------------------------------------
# Waitlist endpoint tests
# -------------------------------------------------------------

def test_waitlist_accepts_valid_email():
    """POST /waitlist with a valid email should succeed and persist."""
    with patch("main.get_connection", return_value=make_fake_conn()):
        response = client.post("/waitlist", json={"email": "test@example.com"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_waitlist_rejects_obviously_invalid_email():
    """POST /waitlist with garbage should return 400."""
    response = client.post("/waitlist", json={"email": "notanemail"})
    assert response.status_code == 400


def test_waitlist_rejects_empty_email():
    """Blank email is rejected."""
    response = client.post("/waitlist", json={"email": "   "})
    assert response.status_code == 400


def test_waitlist_returns_success_on_duplicate_email():
    """Re-submitting an existing email should still return ok
    (we don't want to leak which emails are already on the list)."""
    from psycopg import errors as pg_errors

    fake_conn = make_fake_conn()
    fake_conn.execute.side_effect = pg_errors.UniqueViolation("duplicate")

    with patch("main.get_connection", return_value=fake_conn):
        response = client.post("/waitlist", json={"email": "existing@example.com"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# -------------------------------------------------------------
# Auth endpoint tests - Phase 1
# -------------------------------------------------------------

def test_signup_with_valid_credentials_returns_token():
    """POST /auth/signup with a fresh email+password creates a
    user and returns a JWT."""
    fake_row = {"id": 42}
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_row)):
        response = client.post(
            "/auth/signup",
            json={"email": "new@example.com", "password": "longenoughpw"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user_id"] == 42
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 20   # JWTs are long


def test_signup_rejects_short_password():
    """Passwords under 8 chars should be rejected by Pydantic."""
    response = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422   # Pydantic validation


def test_signup_rejects_bad_email_shape():
    """Email with no @ should 400."""
    response = client.post(
        "/auth/signup",
        json={"email": "notanemail", "password": "longenoughpw"},
    )
    assert response.status_code == 400


def test_signup_returns_409_on_duplicate_email():
    """Trying to register an already-taken email should 409."""
    from psycopg import errors as pg_errors

    fake_conn = make_fake_conn()
    fake_conn.execute.side_effect = pg_errors.UniqueViolation("duplicate")

    with patch("main.get_connection", return_value=fake_conn):
        response = client.post(
            "/auth/signup",
            json={"email": "taken@example.com", "password": "longenoughpw"},
        )
    assert response.status_code == 409


def test_login_with_correct_password_returns_token():
    """Logging in with the right password returns a JWT."""
    # Pre-hash the password so verify_password actually succeeds
    from auth import hash_password
    correct_hash = hash_password("longenoughpw")
    fake_row = {"id": 7, "password_hash": correct_hash}

    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_row)):
        response = client.post(
            "/auth/login",
            json={"email": "real@example.com", "password": "longenoughpw"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == 7


def test_login_with_wrong_password_returns_401():
    """Wrong password should 401 with a generic error."""
    from auth import hash_password
    correct_hash = hash_password("the-real-password")
    fake_row = {"id": 7, "password_hash": correct_hash}

    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_row)):
        response = client.post(
            "/auth/login",
            json={"email": "real@example.com", "password": "wrong-guess-pw"},
        )

    assert response.status_code == 401
    # Should be a generic message that doesn't reveal which part failed
    assert "Invalid email or password" in response.json()["detail"]


def test_login_with_unknown_email_returns_401():
    """Email not in DB should ALSO 401 with the same generic msg
    (to avoid leaking which emails are registered)."""
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=None)):
        response = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "longenoughpw"},
        )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_me_without_token_returns_401():
    """GET /me without an Authorization header should 401."""
    response = client.get("/me")
    assert response.status_code == 401


def test_me_with_garbage_token_returns_401():
    """GET /me with a bogus token should 401."""
    response = client.get("/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert response.status_code == 401


def test_me_with_valid_token_returns_user_info():
    """GET /me with a real JWT returns the user's row."""
    from auth import create_access_token
    token = create_access_token(user_id=99)

    fake_user = {
        "id": 99,
        "email": "user@example.com",
        "email_verified": False,
        "created_at": "2026-05-12T19:00:00",
    }
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_user)):
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["id"] == 99
    assert response.json()["email"] == "user@example.com"


# -------------------------------------------------------------
# Profile endpoint tests - Phase 2a
# -------------------------------------------------------------
# These tests build on the auth tests: every /me/profile call
# needs a valid token. We use the helpers from auth.py to mint
# real tokens for our test users.

def _auth_headers(user_id: int = 1):
    """Create an Authorization header with a valid JWT for the given user."""
    from auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_get_profile_without_token_returns_401():
    """All /me/profile endpoints must require auth."""
    response = client.get("/me/profile")
    assert response.status_code == 401


def test_get_profile_returns_404_when_not_yet_created():
    """A user with no profile gets a 404, not a 500."""
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=None)):
        response = client.get("/me/profile", headers=_auth_headers(user_id=1))
    assert response.status_code == 404


def test_put_profile_creates_when_none_exists():
    """First PUT for a user creates their profile."""
    fake_returned = {
        "user_id": 1,
        "display_name": "Waris",
        "age": 35,
        "bio": "Engineer building Lumora",
        "location_city": "Windsor Mill",
        "looking_for_min_age": 22,
        "looking_for_max_age": 45,
        "created_at": "2026-05-13T06:00:00",
        "updated_at": "2026-05-13T06:00:00",
    }
    with patch("main.get_connection", return_value=make_fake_conn(fetchone_result=fake_returned)):
        response = client.put(
            "/me/profile",
            headers=_auth_headers(user_id=1),
            json={
                "display_name": "Waris",
                "age": 35,
                "bio": "Engineer building Lumora",
                "location_city": "Windsor Mill",
                "looking_for_min_age": 22,
                "looking_for_max_age": 45,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Waris"
    assert body["age"] == 35


def test_put_profile_rejects_underage():
    """Pydantic validation must reject age < 18 before reaching the DB."""
    response = client.put(
        "/me/profile",
        headers=_auth_headers(user_id=1),
        json={"display_name": "Tooyoung", "age": 17},
    )
    assert response.status_code == 422   # Pydantic validation


def test_put_profile_rejects_invalid_age_range_pref():
    """min_age > max_age is logical nonsense."""
    response = client.put(
        "/me/profile",
        headers=_auth_headers(user_id=1),
        json={
            "display_name": "Waris",
            "age": 35,
            "looking_for_min_age": 50,
            "looking_for_max_age": 30,
        },
    )
    assert response.status_code == 400


def test_put_profile_rejects_empty_display_name():
    """Display name must be at least 1 character."""
    response = client.put(
        "/me/profile",
        headers=_auth_headers(user_id=1),
        json={"display_name": "", "age": 25},
    )
    assert response.status_code == 422


def test_delete_profile_requires_auth():
    """DELETE /me/profile without token returns 401."""
    response = client.delete("/me/profile")
    assert response.status_code == 401


def test_delete_profile_returns_404_when_no_profile():
    """Deleting a non-existent profile returns 404, not 500."""
    fake_conn = make_fake_conn()
    fake_result = MagicMock()
    fake_result.rowcount = 0
    fake_conn.execute.return_value = fake_result

    with patch("main.get_connection", return_value=fake_conn):
        response = client.delete("/me/profile", headers=_auth_headers(user_id=1))
    assert response.status_code == 404
