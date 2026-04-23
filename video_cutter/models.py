from __future__ import annotations

from dataclasses import dataclass


def format_seconds(value: float) -> str:
    total_seconds = max(0, int(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class CropRect:
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0


@dataclass(slots=True)
class Section:
    identifier: int
    start: float
    end: float
    crop: CropRect

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class MediaInfo:
    duration: float
    video_width: int
    video_height: int
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    container_extension: str
