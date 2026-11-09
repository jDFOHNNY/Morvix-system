"""Regression coverage for parent-scoped threshold persistence and extension policy sync."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app import config
from backend.app.api import extension, parent
from backend.app.database import connection, initialize_database
from backend.app.main import create_app
from backend.app.policies import ensure_policy
from backend.app.schemas import SettingsPatchInput
from backend.app.time_utils import utc_now


@pytest.fixture
def threshold_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "threshold-settings.db")
    initialize_database()
    now = utc_now()
    users = [str(uuid.uuid4()), str(uuid.uuid4())]
    devices = [str(uuid.uuid4()), str(uuid.uuid4())]
    with connection() as db:
        for index, user_id in enumerate(users):
            db.execute(
                "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
                (user_id, f"Parent {index + 1}", f"parent{index + 1}@example.test", "test-only", now),
            )
            ensure_policy(user_id, db)
            db.execute(
                "INSERT INTO devices(id,user_id,label,paired_at,last_seen_at,created_at) VALUES(?,?,?,?,?,?)",
                (devices[index], user_id, f"Device {index + 1}", now, now, now),
            )
    return {
        "parents": [{"id": user_id} for user_id in users],
        "devices": [
            {"id": device_id, "user_id": user_id}
            for device_id, user_id in zip(devices, users)
        ],
    }


def test_threshold_values_persist_exactly_survive_reload_and_sync(threshold_accounts):
    first, second = threshold_accounts["parents"]
    initial = parent.get_settings(first)
    changed = parent.patch_settings(
        SettingsPatchInput(
            thresholds={
                "threat_language": {"review": 0.43, "block": 0.67},
                "violence": {"review": 0.37, "block": 0.82},
            }
        ),
        first,
    )

    assert changed["version"] == initial["version"] + 1
    assert changed["thresholds"]["threat_language"] == {"review": 0.43, "block": 0.67}
    assert changed["thresholds"]["violence"] == {"review": 0.37, "block": 0.82}

    # A fresh GET is the same read path used when the Settings page is reopened.
    reloaded = parent.get_settings(first)
    assert reloaded["thresholds"] == changed["thresholds"]
    assert parent.get_settings(second)["thresholds"] != reloaded["thresholds"]

    snapshot = extension.synchronize_policy(threshold_accounts["devices"][0])
    assert snapshot["policy"]["version"] == changed["version"]
    assert snapshot["policy"]["thresholds"] == changed["thresholds"]


def test_partial_threshold_update_preserves_other_saved_values_and_parent_isolation(threshold_accounts):
    first, second = threshold_accounts["parents"]
    parent.patch_settings(
        SettingsPatchInput(
            thresholds={
                "threat_language": {"review": 0.44, "block": 0.72},
                "violence": {"review": 0.31, "block": 0.83},
            }
        ),
        first,
    )
    before_second = parent.get_settings(second)

    updated = parent.patch_settings(
        SettingsPatchInput(thresholds={"threat_language": {"block": 0.66}}),
        first,
    )

    assert updated["thresholds"]["threat_language"] == {"review": 0.44, "block": 0.66}
    assert updated["thresholds"]["violence"] == {"review": 0.31, "block": 0.83}
    assert parent.get_settings(second) == before_second


def test_invalid_or_crossed_thresholds_are_rejected_without_persisting(threshold_accounts):
    first = threshold_accounts["parents"][0]
    before = parent.get_settings(first)
    with pytest.raises(ValidationError):
        SettingsPatchInput(thresholds={"threat_language": {"block": 1.01}})

    with pytest.raises(HTTPException) as error:
        parent.patch_settings(
            SettingsPatchInput(thresholds={"threat_language": {"review": 0.95}}),
            first,
        )
    assert error.value.status_code == 422
    after = parent.get_settings(first)
    assert after["thresholds"] == before["thresholds"]
    assert after["version"] == before["version"]


def test_dashboard_settings_endpoint_accepts_patch():
    methods = set().union(
        *(
            route.methods
            for route in create_app().routes
            if getattr(route, "path", None) == "/api/v1/settings"
        )
    )
    assert {"GET", "PUT", "PATCH"} <= methods
