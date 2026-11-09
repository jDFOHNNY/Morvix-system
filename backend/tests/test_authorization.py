import uuid

from backend.app.database import connection
from backend.app.time_utils import utc_now
from backend.tests.conftest import login, register


def test_history_and_alerts_are_account_scoped(client):
    first = register(client)
    login(client)
    event_id = str(uuid.uuid4())
    now = utc_now()
    with connection() as db:
        db.execute(
            "INSERT INTO events(id,user_id,occurred_at,modality,category,confidence,action,source_domain,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, first["id"], now, "text", "Threat Language", 0.98, "block", "example.com", now),
        )
        db.execute(
            "INSERT INTO alerts(id,user_id,event_id,severity,created_at) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), first["id"], event_id, "blocked", now),
        )
    client.post("/api/v1/auth/logout")
    register(client, "other@example.com", "Other Parent")
    login(client, "other@example.com")
    assert client.get("/api/v1/events").json()["total"] == 0
    assert client.get(f"/api/v1/events?event_id={event_id}").json()["total"] == 0
    assert client.get("/api/v1/alerts").json()["items"] == []
    assert client.get(f"/api/v1/events/{event_id}").status_code == 404
    assert client.patch(f"/api/v1/events/{event_id}/review").status_code == 404
