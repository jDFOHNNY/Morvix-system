"""Small environment-backed configuration layer; no secrets are hardcoded."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _path_setting(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


DATABASE_PATH = _path_setting("MORVIX_DATABASE_PATH", "data/morvix.db")
SESSION_HOURS = max(1, int(os.getenv("MORVIX_SESSION_HOURS", "12")))
COOKIE_SECURE = os.getenv("MORVIX_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
GOOGLE_CLIENT_ID = os.getenv("MORVIX_GOOGLE_CLIENT_ID", "").strip()
SMTP_HOST = os.getenv("MORVIX_SMTP_HOST", "").strip()
SMTP_PORT = max(1, min(65535, int(os.getenv("MORVIX_SMTP_PORT", "587"))))
SMTP_USERNAME = os.getenv("MORVIX_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("MORVIX_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("MORVIX_EMAIL_FROM", "").strip()
SMTP_USE_SSL = os.getenv("MORVIX_SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
CORS_ORIGINS = [
    value.strip()
    for value in os.getenv(
        "MORVIX_CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",")
    if value.strip()
]
MODEL_ROOT = _path_setting("MORVIX_MODEL_ROOT", "models")
TEXT_MODEL_PATH = _path_setting("MORVIX_TEXT_MODEL", "models/text/toxic-bert")
IMAGE_MODEL_PATH = _path_setting(
    "MORVIX_IMAGE_MODEL", "models/image/vit-base-violence-detection"
)
VIDEO_MODEL_PATH = _path_setting(
    "MORVIX_VIDEO_MODEL", "models/video/videomae-violence-detector"
)
MAX_TEXT_CHARS = min(100_000, max(100, int(os.getenv("MORVIX_MAX_TEXT_CHARS", "20000"))))
MAX_IMAGE_BYTES = min(25_000_000, max(1024, int(os.getenv("MORVIX_MAX_IMAGE_BYTES", "8388608"))))
MAX_VIDEO_BYTES = min(100_000_000, max(1024, int(os.getenv("MORVIX_MAX_VIDEO_BYTES", "26214400"))))
MAX_VIDEO_SECONDS = min(600, max(1, int(os.getenv("MORVIX_MAX_VIDEO_SECONDS", "180"))))
VIDEO_SAMPLE_SECONDS = min(30, max(1, int(os.getenv("MORVIX_VIDEO_SAMPLE_SECONDS", "2"))))
VIDEO_MAX_FRAMES = min(120, max(1, int(os.getenv("MORVIX_VIDEO_MAX_FRAMES", "24"))))
# Provisional local-client cache lifetime. Team/adviser confirmation is recorded
# in DECISIONS_AND_LIMITATIONS.md; clamp it to one minute through seven days.
POLICY_CACHE_MAX_AGE_MINUTES = min(10_080, max(1, int(os.getenv("MORVIX_POLICY_CACHE_MAX_AGE_MINUTES", "1440"))))

