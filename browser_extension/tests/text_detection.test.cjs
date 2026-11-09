"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const extensionRoot = path.resolve(__dirname, "..");
const contentSource = fs.readFileSync(path.join(extensionRoot, "content.js"), "utf8");

function runContentScript(initialText, textEnabled = true, analyzeResponse = async () => ({ status: "result", action: "allow" }), options = {}) {
  const submitted = [];
  const resourceRequests = [];
  const observers = [];
  const notices = [];
  let historyBacks = 0;
  const body = {};
  const nodes = [makeTextNode(initialText)];
  const images = options.images || [];
  function element(tagName) {
    return {
      tagName,
      style: {},
      children: [],
      attributes: {},
      listeners: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name] ?? null; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      append(...children) { this.children.push(...children); },
      attachShadow() {
        this.shadow = { children: [], append(...children) { this.children.push(...children); } };
        return this.shadow;
      },
      remove() { this.removed = true; },
    };
  }
  const document = {
    readyState: "complete",
    body,
    images,
    documentElement: { append(node) { notices.push(node); } },
    createTreeWalker() {
      let index = 0;
      return { nextNode() { return index < nodes.length ? (this.currentNode = nodes[index++], true) : false; } };
    },
    createRange() {
      return {
        selectNodeContents(node) { this.node = node; },
        getClientRects() { return this.node.visible ? [{ width: 20, height: 12 }] : []; },
      };
    },
    createElement(tagName) { return element(tagName); },
    getElementById() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  class FakeMutationObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() {}
  }
  const context = {
    window: { addEventListener() {} },
    history: { length: 2, back() { historyBacks += 1; } },
    document,
    NodeFilter: { SHOW_TEXT: 4 },
    MutationObserver: FakeMutationObserver,
    innerHeight: 800,
    innerWidth: 1000,
    getComputedStyle: () => ({ display: "block", visibility: "visible", opacity: "1" }),
    chrome: { runtime: { sendMessage: async (message) => {
      if (options.runtimeError) throw new Error(options.runtimeError);
      if (message.type === "morvix-analyze-text") {
        submitted.push(message.text);
        return analyzeResponse(message, submitted.length);
      }
      if (message.type === "morvix-analyze-resource") {
        resourceRequests.push(message);
        return options.resourceResponse?.(message, resourceRequests.length) || { status: "unavailable", modality: message.modality };
      }
      if (message.type === "morvix-check-site-policy") {
        return options.sitePolicyResponse || { status: "continue", policy: { protection_enabled: true, modalities: { text: textEnabled, image: Boolean(options.imageEnabled), video: false } } };
      }
      if (message.type === "morvix-get-content-status") {
        return { cachedPolicy: { policy: { protection_enabled: true, modalities: { image: Boolean(options.imageEnabled), video: false } } }, policyFreshness: { fresh: true } };
      }
      return {};
    } } },
    setTimeout,
    clearTimeout,
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(contentSource, context, { filename: "content.js" });
  return {
    submitted,
    notices,
    resourceRequests,
    get historyBacks() { return historyBacks; },
    addText(value) {
      nodes.push(makeTextNode(value));
      observers[0]?.callback([{ type: "childList", target: body }]);
    },
  };
}

function makeTextNode(value) {
  return {
    nodeValue: value,
    visible: true,
    parentElement: { closest: () => null },
  };
}

test("analyzes visible page text shorter than 21 characters", async () => {
  const page = runContentScript("I will hurt you.");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(page.submitted, ["I will hurt you."]);
});

test("does not submit page text when the parent has disabled text analysis", async () => {
  const page = runContentScript("A visible page sentence.", false);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(page.submitted, []);
});

test("rescans changed text added after the initial page scan", async () => {
  const page = runContentScript("A calm article.");
  await new Promise((resolve) => setImmediate(resolve));
  page.addText(" New text loaded later.");
  await new Promise((resolve) => setTimeout(resolve, 750));
  assert.equal(page.submitted.length, 2);
  assert.equal(page.submitted[1], "A calm article. New text loaded later.");
});

test("does not resubmit an unchanged page after a DOM mutation", async () => {
  const page = runContentScript("An unchanged article.");
  await new Promise((resolve) => setImmediate(resolve));
  page.addText("   ");
  await new Promise((resolve) => setTimeout(resolve, 750));
  assert.equal(page.submitted.length, 1);
});

test("reports an unexpected text response as an uncertain non-blocking notice", async () => {
  const page = runContentScript("A visible article.", true, async () => ({ error: "Malformed local classifier response." }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(page.notices.length, 1);
  const panel = page.notices[0].shadow.children[0];
  assert.equal(panel.children[1].textContent, "MORVIX could not check this content");
  assert.match(panel.children[2].textContent, /Malformed local classifier response/);
});

test("an invalidated extension context asks for a page refresh without surfacing the raw exception", async () => {
  const page = runContentScript("A visible article.", true, async () => ({ status: "result", action: "allow" }), {
    runtimeError: "Extension context invalidated.",
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(page.notices.length, 1);
  const panel = page.notices[0].shadow.children[0];
  assert.match(panel.children[2].textContent, /MORVIX was reloaded\. Refresh this page/);
  assert.doesNotMatch(panel.children[2].textContent, /Extension context invalidated/i);
  assert.doesNotMatch(page.notices[0].style.cssText, /pointer-events:auto/);
});

test("renders warning and blocking actions with their matching parent-policy notice", async () => {
  const warning = runContentScript("A reviewed warning sample.", true, async () => ({
    status: "result", category: "threat_language", action: "warn", reason: "Parent review rule.",
  }));
  await new Promise((resolve) => setImmediate(resolve));
  const warningPanel = warning.notices[0].shadow.children[0];
  assert.equal(warningPanel.children[1].textContent, "Review before continuing");
  assert.equal(warningPanel.children[3].children[0].textContent, "Continue");

  const blocked = runContentScript("A blocked sample.", true, async () => ({
    status: "result", category: "threat_language", confidence: 0.6422476172447205,
    action: "block", reason: "Parent category rule and configured block threshold.", event_id: "persisted-block-event",
  }));
  await new Promise((resolve) => setImmediate(resolve));
  const blockedPanel = blocked.notices[0].shadow.children[0];
  assert.equal(blockedPanel.children[1].textContent, "This content was blocked");
  assert.equal(blockedPanel.getAttribute("role"), "alertdialog");
  assert.equal(blockedPanel.children[3].children[0].textContent, "Go back");
  assert.match(blocked.notices[0].style.cssText, /pointer-events:auto/);
  blockedPanel.children[3].children[0].listeners.click();
  assert.equal(blocked.historyBacks, 1, "the block interface invokes browser back navigation");
});

test("image-classifier unavailability leaves the page clear while text warnings still render", async () => {
  const image = {
    currentSrc: "https://news.example.test/hero.jpg",
    naturalWidth: 640,
    getBoundingClientRect: () => ({ width: 640, height: 360, bottom: 360, right: 640, top: 0, left: 0 }),
  };
  const page = runContentScript("A visible threat sample.", true, async () => ({
    status: "result", category: "threat_language", action: "warn", event_id: "saved-text-event",
  }), {
    imageEnabled: true,
    images: [image],
    resourceResponse: async () => ({
      status: "unavailable", modality: "image", reason: "No verified image label map.",
    }),
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(page.submitted, ["A visible threat sample."]);
  assert.equal(page.resourceRequests.length, 1);
  assert.equal(page.notices.length, 1, "only the existing text warning is shown");
  assert.equal(page.notices[0].shadow.children[0].children[1].textContent, "Review before continuing");
  assert.doesNotMatch(page.notices[0].shadow.children[0].children[1].textContent, /could not check/i);
});

test("image-classifier unavailability by itself does not create a page overlay", async () => {
  const image = {
    currentSrc: "https://news.example.test/hero.jpg",
    naturalWidth: 640,
    getBoundingClientRect: () => ({ width: 640, height: 360, bottom: 360, right: 640, top: 0, left: 0 }),
  };
  const page = runContentScript("", false, async () => ({ status: "result", action: "allow" }), {
    imageEnabled: true,
    images: [image],
    resourceResponse: async () => ({ status: "unavailable", modality: "image", reason: "No verified image label map." }),
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(page.submitted, [], "text remains independently disabled by policy");
  assert.equal(page.resourceRequests.length, 1, "readiness is still checked for enabled image analysis");
  assert.deepEqual(page.notices, [], "image unavailability alone is reported in the popup, not over the page");
});

test("an independent parent website block still takes effect before image analysis", async () => {
  const page = runContentScript("A visible article.", true, async () => ({ status: "result", action: "allow" }), {
    imageEnabled: true,
    sitePolicyResponse: {
      status: "result", action: "block", category: "website_rule", reason: "Parent website rule.",
    },
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(page.notices.length, 1);
  assert.equal(page.notices[0].shadow.children[0].children[1].textContent, "This content was blocked");
  assert.deepEqual(page.submitted, []);
  assert.deepEqual(page.resourceRequests, []);
});

test("retries an unchanged snapshot after a temporary failure when the page changes", async () => {
  const page = runContentScript("A visible article.", true, async (_message, attempt) => (
    attempt === 1
      ? { status: "uncertain", reason: "Local backend timed out." }
      : { status: "result", action: "allow" }
  ));
  await new Promise((resolve) => setImmediate(resolve));
  page.addText(" A later sentence.");
  await new Promise((resolve) => setTimeout(resolve, 750));
  assert.equal(page.submitted.length, 2);
  assert.equal(page.notices.length, 1, "the successful allow result clears the temporary warning");
  assert.equal(page.notices[0].removed, true);
});
