from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import MediaInfo


def probe_media(path: Path) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError("Selected file has no video stream.")

    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )

    duration = float(video_stream.get("duration") or format_info.get("duration") or 0.0)
    container_extension = path.suffix or ".mp4"

    return MediaInfo(
        duration=duration,
        video_width=int(video_stream.get("width") or 0),
        video_height=int(video_stream.get("height") or 0),
        video_codec=str(video_stream.get("codec_name") or "h264"),
        audio_codec=(
            str(audio_stream.get("codec_name"))
            if audio_stream and audio_stream.get("codec_name")
            else None
        ),
        has_audio=audio_stream is not None,
        container_extension=container_extension,
    )
