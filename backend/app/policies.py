"""Single policy representation and deterministic precedence evaluator."""

from __future__ import annotations

import json
import math
from urllib.parse import urlsplit

from backend.app.database import connection

DEFAULT_MODALITIES = {"text": True, "image": True, "video": True}
DEFAULT_ACTIONS = {"violence": "warn", "threat_language": "warn", "self_harm_indicators": "warn"}
DEFAULT_THRESHOLDS = {
    category: {"review": 0.50, "block": 0.90} for category in DEFAULT_ACTIONS
}


def ensure_policy(user_id: str, db=None) -> dict:
    if db is None:
        with connection() as owned:
            return ensure_policy(user_id, owned)
    row = db.execute("SELECT * FROM policies WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        from backend.app.time_utils import utc_now

        db.execute(
            "INSERT INTO policies(user_id,protection_enabled,modalities_json,category_actions_json,thresholds_json,version,updated_at) "
            "VALUES(?,1,?,?,?,1,?)",
            (user_id, json.dumps(DEFAULT_MODALITIES), json.dumps(DEFAULT_ACTIONS), json.dumps(DEFAULT_THRESHOLDS), utc_now()),
        )
        row = db.execute("SELECT * FROM policies WHERE user_id=?", (user_id,)).fetchone()
    return policy_dict(row)


def policy_dict(row) -> dict:
    return {
        "protection_enabled": bool(row["protection_enabled"]),
        "modalities": json.loads(row["modalities_json"]),
        "category_actions": json.loads(row["category_actions_json"]),
        "thresholds": json.loads(row["thresholds_json"]),
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


def get_rules(user_id: str, db=None) -> list[dict]:
    if db is None:
        with connection() as owned:
            return get_rules(user_id, owned)
    rows = db.execute(
        "SELECT id,kind,target,action,enabled,created_at,updated_at FROM rules WHERE user_id=? ORDER BY kind,target COLLATE NOCASE",
        (user_id,),
    ).fetchall()
    return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value if "://" in value else f"//{value}")
    domain = (parsed.hostname or "").strip(".").lower()
    return domain or None


def matching_rule(rules: list[dict], domain: str | None, kind: str, target: str | None = None) -> dict | None:
    candidates = []
    for rule in rules:
        if not rule.get("enabled") or rule["kind"] != kind:
            continue
        if kind == "category":
            if rule["target"].lower() == (target or "").lower():
                candidates.append((len(rule["target"]), rule))
        else:
            candidate_domain = normalize_domain(rule["target"])
            if domain and candidate_domain and (domain == candidate_domain or domain.endswith("." + candidate_domain)):
                candidates.append((len(candidate_domain), rule))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def thresholds_for_category(policy: dict, category: str) -> dict[str, float]:
    """Read a complete saved threshold pair; invalid policy data must not be defaulted."""
    try:
        values = policy["thresholds"][category]
        review, block = float(values["review"]), float(values["block"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Saved {category} thresholds are missing or invalid.") from exc
    if (
        not math.isfinite(review) or not math.isfinite(block) or
        not 0.0 <= review <= block <= 1.0
    ):
        raise ValueError(f"Saved {category} thresholds are outside the supported range or order.")
    return {"review": review, "block": block}


def evaluate_policy(policy: dict, rules: list[dict], modality: str, category: str, confidence: float, source_url: str | None) -> dict:
    domain = normalize_domain(source_url)
    if not policy["protection_enabled"]:
        return {"action": "allow", "reason": "Protection is disabled."}
    site_rule = matching_rule(rules, domain, "website")
    if site_rule:
        return {"action": site_rule["action"], "reason": f"Website rule for {site_rule['target']}.", "rule_id": site_rule["id"]}
    if not policy["modalities"].get(modality, False):
        return {"action": "allow", "reason": f"{modality.title()} protection is disabled."}
    category_rule = matching_rule(rules, domain, "category", category)
    configured = category_rule["action"] if category_rule else policy["category_actions"].get(category, "warn")
    thresholds = thresholds_for_category(policy, category)
    if confidence < thresholds["review"]:
        return {"action": "allow", "reason": "Score is below the configured review threshold."}
    action = configured
    reason = "Category action from a protection rule." if category_rule else "Category action from parent settings."
    if action == "block" and confidence < thresholds["block"]:
        return {"action": "warn", "reason": "Score is below the configured block threshold; flagged for review."}
    return {"action": action, "reason": reason, **({"rule_id": category_rule["id"]} if category_rule else {})}

