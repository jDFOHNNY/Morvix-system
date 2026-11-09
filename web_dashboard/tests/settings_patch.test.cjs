"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const helperSource = fs.readFileSync(path.join(root, "js", "settings_patch.js"), "utf8");
const appSource = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");

function loadHelper() {
  const context = { globalThis: null };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(helperSource, context, { filename: "settings_patch.js" });
  return context.MORVIX_SETTINGS_PATCH;
}

test("dashboard threshold edits create a partial patch with the selected percentages", () => {
  const changes = loadHelper().create();
  const helper = loadHelper();
  helper.setThreshold(changes, "threat_language", "block", "64");
  helper.setThreshold(changes, "violence", "review", "37");

  assert.deepEqual(JSON.parse(JSON.stringify(changes)), {
    thresholds: {
      threat_language: { block: 0.64 },
      violence: { review: 0.37 },
    },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(helper.copy(changes))), JSON.parse(JSON.stringify(changes)));
});

test("dashboard sends only edited settings and displays a save error instead of success", () => {
  assert.match(html, /settings_patch\.js[\s\S]*app\.js/);
  assert.match(appSource, /api\("\/settings", \{ method: "PATCH", body: JSON\.stringify\(MORVIX_SETTINGS_PATCH\.copy\(pendingSettings\)\) \}\)/);
  assert.match(appSource, /saved\.thresholds\?\.\[category\]\?\.\[threshold\] !== value/);
  assert.match(appSource, /catch \(error\) \{ errorText\.textContent = error\.message; button\.disabled = false; \}/);
  assert.match(appSource, /Array\.isArray\(data\.detail\)[\s\S]*map\(\(item\) => item\?\.msg\)/);
  assert.match(appSource, /const \[settings, devices, readiness\] = await Promise\.all\(\[api\("\/settings"\)/);
});
