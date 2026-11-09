"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const nodeCrypto = require("node:crypto");

const root = path.resolve(__dirname, "..");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");

function loadHelpers() {
  const context = { URL, URLSearchParams, Date, Map, AbortSignal, crypto: nodeCrypto, fetch: async () => { throw new Error("Unexpected fetch"); } };
  context.globalThis = context;
  context.importScripts = () => {};
  vm.createContext(context);
  for (const name of ["api_config.js", "media_transport.js", "policy_cache.js"]) {
    vm.runInContext(source(name), context, { filename: name });
  }
  return context;
}

function installBackground(context, store, fetchImplementation) {
  const chrome = {
    storage: { local: {
      get: async (keys) => Object.fromEntries(keys.filter((key) => key in store).map((key) => [key, store[key]])),
      set: async (value) => Object.assign(store, value),
      remove: async (keys) => keys.forEach((key) => delete store[key]),
    } },
    permissions: { remove: async () => true },
    scripting: { unregisterContentScripts: async () => {} },
    runtime: {
      onMessage: { addListener(callback) { context.messageListener = callback; } },
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} },
    },
    alarms: { create() {}, onAlarm: { addListener() {} } },
  };
  context.chrome = chrome;
  context.fetch = fetchImplementation;
  vm.runInContext(source("background.js"), context, { filename: "background.js" });
  return context;
}

test("altered stored backend cannot receive an authenticated extension request", async () => {
  for (const apiBase of [
    "https://collector.example/api/v1",
    "http://127.0.0.1:9000/api/v1",
    "https://127.0.0.1:8000/api/v1",
  ]) {
    const calls = [];
    const context = loadHelpers();
    const store = { apiBase, deviceToken: "device-secret-test-value" };
    const chrome = {
      storage: { local: {
        get: async () => ({ ...store }),
        set: async (value) => Object.assign(store, value),
        remove: async () => {},
      } },
      permissions: { remove: async () => true },
      scripting: { unregisterContentScripts: async () => {} },
      runtime: {
        onMessage: { addListener(callback) { context.messageListener = callback; } },
        onStartup: { addListener() {} },
        onInstalled: { addListener() {} },
      },
      alarms: { create() {}, onAlarm: { addListener() {} } },
    };
    context.chrome = chrome;
    context.fetch = async (...args) => { calls.push(args); throw new Error("Unexpected fetch"); };
    vm.runInContext(source("background.js"), context, { filename: "background.js" });

    const reply = await new Promise((resolve) => {
      context.messageListener({ type: "morvix-sync-policy" }, {}, resolve);
    });
    assert.match(reply.error, /configuration is invalid/i);
    assert.equal(calls.length, 0, `altered destination ${apiBase} must be rejected before fetch`);
    assert.equal(store.configurationError, "Saved MORVIX backend configuration is invalid. Disconnect and pair this browser again.");
  }
});

test("approved API requests use the single loopback endpoint and reject redirects", async () => {
  const context = loadHelpers();
  let call;
  await context.MORVIX_API_CONFIG.fetchAuthenticated(
    "/extension/policy", "device-token", context.MORVIX_API_CONFIG.BASE,
    {}, async (url, options) => { call = { url, options }; return { ok: true }; },
  );
  assert.equal(call.url, "http://127.0.0.1:8000/api/v1/extension/policy");
  assert.equal(call.options.headers.Authorization, "Bearer device-token");
  assert.equal(call.options.redirect, "error");
  assert.equal(call.options.credentials, "omit");
});

test("extension status never exposes the device bearer token to the popup or content script", async () => {
  const context = loadHelpers();
  const store = { deviceId: "device-id", deviceToken: "private-bearer-token", cachedPolicy: null };
  context.chrome = {
    storage: { local: {
      get: async (keys) => Object.fromEntries(keys.filter((key) => key in store).map((key) => [key, store[key]])),
      set: async (value) => Object.assign(store, value),
      remove: async () => {},
    } },
    permissions: { remove: async () => true },
    scripting: { unregisterContentScripts: async () => {} },
    runtime: {
      onMessage: { addListener(callback) { context.messageListener = callback; } },
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} },
    },
    alarms: { create() {}, onAlarm: { addListener() {} } },
  };
  vm.runInContext(source("background.js"), context, { filename: "background.js" });
  const status = await new Promise((resolve) => {
    context.messageListener({ type: "morvix-get-status" }, {}, resolve);
  });
  assert.equal(Object.hasOwn(status, "deviceToken"), false);
  assert.equal(JSON.stringify(status).includes(store.deviceToken), false);
});

test("successful backend text classification is normalized for the content-script result handler", async () => {
  const context = loadHelpers();
  const snapshot = {
    policy: { protection_enabled: true, modalities: { text: true, image: false, video: false } },
    rules: [],
    cache_max_age_minutes: 1440,
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy: snapshot,
    lastSyncAt: new Date().toISOString(),
  };
  let request;
  installBackground(context, store, async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      url,
      json: async () => ({
        status: "classified", modality: "text", category: "threat_language", confidence: 0.64,
        scores: { threat_language: 0.64 }, classifier: "experimental-text-model",
        supported_categories: ["threat_language"], detected: true, action: "warn",
        reason: "Configured review threshold reached.", event_id: "persisted-event-id",
      }),
    };
  });
  const response = await new Promise((resolve) => {
    context.messageListener(
      { type: "morvix-analyze-text", text: "controlled visible page text" },
      { tab: { url: "http://localhost:8001/controlled/page?private=1" } },
      resolve,
    );
  });
  assert.equal(request.url, "http://127.0.0.1:8000/api/v1/extension/classify/text");
  assert.equal(request.options.headers.Authorization, "Bearer local-only-token");
  assert.equal(JSON.parse(request.options.body).source_url, "http://localhost:8001");
  assert.equal(response.status, "result", "content.js recognizes this as a successful analysis result");
  assert.equal(response.analysisStatus, "classified", "the backend classifier status remains available");
  assert.equal(response.category, "threat_language");
  assert.equal(response.action, "warn");
  assert.equal(response.event_id, "persisted-event-id");
});

test("a backend block action for a 64 percent result reaches the content-script result handler unchanged", async () => {
  const context = loadHelpers();
  const snapshot = {
    policy: { protection_enabled: true, modalities: { text: true, image: false, video: false }, version: 3 },
    rules: [{ kind: "category", target: "threat_language", action: "block", enabled: true }],
    cache_max_age_minutes: 1440,
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy: snapshot,
    lastSyncAt: new Date().toISOString(),
  };
  installBackground(context, store, async (url) => ({
    ok: true,
    url,
    json: async () => ({
      status: "classified", modality: "text", category: "threat_language", confidence: 0.6422476172447205,
      scores: { threat_language: 0.6422476172447205 }, classifier: "experimental-text-model",
      supported_categories: ["threat_language"], detected: true, action: "block",
      reason: "Category action from a protection rule.", event_id: "persisted-block-event", policy_version: 3,
    }),
  }));
  const response = await new Promise((resolve) => context.messageListener(
    { type: "morvix-analyze-text", text: "controlled threat-language sample" },
    { tab: { url: "http://127.0.0.1:8001/threat-only.html" } }, resolve,
  ));
  assert.equal(response.status, "result");
  assert.equal(response.confidence, 0.6422476172447205);
  assert.equal(response.action, "block");
  assert.equal(response.event_id, "persisted-block-event");
  assert.equal(response.policy_version, 3, "the server-applied policy version reaches the content script");
});

test("policy synchronization replaces the extension cache with the persisted thresholds and version", async () => {
  const context = loadHelpers();
  const policy = {
    protection_enabled: true,
    modalities: { text: true, image: true, video: true },
    category_actions: { violence: "warn", threat_language: "block", self_harm_indicators: "warn" },
    thresholds: {
      violence: { review: 0.37, block: 0.82 },
      threat_language: { review: 0.43, block: 0.67 },
      self_harm_indicators: { review: 0.5, block: 0.9 },
    },
    version: 18,
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "test-device-token",
    cachedPolicy: { policy: { ...policy, version: 17 }, rules: [] },
    lastSyncAt: "2026-01-01T00:00:00Z",
  };
  installBackground(context, store, async (url) => ({
    ok: true,
    url,
    json: async () => ({
      policy,
      rules: [],
      cache_max_age_minutes: 1440,
      last_synced_at: new Date().toISOString(),
    }),
  }));

  const result = await new Promise((resolve) => {
    context.messageListener({ type: "morvix-sync-policy" }, {}, resolve);
  });

  assert.equal(result.policy.version, 18);
  assert.deepEqual(JSON.parse(JSON.stringify(store.cachedPolicy.policy.thresholds)), policy.thresholds);
  assert.equal(store.cachedPolicy.policy.category_actions.threat_language, "block");
  assert.equal(store.policySyncError, null);
});

test("malformed successful text responses remain uncertain and never trigger a block", async () => {
  const context = loadHelpers();
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy: { policy: { protection_enabled: true, modalities: { text: true } }, rules: [], cache_max_age_minutes: 1440 },
    lastSyncAt: new Date().toISOString(),
  };
  installBackground(context, store, async (url) => ({
    ok: true,
    url,
    json: async () => ({
      status: "classified", modality: "text", category: "threat_language", confidence: "not-a-number",
      action: "block", reason: "Malformed test response.", detected: true,
      supported_categories: ["threat_language"], scores: { threat_language: 0.8 },
    }),
  }));
  const response = await new Promise((resolve) => context.messageListener(
    { type: "morvix-analyze-text", text: "controlled page text" },
    { tab: { url: "http://localhost:8001/" } },
    resolve,
  ));
  assert.equal(response.status, "uncertain");
  assert.equal(response.action, undefined);
  assert.match(response.reason, /invalid response/i);
  assert.equal(store.backendOnline, true, "a malformed response still proves the backend answered");
});

test("text request timeout and backend outage return a visible non-blocking uncertain result", async () => {
  for (const message of ["Text analysis timed out.", "local backend offline"]) {
    const context = loadHelpers();
    const store = {
      apiBase: context.MORVIX_API_CONFIG.BASE,
      deviceToken: "local-only-token",
      cachedPolicy: { policy: { protection_enabled: true, modalities: { text: true } }, rules: [], cache_max_age_minutes: 1440 },
      lastSyncAt: new Date().toISOString(),
    };
    let requestOptions;
    installBackground(context, store, async (_url, options) => {
      requestOptions = options;
      const error = new Error(message);
      if (message.includes("timed out")) error.name = "TimeoutError";
      throw error;
    });
    const response = await new Promise((resolve) => context.messageListener(
      { type: "morvix-analyze-text", text: "controlled page text" },
      { tab: { url: "http://localhost:8001/" } },
      resolve,
    ));
    assert.ok(requestOptions.signal, "text classification request has a bounded timeout");
    assert.equal(response.status, "uncertain");
    assert.equal(response.action, undefined, "a failed local check must not block the page");
    assert.match(response.reason, new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
    assert.equal(store.backendOnline, false);
  }
});

test("text requests remain capped at 20,000 characters in the service worker", async () => {
  const context = loadHelpers();
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy: { policy: { protection_enabled: true, modalities: { text: true } }, rules: [], cache_max_age_minutes: 1440 },
    lastSyncAt: new Date().toISOString(),
  };
  let payload;
  installBackground(context, store, async (url, options) => {
    payload = JSON.parse(options.body);
    return {
      ok: true,
      url,
      json: async () => ({
        status: "classified", modality: "text", category: null, confidence: 0.1,
        action: "allow", reason: "Below review threshold.", detected: false,
        supported_categories: ["threat_language"], scores: { threat_language: 0.1 },
      }),
    };
  });
  const response = await new Promise((resolve) => context.messageListener(
    { type: "morvix-analyze-text", text: "x".repeat(20_500) },
    { tab: { url: "http://localhost:8001/" } },
    resolve,
  ));
  assert.equal(response.status, "result");
  assert.equal(payload.text.length, 20_000);
});

test("legacy queued full URLs are sanitized before storage and are not returned in extension status", async () => {
  const context = loadHelpers();
  const store = {
    deviceId: "device-id",
    cachedPolicy: null,
    offlineEvents: [{
      modality: "text",
      source_url: "https://news.example/private/path?session=old#fragment",
      event_key: "legacy-event-key-01",
    }],
  };
  installBackground(context, store, async () => { throw new Error("Unexpected fetch"); });
  const status = await new Promise((resolve) => {
    context.messageListener({ type: "morvix-get-status" }, {}, resolve);
  });
  assert.equal(store.offlineEvents[0].source_url, "https://news.example");
  assert.equal(status.offlineEventCount, 1);
  assert.equal(Object.hasOwn(status, "offlineEvents"), false);
  assert.equal(JSON.stringify(status).includes("session=old"), false);
});

test("cached website rules apply before text eligibility and queue only the page origin offline", async () => {
  const context = loadHelpers();
  const cachedPolicy = {
    cache_max_age_minutes: 1440,
    policy: { protection_enabled: true, modalities: { text: false, image: false, video: false } },
    rules: [{ kind: "website", target: "example.test", action: "block", enabled: true }],
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy,
    lastSyncAt: new Date().toISOString(),
    offlineEvents: [],
  };
  let request;
  installBackground(context, store, async (url, options) => {
    request = { url, options };
    throw new Error("local backend offline");
  });
  const result = await new Promise((resolve) => {
    context.messageListener(
      { type: "morvix-check-site-policy", modality: "text" },
      { tab: { url: "https://sub.example.test/private/path?session=secret#fragment" } },
      resolve,
    );
  });
  assert.equal(result.action, "block");
  assert.equal(result.category, "website_rule");
  assert.equal(request.url, "http://127.0.0.1:8000/api/v1/extension/offline-events");
  assert.equal(request.options.headers.Authorization, "Bearer local-only-token");
  assert.equal(JSON.parse(request.options.body).source_url, "https://sub.example.test");
  assert.equal(store.offlineEvents.length, 1);
  assert.equal(store.offlineEvents[0].source_url, "https://sub.example.test");
  assert.equal(store.offlineEvents[0].source_url.includes("/private"), false);
  assert.equal(store.offlineEvents[0].source_url.includes("session"), false);
});

test("expired cached policy is retained but not applied while the backend is unavailable", async () => {
  const context = loadHelpers();
  const cachedPolicy = {
    cache_max_age_minutes: 1,
    policy: { protection_enabled: true, modalities: { text: true, image: true, video: true } },
    rules: [{ kind: "website", target: "example.test", action: "block", enabled: true }],
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy,
    lastSyncAt: new Date(Date.now() - 2 * 60_000).toISOString(),
    offlineEvents: [],
  };
  installBackground(context, store, async () => { throw new Error("local backend offline"); });
  const result = await new Promise((resolve) => {
    context.messageListener(
      { type: "morvix-check-site-policy", modality: "text" },
      { tab: { url: "https://sub.example.test/private" } },
      resolve,
    );
  });
  assert.equal(result.status, "offline");
  assert.match(result.reason, /local backend offline/i);
  assert.equal(store.cachedPolicy, cachedPolicy, "the last valid snapshot is preserved for a later successful sync");
  assert.equal(store.offlineEvents.length, 0, "expired cached rules must not create events");
});

test("offline event queue stays bounded and retries preserve the original idempotency key", async () => {
  let context = loadHelpers();
  const cachedPolicy = {
    cache_max_age_minutes: 1440,
    policy: { protection_enabled: true, modalities: { text: true, image: true, video: true } },
    rules: [{ kind: "website", target: "example.test", action: "block", enabled: true }],
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy,
    lastSyncAt: new Date().toISOString(),
    offlineEvents: [],
  };
  installBackground(context, store, async () => { throw new Error("offline"); });
  for (let index = 0; index < 101; index += 1) {
    await new Promise((resolve) => {
      context.messageListener(
        { type: "morvix-check-site-policy", modality: "text" },
        { tab: { url: `https://sub.example.test/story/${index}?private=1` } },
        resolve,
      );
    });
  }
  assert.equal(store.offlineEvents.length, 100);
  assert.equal(store.offlineEvents.some((item) => item.source_url.includes("/story/")), false);

  const queued = store.offlineEvents[0];
  store.offlineEvents = [queued];
  let retried;
  context = loadHelpers();
  installBackground(context, store, async (url, options) => {
    if (url.endsWith("/extension/policy")) {
      return {
        ok: true,
        url,
        json: async () => ({
          policy: cachedPolicy.policy,
          rules: cachedPolicy.rules,
          cache_max_age_minutes: 1440,
          last_synced_at: new Date().toISOString(),
        }),
      };
    }
    retried = JSON.parse(options.body);
    throw new Error("response lost after server received the event");
  });
  await new Promise((resolve) => {
    context.messageListener({ type: "morvix-sync-policy" }, {}, resolve);
  });
  assert.equal(retried.event_key, queued.event_key);
  assert.equal(retried.source_url, queued.source_url);
  assert.equal(store.offlineEvents.length, 1);
  assert.equal(store.offlineEvents[0].event_key, queued.event_key);
});

test("same-origin media is fetched without credentials and with redirects disabled", async () => {
  const context = loadHelpers();
  let call;
  const response = { ok: true, url: "https://news.example/story/image.jpg" };
  const result = await context.MORVIX_MEDIA.fetchSameOrigin(
    "https://news.example/story/image.jpg", "https://news.example/article/1",
    {}, async (url, options) => { call = { url, options }; return response; },
  );
  assert.equal(result, response);
  assert.equal(call.options.redirect, "error");
  assert.equal(call.options.credentials, "omit");
});

test("cross-origin media is rejected before a request is made", async () => {
  const context = loadHelpers();
  let calls = 0;
  await assert.rejects(context.MORVIX_MEDIA.fetchSameOrigin(
    "https://cdn.example/image.jpg", "https://news.example/article",
    {}, async () => { calls += 1; return { ok: true }; },
  ), /Cross-origin/);
  assert.equal(calls, 0);
});

test("cross-origin redirect response is rejected before media is accepted", async () => {
  const context = loadHelpers();
  let redirectMode;
  await assert.rejects(context.MORVIX_MEDIA.fetchSameOrigin(
    "https://news.example/image.jpg", "https://news.example/article",
    {}, async (_url, options) => {
      redirectMode = options.redirect;
      // Simulates a response that a noncompliant fetch implementation followed.
      return { ok: true, url: "https://elsewhere.example/image.jpg" };
    },
  ), /crossed to another origin/);
  assert.equal(redirectMode, "error");
});

test("image upload is gated on actual classifier readiness and the backend limit", () => {
  const { MORVIX_MEDIA } = loadHelpers();
  assert.equal(MORVIX_MEDIA.uploadLimit({ ready: false, max_upload_bytes: 8_388_608 }), null);
  assert.equal(MORVIX_MEDIA.uploadLimit({ ready: true, max_upload_bytes: 8_388_608 }), 8_388_608);
  assert.equal(MORVIX_MEDIA.uploadLimit({ ready: true, max_upload_bytes: "invalid" }), null);
});

test("an unavailable image classifier is saved for the popup and prevents page-image upload", async () => {
  const context = loadHelpers();
  const snapshot = {
    policy: { protection_enabled: true, modalities: { text: true, image: true, video: false } },
    rules: [],
    cache_max_age_minutes: 1440,
  };
  const store = {
    apiBase: context.MORVIX_API_CONFIG.BASE,
    deviceToken: "local-only-token",
    cachedPolicy: snapshot,
    lastSyncAt: new Date().toISOString(),
  };
  const requests = [];
  installBackground(context, store, async (url, options) => {
    requests.push({ url, options });
    assert.match(url, /\/extension\/readiness\?modality=image$/);
    return {
      ok: true,
      url,
      json: async () => ({
        modality: "image",
        ready: false,
        classifier_status: "incompatible_checkpoint_labels",
        reason: "The checkpoint has no verified image label map.",
        max_upload_bytes: 8_388_608,
      }),
    };
  });

  const result = await new Promise((resolve) => context.messageListener(
    { type: "morvix-analyze-resource", modality: "image", url: "https://news.example.test/hero.jpg" },
    { tab: { url: "https://news.example.test/story" } },
    resolve,
  ));
  assert.equal(result.status, "unavailable");
  assert.equal(requests.length, 1, "the only backend request is readiness preflight");
  assert.equal(store.classifierReadiness.image.ready, false);
  assert.equal(store.classifierReadiness.image.classifier_status, "incompatible_checkpoint_labels");

  const popupStatus = await new Promise((resolve) => context.messageListener(
    { type: "morvix-get-status" }, {}, resolve,
  ));
  assert.equal(popupStatus.classifierReadiness.image.reason, "The checkpoint has no verified image label map.");
});

test("page metadata strips paths, query strings, and fragments", () => {
  const { MORVIX_MEDIA } = loadHelpers();
  assert.deepEqual(
    JSON.parse(JSON.stringify(MORVIX_MEDIA.pageIdentity("https://news.example/story/private?q=secret#part"))),
    { origin: "https://news.example", hostname: "news.example" },
  );
});

test("cached rules are valid only for the configured policy age and match subdomains", () => {
  const { MORVIX_POLICY_CACHE } = loadHelpers();
  const snapshot = {
    cache_max_age_minutes: 5,
    rules: [
      { kind: "website", target: "example.com", action: "warn", enabled: true },
      { kind: "website", target: "news.example.com", action: "block", enabled: true },
    ],
  };
  const synced = "2026-01-01T00:00:00.000Z";
  const fresh = MORVIX_POLICY_CACHE.freshness(snapshot, synced, Date.parse(synced) + 4 * 60_000);
  const expired = MORVIX_POLICY_CACHE.freshness(snapshot, synced, Date.parse(synced) + 6 * 60_000);
  const future = MORVIX_POLICY_CACHE.freshness(snapshot, new Date(Date.parse(synced) + 10 * 60_000).toISOString(), Date.parse(synced));
  assert.equal(fresh.fresh, true);
  assert.equal(fresh.maxAgeMinutes, 5);
  assert.equal(expired.fresh, false);
  assert.equal(future.fresh, false);
  assert.equal(MORVIX_POLICY_CACHE.matchingWebsiteRule(snapshot, "article.news.example.com").action, "block");
});
