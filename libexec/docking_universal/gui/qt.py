"""Single Qt 6 binding used by the desktop and optional embedded viewer."""

from pathlib import Path
import os

# The combined PyMOL environment can retain a Qt 5 ``qt.conf`` from its native
# dependencies. Select the PyQt6 wheel's plugins before QApplication exists.
os.environ.setdefault("QT_API", "pyqt6")
for _key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
    os.environ.pop(_key, None)

import PyQt6

from PyQt6 import QtCore, QtGui, QtWidgets

_qt6_plugins = Path(PyQt6.__file__).parent / "Qt6" / "plugins"
if _qt6_plugins.is_dir() and QtCore.QCoreApplication.instance() is None:
    QtCore.QCoreApplication.setLibraryPaths([str(_qt6_plugins)])
if QtCore.QCoreApplication.instance() is None:
    # Detaching the embedded QOpenGLWidget into its own full-screen window must
    # preserve the live PyMOL context rather than creating another engine.
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True,
    )


# Keep the existing widget code readable during the binding migration. These
# names map only Qt 5's unscoped enum spelling onto the corresponding Qt 6 enum;
# they do not load or depend on PyQt5.
_ENUM_ALIASES = (
    (QtCore.Qt, "AlignCenter", QtCore.Qt.AlignmentFlag.AlignCenter),
    (QtCore.Qt, "AllDockWidgetAreas", QtCore.Qt.DockWidgetArea.AllDockWidgetAreas),
    (QtCore.Qt, "BottomDockWidgetArea", QtCore.Qt.DockWidgetArea.BottomDockWidgetArea),
    (QtCore.Qt, "KeepAspectRatio", QtCore.Qt.AspectRatioMode.KeepAspectRatio),
    (QtCore.Qt, "LeftDockWidgetArea", QtCore.Qt.DockWidgetArea.LeftDockWidgetArea),
    (QtCore.Qt, "RightDockWidgetArea", QtCore.Qt.DockWidgetArea.RightDockWidgetArea),
    (QtCore.Qt, "SmoothTransformation", QtCore.Qt.TransformationMode.SmoothTransformation),
    (QtCore.Qt, "UserRole", QtCore.Qt.ItemDataRole.UserRole),
    (QtCore.Qt, "Vertical", QtCore.Qt.Orientation.Vertical),
    (QtCore.QSettings, "IniFormat", QtCore.QSettings.Format.IniFormat),
    (QtGui.QImage, "Format_RGB32", QtGui.QImage.Format.Format_RGB32),
    (QtWidgets.QAbstractItemView, "ExtendedSelection", QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection),
    (QtWidgets.QAbstractItemView, "NoEditTriggers", QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers),
    (QtWidgets.QAbstractItemView, "SelectRows", QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows),
    (QtWidgets.QAbstractItemView, "SingleSelection", QtWidgets.QAbstractItemView.SelectionMode.SingleSelection),
    (QtWidgets.QDockWidget, "DockWidgetClosable", QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable),
    (QtWidgets.QDockWidget, "DockWidgetFloatable", QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable),
    (QtWidgets.QDockWidget, "DockWidgetMovable", QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable),
    (QtWidgets.QFrame, "StyledPanel", QtWidgets.QFrame.Shape.StyledPanel),
    (QtWidgets.QMessageBox, "DestructiveRole", QtWidgets.QMessageBox.ButtonRole.DestructiveRole),
    (QtWidgets.QMessageBox, "RejectRole", QtWidgets.QMessageBox.ButtonRole.RejectRole),
    (QtWidgets.QMessageBox, "Warning", QtWidgets.QMessageBox.Icon.Warning),
)
for _owner, _name, _value in _ENUM_ALIASES:
    if not hasattr(_owner, _name):
        setattr(_owner, _name, _value)

__all__ = ["QtCore", "QtGui", "QtWidgets"]
