"""Presentation lifecycle controller for the top-level study workspace."""

from __future__ import annotations

from .qt import QtCore


class WorkspaceWindowController(QtCore.QObject):
    """Own window layout and polling; never own or mutate scientific state."""

    # Version 6 replaces visibility-swapped stage docks with persistent stacked
    # shells.  Restoring a version-5 dock graph can hide the shell and make the
    # workflow navigator appear inert, so those layouts must not be replayed.
    LAYOUT_VERSION = 6

    def __init__(self, window, settings, refresh_callback, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.settings = settings
        self.refresh_callback = refresh_callback
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)

    def restore_layout(self) -> None:
        geometry = self.settings.value("window/geometry")
        layout = self.settings.value("window/layout")
        if geometry is not None:
            self.window.restoreGeometry(geometry)
        saved_version = self.settings.value("window/layout_version", 0, type=int)
        if layout is not None and saved_version == self.LAYOUT_VERSION:
            self.window.restoreState(layout)

    def save_layout(self) -> None:
        self.settings.setValue("window/geometry", self.window.saveGeometry())
        self.settings.setValue("window/layout", self.window.saveState())
        self.settings.setValue("window/layout_version", self.LAYOUT_VERSION)

    def shown(self) -> None:
        self.timer.start()

    def poll(self) -> None:
        if self.window.isVisible():
            self.refresh_callback()
        else:
            self.timer.stop()

    def closed(self) -> None:
        self.timer.stop()
