const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { createConnectionStatusRefresh } = require("../js/connection_status_refresh.js");

function fakeBrowser() {
  const intervals = new Map();
  const windowListeners = new Map();
  const documentListeners = new Map();
  let nextTimer = 1;
  const add = (map, name, callback) => map.set(name, [...(map.get(name) || []), callback]);
  const remove = (map, name, callback) => map.set(name, (map.get(name) || []).filter((item) => item !== callback));
  return {
    intervals,
    windowListeners,
    documentListeners,
    windowRef: {
      setInterval(callback, delay) { const id = nextTimer++; intervals.set(id, { callback, delay }); return id; },
      clearInterval(id) { intervals.delete(id); },
      addEventListener(name, callback) { add(windowListeners, name, callback); },
      removeEventListener(name, callback) { remove(windowListeners, name, callback); },
    },
    documentRef: {
      visibilityState: "visible",
      addEventListener(name, callback) { add(documentListeners, name, callback); },
      removeEventListener(name, callback) { remove(documentListeners, name, callback); },
    },
  };
}

test("connection status refreshes on the interval, focus, and return to a visible tab", async () => {
  const browser = fakeBrowser();
  let active = true;
  let calls = 0;
  const controller = createConnectionStatusRefresh({
    refresh: async () => { calls += 1; },
    isActive: () => active,
    windowRef: browser.windowRef,
    documentRef: browser.documentRef,
  });
  const timer = [...browser.intervals.values()][0];
  assert.equal(timer.delay, 10000);
  timer.callback();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 1);

  browser.documentRef.visibilityState = "hidden";
  browser.windowListeners.get("focus")[0]();
  browser.documentListeners.get("visibilitychange")[0]();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 1);

  browser.documentRef.visibilityState = "visible";
  browser.documentListeners.get("visibilitychange")[0]();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 2);

  active = false;
  browser.windowListeners.get("focus")[0]();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 2);
  controller.stop();
  assert.equal(browser.intervals.size, 0);
  assert.equal(browser.windowListeners.get("focus").length, 0);
  assert.equal(browser.documentListeners.get("visibilitychange").length, 0);
});

test("connection status refresh prevents overlapping requests", async () => {
  const browser = fakeBrowser();
  let calls = 0;
  let finish;
  const controller = createConnectionStatusRefresh({
    refresh: () => { calls += 1; return new Promise((resolve) => { finish = resolve; }); },
    isActive: () => true,
    windowRef: browser.windowRef,
    documentRef: browser.documentRef,
  });
  const callback = [...browser.intervals.values()][0].callback;
  callback();
  callback();
  assert.equal(calls, 1);
  finish();
  await new Promise((resolve) => setImmediate(resolve));
  controller.stop();
});

test("dashboard loads the refresh helper before app code and refreshes only server-reported status", () => {
  const root = path.resolve(__dirname, "..");
  const html = readFileSync(path.join(root, "index.html"), "utf8");
  const app = readFileSync(path.join(root, "js", "app.js"), "utf8");
  assert.ok(html.indexOf("connection_status_refresh.js") < html.indexOf("app.js"));
  assert.match(app, /MorvixConnectionStatusRefresh\.createConnectionStatusRefresh/);
  assert.match(app, /\["dashboard", "settings", "alerts"\]\.includes\(state\.route\)/);
  assert.match(app, /api\("\/devices"\)/);
  assert.match(app, /if \(state\.route === "alerts"\) return refreshAlertsView\?\.\(\)/);
  assert.match(app, /New saved alerts appear within about 10 seconds/);
  assert.match(app, /device\.connected/);
  assert.match(app, /banner\.outerHTML = connectionStatusBanner\(data\)/);
});
