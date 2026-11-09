# MORVIX API Contract

The server hosts the parent dashboard and exposes a versioned JSON API at `/api/v1`. Dashboard calls use an HTTP-only `morvix_session` cookie. Extension calls use `Authorization: Bearer <device_token>`. Account and device ownership are resolved from those credentials; clients cannot choose an owner ID.

Interactive OpenAPI docs are available at `/docs` during local development.

## Health

| Method / path | Auth | Purpose |
| --- | --- | --- |
| `GET /health/live` | None | Process liveness only. |
| `GET /health/ready` | None | Database state, the legacy per-modality `classifiers` status map, and sanitized `classifier_details`. Text details distinguish missing weights, invalid/incomplete files, missing dependencies, load failure, initialized state, and last inference failure. No private absolute paths or tracebacks are returned. Database `status: ready` does not imply that a classifier is ready. |

## Parent account

| Method / path | Purpose |
| --- | --- |
| `POST /auth/register` | Create a parent with `name`, `email`, `password` (10–128 chars); registration does not log in automatically. |
| `POST /auth/login` | Verify credentials and set the HTTP-only session cookie. |
| `GET /auth/google/config` | Report Google sign-in availability and issue a short-lived CSRF token when Google and SMTP email notification settings are configured. |
| `POST /auth/google` | Verify a Google ID token, send a parent-account confirmation to a first-time Google identity, create/link the account identity, and set the HTTP-only session cookie. Requires `MORVIX_GOOGLE_CLIENT_ID` and working SMTP settings. |
| `POST /auth/logout` | Revoke the current session and clear cookie. |
| `GET /auth/me` | Return current account identity. |

## Dashboard data

| Method / path | Purpose |
| --- | --- |
| `GET /dashboard/summary` | Real 30-day action counts, recent events, device connection, modality/category aggregates and unread alert count. `model_performance` remains null until validated results exist. |
| `GET /events` | Paginated event history. Filters: `search`, `modality`, `category`, `action`, `domain`, `date_from`, `date_to`, `page`, `page_size`. Date values are ISO-8601. |
| `GET /events/{id}` | Read an owner-scoped event. |
| `PATCH /events/{id}/review` | Mark an event reviewed. |
| `GET /alerts?unread_only=true` | List alerts for flagged/blocked records. |
| `PATCH /alerts/{id}/review` | Mark alert and linked event reviewed. |

## Rules, settings and devices

| Method / path | Purpose |
| --- | --- |
| `GET /rules` | List website and candidate-category rules. |
| `POST /rules` | Create `{kind, target, action, enabled}`. `kind` is `website` or `category`; `action` is `allow`, `warn`, or `block`. |
| `PUT /rules/{id}` | Replace a rule. |
| `DELETE /rules/{id}` | Delete a rule. |
| `GET /settings` | Read global protection, modality switches, category actions, thresholds and policy version. |
| `PUT /settings` | Replace those settings; successful updates increment policy version. |
| `POST /devices/pair?label=...` | Issue a one-time 5-minute pairing code to an authenticated parent. |
| `GET /devices` | List paired/pending devices and connection state. |
| `DELETE /devices/{id}` | Revoke an extension credential. |

## Extension

| Method / path | Auth | Purpose |
| --- | --- | --- |
| `POST /extension/activate` | Pairing code | Consume a one-time code; returns device token once and the current policy snapshot. |
| `GET /extension/policy` | Device token | Heartbeat and retrieve the current policy/rules/version. |
| `POST /extension/heartbeat` | Device token | Update last-seen. |
| `GET /extension/status` | Device token | Current protection and connection status. |
| `POST /extension/offline-events` | Device token | Persist a cached website-rule decision only if the same enabled `warn`/`block` rule remains active; accepts `{modality, source_url, event_key}` and stores host metadata only. |
| `POST /extension/classify/text` | Device token | Classify bounded accessible text locally, evaluate policy, and persist the final action for each completed result with a supported category, including below-review Allow outcomes. |
| `POST /extension/classify/image` | Device token | Analyze an allowed image upload. Multipart `file`; optional `source_url`. |
| `POST /extension/classify/video` | Device token | Analyze a bounded video by frame sampling. Multipart `file`; optional `source_url`. |

Classification responses use a normalized shape with `status`, `modality`, `category`, `confidence`, `classifier`, `action`, `reason`, `policy_version`, and `event_id` when an event is saved. A completed result with a supported category is saved as metadata even when its score is below review and its final action is Allow; only Warn and Block outcomes create alerts. Requests preempted by disabled protection, disabled modality, or a matching website rule do not create a category-classification record. The applied version is the version loaded by the backend for that request; each saved event stores the same version. Reusing an event key returns the original event's action, reason, and policy version. A missing/unavailable model returns an explicit service error and never a guessed category or score. Raw text and media are not stored. Events created before the policy-version migration show no recorded policy version.

The extension stores its device token and most recent policy in extension-local storage. It requests site access one website at a time from the popup, reads rendered text up to 20,000 characters, and checks at most five visible same-origin images and one same-origin video per page load. Media uploads are capped at 25 MiB in the extension; backend limits and video frame/duration limits also apply. Cross-origin media, browser-internal pages, and protected/DRM content are skipped. A local backend outage preserves cached website rules; new classifier checks show an uncertainty notice and keep the page open. Cached website-rule events are queued and server-revalidated before persistence. The image endpoint currently returns an explicit unavailable response because no compatible image checkpoint is configured; video uses the separate local VideoMAE model and has not been evaluated on MORVIX data.

## Candidate categories and actions

Internal category keys are `violence`, `threat_language`, and `self_harm_indicators`. The current text model exposes only the Jigsaw `threat` output, mapped to `threat_language`; it does not classify graphic violence or self-harm. The image classifier is unavailable because its checkpoint has no documented label map, and the separate VideoMAE violence candidate has not been evaluated for MORVIX. These configured categories do not indicate that every modality can detect them. When protection is enabled, a matching website rule is evaluated first and bypasses category scoring. Otherwise, a category rule overrides the parent category action, while parent-configured confidence thresholds still apply: below review is allowed; at or above review, the requested action is retained except that Block is flagged below the block threshold and remains Block at or above it. Thresholds do not upgrade Warn or Allow actions. Thus, a category rule set to Block does not bypass the confidence gate.

## Error behavior

Validation errors return HTTP 422; missing/invalid session or device credential returns 401; account-scoped missing records return 404; duplicate rules return 409; unavailable models return 503; unsupported/oversized media return 413 or 415. Client responses contain concise details and do not expose tracebacks or credentials.
