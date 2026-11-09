# MORVIX Architecture

**Status:** implementation baseline, pending requirements review. The SRS is Draft 1.0; provisional choices below are not adviser-approved requirements.

## System boundary

MORVIX is a local course-project deployment with three clients/components: a parent dashboard, a Chromium Manifest V3 extension, and a Python/FastAPI backend. SQLite stores account-scoped policies and event metadata. Local model adapters receive content transiently, return normalized scores, and never persist raw page text, images, or video. The extension analyzes only content it can access on supported pages. No native mobile app, general device surveillance, third-party platform server moderation, email/push notification delivery, or cloud moderation service is in scope.

```text
Parent browser ── dashboard (HTML/CSS/JS) ──┐
                                             ├── FastAPI /api/v1 ── SQLite
Protected browser ── MV3 extension ─────────┘          │
          └── cached signed-by-transport policy         └── local classifier adapters
```

The extension submits accessible text and supported media to the same backend policy/classification path used by the dashboard. The backend authenticates the parent through an HTTP-only session cookie and the extension through a separate revocable device credential. Event ownership is derived server-side from the authenticated user or device, never from a caller-supplied account ID.

## Components and responsibilities

| Component | Responsibility |
| --- | --- |
| `backend/app/main.py` and `backend/app/api/` | FastAPI app, versioned API, static dashboard hosting, request validation, auth dependencies, error mapping, health/readiness. |
| `backend/app/database.py` | SQLite initialization, schema version marker, foreign keys, parameterized queries and transactions. |
| `backend/app/security.py` | Password hashing, expiring dashboard sessions, extension-token hashing and credential revocation. |
| `backend/app/policies.py` | One effective-policy evaluator; website rules override category actions; disabled protection allows content and records no enforcement. |
| `backend/app/classifiers.py` and `backend/app/video.py` | Replaceable local text and image adapters, plus bounded 16-frame inference using a dedicated VideoMAE video model. Missing or incompatible weights produce an explicit unavailable result, never a fabricated score. |
| `backend/app/events.py` | Metadata-only event persistence, alert creation for warn/block, deduplication support and review state. |
| `web_dashboard/` | Warm peach/cream desktop dashboard, login, real API calls, dashboard/history/alerts/rules/settings views, empty/loading/error states. |
| `browser_extension/` | MV3 popup, service worker, pairing, cached policy, conservative extraction, classification requests, supported warning/block overlays and bounded retries. |

## Trust and data flow

1. A parent creates an account and signs in. Passwords are salted and hashed; a random session token is returned only in an HTTP-only, SameSite cookie and only its digest is stored.
2. The parent starts pairing in dashboard settings. A short-lived, one-use pairing code is exchanged for a random device credential. The server stores only its digest and binds it to that parent. The extension stores the credential in extension-local storage; revocation invalidates it server-side.
3. The extension polls for policy updates and sends a heartbeat. Policy responses include a monotonically increasing version and update timestamp; the extension only replaces its cached policy after validation.
4. Accessible content is sent over the local API for in-memory inference. The server validates modality and size, classifies locally, evaluates the parent's effective policy, and persists only event metadata (category, score, model version, source host, action, timestamp, review state). Raw content is discarded after the request.
5. The dashboard loads counts, events, alerts, devices and policy from authenticated endpoints. Every query scopes by the authenticated owner.

## Data and policy rules

- SQLite is the provisional local database; schema upgrades use an explicit `schema_version` table and ordered migrations.
- Timestamps are stored as UTC ISO-8601 and formatted for the user's browser locale.
- Website-specific rules take precedence over category actions; if no website rule matches, enabled category policy applies. Disabled protection and explicitly allowed domains permit access. Uncertain or unavailable classification is not treated as confirmed safe; the extension preserves access with a visible uncertainty warning and does not fabricate an event score.
- Defaults for taxonomy, confidence thresholds, category actions, sampling interval, retention, and the supported browser remain provisional (see `DECISIONS_AND_LIMITATIONS.md`).
- History retention is metadata-only. A user-triggered account deletion/reset flow will remove dependent data; no automatic expiry period is selected until team/adviser confirmation.

## API shape

The stable API prefix is `/api/v1`. Endpoint details and schemas are maintained in `docs/API.md` as implementation proceeds; interactive OpenAPI documentation is served by FastAPI at `/docs` in development. The API separates parent session endpoints from extension credential endpoints. Dashboard endpoints include registration/login/logout/current user, summary, history/search/pagination/review, alerts/review, rules CRUD, settings, extension pairing/status/revocation. Extension endpoints include pairing exchange, heartbeat, policy sync, and text/image/video classification plus event submission. Health and classifier readiness are separate so a healthy backend does not imply that model weights are installed.

## Security and privacy controls

- PBKDF2-HMAC password hashing (stdlib) with per-user salt; constant-time verification.
- Opaque random sessions and extension credentials; only SHA-256 digests are persisted. Session expiration and device revocation are enforced server-side.
- Account ownership is always taken from authenticated credentials. SQL uses parameters and foreign keys; uploads have strict byte/type/time/frame limits and temporary files are removed.
- Production secrets and HTTPS cookie settings are environment-controlled. Development CORS is limited to documented local dashboard origins. Extension host access is restricted to configured backend and active tabs.
- Content payloads exist only in request memory/temp files. Detection history keeps host, modality, categories, confidence, classifier version, policy outcome and timestamps, not raw content or full URL query strings.
- External moderation APIs are prohibited. Model artifact downloads are setup-time only; runtime inference is local.

## Verification boundaries

Automated backend/API/policy tests live in `backend/tests/`; browser-specific manual checks live in `docs/ACCEPTANCE_TESTS.md`. The supported extension workflow is not considered verified until loaded and exercised in Chromium. Model runtime readiness is checked by strict loading and local inference; task fit and performance are not considered validated until the model is evaluated against a held-out, appropriately labeled set. `BUILD_STATUS.md` is the source of truth for what has actually been run.
