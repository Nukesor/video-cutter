"""Main backend controller exposed to QML as the editor state facade."""

from __future__ import annotations

import math
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import mpv
from PySide6.QtCore import (
    Q_ARG,
    Property,
    QMetaObject,
    QObject,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from .debug import get_logger
from .media import probe_media
from .models import CropRect, MediaInfo, Section, clamp, format_seconds
from .persistence import DialogDirectoryState, DialogDirectoryStore
from .render_runner import RenderRunner
from .rendering import plan_render_jobs
from .sections_model import SectionsModel


def _coerce_local_path(path_or_url: str) -> Path | None:
    """Convert a QML file or folder URL into a local path."""
    if not path_or_url:
        return None

    url = QUrl(path_or_url)
    if url.isLocalFile():
        return Path(url.toLocalFile())

    return Path(path_or_url)


class VideoEditorController(QObject):
    """Coordinate playback, section editing, and rendering for the QML UI."""

    sourceChanged = Signal()
    dialogDirectoriesChanged = Signal()
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
    renderabilityChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the editor backend and its long-lived collaborators."""
        super().__init__(parent)
        self._log = get_logger("video_cutter.controller")
        self._sections_model = SectionsModel(self)
        self._directory_store = DialogDirectoryStore(
            Path.home() / ".local" / "state" / "video_cutter.json"
        )
        self._dialog_state = DialogDirectoryState()
        self._player = mpv.MPV(
            config=False,
            hwdec="no",
            keep_open="yes",
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
        self._eof_reached = False
        self._preview_section_end: float | None = None
        self._status_text = "Open a video to start cutting sections."
        self._render_runner = RenderRunner(self)
        self._render_runner.runningChanged.connect(self._handle_render_state_change)
        self._render_runner.statusMessage.connect(self._set_status_text)

        self._player.observe_property("time-pos", self._handle_time_position)
        self._player.observe_property("pause", self._handle_pause_state)
        self._player.observe_property("eof-reached", self._handle_eof_reached)
        self._dialog_state = self._directory_store.load()
        self._log.info("controller initialized")

    @Property(QObject, constant=True)
    def sectionsModel(self) -> QObject:
        """Expose the section list model consumed by the sidebar and timeline."""
        return self._sections_model

    @Property(str, notify=sourceChanged)
    def sourcePath(self) -> str:
        """Return the currently opened source path for QML bindings."""
        return str(self._source_path) if self._source_path else ""

    @Property(str, notify=sourceChanged)
    def sourceName(self) -> str:
        """Return the current source filename for window and toolbar labels."""
        return self._source_path.name if self._source_path else ""

    @Property(str, notify=dialogDirectoriesChanged)
    def defaultOpenDirectoryUrl(self) -> str:
        """Return the initial folder used by the open-file dialog."""
        directory = self._dialog_state.last_open_directory or Path.home()
        return QUrl.fromLocalFile(str(directory)).toString()

    @Property(str, notify=dialogDirectoriesChanged)
    def defaultOutputDirectoryUrl(self) -> str:
        """Return the initial folder used by the export dialog."""
        directory = self._dialog_state.last_output_directory
        if directory is None and self._source_path is not None:
            directory = self._source_path.parent
        if directory is None:
            directory = Path.home()
        return QUrl.fromLocalFile(str(directory)).toString()

    @Property(bool, notify=sourceChanged)
    def hasSource(self) -> bool:
        """Return whether a source file is currently loaded."""
        return self._source_path is not None

    @Property(float, notify=durationChanged)
    def duration(self) -> float:
        """Return the current source duration in seconds."""
        return self._media_info.duration if self._media_info else 0.0

    @Property(float, notify=positionChanged)
    def position(self) -> float:
        """Return the last known playback position in seconds."""
        return self._position

    @Property(str, notify=positionChanged)
    def positionLabel(self) -> str:
        """Return the formatted playback position shown in the timeline UI."""
        return format_seconds(self._position)

    @Property(str, notify=durationChanged)
    def durationLabel(self) -> str:
        """Return the formatted source duration shown in the timeline UI."""
        return format_seconds(self.duration)

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        """Return whether preview playback is currently running."""
        return self._playing

    @Property(float, notify=markersChanged)
    def pendingStart(self) -> float:
        """Return the active start marker for creation or section editing."""
        section = self._selected_section()
        marker = section.start if section else self._pending_start
        return -1.0 if marker is None else marker

    @Property(float, notify=markersChanged)
    def pendingEnd(self) -> float:
        """Return the active end marker for creation or section editing."""
        section = self._selected_section()
        marker = section.end if section else self._pending_end
        return -1.0 if marker is None else marker

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        """Return whether exports should drop the audio stream."""
        return self._muted

    @Property(int, notify=selectedSectionChanged)
    def selectedSectionIndex(self) -> int:
        """Return the currently selected section row, or -1 when none is selected."""
        return self._selected_section_index

    @Property(bool, notify=selectedSectionChanged)
    def hasSelectedSection(self) -> bool:
        """Return whether a section is selected for editing."""
        return self._sections_model.section_at(self._selected_section_index) is not None

    @Property("QVariantMap", notify=selectedCropChanged)
    def selectedCrop(self) -> dict[str, float]:
        """Return the selected section crop in normalized coordinates."""
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
        """Return the source video width used for crop normalization."""
        return self._media_info.video_width if self._media_info else 0

    @Property(int, notify=mediaInfoChanged)
    def videoHeight(self) -> int:
        """Return the source video height used for crop normalization."""
        return self._media_info.video_height if self._media_info else 0

    @Property(bool, notify=renderingChanged)
    def rendering(self) -> bool:
        """Return whether an export batch is currently running."""
        return self._render_runner.running

    @Property(bool, notify=renderabilityChanged)
    def canRender(self) -> bool:
        """Return whether the current editor state is ready for export."""
        return (
            self.hasSource
            and self._sections_model.rowCount() > 0
            and not self._render_runner.running
        )

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        """Return the latest user-facing status message."""
        return self._status_text

    @property
    def player(self) -> mpv.MPV:
        """Expose the embedded mpv player to the custom QML video item."""
        return self._player

    def _set_status_text(self, text: str) -> None:
        """Store and broadcast a new status line when it changes."""
        if text == self._status_text:
            return
        self._status_text = text
        self._log.info("status: %s", text)
        self.statusTextChanged.emit()

    @Slot(bool)
    def _handle_render_state_change(self, _running: bool) -> None:
        """Forward render-runner state changes to QML-facing signals."""
        self.renderingChanged.emit()
        self.renderabilityChanged.emit()

    def _remember_open_directory(self, path: Path) -> None:
        """Persist the last directory used for opening source files."""
        directory = path if path.is_dir() else path.parent
        if directory == self._dialog_state.last_open_directory:
            return
        self._dialog_state.last_open_directory = directory
        self._directory_store.save(self._dialog_state)
        self.dialogDirectoriesChanged.emit()

    def _remember_output_directory(self, path: Path) -> None:
        """Persist the last directory used for rendering output."""
        directory = path if path.is_dir() else path.parent
        if directory == self._dialog_state.last_output_directory:
            return
        self._dialog_state.last_output_directory = directory
        self._directory_store.save(self._dialog_state)
        self.dialogDirectoriesChanged.emit()

    def _clear_pending_markers(self, *, emit_signal: bool = True) -> None:
        """Clear the temporary markers used while creating a new section."""
        if self._pending_start is None and self._pending_end is None:
            return
        self._pending_start = None
        self._pending_end = None
        if emit_signal:
            self.markersChanged.emit()

    def _load_player_source(self, start: float = 0.0, pause: bool = True) -> bool:
        """Load the current source into mpv, optionally seeking from the start."""
        if self._source_path is None:
            return False

        options = {"pause": "yes" if pause else "no"}
        if start > 0.0:
            options["start"] = f"{start:.3f}"

        try:
            self._player.loadfile(str(self._source_path), "replace", **options)
        except SystemError as error:
            self._log.exception(
                "failed to load source path=%s start=%.3f pause=%s",
                self._source_path,
                start,
                pause,
            )
            self._set_status_text(f"Playback failed: {error}")
            return False

        self._eof_reached = False
        self._preview_section_end = None
        self._position = start
        self.positionChanged.emit()
        return True

    def _selected_section(self) -> Section | None:
        """Return the currently selected section object, if any."""
        return self._sections_model.section_at(self._selected_section_index)

    def _replace_selected_section(self, **changes: Any) -> Section | None:
        """Apply dataclass-style field updates to the selected section."""
        section = self._selected_section()
        if section is None:
            return None

        updated_section = replace(section, **changes)
        self._sections_model.update_section(
            self._selected_section_index,
            updated_section,
        )
        return updated_section

    def _seek_to_position(
        self,
        seconds: float,
        *,
        clear_preview: bool,
        pause_on_reload: bool,
    ) -> bool:
        """Seek preview playback while handling mpv recovery details."""
        if not self.hasSource:
            return False

        target = clamp(seconds, 0.0, self.duration)
        self._eof_reached = False
        if clear_preview:
            self._preview_section_end = None

        try:
            self._player.seek(target, reference="absolute", precision="exact")
        except SystemError:
            self._log.exception("seek failed at %.3f, reloading current source", target)
            if not self._load_player_source(start=target, pause=pause_on_reload):
                return False

        self._position = target
        self.positionChanged.emit()
        return True

    def _stop_section_preview(self) -> None:
        """Stop bounded preview playback at the selected section end."""
        if self._preview_section_end is None:
            return

        preview_end = self._preview_section_end
        self._preview_section_end = None

        try:
            self._player.pause = True
        except SystemError:
            self._log.exception("failed to pause at preview boundary")

        self._seek_to_position(
            preview_end,
            clear_preview=False,
            pause_on_reload=True,
        )

    def _handle_mpv_log(
        self,
        level: str,
        prefix: str,
        message: str,
    ) -> None:
        """Forward mpv log messages into the app logger."""
        self._log.debug("mpv[%s][%s] %s", level, prefix, message.rstrip())

    def _reset_editor_state(self) -> None:
        """Clear per-file editing state after loading a new source."""
        self._sections_model.clear()
        self._pending_start = None
        self._pending_end = None
        self._selected_section_index = -1
        self._next_section_id = 1
        self._eof_reached = False
        self._preview_section_end = None
        self._position = 0.0
        self.markersChanged.emit()
        self.positionChanged.emit()
        self.selectedSectionChanged.emit()
        self.selectedCropChanged.emit()
        self.renderabilityChanged.emit()

    @Slot(float)
    def _apply_position_update(self, position: float) -> None:
        """Apply queued position updates from mpv on the Qt thread."""
        if (
            self._preview_section_end is not None
            and position >= self._preview_section_end - 0.01
        ):
            self._position = position
            self.positionChanged.emit()
            self._stop_section_preview()
            return

        if math.isclose(position, self._position, abs_tol=0.01):
            return
        self._position = position
        self.positionChanged.emit()

    @Slot(bool)
    def _apply_playing_update(self, playing: bool) -> None:
        """Apply queued play/pause updates from mpv on the Qt thread."""
        if playing == self._playing:
            return
        self._playing = playing
        self.playingChanged.emit()

    def _handle_time_position(self, _name: str, value: Any) -> None:
        """Queue mpv time updates onto the Qt thread."""
        position = 0.0 if value is None else float(value)
        QMetaObject.invokeMethod(
            self,
            "_apply_position_update",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, position),
        )

    def _handle_pause_state(self, _name: str, value: Any) -> None:
        """Queue mpv pause-state updates onto the Qt thread."""
        playing = not bool(value)
        QMetaObject.invokeMethod(
            self,
            "_apply_playing_update",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, playing),
        )

    @Slot(bool)
    def _apply_eof_update(self, reached: bool) -> None:
        """Apply end-of-file state changes from mpv on the Qt thread."""
        if reached == self._eof_reached:
            return
        self._eof_reached = reached
        if reached:
            self._preview_section_end = None
        if reached:
            self._apply_playing_update(False)

    def _handle_eof_reached(self, _name: str, value: Any) -> None:
        """Queue mpv EOF updates onto the Qt thread."""
        reached = bool(value)
        QMetaObject.invokeMethod(
            self,
            "_apply_eof_update",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, reached),
        )

    def _emit_selection_change(self) -> None:
        """Emit the small group of signals affected by section selection changes."""
        self.markersChanged.emit()
        self.selectedSectionChanged.emit()
        self.selectedCropChanged.emit()

    def _cancel_render(self, *, reason: str | None = None) -> None:
        """Stop the active export batch through the render runner."""
        self._render_runner.cancel(reason=reason)

    def _normalized_crop(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> CropRect:
        """Clamp a draft crop into valid normalized video coordinates."""
        if self.videoWidth <= 0 or self.videoHeight <= 0:
            return CropRect()

        min_width = 1.0 / self.videoWidth
        min_height = 1.0 / self.videoHeight
        x = clamp(x, 0.0, 1.0)
        y = clamp(y, 0.0, 1.0)
        width = clamp(width, min_width, 1.0 - x)
        height = clamp(height, min_height, 1.0 - y)
        return CropRect(x=x, y=y, width=width, height=height)

    @Slot(str)
    def openFile(self, file_url: str) -> None:
        """Load a new source file, probe it, and reset editor state."""
        path = _coerce_local_path(file_url)
        if path is None:
            return

        self._log.info("opening file %s", path)

        try:
            media_info = probe_media(path)
        except FileNotFoundError:
            self._set_status_text(
                "ffprobe was not found. Install ffmpeg to inspect videos.",
            )
            return
        except (subprocess.CalledProcessError, ValueError) as error:
            self._set_status_text(f"Unable to open video: {error}")
            return

        self._cancel_render(
            reason="Canceled the active render while loading a new file."
        )
        self._source_path = path
        self._media_info = media_info
        self._remember_open_directory(path)
        self._reset_editor_state()
        self.sourceChanged.emit()
        self.durationChanged.emit()
        self.mediaInfoChanged.emit()

        if self._load_player_source(pause=True):
            self._set_status_text(f"Loaded {path.name}")

    @Slot()
    def togglePlayback(self) -> None:
        """Toggle preview playback, restarting from EOF when needed."""
        if not self.hasSource:
            return

        if not self._playing and (
            self._eof_reached
            or math.isclose(self._position, self.duration, abs_tol=0.05)
        ):
            self._load_player_source(pause=False)
            return

        try:
            self._player.pause = self._playing
        except SystemError:
            self._log.exception("playback toggle failed, reloading current source")
            self._load_player_source(start=self._position, pause=self._playing)

    @Slot(float)
    def seekTo(self, seconds: float) -> None:
        """Seek preview playback to a position chosen in the timeline."""
        self._seek_to_position(
            seconds,
            clear_preview=True,
            pause_on_reload=not self._playing,
        )

    @Slot()
    def stepFrameForward(self) -> None:
        """Advance preview playback by one frame."""
        if not self.hasSource:
            return
        self._preview_section_end = None
        try:
            self._player.command("frame-step")
        except SystemError:
            self._log.exception("frame-step failed")

    @Slot()
    def stepFrameBackward(self) -> None:
        """Step preview playback backward by one frame."""
        if not self.hasSource:
            return
        self._preview_section_end = None
        try:
            self._player.command("frame-back-step")
        except SystemError:
            self._log.exception("frame-back-step failed")

    @Slot()
    def markStart(self) -> None:
        """Store the current position as the pending section start."""
        if not self.hasSource:
            return
        self._pending_start = self._position
        self.markersChanged.emit()

    @Slot()
    def markEnd(self) -> None:
        """Store the current position as the pending section end."""
        if not self.hasSource:
            return
        self._pending_end = self._position
        self.markersChanged.emit()

    @Slot()
    def clearMarkers(self) -> None:
        """Clear the pending markers used to create a new section."""
        self._clear_pending_markers()

    @Slot()
    def addSectionFromMarkers(self) -> None:
        """Create a new section from the pending start and end markers."""
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
        self._clear_pending_markers(emit_signal=False)
        self._selected_section_index = -1
        self._emit_selection_change()
        self.renderabilityChanged.emit()
        self._log.info(
            "added section id=%s start=%.3f end=%.3f",
            section.identifier,
            start,
            end,
        )
        self._set_status_text(
            "Added section "
            f"{format_seconds(start)} - {format_seconds(end)}. "
            "Select it in the list to adjust its crop.",
        )

    @Slot(int)
    def selectSection(self, index: int) -> None:
        """Select a section so its bounds and crop can be edited."""
        if index == self._selected_section_index:
            return
        if self._sections_model.section_at(index) is None:
            return
        self._clear_pending_markers(emit_signal=False)
        self._selected_section_index = index
        self._log.info("selected section index=%s", index)
        self._emit_selection_change()

    @Slot(int)
    def playSection(self, index: int) -> None:
        """Preview a section from its start and stop automatically at its end."""
        section = self._sections_model.section_at(index)
        if section is None:
            return

        if index != self._selected_section_index:
            self._clear_pending_markers(emit_signal=False)
            self._selected_section_index = index
            self._emit_selection_change()

        self._preview_section_end = section.end
        if not self._seek_to_position(
            section.start,
            clear_preview=False,
            pause_on_reload=False,
        ):
            self._preview_section_end = None
            return

        try:
            self._player.pause = False
        except SystemError:
            self._log.exception("failed to start section preview")
            self._preview_section_end = None
            self._load_player_source(start=section.start, pause=False)
            return

        self._set_status_text(
            "Previewing section "
            f"{section.identifier} "
            f"({format_seconds(section.start)} - {format_seconds(section.end)})"
        )

    @Slot(int)
    def removeSection(self, index: int) -> None:
        """Delete a section and keep selection state consistent."""
        if self._sections_model.section_at(index) is None:
            return
        self._log.info("removing section index=%s", index)
        self._sections_model.remove_section(index)
        if not self._sections_model.rowCount():
            self._selected_section_index = -1
        elif index <= self._selected_section_index:
            self._selected_section_index = max(0, self._selected_section_index - 1)
        self._emit_selection_change()
        self.renderabilityChanged.emit()

    @Slot()
    def clearSelectedSection(self) -> None:
        """Exit section edit mode without removing any data."""
        if self._selected_section_index < 0:
            return
        self._log.info(
            "cleared selected section index=%s", self._selected_section_index
        )
        self._selected_section_index = -1
        self._emit_selection_change()

    @Slot()
    def updateSelectedSectionStart(self) -> None:
        """Replace the selected section start with the current playhead position."""
        section = self._selected_section()
        if section is None:
            return
        new_start = self._position
        if new_start >= section.end:
            self._set_status_text("Start time must be before end time.")
            return
        self._replace_selected_section(start=new_start)
        self.markersChanged.emit()
        self._log.info(
            "updated section %s start to %.3f",
            section.identifier,
            new_start,
        )

    @Slot()
    def updateSelectedSectionEnd(self) -> None:
        """Replace the selected section end with the current playhead position."""
        section = self._selected_section()
        if section is None:
            return
        new_end = self._position
        if new_end <= section.start:
            self._set_status_text("End time must be after start time.")
            return
        self._replace_selected_section(end=new_end)
        self.markersChanged.emit()
        self._log.info(
            "updated section %s end to %.3f",
            section.identifier,
            new_end,
        )

    @Slot()
    def resetSelectedCrop(self) -> None:
        """Restore the selected section crop to the full frame."""
        section = self._selected_section()
        if section is None:
            return
        self._replace_selected_section(crop=CropRect())
        self.selectedCropChanged.emit()

    @Slot(float, float, float, float)
    def setSelectedCropNormalized(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        """Store a normalized crop drafted by the QML crop overlay."""
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
        self._replace_selected_section(crop=crop)
        self.selectedCropChanged.emit()

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        """Toggle whether future exports include audio."""
        if muted == self._muted:
            return
        self._muted = muted
        self._log.info("muted=%s", muted)
        self.mutedChanged.emit()

    @Slot(str)
    def renderTo(self, output_file_url: str) -> None:
        """Plan and start rendering all current sections to an output folder."""
        if not self.canRender or self._source_path is None or self._media_info is None:
            return

        output_directory = _coerce_local_path(output_file_url)
        if output_directory is None:
            return

        if output_directory.exists() and not output_directory.is_dir():
            self._set_status_text(
                "Choose a directory for the rendered sections.",
            )
            return

        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._set_status_text(f"Unable to create output directory: {error}")
            return

        sections = self._sections_model.sections()
        jobs = plan_render_jobs(
            self._source_path,
            self._media_info,
            sections,
            output_directory,
            muted=self._muted,
        )
        self._remember_output_directory(output_directory)
        self._render_runner.start(jobs, output_directory)

    @Slot()
    def shutdown(self) -> None:
        """Stop background work and tear down the embedded player on exit."""
        self._log.info("controller shutdown")
        self._render_runner.cancel()
        self._player.terminate()
