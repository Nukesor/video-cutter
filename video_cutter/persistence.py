"""Persistence for file dialog directories between app launches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .debug import get_logger


@dataclass(slots=True)
class DialogDirectoryState:
    """Last-used directories for opening sources and exporting renders."""

    last_open_directory: Path | None = None
    last_output_directory: Path | None = None


class DialogDirectoryStore:
    """Load and save dialog directory state in the local state directory."""

    def __init__(self, path: Path) -> None:
        """Remember where the JSON state file is stored."""
        self._log = get_logger("video_cutter.persistence")
        self._path = path

    def load(self) -> DialogDirectoryState:
        """Read persisted dialog directories, ignoring invalid or missing state."""
        if not self._path.exists():
            return DialogDirectoryState()

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._log.exception("failed to load state from %s", self._path)
            return DialogDirectoryState()

        return DialogDirectoryState(
            last_open_directory=self._coerce_directory_path(
                payload.get("last_open_directory"),
            ),
            last_output_directory=self._coerce_directory_path(
                payload.get("last_output_directory"),
            ),
        )

    def save(self, state: DialogDirectoryState) -> None:
        """Persist the current dialog directories for the next launch."""
        payload = {
            "last_open_directory": (
                str(state.last_open_directory) if state.last_open_directory else None
            ),
            "last_output_directory": (
                str(state.last_output_directory)
                if state.last_output_directory
                else None
            ),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            self._log.exception("failed to save state to %s", self._path)

    def _coerce_directory_path(self, value: Any) -> Path | None:
        """Accept only existing directories from persisted JSON values."""
        if not isinstance(value, str) or not value:
            return None
        path = Path(value).expanduser()
        if path.exists() and path.is_dir():
            return path
        return None
