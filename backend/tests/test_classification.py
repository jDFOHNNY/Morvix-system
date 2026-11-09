from backend.app.database import connection
from backend.app import config
from backend.app.classifiers import (
    ClassifierUnavailable,
    _adapt_videomae_checkpoint,
    _load_image_model,
    _require_model,
    classifier_diagnostics,
    classifier_readiness,
)
from backend.tests.conftest import login, register


def _paired_device(client):
    register(client)
    login(client)
    pair = client.post("/api/v1/devices/pair")
    activated = client.post("/api/v1/extension/activate", json={"pairing_code": pair.json()["pairing_code"]})
    return {"Authorization": f"Bearer {activated.json()['device_token']}"}


def test_missing_local_model_returns_explicit_unavailable_and_does_not_record_content(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEXT_MODEL_PATH", tmp_path / "missing-text-model")
    monkeypatch.setattr("backend.app.classifiers._text_model", None)
    monkeypatch.setattr("backend.app.classifiers._text_tokenizer", None)
    headers = _paired_device(client)
    response = client.post(
        "/api/v1/extension/classify/text",
        headers=headers,
        json={"text": "This must not be stored when no model is available.", "source_url": "https://example.com/post"},
    )
    assert response.status_code == 503
    assert "text model snapshot is not present" in response.json()["detail"]
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0


def test_health_readiness_reports_text_model_state_and_safe_diagnostics(client, tmp_path, monkeypatch):
    import backend.app.classifiers as classifiers

    monkeypatch.setattr(config, "TEXT_MODEL_PATH", tmp_path / "no-text-snapshot")
    monkeypatch.setitem(classifiers._loaded, "text", False)
    monkeypatch.delitem(classifiers._load_failures, "text", raising=False)
    monkeypatch.delitem(classifiers._inference_failures, "text", raising=False)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "ready"
    assert data["classifiers"]["text"] == "missing_weights"
    assert data["classifier_details"]["text"]["status"] == "missing_weights"
    assert data["classifier_details"]["text"]["last_inference"] == "not_failed"
    assert "C:\\Users" not in data["classifier_details"]["text"]["message"]


def test_text_size_and_image_type_validation_happen_before_model_loading(client):
    headers = _paired_device(client)
    oversized = "x" * 20_001
    response = client.post("/api/v1/extension/classify/text", headers=headers, json={"text": oversized})
    assert response.status_code == 413

    unsupported = client.post(
        "/api/v1/extension/classify/image",
        headers=headers,
        files={"file": ("page.html", b"not an image", "text/html")},
    )
    assert unsupported.status_code == 415


def test_empty_and_whitespace_only_text_are_rejected_as_client_errors(client):
    headers = _paired_device(client)
    empty = client.post("/api/v1/extension/classify/text", headers=headers, json={"text": ""})
    whitespace = client.post("/api/v1/extension/classify/text", headers=headers, json={"text": "  \t\n "})

    assert empty.status_code == 422
    assert whitespace.status_code == 422
    assert "non-whitespace" in whitespace.json()["detail"]


def test_text_inference_failure_is_reported_and_does_not_record_an_event(client, monkeypatch):
    headers = _paired_device(client)
    from backend.app.api import extension

    def failed_inference(_text):
        raise ClassifierUnavailable("injected local inference failure")

    monkeypatch.setattr(extension, "classify_text", failed_inference)
    response = client.post(
        "/api/v1/extension/classify/text",
        headers=headers,
        json={"text": "A controlled local test sample", "source_url": "https://example.test"},
    )

    assert response.status_code == 503
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0


def test_normalized_result_policy_and_event_persistence_use_no_raw_content(client, monkeypatch):
    headers = _paired_device(client)
    settings = client.get("/api/v1/settings").json()
    settings["category_actions"]["threat_language"] = "block"
    client.put("/api/v1/settings", json=settings)
    active_policy = client.get("/api/v1/settings").json()

    from backend.app.api import extension

    monkeypatch.setattr(
        extension,
        "classify_text",
        lambda text: {
            "status": "classified",
            "modality": "text",
            "category": "threat_language",
            "confidence": 0.75,
            "scores": {"threat_language": 0.75},
            "supported_categories": ["threat_language"],
            "classifier": "injected-test-adapter",
        },
    )
    request = {"text": "private sample words are not saved", "source_url": "https://sub.example.com/story", "event_key": "same-event-key-01"}
    first = client.post("/api/v1/extension/classify/text", headers=headers, json=request)
    second = client.post("/api/v1/extension/classify/text", headers=headers, json=request)
    assert first.status_code == 200, first.text
    assert first.json()["category"] == "threat_language"
    assert first.json()["confidence"] == 0.75
    assert first.json()["action"] == "warn"  # Below the provisional block threshold.
    assert first.json()["policy_version"] == active_policy["version"]
    assert first.json()["event_id"] == second.json()["event_id"]
    assert client.get("/api/v1/settings").json() == active_policy, "a classification event must not change the active parent policy"
    assert client.get("/api/v1/events").json()["total"] == 1
    assert client.get("/api/v1/alerts").json()["items"][0]["severity"] == "warning"
    with connection() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        values = [str(value) for value in db.execute("SELECT * FROM events").fetchone()]
    assert "raw_text" not in columns and all("private sample words" not in value for value in values)


def test_low_score_text_is_saved_as_allowed_history_across_supported_domains(client, monkeypatch):
    headers = _paired_device(client)
    text = "A harmless fictional story mentions an old cemetery and a stormy night."
    seen_inputs = []

    from backend.app.api import extension

    def classify_same_text(value):
        seen_inputs.append(value)
        return {
            "status": "classified",
            "modality": "text",
            "category": None,
            "confidence": 0.00012,
            "scores": {"threat_language": 0.00012},
            "supported_categories": ["threat_language"],
            "classifier": "isolated-domain-independence-test",
        }

    monkeypatch.setattr(extension, "classify_text", classify_same_text)
    urls = [
        "https://www.gutenberg.org/ebooks/12345",
        "https://en.wikipedia.org/wiki/Example",
        "https://example.org/story",
    ]
    responses = [
        client.post(
            "/api/v1/extension/classify/text",
            headers=headers,
            json={"text": text, "source_url": url, "event_key": f"domain-independence-{index:02d}"},
        )
        for index, url in enumerate(urls)
    ]

    assert all(response.status_code == 200 for response in responses)
    assert seen_inputs == [text, text, text], "The page domain must not alter the text passed to the classifier."
    for response in responses:
        payload = response.json()
        assert payload["category"] == "threat_language"
        assert payload["confidence"] == 0.00012
        assert payload["detected"] is False
        assert payload["action"] == "allow"
        assert payload["event_id"]
        history_item = next(
            item for item in client.get("/api/v1/events").json()["items"]
            if item["id"] == payload["event_id"]
        )
        assert history_item["action"] == "allow"
        assert history_item["category"] == "threat_language"
        assert history_item["confidence"] == 0.00012
        assert history_item["occurred_at"]
        assert history_item["source_domain"] in {"www.gutenberg.org", "en.wikipedia.org", "example.org"}
        assert history_item["classifier_version"] == "isolated-domain-independence-test"

    assert client.get("/api/v1/events").json()["total"] == 3
    assert client.get("/api/v1/dashboard/summary").json()["counts"] == {
        "total": 3, "blocked": 0, "flagged": 0, "allowed": 3, "unread_alerts": 0,
    }
    with connection() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        values = [str(value) for row in db.execute("SELECT * FROM events") for value in row]
    assert "raw_text" not in columns
    assert all(text not in value for value in values)


def test_threat_language_block_rule_flags_64_percent_below_threshold_and_reuses_saved_action(client, monkeypatch):
    headers = _paired_device(client)
    rule_response = client.post("/api/v1/rules", json={
        "kind": "category", "target": "threat_language", "action": "block", "enabled": True,
    })
    assert rule_response.status_code == 201, rule_response.text
    saved_rule = rule_response.json()
    assert (saved_rule["kind"], saved_rule["target"], saved_rule["action"], saved_rule["enabled"]) == (
        "category", "threat_language", "block", True,
    )

    synchronized = client.get("/api/v1/extension/policy", headers=headers).json()
    assert synchronized["policy"]["version"] == client.get("/api/v1/settings").json()["version"]
    assert any(rule["id"] == saved_rule["id"] and rule["action"] == "block" for rule in synchronized["rules"])
    assert synchronized["policy"]["thresholds"]["threat_language"] == {"review": 0.5, "block": 0.9}

    from backend.app.api import extension

    applied_versions = []
    original_ensure_policy = extension.ensure_policy

    def capture_applied_policy(user_id, db):
        policy = original_ensure_policy(user_id, db)
        applied_versions.append(policy["version"])
        return policy

    monkeypatch.setattr(extension, "ensure_policy", capture_applied_policy)
    monkeypatch.setattr(extension, "classify_text", lambda _text: {
        "status": "classified", "modality": "text", "category": "threat_language",
        "confidence": 0.6422476172447205, "scores": {"threat_language": 0.6422476172447205},
        "supported_categories": ["threat_language"], "classifier": "injected-test-adapter",
    })
    request = {
        "text": "controlled threat-language sample", "source_url": "http://127.0.0.1:8001/threat-only.html",
        "event_key": "threat-rule-threshold-event-01",
    }
    flagged = client.post("/api/v1/extension/classify/text", headers=headers, json=request)
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["confidence"] == 0.6422476172447205
    assert flagged.json()["action"] == "warn"
    assert "block threshold" in flagged.json()["reason"]
    assert flagged.json()["policy_version"] == synchronized["policy"]["version"]
    assert applied_versions == [synchronized["policy"]["version"]]

    with connection() as db:
        saved_event = db.execute("SELECT * FROM events WHERE id=?", (flagged.json()["event_id"],)).fetchone()
    assert saved_event["category"] == "threat_language"
    assert saved_event["confidence"] == 0.6422476172447205
    assert saved_event["action"] == flagged.json()["action"] == "warn"
    assert saved_event["policy_version"] == flagged.json()["policy_version"]
    assert saved_event["source_domain"] == "127.0.0.1"
    assert saved_event["policy_reason"] == flagged.json()["reason"]
    assert client.get("/api/v1/dashboard/summary").json()["counts"]["flagged"] == 1
    assert client.get("/api/v1/dashboard/summary").json()["counts"]["blocked"] == 0

    # A reused idempotency key must continue to report its saved result even if
    # the parent's threshold changes before a client retry.
    settings = client.get("/api/v1/settings").json()
    settings["thresholds"]["threat_language"]["block"] = 0.6
    newer_policy = client.put("/api/v1/settings", json=settings).json()
    retry = client.post("/api/v1/extension/classify/text", headers=headers, json=request)
    assert retry.json()["event_id"] == flagged.json()["event_id"]
    assert retry.json()["action"] == "warn"
    assert retry.json()["policy_version"] == flagged.json()["policy_version"]
    assert applied_versions[-1] == newer_policy["version"]


def test_threat_language_64_percent_blocks_when_parent_threshold_allows_it_and_saves_block(client, monkeypatch):
    headers = _paired_device(client)
    rule = client.post("/api/v1/rules", json={
        "kind": "category", "target": "threat_language", "action": "block", "enabled": True,
    }).json()
    settings = client.get("/api/v1/settings").json()
    settings["thresholds"]["threat_language"]["block"] = 0.6
    configured = client.put("/api/v1/settings", json=settings).json()
    synchronized = client.get("/api/v1/extension/policy", headers=headers).json()
    assert synchronized["policy"]["version"] == configured["version"]
    assert any(item["id"] == rule["id"] and item["action"] == "block" for item in synchronized["rules"])

    from backend.app.api import extension

    applied_versions = []
    original_ensure_policy = extension.ensure_policy

    def capture_applied_policy(user_id, db):
        policy = original_ensure_policy(user_id, db)
        applied_versions.append(policy["version"])
        return policy

    monkeypatch.setattr(extension, "ensure_policy", capture_applied_policy)
    monkeypatch.setattr(extension, "classify_text", lambda _text: {
        "status": "classified", "modality": "text", "category": "threat_language",
        "confidence": 0.6422476172447205, "scores": {"threat_language": 0.6422476172447205},
        "supported_categories": ["threat_language"], "classifier": "injected-test-adapter",
    })
    response = client.post("/api/v1/extension/classify/text", headers=headers, json={
        "text": "controlled threat-language sample", "source_url": "http://127.0.0.1:8001/threat-only.html",
        "event_key": "threat-rule-block-event-01",
    })
    assert response.status_code == 200, response.text
    assert response.json()["confidence"] == 0.6422476172447205
    assert response.json()["action"] == "block"
    assert response.json()["policy_version"] == synchronized["policy"]["version"]
    assert applied_versions == [synchronized["policy"]["version"]]
    with connection() as db:
        saved_event = db.execute("SELECT * FROM events WHERE id=?", (response.json()["event_id"],)).fetchone()
        saved_alert = db.execute("SELECT severity FROM alerts WHERE event_id=?", (response.json()["event_id"],)).fetchone()
    assert saved_event["action"] == response.json()["action"] == "block"
    assert saved_event["policy_version"] == response.json()["policy_version"]
    assert saved_event["policy_reason"] == response.json()["reason"]
    assert saved_event["source_domain"] == "127.0.0.1"
    assert saved_alert["severity"] == "blocked"
    summary = client.get("/api/v1/dashboard/summary").json()["counts"]
    assert summary["blocked"] == 1
    assert summary["flagged"] == 0


def test_image_checkpoint_without_documented_label_map_fails_closed(tmp_path, monkeypatch):
    model_path = tmp_path / "image-model"
    model_path.mkdir()
    (model_path / "config.json").write_text('{"num_labels":2}', encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"placeholder")
    monkeypatch.setattr(config, "IMAGE_MODEL_PATH", model_path)

    assert classifier_readiness()["image"] == "incompatible_checkpoint_labels"
    try:
        _load_image_model()
        raise AssertionError("An undocumented label map must not be loaded.")
    except ClassifierUnavailable as error:
        assert "no documented violence label map" in str(error)


def test_text_readiness_and_error_name_missing_ml_packages(tmp_path, monkeypatch):
    import backend.app.classifiers as classifiers

    model_path = tmp_path / "text-model"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        '{"model_type":"bert","num_labels":2,"id2label":{"0":"non_threat","1":"threat"}}',
        encoding="utf-8",
    )
    (model_path / "model.safetensors").write_bytes(b"placeholder")
    (model_path / "vocab.txt").write_text("[PAD]\n[UNK]\n", encoding="utf-8")
    monkeypatch.setattr(config, "TEXT_MODEL_PATH", model_path)
    monkeypatch.setattr(
        classifiers.importlib.util,
        "find_spec",
        lambda package: object() if package == "PIL" else None,
    )

    assert classifier_readiness()["text"] == "install_ml_dependencies"
    try:
        _require_model(model_path, "text")
        raise AssertionError("Missing model runtime packages must be reported.")
    except ClassifierUnavailable as error:
        assert "torch, transformers, safetensors" in str(error)
        assert "requirements-ml.txt" in str(error)


def test_text_readiness_distinguishes_missing_weights_and_invalid_snapshot_files(tmp_path, monkeypatch):
    import backend.app.classifiers as classifiers

    model_path = tmp_path / "text-model"
    monkeypatch.setattr(config, "TEXT_MODEL_PATH", model_path)
    assert classifier_readiness()["text"] == "missing_weights"
    diagnostics = classifier_diagnostics()["text"]
    assert diagnostics["status"] == "missing_weights"
    assert "safetensors" in diagnostics["message"] or "snapshot" in diagnostics["message"]
    assert "C:\\Users" not in diagnostics["message"]

    model_path.mkdir()
    (model_path / "config.json").write_text(
        '{"model_type":"bert","num_labels":2,"id2label":{"0":"non_threat","1":"threat"}}',
        encoding="utf-8",
    )
    (model_path / "model.safetensors").write_bytes(b"placeholder")
    assert classifiers._text_snapshot_problem()[0] == "invalid_model_files"
    assert classifier_readiness()["text"] == "invalid_model_files"


def test_text_model_loading_failure_is_reported_without_exposing_exception_details(tmp_path, monkeypatch):
    import builtins
    import backend.app.classifiers as classifiers

    model_path = tmp_path / "text-model"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        '{"model_type":"bert","num_labels":2,"id2label":{"0":"non_threat","1":"threat"}}',
        encoding="utf-8",
    )
    (model_path / "model.safetensors").write_bytes(b"placeholder")
    (model_path / "vocab.txt").write_text("[PAD]\n[UNK]\n", encoding="utf-8")
    monkeypatch.setattr(config, "TEXT_MODEL_PATH", model_path)
    monkeypatch.setattr(classifiers, "_missing_ml_dependencies", lambda: [])
    monkeypatch.setattr(classifiers, "_text_model", None)
    monkeypatch.setattr(classifiers, "_text_tokenizer", None)
    monkeypatch.setitem(classifiers._loaded, "text", False)
    original_import = builtins.__import__

    def fail_transformers(name, *args, **kwargs):
        if name == "transformers":
            raise RuntimeError("private loader internals")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_transformers)
    try:
        classifiers._load_text_model()
        raise AssertionError("An unavailable loader must fail clearly.")
    except ClassifierUnavailable as error:
        assert "could not be loaded" in str(error)
        assert "private loader internals" not in str(error)
    try:
        assert classifier_readiness()["text"] == "loading_failed"
    finally:
        classifiers._load_failures.pop("text", None)


def test_text_inference_failure_is_reported_as_unavailable(tmp_path, monkeypatch):
    import builtins
    import types
    from contextlib import nullcontext
    import backend.app.classifiers as classifiers

    class BrokenModel:
        def __call__(self, **_kwargs):
            raise RuntimeError("synthetic inference failure")

    fake_torch = types.SimpleNamespace(inference_mode=nullcontext)
    original_import = builtins.__import__

    def import_fake_torch(name, *args, **kwargs):
        if name == "torch":
            return fake_torch
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_fake_torch)
    monkeypatch.setattr(classifiers, "_load_text_model", lambda: (BrokenModel(), lambda *_a, **_k: {"input_ids": object()}))
    monkeypatch.setitem(classifiers._loaded, "text", True)
    try:
        classifiers.classify_text("harmless synthetic text")
        raise AssertionError("The synthetic inference failure must not return a classification.")
    except ClassifierUnavailable as error:
        assert "could not complete inference" in str(error)
    diagnostics = classifier_diagnostics()["text"]
    assert diagnostics["status"] == "inference_failed"
    assert diagnostics["last_inference"] == "failed"
    classifiers._inference_failures.pop("text", None)


def test_videomae_checkpoint_bias_mapping_is_complete_and_strict():
    query_bias = object()
    value_bias = object()
    classifier_weight = object()
    mapped = _adapt_videomae_checkpoint(
        {
            "videomae.encoder.layer.0.attention.attention.query.bias": query_bias,
            "videomae.encoder.layer.0.attention.attention.value.bias": value_bias,
            "videomae.encoder.layer.0.attention.attention.key.bias": object(),
            "classifier.weight": classifier_weight,
        },
        {
            "videomae.encoder.layer.0.attention.attention.q_bias",
            "videomae.encoder.layer.0.attention.attention.v_bias",
            "classifier.weight",
        },
    )
    assert mapped == {
        "videomae.encoder.layer.0.attention.attention.q_bias": query_bias,
        "videomae.encoder.layer.0.attention.attention.v_bias": value_bias,
        "classifier.weight": classifier_weight,
    }

    try:
        _adapt_videomae_checkpoint({"classifier.weight": classifier_weight}, {"classifier.weight", "classifier.bias"})
        raise AssertionError("A partial checkpoint must not be loaded.")
    except ClassifierUnavailable as error:
        assert "strict weight validation" in str(error)
