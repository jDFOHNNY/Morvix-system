"use strict";

const $ = (selector) => document.querySelector(selector);
let activeTab = null;
let currentOrigin = null;

async function message(payload) {
  const response = await chrome.runtime.sendMessage(payload);
  if (response?.error) throw new Error(response.error);
  return response;
}
async function getState() { return message({ type: "morvix-get-status" }); }
function setMessage(text, error = false) { const node = $("#message"); node.textContent = text || ""; node.style.color = error ? "#9c422e" : "#39764d"; }
function matchFor(origin) {
  const url = new URL(origin);
  return `${url.protocol}//${url.hostname}/*`;
}

async function render() {
  const state = await getState().catch(() => ({}));
  let online = false;
  if (state.deviceId) {
    try { await message({ type: "morvix-sync-policy" }); online = true; }
    catch (_) { online = false; }
  }
  const fresh = await getState().catch(() => state);
  const paired = Boolean(fresh.deviceId);
  const connection = $("#connection");
  connection.textContent = paired ? (fresh.configurationError ? "Configuration issue" : online ? "Connected" : "Offline") : "Not paired";
  connection.className = `status ${paired ? fresh.configurationError || !online ? "offline" : "online" : ""}`;
  const main = $("#state");
  if (!paired) {
    main.innerHTML = `<div class="card-title">Connect to your parent account</div><p class="muted">Create a one-time pairing code in the MORVIX dashboard, then enter it below. The code expires in five minutes.</p><div class="field"><label for="pairing-code">One-time pairing code</label><input id="pairing-code" inputmode="text" autocomplete="one-time-code" maxlength="40" placeholder="Paste the dashboard code"></div><button id="pair" class="button primary" type="button">Pair extension</button>`;
    $("#pair").addEventListener("click", pair);
  } else {
    const policy = fresh.cachedPolicy?.policy;
    const freshness = fresh.policyFreshness || {};
    const expires = freshness.expiresAt ? new Date(freshness.expiresAt).toLocaleString() : "unknown";
    const offlinePolicy = freshness.fresh
      ? `If the backend goes offline, cached website rules remain available until ${escapeHtml(expires)}. New text, image, and video classification requires the local MORVIX backend.`
      : "The cached policy is expired or unavailable. Offline website rules are not applied, and new content classification requires the local MORVIX backend.";
    const syncStatus = online
      ? "Your parent policy is synchronized."
      : freshness.fresh
        ? "The local backend is offline. MORVIX is using the last valid cached website rules. New content classification is unavailable."
        : "The local backend is offline and the cached policy is expired or unavailable.";
    const categoryNames = { violence: "Violence", threat_language: "Threat Language", self_harm_indicators: "Self-harm Indicators" };
    const syncedThresholds = Object.entries(policy?.thresholds || {})
      .filter(([category, values]) => categoryNames[category] && Number.isFinite(Number(values?.review)) && Number.isFinite(Number(values?.block)))
      .map(([category, values]) => `${categoryNames[category]}: ${Number(values.review) * 100}% review / ${Number(values.block) * 100}% block`)
      .join(" · ");
    const thresholdStatus = syncedThresholds
      ? `<p class="muted">${online ? "Synchronized thresholds" : "Cached thresholds"}: ${escapeHtml(syncedThresholds)}</p>`
      : "";
    const imageReadiness = fresh.classifierReadiness?.image;
    const imageStatus = !imageReadiness
      ? `<section class="classifier-status pending" role="status" aria-live="polite"><strong>Image classifier status not checked</strong><p>Image readiness is checked before MORVIX fetches a page image. Text analysis is separate.</p></section>`
      : imageReadiness.ready
        ? `<section class="classifier-status" role="status" aria-live="polite"><strong>Image model passed runtime checks</strong><p>This status does not verify classification accuracy.</p></section>`
        : `<section class="classifier-status unavailable" role="status" aria-live="polite"><strong>Image classification unavailable</strong><p>Image checks are skipped and pages stay accessible unless a parent website rule blocks them. Text analysis remains active.</p><p class="classifier-reason">${escapeHtml(imageReadiness.reason || "The local image classifier is not ready.")}</p></section>`;
    main.innerHTML = `<div class="card-title">${escapeHtml(fresh.deviceLabel || "Protected browser")}</div><p class="muted">${syncStatus}</p>${fresh.configurationError ? `<p class="message error">${escapeHtml(fresh.configurationError)}</p>` : ""}${fresh.policySyncError && online ? `<p class="muted">Policy sync issue: ${escapeHtml(fresh.policySyncError)}</p>` : ""}<p class="muted">${offlinePolicy}</p><p class="muted">Protection: <strong>${policy?.protection_enabled ? "On" : "Paused"}</strong> · Enabled sites: <strong>${(fresh.enabledOrigins || []).length}</strong> · Queued rule events: <strong>${fresh.offlineEventCount || 0}</strong></p>${thresholdStatus}${imageStatus}${fresh.lastSyncAt ? `<p class="muted">Cached policy v${policy?.version ?? "—"} · Last sync: ${escapeHtml(new Date(fresh.lastSyncAt).toLocaleString())} · Cache age limit: ${fresh.policyFreshness?.maxAgeMinutes ?? 1440} minutes</p>` : `<p class="muted">Cached policy v${policy?.version ?? "—"} · Cache age limit: ${fresh.policyFreshness?.maxAgeMinutes ?? 1440} minutes</p>`}<button id="unpair" class="button" type="button">Disconnect this browser</button>`;
    $("#unpair").addEventListener("click", async () => {
      await message({ type: "morvix-disconnect" });
      await render();
    });
  }
  if (activeTab && currentOrigin) {
    const section = $("#site-card");
    section.classList.remove("hidden");
    $("#site-name").textContent = new URL(currentOrigin).hostname;
    const permissions = await chrome.permissions.contains({ origins: [matchFor(currentOrigin)] }).catch(() => false);
    const enabled = (fresh.enabledOrigins || []).includes(currentOrigin);
    $("#site-state").textContent = enabled ? "Protection is enabled for this website." : permissions ? "This site permission is available. Enable MORVIX to scan this website." : "This site is not enabled. MORVIX cannot read it until you grant access here.";
    const button = $("#enable-site");
    button.textContent = enabled ? "Refresh protection on this site" : "Enable protection on this site";
    button.disabled = !paired;
    button.addEventListener("click", enableCurrentSite);
  }
}

function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }

async function pair() {
  const code = $("#pairing-code").value.trim();
  if (code.length < 8) { setMessage("Enter the pairing code shown in dashboard settings.", true); return; }
  const button = $("#pair"); button.disabled = true; setMessage("Pairing with your local MORVIX service…");
  try {
    const response = await fetch(MORVIX_API_CONFIG.url("/extension/activate"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pairing_code: code }), signal: AbortSignal.timeout(15000), cache: "no-store",
      credentials: "omit", redirect: "error",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Pairing failed (${response.status}).`);
    await chrome.storage.local.set({ deviceId: data.device_id, deviceLabel: data.label, deviceToken: data.device_token, cachedPolicy: { policy: data.policy, rules: data.rules, cache_max_age_minutes: data.cache_max_age_minutes }, lastSyncAt: data.last_synced_at, backendOnline: true, configurationError: null, policySyncError: null, offlineEvents: [] });
    setMessage("Extension paired. Choose which websites MORVIX can check.");
    await render();
  } catch (error) { setMessage(error.message, true); button.disabled = false; }
}

async function registerContentScripts(origins) {
  const registrations = await chrome.scripting.getRegisteredContentScripts({ ids: ["morvix-content"] });
  if (registrations.length) await chrome.scripting.unregisterContentScripts({ ids: ["morvix-content"] });
  if (!origins.length) return;
  await chrome.scripting.registerContentScripts([{ id: "morvix-content", matches: origins.map(matchFor), js: ["content.js"], runAt: "document_idle", persistAcrossSessions: true }]);
}

async function unregisterContentScripts() {
  try { await chrome.scripting.unregisterContentScripts({ ids: ["morvix-content"] }); } catch (_) { /* Nothing was registered. */ }
}

async function enableCurrentSite() {
  const button = $("#enable-site");
  const match = matchFor(currentOrigin);
  button.disabled = true; setMessage("Requesting access for this website…");
  try {
    const granted = await chrome.permissions.request({ origins: [match] });
    if (!granted) throw new Error("Site access was not granted.");
    const state = await getState();
    const origins = [...new Set([...(state.enabledOrigins || []), currentOrigin])];
    await chrome.storage.local.set({ enabledOrigins: origins });
    await registerContentScripts(origins);
    if (activeTab?.id) await chrome.scripting.executeScript({ target: { tabId: activeTab.id }, files: ["content.js"] });
    await message({ type: "morvix-sync-policy" }).catch(() => null);
    setMessage("Protection enabled for this website.");
    await render();
  } catch (error) { setMessage(error.message || "Could not enable this website.", true); button.disabled = false; }
}

document.addEventListener("DOMContentLoaded", async () => {
  [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (activeTab?.url && /^https?:/i.test(activeTab.url)) currentOrigin = new URL(activeTab.url).origin;
  else $("#site-card").classList.add("hidden");
  $("#sync").addEventListener("click", async () => {
    try { await message({ type: "morvix-sync-policy" }); setMessage("Policy synchronized."); await render(); }
    catch (error) { setMessage(error.message, true); }
  });
  await render();
});
