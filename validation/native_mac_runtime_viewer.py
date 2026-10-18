"""Real Qt/OpenGL and full-PyMOL detach check, using only a fresh runtime.

Uses an upstream built-in amino-acid fragment, not a user's receptor or study.
"""
import argparse
import ctypes
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.runtime.resolve()))
    from docking_universal.gui.qt import QtCore, QtWidgets
    from PyQt6.QtTest import QTest
    from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
    from docking_universal.viewer.full_pymol import create_full_pymol_window
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    for scope in (QtCore.QSettings.Scope.UserScope, QtCore.QSettings.Scope.SystemScope):
        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, scope, str(args.out / 'qt-settings'))
    app = QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    widget = create_embedded_pymol_widget()
    window.setCentralWidget(widget)
    window.setWindowTitle('Fresh-install embedded PyMOL acceptance')
    window.resize(900, 700)
    adapter = EmbeddedPymolAdapter(widget)
    record = {'status': 'running', 'python': sys.executable, 'checks': []}

    def check(name, value):
        record['checks'].append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)

    def exercise():
        detached = None
        try:
            adapter.launch()
            cmd = adapter.cmd
            cmd.fragment('trp', 'example')
            cmd.hide('everything')
            cmd.show('sticks', 'example')
            cmd.show('surface', 'example')
            cmd.set('transparency', .5, 'example')
            cmd.color('skyblue', 'example and elem C')
            cmd.label('name CA', '"TRP1"')
            cmd.set('label_size', 18)
            cmd.zoom('example', 3)
            adapter.show_box([0, 0, 0], [14, 14, 14])
            cmd.orient('example')
            cmd.rotate('y', 25)
            QTest.qWait(500)
            check('embedded native engine alive', adapter.is_alive())
            check('fragment loaded', cmd.count_atoms('example') > 10)
            check('surface and CGO box loaded', 'du_box' in cmd.get_names('objects'))
            frame = widget.grabFramebuffer()
            check('real OpenGL framebuffer', not frame.isNull() and frame.width() > 100)
            pixels = {frame.pixelColor(x, y).rgba() for x in range(0, frame.width(), 7)
                      for y in range(0, frame.height(), 7)}
            check('framebuffer contains rendered colors', len(pixels) > 20)
            frame.save(str(args.out / 'embedded.png'))
            before = tuple(cmd.get_view())[:9]
            engine = widget.pymol

            def restore():
                window.setCentralWidget(widget)
                widget.show()

            window.takeCentralWidget()
            detached = create_full_pymol_window(widget, window, restore)
            detached.show()
            QTest.qWait(400)
            check('full PyMOL reuses same live engine', widget.pymol is engine)
            check('full PyMOL command input present', hasattr(detached, 'ext_window'))
            detached.grab().save(str(args.out / 'full-pymol.png'))
            detached.close()
            QTest.qWait(300)
            detached = None
            check('viewport returned to workspace', window.centralWidget() is widget)
            check('camera orientation preserved', max(abs(a-b) for a, b in zip(before, cmd.get_view()[:9])) < 1e-5)
            check('engine still alive after return', adapter.is_alive())
            cmd.png(str(args.out / 'ray.png'), width=640, height=480, ray=1, quiet=1)
            check('ray export works', (args.out / 'ray.png').stat().st_size > 1000)
            import pymol._cmd
            check('PyMOL extension loaded from fresh GUI prefix',
                  Path(pymol._cmd.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()))
            dyld = ctypes.CDLL(None)
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            libraries = [dyld._dyld_get_image_name(i).decode() for i in range(dyld._dyld_image_count())]
            record['loaded_relevant_libraries'] = [p for p in libraries if any(
                term in p.lower() for term in ('glew', 'freetype', 'libpng', 'qtcore', 'qtwidgets', 'libc++', '_cmd.'))]
            check('no old prototype or working Conda libraries', not any(
                '/opt/anaconda3' in p or 'embedded-pymol-poc' in p for p in libraries))
            check('no Qt5 framework loaded', not any('/Qt5' in p or '/qt5' in p.lower() for p in libraries))
            check('GLEW loaded from fresh GUI prefix', any('libGLEW' in p and str(Path(sys.prefix)) in p for p in libraries))
            record['status'] = 'passed'
        except BaseException as exc:
            record.update(status='failed', error=str(exc))
        finally:
            if detached is not None:
                detached.close()
            adapter.close()
            window.close()
            (args.out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
            app.exit(0 if record['status'] == 'passed' else 1)
    window.show()
    QtCore.QTimer.singleShot(600, exercise)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
