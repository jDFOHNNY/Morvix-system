import sys
import types

from backend.app import config
from backend.app.database import connection
from backend.app.notifications import NotificationDeliveryError

from backend.tests.conftest import login, register


def test_registration_hashes_password_and_login_sets_http_only_cookie(client):
    register(client)
    with connection() as db:
        row = db.execute("SELECT password_hash FROM users WHERE email=?", ("parent@example.com",)).fetchone()
    assert row["password_hash"] != "Correct horse battery"
    assert row["password_hash"].startswith("pbkdf2_sha256$")

    rejected = client.post("/api/v1/auth/login", json={"email": "parent@example.com", "password": "bad"})
    assert rejected.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401

    login(client)
    assert client.cookies.get("morvix_session")
    assert client.get("/api/v1/auth/me").json()["email"] == "parent@example.com"
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_registration_validates_email_and_duplicate(client):
    assert client.post("/api/v1/auth/register", json={"name": "X", "email": "nope", "password": "1234567890"}).status_code == 422
    register(client)
    assert client.post("/api/v1/auth/register", json={"name": "Again", "email": "parent@example.com", "password": "Correct horse battery"}).status_code == 409


def test_google_sign_in_is_explicitly_disabled_without_client_id(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    assert client.get("/api/v1/auth/google/config").json()["enabled"] is False
    response = client.post(
        "/api/v1/auth/google",
        json={"credential": "placeholder-google-id-token-value", "csrf_token": "x" * 40},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_google_sign_in_rejects_csrf_mismatch_before_token_validation(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "morvix-test-client-id")
    monkeypatch.setattr("backend.app.api.auth.email_notifications_configured", lambda: True)
    client.cookies.set("morvix_google_csrf", "a" * 40, path="/api/v1/auth/google")
    response = client.post(
        "/api/v1/auth/google",
        json={"credential": "placeholder-google-id-token-value", "csrf_token": "b" * 40},
    )
    assert response.status_code == 400
    assert "could not be verified" in response.json()["detail"]


def install_google_token_verifier(monkeypatch, claims):
    google = types.ModuleType("google")
    google.__path__ = []
    auth = types.ModuleType("google.auth")
    auth.__path__ = []
    transport = types.ModuleType("google.auth.transport")
    transport.__path__ = []
    requests = types.ModuleType("google.auth.transport.requests")
    requests.Request = lambda: object()
    oauth2 = types.ModuleType("google.oauth2")
    oauth2.__path__ = []
    id_token = types.ModuleType("google.oauth2.id_token")
    id_token.verify_oauth2_token = lambda token, request, audience: claims
    google.auth = auth
    google.oauth2 = oauth2
    auth.transport = transport
    transport.requests = requests
    oauth2.id_token = id_token
    for name, module in {
        "google": google,
        "google.auth": auth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": requests,
        "google.oauth2": oauth2,
        "google.oauth2.id_token": id_token,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def google_config(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "morvix-test-client-id")
    monkeypatch.setattr("backend.app.api.auth.email_notifications_configured", lambda: True)
    result = client.get("/api/v1/auth/google/config")
    assert result.status_code == 200
    return result.json()


def test_google_parent_creation_sends_notice_to_verified_account(client, monkeypatch):
    csrf = google_config(client, monkeypatch)["csrf_token"]
    install_google_token_verifier(monkeypatch, {
        "sub": "google-sub-123",
        "email": "parent@gmail.com",
        "email_verified": True,
        "name": "Test Parent",
    })
    sent_notifications = []
    monkeypatch.setattr("backend.app.api.auth.send_parent_acceptance_notice", lambda email, name: sent_notifications.append((email, name)))

    response = client.post("/api/v1/auth/google", json={"credential": "verified-test-id-token", "csrf_token": csrf})

    assert response.status_code == 200, response.text
    assert response.json()["user"]["email"] == "parent@gmail.com"
    assert client.get("/api/v1/auth/me").json()["email"] == "parent@gmail.com"
    assert sent_notifications == [("parent@gmail.com", "Test Parent")]
    with connection() as db:
        identity = db.execute("SELECT provider,subject FROM oauth_identities").fetchone()
        account_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert dict(identity) == {"provider": "google", "subject": "google-sub-123"}
    assert account_count == 1


def test_google_parent_creation_rolls_back_when_notice_fails(client, monkeypatch):
    csrf = google_config(client, monkeypatch)["csrf_token"]
    install_google_token_verifier(monkeypatch, {
        "sub": "google-sub-failure",
        "email": "parent@gmail.com",
        "email_verified": True,
        "name": "Test Parent",
    })

    def fail_notice(email, name):
        raise NotificationDeliveryError("test SMTP failure")

    monkeypatch.setattr("backend.app.api.auth.send_parent_acceptance_notice", fail_notice)
    response = client.post("/api/v1/auth/google", json={"credential": "verified-test-id-token", "csrf_token": csrf})

    assert response.status_code == 503
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM oauth_identities").fetchone()[0] == 0
