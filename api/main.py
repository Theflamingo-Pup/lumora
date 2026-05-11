# =============================================================
# Lumora Profiles API - v3 (now backed by a real database)
# =============================================================
# Same endpoints as before, but instead of a hardcoded list,
# we now read from PostgreSQL.
#
# Notice we never hardcode the database password in this file.
# We read it from environment variables (set by docker-compose).
# =============================================================

import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg                              # the postgres driver
from psycopg.rows import dict_row           # makes rows behave like dicts

app = FastAPI(title="Lumora Profiles API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# -------------------------------------------------------------
# Database connection config - all from environment variables.
# Compose sets these. In production, a secrets manager would.
# -------------------------------------------------------------
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "db"),
    "port":     os.environ.get("DB_PORT", "5432"),
    "dbname":   os.environ.get("DB_NAME", "lumora"),
    "user":     os.environ.get("DB_USER", "lumora_user"),
    "password": os.environ.get("DB_PASSWORD", "changeme"),
}


def get_connection():
    """Open a new postgres connection. Real apps use a connection
    pool - we're keeping it simple."""
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


def wait_for_db(max_attempts: int = 30):
    """When the whole stack starts, postgres might not be ready
    yet when the API tries to connect. We retry a few times.
    
    This is one of the most common gotchas in compose/k8s -
    starting != ready. The DB process is up but it hasn't
    finished initializing yet."""
    for attempt in range(1, max_attempts + 1):
        try:
            with get_connection() as conn:
                conn.execute("SELECT 1")
            print(f"[startup] DB ready after {attempt} attempts")
            return
        except Exception as e:
            print(f"[startup] DB not ready (attempt {attempt}/{max_attempts}): {e}")
            time.sleep(1)
    raise RuntimeError("Could not connect to database after retries")


@app.on_event("startup")
def on_startup():
    """Runs once when the API container boots."""
    wait_for_db()


# -------------------------------------------------------------
# Endpoints - same shape as before, now reading from postgres
# -------------------------------------------------------------

@app.get("/health")
def health_check():
    """Returns ok if we can talk to the DB. K8s will use this later."""
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "service": "lumora-api", "db": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unreachable: {e}")


@app.get("/profiles")
def list_profiles():
    """Return all profiles from the database."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, age, bio, distance_mi FROM profiles ORDER BY id"
        ).fetchall()
    return {"count": len(rows), "profiles": rows}


@app.get("/profiles/{profile_id}")
def get_profile(profile_id: int):
    """Return a single profile, or 404 if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, age, bio, distance_mi FROM profiles WHERE id = %s",
            (profile_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return row


@app.post("/profiles")
def create_profile(name: str, age: int, bio: str = "", distance_mi: int = 0):
    """NEW: create a new profile. Now we have CRUD, not just R.
    Try this in /docs - it will actually persist to the DB."""
    with get_connection() as conn:
        new_row = conn.execute(
            """INSERT INTO profiles (name, age, bio, distance_mi)
               VALUES (%s, %s, %s, %s)
               RETURNING id, name, age, bio, distance_mi""",
            (name, age, bio, distance_mi),
        ).fetchone()
        conn.commit()
    return new_row
