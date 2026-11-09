"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const popupSource = fs.readFileSync(path.resolve(__dirname, "..", "popup.js"), "utf8");

async function renderPopup(imageReadiness) {
  const nodes = new Map();
  const node = (selector) => {
    if (!nodes.has(selector)) {
      nodes.set(selector, {
        textContent: "",
        innerHTML: "",
        className: "",
        style: {},
        classList: { add() {}, remove() {} },
        addEventListener() {},
      });
    }
    return nodes.get(selector);
  };
  let readyHandler;
  const state = {
    deviceId: "paired-device",
    deviceLabel: "Protected browser",
    cachedPolicy: { policy: {
      protection_enabled: true,
      version: 7,
      thresholds: {
        violence: { review: 0.37, block: 0.82 },
        threat_language: { review: 0.43, block: 0.67 },
      },
    }, rules: [] },
    policyFreshness: { fresh: true, maxAgeMinutes: 1440 },
    enabledOrigins: [],
    classifierReadiness: { image: imageReadiness },
    lastSyncAt: "2026-10-16T00:00:00Z",
  };
  const context = {
    URL,
    Date,
    document: {
      querySelector: node,
      addEventListener(event, callback) { if (event === "DOMContentLoaded") readyHandler = callback; },
    },
    chrome: {
      tabs: { query: async () => [] },
      runtime: { sendMessage: async ({ type }) => type === "morvix-get-status" ? state : {} },
    },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(popupSource, context, { filename: "popup.js" });
  await readyHandler();
  return node("#state").innerHTML;
}

test("popup clearly reports unavailable image classification and preserves text protection", async () => {
  const markup = await renderPopup({
    ready: false,
    classifier_status: "incompatible_checkpoint_labels",
    reason: "The checkpoint has no verified image label map.",
  });
  assert.match(markup, /Image classification unavailable/);
  assert.match(markup, /Image checks are skipped/);
  assert.match(markup, /pages stay accessible unless a parent website rule blocks them/);
  assert.match(markup, /Text analysis remains active/);
  assert.match(markup, /no verified image label map/);
  assert.match(markup, /Cached policy v7/);
  assert.match(markup, /Synchronized thresholds: Violence: 37% review \/ 82% block · Threat Language: 43% review \/ 67% block/);
  assert.doesNotMatch(markup, /image classification works/i);
});

test("popup describes a readiness pass without claiming image-classification accuracy", async () => {
  const markup = await renderPopup({ ready: true, classifier_status: "ready" });
  assert.match(markup, /Image model passed runtime checks/);
  assert.match(markup, /does not verify classification accuracy/);
  assert.doesNotMatch(markup, /Image classifier is ready\./);
});
