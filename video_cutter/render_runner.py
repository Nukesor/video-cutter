"""Runtime ffmpeg orchestration for queued section exports."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .debug import get_logger
from .rendering import RenderJob


class RenderRunner(QObject):
    """Own the ffmpeg process and run planned render jobs sequentially."""

    runningChanged = Signal(bool)
    statusMessage = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the render queue state and wire up the process signals."""
        super().__init__(parent)
        self._log = get_logger("video_cutter.render_runner")
        self._running = False
        self._output = ""
        self._output_directory: Path | None = None
        self._queue: list[RenderJob] = []
        self._current_job: RenderJob | None = None
        self._completed_count = 0
        self._cancelled = False

        self._process = QProcess(self)
        self._process.setProgram("ffmpeg")
        self._process.readyReadStandardError.connect(self._consume_output)
        self._process.readyReadStandardOutput.connect(self._consume_output)
        self._process.finished.connect(self._handle_finished)
        self._process.errorOccurred.connect(self._handle_error)

    @property
    def running(self) -> bool:
        """Return whether a render is active or queued."""
        return self._running

    def start(self, jobs: list[RenderJob], output_directory: Path) -> None:
        """Replace any active work and begin rendering a new job queue."""
        if not jobs:
            return

        self.cancel()
        self._queue = list(jobs)
        self._output_directory = output_directory
        self._current_job = None
        self._completed_count = 0
        self._cancelled = False
        self._set_running(True)
        self._start_next_render()

    def cancel(self, *, reason: str | None = None) -> None:
        """Stop the active render and clear any queued jobs."""
        if not self._running and not self._queue and self._current_job is None:
            return

        self._log.info("cancelling active render")
        self._cancelled = True
        self._queue.clear()
        self._current_job = None
        self._output = ""
        self._output_directory = None
        self._completed_count = 0
        self._set_running(False)

        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(1000)

        if reason is not None:
            self.statusMessage.emit(reason)

    def _set_running(self, running: bool) -> None:
        """Update the running flag and notify observers when it changes."""
        if running == self._running:
            return
        self._running = running
        self.runningChanged.emit(running)

    def _consume_output(self) -> None:
        """Collect ffmpeg output and surface the latest line as status text."""
        stderr = bytes(self._process.readAllStandardError()).decode(
            "utf-8",
            errors="replace",
        )
        stdout = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8",
            errors="replace",
        )
        combined = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
        if not combined:
            return

        self._output = f"{self._output}\n{combined}".strip()
        last_line = self._output.splitlines()[-1]
        if last_line:
            self._log.info("ffmpeg: %s", last_line)
            self.statusMessage.emit(last_line)

    def _handle_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        """Advance the queue after a process exit or report the failure."""
        if self._cancelled:
            self._cancelled = False
            return

        self._consume_output()
        self._log.info(
            "render finished exit_code=%s exit_status=%s",
            exit_code,
            exit_status,
        )

        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._completed_count += 1
            self._start_next_render()
            return

        details = self._output.splitlines()[-1] if self._output else "ffmpeg failed"
        self._set_running(False)
        self._queue.clear()
        self._current_job = None
        self.statusMessage.emit(f"Render failed: {details}")

    def _handle_error(self, process_error: QProcess.ProcessError) -> None:
        """Translate process-level startup and runtime errors into status text."""
        if self._cancelled:
            self._cancelled = False
            return

        self._set_running(False)
        self._queue.clear()
        self._current_job = None
        self._log.error("render process error: %s", int(process_error))
        if process_error == QProcess.ProcessError.FailedToStart:
            self.statusMessage.emit(
                "ffmpeg was not found. Install ffmpeg and try again."
            )
            return
        self.statusMessage.emit("ffmpeg process error interrupted rendering.")

    def _start_next_render(self) -> None:
        """Launch the next queued job or finish the batch cleanly."""
        if not self._queue:
            self._current_job = None
            self._set_running(False)
            if self._output_directory is not None:
                count = self._completed_count
                noun = "section" if count == 1 else "sections"
                self.statusMessage.emit(
                    f"Rendered {count} {noun} to {self._output_directory}"
                )
            return

        self._output = ""
        self._current_job = self._queue.pop(0)
        job = self._current_job
        section = job.section
        render_index = self._completed_count + 1
        total = self._completed_count + 1 + len(self._queue)
        self.statusMessage.emit(
            f"Rendering section {section.identifier} ({render_index}/{total})..."
        )

        self._log.info("starting ffmpeg with args: %s", job.arguments)
        self._process.setArguments(job.arguments)
        self._process.start()
