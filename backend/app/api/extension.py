"""Device pairing, policy synchronization and authenticated event reporting."""

from __future__ import annotations

import json
import secrets
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app import config
from backend.app.classifiers import ClassifierUnavailable, classify_image, classify_text, classifier_readiness, prepare_classifier
from backend.app.database import connection
from backend.app.events import record_detection
from backend.app.policies import ensure_policy, get_rules, matching_rule, normalize_domain, evaluate_policy, thresholds_for_category
from backend.app.security import get_device, token_digest
from backend.app.time_utils import utc_now
from backend.app.video import classify_video

router = APIRouter(prefix="/api/v1/extension", tags=["browser extension"])


class ActivateInput(BaseModel):
    pairing_code: str = Field(min_length=8, max_length=40)


class TextAnalysisInput(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    source_url: str | None = Field(default=None, max_length=2048)
    event_key: str | None = Field(default=None, min_length=8, max_length=100)


class OfflineEventInput(BaseModel):
    modality: str = Field(pattern="^(text|image|video)$")
    source_url: str = Field(min_length=1, max_length=2048)
    event_key: str = Field(min_length=8, max_length=100)


def _policy_snapshot(user_id: str, db) -> dict:
    policy = ensure_policy(user_id, db)
    return {
        "policy": policy,
        "rules": get_rules(user_id, db),
        "cache_max_age_minutes": config.POLICY_CACHE_MAX_AGE_MINUTES,
    }


@router.post("/activate")
def activate(payload: ActivateInput):
    credential = secrets.token_urlsafe(32)
    now = utc_now()
    with connection() as db:
        row = db.execute(
            "SELECT id,user_id,label FROM devices WHERE pairing_code_hash=? AND pairing_expires_at>? AND paired_at IS NULL AND revoked_at IS NULL",
            (token_digest(payload.pairing_code.strip()), now),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="Pairing code is invalid, expired, or already used.")
        db.execute(
            "UPDATE devices SET token_hash=?,pairing_code_hash=NULL,pairing_expires_at=NULL,paired_at=?,last_seen_at=? WHERE id=?",
            (token_digest(credential), now, now, row["id"]),
        )
        snapshot = _policy_snapshot(row["user_id"], db)
    return {"device_id": row["id"], "label": row["label"], "device_token": credential, **snapshot, "last_synced_at": now}


@router.get("/policy")
def synchronize_policy(device: dict = Depends(get_device)):
    now = utc_now()
    with connection() as db:
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
        snapshot = _policy_snapshot(device["user_id"], db)
    return {"device_id": device["id"], **snapshot, "last_synced_at": now}


@router.post("/heartbeat")
def heartbeat(device: dict = Depends(get_device)):
    now = utc_now()
    with connection() as db:
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
    return {"device_id": device["id"], "connected": True, "last_seen_at": now}


@router.get("/readiness")
def classifier_upload_readiness(
    modality: str = Query(pattern="^(image|video)$"),
    device: dict = Depends(get_device),
):
    """Prepare a media classifier before the extension fetches and uploads page media."""
    reason = None
    ready = False
    try:
        prepare_classifier(modality)
        ready = True
    except ClassifierUnavailable as exc:
        reason = str(exc)
    max_upload_bytes = config.MAX_IMAGE_BYTES if modality == "image" else config.MAX_VIDEO_BYTES
    return {
        "modality": modality,
        "ready": ready,
        "classifier_status": classifier_readiness()[modality],
        "reason": reason,
        "max_upload_bytes": max_upload_bytes,
    }


@router.post("/offline-events", status_code=201)
def submit_offline_event(payload: OfflineEventInput, device: dict = Depends(get_device)):
    """Accept only still-authorized, cached website warn/block decisions; no scores or raw content."""
    domain = normalize_domain(payload.source_url)
    now = utc_now()
    with connection() as db:
        policy = ensure_policy(device["user_id"], db)
        if not policy["protection_enabled"]:
            raise HTTPException(status_code=409, detail="Protection is no longer enabled.")
        rule = matching_rule(get_rules(device["user_id"], db), domain, "website")
        if rule is None or rule["action"] not in {"warn", "block"}:
            raise HTTPException(status_code=409, detail="The cached website rule is no longer active.")
        event = record_detection(
            db, user_id=device["user_id"], device_id=device["id"], modality=payload.modality,
            category="website_rule", confidence=None, action=rule["action"], source_domain=domain,
            classifier_version=None, policy_reason=f"Offline application of website rule for {rule['target']}.",
            policy_version=policy["version"], event_key=payload.event_key,
        )
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
    return {"id": event["id"], "action": event["action"], "stored": True}


@router.get("/status")
def extension_status(device: dict = Depends(get_device)):
    now = utc_now()
    with connection() as db:
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
        snapshot = _policy_snapshot(device["user_id"], db)
    return {"device_id": device["id"], "connected": True, **snapshot, "last_seen_at": now}


def _analyze(device: dict, modality: str, source_url: str | None, event_key: str | None, infer):
    domain = normalize_domain(source_url)
    with connection() as db:
        policy = ensure_policy(device["user_id"], db)
        rules = get_rules(device["user_id"], db)
        if not policy["protection_enabled"]:
            return {"status": "skipped", "modality": modality, "category": None, "confidence": None, "action": "allow", "reason": "Protection is disabled.", "event_id": None, "policy_version": policy["version"]}
        site_rule = matching_rule(rules, domain, "website")
        if site_rule:
            now = utc_now()
            db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
            event = None
            if site_rule["action"] in {"warn", "block"}:
                event = record_detection(
                    db, user_id=device["user_id"], device_id=device["id"], modality=modality,
                    category="website_rule", confidence=None, action=site_rule["action"],
                    source_domain=domain, classifier_version=None,
                    policy_reason=f"Website rule for {site_rule['target']}.",
                    policy_version=policy["version"], event_key=event_key,
                )
            return {
                "status": "policy_applied", "modality": modality, "category": "website_rule", "confidence": None,
                "action": event["action"] if event else site_rule["action"],
                "reason": event["policy_reason"] if event else f"Website rule for {site_rule['target']}.",
                "event_id": event["id"] if event else None,
                "policy_version": event["policy_version"] if event else policy["version"],
            }
        if not policy["modalities"].get(modality, False):
            return {"status": "skipped", "modality": modality, "category": None, "confidence": None, "action": "allow", "reason": f"{modality.title()} protection is disabled.", "event_id": None, "policy_version": policy["version"]}
        try:
            result = infer()
        except ClassifierUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        scores = result.get("scores", {})
        supported = result.get("supported_categories", [])
        detected_category = None
        detected_score = 0.0
        for category in supported:
            score = float(scores.get(category, 0.0))
            review_threshold = thresholds_for_category(policy, category)["review"]
            if score >= review_threshold and (detected_category is None or score > detected_score):
                detected_category, detected_score = category, score
        now = utc_now()
        db.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (now, device["id"]))
        if detected_category is None:
            # A completed classifier result is a real monitoring outcome even
            # when its score is below the parent's review threshold. Keep the
            # category/score and final allow decision in metadata-only history.
            # If a classifier advertises no supported category, there is no
            # category decision to record.
            candidate = max(supported, key=lambda item: float(scores.get(item, 0.0))) if supported else None
            if candidate is None:
                return {
                    **result, "category": None, "confidence": None, "detected": False, "action": "allow",
                    "reason": "The classifier returned no supported category score.",
                    "event_id": None, "policy_version": policy["version"],
                }
            score = float(scores.get(candidate, 0.0))
            decision = evaluate_policy(policy, rules, modality, candidate, score, source_url)
            event = record_detection(
                db, user_id=device["user_id"], device_id=device["id"], modality=modality,
                category=candidate, confidence=score, action=decision["action"],
                source_domain=domain, classifier_version=result.get("classifier"),
                policy_reason=decision["reason"], policy_version=policy["version"], event_key=event_key,
            )
            return {
                **result, "category": candidate, "confidence": score, "detected": False,
                "action": event["action"], "reason": event["policy_reason"],
                "event_id": event["id"], "policy_version": event["policy_version"],
            }
        decision = evaluate_policy(policy, rules, modality, detected_category, detected_score, source_url)
        event = record_detection(
            db, user_id=device["user_id"], device_id=device["id"], modality=modality,
            category=detected_category, confidence=detected_score, action=decision["action"],
            source_domain=domain, classifier_version=result.get("classifier"),
            policy_reason=decision["reason"], policy_version=policy["version"], event_key=event_key,
        )
        return {
            **result, "category": detected_category, "confidence": detected_score, "detected": True,
            # Idempotent event keys return the existing row. Keep the response and
            # extension intervention tied to that persisted final action/reason.
            "action": event["action"], "reason": event["policy_reason"], "event_id": event["id"],
            "policy_version": event["policy_version"],
        }


@router.post("/classify/text")
def analyze_text(payload: TextAnalysisInput, device: dict = Depends(get_device)):
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Text must contain at least one non-whitespace character.")
    if len(payload.text) > config.MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail=f"Text exceeds the {config.MAX_TEXT_CHARS:,}-character processing limit.")
    return _analyze(device, "text", payload.source_url, payload.event_key, lambda: classify_text(payload.text))


@router.post("/classify/image")
def analyze_image(
    file: UploadFile = File(...),
    source_url: str | None = Query(default=None, max_length=2048),
    event_key: str | None = Query(default=None, min_length=8, max_length=100),
    device: dict = Depends(get_device),
):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Supported image uploads are JPEG, PNG and WebP.")
    content = file.file.read(config.MAX_IMAGE_BYTES + 1)
    if len(content) > config.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit.")
    try:
        return _analyze(device, "image", source_url, event_key, lambda: classify_image(content))
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    finally:
        file.file.close()


@router.post("/classify/video")
def analyze_video(
    file: UploadFile = File(...),
    source_url: str | None = Query(default=None, max_length=2048),
    event_key: str | None = Query(default=None, min_length=8, max_length=100),
    device: dict = Depends(get_device),
):
    if file.content_type not in {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}:
        raise HTTPException(status_code=415, detail="Supported video uploads are MP4, WebM, MOV and AVI.")
    content = file.file.read(config.MAX_VIDEO_BYTES + 1)
    if len(content) > config.MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="Video exceeds the configured upload limit.")
    try:
        return _analyze(device, "video", source_url, event_key, lambda: classify_video(content, file.content_type or ""))
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    finally:
        file.file.close()

