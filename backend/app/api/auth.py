"""Parent account registration and opaque-cookie sessions."""

from __future__ import annotations

import uuid
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.app import config
from backend.app.database import connection
from backend.app.notifications import NotificationDeliveryError, email_notifications_configured, send_parent_acceptance_notice
from backend.app.policies import ensure_policy
from backend.app.schemas import GoogleCredentialInput, LoginInput, RegisterInput
from backend.app.security import create_session, get_parent, hash_password, token_digest, verify_password
from backend.app.time_utils import utc_now

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _set_session_cookie(response: Response, user_id: str) -> str:
    token, expires = create_session(user_id)
    response.set_cookie(
        "morvix_session",
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=config.SESSION_HOURS * 3600,
        path="/",
    )
    return expires


@router.get("/google/config")
def google_config(response: Response):
    if not config.GOOGLE_CLIENT_ID:
        return {"enabled": False, "reason": "Google sign-in is not configured for this MORVIX installation."}
    if not email_notifications_configured():
        return {"enabled": False, "reason": "Google sign-in needs email delivery configured so new parent accounts receive a confirmation."}
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        "morvix_google_csrf",
        csrf_token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        max_age=600,
        path="/api/v1/auth/google",
    )
    return {"enabled": True, "client_id": config.GOOGLE_CLIENT_ID, "csrf_token": csrf_token}


@router.post("/register", status_code=201)
def register(payload: RegisterInput):
    user_id = str(uuid.uuid4())
    with connection() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email=?", (payload.email,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, payload.name, payload.email, hash_password(payload.password), utc_now()),
        )
        ensure_policy(user_id, db)
    return {"id": user_id, "name": payload.name, "email": payload.email, "message": "Account created. Sign in to continue."}


@router.post("/login")
def login(payload: LoginInput, response: Response):
    with connection() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (payload.email.strip().lower(),)).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    expires = _set_session_cookie(response, user["id"])
    return {"user": {"id": user["id"], "name": user["name"], "email": user["email"]}, "expires_at": expires}


@router.post("/google")
def google_sign_in(payload: GoogleCredentialInput, request: Request, response: Response):
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured for this MORVIX installation.")
    if not email_notifications_configured():
        raise HTTPException(status_code=503, detail="Email delivery must be configured before MORVIX can accept a new Google parent account.")
    csrf_cookie = request.cookies.get("morvix_google_csrf", "")
    if not csrf_cookie or not secrets.compare_digest(csrf_cookie, payload.csrf_token):
        raise HTTPException(status_code=400, detail="Google sign-in could not be verified. Refresh the page and try again.")
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        identity = id_token.verify_oauth2_token(
            payload.credential,
            GoogleRequest(),
            config.GOOGLE_CLIENT_ID,
        )
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Google sign-in dependencies are not installed.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Google could not verify this sign-in. Please try again.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Google sign-in could not be reached. Please try again later.") from exc

    email = str(identity.get("email", "")).strip().lower()
    subject = str(identity.get("sub", "")).strip()
    email_verified = identity.get("email_verified") is True
    hosted_domain = str(identity.get("hd", "")).strip()
    google_authoritative_email = email.endswith("@gmail.com") or bool(hosted_domain)
    if not subject or "@" not in email or not email_verified or not google_authoritative_email:
        raise HTTPException(
            status_code=403,
            detail="Use a verified Gmail or Google Workspace account to create or access a MORVIX account.",
        )

    user_id = None
    try:
        with connection() as db:
            row = db.execute(
                "SELECT u.id,u.name,u.email FROM oauth_identities i JOIN users u ON u.id=i.user_id "
                "WHERE i.provider='google' AND i.subject=?",
                (subject,),
            ).fetchone()
            if row is None:
                row = db.execute("SELECT id,name,email FROM users WHERE email=?", (email,)).fetchone()
                if row is None:
                    user_id = str(uuid.uuid4())
                    name = str(identity.get("name") or identity.get("given_name") or email.split("@", 1)[0]).strip()[:100]
                    db.execute(
                        "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
                        (user_id, name or "MORVIX Parent", email, hash_password(secrets.token_urlsafe(48)), utc_now()),
                    )
                    ensure_policy(user_id, db)
                else:
                    user_id = row["id"]
                    name = row["name"]
                db.execute(
                    "INSERT INTO oauth_identities(provider,subject,user_id,created_at) VALUES('google',?,?,?)",
                    (subject, user_id, utc_now()),
                )
                send_parent_acceptance_notice(email, name or "MORVIX Parent")
            else:
                user_id = row["id"]
    except NotificationDeliveryError as exc:
        raise HTTPException(
            status_code=503,
            detail="MORVIX could not send the parent-account confirmation, so the new account was not accepted. Try again later.",
        ) from exc
    except Exception as exc:
        from sqlite3 import IntegrityError

        if isinstance(exc, IntegrityError):
            raise HTTPException(status_code=409, detail="This Google account is already linked to another MORVIX account.") from exc
        raise

    expires = _set_session_cookie(response, user_id)
    response.delete_cookie("morvix_google_csrf", path="/api/v1/auth/google", httponly=True, secure=config.COOKIE_SECURE, samesite="strict")
    with connection() as db:
        user = db.execute("SELECT id,name,email FROM users WHERE id=?", (user_id,)).fetchone()
    return {"user": dict(user), "expires_at": expires}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("morvix_session")
    if token:
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_digest(token),))
    response.delete_cookie("morvix_session", path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return {"message": "Signed out."}


@router.get("/me")
def me(parent: dict = Depends(get_parent)):
    return {"id": parent["id"], "name": parent["name"], "email": parent["email"]}

