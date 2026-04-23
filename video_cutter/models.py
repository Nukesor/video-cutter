"""Shared data models and small value helpers used across the app."""

from __future__ import annotations

from dataclasses import dataclass


def format_seconds(value: float) -> str:
    """Format a playback time for labels in the UI."""
    total_seconds = max(0, int(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value into an inclusive range."""
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class CropRect:
    """Normalized crop rectangle stored on each section."""

    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0


@dataclass(slots=True)
class Section:
    """Editable cut range with its own crop state."""

    identifier: int
    start: float
    end: float
    crop: CropRect

    @property
    def duration(self) -> float:
        """Return the non-negative runtime of the section."""
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class MediaInfo:
    """Subset of probed media metadata needed by preview and export."""

    duration: float
    video_width: int
    video_height: int
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    container_extension: str
