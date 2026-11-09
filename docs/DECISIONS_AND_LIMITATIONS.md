# MORVIX Decisions and Limitations

The supplied SRS is Draft 1.0 and explicitly requires validation. Decisions marked **provisional** are implementation defaults to make progress, not approval on behalf of the team or adviser.

## Requirements still requiring confirmation

| Open SRS item | Provisional implementation default | Reason / remaining approval |
| --- | --- | --- |
| Final content taxonomy | Candidate labels remain Graphic Violence, Threat Language, and Self-harm Indicators; each classifier advertises only labels it can substantiate. | Candidate list comes from the draft. Adviser/team must approve target definitions and evaluation labels. |
| Audio | Excluded from initial acceptance scope and UI. | Optional in SRS; no confirmed requirement or suitable local dataset/model. |
| Supported browser | Chromium Manifest V3; Chrome is the primary manual test target. | The user confirmed a Chrome load and pairing; the controlled-page end-to-end acceptance remains pending. Edge remains untested. |
| Video strategy | Use a dedicated local video classifier on 16 frames sampled evenly across bounded clips, with file-size and duration caps. | The candidate model documents binary violent/non-violent labels; its temporal and domain limits still require evaluation and adviser review. |
| Confidence thresholds | Configurable per category/modality; defaults are conservative warning/flag, with block only when an explicit parent rule requests it and confidence passes a configured gate. | Threshold numbers cannot be responsibly selected without model calibration and adviser approval. No accuracy claims. |
| Extension pairing | Short-lived, one-use dashboard-issued pairing code exchanged for a random revocable device credential. | Secure practical default; confirm with project team. |
| Raw-data retention | Do not retain raw content; retain minimal event metadata. Retention duration is configurable/undecided, with no automatic purge until approved. | SRS requires minimization but leaves retention duration open. |
| Database/deployment | SQLite local development, one FastAPI process and same-machine browser demo; migration seam maintained. | Builder specification prefers SQLite; original SRS allows a lightweight alternative and leaves topology open. |
| Notifications | Dashboard alerts only. | Email/OS/push is explicitly out of scope unless later approved. |
| Metrics | Event counts from database only. No accuracy metric until an evaluation set is supplied and run. | Required to avoid fabricated metrics. |
| Policy precedence | When protection is enabled, a matching website rule is applied first and bypasses category scoring. Otherwise, an enabled category rule overrides the parent category action. Below the review threshold, the result is allowed. At or above review, the requested parent action is retained except that Block becomes Flagged while confidence is below the block threshold; Block remains Block at or above that threshold. Warn and Allow are never upgraded by thresholds. | Consistent with the SRS's parent-controlled policy and configurable confidence thresholds. A category Block rule does not bypass its configured confidence gate. |
| Offline policy age | `MORVIX_POLICY_CACHE_MAX_AGE_MINUTES` controls the extension's cached-policy lifetime. Default is 1440 minutes (24 hours), clamped to 1 minute–7 days. | Provisional default; team/adviser confirmation is pending. Expired policy is retained for a later successful sync but is not applied offline. |
| Model selection | Replaceable local adapters. Candidate model IDs, revisions and declared licenses are recorded in `MODEL_INVENTORY.md`; image scoring remains disabled until a compatible checkpoint is selected. | Draft leaves architecture, datasets and taxonomy open; candidate labels do not establish task accuracy or safety. |
| Classifier capability display | Settings distinguishes configured policy from local model readiness. Text and video are experimental candidate pipelines; image and self-harm detection are unavailable. | A saved policy action or enabled modality must not be mistaken for proven classifier coverage. Revisit after compatible models and labeled MORVIX evaluation are available. |

## Confirmed scope

- Parent desktop dashboard, MV3 extension, backend and local SQLite persistence.
- Parent authentication, account-level isolation, extension registration/revocation, policy controls, metadata history and dashboard alerts.
- Required modalities are text, image and video; audio is optional.
- No external runtime moderation/content-classification API. A model download during setup is distinct from inference; inference remains local.
- The extension only covers supported, accessible browser content; it is not universal web/device monitoring.
- Warm peach, cream, orange and dark-brown design from the supplied screenshots. The screenshot's sample accuracy/counts are not product data.

## Known technical limitations to state in UI/docs

- Cross-origin media, protected pages, browser-internal pages, DRM, canvas/video restrictions, dynamic DOMs and platform-specific rendering can prevent extraction.
- The video classifier samples 16 frames across each bounded clip, can miss brief events between sampled frames, and does not analyze audio tracks.
- The extension requests access per enabled website, scans rendered text up to 20,000 characters, up to five visible same-origin images and one same-origin video per page load. It does not scan cross-origin media. Visible text is rescanned after debounced DOM mutations; unchanged snapshots are deduplicated, but hidden text and content outside the rendered DOM are not analyzed.
- A model's training labels may not match MORVIX categories. No category mapping or safety claim is made without inspected model documentation and evaluation data.
- Text uses `unitary/toxic-bert`'s English Jigsaw toxic-comment `threat` head. It is not a validated general threat detector; profanity or identity-related language may affect scores regardless of intent. The local model is uncased English, evaluates overlapping 512-token windows with 64-token overlap up to the 20,000-character cap, and uses the maximum window score. That aggregation is not calibrated and may raise a score on longer pages. This is not the model card's separate multilingual XLM-R checkpoint. MORVIX has not evaluated its language coverage, bias, calibration, or accuracy. It does not provide a violence or self-harm text classifier.
- Completed classifier decisions with a supported category are stored as metadata-only history records even when the score is below the review threshold and the final action is Allow. Paused protection, disabled modalities, matching website rules that preempt classification, unavailable classifiers, and classifier results without a supported category do not create category-classification history rows. Raw page text is not stored.
- Video uses `HappyGook/videomae-violence-detector`, a binary violent/non-violent VideoMAE candidate fine-tuned for bus-surveillance footage. MORVIX smoke-tested actual local inference on a generated AVI, but has no evaluation set. It is not validated for the draft graphic-violence category. Sampling can miss brief activity; audio is ignored.
- The image candidate config has two classes but no `id2label`; its weight names use a timm-style ViT layout while its config declares a Transformers ViT. Neither the local metadata nor model card verifies class-index order. Converting tensor names alone cannot safely assign the violence output, so image preflight refuses it rather than guessing.
- Self-harm Indicators has no selected model or inference code. It is a policy taxonomy entry only and does not represent active detection.
- Offline cached policy can apply website rules only until the configured policy age expires. The default is 24 hours and still needs team/adviser confirmation. After expiry, the retained snapshot is not applied until a successful sync. Text/image/video classification still requires the local backend; the popup reports this limitation.
- The extension checks classifier readiness before fetching page media for upload and follows the backend's configured upload limit. The current image checkpoint is incompatible, so no image is uploaded for classification and image classification is not complete.
- Extension classification sends visible text (bounded to 20,000 characters) and, only after a ready classifier check, bounded same-origin media to `http://127.0.0.1:8000`. Event records and queued offline metadata contain the page origin/host only; paths, queries and fragments are omitted.
- Extension connection is represented by an authenticated check-in, not proof of page enforcement. Pair activation initializes `paired_at` and `last_seen_at`; the extension's popup and one-minute service-worker policy sync call `GET /api/v1/extension/policy`, which also updates `last_seen_at`. `POST /api/v1/extension/heartbeat` is available but is not the extension's current recurring check-in. The backend reports connected only for a non-revoked device whose last check-in is at most 120 seconds old. The dashboard now refreshes Overview and Settings status every 10 seconds while visible and on focus/return; actual post-fix display still requires manual browser confirmation.
- `data/controlled_extension_test/MORVIX_plain_text_demo.html` is the manual controlled text-test page, served at `http://localhost:8001/MORVIX_plain_text_demo.html` with the PowerShell command recorded in `BUILD_STATUS.md`. This host differs from the dashboard/backend host `127.0.0.1`. Chrome host match patterns do not scope permissions to the port; the existing popup's `http://localhost/*` grant covers localhost across ports. The page contains both labeled samples and explanatory copy in the visible text, so the extension sends their combined page text; a score is experimental, not validated accuracy. No analysis or detection event has yet been confirmed from this page.
- The user confirmed that the reviewed extension was loaded in Chrome, paired, showed Connected in its popup, and synchronized policy version 7. The controlled-page analysis, resulting policy action, event persistence/history, and the dashboard's refreshed connected status remain unverified pending manual testing. The source now normalizes classifier responses so the content script can show a result notice, but the loaded Chrome runtime was not reloaded and may still contain the prior handler; a later user-approved reload is needed to test that UI fix. No Chrome automation was used in the follow-up.
- Extension protection and page interventions require real browser testing. Source creation alone is not validation.
- Model weights, datasets and large runtime packages may require setup-time internet/storage and can exceed the current environment's capacity.

## Decision log

| Decision | Current record | Revisit trigger |
| --- | --- | --- |
| Use Python/FastAPI + stdlib SQLite access for local baseline | Provisional; avoids an ORM/migration dependency for the course prototype. Schema changes are versioned. | Adviser/team selects a production DB or ORM. |
| Use PBKDF2-HMAC and opaque DB-backed sessions | Local secure baseline using stdlib; deployment requires HTTPS and secure cookie flag. | Production deployment or security review. |
| Keep event metadata, not raw content | Default privacy-preserving behavior. | Explicit team/adviser approval and privacy assessment for any excerpt retention. |
| Do not show model accuracy without evaluation | Confirmed by SRS. | Only a reproducible held-out evaluation can add measured results. |
