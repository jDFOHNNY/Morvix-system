"use strict";

(function attachClassifierCopy(global) {
  const STATUS = {
    ready: ["Loaded and validated in this backend process", "pill-allow"],
    available_unloaded: ["Local files found; load check pending", "pill-muted"],
    incompatible_checkpoint_labels: ["Unavailable: verified label map missing", "pill-warn"],
    missing_weights: ["Unavailable: model files missing", "pill-warn"],
    invalid_model_files: ["Unavailable: model snapshot is incomplete or invalid", "pill-warn"],
    loading_failed: ["Unavailable: local model failed to load", "pill-warn"],
    inference_failed: ["Unavailable: most recent inference failed", "pill-warn"],
    install_ml_dependencies: ["Unavailable: install ML dependencies", "pill-warn"],
    install_image_dependencies: ["Unavailable: install image dependencies", "pill-warn"],
    install_video_dependencies: ["Unavailable: install video dependencies", "pill-warn"],
  };

  const MODALITY_POLICY = {
    text: "Policy setting only. When enabled, accessible text may be sent to the local backend. The available model returns an English toxic-comment threat score; it has not been evaluated for MORVIX use.",
    image: "Policy setting only. Image detection is unavailable: the local checkpoint has no verified class-to-label map, so image uploads are rejected during classifier preflight.",
    video: "When enabled and available, supported videos are analyzed by local VideoMAE. It samples 16 frames, ignores audio, and has not been evaluated on MORVIX data.",
  };

  const CATEGORY_COVERAGE = {
    violence: "Candidate output comes from video only (binary violent/non-violent). Image classification is unavailable, and the video model has not been validated for MORVIX's graphic-violence definition.",
    threat_language: "The text model exposes the English toxic-comment threat label. This is not a validated general threat detector; language, domain, and bias limitations apply.",
    self_harm_indicators: "Policy category only. No self-harm classifier is installed or supported, so MORVIX does not detect this category.",
  };

  function status(value) {
    const [label, tone] = STATUS[value] || ["Unavailable: status not recognized", "pill-warn"];
    return { label, tone };
  }

  const api = Object.freeze({
    status,
    modalityPolicy: (key) => MODALITY_POLICY[key] || "Policy setting; classifier coverage is not configured.",
    categoryCoverage: (key) => CATEGORY_COVERAGE[key] || "No classifier coverage is documented for this category.",
  });

  global.MorvixClassifierCopy = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
