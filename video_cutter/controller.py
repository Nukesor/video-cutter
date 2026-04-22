from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mpv
from PySide6.QtCore import (
    Q_ARG,
    Property,
    QAbstractListModel,
    QByteArray,
    QMetaObject,
    QModelIndex,
    QObject,
    QProcess,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from .debug import get_logger


def _format_seconds(value: float) -> str:
    total_seconds = max(0, int(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _coerce_local_path(path_or_url: str) -> Path | None:
    if not path_or_url:
        return None

    url = QUrl(path_or_url)
    if url.isLocalFile():
        return Path(url.toLocalFile())

    return Path(path_or_url)


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


class SectionsModel(QAbstractListModel):
    IdentifierRole = Qt.ItemDataRole.UserRole + 1
    StartRole = Qt.ItemDataRole.UserRole + 2
    EndRole = Qt.ItemDataRole.UserRole + 3
    DurationRole = Qt.ItemDataRole.UserRole + 4
    LabelRole = Qt.ItemDataRole.UserRole + 5
    CropSummaryRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sections: list[Section] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._sections)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._sections):
            return None

        section = self._sections[index.row()]
        if role == self.IdentifierRole:
            return section.identifier
        if role == self.StartRole:
            return section.start
        if role == self.EndRole:
            return section.end
        if role == self.DurationRole:
            return section.duration
        if role == self.LabelRole:
            return f"{_format_seconds(section.start)} - {_format_seconds(section.end)}"
        if role == self.CropSummaryRole:
            crop = section.crop
            return (
                f"Crop {crop.width * 100:.0f}% x {crop.height * 100:.0f}%"
                f" at {crop.x * 100:.0f}%, {crop.y * 100:.0f}%"
            )
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.IdentifierRole: QByteArray(b"identifier"),
            self.StartRole: QByteArray(b"start"),
            self.EndRole: QByteArray(b"end"),
            self.DurationRole: QByteArray(b"duration"),
            self.LabelRole: QByteArray(b"label"),
            self.CropSummaryRole: QByteArray(b"cropSummary"),
        }

    def section_at(self, index: int) -> Section | None:
        if 0 <= index < len(self._sections):
            return self._sections[index]
        return None

    def add_section(self, section: Section) -> None:
        insert_row = len(self._sections)
        self.beginInsertRows(QModelIndex(), insert_row, insert_row)
        self._sections.append(section)
        self.endInsertRows()

    def update_section(self, index: int, section: Section) -> None:
        if not 0 <= index < len(self._sections):
            return
        self._sections[index] = section
        model_index = self.index(index)
        self.dataChanged.emit(model_index, model_index)

    def remove_section(self, index: int) -> None:
        if not 0 <= index < len(self._sections):
            return
        self.beginRemoveRows(QModelIndex(), index, index)
        del self._sections[index]
        self.endRemoveRows()

    def clear(self) -> None:
        if not self._sections:
            return
        self.beginResetModel()
        self._sections.clear()
        self.endResetModel()

    def sections(self) -> list[Section]:
        return list(self._sections)


class VideoEditorController(QObject):
    sourceChanged = Signal()
    durationChanged = Signal()
    positionChanged = Signal()
    playingChanged = Signal()
    markersChanged = Signal()
    mutedChanged = Signal()
    selectedSectionChanged = Signal()
    selectedCropChanged = Signal()
    mediaInfoChanged = Signal()
    statusTextChanged = Signal()
    renderingChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger("video_cutter.controller")
        self._sections_model = SectionsModel(self)
        self._player = mpv.MPV(
            config=False,
            hwdec="no",
            loglevel="info",
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            vo="libmpv",
            log_handler=self._handle_mpv_log,
        )
        self._source_path: Path | None = None
        self._media_info: MediaInfo | None = None
        self._position = 0.0
        self._playing = False
        self._pending_start: float | None = None
        self._pending_end: float | None = None
        self._muted = False
        self._selected_section_index = -1
        self._next_section_id = 1
        self._status_text = "Open a video to start cutting sections."
        self._rendering = False
        self._render_output = ""
        self._render_destination: Path | None = None

        self._render_process = QProcess(self)
        self._render_process.setProgram("ffmpeg")
        self._render_process.readyReadStandardError.connect(self._consume_render_output)
        self._render_process.readyReadStandardOutput.connect(
            self._consume_render_output
        )
        self._render_process.finished.connect(self._handle_render_finished)
        self._render_process.errorOccurred.connect(self._handle_render_error)

        self._player.observe_property("time-pos", self._handle_time_position)
        self._player.observe_property("pause", self._handle_pause_state)
        self._log.info("controller initialized")

    @Property(QObject, constant=True)
    def sectionsModel(self) -> QObject:
        return self._sections_model

    @Property(str, notify=sourceChanged)
    def sourcePath(self) -> str:
        return str(self._source_path) if self._source_path else ""

    @Property(str, notify=sourceChanged)
    def sourceName(self) -> str:
        return self._source_path.name if self._source_path else ""

    @Property(str, notify=sourceChanged)
    def defaultOutputFileUrl(self) -> str:
        if self._source_path is None:
            return ""
        output_path = self._source_path.with_stem(f"{self._source_path.stem}_rendered")
        return QUrl.fromLocalFile(str(output_path)).toString()

    @Property(bool, notify=sourceChanged)
    def hasSource(self) -> bool:
        return self._source_path is not None

    @Property(float, notify=durationChanged)
    def duration(self) -> float:
        return self._media_info.duration if self._media_info else 0.0

    @Property(float, notify=positionChanged)
    def position(self) -> float:
        return self._position

    @Property(str, notify=positionChanged)
    def positionLabel(self) -> str:
        return _format_seconds(self._position)

    @Property(str, notify=durationChanged)
    def durationLabel(self) -> str:
        return _format_seconds(self.duration)

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        return self._playing

    @Property(float, notify=markersChanged)
    def pendingStart(self) -> float:
        return -1.0 if self._pending_start is None else self._pending_start

    @Property(float, notify=markersChanged)
    def pendingEnd(self) -> float:
        return -1.0 if self._pending_end is None else self._pending_end

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self._muted

    @Property(int, notify=selectedSectionChanged)
    def selectedSectionIndex(self) -> int:
        return self._selected_section_index

    @Property(bool, notify=selectedSectionChanged)
    def hasSelectedSection(self) -> bool:
        return self._sections_model.section_at(self._selected_section_index) is not None

    @Property("QVariantMap", notify=selectedCropChanged)
    def selectedCrop(self) -> dict[str, float]:
        section = self._sections_model.section_at(self._selected_section_index)
        crop = section.crop if section else CropRect()
        return {
            "x": crop.x,
            "y": crop.y,
            "width": crop.width,
            "height": crop.height,
        }

    @Property(int, notify=mediaInfoChanged)
    def videoWidth(self) -> int:
        return self._media_info.video_width if self._media_info else 0

    @Property(int, notify=mediaInfoChanged)
    def videoHeight(self) -> int:
        return self._media_info.video_height if self._media_info else 0

    @Property(bool, notify=renderingChanged)
    def rendering(self) -> bool:
        return self._rendering

    @Property(bool, notify=renderingChanged)
    def canRender(self) -> bool:
        return (
            self.hasSource
            and self._sections_model.rowCount() > 0
            and not self._rendering
        )

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @property
    def player(self) -> mpv.MPV:
        return self._player

    def _set_status_text(self, text: str) -> None:
        if text == self._status_text:
            return
        self._status_text = text
        self._log.info("status: %s", text)
        self.statusTextChanged.emit()

    def _set_rendering(self, rendering: bool) -> None:
        if rendering == self._rendering:
            return
        self._rendering = rendering
        self.renderingChanged.emit()

    def _selected_section(self) -> Section | None:
        return self._sections_model.section_at(self._selected_section_index)

    def _handle_mpv_log(
        self,
        level: str,
        prefix: str,
        message: str,
    ) -> None:
        self._log.debug("mpv[%s][%s] %s", level, prefix, message.rstrip())

    def _reset_editor_state(self) -> None:
        self._sections_model.clear()
        self._pending_start = None
        self._pending_end = None
        self._selected_section_index = -1
        self._next_section_id = 1
        self._position = 0.0
        self.markersChanged.emit()
        self.positionChanged.emit()
        self.selectedSectionChanged.emit()
        self.selectedCropChanged.emit()
        self.renderingChanged.emit()

    @Slot(float)
    def _apply_position_update(self, position: float) -> None:
        if math.isclose(position, self._position, abs_tol=0.01):
            return
        self._position = position
        self.positionChanged.emit()

    @Slot(bool)
    def _apply_playing_update(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        self.playingChanged.emit()

    def _handle_time_position(self, _name: str, value: Any) -> None:
        position = 0.0 if value is None else float(value)
        QMetaObject.invokeMethod(
            self,
            "_apply_position_update",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, position),
        )

    def _handle_pause_state(self, _name: str, value: Any) -> None:
        playing = not bool(value)
        QMetaObject.invokeMethod(
            self,
            "_apply_playing_update",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, playing),
        )

    def _probe_media(self, path: Path) -> MediaInfo:
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

        duration = float(
            video_stream.get("duration") or format_info.get("duration") or 0.0
        )

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

    def _consume_render_output(self) -> None:
        stderr = bytes(self._render_process.readAllStandardError()).decode(
            "utf-8",
            errors="replace",
        )
        stdout = bytes(self._render_process.readAllStandardOutput()).decode(
            "utf-8",
            errors="replace",
        )
        combined = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
        if not combined:
            return

        self._render_output = f"{self._render_output}\n{combined}".strip()
        last_line = self._render_output.splitlines()[-1]
        if last_line:
            self._log.info("ffmpeg: %s", last_line)
            self._set_status_text(last_line)

    def _handle_render_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        self._consume_render_output()
        self._set_rendering(False)
        self._log.info(
            "render finished exit_code=%s exit_status=%s",
            exit_code,
            int(exit_status),
        )

        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            destination = (
                str(self._render_destination) if self._render_destination else "output"
            )
            self._set_status_text(f"Rendered {destination}")
            return

        details = (
            self._render_output.splitlines()[-1]
            if self._render_output
            else "ffmpeg failed"
        )
        self._set_status_text(f"Render failed: {details}")

    def _handle_render_error(self, process_error: QProcess.ProcessError) -> None:
        self._set_rendering(False)
        self._log.exception("render process error: %s", int(process_error))
        if process_error == QProcess.ProcessError.FailedToStart:
            self._set_status_text("ffmpeg was not found. Install ffmpeg and try again.")
            return
        self._set_status_text("ffmpeg process error interrupted rendering.")

    def _emit_selection_change(self) -> None:
        self.selectedSectionChanged.emit()
        self.selectedCropChanged.emit()

    def _normalized_crop(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> CropRect:
        if self.videoWidth <= 0 or self.videoHeight <= 0:
            return CropRect()

        min_width = 1.0 / self.videoWidth
        min_height = 1.0 / self.videoHeight
        x = _clamp(x, 0.0, 1.0)
        y = _clamp(y, 0.0, 1.0)
        width = _clamp(width, min_width, 1.0 - x)
        height = _clamp(height, min_height, 1.0 - y)
        return CropRect(x=x, y=y, width=width, height=height)

    def _pixel_crop(self, crop: CropRect) -> tuple[int, int, int, int]:
        width = max(2, self.videoWidth)
        height = max(2, self.videoHeight)

        x = round(crop.x * width)
        y = round(crop.y * height)
        crop_width = round(crop.width * width)
        crop_height = round(crop.height * height)

        x = _clamp(x, 0, width - 1)
        y = _clamp(y, 0, height - 1)
        crop_width = int(_clamp(crop_width, 2, width - x))
        crop_height = int(_clamp(crop_height, 2, height - y))

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

    def _build_ffmpeg_arguments(self, output_path: Path) -> list[str]:
        assert self._source_path is not None
        assert self._media_info is not None

        sections = self._sections_model.sections()
        pixel_crops = [self._pixel_crop(section.crop) for section in sections]
        target_width = max(crop[2] for crop in pixel_crops)
        target_height = max(crop[3] for crop in pixel_crops)

        filter_parts: list[str] = []
        video_labels: list[str] = []
        audio_labels: list[str] = []

        for index, (section, crop) in enumerate(
            zip(sections, pixel_crops, strict=True),
        ):
            crop_x, crop_y, crop_width, crop_height = crop
            padded_label = f"vp{index}"
            filter_parts.append(
                ""
                f"[0:v]trim=start={section.start:.3f}:end={section.end:.3f},"
                f"setpts=PTS-STARTPTS,"
                f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"
                f"[{padded_label}]"
            )
            video_labels.append(f"[{padded_label}]")

            if self._media_info.has_audio and not self._muted:
                audio_label = f"a{index}"
                filter_parts.append(
                    ""
                    f"[0:a]atrim=start={section.start:.3f}:end={section.end:.3f},"
                    f"asetpts=PTS-STARTPTS[{audio_label}]"
                )
                audio_labels.append(f"[{audio_label}]")

        if len(video_labels) == 1:
            filter_parts.append(f"{video_labels[0]}null[vout]")
            if len(audio_labels) == 1:
                filter_parts.append(f"{audio_labels[0]}anull[aout]")
        else:
            filter_parts.append(
                f"{''.join(video_labels)}concat=n={len(video_labels)}:v=1:a=0[vout]",
            )
            if audio_labels:
                filter_parts.append(
                    f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[aout]"
                )

        arguments = [
            "-hide_banner",
            "-y",
            "-i",
            str(self._source_path),
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-c:v",
            self._media_info.video_codec,
        ]

        if (
            self._media_info.has_audio
            and not self._muted
            and self._media_info.audio_codec
        ):
            arguments.extend(
                [
                    "-map",
                    "[aout]",
                    "-c:a",
                    self._media_info.audio_codec,
                ],
            )
        else:
            arguments.append("-an")

        arguments.append(str(output_path))
        return arguments

    @Slot(str)
    def openFile(self, file_url: str) -> None:
        path = _coerce_local_path(file_url)
        if path is None:
            return

        self._log.info("opening file %s", path)

        try:
            media_info = self._probe_media(path)
        except FileNotFoundError:
            self._set_status_text(
                "ffprobe was not found. Install ffmpeg to inspect videos.",
            )
            return
        except (subprocess.CalledProcessError, ValueError) as error:
            self._set_status_text(f"Unable to open video: {error}")
            return

        self._source_path = path
        self._media_info = media_info
        self._reset_editor_state()
        self.sourceChanged.emit()
        self.durationChanged.emit()
        self.mediaInfoChanged.emit()

        self._player.play(str(path))
        self._player.pause = True
        self._set_status_text(f"Loaded {path.name}")

    @Slot()
    def togglePlayback(self) -> None:
        if not self.hasSource:
            return
        self._player.pause = self._playing

    @Slot(float)
    def seekTo(self, seconds: float) -> None:
        if not self.hasSource:
            return
        target = _clamp(seconds, 0.0, self.duration)
        self._player.seek(target, reference="absolute", precision="exact")
        self._position = target
        self.positionChanged.emit()

    @Slot()
    def markStart(self) -> None:
        if not self.hasSource:
            return
        self._pending_start = self._position
        self.markersChanged.emit()

    @Slot()
    def markEnd(self) -> None:
        if not self.hasSource:
            return
        self._pending_end = self._position
        self.markersChanged.emit()

    @Slot()
    def clearMarkers(self) -> None:
        self._pending_start = None
        self._pending_end = None
        self.markersChanged.emit()

    @Slot()
    def addSectionFromMarkers(self) -> None:
        if self._pending_start is None or self._pending_end is None:
            self._set_status_text("Set both a start and an end marker first.")
            return

        start = min(self._pending_start, self._pending_end)
        end = max(self._pending_start, self._pending_end)
        if math.isclose(start, end, abs_tol=0.01):
            self._set_status_text("Section duration must be greater than zero.")
            return

        section = Section(
            identifier=self._next_section_id,
            start=start,
            end=end,
            crop=CropRect(),
        )
        self._next_section_id += 1
        self._sections_model.add_section(section)
        self._selected_section_index = self._sections_model.rowCount() - 1
        self._emit_selection_change()
        self.renderingChanged.emit()
        self._log.info(
            "added section id=%s start=%.3f end=%.3f",
            section.identifier,
            start,
            end,
        )
        self._set_status_text(
            f"Added section {_format_seconds(start)} - {_format_seconds(end)}",
        )

    @Slot(int)
    def selectSection(self, index: int) -> None:
        if index == self._selected_section_index:
            return
        if self._sections_model.section_at(index) is None:
            return
        self._selected_section_index = index
        self._log.info("selected section index=%s", index)
        self._emit_selection_change()

    @Slot(int)
    def removeSection(self, index: int) -> None:
        if self._sections_model.section_at(index) is None:
            return
        self._log.info("removing section index=%s", index)
        self._sections_model.remove_section(index)
        if not self._sections_model.rowCount():
            self._selected_section_index = -1
        elif index <= self._selected_section_index:
            self._selected_section_index = max(0, self._selected_section_index - 1)
        self._emit_selection_change()
        self.renderingChanged.emit()

    @Slot()
    def resetSelectedCrop(self) -> None:
        section = self._selected_section()
        if section is None:
            return
        self._sections_model.update_section(
            self._selected_section_index,
            Section(
                identifier=section.identifier,
                start=section.start,
                end=section.end,
                crop=CropRect(),
            ),
        )
        self.selectedCropChanged.emit()

    @Slot(float, float, float, float)
    def setSelectedCropNormalized(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        section = self._selected_section()
        if section is None:
            return
        crop = self._normalized_crop(x, y, width, height)
        self._log.info(
            "updated crop index=%s x=%.3f y=%.3f w=%.3f h=%.3f",
            self._selected_section_index,
            crop.x,
            crop.y,
            crop.width,
            crop.height,
        )
        self._sections_model.update_section(
            self._selected_section_index,
            Section(
                identifier=section.identifier,
                start=section.start,
                end=section.end,
                crop=crop,
            ),
        )
        self.selectedCropChanged.emit()

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        if muted == self._muted:
            return
        self._muted = muted
        self._log.info("muted=%s", muted)
        self.mutedChanged.emit()

    @Slot(str)
    def renderTo(self, output_file_url: str) -> None:
        if not self.canRender or self._source_path is None or self._media_info is None:
            return

        output_path = _coerce_local_path(output_file_url)
        if output_path is None:
            return

        if output_path == self._source_path:
            self._set_status_text(
                "Choose a different output file than the source video.",
            )
            return

        if output_path.suffix.lower() != self._media_info.container_extension.lower():
            output_path = output_path.with_suffix(self._media_info.container_extension)

        self._render_output = ""
        self._render_destination = output_path
        self._set_rendering(True)
        self._set_status_text(f"Rendering {output_path.name}...")

        arguments = self._build_ffmpeg_arguments(output_path)
        self._log.info("starting ffmpeg with args: %s", arguments)
        self._render_process.setArguments(arguments)
        self._render_process.start()

    @Slot()
    def shutdown(self) -> None:
        self._log.info("controller shutdown")
        if self._render_process.state() != QProcess.ProcessState.NotRunning:
            self._render_process.kill()
            self._render_process.waitForFinished(1000)
        self._player.terminate()
