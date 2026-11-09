"""Bounded video decoding and 16-frame local VideoMAE inference."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from backend.app import config
from backend.app.classifiers import ClassifierUnavailable, classify_video_frames

VIDEO_MODEL_INPUT_FRAMES = 16


def classify_video(video_bytes: bytes, content_type: str) -> dict:
    if not video_bytes or len(video_bytes) > config.MAX_VIDEO_BYTES:
        raise ValueError(f"Video must be between 1 byte and {config.MAX_VIDEO_BYTES:,} bytes.")
    if content_type not in {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}:
        raise ValueError("Supported video uploads are MP4, WebM, MOV and AVI.")
    if importlib.util.find_spec("cv2") is None:
        raise ClassifierUnavailable("OpenCV is required to decode supported videos locally.")

    import cv2
    from PIL import Image

    suffix = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov", "video/x-msvideo": ".avi"}[content_type]
    temp_dir = config.ROOT / "data" / "tmp_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"morvix-{uuid.uuid4().hex}{suffix}"
    capture = None
    try:
        temp_path.write_bytes(video_bytes)
        capture = cv2.VideoCapture(str(temp_path))
        if not capture.isOpened():
            raise ValueError("The video cannot be decoded by this local OpenCV build.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or total_frames <= 0:
            raise ValueError("Video duration or frame rate could not be read.")
        duration = total_frames / fps
        if duration > config.MAX_VIDEO_SECONDS:
            raise ValueError(f"Video duration exceeds the {config.MAX_VIDEO_SECONDS}-second limit.")

        unique_sample_count = min(total_frames, VIDEO_MODEL_INPUT_FRAMES, config.VIDEO_MAX_FRAMES)
        indices = (
            [round(i * (total_frames - 1) / (unique_sample_count - 1)) for i in range(unique_sample_count)]
            if unique_sample_count > 1 else [0]
        )
        frames = []
        for frame_index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))
        if not frames:
            raise ValueError("No readable frames were found for analysis.")
        unique_frames_analyzed = len(frames)
        # VideoMAE expects a fixed 16-frame clip; repeat the final decoded frame for very short clips.
        model_frames = frames + [frames[-1]] * (VIDEO_MODEL_INPUT_FRAMES - len(frames))
        result = classify_video_frames(model_frames)
        return {
            **result,
            "sampling": {
                "strategy": "evenly spaced frames across the clip",
                "frames_analyzed": unique_frames_analyzed,
                "model_input_frames": VIDEO_MODEL_INPUT_FRAMES,
                "duration_seconds": round(duration, 2),
                "temporal_model": True,
            },
        }
    except ClassifierUnavailable:
        raise
    finally:
        if capture is not None:
            capture.release()
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
