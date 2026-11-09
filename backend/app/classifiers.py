"""Replaceable local model adapters. Weights are loaded from disk only, never from runtime APIs."""

from __future__ import annotations

import importlib.util
import json
import threading
import unicodedata
from pathlib import Path

from backend.app import config

TEXT_MODEL_NAME = "unitary/toxic-bert"
IMAGE_MODEL_NAME = "jaranohaal/vit-base-violence-detection"
VIDEO_MODEL_NAME = "HappyGook/videomae-violence-detector"
TEXT_CLASSIFIER_VERSION = "unitary/toxic-bert (local snapshot)"
IMAGE_CLASSIFIER_VERSION = "jaranohaal/vit-base-violence-detection (local snapshot)"
VIDEO_CLASSIFIER_VERSION = "HappyGook/videomae-violence-detector (local snapshot)"

_lock = threading.RLock()
_text_model = None
_text_tokenizer = None
_image_model = None
_image_processor = None
_video_model = None
_video_processor = None
_loaded = {"text": False, "image": False, "video": False}
_load_failures: dict[str, str] = {}
_inference_failures: dict[str, str] = {}


class ClassifierUnavailable(RuntimeError):
    """Raised when a required local dependency or model artifact cannot be loaded."""


def _weights_present(path: Path) -> bool:
    return path.is_dir() and (path / "config.json").exists() and any(
        candidate.exists()
        for candidate in (path / "model.safetensors", path / "pytorch_model.bin", path / "model.safetensors.index.json")
    )


def _declared_image_labels(path: Path) -> list[str]:
    try:
        metadata = json.loads((path / "config.json").read_text(encoding="utf-8"))
        return [str(label).lower().replace("_", "-") for label in metadata.get("id2label", {}).values()]
    except (OSError, ValueError, TypeError):
        return []


def _is_positive_violence_label(label: str) -> bool:
    normalized = str(label).lower().replace("_", "-").strip()
    return "non-violent" not in normalized and "non-violence" not in normalized and (
        "violent" in normalized or "violence" in normalized
    )


def _missing_ml_dependencies() -> list[str]:
    """Return required local-model packages missing from this Python environment."""
    return [
        package
        for package in ("torch", "transformers", "safetensors")
        if importlib.util.find_spec(package) is None
    ]


def _text_snapshot_problem() -> tuple[str, str] | None:
    """Check the local text snapshot contract without loading model weights."""
    path = config.TEXT_MODEL_PATH
    if not path.is_dir():
        return "missing_weights", "The local text model snapshot is not present."

    weights = path / "model.safetensors"
    index_file = path / "model.safetensors.index.json"
    if weights.is_file():
        pass
    elif index_file.is_file():
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
            shards = set(index.get("weight_map", {}).values())
            if not shards or any(Path(name).name != name or not (path / name).is_file() for name in shards):
                return "invalid_model_files", "The text model safetensors index is invalid or a shard is missing."
        except (OSError, ValueError, TypeError, AttributeError):
            return "invalid_model_files", "The text model safetensors index is invalid or unreadable."
    elif (path / "pytorch_model.bin").is_file():
        return "invalid_model_files", "The text snapshot has non-safetensors weights; MORVIX requires safetensors."
    else:
        return "missing_weights", "The text model safetensors weights are missing."

    config_file = path / "config.json"
    if not config_file.is_file():
        return "invalid_model_files", "The text snapshot is missing config.json."
    try:
        metadata = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "invalid_model_files", "The text snapshot config.json is invalid or unreadable."
    labels = metadata.get("id2label")
    if not isinstance(labels, dict) or not labels:
        return "invalid_model_files", "The text model config has no verified id2label mapping."
    try:
        indexed_labels = [(int(index), str(label)) for index, label in labels.items()]
    except (TypeError, ValueError):
        return "invalid_model_files", "The text model id2label mapping has invalid class indexes."
    if len({index for index, _ in indexed_labels}) != len(indexed_labels) or not any(
        "threat" in label.lower() for _, label in indexed_labels
    ):
        return "invalid_model_files", "The text model config has no unique, documented threat label mapping."

    tokenizer_assets = ("tokenizer.json", "vocab.txt", "spiece.model", "sentencepiece.bpe.model")
    if not any((path / name).is_file() for name in tokenizer_assets):
        return "invalid_model_files", "The text snapshot is missing its tokenizer vocabulary or tokenizer.json."
    return None


def _text_readiness_detail() -> dict:
    missing_dependencies = _missing_ml_dependencies()
    snapshot_problem = _text_snapshot_problem()
    if _loaded["text"]:
        if "text" in _inference_failures:
            status = "inference_failed"
            message = "The model initialized, but its most recent inference failed. Inspect the local backend logs."
        else:
            status = "ready"
            message = "The local text model initialized and its documented label mapping was checked."
    elif "text" in _load_failures:
        status = "loading_failed"
        message = _load_failures["text"]
    elif snapshot_problem:
        status, message = snapshot_problem
    elif missing_dependencies:
        status = "install_ml_dependencies"
        message = "Install the missing local model dependencies listed in requirements-ml.txt."
    else:
        status = "available_unloaded"
        message = "The snapshot and runtime dependencies are present; model initialization has not yet run."
    return {
        "status": status,
        "message": message,
        "missing_dependencies": missing_dependencies,
        "last_inference": "failed" if "text" in _inference_failures else "not_failed",
    }


def classifier_diagnostics() -> dict[str, dict]:
    """Safe readiness detail for health checks; never returns private paths or tracebacks."""
    details = _text_readiness_detail()
    statuses = classifier_readiness()
    return {
        "text": details,
        "image": {"status": statuses["image"], "message": "See the image classifier status; this build does not report image inference as ready unless its approved local model initializes."},
        "video": {"status": statuses["video"], "message": "See the video classifier status; this build does not report video inference as ready unless its approved local model initializes."},
    }


def classifier_readiness() -> dict[str, str]:
    ml_dependencies_ready = not _missing_ml_dependencies()
    pillow = importlib.util.find_spec("PIL") is not None
    opencv = importlib.util.find_spec("cv2") is not None
    text = _text_readiness_detail()["status"]
    image_labels = _declared_image_labels(config.IMAGE_MODEL_PATH) if _weights_present(config.IMAGE_MODEL_PATH) else []
    if _loaded["image"]:
        image = "ready"
    elif not _weights_present(config.IMAGE_MODEL_PATH):
        image = "missing_weights"
    elif not any(_is_positive_violence_label(label) for label in image_labels):
        image = "incompatible_checkpoint_labels"
    elif not ml_dependencies_ready:
        image = "install_ml_dependencies"
    elif not pillow:
        image = "install_image_dependencies"
    else:
        image = "available_unloaded"
    if _loaded["video"]:
        video = "ready"
    elif not _weights_present(config.VIDEO_MODEL_PATH):
        video = "missing_weights"
    elif not ml_dependencies_ready:
        video = "install_ml_dependencies"
    elif not opencv or not pillow:
        video = "install_video_dependencies"
    else:
        video = "available_unloaded"
    return {"text": text, "image": image, "video": video}


def _require_model(path: Path, modality: str) -> None:
    if not _weights_present(path):
        raise ClassifierUnavailable(
            f"The local {modality} model weights are missing. Provide the approved snapshot described in docs/MODEL_INVENTORY.md."
        )
    missing_dependencies = _missing_ml_dependencies()
    if missing_dependencies:
        raise ClassifierUnavailable(
            "Local classifier dependencies are missing from this Python environment: "
            f"{', '.join(missing_dependencies)}. Install the optional packages listed in requirements-ml.txt."
        )


def _load_text_model():
    global _text_model, _text_tokenizer
    with _lock:
        if _text_model is not None:
            return _text_model, _text_tokenizer
        snapshot_problem = _text_snapshot_problem()
        if snapshot_problem:
            raise ClassifierUnavailable(snapshot_problem[1])
        _require_model(config.TEXT_MODEL_PATH, "text")
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            _text_tokenizer = AutoTokenizer.from_pretrained(str(config.TEXT_MODEL_PATH), local_files_only=True)
            _text_model = AutoModelForSequenceClassification.from_pretrained(
                str(config.TEXT_MODEL_PATH), local_files_only=True, use_safetensors=True
            )
            _text_model.eval()
            labels = [str(label).lower() for label in _text_model.config.id2label.values()]
            if not any("threat" in label for label in labels):
                _text_model = _text_tokenizer = None
                raise ClassifierUnavailable("The configured text model does not expose the documented threat label.")
            _loaded["text"] = True
            _load_failures.pop("text", None)
            _inference_failures.pop("text", None)
        except ClassifierUnavailable:
            raise
        except Exception as exc:
            _text_model = _text_tokenizer = None
            _load_failures["text"] = "The local text model files passed basic checks but could not be loaded by this runtime. Inspect the local backend logs."
            raise ClassifierUnavailable(_load_failures["text"]) from exc
        return _text_model, _text_tokenizer


def _load_image_model():
    global _image_model, _image_processor
    with _lock:
        if _image_model is not None:
            return _image_model, _image_processor
        if not _weights_present(config.IMAGE_MODEL_PATH):
            _require_model(config.IMAGE_MODEL_PATH, "image")
        if importlib.util.find_spec("PIL") is None:
            raise ClassifierUnavailable("Pillow is required for safe image decoding.")
        labels = _declared_image_labels(config.IMAGE_MODEL_PATH)
        if not any(_is_positive_violence_label(label) for label in labels):
            raise ClassifierUnavailable(
                "The downloaded image checkpoint has no documented violence label map; no label order will be assumed."
            )
        _require_model(config.IMAGE_MODEL_PATH, "image")
        try:
            from transformers import AutoImageProcessor, AutoModelForImageClassification

            _image_processor = AutoImageProcessor.from_pretrained(str(config.IMAGE_MODEL_PATH), local_files_only=True)
            _image_model = AutoModelForImageClassification.from_pretrained(
                str(config.IMAGE_MODEL_PATH), local_files_only=True, use_safetensors=True
            )
            _image_model.eval()
            labels = [str(label) for label in _image_model.config.id2label.values()]
            if not any(_is_positive_violence_label(label) for label in labels):
                _image_model = _image_processor = None
                raise ClassifierUnavailable("The configured image model does not expose a violence label.")
            _loaded["image"] = True
        except ClassifierUnavailable:
            raise
        except Exception as exc:
            _image_model = _image_processor = None
            raise ClassifierUnavailable("The local image model could not be loaded. Check the model files and ML setup.") from exc
        return _image_model, _image_processor


def _load_video_model():
    global _video_model, _video_processor
    with _lock:
        if _video_model is not None:
            return _video_model, _video_processor
        _require_model(config.VIDEO_MODEL_PATH, "video")
        try:
            from safetensors.torch import load_file
            from transformers import AutoConfig, AutoModelForVideoClassification, AutoProcessor

            _video_processor = AutoProcessor.from_pretrained(str(config.VIDEO_MODEL_PATH), local_files_only=True)
            model_config = AutoConfig.from_pretrained(str(config.VIDEO_MODEL_PATH), local_files_only=True)
            _video_model = AutoModelForVideoClassification.from_config(model_config)
            checkpoint_path = config.VIDEO_MODEL_PATH / "model.safetensors"
            if not checkpoint_path.is_file():
                raise ClassifierUnavailable("The pinned video checkpoint must contain a single safetensors file.")
            checkpoint = load_file(str(checkpoint_path), device="cpu")
            adapted = _adapt_videomae_checkpoint(checkpoint, _video_model.state_dict().keys())
            _video_model.load_state_dict(adapted, strict=True)
            _video_model.eval()
            config_labels = {
                str(label).lower().replace("_", "-"): int(index)
                for index, label in _video_model.config.id2label.items()
            }
            if not any("violent" in label and "non-violent" not in label for label in config_labels):
                # The model card documents index 0 as non-violent and index 1 as violent.
                manifest = json.loads((config.VIDEO_MODEL_PATH / "manifest.json").read_text(encoding="utf-8"))
                labels = manifest.get("supported_labels", [])
                if labels != ["non-violent", "violent"]:
                    _video_model = _video_processor = None
                    raise ClassifierUnavailable("The local video checkpoint has no verified violence label mapping.")
            _loaded["video"] = True
        except ClassifierUnavailable:
            raise
        except Exception as exc:
            _video_model = _video_processor = None
            raise ClassifierUnavailable("The local video classifier could not be loaded. Check the model files and ML setup.") from exc
        return _video_model, _video_processor


def prepare_classifier(modality: str) -> None:
    """Load and validate a media model before a client uploads its media bytes."""
    if modality == "image":
        _load_image_model()
    elif modality == "video":
        _load_video_model()
    else:
        raise ValueError("Only image and video classifiers can be preflighted.")


def _adapt_videomae_checkpoint(checkpoint: dict, expected_keys) -> dict:
    """Map equivalent HF VideoMAE attention bias names and reject all partial loads.

    This pinned checkpoint stores separate query/key/value biases. Transformers'
    VideoMAE stores only query/value biases; key bias is a softmax-invariant
    additive constant and is intentionally omitted by that architecture.
    """
    expected = set(expected_keys)
    adapted = {}
    discarded_key_biases = []
    for name, tensor in checkpoint.items():
        if name.endswith(".attention.attention.query.bias"):
            target = name.removesuffix("query.bias") + "q_bias"
        elif name.endswith(".attention.attention.value.bias"):
            target = name.removesuffix("value.bias") + "v_bias"
        elif name.endswith(".attention.attention.key.bias"):
            discarded_key_biases.append(name)
            continue
        else:
            target = name
        if target in adapted:
            raise ClassifierUnavailable("The local video checkpoint has duplicate mapped parameter names.")
        adapted[target] = tensor

    missing = expected - adapted.keys()
    unexpected = adapted.keys() - expected
    if missing or unexpected:
        raise ClassifierUnavailable(
            "The local video checkpoint is incompatible; strict weight validation found missing or unexpected parameters."
        )
    expected_key_biases = {
        name.removesuffix("q_bias") + "key.bias"
        for name in expected
        if name.endswith("q_bias")
    }
    if set(discarded_key_biases) != expected_key_biases:
        raise ClassifierUnavailable("The local video checkpoint contains an unrecognized attention-bias layout.")
    return adapted


def classify_text(text: str) -> dict:
    normalized = unicodedata.normalize("NFC", text).strip()
    if not normalized:
        raise ValueError("Text must contain at least one visible character.")
    if len(normalized) > config.MAX_TEXT_CHARS:
        raise ValueError(f"Text exceeds the {config.MAX_TEXT_CHARS:,}-character processing limit.")
    model, tokenizer = _load_text_model()
    try:
        import torch

        # Page extraction is capped at 20k characters by the extension/API, but a
        # single BERT input is only 512 tokens. Run overlapping windows so text
        # later in a long article is still considered. Scores are aggregated by
        # maximum across windows; this is a practical heuristic, not calibration.
        batch = tokenizer(
            normalized,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=512,
            return_overflowing_tokens=True,
            stride=64,
        )
        model_inputs = {
            name: value
            for name, value in batch.items()
            if name not in {"overflow_to_sample_mapping", "num_truncated_tokens", "special_tokens_mask"}
        }
        with torch.inference_mode():
            logits = model(**model_inputs).logits
            probabilities = torch.sigmoid(logits)
            label_to_score = {
                str(label).lower(): float(probabilities[:, int(index)].max().item())
                for index, label in model.config.id2label.items()
            }
        threat_score = next(score for label, score in label_to_score.items() if "threat" in label)
    except ClassifierUnavailable as exc:
        _inference_failures["text"] = "inference_failed"
        raise exc
    except Exception as exc:
        _inference_failures["text"] = "inference_failed"
        raise ClassifierUnavailable("The local text classifier could not complete inference.") from exc
    _inference_failures.pop("text", None)
    return {
        "modality": "text",
        "category": "threat_language" if threat_score >= 0.50 else None,
        "confidence": threat_score,
        "scores": {"threat_language": threat_score},
        "classifier": TEXT_CLASSIFIER_VERSION,
        "supported_categories": ["threat_language"],
        "status": "classified",
    }


def _decode_image(image_bytes: bytes):
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
        import io

        Image.MAX_IMAGE_PIXELS = 30_000_000
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        image = Image.open(io.BytesIO(image_bytes))
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Supported image formats are JPEG, PNG and WebP.")
        if image.width < 1 or image.height < 1 or image.width * image.height > 30_000_000:
            raise ValueError("Image dimensions exceed the safe processing limit.")
        image.load()
        return image.convert("RGB")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The uploaded file is not a supported, readable image.") from exc


def classify_image(image_bytes: bytes) -> dict:
    if not image_bytes or len(image_bytes) > config.MAX_IMAGE_BYTES:
        raise ValueError(f"Image must be between 1 byte and {config.MAX_IMAGE_BYTES:,} bytes.")
    image = _decode_image(image_bytes)
    model, processor = _load_image_model()
    try:
        import torch

        inputs = processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**inputs).logits[0]
            probabilities = torch.softmax(logits, dim=-1).tolist()
        label_to_score = {
            str(label).lower().replace("_", "-"): float(probabilities[int(index)])
            for index, label in model.config.id2label.items()
        }
        violence_score = next(score for label, score in label_to_score.items() if _is_positive_violence_label(label))
    except Exception as exc:
        if isinstance(exc, ClassifierUnavailable):
            raise
        raise ClassifierUnavailable("The local image classifier could not complete inference.") from exc
    return {
        "modality": "image",
        "category": "violence" if violence_score >= 0.50 else None,
        "confidence": violence_score,
        "scores": {"violence": violence_score},
        "classifier": IMAGE_CLASSIFIER_VERSION,
        "supported_categories": ["violence"],
        "status": "classified",
    }


def classify_video_frames(frames) -> dict:
    """Classify a bounded sequence of decoded RGB PIL frames with the local video model."""
    if not frames:
        raise ValueError("At least one decoded video frame is required.")
    model, processor = _load_video_model()
    try:
        import torch

        inputs = processor(frames, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**inputs).logits[0]
            probabilities = torch.softmax(logits, dim=-1).tolist()
        labels = {
            int(index): str(label).lower().replace("_", "-")
            for index, label in model.config.id2label.items()
        }
        violent_index = next((index for index, label in labels.items() if "violent" in label and "non-violent" not in label), None)
        if violent_index is None:
            violent_index = 1  # The pinned model card documents index 1 as violent.
        violence_score = float(probabilities[violent_index])
    except ClassifierUnavailable:
        raise
    except Exception as exc:
        raise ClassifierUnavailable("The local video classifier could not complete inference.") from exc
    return {
        "modality": "video",
        "category": "violence" if violence_score >= 0.50 else None,
        "confidence": violence_score,
        "scores": {"violence": violence_score},
        "classifier": VIDEO_CLASSIFIER_VERSION,
        "supported_categories": ["violence"],
        "status": "classified",
    }

