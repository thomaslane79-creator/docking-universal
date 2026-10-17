"""Reuse the upstream full Qt interface around the one existing PyMOL engine.

The upstream constructor has no widget-injection argument. Its widget factory
is replaced only during construction on the GUI thread, then restored in a
finally block. Never call pmg_qt.run(), PyMOL.start(), or launch another process.
"""
from ..gui.qt import QtCore, QtWidgets
from .scene_style import expand_scene_clipping


def create_full_pymol_window(widget, parent, restore):
    from pmg_qt import pymol_qt_gui as upstream
    from pmg_qt.pymol_gl_widget import PyMOLGLWidget
    import pymol
    import pymol.gui
    from pymol import controlling

    if not isinstance(widget, PyMOLGLWidget):
        raise RuntimeError("Full PyMOL requires the genuine embedded PyMOL widget")
    if QtCore.QThread.currentThread() != QtWidgets.QApplication.instance().thread():
        raise RuntimeError("Full PyMOL must be opened on the Qt GUI thread")
    cmd = widget.cmd
    original_gui = widget.gui
    original_factory = upstream.PyMOLGLWidget
    original_quit = cmd._quit
    original_legacy_factory = pymol.gui.createlegacypmgapp
    original_legacy_gui = pymol._ext_gui
    original_window = getattr(upstream, "window", None)
    settings = {name: cmd.get_setting_int(name) for name in
                ("internal_gui", "internal_feedback", "seq_view", "button_mode", "mouse_selection_mode")}
    original_mouse_ring = list(controlling.mouse_ring)
    original_wizard = cmd.get_wizard()
    camera = cmd.get_view()

    class FullPyMOLWindow(upstream.PyMOLQtGUI):
        returnRequested = QtCore.pyqtSignal()

        def __init__(self):
            self._returned = False
            super().__init__()
            self.returnRequested.connect(self.close)

        def confirm_quit(self):
            self.close()

        def showEvent(self, event):
            super().showEvent(event)
            if not getattr(self, '_initial_console_sized', False):
                self._initial_console_sized = True
                # macOS maximization finishes after the initial Qt show/layout.
                # Size once afterward; never override later user dock resizing.
                QtCore.QTimer.singleShot(100, self.compact_command_area)

        def compact_command_area(self):
            # Keep the console and every upstream quick control available, but
            # start at their minimum usable height rather than ext_y's large
            # preferred height. The user can still drag the dock taller.
            contents = self.ext_window.widget()
            contents._size_hint = QtCore.QSize(1100, contents.minimumSizeHint().height())
            self.resizeDocks([self.ext_window],
                [contents.minimumSizeHint().height()], QtCore.Qt.Orientation.Vertical)

        def update_progress(self):
            super().update_progress()
            # Do not conceal upstream Abort during a native PyMOL calculation.
            if hasattr(self, 'quick_controls_toggle') and not self.abortbutton.isHidden():
                self.quick_controls_toggle.setChecked(True)

        def new_window(self, extra_argv=()):
            # This application owns one live engine. File > New Window cannot
            # quietly recreate the duplicate/orphan viewer failure.
            QtWidgets.QMessageBox.information(self, "One live PyMOL session",
                "This window is the live Docking Universal session. Use File → Open to load additional structures here.")

        def closeEvent(self, event):
            if not self._returned:
                self._returned = True
                self.feedback_timer.stop()
                self.pymolwidget.removeEventFilter(self)
                self.takeCentralWidget()
                cmd._quit = original_quit
                pymol.gui.createlegacypmgapp = original_legacy_factory
                pymol._ext_gui = original_legacy_gui
                if original_window is None:
                    upstream.__dict__.pop("window", None)
                else:
                    upstream.window = original_window
                widget.gui = original_gui
                widget._du_full_interface = False
                widget.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.PreventContextMenu)
                for name, value in settings.items():
                    cmd.set(name, value)
                controlling.mouse_ring = original_mouse_ring
                cmd.mouse()
                cmd.button("single_left", "none", "pk1")
                cmd.set_wizard(original_wizard)
                restore()
            event.accept()
            self.deleteLater()

    def reuse_existing(host):
        hosts.append(host)
        widget.gui = host
        return widget

    window = None
    hosts = []
    try:
        upstream.PyMOLGLWidget = reuse_existing
        window = FullPyMOLWindow()
        window.setParent(parent, QtCore.Qt.WindowType.Window)
        window.menuBar().setNativeMenuBar(False)
        window.setWindowTitle("Docking Universal — Full PyMOL")
        window.resize(1100, 800)
        pymol.gui.createlegacypmgapp = window.createlegacypmgapp
        pymol._ext_gui = None
        upstream.window = window
        window.ext_window.show()
        # The five rows of native shortcut buttons dictate the console's
        # minimum height. Collapse those shortcuts, not the command line or
        # menus; keep them one click away in the same upstream layout.
        contents = window.ext_window.widget()
        external_layout = contents.layout()
        shortcuts = external_layout.takeAt(1).layout()
        shortcut_container = QtWidgets.QWidget(contents)
        shortcut_container.setLayout(shortcuts)
        external_layout.addWidget(shortcut_container)
        window.quick_controls_toggle = QtWidgets.QToolButton(contents)
        window.quick_controls_toggle.setText('Controls')
        window.quick_controls_toggle.setCheckable(True)
        window.quick_controls_toggle.setToolTip('Show or hide native PyMOL shortcut buttons. Menus and command input stay available.')
        command_layout = external_layout.itemAt(0).layout().itemAt(1).layout()
        command_layout.addWidget(window.quick_controls_toggle)
        shortcut_container.hide()
        window.quick_controls_toggle.toggled.connect(shortcut_container.setVisible)
        window.quick_controls_toggle.toggled.connect(lambda _checked: window.compact_command_area())
        window.browser.setMinimumHeight(window.browser.fontMetrics().lineSpacing()
                                      + 2 * window.browser.frameWidth()
                                      + int(2 * window.browser.document().documentMargin()))
        window.browser.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                     QtWidgets.QSizePolicy.Policy.Ignored)
        window.compact_command_area()
        QtCore.QTimer.singleShot(0, window.compact_command_area)
        window.statusBar().showMessage("Live exploratory view — changes do not approve or alter the docking protocol.")
        action = window.menuBar().addAction("Return to Docking Universal")
        action.triggered.connect(window.close)
        widget._du_full_interface = True
        widget.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.DefaultContextMenu)
        cmd.set("internal_gui", 1)
        cmd.set("internal_feedback", 0)
        # Menu, console, and object-popup Quit all return the viewport safely.
        cmd._quit = lambda *_args, **_kwargs: window.returnRequested.emit()
        cmd.set_view(camera)
        bounds = getattr(widget, '_du_box_bounds', None) if 'du_box' in cmd.get_names('objects', enabled_only=1) else None
        expand_scene_clipping(cmd, bounds)
        return window
    except Exception:
        cmd._quit = original_quit
        pymol.gui.createlegacypmgapp = original_legacy_factory
        pymol._ext_gui = original_legacy_gui
        if original_window is None:
            upstream.__dict__.pop("window", None)
        else:
            upstream.window = original_window
        widget.gui = original_gui
        widget._du_full_interface = False
        for name, value in settings.items():
            cmd.set(name, value)
        failed = window or (hosts[0] if hosts else None)
        if failed is not None:
            if hasattr(failed, "feedback_timer"):
                failed.feedback_timer.stop()
            failed.takeCentralWidget()
            widget.removeEventFilter(failed)
            failed.deleteLater()
        restore()
        raise
    finally:
        upstream.PyMOLGLWidget = original_factory
