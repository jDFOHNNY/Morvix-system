"use strict";

(() => {
  if (window.__morvixProtectionStarted) return;
  window.__morvixProtectionStarted = true;
  const MAX_VISIBLE_TEXT = 20000;
  const TEXT_RESCAN_DELAY_MS = 700;
  let stopped = false;
  let noticeHost = null;
  let noticeIsUncertain = false;
  let textScanningEnabled = false;
  let textObserver = null;
  let textScanTimer = null;
  let textScanInProgress = false;
  let textScanRequested = false;
  let lastTextFingerprint = null;

  function sendExtensionMessage(message) {
    try {
      return Promise.resolve(chrome.runtime.sendMessage(message));
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function showNotice(result, modality = "text") {
    if (!result || stopped) return;
    if (result.action === "allow" || result.status === "skipped") {
      if (noticeHost && noticeIsUncertain) {
        noticeHost.remove();
        noticeHost = null;
        noticeIsUncertain = false;
      }
      return;
    }
    const isBlock = result.action === "block";
    const uncertain = result.status === "uncertain" || result.status === "offline" || result.status === "unavailable";
    const contextInvalidated = result.contextInvalidated || /extension context invalidated/i.test(result.reason || "");
    if (isBlock) {
      stopped = true;
      stopTextMonitoring();
    }
    noticeHost?.remove();

    const host = document.createElement("div");
    host.id = "morvix-intervention";
    host.style.cssText = `all:initial;position:fixed;inset:0;z-index:2147483647;pointer-events:${isBlock ? "auto" : "none"};background:${isBlock ? "rgba(38,25,19,.62)" : "transparent"}`;
    const shadow = host.attachShadow({ mode: "closed" });
    const panel = document.createElement("section");
    panel.setAttribute("role", isBlock ? "alertdialog" : "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.style.cssText = `box-sizing:border-box;position:fixed;${isBlock ? "left:50%;top:50%;transform:translate(-50%,-50%)" : "right:20px;bottom:20px"};width:min(410px,calc(100vw - 32px));padding:22px;border-radius:18px;background:#fff9f5;color:#442b20;border:1px solid #e8bca2;box-shadow:0 14px 54px #42251755;font:15px/1.5 system-ui,sans-serif;pointer-events:auto`;
    const label = document.createElement("div");
    label.textContent = "MORVIX · content protection";
    label.style.cssText = "font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#9b572c;font-weight:800";
    const heading = document.createElement("h2");
    heading.textContent = isBlock ? "This content was blocked" : uncertain ? "MORVIX could not check this content" : "Review before continuing";
    heading.style.cssText = "font:700 21px/1.25 system-ui,sans-serif;margin:8px 0";
    const detail = document.createElement("p");
    detail.textContent = isBlock
      ? "A parent protection rule blocked this page or item."
      : uncertain
        ? contextInvalidated
          ? "MORVIX was reloaded. Refresh this page to reconnect protection. The page remains open."
          : `${result.reason || `The local ${modality} check is unavailable.`} This content remains open unless a cached website rule applies.`
        : result.category === "website_rule"
          ? "A parent website rule asks you to pause before continuing."
          : "A local content check reached a category configured for review.";
    detail.style.cssText = "margin:0 0 17px;color:#705444";
    const controls = document.createElement("div");
    controls.style.cssText = "display:flex;justify-content:flex-end;gap:9px;flex-wrap:wrap";
    const button = (text, primary, action) => {
      const item = document.createElement("button");
      item.type = "button"; item.textContent = text;
      item.style.cssText = `border:1px solid ${primary ? "#d9842c" : "#dbc7b9"};border-radius:10px;padding:10px 14px;background:${primary ? "#e8912d" : "#fff"};color:${primary ? "#fff" : "#553d30"};font:600 14px system-ui,sans-serif;cursor:pointer`;
      item.addEventListener("click", action);
      return item;
    };
    const dismiss = () => {
      host.remove();
      if (noticeHost === host) { noticeHost = null; noticeIsUncertain = false; }
    };
    if (isBlock) controls.append(button("Go back", true, () => { history.length > 1 ? history.back() : (location.href = "about:blank"); }));
    else if (!uncertain) controls.append(button("Continue", true, dismiss));
    else controls.append(button("Dismiss", true, dismiss));
    panel.append(label, heading, detail, controls); shadow.append(panel); noticeHost = host; noticeIsUncertain = uncertain; document.documentElement.append(host);
  }

  function visibleText() {
    const body = document.body;
    if (!body) return "";
    const ignored = "script,style,noscript,svg,canvas,iframe,form,input,textarea,select,button,[aria-hidden='true'],[hidden]";
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const pieces = [];
    let length = 0;
    while (walker.nextNode() && length < MAX_VISIBLE_TEXT) {
      const node = walker.currentNode;
      const value = (node.nodeValue || "").replace(/\s+/g, " ").trim();
      const parent = node.parentElement;
      if (!value || !parent || parent.closest(ignored)) continue;
      let hidden = false;
      for (let element = parent; element && element !== body; element = element.parentElement) {
        const style = getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) { hidden = true; break; }
      }
      if (hidden) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      if (![...range.getClientRects()].some((rect) => rect.width > 0 && rect.height > 0)) continue;
      const portion = value.slice(0, MAX_VISIBLE_TEXT - length);
      pieces.push(portion);
      length += portion.length + 1;
    }
    return pieces.join(" ").slice(0, MAX_VISIBLE_TEXT);
  }

  function textFingerprint(text) {
    let firstHash = 2166136261;
    let secondHash = 5381;
    for (let index = 0; index < text.length; index += 1) {
      const code = text.charCodeAt(index);
      firstHash ^= code;
      firstHash = Math.imul(firstHash, 16777619);
      secondHash = Math.imul(secondHash, 33) ^ code;
    }
    return `${text.length}:${firstHash >>> 0}:${secondHash >>> 0}`;
  }

  function stopTextMonitoring() {
    textScanningEnabled = false;
    if (textScanTimer !== null) {
      clearTimeout(textScanTimer);
      textScanTimer = null;
    }
    textObserver?.disconnect();
    textObserver = null;
  }

  function scheduleTextScan(delay = TEXT_RESCAN_DELAY_MS) {
    if (!textScanningEnabled || stopped) return;
    if (textScanTimer !== null) clearTimeout(textScanTimer);
    textScanTimer = setTimeout(() => {
      textScanTimer = null;
      analyzeVisibleText().catch((error) => showNotice({
        status: "uncertain",
        reason: error?.message || "The local text check could not finish. This page remains open.",
      }));
    }, delay);
  }

  function observeTextChanges() {
    if (textObserver || !document.body || typeof MutationObserver !== "function") return;
    textObserver = new MutationObserver((records) => {
      if (records.length) scheduleTextScan();
    });
    textObserver.observe(document.body, { childList: true, characterData: true, subtree: true });
  }

  async function analyzeVisibleText() {
    if (!textScanningEnabled || stopped) return;
    if (textScanInProgress) {
      textScanRequested = true;
      return;
    }
    const text = visibleText();
    if (!text.trim()) return;
    const fingerprint = textFingerprint(text);
    if (fingerprint === lastTextFingerprint) return;

    textScanInProgress = true;
    lastTextFingerprint = fingerprint;
    try {
      const response = await sendExtensionMessage({ type: "morvix-analyze-text", text })
        .catch((error) => ({ status: "offline", reason: error.message, contextInvalidated: /extension context invalidated/i.test(error.message || "") }));
      if (response?.error) {
        lastTextFingerprint = null;
        showNotice({ status: "uncertain", reason: response.error });
      } else if (response?.status === "result" || response?.status === "uncertain" || response?.status === "offline") {
        if (response.status === "uncertain" || response.status === "offline") lastTextFingerprint = null;
        showNotice(response);
      } else if (response?.status !== "skipped") {
        lastTextFingerprint = null;
        showNotice({ status: "uncertain", reason: "The local text check returned an invalid response. This page remains open." });
      }
      if (response?.category === "website_rule") stopTextMonitoring();
    } finally {
      textScanInProgress = false;
      if (textScanRequested && textScanningEnabled && !stopped) {
        textScanRequested = false;
        scheduleTextScan(0);
      }
    }
  }

  function visible(element) {
    const rect = element.getBoundingClientRect();
    return rect.width > 16 && rect.height > 16 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  }

  async function scanResources() {
    const images = [...document.images].filter((item) => item.currentSrc && item.naturalWidth > 0 && visible(item)).slice(0, 5);
    for (const image of images) {
      if (stopped) return;
      const response = await sendExtensionMessage({ type: "morvix-analyze-resource", modality: "image", url: image.currentSrc }).catch(() => null);
      if (response?.status === "result") showNotice(response, "image");
      else if (response?.status === "uncertain") showNotice(response, "image");
      else if (response?.status === "unavailable") break;
    }
    const video = [...document.querySelectorAll("video")].find((item) => (item.currentSrc || item.src) && visible(item));
    if (!stopped && video) {
      const response = await sendExtensionMessage({ type: "morvix-analyze-resource", modality: "video", url: video.currentSrc || video.src }).catch(() => null);
      if (response?.status === "result") showNotice(response, "video");
      else if (response?.status === "uncertain") showNotice(response, "video");
      else if (response?.status === "unavailable") showNotice(response, "video");
    }
  }

  async function start() {
    // Website rules apply even when there is no extractable text or text checks are disabled.
    const sitePolicy = await sendExtensionMessage({ type: "morvix-check-site-policy", modality: "text" }).catch((error) => ({
      status: "offline", reason: error.message,
      contextInvalidated: /extension context invalidated/i.test(error.message || ""),
    }));
    if (sitePolicy?.category === "website_rule") { showNotice(sitePolicy); return; }
    if (sitePolicy?.status === "offline") { showNotice(sitePolicy); return; }
    if (sitePolicy?.protectionEnabled === false || sitePolicy?.status === "skipped") return;

    if (sitePolicy.policy?.modalities?.text) {
      textScanningEnabled = true;
      observeTextChanges();
      await analyzeVisibleText();
    }
    const { cachedPolicy, policyFreshness } = (await sendExtensionMessage({ type: "morvix-get-content-status" }).catch(() => ({}))) || {};
    const policy = cachedPolicy?.policy;
    if (!stopped && policyFreshness?.fresh && policy?.protection_enabled && (policy?.modalities?.image || policy?.modalities?.video)) await scanResources();
  }

  window.addEventListener("pagehide", stopTextMonitoring, { once: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
