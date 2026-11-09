"""Metadata-only detection event and corresponding alert persistence."""

from __future__ import annotations

import uuid

from backend.app.time_utils import utc_now


def record_detection(
    db,
    *,
    user_id: str,
    device_id: str | None,
    modality: str,
    category: str,
    confidence: float | None,
    action: str,
    source_domain: str | None,
    classifier_version: str | None,
    policy_reason: str,
    policy_version: int,
    event_key: str | None = None,
) -> dict:
    now = utc_now()
    event_id = str(uuid.uuid4())
    db.execute(
        "INSERT OR IGNORE INTO events(id,user_id,device_id,occurred_at,modality,category,confidence,action,source_domain,classifier_version,policy_reason,policy_version,event_key,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, user_id, device_id, now, modality, category, confidence, action, source_domain, classifier_version, policy_reason, policy_version, event_key, now),
    )
    if event_key:
        row = db.execute("SELECT * FROM events WHERE user_id=? AND event_key=?", (user_id, event_key)).fetchone()
        event_id = row["id"]
    else:
        row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row["action"] in {"warn", "block"}:
        severity = "blocked" if row["action"] == "block" else "warning"
        db.execute(
            "INSERT OR IGNORE INTO alerts(id,user_id,event_id,severity,created_at) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), user_id, event_id, severity, now),
        )
    return dict(row) | {"reviewed": bool(row["reviewed"])}

