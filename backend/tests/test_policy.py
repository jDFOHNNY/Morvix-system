import pytest

from backend.app.policies import evaluate_policy, matching_rule


def test_website_rule_precedes_category_action_and_matches_subdomains():
    policy = {
        "protection_enabled": True,
        "modalities": {"text": True, "image": True, "video": True},
        "category_actions": {"violence": "warn"},
        "thresholds": {"violence": {"review": 0.5, "block": 0.9}},
    }
    rules = [{"id": "site", "kind": "website", "target": "example.com", "action": "allow", "enabled": True}]
    decision = evaluate_policy(policy, rules, "image", "violence", 0.99, "https://news.example.com/photo")
    assert decision["action"] == "allow"
    assert decision["rule_id"] == "site"
    assert matching_rule(rules, "notexample.com", "website") is None


def test_low_confidence_block_is_downgraded_to_warning():
    policy = {
        "protection_enabled": True,
        "modalities": {"text": True},
        "category_actions": {"threat_language": "block"},
        "thresholds": {"threat_language": {"review": 0.5, "block": 0.9}},
    }
    decision = evaluate_policy(policy, [], "text", "threat_language", 0.75, "https://example.com")
    assert decision["action"] == "warn"
    assert "block threshold" in decision["reason"]


def test_review_and_block_thresholds_are_inclusive_at_their_boundaries():
    policy = {
        "protection_enabled": True,
        "modalities": {"text": True},
        "category_actions": {"threat_language": "block"},
        "thresholds": {"threat_language": {"review": 0.5, "block": 0.9}},
    }

    at_review = evaluate_policy(policy, [], "text", "threat_language", 0.5, "https://example.com")
    at_block = evaluate_policy(policy, [], "text", "threat_language", 0.9, "https://example.com")

    assert at_review["action"] == "warn"
    assert at_block["action"] == "block"


def test_confidence_thresholds_do_not_upgrade_parent_allow_or_warn_actions():
    policy = {
        "protection_enabled": True,
        "modalities": {"text": True},
        "category_actions": {"threat_language": "allow"},
        "thresholds": {"threat_language": {"review": 0.5, "block": 0.9}},
    }
    assert evaluate_policy(policy, [], "text", "threat_language", 0.99, "https://example.com")["action"] == "allow"
    policy["category_actions"]["threat_language"] = "warn"
    assert evaluate_policy(policy, [], "text", "threat_language", 0.99, "https://example.com")["action"] == "warn"


def test_invalid_or_missing_saved_thresholds_are_not_silently_replaced_with_defaults():
    policy = {
        "protection_enabled": True,
        "modalities": {"text": True},
        "category_actions": {"threat_language": "block"},
        "thresholds": {"threat_language": {"review": 0.5}},
    }
    with pytest.raises(ValueError, match="missing or invalid"):
        evaluate_policy(policy, [], "text", "threat_language", 0.75, "https://example.com")

    policy["thresholds"]["threat_language"] = {"review": 0.8, "block": 0.7}
    with pytest.raises(ValueError, match="supported range or order"):
        evaluate_policy(policy, [], "text", "threat_language", 0.85, "https://example.com")

