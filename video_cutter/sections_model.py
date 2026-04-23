"""Qt list model for exposing sections to QML views and overlays."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QObject, Qt

from .models import Section, format_seconds


class SectionsModel(QAbstractListModel):
    """QAbstractListModel wrapper around the in-memory section list."""

    IdentifierRole = Qt.ItemDataRole.UserRole + 1
    StartRole = Qt.ItemDataRole.UserRole + 2
    EndRole = Qt.ItemDataRole.UserRole + 3
    DurationRole = Qt.ItemDataRole.UserRole + 4
    LabelRole = Qt.ItemDataRole.UserRole + 5
    CropSummaryRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize an empty model owned by the controller."""
        super().__init__(parent)
        self._sections: list[Section] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of top-level section rows."""
        if parent.isValid():
            return 0
        return len(self._sections)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Expose section fields and derived labels to QML delegates."""
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
            return f"{format_seconds(section.start)} - {format_seconds(section.end)}"
        if role == self.CropSummaryRole:
            crop = section.crop
            return (
                f"Crop {crop.width * 100:.0f}% x {crop.height * 100:.0f}%"
                f" at {crop.x * 100:.0f}%, {crop.y * 100:.0f}%"
            )
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        """Declare the custom role names consumed by QML."""
        return {
            self.IdentifierRole: QByteArray(b"identifier"),
            self.StartRole: QByteArray(b"start"),
            self.EndRole: QByteArray(b"end"),
            self.DurationRole: QByteArray(b"duration"),
            self.LabelRole: QByteArray(b"label"),
            self.CropSummaryRole: QByteArray(b"cropSummary"),
        }

    def section_at(self, index: int) -> Section | None:
        """Return the section for a row index when it exists."""
        if 0 <= index < len(self._sections):
            return self._sections[index]
        return None

    def add_section(self, section: Section) -> None:
        """Append a section and notify Qt about the inserted row."""
        insert_row = len(self._sections)
        self.beginInsertRows(QModelIndex(), insert_row, insert_row)
        self._sections.append(section)
        self.endInsertRows()

    def update_section(self, index: int, section: Section) -> None:
        """Replace one section and emit a data-changed notification."""
        if not 0 <= index < len(self._sections):
            return
        self._sections[index] = section
        model_index = self.index(index)
        self.dataChanged.emit(model_index, model_index)

    def remove_section(self, index: int) -> None:
        """Remove one section and notify Qt about the row removal."""
        if not 0 <= index < len(self._sections):
            return
        self.beginRemoveRows(QModelIndex(), index, index)
        del self._sections[index]
        self.endRemoveRows()

    def clear(self) -> None:
        """Reset the model after loading a new source file."""
        if not self._sections:
            return
        self.beginResetModel()
        self._sections.clear()
        self.endResetModel()

    def sections(self) -> list[Section]:
        """Return a copy of the current section list for non-Qt code."""
        return list(self._sections)
