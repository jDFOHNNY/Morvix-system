"""Regression coverage for parent category rules and final enforcement actions."""

import json
import uuid

import pytest

from backend.app import config
from backend.app.api import extension, parent
from backend.app.database import connection, initialize_database
from backend.app.policies import ensure_policy
from backend.app.schemas import SettingsPatchInput
from backend.app.time_utils import utc_now


@pytest.fixture
def threat_rule_device(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "policy-enforcement.db")
    initialize_database()
    user_id, device_id, rule_id = (str(uuid.uuid4()) for _ in range(3))
    now = utc_now()
    with connection() as db:
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, "Policy Test Parent", "policy-test@example.test", "test-only", now),
        )
        ensure_policy(user_id, db)
        db.execute(
            "INSERT INTO rules(id,user_id,kind,target,action,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (rule_id, user_id, "category", "threat_language", "block", 1, now, now),
        )
        db.execute("UPDATE policies SET version=version+1 WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO devices(id,user_id,label,paired_at,last_seen_at,created_at) VALUES(?,?,?,?,?,?)",
            (device_id, user_id, "Policy regression test", now, now, now),
        )
    return {"user_id": user_id, "device_id": device_id, "rule_id": rule_id}


def _threat_result():
    return {
        "status": "classified",
        "modality": "text",
        "category": "threat_language",
        "confidence": 0.6422476172447205,
        "scores": {"threat_language": 0.6422476172447205},
        "supported_categories": ["threat_language"],
        "classifier": "injected-test-adapter",
    }


def _analyze(device, event_key):
    return extension._analyze(
        device,
        "text",
        "http://127.0.0.1:8001/threat-only.html",
        event_key,
        _threat_result,
    )


def test_configured_threat_block_at_64_percent_is_flagged_by_default_threshold_and_saved(threat_rule_device, monkeypatch):
    device = threat_rule_device
    synchronized = extension.synchronize_policy({"id": device["device_id"], "user_id": device["user_id"]})
    snapshot = synchronized
    rule = next(item for item in snapshot["rules"] if item["id"] == device["rule_id"])
    assert (rule["kind"], rule["target"], rule["action"], rule["enabled"]) == (
        "category", "threat_language", "block", True,
    )
    assert snapshot["policy"]["thresholds"]["threat_language"] == {"review": 0.5, "block": 0.9}

    applied_versions = []
    original_ensure_policy = extension.ensure_policy

    def capture_policy_version(user_id, db):
        policy = original_ensure_policy(user_id, db)
        applied_versions.append(policy["version"])
        return policy

    monkeypatch.setattr(extension, "ensure_policy", capture_policy_version)
    response = _analyze({"id": device["device_id"], "user_id": device["user_id"]}, "threat-rule-event-01")

    assert response["confidence"] == 0.6422476172447205
    assert response["action"] == "warn"
    assert "block threshold" in response["reason"]
    assert response["policy_version"] == snapshot["policy"]["version"]
    assert applied_versions == [snapshot["policy"]["version"]]
    with connection() as db:
        event = db.execute("SELECT * FROM events WHERE id=?", (response["event_id"],)).fetchone()
        alert = db.execute("SELECT severity FROM alerts WHERE event_id=?", (response["event_id"],)).fetchone()
    assert event["category"] == "threat_language"
    assert event["confidence"] == response["confidence"]
    assert event["action"] == response["action"] == "warn"
    assert event["policy_version"] == response["policy_version"]
    assert event["source_domain"] == "127.0.0.1"
    assert event["policy_reason"] == response["reason"]
    assert alert["severity"] == "warning"


def test_64_percent_blocks_only_after_parent_lowers_threshold_and_saved_action_is_authoritative(threat_rule_device, monkeypatch):
    device = threat_rule_device
    applied_versions = []
    original_ensure_policy = extension.ensure_policy

    def capture_policy_version(user_id, db):
        policy = original_ensure_policy(user_id, db)
        applied_versions.append(policy["version"])
        return policy

    monkeypatch.setattr(extension, "ensure_policy", capture_policy_version)
    first = _analyze({"id": device["device_id"], "user_id": device["user_id"]}, "threat-rule-event-02")
    assert first["action"] == "warn"
    with connection() as db:
        policy = ensure_policy(device["user_id"], db)
        policy["thresholds"]["threat_language"]["block"] = 0.6
        db.execute(
            "UPDATE policies SET thresholds_json=?,version=version+1,updated_at=? WHERE user_id=?",
            (json.dumps(policy["thresholds"]), utc_now(), device["user_id"]),
        )
    updated_snapshot = extension.synchronize_policy({"id": device["device_id"], "user_id": device["user_id"]})
    assert updated_snapshot["policy"]["version"] == applied_versions[0] + 1

    # A retry with the original idempotency key must use the already persisted
    # action and reason, even though current policy now resolves new events to Block.
    retry = _analyze({"id": device["device_id"], "user_id": device["user_id"]}, "threat-rule-event-02")
    assert retry["event_id"] == first["event_id"]
    assert retry["action"] == first["action"] == "warn"
    assert retry["reason"] == first["reason"]
    assert retry["policy_version"] == first["policy_version"]
    assert applied_versions[-1] == updated_snapshot["policy"]["version"]

    # A new event under that same parent-controlled version is Block and is
    # persisted with the same final action that the extension receives.
    blocked = _analyze({"id": device["device_id"], "user_id": device["user_id"]}, "threat-rule-event-03")
    assert blocked["confidence"] == 0.6422476172447205
    assert blocked["action"] == "block"
    assert blocked["policy_version"] == updated_snapshot["policy"]["version"]
    assert applied_versions[-1] == updated_snapshot["policy"]["version"]
    with connection() as db:
        event = db.execute("SELECT * FROM events WHERE id=?", (blocked["event_id"],)).fetchone()
        alert = db.execute("SELECT severity FROM alerts WHERE event_id=?", (blocked["event_id"],)).fetchone()
    assert event["action"] == blocked["action"] == "block"
    assert event["policy_version"] == blocked["policy_version"]
    assert event["policy_reason"] == blocked["reason"]
    assert event["source_domain"] == "127.0.0.1"
    assert alert["severity"] == "blocked"


def test_fixed_64_percent_result_follows_multiple_parent_saved_block_thresholds(threat_rule_device):
    device = threat_rule_device
    parent_account = {"id": device["user_id"]}
    confidence = _threat_result()["confidence"]

    # This is the fixed classifier result from the controlled threat-language
    # case. Only the parent's saved threshold changes between requests.
    for index, block_threshold in enumerate((0.60, 0.64, 0.65, 0.75, 0.90), start=1):
        saved = parent.patch_settings(
            SettingsPatchInput(thresholds={"threat_language": {"block": block_threshold}}),
            parent_account,
        )
        synchronized = extension.synchronize_policy(
            {"id": device["device_id"], "user_id": device["user_id"]}
        )
        assert synchronized["policy"]["thresholds"]["threat_language"]["block"] == block_threshold
        assert synchronized["policy"]["version"] == saved["version"]

        response = _analyze(
            {"id": device["device_id"], "user_id": device["user_id"]},
            f"threshold-boundary-event-{index}",
        )
        expected_action = "block" if confidence >= block_threshold else "warn"
        assert response["confidence"] == confidence
        assert response["action"] == expected_action
        assert response["policy_version"] == saved["version"]
        with connection() as db:
            event = db.execute("SELECT action,confidence,policy_version FROM events WHERE id=?", (response["event_id"],)).fetchone()
        assert event["action"] == expected_action
        assert event["confidence"] == confidence
        assert event["policy_version"] == saved["version"]


def test_schema_v1_database_migrates_to_policy_versioned_detection_events(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "schema-migration.db")
    initialize_database()
    user_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = utc_now()
    with connection() as db:
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, "Migration Test Parent", "migration-test@example.test", "test-only", now),
        )
        db.execute(
            "INSERT INTO events(id,user_id,occurred_at,modality,category,confidence,action,source_domain,policy_reason,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, user_id, now, "text", "threat_language", 0.64, "warn", "example.test", "legacy event", now),
        )
        db.execute("ALTER TABLE events DROP COLUMN policy_version")
        db.execute("UPDATE schema_version SET version=1")

    initialize_database()
    with connection() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        version = db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        oauth_tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        event = db.execute("SELECT id,action,policy_version FROM events WHERE id=?", (event_id,)).fetchone()
    assert "policy_version" in columns
    assert version == 3
    assert "oauth_identities" in oauth_tables
    assert event["id"] == event_id
    assert event["action"] == "warn"
    assert event["policy_version"] is None
