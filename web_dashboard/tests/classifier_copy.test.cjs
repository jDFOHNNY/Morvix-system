const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const copy = require("../js/classifier_copy.js");

test("classifier status copy distinguishes loaded, pending, and unavailable states", () => {
  assert.match(copy.status("ready").label, /Loaded and validated in this backend process/);
  assert.match(copy.status("available_unloaded").label, /load check pending/);
  assert.match(copy.status("invalid_model_files").label, /snapshot is incomplete or invalid/);
  assert.match(copy.status("loading_failed").label, /model failed to load/);
  assert.match(copy.status("inference_failed").label, /most recent inference failed/);
  assert.match(copy.status("incompatible_checkpoint_labels").label, /Unavailable/);
  assert.equal(copy.status("unexpected").tone, "pill-warn");
});

test("policy controls do not claim unavailable image or unevaluated video detection", () => {
  assert.match(copy.modalityPolicy("image"), /Image detection is unavailable/);
  assert.match(copy.modalityPolicy("image"), /uploads are rejected/);
  assert.match(copy.modalityPolicy("video"), /samples 16 frames/);
  assert.match(copy.modalityPolicy("video"), /ignores audio/);
  assert.match(copy.modalityPolicy("video"), /not been evaluated/);
});

test("category copy identifies candidate mappings and the absent self-harm model", () => {
  assert.match(copy.categoryCoverage("violence"), /video only/);
  assert.match(copy.categoryCoverage("threat_language"), /English toxic-comment threat label/);
  assert.match(copy.categoryCoverage("self_harm_indicators"), /does not detect this category/);
});

test("Settings renders the tested copy and loads it before the dashboard app", () => {
  const root = path.resolve(__dirname, "..");
  const html = readFileSync(path.join(root, "index.html"), "utf8");
  const app = readFileSync(path.join(root, "js", "app.js"), "utf8");
  assert.ok(html.indexOf("classifier_copy.js") < html.indexOf("app.js"));
  assert.match(app, /MorvixClassifierCopy\.modalityPolicy/);
  assert.match(app, /MorvixClassifierCopy\.categoryCoverage/);
  assert.match(app, /MorvixClassifierCopy\.status/);
});
