import uuid
from datetime import datetime, timedelta, timezone

from backend.app.database import connection
from backend.app.time_utils import utc_now
from backend.tests.conftest import login, register


def test_overview_filter_helper_is_served_with_dashboard(client):
    page = client.get("/")
    asset = client.get("/assets/js/dashboard_view.js")
    assert page.status_code == 200
    assert 'dashboard_view.js' in page.text
    assert asset.status_code == 200
    assert "summaryPath" in asset.text


def test_dashboard_summary_uses_empty_database_counts_and_no_unmeasured_accuracy(client):
    register(client)
    login(client)
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["counts"] == {"total": 0, "blocked": 0, "flagged": 0, "allowed": 0, "unread_alerts": 0}
    assert data["recent"] == []
    assert data["alerts"] == []
    assert data["period_days"] == 30
    assert data["event_modalities"] == ["text", "image", "video"]
    assert data["model_performance"] is None


def test_dashboard_summary_selected_period_modality_recent_filter_and_alert_details(client):
    user = register(client)
    login(client)
    now = datetime.now(timezone.utc)
    recent_text = str(uuid.uuid4())
    recent_video = str(uuid.uuid4())
    older_image = str(uuid.uuid4())
    with connection() as db:
        for event_id, days_ago, modality, category, action, domain in (
            (recent_text, 1, "text", "threat_language", "warn", "text.example.com"),
            (recent_video, 2, "video", "violence", "block", "video.example.com"),
            (older_image, 45, "image", "violence", "allow", "image.example.com"),
        ):
            occurred = (now - timedelta(days=days_ago)).isoformat(timespec="seconds").replace("+00:00", "Z")
            db.execute(
                "INSERT INTO events(id,user_id,occurred_at,modality,category,confidence,action,source_domain,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, user["id"], occurred, modality, category, 0.72, action, domain, occurred),
            )
            if action in {"warn", "block"}:
                severity = "blocked" if action == "block" else "warning"
                db.execute(
                    "INSERT INTO alerts(id,user_id,event_id,severity,created_at) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), user["id"], event_id, severity, occurred),
                )

    filtered = client.get("/api/v1/dashboard/summary?days=7&modality=text")
    assert filtered.status_code == 200
    data = filtered.json()
    assert data["period_days"] == 7
    assert data["counts"] == {"total": 2, "blocked": 1, "flagged": 1, "allowed": 0, "unread_alerts": 2}
    assert data["by_action"] == {"allow": 0, "warn": 1, "block": 1}
    assert data["by_modality"] == {"text": 1, "video": 1}
    assert [item["id"] for item in data["recent"]] == [recent_text]
    assert {"category", "source_domain", "occurred_at", "modality", "confidence", "action"} <= data["recent"][0].keys()
    assert {item["event_id"] for item in data["alerts"]} == {recent_text, recent_video}
    assert all({"category", "source_domain", "created_at", "modality", "confidence", "action"} <= item.keys() for item in data["alerts"])

    longer_range = client.get("/api/v1/dashboard/summary?days=90&modality=video")
    assert longer_range.status_code == 200
    longer = longer_range.json()
    assert longer["counts"]["total"] == 3
    assert longer["counts"]["allowed"] == 1
    assert [item["id"] for item in longer["recent"]] == [recent_video]
    assert longer["by_modality"] == {"text": 1, "video": 1, "image": 1}


def test_dashboard_summary_rejects_unsupported_modality_and_invalid_range(client):
    register(client)
    login(client)
    assert client.get("/api/v1/dashboard/summary?modality=audio").status_code == 422
    assert client.get("/api/v1/dashboard/summary?days=500").status_code == 422


def test_history_filters_and_alert_review_round_trip(client):
    user = register(client)
    login(client)
    now = utc_now()
    target_id = str(uuid.uuid4())
    with connection() as db:
        for modality, category, action, domain in (
            ("text", "threat_language", "warn", "news.example.com"),
            ("image", "violence", "block", "media.example.net"),
        ):
            event_id = target_id if modality == "image" else str(uuid.uuid4())
            db.execute(
                "INSERT INTO events(id,user_id,occurred_at,modality,category,confidence,action,source_domain,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, user["id"], now, modality, category, 0.8, action, domain, now),
            )
            if action == "block":
                db.execute(
                    "INSERT INTO alerts(id,user_id,event_id,severity,created_at) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), user["id"], event_id, "blocked", now),
                )

    history = client.get("/api/v1/events?modality=image&action=block&domain=example.net")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == target_id
    linked_history = client.get(f"/api/v1/events?event_id={target_id}")
    assert linked_history.status_code == 200
    assert linked_history.json()["total"] == 1
    assert linked_history.json()["items"][0]["id"] == target_id
    assert client.get("/api/v1/events?category=violence").json()["total"] == 1
    assert client.get("/api/v1/events?search=news.example.com").json()["total"] == 1
    assert client.get(f"/api/v1/events?date_from={now}&date_to={now}").json()["total"] == 2
    alerts = client.get("/api/v1/alerts?unread_only=true").json()["items"]
    assert len(alerts) == 1 and alerts[0]["reviewed"] is False
    reviewed = client.patch(f"/api/v1/alerts/{alerts[0]['id']}/review")
    assert reviewed.status_code == 200 and reviewed.json()["reviewed"] is True
    assert client.get("/api/v1/alerts?unread_only=true").json()["items"] == []

