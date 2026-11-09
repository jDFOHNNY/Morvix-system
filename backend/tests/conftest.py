import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "morvix-test.db")
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def register(client, email="parent@example.com", name="Test Parent"):
    response = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "Correct horse battery"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email="parent@example.com"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Correct horse battery"},
    )
    assert response.status_code == 200, response.text
    return response.json()
