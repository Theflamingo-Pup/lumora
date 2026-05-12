# =============================================================
# Lumora auth helpers
# =============================================================
# All the security-sensitive primitives in one place:
#   - password hashing/verification (argon2id)
#   - JWT token creation/decoding (HS256)
#   - the "get current user from token" dependency
#
# Why a separate module: keeps main.py focused on routes, makes
# this code easier to test in isolation, and makes auditing the
# security primitives a smaller surface area.
# =============================================================

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


# -------------------------------------------------------------
# Configuration - all from environment variables
# -------------------------------------------------------------
# JWT_SECRET must be set in the environment. We do NOT provide
# a default - if it's missing the API fails to start, which is
# the right behavior (no silent fallback to a weak secret).
JWT_SECRET    = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 30


# -------------------------------------------------------------
# Password hashing
# -------------------------------------------------------------
# argon2-cffi's PasswordHasher uses sane defaults that match
# OWASP's 2023 recommendations. We do not override them.
#   * memory_cost = 64 MB
#   * time_cost   = 3 iterations
#   * parallelism = 4 lanes
# That's slow enough to make brute-forcing expensive, fast
# enough that a real login feels instant.
_ph = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password with argon2id.
    
    Returns a self-contained string that includes the algorithm,
    parameters, salt, and hash. Safe to store directly in the
    password_hash column.
    """
    return _ph.hash(plain_password)


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Check whether a plain-text password matches the stored hash.
    
    Returns True if it matches, False otherwise. NEVER raises on
    a mismatch - that's an expected outcome of "wrong password",
    not an error.
    """
    try:
        _ph.verify(stored_hash, plain_password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


# -------------------------------------------------------------
# JWT tokens
# -------------------------------------------------------------

def create_access_token(user_id: int) -> str:
    """Create a signed JWT for the given user.
    
    The token contains:
      sub: the user's id (as a string)
      exp: when the token expires (UTC, seconds since epoch)
      iat: when the token was issued (UTC)
    
    Tokens are signed with JWT_SECRET using HS256.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    """Decode and verify a JWT, returning the user_id inside.
    
    Returns None if the token is invalid, expired, or tampered.
    NEVER trusts the payload without verifying the signature -
    that's the whole point of HS256.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        return int(user_id_str)
    except (JWTError, ValueError):
        return None


# -------------------------------------------------------------
# FastAPI dependency: extract current user from request
# -------------------------------------------------------------
# Usage in an endpoint:
#
#     @app.get("/me")
#     def get_me(user_id: int = Depends(current_user_id)):
#         ...
#
# FastAPI auto-injects the user_id by:
#   1. Reading the Authorization: Bearer <token> header
#   2. Verifying the token via decode_access_token()
#   3. If invalid/missing - returns 401 before our endpoint runs
# -------------------------------------------------------------
_bearer_scheme = HTTPBearer(auto_error=False)


def current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> int:
    """Resolve the authenticated user's id, or raise 401."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id
