"use strict";

// Local development is pinned to one loopback origin. Never load this value from
// extension storage: device tokens are only attached after this check succeeds.
globalThis.MORVIX_API_CONFIG = Object.freeze({
  BASE: "http://127.0.0.1:8000/api/v1",

  assertStoredBase(value) {
    if (value !== undefined && value !== null && value !== this.BASE) {
      throw new Error("Saved MORVIX backend configuration is invalid. Disconnect and pair this browser again.");
    }
  },

  url(path) {
    if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
      throw new Error("Invalid MORVIX API route.");
    }
    const url = new URL(`${this.BASE}${path}`);
    if (
      url.origin !== "http://127.0.0.1:8000" ||
      url.protocol !== "http:" ||
      url.hostname !== "127.0.0.1" ||
      url.port !== "8000" ||
      url.username || url.password ||
      !(url.pathname === "/api/v1" || url.pathname.startsWith("/api/v1/"))
    ) {
      throw new Error("MORVIX API route is outside the approved local backend.");
    }
    return url.href;
  },

  async fetchAuthenticated(path, token, storedBase, options = {}, fetchImplementation = fetch) {
    this.assertStoredBase(storedBase);
    if (typeof token !== "string" || !token) throw new Error("Pair this extension from the MORVIX dashboard first.");
    const url = this.url(path);
    return fetchImplementation(url, {
      ...options,
      signal: options.signal || AbortSignal.timeout(20000),
      headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
  },
});
