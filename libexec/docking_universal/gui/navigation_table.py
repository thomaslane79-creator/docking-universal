"""Candidate navigation without moving text that is already on screen."""

from .qt import QtWidgets


class NavigationTable(QtWidgets.QTableWidget):
    def scrollTo(self, index, hint=QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible):
        # Qt also invokes this on selection/focus changes. A partially visible
        # cell can already be clicked; ensuring its entire row/column is visible
        # shifts the list under the pointer, especially with clipped long text.
        if (hint == QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible
                and self.visualRect(index).intersects(self.viewport().rect())):
            return
        super().scrollTo(index, hint)
