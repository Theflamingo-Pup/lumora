# =============================================================
# Lumora photos helpers - R2 (Cloudflare) integration
# =============================================================
# R2 is S3-API compatible. We use boto3 (the AWS SDK) with a
# custom endpoint URL.
#
# Two main jobs in this module:
#   1. Generate "presigned URLs" for uploads
#      - Browser POSTs directly to R2, bypassing our cluster
#      - URL is valid for 5 min, restricted to specific content-type
#      - This is the standard "S3 direct upload" pattern
#
#   2. Delete objects (for when a user replaces or removes a photo)
# =============================================================

import os
import uuid
from typing import Optional

import boto3
from botocore.client import Config


# -------------------------------------------------------------
# Configuration - all from environment (loaded at import time)
# -------------------------------------------------------------
R2_ACCESS_KEY_ID     = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_ENDPOINT          = os.environ["R2_ENDPOINT"]
R2_BUCKET            = os.environ["R2_BUCKET"]

# The public base URL that serves objects after upload. Set via
# env so we can swap between dev/prod buckets without code changes.
# Defaults to "" which signals "use the endpoint" - but in
# practice you want the public r2.dev URL or your custom domain.
R2_PUBLIC_BASE = os.environ.get("R2_PUBLIC_BASE", "")


# -------------------------------------------------------------
# Constants - what we allow
# -------------------------------------------------------------
MAX_UPLOAD_BYTES = 8 * 1024 * 1024            # 8 MB max per photo
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}
SIGNED_URL_TTL_SECONDS = 300                  # 5 minutes


# -------------------------------------------------------------
# The R2 client (one per process - boto3 is thread-safe)
# -------------------------------------------------------------
def _make_client():
    """Build a boto3 client configured for R2.

    Two important non-defaults:
      - endpoint_url: points at R2 instead of AWS
      - signature_version='s3v4': R2 requires this
      - region_name='auto': R2 doesn't use regions
    """
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


_client = _make_client()


# -------------------------------------------------------------
# Object key generation
# -------------------------------------------------------------
def _make_key(user_id: int, content_type: str) -> str:
    """Build a deterministic-prefix, random-suffix object key.

    Format: users/<user_id>/profile-<uuid>.<ext>

    Why this shape:
      * users/<user_id>/  groups all of one user's files (easy
        to list/clean up later)
      * <uuid> makes the key unguessable (defense against
        someone enumerating other users' photos by URL)
      * .<ext> is cosmetic - browsers don't need it, but it
        helps when debugging

    We pick the extension based on the validated content_type,
    not user input.
    """
    ext = {
        "image/jpeg": "jpg",
        "image/png":  "png",
        "image/webp": "webp",
    }[content_type]
    return f"users/{user_id}/profile-{uuid.uuid4().hex}.{ext}"


# -------------------------------------------------------------
# Public functions
# -------------------------------------------------------------

def create_upload_url(user_id: int, content_type: str) -> dict:
    """Generate a presigned PUT URL the browser can upload to.

    Returns:
        {
          "upload_url": "<URL with auth baked in>",
          "key": "<object key in the bucket>",
          "expires_in": 300,
          "max_bytes": 8388608,
        }

    The URL is valid for SIGNED_URL_TTL_SECONDS. After that
    R2 refuses to accept the upload.
    """
    if content_type not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported content type: {content_type}")

    key = _make_key(user_id, content_type)

    # generate_presigned_url is boto3's S3 magic - it signs a
    # URL with our credentials so R2 can verify the request
    # came from us, without revealing the credentials themselves.
    upload_url = _client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": R2_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )

    return {
        "upload_url": upload_url,
        "key": key,
        "expires_in": SIGNED_URL_TTL_SECONDS,
        "max_bytes": MAX_UPLOAD_BYTES,
    }


def object_exists(key: str) -> bool:
    """Check if an object actually exists in the bucket.
    
    Used after the browser claims it uploaded - we verify before
    saving the URL to the DB. Prevents bogus 'I uploaded a photo'
    requests from setting a non-existent photo_url.
    """
    try:
        _client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except Exception:
        return False


def delete_object(key: str) -> None:
    """Delete an object from the bucket.
    
    Used when a user replaces their photo (old one removed) or
    deletes their photo entirely. We swallow errors - if the
    object is already gone, that's fine.
    """
    try:
        _client.delete_object(Bucket=R2_BUCKET, Key=key)
    except Exception as e:
        print(f"[photos] delete_object({key}) failed: {e}")


def public_url_for(key: str) -> str:
    """Build the public URL where a stored object can be served."""
    if not R2_PUBLIC_BASE:
        # Fallback - works for dev but not great. In prod, set
        # R2_PUBLIC_BASE to your pub-XXX.r2.dev URL.
        return f"{R2_ENDPOINT}/{R2_BUCKET}/{key}"
    return f"{R2_PUBLIC_BASE.rstrip('/')}/{key}"


def key_from_url(url: str) -> Optional[str]:
    """Inverse of public_url_for - extract the key from a stored URL.

    Used when deleting a photo: we have the photo_url in the DB
    and need the key to call delete_object().

    Returns None if the URL doesn't look like one of ours.
    """
    if not url:
        return None
    if R2_PUBLIC_BASE and url.startswith(R2_PUBLIC_BASE):
        return url[len(R2_PUBLIC_BASE):].lstrip("/")
    # Fallback for the no-PUBLIC_BASE case
    prefix = f"{R2_ENDPOINT}/{R2_BUCKET}/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None
