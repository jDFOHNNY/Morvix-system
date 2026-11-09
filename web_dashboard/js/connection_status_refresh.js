"use strict";

(function exposeConnectionStatusRefresh(root) {
  function createConnectionStatusRefresh({ refresh, isActive, windowRef, documentRef, intervalMs = 10000 }) {
    let inFlight = false;
    const run = async () => {
      if (inFlight || !isActive() || documentRef.visibilityState === "hidden") return;
      inFlight = true;
      try { await refresh(); } catch (_) { /* Keep the last displayed server result during transient failures. */ }
      finally { inFlight = false; }
    };
    const onFocus = () => { void run(); };
    const onVisibilityChange = () => {
      if (documentRef.visibilityState !== "hidden") void run();
    };
    const timer = windowRef.setInterval(() => { void run(); }, intervalMs);
    windowRef.addEventListener("focus", onFocus);
    documentRef.addEventListener("visibilitychange", onVisibilityChange);
    return {
      stop() {
        windowRef.clearInterval(timer);
        windowRef.removeEventListener("focus", onFocus);
        documentRef.removeEventListener("visibilitychange", onVisibilityChange);
      },
    };
  }

  const api = { createConnectionStatusRefresh };
  root.MorvixConnectionStatusRefresh = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
