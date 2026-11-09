"""Password, dashboard-session and extension-device credential helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from backend.app import config
from backend.app.database import connection
from backend.app.time_utils import utc_now

PASSWORD_ITERATIONS = 310_000


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(rounds))
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=config.SESSION_HOURS)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with connection() as db:
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES (?,?,?,?)",
            (token_digest(token), user_id, utc_now(), expires),
        )
    return token, expires


def get_parent(request: Request) -> dict:
    token = request.cookies.get("morvix_session")
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to access this MORVIX data.")
    with connection() as db:
        row = db.execute(
            "SELECT u.id,u.name,u.email,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (token_digest(token), utc_now()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again.")
    return dict(row)


def get_device(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(status_code=401, detail="A paired extension credential is required.")
    with connection() as db:
        row = db.execute(
            "SELECT id,user_id,label,last_seen_at FROM devices WHERE token_hash=? AND revoked_at IS NULL",
            (token_digest(credential),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="This extension is not paired or has been revoked.")
    return dict(row)

