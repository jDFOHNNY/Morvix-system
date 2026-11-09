from backend.tests.conftest import login, register


def test_one_time_extension_pairing_policy_sync_and_revocation(client):
    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair?label=Kitchen%20Chromium")
    assert pair.status_code == 201, pair.text
    code = pair.json()["pairing_code"]

    activate = client.post("/api/v1/extension/activate", json={"pairing_code": code})
    assert activate.status_code == 200, activate.text
    device_token = activate.json()["device_token"]
    headers = {"Authorization": f"Bearer {device_token}"}
    assert activate.json()["policy"]["version"] >= 1
    assert activate.json()["cache_max_age_minutes"] == 1440
    assert client.post("/api/v1/extension/activate", json={"pairing_code": code}).status_code == 400
    assert client.get("/api/v1/extension/policy", headers=headers).status_code == 200
    assert client.post("/api/v1/extension/heartbeat", headers=headers).json()["connected"] is True

    device_id = activate.json()["device_id"]
    assert client.delete(f"/api/v1/devices/{device_id}").json()["revoked"] is True
    assert client.get("/api/v1/extension/policy", headers=headers).status_code == 401


def test_pairing_and_policy_sync_update_dashboard_device_connection(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair?label=Status%20check")
    device_id = pair.json()["device_id"]

    pending = client.get("/api/v1/devices").json()["items"][0]
    assert pending["id"] == device_id
    assert pending["paired_at"] is None
    assert pending["connected"] is False

    now = datetime.now(timezone.utc)
    activated_at = (now - timedelta(seconds=4)).isoformat(timespec="seconds").replace("+00:00", "Z")
    checked_in_at = (now - timedelta(seconds=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    timestamps = iter([activated_at, checked_in_at])
    monkeypatch.setattr("backend.app.api.extension.utc_now", lambda: next(timestamps))
    activated = client.post("/api/v1/extension/activate", json={"pairing_code": pair.json()["pairing_code"]})
    assert activated.status_code == 200
    headers = {"Authorization": f"Bearer {activated.json()['device_token']}"}

    after_pairing = client.get("/api/v1/devices").json()["items"][0]
    assert after_pairing["paired_at"] == activated_at
    assert after_pairing["last_seen_at"] == activated_at
    assert after_pairing["connected"] is True

    assert client.get("/api/v1/extension/policy", headers=headers).status_code == 200
    after_policy_checkin = client.get("/api/v1/devices").json()["items"][0]
    assert after_policy_checkin["last_seen_at"] == checked_in_at
    assert after_policy_checkin["connected"] is True

    from backend.app.database import connection

    stale_at = (now - timedelta(minutes=3)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with connection() as db:
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (stale_at, device_id))
    after_expiry = client.get("/api/v1/devices").json()["items"][0]
    assert after_expiry["last_seen_at"] == stale_at
    assert after_expiry["connected"] is False


def _paired_extension(client):
    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair")
    activated = client.post("/api/v1/extension/activate", json={"pairing_code": pair.json()["pairing_code"]})
    return {"Authorization": f"Bearer {activated.json()['device_token']}"}


def _classification_payloads(client, headers, source_url="https://sub.example.test/page?secret=1"):
    text = client.post("/api/v1/extension/classify/text", headers=headers, json={
        "text": "A test statement", "source_url": source_url, "event_key": "site-text-event-01",
    })
    image = client.post("/api/v1/extension/classify/image", headers=headers, params={
        "source_url": source_url, "event_key": "site-image-event-01",
    }, files={"file": ("page.png", b"uninspected", "image/png")})
    video = client.post("/api/v1/extension/classify/video", headers=headers, params={
        "source_url": source_url, "event_key": "site-video-event-01",
    }, files={"file": ("page.webm", b"uninspected", "video/webm")})
    return text, image, video


def test_website_policy_precedes_modality_and_text_eligibility_for_all_media(client, monkeypatch):
    import backend.app.api.extension as extension_api

    headers = _paired_extension(client)
    settings = client.get("/api/v1/settings").json()
    settings["modalities"] = {"text": False, "image": False, "video": False}
    assert client.put("/api/v1/settings", json=settings).status_code == 200
    assert client.post("/api/v1/rules", json={
        "kind": "website", "target": "example.test", "action": "block", "enabled": True,
    }).status_code == 201

    def inference_must_not_run(*_args, **_kwargs):
        raise AssertionError("Website policy must be applied before classifier eligibility or inference.")

    monkeypatch.setattr(extension_api, "classify_text", inference_must_not_run)
    monkeypatch.setattr(extension_api, "classify_image", inference_must_not_run)
    monkeypatch.setattr(extension_api, "classify_video", inference_must_not_run)
    responses = _classification_payloads(client, headers)
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert [response.json()["action"] for response in responses] == ["block", "block", "block"]
    assert [response.json()["category"] for response in responses] == ["website_rule"] * 3


def test_category_rules_apply_consistently_to_text_image_and_video(client, monkeypatch):
    import backend.app.api.extension as extension_api

    headers = _paired_extension(client)
    for category in ("threat_language", "violence"):
        response = client.post("/api/v1/rules", json={
            "kind": "category", "target": category, "action": "block", "enabled": True,
        })
        assert response.status_code == 201, response.text

    def result(modality, category):
        return {
            "modality": modality,
            "category": category,
            "confidence": 0.99,
            "scores": {category: 0.99},
            "classifier": "test model",
            "supported_categories": [category],
            "status": "classified",
        }

    monkeypatch.setattr(extension_api, "classify_text", lambda _text: result("text", "threat_language"))
    monkeypatch.setattr(extension_api, "classify_image", lambda _image: result("image", "violence"))
    monkeypatch.setattr(extension_api, "classify_video", lambda _video, _mime: result("video", "violence"))
    text, image, video = _classification_payloads(client, headers, "https://plain.example.test/")
    assert [response.status_code for response in (text, image, video)] == [200, 200, 200]
    assert [response.json()["action"] for response in (text, image, video)] == ["block", "block", "block"]


def test_classifier_readiness_reports_upload_limit_without_accepting_image_bytes(client, monkeypatch):
    import backend.app.api.extension as extension_api
    from backend.app.classifiers import ClassifierUnavailable

    headers = _paired_extension(client)

    def unavailable(_modality):
        raise ClassifierUnavailable("The candidate image model has no verified label map.")

    monkeypatch.setattr(extension_api, "prepare_classifier", unavailable)
    response = client.get("/api/v1/extension/readiness?modality=image", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is False
    assert response.json()["reason"] == "The candidate image model has no verified label map."
    assert response.json()["max_upload_bytes"] == 8 * 1024 * 1024


def test_policy_cache_lifetime_is_server_configurable(client, monkeypatch):
    from backend.app import config

    monkeypatch.setattr(config, "POLICY_CACHE_MAX_AGE_MINUTES", 37)
    headers = _paired_extension(client)
    response = client.get("/api/v1/extension/policy", headers=headers)
    assert response.status_code == 200
    assert response.json()["cache_max_age_minutes"] == 37


def test_pairing_code_is_account_scoped(client):
    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair")
    code = pair.json()["pairing_code"]
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/register", json={"name": "Second", "email": "second@example.com", "password": "Correct horse battery"})
    client.post("/api/v1/auth/login", json={"email": "second@example.com", "password": "Correct horse battery"})
    assert client.get("/api/v1/devices").json()["items"] == []
    # Pairing credentials are one-use bearer secrets, and only a matching pending record may consume them.
    assert client.post("/api/v1/extension/activate", json={"pairing_code": code}).status_code == 200
    assert client.get("/api/v1/devices").json()["items"] == []


def test_offline_website_event_is_metadata_only_deduplicated_and_revalidated(client):
    from backend.app.database import connection

    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair")
    activated = client.post("/api/v1/extension/activate", json={"pairing_code": pair.json()["pairing_code"]})
    headers = {"Authorization": f"Bearer {activated.json()['device_token']}"}
    rule = client.post("/api/v1/rules", json={"kind": "website", "target": "example.com", "action": "block", "enabled": True})
    assert rule.status_code == 201
    payload = {"modality": "text", "source_url": "https://news.example.com/story?private=1", "event_key": "offline-rule-event-01"}

    first = client.post("/api/v1/extension/offline-events", headers=headers, json=payload)
    second = client.post("/api/v1/extension/offline-events", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["action"] == "block"
    with connection() as db:
        event = db.execute("SELECT * FROM events WHERE event_key=?", (payload["event_key"],)).fetchone()
        assert event["category"] == "website_rule"
        assert event["confidence"] is None
        assert event["source_domain"] == "news.example.com"
        assert event["policy_reason"].find("example.com") >= 0
        assert "private=1" not in str(tuple(event))
        assert db.execute("SELECT COUNT(*) FROM alerts WHERE event_id=?", (event["id"],)).fetchone()[0] == 1

    assert client.post("/api/v1/extension/offline-events", headers=headers, json={**payload, "event_key": "other-event-key-02", "source_url": "https://other.test/"}).status_code == 409
    settings = client.get("/api/v1/settings").json()
    settings["protection_enabled"] = False
    client.put("/api/v1/settings", json=settings)
    assert client.post("/api/v1/extension/offline-events", headers=headers, json={**payload, "event_key": "disabled-event-003"}).status_code == 409

