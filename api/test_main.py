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
