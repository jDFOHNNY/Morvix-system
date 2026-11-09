from backend.app import config
from backend.app.api import extension, parent
from backend.app.database import connection, initialize_database
from backend.app.policies import ensure_policy
from backend.app.schemas import RuleInput, SettingsInput
from backend.app.time_utils import utc_now


def test_text_route_saves_low_score_allow_events_independently_of_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "morvix-text-history.db")
    initialize_database()
    user_id = "parent-history-test"
    other_user_id = "different-parent-history-test"
    device_id = "extension-history-test"
    with connection() as db:
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, "Parent", "parent-history-test@example.invalid", "test-only", utc_now()),
        )
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (other_user_id, "Other Parent", "other-parent-history-test@example.invalid", "test-only", utc_now()),
        )
        db.execute(
            "INSERT INTO devices(id,user_id,label,created_at) VALUES(?,?,?,?)",
            (device_id, user_id, "Test Extension", utc_now()),
        )

    seen_text = []
    text = "A harmless fictional story mentions an old cemetery and a stormy night."
    monkeypatch.setattr(extension, "classify_text", lambda value: seen_text.append(value) or {
        "status": "classified",
        "modality": "text",
        "category": None,
        "confidence": 0.00012,
        "scores": {"threat_language": 0.00012},
        "supported_categories": ["threat_language"],
        "classifier": "isolated-domain-independence-test",
    })

    urls = [
        "https://www.gutenberg.org/ebooks/12345",
        "https://en.wikipedia.org/wiki/Example",
        "https://example.org/story",
    ]
    responses = [
        extension.analyze_text(
            extension.TextAnalysisInput(text=text, source_url=url, event_key=f"domain-independence-{index:02d}"),
            {"id": device_id, "user_id": user_id},
        )
        for index, url in enumerate(urls)
    ]

    assert seen_text == [text, text, text]
    assert len({response["event_id"] for response in responses}) == 3
    assert all(response["status"] == "classified" for response in responses)
    assert all(response["category"] == "threat_language" for response in responses)
    assert all(response["confidence"] == 0.00012 for response in responses)
    assert all(response["detected"] is False and response["action"] == "allow" for response in responses)
    assert all(response["event_id"] and response["policy_version"] == 1 for response in responses)

    with connection() as db:
        rows = db.execute(
            "SELECT id,user_id,device_id,occurred_at,modality,category,confidence,action,source_domain,classifier_version,policy_version "
            "FROM events WHERE user_id=? ORDER BY source_domain",
            (user_id,),
        ).fetchall()
        raw_text_columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        stored_values = [str(value) for row in db.execute("SELECT * FROM events WHERE user_id=?", (user_id,)) for value in row]
        summary = db.execute("SELECT action,COUNT(*) AS count FROM events WHERE user_id=? GROUP BY action", (user_id,)).fetchall()
    assert len(rows) == 3
    assert {row["source_domain"] for row in rows} == {"www.gutenberg.org", "en.wikipedia.org", "example.org"}
    assert {row["user_id"] for row in rows} == {user_id}
    assert {row["device_id"] for row in rows} == {device_id}
    assert all(row["category"] == "threat_language" and row["confidence"] == 0.00012 for row in rows)
    assert all(row["action"] == "allow" and row["modality"] == "text" for row in rows)
    assert all(row["occurred_at"] and row["policy_version"] for row in rows)
    assert all(row["classifier_version"] == "isolated-domain-independence-test" for row in rows)
    assert "raw_text" not in raw_text_columns
    assert all(text not in value for value in stored_values)
    assert {row["action"]: row["count"] for row in summary} == {"allow": 3}
    history = parent.list_events(
        event_id=None, search=None, modality=None, category=None, action=None, domain=None,
        date_from=None, date_to=None, page=1, page_size=20, parent={"id": user_id},
    )
    dashboard = parent.dashboard_summary(days=30, modality=None, parent={"id": user_id})
    assert history["total"] == 3
    assert {item["id"] for item in history["items"]} == {response["event_id"] for response in responses}
    by_event_id = {row["id"]: row for row in rows}
    assert all(response["policy_version"] == by_event_id[response["event_id"]]["policy_version"] for response in responses)
    assert all(response["category"] == by_event_id[response["event_id"]]["category"] for response in responses)
    assert all(response["confidence"] == by_event_id[response["event_id"]]["confidence"] for response in responses)
    assert all(response["action"] == by_event_id[response["event_id"]]["action"] for response in responses)
    other_parent_history = parent.list_events(
        event_id=None, search=None, modality=None, category=None, action=None, domain=None,
        date_from=None, date_to=None, page=1, page_size=20, parent={"id": other_user_id},
    )
    assert other_parent_history["total"] == 0
    assert dashboard["counts"]["allowed"] == dashboard["counts"]["total"] == 3
    assert dashboard["by_modality"] == {"text": 3}
    assert dashboard["by_category"] == {"threat_language": 3}
    assert dashboard["by_action"]["allow"] == 3


def test_text_event_is_not_created_when_result_has_no_supported_category(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "morvix-unsupported-result.db")
    initialize_database()
    user_id = "parent-unsupported-result-test"
    device_id = "extension-unsupported-result-test"
    with connection() as db:
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, "Parent", "unsupported-parent@example.invalid", "test-only", utc_now()),
        )
        db.execute(
            "INSERT INTO devices(id,user_id,label,created_at) VALUES(?,?,?,?)",
            (device_id, user_id, "Test Extension", utc_now()),
        )

    monkeypatch.setattr(extension, "classify_text", lambda _value: {
        "status": "classified", "modality": "text", "category": None, "confidence": None,
        "scores": {}, "supported_categories": [], "classifier": "unsupported-result-test",
    })
    response = extension.analyze_text(
        extension.TextAnalysisInput(
            text="Harmless test input.", source_url="https://en.wikipedia.org/wiki/Example",
            event_key="unsupported-result-0001",
        ),
        {"id": device_id, "user_id": user_id},
    )

    assert response["category"] is None
    assert response["confidence"] is None
    assert response["action"] == "allow"
    assert response["event_id"] is None
    assert "no supported category" in response["reason"]
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE user_id=?", (user_id,)).fetchone()[0] == 0




def test_saved_category_rule_and_block_threshold_determine_text_event_action(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "morvix-text-policy.db")
    initialize_database()
    user_id = "parent-policy-test"
    device_id = "extension-policy-test"
    with connection() as db:
        db.execute(
            "INSERT INTO users(id,name,email,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, "Parent", "parent-policy-test@example.invalid", "test-only", utc_now()),
        )
        db.execute(
            "INSERT INTO devices(id,user_id,label,created_at) VALUES(?,?,?,?)",
            (device_id, user_id, "Test Extension", utc_now()),
        )
        settings = ensure_policy(user_id, db)

    settings["thresholds"]["threat_language"]["block"] = 0.70
    saved_policy = parent.update_settings(SettingsInput.model_validate(settings), {"id": user_id})
    parent.create_rule(RuleInput(kind="category", target="threat_language", action="block"), {"id": user_id})

    score = 0.6422476172447205
    monkeypatch.setattr(extension, "classify_text", lambda _text: {
        "status": "classified", "modality": "text", "category": "threat_language",
        "confidence": score, "scores": {"threat_language": score},
        "supported_categories": ["threat_language"], "classifier": "controlled-policy-test",
    })
    device = {"id": device_id, "user_id": user_id}
    request = extension.TextAnalysisInput(
        text="controlled threat-language sample",
        source_url="http://127.0.0.1:8001/threat-only.html",
        event_key="configured-threat-rule-test-01",
    )
    below_block = extension.analyze_text(request, device)
    assert below_block["confidence"] == score
    assert below_block["action"] == "warn"
    assert "below the configured block threshold" in below_block["reason"]
    assert below_block["policy_version"] == parent.get_settings({"id": user_id})["version"]

    settings = parent.get_settings({"id": user_id})
    settings["thresholds"]["threat_language"]["block"] = 0.60
    saved_policy = parent.update_settings(SettingsInput.model_validate(settings), {"id": user_id})
    request.event_key = "configured-threat-rule-test-02"
    above_block = extension.analyze_text(request, device)
    assert above_block["confidence"] == score
    assert above_block["action"] == "block"
    assert above_block["policy_version"] == saved_policy["version"]

    with connection() as db:
        events = db.execute(
            "SELECT action,confidence,policy_version,policy_reason FROM events WHERE user_id=? ORDER BY policy_version",
            (user_id,),
        ).fetchall()
        alerts = db.execute("SELECT severity FROM alerts ORDER BY severity").fetchall()
    assert [(row["action"], row["confidence"]) for row in events] == [("warn", score), ("block", score)]
    assert events[0]["policy_version"] < events[1]["policy_version"]
    assert "block threshold" in events[0]["policy_reason"]
    assert {row["severity"] for row in alerts} == {"warning", "blocked"}

