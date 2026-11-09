> Automated suite results below were rerun on 2026-10-21. Model-dependent and live browser checks remain separate; do not mark them passed from source review alone.

# MORVIX Acceptance Test Checklist

**Status key:** Pass / Fail / Blocked / Not run. Do not mark a browser or ML scenario passed from source review alone.

## Teacher comment follow-up for the second review

| Teacher comment | What is in MORVIX | Second-review check | Current status |
| --- | --- | --- | --- |
| Offer two account creation options: traditional and Google. | The account screen shows email/password registration and a Google option. Google is disabled with a setup explanation until its Web client ID and SMTP sender are configured. | Open the signed-out dashboard, choose **Create account**, confirm both options are visible. Register with email/password. After Google and SMTP are configured, use a verified test Google account and confirm the parent acceptance email arrives. | Traditional path implemented and covered by backend tests. Google code and delivery rollback are covered by mocked tests; live Google/inbox check is blocked by missing configuration. |
| Prepare for second-round checking. | The acceptance cases below separate automated results from manual browser, setup, and model checks. | Run the automated commands in the README, then record each manual/browser result below with Pass, Fail, Blocked, or Not run. | Backend 58 passed / 4 skipped; extension 33 passed; dashboard 14 passed on 2026-10-21. |
| Identify which functions/features each function applies to. | The [SRS traceability map](REQUIREMENTS_TRACEABILITY.md) maps each marked SRS function to its screen, code path, and limitation. | For each marked row, trace the named UI control through the API route to the backend or extension handler. Confirm outcomes in dashboard history where the end-to-end path is available. | Mapping documented; live Chrome and model-dependent rows remain unverified or blocked as shown in the map. |

## Automated / API checks

- [x] AC-01/02: account registration and login, invalid credentials, protected current-user endpoint, logout.
- [x] AC-06/07: rule create/read/update/delete, validation, persisted setting change and version increment.
- [x] AC-11: account-scoped event/alert/history access (API-level fixture).
- [x] AC-17: pairing code exchange, one-use behavior, policy sync, heartbeat and revocation (API-level).
- [x] Offline site-rule event API: active rule revalidation, deduplication, host-only persistence, disabled-protection rejection.
- [x] Dashboard API: zero-data counts, no unmeasured accuracy, history filters, alert review (API-level fixtures).
- [ ] AC-02: verify database records after a full backend process restart.
- [ ] AC-08/10/14/16: full classifier-to-event-to-alert and filtered dashboard round trip.
- [ ] AC-15/20: inspect DB contents after real text/image/video inference to confirm raw inputs are not persisted.

## Manual Chromium checks

- [ ] Teacher comment: signed-out account screen shows traditional email/password registration and the Google option. Traditional registration is ready; Google remains blocked until OAuth client ID and SMTP settings are supplied.
- [ ] After configuring Google and SMTP: complete a first-time Google parent sign-in with a test account and confirm the parent acceptance notice arrives in that account's inbox.
- [ ] AC-01: register a parent in the dashboard and sign in.
- [ ] AC-03/11: create pairing code in settings, enter it in extension popup, confirm the same device appears in dashboard.
- [ ] AC-07/08: use a local test page and verify supported block and warn behavior; check that an API error never silently blocks.
- [ ] AC-09/17: edit a policy and verify extension policy version changes after synchronization.
- [ ] AC-13/18: disconnect backend after sync; confirm cached site rules remain, status shows disconnected, unavailable classification is warned about, and reconnection resynchronizes.
- [ ] AC-22: use every dashboard navigation item and sign out.
- [ ] NFR-COM-01: confirm the selected Chromium browser and extension workflow after the team/adviser confirms the browser.

## Local model checks

- **Blocked — AC-04/12:** no approved local text snapshot is present. Runtime package imports pass, but model loading and inference cannot be tested until the team supplies an approved exact revision and snapshot files.
- **Blocked — AC-05/13:** image scoring is unavailable because the inspected checkpoint is incompatible and is rejected before inference. A compatible labeled image model is required.
- **Blocked — AC-06/14:** the video model snapshot is absent in this checkout. Earlier smoke notes are historical and are not reproducible here.
- [ ] Run evaluation on a held-out labeled set and record category precision, recall, F1 and confusion matrix where data supports them.

See `BUILD_STATUS.md` for checks completed to date and evidence.
