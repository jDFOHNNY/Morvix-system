"use strict";

globalThis.MORVIX_POLICY_CACHE = Object.freeze({
  DEFAULT_MAX_AGE_MINUTES: 1440,

  freshness(snapshot, lastSyncAt, now = Date.now()) {
    const configured = Number(snapshot?.cache_max_age_minutes);
    const minutes = Number.isFinite(configured) && configured >= 1 && configured <= 10080
      ? Math.floor(configured)
      : this.DEFAULT_MAX_AGE_MINUTES;
    const synced = Date.parse(lastSyncAt || "");
    const timestampValid = Number.isFinite(synced) && synced <= now + 5 * 60 * 1000;
    const ageMs = timestampValid ? Math.max(0, now - synced) : null;
    const maxAgeMs = minutes * 60 * 1000;
    return {
      fresh: ageMs !== null && ageMs <= maxAgeMs,
      ageMs,
      maxAgeMs,
      maxAgeMinutes: minutes,
      expiresAt: timestampValid ? new Date(synced + maxAgeMs).toISOString() : null,
    };
  },

  matchingWebsiteRule(snapshot, hostname) {
    const domain = String(hostname || "").toLowerCase().replace(/\.$/, "");
    return (snapshot?.rules || [])
      .filter((rule) => rule.enabled && rule.kind === "website")
      .filter((rule) => {
        const target = String(rule.target || "").toLowerCase().replace(/^\.+|\.+$/g, "");
        return target && (domain === target || domain.endsWith(`.${target}`));
      })
      .sort((a, b) => String(b.target).length - String(a.target).length)[0] || null;
  },
});
