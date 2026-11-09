"use strict";

globalThis.MORVIX_MEDIA = Object.freeze({
  pageIdentity(value) {
    const url = new URL(value);
    if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password) {
      throw new Error("This page URL is not supported.");
    }
    return { origin: url.origin, hostname: url.hostname.toLowerCase() };
  },

  validateSameOriginUrl(mediaValue, pageValue) {
    const page = new URL(pageValue);
    const media = new URL(mediaValue, page.origin);
    if (
      !(["http:", "https:"].includes(page.protocol)) ||
      !(["http:", "https:"].includes(media.protocol)) ||
      page.username || page.password || media.username || media.password ||
      page.origin !== media.origin
    ) {
      throw new Error("Cross-origin or unsupported media is not analyzed.");
    }
    return { url: media.href, origin: page.origin };
  },

  async fetchSameOrigin(mediaValue, pageValue, options = {}, fetchImplementation = fetch) {
    const requested = this.validateSameOriginUrl(mediaValue, pageValue);
    const response = await fetchImplementation(requested.url, {
      ...options,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) throw new Error("Media is unavailable from this page origin.");
    if (response.url && new URL(response.url).origin !== requested.origin) {
      throw new Error("The media response crossed to another origin and was rejected.");
    }
    return response;
  },

  uploadLimit(readiness) {
    if (!readiness || readiness.ready !== true) return null;
    const value = Number(readiness.max_upload_bytes);
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  },
});
