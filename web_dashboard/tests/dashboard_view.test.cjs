const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const view = require("../js/dashboard_view.js");

test("overview exposes selectable analytics periods and only supported detection channels", () => {
  const markup = view.controlsMarkup(90, "video", ["text", "image", "video"]);
  assert.match(markup, /Analytics time range/);
  assert.match(markup, /value="90" selected>Last 90 days/);
  assert.match(markup, /Recent detection channel/);
  assert.match(markup, /value="video" selected>Video/);
  assert.match(markup, /<option value="all" >All/);
  assert.doesNotMatch(markup, />Audio</);
});

test("overview requests use the selected date range and recent channel filter", () => {
  assert.equal(view.summaryPath(7, "text"), "/dashboard/summary?days=7&modality=text");
  assert.equal(view.summaryPath(365, "all"), "/dashboard/summary?days=365");
  assert.equal(view.summaryPath(7, "audio"), "/dashboard/summary?days=7");
});

test("event history links preserve the selected event in the dashboard route", () => {
  const eventId = "event/with spaces+chars";
  const hash = view.historyEventHash(eventId);
  assert.equal(hash, "#/history?event_id=event%2Fwith%20spaces%2Bchars");
  assert.deepEqual(view.parseRouteHash(hash), { route: "history", eventId });
  assert.deepEqual(view.parseRouteHash("#/history"), { route: "history", eventId: null });
});

test("dashboard app connects overview filters, action analytics, and alert review to real API data", () => {
  const root = path.resolve(__dirname, "..");
  const html = readFileSync(path.join(root, "index.html"), "utf8");
  const app = readFileSync(path.join(root, "js", "app.js"), "utf8");
  assert.ok(html.indexOf("dashboard_view.js") < html.indexOf("app.js"));
  assert.match(app, /MorvixDashboardView\.summaryPath\(state\.dashboard\.days, state\.dashboard\.modality\)/);
  assert.match(app, /addEventListener\("change"/);
  assert.match(app, /distributionRows\(data\.by_action, actionLabel\)/);
  assert.match(app, /overviewAlertRows\(data\.alerts\)/);
  assert.match(app, /data-review-overview-alert/);
  assert.match(app, /Allowed events/);
  assert.match(app, /data\.counts\.allowed/);
  assert.match(app, /historyEventHash\(item\.event_id\)/);
  assert.match(app, /params\.event_id = state\.history\.eventId/);
  assert.match(app, /historyEventHash\(event\.id\)/);
  assert.match(app, /Policy v\$\{Number\(event\.policy_version\)\}/);
  assert.match(app, /Policy version not recorded/);
});

test("account screen always presents traditional registration and the Google option with clear readiness", () => {
  const app = readFileSync(path.resolve(__dirname, "../js/app.js"), "utf8");
  const css = readFileSync(path.resolve(__dirname, "../css/app.css"), "utf8");
  assert.match(app, /data-auth-tab="register">Create account/);
  assert.match(app, /name="email" type="email"/);
  assert.match(app, /name="password" type="password"/);
  assert.match(app, /id="google-fallback"[^>]*disabled[^>]*>Continue with Google/);
  assert.match(app, /settings\.reason \|\| "Google sign-in is unavailable/);
  assert.match(app, /googleFallback\.hidden = true/);
  assert.match(app, /googleButton\.hidden = false/);
  assert.match(app, /Could not check Google sign-in\. Email and password remain available\./);
  assert.match(css, /#google-button\[hidden\].*display:\s*none/);
});
