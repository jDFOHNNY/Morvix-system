from backend.tests.conftest import login, register


def test_rule_crud_persists_and_updates_policy_version(client):
    register(client)
    login(client)
    before = client.get("/api/v1/settings").json()["version"]
    created = client.post("/api/v1/rules", json={"kind": "website", "target": "WWW.Example.com", "action": "block"})
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["target"] == "www.example.com"
    assert client.get("/api/v1/settings").json()["version"] == before + 1

    updated = client.put(f"/api/v1/rules/{rule['id']}", json={"kind": "website", "target": "example.com", "action": "warn", "enabled": False})
    assert updated.status_code == 200
    assert updated.json()["action"] == "warn"
    assert updated.json()["enabled"] is False

    listed = client.get("/api/v1/rules").json()["items"]
    assert len(listed) == 1 and listed[0]["target"] == "example.com"
    assert client.delete(f"/api/v1/rules/{rule['id']}").status_code == 204
    assert client.get("/api/v1/rules").json()["items"] == []


def test_invalid_rule_and_settings_are_rejected(client):
    register(client)
    login(client)
    assert client.post("/api/v1/rules", json={"kind": "website", "target": "https://bad.site/path", "action": "block"}).status_code == 422
    assert client.post("/api/v1/rules", json={"kind": "category", "target": "made_up", "action": "block"}).status_code == 422
    settings = client.get("/api/v1/settings").json()
    settings["thresholds"]["violence"] = {"review": 0.95, "block": 0.5}
    assert client.put("/api/v1/settings", json=settings).status_code == 422


def test_settings_update_persists_and_increments_version(client):
    register(client)
    login(client)
    settings = client.get("/api/v1/settings").json()
    settings["protection_enabled"] = False
    settings["modalities"]["image"] = False
    changed = client.put("/api/v1/settings", json=settings)
    assert changed.status_code == 200, changed.text
    assert changed.json()["protection_enabled"] is False
    assert changed.json()["modalities"]["image"] is False
    assert changed.json()["version"] == settings["version"] + 1



