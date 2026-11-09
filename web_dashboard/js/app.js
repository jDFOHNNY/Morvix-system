"use strict";

const API = "/api/v1";
const CATEGORIES = [
  { key: "violence", label: "Violence (candidate)" },
  { key: "threat_language", label: "Threat Language" },
  { key: "self_harm_indicators", label: "Self-harm Indicators" },
];
const NAV = [
  ["dashboard", "Overview", "◫"],
  ["history", "Detection History", "▤"],
  ["alerts", "Alerts", "!"],
  ["rules", "Protection Rules", "◇"],
  ["settings", "Settings", "⚙"],
];
const state = { user: null, route: "dashboard", dashboard: { days: 30, modality: "all" }, history: { page: 1, page_size: 20, eventId: null }, alertItems: [], rules: [], settings: null, devices: [] };
const root = document.getElementById("app");
const dialog = document.getElementById("rule-dialog");
let connectionStatusRefresh = null;
let refreshAlertsView = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}
function categoryLabel(key) { return CATEGORIES.find((item) => item.key === key)?.label || key || "Unclassified"; }
function showToast(message, isError = false) {
  const toast = document.createElement("div");
  toast.className = `toast${isError ? " error" : ""}`;
  toast.textContent = message;
  document.getElementById("toast-region").append(toast);
  setTimeout(() => toast.remove(), 4200);
}
async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item?.msg).filter(Boolean).join(" ")
      : data.detail;
    throw new Error(typeof detail === "string" && detail ? detail : `Request failed (${response.status}).`);
  }
  return data;
}
function setRoute(route) {
  state.route = route;
  location.hash = `#/${route}`;
  render();
}
function shell(title, subtitle, content) {
  const initials = (state.user?.name || "P").trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">M</span><div><p class="brand-name">MORVIX</p><span class="brand-sub">Content protection</span></div></div>
        <div class="nav-label">Parent console</div>
        <nav class="nav-list" aria-label="Main navigation">
          ${NAV.map(([key, label, icon]) => `<a class="nav-link" href="#/${key}" ${state.route === key ? 'aria-current="page"' : ""}><span class="nav-icon" aria-hidden="true">${icon}</span>${label}</a>`).join("")}
        </nav>
        <div class="sidebar-foot"><p>Protection applies only to content MORVIX can access and analyze.</p><button class="btn" data-action="logout"><span aria-hidden="true">↪</span> Sign out</button></div>
      </aside>
      <main class="main-area">
        <header class="topbar">
          <div><span class="eyebrow">MORVIX parent console</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div>
          <div class="account-chip"><span class="avatar" aria-hidden="true">${escapeHtml(initials)}</span><span class="account-details"><span class="account-name">${escapeHtml(state.user?.name)}</span><span class="account-email">${escapeHtml(state.user?.email)}</span></span></div>
        </header>
        <section id="view">${content || `<p class="loading">Loading your account data…</p>`}</section>
      </main>
    </div>`;
  root.querySelectorAll('[data-action="logout"]').forEach((button) => button.addEventListener("click", logout));
}
function pageHeading(eyebrow, title, description, action = "") {
  return `<div class="page-heading"><div><span class="eyebrow">${escapeHtml(eyebrow)}</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>${action}</div>`;
}
function actionPill(action) {
  const className = action === "block" ? "pill-block" : action === "warn" ? "pill-warn" : "pill-allow";
  const label = action === "warn" ? "Flagged" : action === "block" ? "Blocked" : "Allowed";
  return `<span class="pill ${className}">${label}</span>`;
}
function formatDate(value) {
  if (!value) return "Not seen yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString();
}
function emptyState(message, detail = "New activity will appear here when a paired extension records it.") {
  return `<div class="empty"><strong>${escapeHtml(message)}</strong><span>${escapeHtml(detail)}</span></div>`;
}
function distributionRows(values = {}, labelFor = categoryLabel) {
  const entries = Object.entries(values);
  if (!entries.length) return emptyState("No recorded activity yet", "These totals use saved detection events, not sample figures.");
  const max = Math.max(1, ...entries.map(([, count]) => Number(count)));
  return `<div class="distribution">${entries.map(([name, count]) => `<div class="distribution-row"><span>${escapeHtml(labelFor(name))}</span><div class="bar-track"><div class="bar-fill" style="width:${Number(count) > 0 ? Math.max(2, Number(count) / max * 100) : 0}%"></div></div><span class="bar-value">${Number(count)}</span></div>`).join("")}</div>`;
}
function actionLabel(action) { return ({ allow: "Allowed", warn: "Flagged", block: "Blocked" })[action] || action; }
function modalityLabel(modality) { return modality ? modality[0].toUpperCase() + modality.slice(1) : "Unknown"; }
function eventRows(items = [], includeReview = false) {
  if (!items.length) return `<tr><td colspan="${includeReview ? 7 : 6}">${emptyState("No detections match", "Try clearing a filter or wait for a paired extension to record activity.")}</td></tr>`;
  return items.map((event) => `<tr>
    <td>${escapeHtml(formatDate(event.occurred_at))}</td>
    <td><strong>${escapeHtml(event.source_domain || "Local analysis")}</strong><small>${escapeHtml(event.modality)}</small></td>
    <td>${escapeHtml(categoryLabel(event.category))}</td>
    <td>${event.confidence == null ? "—" : `${Math.round(Number(event.confidence) * 100)}%`}</td>
    <td>${actionPill(event.action)}<small>${event.policy_version == null ? "Policy version not recorded" : `Policy v${Number(event.policy_version)}`}</small></td>
    ${includeReview ? `<td>${event.reviewed ? '<span class="pill pill-muted">Reviewed</span>' : `<button class="btn btn-small" data-review-event="${escapeHtml(event.id)}">Mark reviewed</button>`}</td>` : ""}
    <td><a class="btn btn-small" href="${MorvixDashboardView.historyEventHash(event.id)}">Details</a></td>
  </tr>`).join("");
}
function overviewAlertRows(items = []) {
  if (!items.length) return emptyState("No current alerts", "New blocked or flagged detections will appear here for parent review.");
  return items.map((item) => `<article class="alert-card">
    <span class="alert-icon" aria-hidden="true">${item.severity === "blocked" ? "■" : "!"}</span>
    <div><div class="alert-title">${escapeHtml(categoryLabel(item.category))} · ${item.severity === "blocked" ? "Blocked" : "Flagged"}</div>
      <div class="alert-meta">${escapeHtml(item.source_domain || "Local analysis")} · ${escapeHtml(item.modality)} · ${escapeHtml(formatDate(item.created_at))} · ${item.confidence == null ? "score unavailable" : `${Math.round(Number(item.confidence) * 100)}% score`}</div></div>
    <div><a class="btn btn-small" href="${MorvixDashboardView.historyEventHash(item.event_id)}">View history record</a> <button class="btn btn-small" data-review-overview-alert="${escapeHtml(item.id)}">Mark reviewed</button></div>
  </article>`).join("");
}
function summaryMetric(label, value, note, icon) {
  return `<article class="card metric-card"><div class="card-head"><span class="metric-label">${escapeHtml(label)}</span><span class="pill pill-muted" aria-hidden="true">${icon}</span></div><div class="metric-value">${Number(value || 0).toLocaleString()}</div><div class="metric-note">${escapeHtml(note)}</div></article>`;
}
function render() {
  if (!state.user) return renderLogin();
  const route = state.route;
  if (route === "dashboard") return renderDashboard();
  if (route === "history") return renderHistory();
  if (route === "alerts") return renderAlerts();
  if (route === "rules") return renderRules();
  if (route === "settings") return renderSettings();
  state.route = "dashboard";
  renderDashboard();
}
function renderLogin(message = "") {
  root.innerHTML = `<main class="login-shell"><section class="login-card" aria-labelledby="login-title">
    <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">M</span><div><p class="brand-name">MORVIX</p><span class="brand-sub">Intelligent content protection</span></div></div>
    <h1 id="login-title">A calmer way to stay informed.</h1>
    <p>Sign in to review activity and manage protection for a paired browser extension.</p>
    <div class="auth-switch" role="tablist" aria-label="Account action"><button role="tab" aria-selected="true" data-auth-tab="login">Sign in</button><button role="tab" aria-selected="false" data-auth-tab="register">Create account</button></div>
    <form id="auth-form"><div id="auth-fields"></div><p class="error-text" id="auth-error" role="alert">${escapeHtml(message)}</p><button class="btn btn-primary btn-block" type="submit">Sign in</button></form>
    <div id="google-auth" class="google-auth"><div class="auth-divider"><span>or use Google</span></div><div id="google-button" hidden></div><button id="google-fallback" class="btn btn-block google-fallback" type="button" disabled aria-describedby="google-auth-note">Continue with Google</button></div>
    <p id="google-auth-note" class="help google-auth-note">Google sign-in availability is being checked.</p>
    <p class="help" style="margin:17px 0 0">MORVIX only reviews content that a supported browser extension can access and analyze.</p>
  </section></main>`;
  let mode = "login";
  const fields = root.querySelector("#auth-fields");
  const submit = root.querySelector("#auth-form button[type=submit]");
  const showForm = () => {
    fields.innerHTML = `${mode === "register" ? `<div class="field"><label for="auth-name">Parent name</label><input id="auth-name" name="name" autocomplete="name" required maxlength="100"></div>` : ""}
      <div class="field"><label for="auth-email">Email</label><input id="auth-email" name="email" type="email" autocomplete="email" required maxlength="254"></div>
      <div class="field"><label for="auth-password">Password</label><input id="auth-password" name="password" type="password" autocomplete="${mode === "login" ? "current-password" : "new-password"}" required minlength="${mode === "login" ? 1 : 10}" maxlength="128"></div>`;
    submit.textContent = mode === "login" ? "Sign in" : "Create account";
    root.querySelectorAll("[data-auth-tab]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.authTab === mode)));
  };
  root.querySelectorAll("[data-auth-tab]").forEach((button) => button.addEventListener("click", () => { mode = button.dataset.authTab; root.querySelector("#auth-error").textContent = ""; showForm(); }));
  showForm();
  api("/auth/google/config").then((settings) => {
    const googleAuth = root.querySelector("#google-auth");
    const googleFallback = root.querySelector("#google-fallback");
    const googleButton = root.querySelector("#google-button");
    const note = root.querySelector("#google-auth-note");
    if (!settings.enabled) { note.hidden = false; note.textContent = settings.reason || "Google sign-in is unavailable until this installation is configured."; return; }
    note.hidden = true;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.referrerPolicy = "strict-origin-when-cross-origin";
    script.onload = () => {
      if (!root.contains(googleAuth)) return;
      if (!window.google?.accounts?.id) {
        note.hidden = false;
        note.textContent = "Google sign-in did not initialize. Use email and password or reload the page.";
        return;
      }
      window.google.accounts.id.initialize({
        client_id: settings.client_id,
        callback: async ({ credential }) => {
          const error = root.querySelector("#auth-error");
          submit.disabled = true;
          error.textContent = "";
          try {
            await api("/auth/google", { method: "POST", body: JSON.stringify({ credential, csrf_token: settings.csrf_token }) });
            await loadUser();
          } catch (failure) { error.textContent = failure.message; }
          finally { submit.disabled = false; }
        },
      });
      window.google.accounts.id.renderButton(root.querySelector("#google-button"), { theme: "outline", size: "large", text: "continue_with", shape: "pill", width: 360 });
      googleFallback.hidden = true;
      googleButton.hidden = false;
    };
    script.onerror = () => { note.hidden = false; note.textContent = "Google sign-in could not load. Check the internet connection and try again."; };
    document.head.append(script);
  }).catch(() => {
    const note = root.querySelector("#google-auth-note");
    if (note) { note.hidden = false; note.textContent = "Could not check Google sign-in. Email and password remain available."; }
  });
  root.querySelector("#auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    root.querySelector("#auth-error").textContent = "";
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (mode === "register") {
        await api("/auth/register", { method: "POST", body: JSON.stringify(data) });
        mode = "login";
        showForm();
        root.querySelector("#auth-error").className = "notice success";
        root.querySelector("#auth-error").textContent = "Your account is ready. Sign in to continue.";
      } else {
        await api("/auth/login", { method: "POST", body: JSON.stringify(data) });
        await loadUser();
      }
    } catch (error) { root.querySelector("#auth-error").textContent = error.message; }
    finally { submit.disabled = false; }
  });
}
async function loadUser() {
  try { state.user = await api("/auth/me"); }
  catch { state.user = null; }
  if (state.user) {
    const { route, eventId } = MorvixDashboardView.parseRouteHash(location.hash);
    state.route = NAV.some(([key]) => key === route) ? route : "dashboard";
    state.history.eventId = state.route === "history" ? eventId : null;
    if (!connectionStatusRefresh) {
      connectionStatusRefresh = MorvixConnectionStatusRefresh.createConnectionStatusRefresh({
        refresh: refreshVisibleConnectionStatus,
        isActive: () => Boolean(state.user && ["dashboard", "settings", "alerts"].includes(state.route)),
        windowRef: window,
        documentRef: document,
      });
    }
  }
  render();
}
async function logout() {
  try { await api("/auth/logout", { method: "POST" }); }
  finally {
    connectionStatusRefresh?.stop(); connectionStatusRefresh = null;
    refreshAlertsView = null;
    state.user = null; state.route = "dashboard"; location.hash = "#/dashboard"; renderLogin();
  }
}
function connectionStatusBanner(data) {
  const connectedDevice = (data.devices || []).find((device) => device.connected);
  const extensionConnected = Boolean(data.extension_connected ?? connectedDevice?.connected);
  const protectionEnabled = Boolean(data.protection_enabled);
  const extensionLabel = connectedDevice?.label ? `${escapeHtml(connectedDevice.label)} is connected` : "A paired extension checked in recently";
  const enforcementStatus = !protectionEnabled
    ? "Not active"
    : extensionConnected
      ? "Not verified on individual pages"
      : "Unavailable without an extension connection";
  const enforcementDetail = !protectionEnabled
    ? "The account policy is paused."
    : extensionConnected
      ? "A recent check-in confirms connection, not enforcement on a specific page."
      : "The account policy is on, but no extension is connected.";
  return `<div class="status-banner" role="status" aria-label="Protection and extension status">
    <div class="status-summary"><span class="status-dot ${protectionEnabled ? "" : "off"}" aria-hidden="true"></span><div><span class="eyebrow">Account policy</span><div class="status-title">${protectionEnabled ? "Protection enabled" : "Protection paused"}</div><div class="status-detail">${protectionEnabled ? "Your saved rules and category settings are on." : "Content interventions are paused."}</div></div></div>
    <div class="status-fact"><span class="eyebrow">Browser extension</span><strong>${extensionConnected ? extensionLabel : "Not connected"}</strong><div class="status-detail">${connectedDevice?.last_seen_at ? `Last check-in ${escapeHtml(formatDate(connectedDevice.last_seen_at))}` : extensionConnected ? "A recent check-in was received." : "No extension has checked in recently."}</div></div>
    <div class="status-fact"><span class="eyebrow">Enforcement status</span><strong>${escapeHtml(enforcementStatus)}</strong><div class="status-detail">${escapeHtml(enforcementDetail)}</div></div>
  </div>`;
}
async function renderDashboard() {
  shell("Dashboard", "Your protection overview and recent activity.");
  const view = document.getElementById("view");
  try {
    const data = await api(MorvixDashboardView.summaryPath(state.dashboard.days, state.dashboard.modality));
    view.innerHTML = `${pageHeading("Overview", "Protection at a glance", "Live totals from your saved MORVIX detection history.", `<a class="btn btn-primary" href="#/settings">Manage protection</a>`)}
      ${connectionStatusBanner(data)}
      ${MorvixDashboardView.controlsMarkup(state.dashboard.days, state.dashboard.modality, data.event_modalities)}
      <div class="grid grid-summary">${summaryMetric("Blocked", data.counts.blocked, `In the past ${data.period_days} days`, "■")}${summaryMetric("Flagged", data.counts.flagged, `In the past ${data.period_days} days`, "! ")}${summaryMetric("Allowed events", data.counts.allowed, `In the past ${data.period_days} days`, "✓")}${summaryMetric("Recorded events", data.counts.total, `In the past ${data.period_days} days`, "◈")}</div>
      <div class="grid grid-two"><article class="card"><div class="card-head"><div><span class="eyebrow">Recent activity</span><h3 style="margin-top:5px">Latest events</h3></div><a class="btn btn-small" href="#/history">View history</a></div><div class="table-wrap"><table><thead><tr><th>Date & time</th><th>Source / modality</th><th>Category</th><th>Confidence</th><th>Action</th><th></th></tr></thead><tbody>${eventRows(data.recent)}</tbody></table></div></article>
      <div class="grid"><article class="card"><div class="card-head"><div><span class="eyebrow">Selected period</span><h3 style="margin-top:5px">By modality</h3></div></div>${distributionRows(data.by_modality, modalityLabel)}</article><article class="card"><div class="card-head"><div><span class="eyebrow">Selected period</span><h3 style="margin-top:5px">By category</h3></div></div>${distributionRows(data.by_category)}</article><article class="card"><div class="card-head"><div><span class="eyebrow">Selected period</span><h3 style="margin-top:5px">By action</h3></div></div>${distributionRows(data.by_action, actionLabel)}</article></div></div>
      <article class="card overview-alerts"><div class="card-head"><div><span class="eyebrow">Parent review</span><h3 style="margin-top:5px">Current alerts</h3><span class="help">${Number(data.counts.unread_alerts || 0).toLocaleString()} unreviewed alerts</span></div><a class="btn btn-small" href="#/alerts">View all alerts</a></div><div class="alert-list">${overviewAlertRows(data.alerts)}</div></article>
      <p class="help" style="margin-top:16px">Model performance is not displayed until it has been measured using a held-out evaluation set. Scores on individual detections are model outputs, not accuracy measurements.</p>`;
    view.querySelector("#dashboard-range").addEventListener("change", (event) => {
      state.dashboard.days = Number(event.target.value);
      renderDashboard();
    });
    view.querySelector("#dashboard-modality").addEventListener("change", (event) => {
      state.dashboard.modality = event.target.value;
      renderDashboard();
    });
    view.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-review-overview-alert]");
      if (!button) return;
      button.disabled = true;
      try {
        await api(`/alerts/${encodeURIComponent(button.dataset.reviewOverviewAlert)}/review`, { method: "PATCH" });
        showToast("Alert marked reviewed.");
        renderDashboard();
      } catch (error) {
        button.disabled = false;
        showToast(error.message, true);
      }
    });
  } catch (error) { view.innerHTML = `<div class="notice error">Could not load the dashboard: ${escapeHtml(error.message)} <button class="btn btn-small" data-retry="dashboard">Retry</button></div>`; view.querySelector("[data-retry]").addEventListener("click", renderDashboard); }
}
function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== "" && value != null) search.set(key, value); });
  return search.toString();
}
async function renderHistory() {
  shell("Detection History", "Search and review metadata recorded by paired extensions.");
  const view = document.getElementById("view");
  const filters = state.history.filters || {};
  view.innerHTML = `${pageHeading("Activity log", "Detection history", "Full page text and media are not retained in the history.")}
    ${state.history.eventId ? `<div class="notice" role="status">Showing the detection linked to this alert. <a href="#/history">Show all history</a></div>` : ""}
    <article class="card"><form id="history-filters" class="filter-row">
      <div class="field search"><label for="history-search">Search</label><input id="history-search" name="search" placeholder="Search source or category" value="${escapeHtml(filters.search || "")}"></div>
      <div class="field"><label for="history-modality">Modality</label><select id="history-modality" name="modality"><option value="">All</option>${["text", "image", "video"].map((item) => `<option ${filters.modality === item ? "selected" : ""} value="${item}">${item[0].toUpperCase() + item.slice(1)}</option>`).join("")}</select></div>
      <div class="field"><label for="history-category">Category</label><select id="history-category" name="category"><option value="">All categories</option>${CATEGORIES.map((item) => `<option value="${item.key}" ${filters.category === item.key ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select></div>
      <div class="field"><label for="history-action">Action</label><select id="history-action" name="action"><option value="">All</option>${["block", "warn", "allow"].map((item) => `<option value="${item}" ${filters.action === item ? "selected" : ""}>${item[0].toUpperCase() + item.slice(1)}</option>`).join("")}</select></div>
      <div class="field"><label for="history-from">From</label><input id="history-from" name="date_from" type="date" value="${escapeHtml(filters.date_from || "")}"></div>
      <div class="field"><label for="history-to">To</label><input id="history-to" name="date_to" type="date" value="${escapeHtml(filters.date_to || "")}"></div>
      <button class="btn btn-primary" type="submit">Apply filters</button><button class="btn" type="reset" data-reset-history>Clear</button>
    </form><div class="table-wrap"><table><thead><tr><th>Date & time</th><th>Source / modality</th><th>Category</th><th>Score</th><th>Action</th><th>Review</th><th></th></tr></thead><tbody><tr><td colspan="7" class="loading">Loading history…</td></tr></tbody></table></div><div class="pagination" id="history-pagination"></div></article>`;
  const form = view.querySelector("#history-filters");
  form.addEventListener("submit", (event) => { event.preventDefault(); state.history.filters = Object.fromEntries(new FormData(form)); state.history.page = 1; loadHistoryItems(); });
  form.querySelector("[data-reset-history]").addEventListener("click", () => { state.history.filters = {}; state.history.page = 1; setTimeout(loadHistoryItems, 0); });
  view.querySelector("tbody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-review-event]");
    if (!button) return;
    try { await api(`/events/${encodeURIComponent(button.dataset.reviewEvent)}/review`, { method: "PATCH" }); showToast("Detection marked reviewed."); loadHistoryItems(); }
    catch (error) { showToast(error.message, true); }
  });
  await loadHistoryItems();
}
async function loadHistoryItems() {
  const view = document.getElementById("view");
  if (!view?.querySelector("#history-filters")) return;
  const dateFilters = state.history.filters || {};
  const params = { ...dateFilters, page: state.history.page, page_size: state.history.page_size };
  if (state.history.eventId) params.event_id = state.history.eventId;
  if (params.date_from) params.date_from = `${params.date_from}T00:00:00Z`;
  if (params.date_to) params.date_to = `${params.date_to}T23:59:59Z`;
  try {
    const data = await api(`/events?${queryString(params)}`);
    view.querySelector("tbody").innerHTML = eventRows(data.items, true);
    const pagination = view.querySelector("#history-pagination");
    pagination.innerHTML = `<span>${data.total ? `Showing ${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total)} of ${data.total}` : "No matching records"}</span><div><button class="btn btn-small" data-page="prev" ${data.page <= 1 ? "disabled" : ""}>Previous</button><button class="btn btn-small" data-page="next" ${data.page >= data.pages ? "disabled" : ""}>Next</button></div>`;
    pagination.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => { state.history.page += button.dataset.page === "next" ? 1 : -1; loadHistoryItems(); }));
  } catch (error) { view.querySelector("tbody").innerHTML = `<tr><td colspan="7"><div class="notice error">Could not load history: ${escapeHtml(error.message)}</div></td></tr>`; }
}
async function renderAlerts() {
  shell("Alerts", "Review events that were flagged or blocked by policy.");
  const view = document.getElementById("view");
  view.innerHTML = `${pageHeading("Parent review", "Alerts", "New saved alerts appear within about 10 seconds while this page is open. MORVIX does not send email or push notifications.", `<label class="pill"><input id="unread-only" type="checkbox" style="accent-color:var(--accent)"> Unreviewed only</label>`)}<div class="alert-list" id="alerts-list"><p class="loading">Loading alerts…</p></div>`;
  const load = async () => {
    const list = view.querySelector("#alerts-list");
    try {
      const data = await api(`/alerts?unread_only=${view.querySelector("#unread-only").checked}`);
      state.alertItems = data.items;
      list.innerHTML = data.items.length ? data.items.map((item) => `<article class="alert-card"><span class="alert-icon" aria-hidden="true">${item.severity === "blocked" ? "■" : "!"}</span><div><div class="alert-title">${escapeHtml(categoryLabel(item.category))} · ${item.severity === "blocked" ? "Blocked" : "Flagged"}</div><div class="alert-meta">${escapeHtml(item.source_domain || "Local analysis")} · ${escapeHtml(item.modality)} · ${escapeHtml(formatDate(item.created_at))} · ${item.confidence == null ? "score unavailable" : `${Math.round(item.confidence * 100)}% score`}</div></div><div>${item.reviewed ? `<span class="pill pill-muted">Reviewed</span>` : `<button class="btn btn-small" data-review-alert="${escapeHtml(item.id)}">Mark reviewed</button>`}<a class="btn btn-small" href="${MorvixDashboardView.historyEventHash(item.event_id)}" aria-label="Open this detection history record">History</a></div></article>`).join("") : emptyState("No alerts to show", "Flagged and blocked detections will appear here.");
    } catch (error) { list.innerHTML = `<div class="notice error">Could not load alerts: ${escapeHtml(error.message)}</div>`; }
  };
  refreshAlertsView = load;
  view.querySelector("#unread-only").addEventListener("change", load);
  view.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-review-alert]"); if (!button) return;
    try { await api(`/alerts/${encodeURIComponent(button.dataset.reviewAlert)}/review`, { method: "PATCH" }); showToast("Alert marked reviewed."); load(); }
    catch (error) { showToast(error.message, true); }
  });
  await load();
}
async function renderRules() {
  shell("Protection Rules", "Choose how MORVIX should respond to sites and supported categories.");
  const view = document.getElementById("view");
  view.innerHTML = `${pageHeading("Policy controls", "Protection rules", "A matching website rule takes precedence over category settings.", `<button class="btn btn-primary" data-add-rule>Add rule</button>`)}<article class="card"><div class="card-head"><div><h3>Saved rules</h3><span class="help">Changes are saved to your MORVIX account.</span></div><button class="btn btn-small" data-refresh-rules>Refresh</button></div><div id="rules-list" class="loading">Loading rules…</div></article>`;
  view.querySelector("[data-add-rule]").addEventListener("click", () => openRuleDialog());
  view.querySelector("[data-refresh-rules]").addEventListener("click", loadRules);
  view.querySelector("#rules-list").addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-edit-rule]");
    const remove = event.target.closest("[data-delete-rule]");
    if (edit) openRuleDialog(state.rules.find((item) => item.id === edit.dataset.editRule));
    if (remove) {
      const rule = state.rules.find((item) => item.id === remove.dataset.deleteRule);
      if (!rule || !confirm(`Delete the ${rule.kind} rule for ${rule.target}?`)) return;
      try { await api(`/rules/${encodeURIComponent(rule.id)}`, { method: "DELETE" }); showToast("Rule deleted."); await loadRules(); }
      catch (error) { showToast(error.message, true); }
    }
  });
  await loadRules();
}
async function loadRules() {
  const list = document.getElementById("rules-list"); if (!list) return;
  try {
    const data = await api("/rules"); state.rules = data.items;
    list.innerHTML = data.items.length ? `<div class="table-wrap"><table><thead><tr><th>Type</th><th>Target</th><th>Action</th><th>Status</th><th></th></tr></thead><tbody>${data.items.map((rule) => `<tr><td>${rule.kind === "website" ? "Website" : "Category"}</td><td><strong>${escapeHtml(rule.kind === "category" ? categoryLabel(rule.target) : rule.target)}</strong></td><td>${actionPill(rule.action)}</td><td><span class="pill ${rule.enabled ? "pill-allow" : "pill-muted"}">${rule.enabled ? "Enabled" : "Disabled"}</span></td><td class="text-right"><button class="btn btn-small" data-edit-rule="${escapeHtml(rule.id)}">Edit</button> <button class="btn btn-small btn-danger" data-delete-rule="${escapeHtml(rule.id)}">Delete</button></td></tr>`).join("")}</tbody></table></div>` : emptyState("No custom rules yet", "Add a website or category rule to tailor the protection behavior.");
  } catch (error) { list.innerHTML = `<div class="notice error">Could not load rules: ${escapeHtml(error.message)}</div>`; }
}
function openRuleDialog(rule = null) {
  const editing = Boolean(rule);
  dialog.innerHTML = `<form method="dialog" class="dialog-body" id="rule-form"><div class="dialog-head"><div><span class="eyebrow">Policy rule</span><h2 id="rule-dialog-title">${editing ? "Edit rule" : "Add a rule"}</h2></div><button type="button" class="btn btn-small" data-close-dialog aria-label="Close">✕</button></div>
    <div class="field"><label for="rule-kind">Rule type</label><select id="rule-kind" name="kind"><option value="website" ${rule?.kind === "website" ? "selected" : ""}>Website or domain</option><option value="category" ${rule?.kind === "category" ? "selected" : ""}>Content category</option></select></div>
    <div class="field"><label for="rule-target">Target</label><input id="rule-target" name="target" required maxlength="253" value="${escapeHtml(rule?.target || "")}" placeholder="example.com"><span class="help">For a website, enter a domain without a path. For a category, choose an available model label.</span></div>
    <div class="field"><label for="rule-action">Action</label><select id="rule-action" name="action">${["allow", "warn", "block"].map((item) => `<option value="${item}" ${rule?.action === item ? "selected" : ""}>${item === "warn" ? "Warn / flag" : item[0].toUpperCase() + item.slice(1)}</option>`).join("")}</select></div>
    <label class="setting-row"><span class="setting-copy"><strong>Rule enabled</strong><span>Disabled rules are saved but not applied.</span></span><input type="checkbox" name="enabled" ${rule?.enabled === false ? "" : "checked"}></label>
    <p id="rule-error" class="error-text" role="alert"></p><div style="display:flex;justify-content:flex-end;gap:9px"><button type="button" class="btn" data-close-dialog>Cancel</button><button type="submit" class="btn btn-primary">${editing ? "Save changes" : "Create rule"}</button></div></form>`;
  const kind = dialog.querySelector("#rule-kind");
  const target = dialog.querySelector("#rule-target");
  const syncTarget = () => {
    if (kind.value === "website") { dialog.querySelector("#rule-target").outerHTML = `<input id="rule-target" name="target" required maxlength="253" value="${escapeHtml(rule?.kind === "website" ? rule.target : "")}" placeholder="example.com">`; }
    else { dialog.querySelector("#rule-target").outerHTML = `<select id="rule-target" name="target">${CATEGORIES.map((item) => `<option value="${item.key}" ${rule?.target === item.key ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select>`; }
  };
  kind.addEventListener("change", syncTarget);
  dialog.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  dialog.querySelector("#rule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget)); data.enabled = event.currentTarget.elements.enabled.checked;
    const submit = event.currentTarget.querySelector("[type=submit]"); submit.disabled = true;
    try {
      await api(editing ? `/rules/${encodeURIComponent(rule.id)}` : "/rules", { method: editing ? "PUT" : "POST", body: JSON.stringify(data) });
      dialog.close(); showToast(editing ? "Rule updated." : "Rule created."); await loadRules();
    } catch (error) { dialog.querySelector("#rule-error").textContent = error.message; }
    finally { submit.disabled = false; }
  });
  dialog.showModal();
}
async function renderSettings() {
  shell("Settings", "Manage account protection, category behavior and extension pairing.");
  const view = document.getElementById("view");
  view.innerHTML = `<p class="loading">Loading your saved settings…</p>`;
  try {
    const [settings, devices, readiness] = await Promise.all([api("/settings"), api("/devices"), api("/health/ready")]);
    state.settings = settings; state.devices = devices.items;
    const pendingSettings = MORVIX_SETTINGS_PATCH.create();
    view.innerHTML = `${pageHeading("Parent controls", "Settings", "These account settings synchronize to paired extensions.")}
      <div class="grid grid-two"><div class="grid"><article class="card"><div class="card-head"><div><span class="eyebrow">Protection</span><h3 style="margin-top:5px">Coverage controls</h3></div><span class="pill pill-muted">Policy v${settings.version}</span></div>
        <p class="help">These controls store your requested policy. Detection also requires a working classifier and a connected backend; a policy setting does not provide a missing classifier.</p>
        <form id="settings-form"><label class="setting-row"><span class="setting-copy"><strong>Protection enabled</strong><span>When paused, MORVIX allows content without category interventions.</span></span><button type="button" class="toggle" role="switch" aria-checked="${settings.protection_enabled}" data-toggle="protection_enabled" aria-label="Toggle overall protection"></button></label>
        <div class="setting-row"><span class="setting-copy"><strong>Text analysis policy</strong><span>${escapeHtml(MorvixClassifierCopy.modalityPolicy("text"))}</span></span><button type="button" class="toggle" role="switch" aria-checked="${settings.modalities.text}" data-toggle="modality:text" aria-label="Toggle text analysis policy"></button></div>
        <div class="setting-row"><span class="setting-copy"><strong>Image analysis policy</strong><span>${escapeHtml(MorvixClassifierCopy.modalityPolicy("image"))}</span></span><button type="button" class="toggle" role="switch" aria-checked="${settings.modalities.image}" data-toggle="modality:image" aria-label="Toggle image analysis policy"></button></div>
        <div class="setting-row"><span class="setting-copy"><strong>Video analysis policy</strong><span>${escapeHtml(MorvixClassifierCopy.modalityPolicy("video"))}</span></span><button type="button" class="toggle" role="switch" aria-checked="${settings.modalities.video}" data-toggle="modality:video" aria-label="Toggle video analysis policy"></button></div>
        <div class="card-head" style="margin-top:22px"><div><span class="eyebrow">Classifier coverage and policy</span><h3 style="margin-top:5px">Category actions</h3><p class="help">Threat thresholds apply to text; violence thresholds apply to video. Settings cannot enable a category without a functioning classifier.</p></div></div>
        ${CATEGORIES.map((item) => `<div class="setting-row"><span class="setting-copy"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(MorvixClassifierCopy.categoryCoverage(item.key))}</span></span><select class="control" style="width:145px" data-category-action="${item.key}" ${item.key === "self_harm_indicators" ? "disabled" : ""}>${["allow", "warn", "block"].map((action) => `<option value="${action}" ${settings.category_actions[item.key] === action ? "selected" : ""}>${action === "warn" ? "Warn / flag" : action[0].toUpperCase() + action.slice(1)}</option>`).join("")}</select></div>`).join("")}
        <div class="card-head" style="margin-top:22px"><div><span class="eyebrow">Confidence behavior</span><h3 style="margin-top:5px">Review and block thresholds</h3><p class="help">Provisional values only. Website rules take precedence. Otherwise, below review is allowed; a requested Block is flagged below its block threshold and blocked at or above it. Thresholds never upgrade Warn or Allow. Scores are not accuracy values.</p></div></div>
        ${CATEGORIES.filter((item) => item.key !== "self_harm_indicators").map((item) => `<div class="setting-row"><span class="setting-copy"><strong>${escapeHtml(item.label)} · review</strong><span>Minimum score before a category result is reviewed.</span></span><div class="range-line"><input type="range" min="0" max="100" value="${Math.round(settings.thresholds[item.key].review * 100)}" data-threshold="${item.key}:review"><output class="range-value">${Math.round(settings.thresholds[item.key].review * 100)}%</output></div></div><div class="setting-row"><span class="setting-copy"><strong>${escapeHtml(item.label)} · block</strong><span>Minimum score for a configured block action.</span></span><div class="range-line"><input type="range" min="0" max="100" value="${Math.round(settings.thresholds[item.key].block * 100)}" data-threshold="${item.key}:block"><output class="range-value">${Math.round(settings.thresholds[item.key].block * 100)}%</output></div></div>`).join("")}
        <p class="error-text" id="settings-error" role="alert"></p><button class="btn btn-primary" type="submit">Save protection settings</button>
        </form></article></div>
        <div class="grid"><article class="card"><div class="card-head"><div><span class="eyebrow">Extension</span><h3 style="margin-top:5px">Pair a browser</h3></div><span class="pill ${readiness.database === "ready" ? "pill-allow" : "pill-warn"}">Backend ${escapeHtml(readiness.database)}</span></div><p class="help">Create a one-time code, then enter it in the MORVIX extension popup. It expires after five minutes.</p><form id="pair-form" style="display:flex;gap:9px;margin:14px 0"><input class="control" name="label" maxlength="80" value="Protected browser" aria-label="Device label"><button class="btn btn-primary" type="submit">Create code</button></form><div id="pairing-result"></div><div id="devices-list">${renderDevices(state.devices)}</div></article>
        <article class="card"><div class="card-head"><div><span class="eyebrow">Classifier readiness</span><h3 style="margin-top:5px">Local model status</h3></div></div><div class="distribution">${Object.entries(readiness.classifiers || {}).map(([key,value]) => { const status = MorvixClassifierCopy.status(value); return `<div class="setting-row"><span class="setting-copy"><strong>${escapeHtml(key[0].toUpperCase()+key.slice(1))}</strong><span>${escapeHtml(status.label)}</span></span><span class="pill ${status.tone}">${escapeHtml(value.replaceAll("_", " "))}</span></div>`; }).join("")}</div><p class="help">“Loaded” means weights passed runtime checks in this backend process, not that the model has been evaluated for MORVIX accuracy. Setup downloads are separate from runtime; inference stays local.</p></article></div></div>`;
    view.querySelectorAll("[data-toggle]").forEach((button) => button.addEventListener("click", () => {
      const key = button.dataset.toggle;
      let value;
      if (key === "protection_enabled") { settings.protection_enabled = !settings.protection_enabled; value = settings.protection_enabled; }
      else { const modality = key.split(":")[1]; settings.modalities[modality] = !settings.modalities[modality]; value = settings.modalities[modality]; }
      MORVIX_SETTINGS_PATCH.setToggle(pendingSettings, key, value);
      button.setAttribute("aria-checked", String(value));
    }));
    view.querySelectorAll("[data-threshold]").forEach((input) => input.addEventListener("input", () => {
      const [category, threshold] = input.dataset.threshold.split(":");
      const output = input.parentElement.querySelector("output"); output.textContent = `${input.value}%`;
      settings.thresholds[category][threshold] = Number(input.value) / 100;
      MORVIX_SETTINGS_PATCH.setThreshold(pendingSettings, category, threshold, input.value);
      if (settings.thresholds[category].review > settings.thresholds[category].block) output.textContent += " · review must not exceed block";
    }));
    view.querySelectorAll("[data-category-action]").forEach((select) => select.addEventListener("change", () => {
      settings.category_actions[select.dataset.categoryAction] = select.value;
      MORVIX_SETTINGS_PATCH.setCategoryAction(pendingSettings, select.dataset.categoryAction, select.value);
    }));
    view.querySelector("#settings-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector("[type=submit]"); button.disabled = true;
      const errorText = event.currentTarget.querySelector("#settings-error"); errorText.textContent = "";
      if (MORVIX_SETTINGS_PATCH.isEmpty(pendingSettings)) {
        errorText.textContent = "Change a setting before saving.";
        button.disabled = false;
        return;
      }
      try {
        const saved = await api("/settings", { method: "PATCH", body: JSON.stringify(MORVIX_SETTINGS_PATCH.copy(pendingSettings)) });
        for (const [category, values] of Object.entries(pendingSettings.thresholds || {})) {
          for (const [threshold, value] of Object.entries(values)) {
            if (saved.thresholds?.[category]?.[threshold] !== value) throw new Error("The backend did not confirm the selected threshold value.");
          }
        }
        for (const [category, action] of Object.entries(pendingSettings.category_actions || {})) {
          if (saved.category_actions?.[category] !== action) throw new Error("The backend did not confirm the selected category action.");
        }
        if (pendingSettings.protection_enabled !== undefined && saved.protection_enabled !== pendingSettings.protection_enabled) throw new Error("The backend did not confirm the protection setting.");
        for (const [modality, enabled] of Object.entries(pendingSettings.modalities || {})) {
          if (saved.modalities?.[modality] !== enabled) throw new Error("The backend did not confirm the modality setting.");
        }
        state.settings = saved; showToast("Protection settings saved and queued for extension synchronization."); await renderSettings();
      } catch (error) { errorText.textContent = error.message; button.disabled = false; }
    });
    view.querySelector("#pair-form").addEventListener("submit", async (event) => {
      event.preventDefault(); const formData = new FormData(event.currentTarget); const label = formData.get("label");
      try {
        const pairing = await api(`/devices/pair?label=${encodeURIComponent(label)}`, { method: "POST" });
        view.querySelector("#pairing-result").innerHTML = `<div class="notice success"><strong>Pairing code</strong><br><span class="code-box">${escapeHtml(pairing.pairing_code)}</span><br>Expires ${escapeHtml(formatDate(pairing.expires_at))}. Enter this code in the extension popup.</div>`;
        await refreshDevices();
      } catch (error) { showToast(error.message, true); }
    });
    view.querySelector("#devices-list").addEventListener("click", async (event) => {
      const button = event.target.closest("[data-revoke-device]"); if (!button) return;
      if (!confirm("Revoke this browser extension? It will stop syncing and must be paired again.")) return;
      try { await api(`/devices/${encodeURIComponent(button.dataset.revokeDevice)}`, { method: "DELETE" }); showToast("Extension revoked."); await refreshDevices(); }
      catch (error) { showToast(error.message, true); }
    });
  } catch (error) { view.innerHTML = `<div class="notice error">Could not load settings: ${escapeHtml(error.message)}</div>`; }
}
function renderDevices(devices) {
  if (!devices.length) return `<div class="empty">No paired browser extensions yet.<br>Pairing one enables browser status and policy sync.</div>`;
  return `<div style="margin-top:12px">${devices.map((device) => `<div class="device-row"><div><strong>${escapeHtml(device.label)}</strong><div class="alert-meta">${device.revoked ? "Revoked" : device.connected ? "Connected" : device.paired_at ? "Disconnected" : "Pairing pending"}${device.last_seen_at ? ` · last seen ${escapeHtml(formatDate(device.last_seen_at))}` : ""}</div></div><div>${device.connected ? '<span class="pill pill-allow">Connected</span>' : device.revoked ? '<span class="pill pill-muted">Revoked</span>' : '<span class="pill pill-warn">Offline</span>'} ${device.revoked ? "" : `<button class="btn btn-small btn-danger" data-revoke-device="${escapeHtml(device.id)}">Revoke</button>`}</div></div>`).join("")}</div>`;
}
async function refreshDevices() {
  const data = await api("/devices"); state.devices = data.items;
  const list = document.getElementById("devices-list"); if (list) list.innerHTML = renderDevices(state.devices);
}
async function refreshVisibleConnectionStatus() {
  if (state.route === "settings") return refreshDevices();
  if (state.route === "alerts") return refreshAlertsView?.();
  if (state.route === "dashboard") {
    const data = await api("/dashboard/summary");
    const banner = document.querySelector("#view .status-banner");
    if (banner) banner.outerHTML = connectionStatusBanner(data);
  }
}
window.addEventListener("hashchange", () => {
  if (!state.user) return;
  const { route: requested, eventId } = MorvixDashboardView.parseRouteHash(location.hash);
  state.route = NAV.some(([key]) => key === requested) ? requested : "dashboard";
  if (state.route === "history") {
    if (eventId && eventId !== state.history.eventId) {
      state.history.filters = {};
      state.history.page = 1;
    } else if (!eventId && state.history.eventId) {
      state.history.page = 1;
    }
    state.history.eventId = eventId;
  } else {
    state.history.eventId = null;
  }
  render();
});
loadUser();
