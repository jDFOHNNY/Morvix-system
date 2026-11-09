# MORVIX — Intelligent Multimodal Content Protection System

**Project:** BSCS-3 Software Engineering capstone  
**Development environment:** Windows, PowerShell, VS Code, Chrome  
**Current local backend:** `http://127.0.0.1:8000/`  
Use the folder where you extracted this project as the project root. Commands below are relative to that folder, so each team member can place it in a different location.

> **Important status note:** This README describes the current reported local setup. It does not claim that every SRS feature is complete. Earlier project notes report a controlled text smoke test, but this source bundle does not contain the required model weights, so that result cannot be reproduced here. Text and video models have not been formally evaluated for MORVIX's target categories. Image classification is unavailable, and no self-harm classifier is configured.

---

## 1. What MORVIX contains

MORVIX is a local content-protection prototype with:

- A parent/guardian web dashboard.
- A FastAPI backend and database.
- A Chromium Manifest V3 browser extension.
- Local text and video inference pipelines in experimental status.
- Detection history, alerts, and configurable protection policies.
- A controlled webpage for testing the extension's text workflow.

Core classification is intended to run locally, without an external cloud moderation API. The extension can analyze only content it can access on enabled and supported pages.

## 2. Important local URLs

| Purpose                                                         | URL                                                 |
| --------------------------------------------------------------- | --------------------------------------------------- |
| MORVIX dashboard                                                | `http://127.0.0.1:8000/`                            |
| FastAPI interactive documentation (if enabled)                  | `http://127.0.0.1:8000/docs`                        |
| Backend readiness check                                         | `http://127.0.0.1:8000/api/v1/health/ready`         |
| Controlled text demo page (when its separate server is running) | `http://localhost:8001/MORVIX_plain_text_demo.html` |
| Isolated fictional threat-language sample                       | `http://localhost:8001/threat-only.html`            |

**Do not use `/api/v1` as the dashboard URL.** It is an API prefix, not the homepage, and may correctly return 404.

## 3. Requirements

- Windows 10/11 or another supported Windows environment.
- Python 3.11 or 3.12. The current local setup uses Python 3.11.9; create a fresh virtual environment with the Python installed on each laptop.
- A project virtual environment created on this laptop at `.venv`. Do not copy `.venv` from another computer.
- Node.js installed and available in PowerShell to run JavaScript tests.
- Chrome or another supported Chromium browser for extension testing.

The optional machine-learning package names are listed in `requirements-ml.txt`; the tested ML package versions are not recorded in this source bundle. Model weights are also absent. See Section 5.6 and `docs/MODEL_INVENTORY.md`, and use the approved versions and snapshots from the team before a classifier demonstration.

## 4. Open the project in VS Code

Open VS Code, select **File → Open Folder**, and choose the folder you extracted. The project root contains `README.md`, `backend`, `browser_extension`, and `web_dashboard`.

Keep the full project root open, rather than opening only `backend`, `web_dashboard`, or `browser_extension`.

Alternatively, from PowerShell:

```powershell
code .
```

If `code` is not recognized, use VS Code's **File → Open Folder** menu.

## 5. First-time setup (only when needed)

### 5.1 Open PowerShell at the project root

```powershell
Set-Location "<the folder where you extracted MORVIX_FRESH_BUILD>"
```

### 5.2 Check whether the virtual environment already exists

```powershell
Test-Path ".\.venv\Scripts\python.exe"
```

If this returns `True`, check it with `& .\.venv\Scripts\python.exe --version`. Keep using it only if it runs and was created with a compatible Python version on this laptop. A `.venv` copied from another laptop is not portable.

If the check returns `False`, or the Python executable cannot run, keep the old folder as a backup by renaming it, then create a fresh environment using Python 3.11 or 3.12. First check which version is available with `python --version` or `py --list`:

```powershell
if (Test-Path ".\.venv") { Rename-Item ".\.venv" (".venv.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
python -m venv .venv
```

If `python` is not recognized but the Python launcher lists an installed version, use its version explicitly, for example `py -3.11 -m venv .venv`. Do not use `py -3.12` unless Python 3.12 appears in `py --list`.

### 5.3 Ensure pip exists inside the virtual environment

Use the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip --version
```

The printed path should point inside this project's `.venv` directory.

### 5.4 Install dependencies in the virtual environment

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt
```

The first requirements file installs the backend and test packages. The second installs the local model runtime packages (`torch`, `transformers`, `safetensors`, plus image/video libraries). This direct-Python method avoids accidentally installing packages into global Python. These packages do not include model weights; follow Section 5.6 as well.

### 5.5 Environment settings

The backend reads settings from process environment variables in `backend/app/config.py`. It does not automatically load a `.env` file. Defaults support the local demo, so no `.env` file is required.

Email/password account creation works without extra settings. To enable the Google option requested in the teacher's review and require a parent-account email notice, create a Google OAuth **Web application** client ID and add the exact dashboard origin(s) you use (for example `http://127.0.0.1:8000` and/or `http://localhost:8000`) under Authorized JavaScript origins. Configure an SMTP sender account as well. For Gmail SMTP, use `smtp.gmail.com` with port `587` and STARTTLS, a full Gmail address as the username, and an app password (never your regular Google password). App passwords require 2-Step Verification and may be unavailable on managed/Advanced Protection accounts; Google Workspace may require an administrator-configured relay. See [Gmail's SMTP settings](https://support.google.com/mail/answer/7104828) and [Google's app-password requirements](https://support.google.com/accounts/answer/185833).

Set these values in the PowerShell window that will run the backend; do not add the app password to source control or send it in chat:

```powershell
$env:MORVIX_GOOGLE_CLIENT_ID = "your-web-client-id.apps.googleusercontent.com"
$env:MORVIX_SMTP_HOST = "smtp.gmail.com"
$env:MORVIX_SMTP_PORT = "587"
$env:MORVIX_SMTP_USERNAME = "morvix-sender@gmail.com"
$env:MORVIX_SMTP_PASSWORD = "your-gmail-app-password"
$env:MORVIX_EMAIL_FROM = $env:MORVIX_SMTP_USERNAME
```

The account screen always shows both traditional email/password registration and a Google option. The Google option stays disabled with a setup explanation until both Google sign-in and SMTP email delivery are configured. MORVIX verifies Google's signed ID token on the backend and accepts verified Gmail or Google Workspace accounts. When a Google identity first creates or links a parent account, MORVIX sends a confirmation to that verified address before committing the account. If SMTP delivery fails, the new Google account/link is rolled back and the dashboard shows an error. The Google ID-token sign-in flow needs a web client ID and network access to Google's Identity Services; it does not use a client secret or redirect URI. If configuration is missing, traditional registration remains usable.

Keep any private local settings file out of source control and do not share secrets from it.

### 5.6 Provide the local model files

The source bundle does not include model weights, model manifests, or a model download script. The text snapshot directory must contain `config.json`, `model.safetensors` (or a valid safetensors index and every referenced shard), and tokenizer data such as `tokenizer.json` or `vocab.txt`; tokenizer configuration files should accompany the approved snapshot when provided. Readiness distinguishes missing weights, incomplete/invalid files, missing runtime packages, model-loading failure, initialized state, and a failed last inference in `classifier_details`. The existing `classifiers` status map remains available for older clients. A failed text check returns HTTP 503 and an uncertain, non-blocking extension notice; it does not create a classification event or block content.

`unitary/toxic-bert` is documented only as a candidate pending team/adviser approval. This checkout has no approval record, pinned revision/commit, or snapshot files, so do not download it as if approved. The project must supply an approved model ID and exact revision plus its configuration, safetensors, and tokenizer assets. The current `.venv` packages (`torch 2.14.1+cpu`, `transformers 5.20.2`, and `safetensors 0.8.0`) import together, including `AutoModelForSequenceClassification` and `AutoTokenizer`; that checks runtime imports only, not compatibility with absent model weights. `requirements-ml.txt` remains unpinned until the approved snapshot can be loaded and tested as a set.

`unitary/toxic-bert` is a toxic-comment model and only exposes its English `threat` label as MORVIX `threat_language`. It is not a morbid-content classifier for gore, graphic injury, death descriptions, or suffering. MORVIX must not claim to detect morbid text until a suitable local model is approved and evaluated on labeled examples that distinguish disturbing descriptions from ordinary medical, historical, news, and fictional discussion.

Image classification is unavailable in this build. Video has a local inference adapter, but its model snapshot is also absent from this source bundle and its target-category accuracy has not been evaluated. Model setup is complete only after readiness reports the expected status and a local inference smoke check succeeds.

## 6. Start the MORVIX backend and dashboard

The current build serves the dashboard from the FastAPI application at the root URL. You normally do **not** need a separate Live Server for the dashboard.

### 6.1 Check if the backend is already running

In PowerShell, from the project root, run:

```powershell
try {
    $response = Invoke-WebRequest "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 3
    Write-Host "Dashboard responds with HTTP $($response.StatusCode). Do not start another server."
} catch {
    Write-Host "The dashboard URL did not respond. Check the listener and start the backend if needed."
}
```

You can also check the readiness endpoint:

```powershell
try {
    $response = Invoke-WebRequest "http://127.0.0.1:8000/api/v1/health/ready" -UseBasicParsing -TimeoutSec 3
    Write-Host "Readiness endpoint returned HTTP $($response.StatusCode)."
    $response.Content
} catch {
    Write-Host "Readiness endpoint did not respond. Inspect the error and backend terminal."
}
```

A readiness response must be interpreted using its content: backend readiness does not necessarily mean that every ML model is available.

### 6.2 Start the backend only if it is not already running

Open a PowerShell terminal at the project root and run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal open while using MORVIX. The server log should say that application startup completed and that it is listening on `127.0.0.1:8000`.

Then open Chrome at:

`http://127.0.0.1:8000/`

### Important: avoid the port 8000 error

If Uvicorn reports `WinError 10048` or says the address is already in use, another process is already listening on port 8000. **Do not keep starting more servers.** Check the existing dashboard URL first. If it responds, use the existing server. If it does not respond, inspect the process before stopping anything:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

If a process ID is shown, inspect it before making changes:

```powershell
Get-Process -Id <PID>
```

Replace `<PID>` with the actual process ID. Do not terminate a process until you know what it is.

## 7. PowerShell activation-policy issue

If PowerShell refuses to load `.venv\Scripts\Activate.ps1` because script execution is disabled, you do not need to change system-wide policy to run MORVIX. Use the virtual environment's Python executable directly, as shown in this README.

If you specifically want to activate the environment for the current PowerShell process, you can run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

This setting applies only to that PowerShell process. If activation is still blocked, use the direct `.venv\Scripts\python.exe` commands instead.

When the virtual environment is active, the prompt usually starts with `(.venv)`. However, seeing `(.venv)` alone is not proof that `pip` is installed or that commands are using the intended interpreter. Verify with:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip --version
```

Both paths should point to `MORVIX_FRESH_BUILD\.venv`.

## 8. Start the controlled extension test page

Use this only when performing the controlled browser test. The MORVIX backend must remain running separately on port 8000.

Open a **second PowerShell window** and run:

```powershell
.\.venv\Scripts\python.exe -m http.server 8001 --bind localhost --directory .\data\controlled_extension_test
```

Keep the test-page server terminal open. Open:

- `http://localhost:8001/MORVIX_plain_text_demo.html` for the controlled benign and fictional text samples.
- `http://localhost:8001/threat-only.html` for the isolated fictional threat sample.

The test page is served from `localhost` so the extension's site-access grant can be managed independently of the backend at `127.0.0.1`. Enable protection for this site through the MORVIX popup if prompted, then refresh the page once to trigger analysis. Stop the test-page server with **Ctrl+C** when finished.

A completed classification for a supported category is saved as a metadata-only history event even when its score is below the review threshold and the action is Allow. A null `event_id` means the backend did not persist an event for that request, such as when protection is disabled, classification is unavailable, or the classifier returns no supported category.

## 9. Load or reload the Chrome extension

The current extension folder is:

`browser_extension` inside the project root

To load it for the first time:

1. Open Chrome and go to `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose the `browser_extension` folder.
5. Open the MORVIX popup and follow the application's pairing process.

If the extension is already loaded, do not remove it just to update it. After code changes, use the extension's **Reload** button when you intentionally need Chrome to load the updated files. The popup's connected status indicates successful communication or policy synchronization as implemented; it does not by itself prove that a page was analyzed or that enforcement happened.

## 10. Suggested manual demonstration

1. Start the backend and open the dashboard at `http://127.0.0.1:8000/`.
2. Create an account with email and password, or use Google sign-in if its Web client ID is configured, then sign in.
3. Open Protection Rules and verify Create, Read, Update, and Delete. Refresh after saving to verify persistence.
4. Confirm the extension is paired and that the displayed connection status updates from backend check-ins.
5. Start the controlled test-page server on port 8001 and enable protection for `localhost` in the extension popup.
6. Open `http://localhost:8001/threat-only.html`, refresh the page, and inspect the extension's `classify/text` request if needed.
7. Verify the classifier response's `detected`, `category`, `confidence`, `action`, `reason`, and `event_id` fields.
8. Check Detection History and Alerts for the resulting event.
9. Record the test result, timestamp, and any errors in `docs/BUILD_STATUS.md`.

Earlier project notes reported a controlled threat sample score of approximately `0.64225`, action `warn`, and a non-null event ID. The required weights are absent from this source bundle, so that result cannot be reproduced from this folder as provided. It is a smoke-test reference only, not a measure of model accuracy.

## 11. Run tests

Run Python tests using the virtual environment's interpreter, whether or not activation is enabled:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Run browser-extension security tests (requires Node.js installed and on `PATH`):

```powershell
node --test browser_extension/tests/security.test.cjs
```

Run dashboard JavaScript tests:

```powershell
node --test web_dashboard/tests/*.test.cjs
```

Check tool availability:

```powershell
node -v
npm -v
```

If `node` is not recognized, install the LTS release from <https://nodejs.org/en/download>, then open a new terminal and retry. Installing Node.js is needed for the JavaScript tests; it is not a replacement for Python.

## 12. Troubleshooting

### `No module named pip`

Use the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### PowerShell says script execution is disabled

Use direct `.venv\Scripts\python.exe` commands in this README, or follow Section 7 for process-scoped activation. Avoid changing machine-wide execution policy just for MORVIX.

### Uvicorn reports address already in use / WinError 10048

Another process already owns port 8000. Test `http://127.0.0.1:8000/` before launching anything else. If the dashboard works, reuse the existing server. If not, inspect the listening process as shown in Section 6; do not kill it blindly.

### Dashboard site cannot be reached

1. Confirm the backend terminal is still running without a traceback or shutdown message.
2. Check `http://127.0.0.1:8000/`, not `/api/v1`.
3. Run the HTTP check in Section 6.1.
4. If the terminal says port 8000 is occupied, find out whether the existing process is the MORVIX server.

### Dashboard opens but its data fails to load

Open browser DevTools (F12), inspect Console and Network, and check the backend terminal. Verify the actual API request URL and response code. Do not disable authentication or CORS protections just to hide an error.

### Detection History is empty

A successful classification HTTP response does not necessarily mean a detection was recorded. Check the JSON fields:

- `detected`
- `category`
- `confidence`
- `action`
- `reason`
- `event_id`

If `event_id` is `null`, the backend did not record an event for that response. If a non-null ID is returned but history remains empty, investigate event persistence, account ownership, and the history API/filter.

### Extension popup says Connected but dashboard says Offline

The dashboard uses the backend-reported last check-in and a 120-second connection window, according to the current implementation report. Policy sync/check-in needs to occur within that window. Refresh the dashboard or focus its tab, then inspect the actual status API before changing status code.

### Model says unavailable

A healthy backend does not mean every classifier is ready. In this source bundle:

- Text: the adapter is implemented, but its model weights are absent; target-category evaluation is also still needed.
- Video: the adapter is implemented, but its model weights are absent; validation for MORVIX's target categories is still needed.
- Image: unavailable in this source bundle because the candidate checkpoint has an unresolved class-label mapping.
- Self-harm: no classifier configured.

Do not claim disabled or unvalidated modalities are working.

## 13. Privacy and safety notes

- The extension can analyze only enabled sites and accessible content that its implementation supports.
- Core classification must not rely on an external cloud moderation API.
- Raw text and media should not be retained by default. Review actual request behavior and logs during testing.
- Use fictional, controlled samples for classroom demonstrations.
- Keep the backend bound to loopback (`127.0.0.1`) for local development unless a reviewed deployment configuration explicitly requires otherwise.
- Do not share `.env`, device tokens, registration credentials, or browser profile data.

## 14. Current known limitations

The current system is a course-project prototype, not a fully validated product.

- Text and video model inference are experimental and require suitable held-out evaluation.
- Image classification is unavailable until the model checkpoint and class-label mapping can be resolved and verified.
- Self-harm classification is not implemented.
- Browser extension coverage is limited by site permissions, DOM behavior, cross-origin restrictions, dynamic content, and media support.
- Offline policy enforcement is limited to the cached rules and supported behavior documented in `docs/DECISIONS_AND_LIMITATIONS.md`.
- Not all SRS acceptance criteria have been verified end to end.

Consult `docs/BUILD_STATUS.md`, `docs/DECISIONS_AND_LIMITATIONS.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, and `docs/MODEL_INVENTORY.md` for the latest project status.

---

## 15. Quick-start checklist

For a normal session, the quick-start sequence is:

1. Open PowerShell in the project root.
2. Check whether `http://127.0.0.1:8000/` already responds.
3. If it does not and no valid server is listening, start Uvicorn using the command in Section 6.2.
4. Open `http://127.0.0.1:8000/` in Chrome.
5. For an extension test, start the separate `http.server` process on port 8001 in another terminal.
6. Run tests only when needed using the commands in Section 11.
7. Stop each server with **Ctrl+C** in the terminal where that server is running.

**Do not recreate `.venv` or start duplicate servers during a normal session.**
