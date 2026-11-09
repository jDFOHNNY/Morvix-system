"use strict";

globalThis.MORVIX_SETTINGS_PATCH = Object.freeze({
  create() { return {}; },

  setToggle(patch, key, value) {
    if (key === "protection_enabled") patch.protection_enabled = Boolean(value);
    else {
      const [kind, name] = String(key).split(":");
      if (kind !== "modality" || !["text", "image", "video"].includes(name)) {
        throw new Error("Unknown protection setting.");
      }
      patch.modalities ||= {};
      patch.modalities[name] = Boolean(value);
    }
    return patch;
  },

  setThreshold(patch, category, threshold, percentage) {
    const score = Number(percentage) / 100;
    if (
      !["violence", "threat_language", "self_harm_indicators"].includes(category) ||
      !["review", "block"].includes(threshold) ||
      !Number.isFinite(score) || score < 0 || score > 1
    ) throw new Error("Choose a valid threshold percentage.");
    patch.thresholds ||= {};
    patch.thresholds[category] ||= {};
    patch.thresholds[category][threshold] = score;
    return patch;
  },

  setCategoryAction(patch, category, action) {
    if (!["violence", "threat_language", "self_harm_indicators"].includes(category) || !["allow", "warn", "block"].includes(action)) {
      throw new Error("Choose a valid category action.");
    }
    patch.category_actions ||= {};
    patch.category_actions[category] = action;
    return patch;
  },

  isEmpty(patch) { return Object.keys(patch).length === 0; },
  copy(patch) { return JSON.parse(JSON.stringify(patch)); },
});
