"""Authenticated parent dashboard, settings, rules, history and alerts."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from backend.app.database import connection
from backend.app.policies import ensure_policy, get_rules, normalize_domain
from backend.app.schemas import RuleInput, SettingsInput, SettingsPatchInput
from backend.app.security import get_parent, token_digest
from backend.app.time_utils import utc_now

router = APIRouter(prefix="/api/v1", tags=["parent dashboard"])


def _increment_policy_version(db, user_id: str) -> None:
    db.execute("UPDATE policies SET version=version+1,updated_at=? WHERE user_id=?", (utc_now(), user_id))


def _rule_data(row) -> dict:
    return dict(row) | {"enabled": bool(row["enabled"])}


@router.get("/dashboard/summary")
def dashboard_summary(
    days: int = Query(default=30, ge=7, le=365),
    modality: str | None = Query(default=None, pattern="^(text|image|video)$"),
    parent: dict = Depends(get_parent),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with connection() as db:
        policy = ensure_policy(parent["id"], db)
        action_rows = db.execute(
            "SELECT action,COUNT(*) AS count FROM events WHERE user_id=? AND occurred_at>=? GROUP BY action",
            (parent["id"], cutoff),
        ).fetchall()
        modality_rows = db.execute(
            "SELECT modality,COUNT(*) AS count FROM events WHERE user_id=? AND occurred_at>=? GROUP BY modality",
            (parent["id"], cutoff),
        ).fetchall()
        category_rows = db.execute(
            "SELECT category,COUNT(*) AS count FROM events WHERE user_id=? AND occurred_at>=? GROUP BY category",
            (parent["id"], cutoff),
        ).fetchall()
        total = db.execute("SELECT COUNT(*) FROM events WHERE user_id=? AND occurred_at>=?", (parent["id"], cutoff)).fetchone()[0]
        unread = db.execute("SELECT COUNT(*) FROM alerts WHERE user_id=? AND reviewed=0", (parent["id"],)).fetchone()[0]
        recent_query = (
            "SELECT id,occurred_at,modality,category,confidence,action,source_domain,policy_version,reviewed FROM events "
            "WHERE user_id=? AND occurred_at>=?"
        )
        recent_values: list = [parent["id"], cutoff]
        if modality:
            recent_query += " AND modality=?"
            recent_values.append(modality)
        recent_query += " ORDER BY occurred_at DESC LIMIT 8"
        recent = db.execute(recent_query, recent_values).fetchall()
        current_alerts = db.execute(
            "SELECT a.id,a.event_id,a.severity,a.reviewed,a.created_at,e.modality,e.category,e.action,e.source_domain,e.confidence "
            "FROM alerts a JOIN events e ON e.id=a.event_id "
            "WHERE a.user_id=? AND a.reviewed=0 ORDER BY a.created_at DESC LIMIT 5",
            (parent["id"],),
        ).fetchall()
        devices = db.execute(
            "SELECT id,label,last_seen_at,revoked_at FROM devices WHERE user_id=? AND paired_at IS NOT NULL ORDER BY created_at DESC",
            (parent["id"],),
        ).fetchall()
    now = datetime.now(timezone.utc)
    device_data = [
        {
            "id": row["id"],
            "label": row["label"],
            "last_seen_at": row["last_seen_at"],
            "revoked": row["revoked_at"] is not None,
            "connected": bool(row["last_seen_at"] and (now - datetime.fromisoformat(row["last_seen_at"].replace("Z", "+00:00"))).total_seconds() <= 120 and not row["revoked_at"]),
        }
        for row in devices
    ]
    action_counts = {key: 0 for key in ("allow", "warn", "block")}
    action_counts.update({row["action"]: row["count"] for row in action_rows})
    return {
        "period_days": days,
        "event_modalities": ["text", "image", "video"],
        "protection_enabled": policy["protection_enabled"],
        "extension_connected": any(device["connected"] for device in device_data),
        "devices": device_data,
        "counts": {"total": total, "blocked": action_counts["block"], "flagged": action_counts["warn"], "allowed": action_counts["allow"], "unread_alerts": unread},
        "by_action": action_counts,
        "by_modality": {row["modality"]: row["count"] for row in modality_rows},
        "by_category": {row["category"]: row["count"] for row in category_rows},
        "recent": [dict(row) | {"reviewed": bool(row["reviewed"])} for row in recent],
        "alerts": [dict(row) | {"reviewed": bool(row["reviewed"])} for row in current_alerts],
        "model_performance": None,
    }


@router.get("/events")
def list_events(
    event_id: str | None = Query(default=None, max_length=64),
    search: str | None = Query(default=None, max_length=200),
    modality: str | None = Query(default=None, pattern="^(text|image|video)$"),
    category: str | None = Query(default=None, max_length=80),
    action: str | None = Query(default=None, pattern="^(allow|warn|block)$"),
    domain: str | None = Query(default=None, max_length=253),
    date_from: str | None = Query(default=None, max_length=40),
    date_to: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    parent: dict = Depends(get_parent),
):
    clauses = ["user_id=?"]
    values: list = [parent["id"]]
    if event_id:
        clauses.append("id=?")
        values.append(event_id)
    if modality:
        clauses.append("modality=?")
        values.append(modality)
    if category:
        clauses.append("category=?")
        values.append(category)
    if action:
        clauses.append("action=?")
        values.append(action)
    if domain:
        clauses.append("source_domain LIKE ?")
        values.append("%" + domain.strip().lower() + "%")
    if search:
        clauses.append("(category LIKE ? OR source_domain LIKE ? OR modality LIKE ?)")
        needle = "%" + search.strip() + "%"
        values.extend([needle, needle, needle])
    try:
        if date_from:
            parsed = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            clauses.append("occurred_at>=?")
            values.append(parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        if date_to:
            parsed = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            clauses.append("occurred_at<=?")
            values.append(parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date filters must be valid ISO-8601 timestamps.") from exc
    where = " AND ".join(clauses)
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM events WHERE {where}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT id,occurred_at,modality,category,confidence,action,source_domain,classifier_version,policy_reason,policy_version,reviewed "
            f"FROM events WHERE {where} ORDER BY occurred_at DESC LIMIT ? OFFSET ?",
            values + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {"items": [dict(row) | {"reviewed": bool(row["reviewed"])} for row in rows], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.get("/events/{event_id}")
def get_event(event_id: str, parent: dict = Depends(get_parent)):
    with connection() as db:
        row = db.execute("SELECT * FROM events WHERE id=? AND user_id=?", (event_id, parent["id"])).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Detection event not found.")
    return dict(row) | {"reviewed": bool(row["reviewed"])}


@router.patch("/events/{event_id}/review")
def review_event(event_id: str, parent: dict = Depends(get_parent)):
    with connection() as db:
        result = db.execute("UPDATE events SET reviewed=1 WHERE id=? AND user_id=?", (event_id, parent["id"]))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Detection event not found.")
    return {"id": event_id, "reviewed": True}


@router.get("/alerts")
def list_alerts(unread_only: bool = False, parent: dict = Depends(get_parent)):
    query = (
        "SELECT a.id,a.event_id,a.severity,a.reviewed,a.created_at,e.modality,e.category,e.action,e.source_domain,e.confidence "
        "FROM alerts a JOIN events e ON e.id=a.event_id WHERE a.user_id=?"
    )
    values: list = [parent["id"]]
    if unread_only:
        query += " AND a.reviewed=0"
    query += " ORDER BY a.created_at DESC LIMIT 200"
    with connection() as db:
        rows = db.execute(query, values).fetchall()
    return {"items": [dict(row) | {"reviewed": bool(row["reviewed"])} for row in rows]}


@router.patch("/alerts/{alert_id}/review")
def review_alert(alert_id: str, parent: dict = Depends(get_parent)):
    with connection() as db:
        row = db.execute("SELECT event_id FROM alerts WHERE id=? AND user_id=?", (alert_id, parent["id"])).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        db.execute("UPDATE alerts SET reviewed=1 WHERE id=?", (alert_id,))
        db.execute("UPDATE events SET reviewed=1 WHERE id=? AND user_id=?", (row["event_id"], parent["id"]))
    return {"id": alert_id, "reviewed": True}


@router.get("/rules")
def list_rules(parent: dict = Depends(get_parent)):
    with connection() as db:
        return {"items": get_rules(parent["id"], db)}


@router.post("/rules", status_code=201)
def create_rule(payload: RuleInput, parent: dict = Depends(get_parent)):
    target = payload.target.lower()
    if payload.kind == "website":
        target = normalize_domain(target) or ""
        if not target:
            raise HTTPException(status_code=422, detail="Enter a valid website domain.")
    rule_id, now = str(uuid.uuid4()), utc_now()
    try:
        with connection() as db:
            db.execute(
                "INSERT INTO rules(id,user_id,kind,target,action,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (rule_id, parent["id"], payload.kind, target, payload.action, int(payload.enabled), now, now),
            )
            _increment_policy_version(db, parent["id"])
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A rule for this target already exists.") from exc
    with connection() as db:
        row = db.execute("SELECT * FROM rules WHERE id=? AND user_id=?", (rule_id, parent["id"])).fetchone()
    return _rule_data(row)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, payload: RuleInput, parent: dict = Depends(get_parent)):
    target = payload.target.lower()
    if payload.kind == "website":
        target = normalize_domain(target) or ""
        if not target:
            raise HTTPException(status_code=422, detail="Enter a valid website domain.")
    try:
        with connection() as db:
            row = db.execute("SELECT id FROM rules WHERE id=? AND user_id=?", (rule_id, parent["id"])).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Rule not found.")
            db.execute(
                "UPDATE rules SET kind=?,target=?,action=?,enabled=?,updated_at=? WHERE id=? AND user_id=?",
                (payload.kind, target, payload.action, int(payload.enabled), utc_now(), rule_id, parent["id"]),
            )
            _increment_policy_version(db, parent["id"])
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A rule for this target already exists.") from exc
    with connection() as db:
        row = db.execute("SELECT * FROM rules WHERE id=? AND user_id=?", (rule_id, parent["id"])).fetchone()
    return _rule_data(row)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, parent: dict = Depends(get_parent)):
    with connection() as db:
        result = db.execute("DELETE FROM rules WHERE id=? AND user_id=?", (rule_id, parent["id"]))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found.")
        _increment_policy_version(db, parent["id"])


@router.get("/settings")
def get_settings(parent: dict = Depends(get_parent)):
    with connection() as db:
        return ensure_policy(parent["id"], db)


@router.put("/settings")
def update_settings(payload: SettingsInput, parent: dict = Depends(get_parent)):
    with connection() as db:
        ensure_policy(parent["id"], db)
        db.execute(
            "UPDATE policies SET protection_enabled=?,modalities_json=?,category_actions_json=?,thresholds_json=?,version=version+1,updated_at=? WHERE user_id=?",
            (int(payload.protection_enabled), json.dumps(payload.modalities), json.dumps(payload.category_actions), json.dumps(payload.thresholds), utc_now(), parent["id"]),
        )
        return ensure_policy(parent["id"], db)


@router.patch("/settings")
def patch_settings(payload: SettingsPatchInput, parent: dict = Depends(get_parent)):
    """Apply only the controls the parent changed to the latest saved policy."""
    with connection() as db:
        current = ensure_policy(parent["id"], db)
        merged = {
            "protection_enabled": current["protection_enabled"],
            "modalities": dict(current["modalities"]),
            "category_actions": dict(current["category_actions"]),
            "thresholds": {category: dict(values) for category, values in current["thresholds"].items()},
        }
        changes = payload.model_dump(exclude_unset=True)
        if "protection_enabled" in changes:
            merged["protection_enabled"] = changes["protection_enabled"]
        for field in ("modalities", "category_actions"):
            if field in changes:
                merged[field].update(changes[field])
        if "thresholds" in changes:
            for category, values in changes["thresholds"].items():
                merged["thresholds"][category].update(values)
        try:
            validated = SettingsInput.model_validate(merged)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
        db.execute(
            "UPDATE policies SET protection_enabled=?,modalities_json=?,category_actions_json=?,thresholds_json=?,version=version+1,updated_at=? WHERE user_id=?",
            (
                int(validated.protection_enabled),
                json.dumps(validated.modalities),
                json.dumps(validated.category_actions),
                json.dumps(validated.thresholds),
                utc_now(),
                parent["id"],
            ),
        )
        return ensure_policy(parent["id"], db)


@router.post("/devices/pair", status_code=201)
def create_pairing_code(label: str = Query(default="Protected browser", min_length=1, max_length=80), parent: dict = Depends(get_parent)):
    device_id = str(uuid.uuid4())
    code = secrets.token_urlsafe(9)
    now_dt = datetime.now(timezone.utc)
    expiry = (now_dt + timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with connection() as db:
        db.execute(
            "INSERT INTO devices(id,user_id,label,pairing_code_hash,pairing_expires_at,created_at) VALUES(?,?,?,?,?,?)",
            (device_id, parent["id"], label.strip(), token_digest(code), expiry, utc_now()),
        )
    return {"device_id": device_id, "pairing_code": code, "expires_at": expiry, "instructions": "Enter this one-time code in the MORVIX extension popup within five minutes."}


@router.get("/devices")
def list_devices(parent: dict = Depends(get_parent)):
    with connection() as db:
        rows = db.execute("SELECT id,label,paired_at,last_seen_at,revoked_at,created_at FROM devices WHERE user_id=? ORDER BY created_at DESC", (parent["id"],)).fetchall()
    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        item = dict(row)
        last_seen = datetime.fromisoformat(row["last_seen_at"].replace("Z", "+00:00")) if row["last_seen_at"] else None
        item["connected"] = bool(last_seen and (now - last_seen).total_seconds() <= 120 and not row["revoked_at"])
        item["revoked"] = row["revoked_at"] is not None
        items.append(item)
    return {"items": items}


@router.delete("/devices/{device_id}")
def revoke_device(device_id: str, parent: dict = Depends(get_parent)):
    with connection() as db:
        result = db.execute(
            "UPDATE devices SET revoked_at=?,token_hash=NULL WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (utc_now(), device_id, parent["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Active extension not found.")
    return {"id": device_id, "revoked": True}

