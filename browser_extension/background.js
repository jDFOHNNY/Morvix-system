"use strict";

importScripts("api_config.js", "media_transport.js", "policy_cache.js");

const EVENT_QUEUE_LIMIT = 100;
const CLASSIFIER_READINESS_CACHE_MS = 60_000;
const TEXT_ANALYSIS_TIMEOUT_MS = 60_000;
const classifierReadinessCache = new Map();

async function read(keys) { return chrome.storage.local.get(keys); }

async function disconnectLocal() {
  const { enabledOrigins = [] } = await read(["enabledOrigins"]);
  const origins = enabledOrigins.map((origin) => {
    try {
      const url = new URL(origin);
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
      return `${url.protocol}//${url.hostname}/*`;
    } catch (_) { return null; }
  }).filter(Boolean);
  if (origins.length) await chrome.permissions.remove({ origins }).catch(() => false);
  await chrome.scripting.unregisterContentScripts({ ids: ["morvix-content"] }).catch(() => {});
  await chrome.storage.local.remove([
    "apiBase", "configurationError", "deviceId", "deviceLabel", "deviceToken",
    "cachedPolicy", "lastSyncAt", "offlineEvents", "enabledOrigins", "classifierReadiness",
  ]);
  classifierReadinessCache.clear();
}

async function apiRequest(path, options = {}) {
  const saved = await read(["apiBase", "deviceToken"]);
  try {
    MORVIX_API_CONFIG.assertStoredBase(saved.apiBase);
  } catch (error) {
    await chrome.storage.local.set({
      configurationError: error.message,
      backendOnline: false,
    });
    throw error;
  }
  if (!saved.deviceToken) throw new Error("Pair this extension from the MORVIX dashboard first.");
  const response = await MORVIX_API_CONFIG.fetchAuthenticated(
    path,
    saved.deviceToken,
    saved.apiBase,
    options,
  );
  if (response.url && new URL(response.url).origin !== "http://127.0.0.1:8000") {
    throw new Error("MORVIX rejected a response outside the approved local backend.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) await disconnectLocal();
    const error = new Error(body.detail || `MORVIX returned ${response.status}.`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function validPolicySnapshot(snapshot) {
  const policy = snapshot?.policy;
  return Boolean(
    policy && typeof policy.protection_enabled === "boolean" &&
    policy.modalities && typeof policy.modalities === "object" &&
    Array.isArray(snapshot.rules) && snapshot.rules.every((rule) =>
      rule && ["website", "category"].includes(rule.kind) &&
      typeof rule.target === "string" &&
      ["allow", "warn", "block"].includes(rule.action) &&
      typeof rule.enabled === "boolean"
    )
  );
}

async function syncPolicy() {
  try {
    const snapshot = await apiRequest("/extension/policy");
    if (!validPolicySnapshot(snapshot)) throw new Error("The policy response was incomplete or invalid.");
    await chrome.storage.local.set({
      cachedPolicy: snapshot,
      lastSyncAt: snapshot.last_synced_at || new Date().toISOString(),
      backendOnline: true,
      policySyncError: null,
      configurationError: null,
    });
    await flushOfflineEvents();
    return snapshot;
  } catch (error) {
    await chrome.storage.local.set({
      backendOnline: Boolean(error.status),
      policySyncError: error.message,
    });
    if (error.status === 401) {
      throw new Error("This browser was revoked. Pair it again from the MORVIX dashboard.");
    }
    throw error;
  }
}

function sanitizeOfflineQueue(events) {
  const unique = new Map();
  for (const item of Array.isArray(events) ? events : []) {
    if (
      !item || !["text", "image", "video"].includes(item.modality) ||
      typeof item.event_key !== "string" || item.event_key.length < 8 || item.event_key.length > 100
    ) continue;
    try {
      const origin = MORVIX_MEDIA.pageIdentity(item.source_url).origin;
      if (!unique.has(item.event_key)) {
        unique.set(item.event_key, { modality: item.modality, source_url: origin, event_key: item.event_key });
      }
    } catch (_) { /* Drop malformed legacy queue data rather than retrying it. */ }
  }
  return [...unique.values()].slice(-EVENT_QUEUE_LIMIT);
}

async function flushOfflineEvents() {
  const { offlineEvents = [] } = await read(["offlineEvents"]);
  const queued = sanitizeOfflineQueue(offlineEvents);
  await chrome.storage.local.set({ offlineEvents: queued });
  if (!queued.length) return;
  const remaining = [];
  let credentialsLost = false;
  for (const item of queued) {
    try {
      // Keep each original event key so a retry is idempotent at the backend.
      await apiRequest("/extension/offline-events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
      });
    } catch (error) {
      if (error.status === 401 || /Pair this extension/i.test(error.message)) { credentialsLost = true; break; }
      if (error.status === 409 && /no longer active|no longer enabled/i.test(error.message)) continue;
      remaining.push(item);
    }
  }
  await chrome.storage.local.set({ offlineEvents: credentialsLost ? [] : remaining });
}

async function sendOfflineEvent(modality, pageUrl, eventKey) {
  let page;
  try { page = MORVIX_MEDIA.pageIdentity(pageUrl); }
  catch (_) { return; }
  const payload = { modality, source_url: page.origin, event_key: eventKey };
  try {
    await apiRequest("/extension/offline-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error.status === 401 || error.status === 409 || /Pair this extension/i.test(error.message)) return;
    const { offlineEvents = [] } = await read(["offlineEvents"]);
    const queue = sanitizeOfflineQueue(offlineEvents);
    if (!queue.some((item) => item.event_key === eventKey)) {
      queue.push(payload);
      await chrome.storage.local.set({ offlineEvents: queue.slice(-EVENT_QUEUE_LIMIT) });
    }
  }
}

async function policyForPage(pageUrl) {
  const state = await read(["cachedPolicy", "lastSyncAt"]);
  let snapshot = state.cachedPolicy;
  let freshness = MORVIX_POLICY_CACHE.freshness(snapshot, state.lastSyncAt);
  if (!validPolicySnapshot(snapshot) || !freshness.fresh) {
    try {
      snapshot = await syncPolicy();
      const synced = await read(["lastSyncAt"]);
      freshness = MORVIX_POLICY_CACHE.freshness(snapshot, synced.lastSyncAt);
    } catch (error) {
      return { snapshot, freshness, error };
    }
  }
  return { snapshot, freshness, error: null };
}

async function checkSitePolicy(pageUrl, modality) {
  let page;
  try { page = MORVIX_MEDIA.pageIdentity(pageUrl); }
  catch (_) { return { status: "skipped", reason: "This page is not supported." }; }

  const { snapshot, freshness, error } = await policyForPage(pageUrl);
  if (!validPolicySnapshot(snapshot) || !freshness.fresh) {
    return {
      status: "offline",
      reason: error?.message || "The cached policy is missing or expired. No cached website rules are being applied.",
      policyFreshness: freshness,
    };
  }
  const policy = snapshot.policy;
  if (!policy.protection_enabled) return { status: "skipped", policy, protectionEnabled: false };

  const rule = MORVIX_POLICY_CACHE.matchingWebsiteRule(snapshot, page.hostname);
  if (!rule) return { status: "continue", policy, policyFreshness: freshness };
  if (rule.action === "warn" || rule.action === "block") {
    await sendOfflineEvent(modality, pageUrl, crypto.randomUUID());
  }
  return {
    status: "result",
    action: rule.action,
    category: "website_rule",
    reason: `Website rule for ${rule.target}.`,
    policy,
  };
}

async function analyzeText(message, sender) {
  const pageUrl = sender.tab?.url;
  if (!pageUrl) return { status: "skipped", reason: "This page is not supported." };
  const gate = await checkSitePolicy(pageUrl, "text");
  if (gate.category === "website_rule" || gate.status !== "continue") return gate;
  if (!gate.policy.modalities?.text) return { status: "skipped", policy: gate.policy };
  const text = String(message.text || "").slice(0, 20000);
  if (!text.trim()) return { status: "skipped", policy: gate.policy };
  try {
    const result = await apiRequest("/extension/classify/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(TEXT_ANALYSIS_TIMEOUT_MS),
      body: JSON.stringify({
        text,
        source_url: MORVIX_MEDIA.pageIdentity(pageUrl).origin,
        event_key: crypto.randomUUID(),
      }),
    });
    await chrome.storage.local.set({ backendOnline: true });
    validateTextAnalysisResult(result);
    return { ...result, analysisStatus: result.status, status: "result", policy: gate.policy };
  } catch (error) {
    if (!error.status && !error.backendReachable) await chrome.storage.local.set({ backendOnline: false });
    return { status: "uncertain", reason: error.message, policy: gate.policy };
  }
}

function validateTextAnalysisResult(result) {
  const allowedStatuses = ["classified", "policy_applied", "skipped"];
  const allowedActions = ["allow", "warn", "block"];
  const isObject = result && typeof result === "object" && !Array.isArray(result);
  const validCategory = result?.category == null || typeof result.category === "string";
  const validConfidence = result?.confidence == null || (
    typeof result.confidence === "number" && Number.isFinite(result.confidence) &&
    result.confidence >= 0 && result.confidence <= 1
  );
  const validClassification = result?.status !== "classified" || (
    typeof result.detected === "boolean" && Array.isArray(result.supported_categories) &&
    result.scores && typeof result.scores === "object" && !Array.isArray(result.scores)
  );
  if (
    !isObject || result.modality !== "text" || !allowedStatuses.includes(result.status) ||
    !allowedActions.includes(result.action) || !validCategory || !validConfidence ||
    typeof result.reason !== "string" || !validClassification
  ) {
    const error = new Error("The local text check returned an invalid response. This page remains open.");
    error.backendReachable = true;
    throw error;
  }
}

async function readBoundedResponse(response, requestedUrl, maxBytes) {
  if (!response.ok || new URL(response.url || requestedUrl).origin !== new URL(requestedUrl).origin) {
    throw new Error("Media is unavailable from this page origin.");
  }
  const type = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  const allowed = ["image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"];
  if (!allowed.includes(type)) throw new Error("MORVIX does not support this media format.");
  const declared = Number(response.headers.get("content-length") || 0);
  if (declared > maxBytes) throw new Error("Media exceeds the backend's configured upload limit.");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("The media response could not be read.");
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new Error("Media exceeds the backend's configured upload limit.");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const blob = new Blob(chunks, { type });
  chunks.length = 0;
  return { blob, type };
}

async function getClassifierReadiness(modality) {
  const cached = classifierReadinessCache.get(modality);
  if (cached && Date.now() - cached.at < CLASSIFIER_READINESS_CACHE_MS) return cached.value;
  const value = await apiRequest(`/extension/readiness?modality=${encodeURIComponent(modality)}`, {
    signal: AbortSignal.timeout(120000),
  });
  classifierReadinessCache.set(modality, { value, at: Date.now() });
  await chrome.storage.local.set({
    classifierReadiness: { ...(await read(["classifierReadiness"])).classifierReadiness, [modality]: value },
    backendOnline: true,
  });
  return value;
}

async function analyzeResource(message, sender) {
  const pageUrl = sender.tab?.url;
  if (!pageUrl) return { status: "skipped", reason: "This page is not supported." };
  const modality = message.modality === "video" ? "video" : "image";
  const gate = await checkSitePolicy(pageUrl, modality);
  if (gate.category === "website_rule" || gate.status !== "continue") return gate;
  if (!gate.policy.modalities?.[modality]) return { status: "skipped", policy: gate.policy };

  let requested;
  try { requested = MORVIX_MEDIA.validateSameOriginUrl(message.url, pageUrl); }
  catch (error) { return { status: "skipped", reason: error.message }; }

  let readiness;
  try {
    readiness = await getClassifierReadiness(modality);
  } catch (error) {
    if (!error.status) await chrome.storage.local.set({ backendOnline: false });
    return { status: "uncertain", modality, reason: error.message };
  }
  const maxBytes = MORVIX_MEDIA.uploadLimit(readiness);
  if (maxBytes === null) {
    return {
      status: "unavailable",
      modality,
      reason: readiness.reason || `The local ${modality} classifier is not ready; media was not uploaded.`,
    };
  }

  let blob, type;
  try {
    const response = await MORVIX_MEDIA.fetchSameOrigin(requested.url, pageUrl, {
      signal: AbortSignal.timeout(15000),
    });
    ({ blob, type } = await readBoundedResponse(response, requested.url, maxBytes));
  } catch (error) {
    return { status: "unavailable", modality, reason: error.message };
  }

  const form = new FormData();
  try {
    form.append("file", blob, modality === "image" ? "page-image" : "page-video");
    const endpoint = modality === "image" ? "/extension/classify/image" : "/extension/classify/video";
    const query = new URLSearchParams({
      source_url: MORVIX_MEDIA.pageIdentity(pageUrl).origin,
      event_key: crypto.randomUUID(),
    });
    const result = await apiRequest(`${endpoint}?${query}`, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(120000),
    });
    await chrome.storage.local.set({ backendOnline: true });
    return { ...result, analysisStatus: result.status, status: "result", modality, mediaType: type };
  } catch (error) {
    if (!error.status) await chrome.storage.local.set({ backendOnline: false });
    return { status: "uncertain", modality, reason: error.message };
  } finally {
    form.delete("file");
    blob = null;
  }
}

async function getStatus() {
  const state = await read([
    "deviceId", "deviceLabel", "cachedPolicy", "lastSyncAt",
    "backendOnline", "apiBase", "configurationError", "policySyncError",
    "enabledOrigins", "offlineEvents", "classifierReadiness",
  ]);
  const safeQueue = sanitizeOfflineQueue(state.offlineEvents);
  if (JSON.stringify(safeQueue) !== JSON.stringify(state.offlineEvents || [])) {
    await chrome.storage.local.set({ offlineEvents: safeQueue });
  }
  delete state.offlineEvents;
  state.offlineEventCount = safeQueue.length;
  if (state.cachedPolicy) state.cachedPolicy = { ...state.cachedPolicy, rules: [] };
  const freshness = MORVIX_POLICY_CACHE.freshness(state.cachedPolicy, state.lastSyncAt);
  const invalidConfig = state.apiBase !== undefined && state.apiBase !== null && state.apiBase !== MORVIX_API_CONFIG.BASE;
  return {
    ...state,
    configurationError: invalidConfig
      ? "Saved MORVIX backend configuration is invalid. Disconnect and pair this browser again."
      : state.configurationError,
    policyFreshness: freshness,
  };
}

async function getContentStatus() {
  const state = await read(["cachedPolicy", "lastSyncAt"]);
  return {
    cachedPolicy: state.cachedPolicy
      ? { ...state.cachedPolicy, rules: [] }
      : null,
    policyFreshness: MORVIX_POLICY_CACHE.freshness(state.cachedPolicy, state.lastSyncAt),
  };
}

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "morvix-analyze-text": return analyzeText(message, sender);
    case "morvix-analyze-resource": return analyzeResource(message, sender);
    case "morvix-check-site-policy": return checkSitePolicy(sender.tab?.url, message.modality || "text");
    case "morvix-sync-policy": return syncPolicy();
    case "morvix-disconnect": await disconnectLocal(); return { disconnected: true };
    case "morvix-get-content-status": return getContentStatus();
    case "morvix-get-status": return getStatus();
    default: return { error: "Unsupported MORVIX request." };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse).catch((error) => sendResponse({ error: error.message }));
  return true;
});

chrome.alarms.create("morvix-policy-sync", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "morvix-policy-sync") syncPolicy().catch(() => {});
});
chrome.runtime.onStartup.addListener(() => syncPolicy().catch(() => {}));
chrome.runtime.onInstalled.addListener(() => syncPolicy().catch(() => {}));
