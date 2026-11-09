"use strict";

(() => {
  const ANALYTICS_RANGES = [7, 30, 90, 365];
  const MODALITY_LABELS = { text: "Text", image: "Image", video: "Video", audio: "Audio" };

  function controlsMarkup(days, modality, supportedModalities = ["text", "image", "video"]) {
    const selectedDays = ANALYTICS_RANGES.includes(Number(days)) ? Number(days) : 30;
    const modalities = ["text", "image", "video", "audio"].filter((item) => supportedModalities.includes(item));
    const selectedModality = modalities.includes(modality) ? modality : "all";
    return `<div class="overview-controls" aria-label="Overview filters">
      <div class="field"><label for="dashboard-range">Analytics time range</label><select id="dashboard-range" name="days">${ANALYTICS_RANGES.map((value) => `<option value="${value}" ${selectedDays === value ? "selected" : ""}>Last ${value} days</option>`).join("")}</select></div>
      <div class="field"><label for="dashboard-modality">Recent detection channel</label><select id="dashboard-modality" name="modality"><option value="all" ${selectedModality === "all" ? "selected" : ""}>All</option>${modalities.map((value) => `<option value="${value}" ${selectedModality === value ? "selected" : ""}>${MODALITY_LABELS[value]}</option>`).join("")}</select></div>
    </div>`;
  }

  function summaryPath(days, modality = "all") {
    const query = new URLSearchParams({ days: String(Number(days) || 30) });
    if (modality !== "all" && ["text", "image", "video"].includes(modality)) query.set("modality", modality);
    return `/dashboard/summary?${query.toString()}`;
  }

  function historyEventHash(eventId) {
    return `#/history?event_id=${encodeURIComponent(String(eventId || ""))}`;
  }

  function parseRouteHash(hash) {
    const routeAndQuery = String(hash || "").replace(/^#\/?/, "");
    const separator = routeAndQuery.indexOf("?");
    const route = (separator < 0 ? routeAndQuery : routeAndQuery.slice(0, separator)).split("/")[0] || "dashboard";
    const query = separator < 0 ? "" : routeAndQuery.slice(separator + 1);
    const eventId = route === "history" ? new URLSearchParams(query).get("event_id") : null;
    return { route, eventId: eventId || null };
  }

  const api = { controlsMarkup, summaryPath, historyEventHash, parseRouteHash };
  globalThis.MorvixDashboardView = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
