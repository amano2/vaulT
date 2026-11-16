"""Token authentication, hashing, constant-time verification, and scoping."""

import secrets
import hashlib
import hmac
import sqlite3
import datetime
from typing import Any


def generate_secure_token() -> tuple[str, str]:
    """Generates a high-entropy random bearer token (32 bytes hex) and its SHA-256 hash.

    The raw token is returned once to the caller; only the hash is persisted.
    """
    raw_token = secrets.token_hex(32)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash


def hash_token(token: str) -> str:
    """Computes SHA-256 hash of a token string."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def verify_token(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    """Validates bearer token in constant time.

    Checks:
    - Token exists
    - Not revoked
    - Not expired
    Returns token record or None if invalid.
    """
    candidate_hash = hash_token(token)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, token_hash, scope, folder_prefix, rate_limit_per_min, expires_at, revoked_at
        FROM access_tokens
        WHERE revoked_at IS NULL
        """
    )
    tokens = cur.fetchall()

    matched_token: sqlite3.Row | None = None
    for row in tokens:
        # Constant time comparison to prevent timing attacks
        if hmac.compare_digest(candidate_hash, row["token_hash"]):
            matched_token = row
            break

    if not matched_token:
        return None

    # Check expiration
    if matched_token["expires_at"]:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if now_iso > matched_token["expires_at"]:
            return None

    # Update last_used_at
    cur.execute(
        "UPDATE access_tokens SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (matched_token["id"],),
    )
    conn.commit()

    return dict(matched_token)
