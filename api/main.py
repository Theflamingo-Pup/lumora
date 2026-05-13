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
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg                              # the postgres driver
from psycopg.rows import dict_row           # makes rows behave like dicts
from psycopg import errors as pg_errors

# Auth helpers (password hashing + JWT) live in their own module.
# Importing this also enforces JWT_SECRET being set in the env,
# because auth.py reads it at import time.
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    current_user_id,
)

# Photo storage (R2) helpers. Importing this enforces all R2_*
# env vars being set, same enforcement pattern as auth.
from photos import (
    ALLOWED_MIMES,
    create_upload_url,
    object_exists,
    delete_object,
    public_url_for,
    key_from_url,
)

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


# =============================================================
# WAITLIST - "get early access" emails from the Coming Soon page
# =============================================================
# Why a separate table from profiles:
#   waitlist emails are NOT user accounts - they have no
#   password, no profile, no signup verification. They're just
#   leads. When Lumora opens beta, we'll email them to invite
#   them to sign up properly.
# =============================================================

class WaitlistSignup(BaseModel):
    """The body the client POSTs to /waitlist."""
    email: str


@app.post("/waitlist")
def add_to_waitlist(payload: WaitlistSignup):
    """Add an email to the waitlist.
    
    Returns the same success message whether the email is new
    OR was already on the list. This is intentional - it
    prevents anyone from probing 'is this email registered?'
    """
    # Normalize the email - trim + lowercase
    email = payload.email.strip().lower()

    # Cheap format check - just verify @ and . are present.
    # Real validation requires sending a verification email,
    # which is Phase 1b territory.
    if "@" not in email or "." not in email or len(email) < 5 or len(email) > 255:
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO waitlist (email) VALUES (%s)",
                (email,),
            )
            conn.commit()
    except pg_errors.UniqueViolation:
        # Email already on the list. Return the same success
        # message as a new signup - we don't want to leak which
        # emails are registered. This is a small privacy win.
        return {"status": "ok", "message": "You're on the list"}
    except Exception as e:
        # Something else went wrong - log it and return generic 500
        print(f"[waitlist] DB error: {e}")
        raise HTTPException(status_code=500, detail="Could not save right now, try again later")

    return {"status": "ok", "message": "You're on the list"}


# =============================================================
# AUTH - real user accounts (Phase 1)
# =============================================================
# Three endpoints:
#   POST /auth/signup   - create an account
#   POST /auth/login    - exchange email+password for a JWT
#   GET  /me            - return current user's info (JWT protected)
# =============================================================

class SignupRequest(BaseModel):
    """Body for POST /auth/signup."""
    email:    str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""
    email:    str
    password: str


class AuthResponse(BaseModel):
    """Returned by both signup and login on success."""
    access_token: str
    token_type:   str = "bearer"
    user_id:      int


def _normalize_email(email: str) -> str:
    """Trim + lowercase. Same convention as the waitlist."""
    return email.strip().lower()


def _is_valid_email_shape(email: str) -> bool:
    """Cheap shape check. We don't do full RFC 5322 validation -
    real validation only happens via an email-verification flow,
    which is Phase 1b territory."""
    return "@" in email and "." in email and 5 <= len(email) <= 255


@app.post("/auth/signup", response_model=AuthResponse)
def signup(payload: SignupRequest):
    """Create a new user account.
    
    On success returns a JWT the client should send as
    Authorization: Bearer <token> on subsequent requests.
    """
    email = _normalize_email(payload.email)

    if not _is_valid_email_shape(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    # Hash the password BEFORE the DB call. If hashing fails for
    # any reason we don't even attempt a write.
    password_hash = hash_password(payload.password)

    try:
        with get_connection() as conn:
            row = conn.execute(
                """INSERT INTO users (email, password_hash)
                   VALUES (%s, %s)
                   RETURNING id""",
                (email, password_hash),
            ).fetchone()
            conn.commit()
    except pg_errors.UniqueViolation:
        # Email already taken. We DO return a clear error here
        # (unlike the waitlist) - signup is intentionally a
        # different UX from "join the list."
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    except Exception as e:
        print(f"[signup] DB error: {e}")
        raise HTTPException(status_code=500, detail="Could not create account, try again later")

    user_id = row["id"]
    token   = create_access_token(user_id)
    return AuthResponse(access_token=token, user_id=user_id)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    """Exchange email+password for a JWT.
    
    SECURITY: always return the same generic error message for
    'no such user' and 'wrong password'. Distinguishing them
    leaks which emails are registered.
    """
    email = _normalize_email(payload.email)

    GENERIC_ERROR = HTTPException(status_code=401, detail="Invalid email or password")

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE email = %s",
                (email,),
            ).fetchone()
    except Exception as e:
        print(f"[login] DB error: {e}")
        raise HTTPException(status_code=500, detail="Could not log in right now, try again later")

    if row is None:
        # User not found - still do a hash to keep timing consistent
        # so attackers can't tell "no such email" vs "wrong password"
        # by timing the response. Defense in depth.
        verify_password(payload.password, "$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "A" * 43)
        raise GENERIC_ERROR

    if not verify_password(payload.password, row["password_hash"]):
        raise GENERIC_ERROR

    user_id = row["id"]
    token   = create_access_token(user_id)
    return AuthResponse(access_token=token, user_id=user_id)


@app.get("/me")
def get_me(user_id: int = Depends(current_user_id)):
    """Return the current authenticated user's info.
    
    Requires Authorization: Bearer <token> header.
    FastAPI auto-rejects with 401 if missing/invalid via
    the current_user_id dependency.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, email, email_verified, created_at
               FROM users
               WHERE id = %s""",
            (user_id,),
        ).fetchone()

    if row is None:
        # Token is valid but user has been deleted. Treat as auth failure.
        raise HTTPException(status_code=401, detail="User no longer exists")

    return row


# =============================================================
# PROFILES - real user-owned profiles (Phase 2a)
# =============================================================
# 3 endpoints, all auth-protected:
#   GET    /me/profile   - view your profile (or 404 if none)
#   PUT    /me/profile   - create or update your profile
#   DELETE /me/profile   - delete your profile
#
# Note: there's NO endpoint here for viewing OTHER users'
# profiles. That's intentional - it's Phase 3 (discovery feed).
# =============================================================

class ProfileWrite(BaseModel):
    """Body for PUT /me/profile (create or update)."""
    display_name:        str           = Field(..., min_length=1, max_length=50)
    age:                 int           = Field(..., ge=18, le=120)
    bio:                 Optional[str] = Field(None, max_length=2000)
    location_city:       Optional[str] = Field(None, max_length=100)
    looking_for_min_age: int           = Field(18, ge=18, le=120)
    looking_for_max_age: int           = Field(99, ge=18, le=120)


@app.get("/me/profile")
def get_my_profile(user_id: int = Depends(current_user_id)):
    """Return the authenticated user's profile, or 404 if none yet."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT user_id, display_name, age, bio, location_city,
                      looking_for_min_age, looking_for_max_age,
                      photo_url,
                      created_at, updated_at
               FROM profiles
               WHERE user_id = %s""",
            (user_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="No profile yet. Use PUT /me/profile to create one.")
    return row


@app.put("/me/profile")
def upsert_my_profile(
    payload: ProfileWrite,
    user_id: int = Depends(current_user_id),
):
    """Create OR update the authenticated user's profile.
    
    UPSERT pattern: if no profile exists for this user, INSERT.
    If one exists, UPDATE in place. The user_id PRIMARY KEY makes
    this safe - we can never accidentally create two profiles for
    the same user.
    """
    # Cross-field check: min age can't exceed max age
    if payload.looking_for_min_age > payload.looking_for_max_age:
        raise HTTPException(
            status_code=400,
            detail="looking_for_min_age must be <= looking_for_max_age",
        )

    try:
        with get_connection() as conn:
            # ON CONFLICT (user_id) DO UPDATE is postgres "upsert"
            row = conn.execute(
                """INSERT INTO profiles (
                       user_id, display_name, age, bio, location_city,
                       looking_for_min_age, looking_for_max_age
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET
                       display_name        = EXCLUDED.display_name,
                       age                 = EXCLUDED.age,
                       bio                 = EXCLUDED.bio,
                       location_city       = EXCLUDED.location_city,
                       looking_for_min_age = EXCLUDED.looking_for_min_age,
                       looking_for_max_age = EXCLUDED.looking_for_max_age,
                       updated_at          = NOW()
                   RETURNING user_id, display_name, age, bio, location_city,
                             looking_for_min_age, looking_for_max_age,
                             photo_url,
                             created_at, updated_at""",
                (
                    user_id, payload.display_name, payload.age, payload.bio,
                    payload.location_city, payload.looking_for_min_age,
                    payload.looking_for_max_age,
                ),
            ).fetchone()
            conn.commit()
    except pg_errors.CheckViolation as e:
        # DB-level constraint rejected the row (e.g. age check).
        # This is defense in depth - Pydantic should have caught
        # it first, but if a bug let it through, the DB stops it.
        raise HTTPException(status_code=400, detail=f"Profile rejected: {e.diag.message_primary}")
    except Exception as e:
        print(f"[upsert_profile] DB error: {e}")
        raise HTTPException(status_code=500, detail="Could not save profile")

    return row


@app.delete("/me/profile")
def delete_my_profile(user_id: int = Depends(current_user_id)):
    """Delete the authenticated user's profile.
    
    Returns 204 if deleted, 404 if there was no profile to delete.
    """
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM profiles WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No profile to delete")

    return {"status": "deleted"}


# =============================================================
# PROFILE PHOTOS - Phase 2b
# =============================================================
# 3 endpoints, all auth-protected:
#   POST   /me/photo/upload-url   request a signed URL to upload to R2
#   POST   /me/photo/confirm      after upload, save the URL to profile
#   DELETE /me/photo              remove photo from profile + R2
#
# The upload itself happens BROWSER -> R2 directly. We never see
# the photo bytes. That's the whole point of presigned URLs.
# =============================================================

class UploadUrlRequest(BaseModel):
    """Body for POST /me/photo/upload-url."""
    content_type: str = Field(..., max_length=64)


class ConfirmRequest(BaseModel):
    """Body for POST /me/photo/confirm. Contains the object key
    that the browser uploaded to (from the previous upload-url
    response)."""
    key: str = Field(..., min_length=10, max_length=500)


@app.post("/me/photo/upload-url")
def get_upload_url(
    payload: UploadUrlRequest,
    user_id: int = Depends(current_user_id),
):
    """Get a presigned URL the browser can PUT the photo to.
    
    The browser then does:
        PUT <upload_url>
        Content-Type: <whatever they asked for>
        <binary photo bytes>
    
    R2 verifies the signature on the URL and stores the object.
    """
    if payload.content_type not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"Content-Type must be one of: {sorted(ALLOWED_MIMES)}",
        )

    try:
        result = create_upload_url(user_id=user_id, content_type=payload.content_type)
    except Exception as e:
        print(f"[upload-url] failed: {e}")
        raise HTTPException(status_code=500, detail="Could not generate upload URL")

    return result


@app.post("/me/photo/confirm")
def confirm_photo(
    payload: ConfirmRequest,
    user_id: int = Depends(current_user_id),
):
    """Browser tells us 'I finished uploading, here's the key'.
    
    We verify the object actually exists in R2, then save the
    public URL into the user's profile. If they had a previous
    photo, we delete the old one from R2 to avoid orphans.
    
    SECURITY: we verify the key starts with users/<user_id>/ so
    a user can't claim someone else's uploaded object.
    """
    expected_prefix = f"users/{user_id}/"
    if not payload.key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="Invalid object key for this user")

    # Verify the upload actually happened
    if not object_exists(payload.key):
        raise HTTPException(
            status_code=404,
            detail="Object not found in storage. Did the upload finish?",
        )

    photo_url = public_url_for(payload.key)

    # Get the OLD photo URL (if any) so we can delete it from R2
    # after the DB update succeeds.
    try:
        with get_connection() as conn:
            old_row = conn.execute(
                "SELECT photo_url FROM profiles WHERE user_id = %s",
                (user_id,),
            ).fetchone()

            if old_row is None:
                # No profile yet. The user has to create their profile
                # (PUT /me/profile) before they can attach a photo.
                raise HTTPException(
                    status_code=400,
                    detail="Create your profile first (PUT /me/profile) before adding a photo",
                )

            old_url = old_row.get("photo_url")

            # Update with the new photo URL
            conn.execute(
                "UPDATE profiles SET photo_url = %s, updated_at = NOW() WHERE user_id = %s",
                (photo_url, user_id),
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        print(f"[confirm] DB error: {e}")
        raise HTTPException(status_code=500, detail="Could not save photo URL")

    # Best-effort: delete the old photo from R2 (don't fail the
    # request if this errors - the DB is already updated).
    if old_url:
        old_key = key_from_url(old_url)
        if old_key:
            delete_object(old_key)

    return {"photo_url": photo_url}


@app.delete("/me/photo")
def delete_photo(user_id: int = Depends(current_user_id)):
    """Remove the user's photo entirely.
    
    Clears photo_url in the profile, and deletes the object
    from R2. Returns 404 if there was no photo to delete.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT photo_url FROM profiles WHERE user_id = %s",
            (user_id,),
        ).fetchone()

        if row is None or row.get("photo_url") is None:
            raise HTTPException(status_code=404, detail="No photo to delete")

        old_url = row["photo_url"]

        conn.execute(
            "UPDATE profiles SET photo_url = NULL, updated_at = NOW() WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()

    # Delete from R2 (best effort)
    old_key = key_from_url(old_url)
    if old_key:
        delete_object(old_key)

    return {"status": "deleted"}
