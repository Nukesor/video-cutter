"""Pure helpers for planning ffmpeg work from editor state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import CropRect, MediaInfo, Section, clamp


@dataclass(slots=True)
class RenderJob:
    """One fully planned ffmpeg invocation for a single section."""

    section: Section
    output_path: Path
    arguments: list[str]


def plan_render_jobs(
    source_path: Path,
    media_info: MediaInfo,
    sections: list[Section],
    output_directory: Path,
    *,
    muted: bool,
) -> list[RenderJob]:
    """Build the ordered render queue for the current set of sections."""
    jobs: list[RenderJob] = []
    for section in sections:
        output_path = section_output_path(
            source_path,
            media_info,
            output_directory,
            section,
        )
        jobs.append(
            RenderJob(
                section=section,
                output_path=output_path,
                arguments=build_ffmpeg_arguments(
                    source_path,
                    media_info,
                    section,
                    output_path,
                    muted=muted,
                ),
            )
        )
    return jobs


def build_ffmpeg_arguments(
    source_path: Path,
    media_info: MediaInfo,
    section: Section,
    output_path: Path,
    *,
    muted: bool,
) -> list[str]:
    """Build the ffmpeg arguments for trimming and cropping one section."""
    crop_x, crop_y, crop_width, crop_height = pixel_crop(
        section.crop,
        media_info.video_width,
        media_info.video_height,
    )
    filter_parts = [
        ""
        f"[0:v]trim=start={section.start:.3f}:end={section.end:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}"
        "[vout]"
    ]

    if media_info.has_audio and not muted:
        filter_parts.append(
            ""
            f"[0:a]atrim=start={section.start:.3f}:end={section.end:.3f},"
            "asetpts=PTS-STARTPTS[aout]"
        )

    arguments = [
        "-hide_banner",
        "-y",
        "-i",
        str(source_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
    ]

    if media_info.has_audio and not muted:
        arguments.extend(["-map", "[aout]"])
    else:
        arguments.append("-an")

    arguments.append(str(output_path))
    return arguments


def pixel_crop(
    crop: CropRect,
    video_width: int,
    video_height: int,
) -> tuple[int, int, int, int]:
    """Convert a normalized crop rectangle into ffmpeg-safe pixel bounds."""
    width = max(2, video_width)
    height = max(2, video_height)

    x = round(crop.x * width)
    y = round(crop.y * height)
    crop_width = round(crop.width * width)
    crop_height = round(crop.height * height)

    x = clamp(x, 0, width - 1)
    y = clamp(y, 0, height - 1)
    crop_width = int(clamp(crop_width, 2, width - x))
    crop_height = int(clamp(crop_height, 2, height - y))

    if crop_width % 2 and crop_width > 2:
        crop_width -= 1
    if crop_height % 2 and crop_height > 2:
        crop_height -= 1
    if x % 2 and x > 0:
        x -= 1
    if y % 2 and y > 0:
        y -= 1

    x = min(x, width - crop_width)
    y = min(y, height - crop_height)
    return int(x), int(y), int(crop_width), int(crop_height)


def section_output_path(
    source_path: Path,
    media_info: MediaInfo,
    output_directory: Path,
    section: Section,
) -> Path:
    """Return the output filename used for a rendered section."""
    suffix = source_path.suffix or media_info.container_extension
    return output_directory / f"{source_path.stem}_section{section.identifier}{suffix}"
