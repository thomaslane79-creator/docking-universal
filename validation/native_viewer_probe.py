"""Real native Qt6/OpenGL, full PyMOL detach/return and image export gate.

Synthetic built-in fragments only. Images and logs remain local; summary.json
contains fixed check names, runtime/driver identity and code locations only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--opengl-dll', type=Path, help='Explicit isolated Windows software-graphics probe only')
    args = parser.parse_args()
    out, source = args.out.resolve(), args.app.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(source))
    status = {'status': 'running', 'system': platform.platform(), 'checks': [],
              'consumer_gpu_accepted': False, 'installed_desktop_accepted': False}
    application = window = widget = adapter = detached = None

    def save():
        (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n', encoding='utf-8')

    def check(name, value):
        status['checks'].append({'name': name, 'passed': bool(value)}); save()
        if not value:
            raise AssertionError(name)

    def phase(name):
        status['phase'] = name; save()

    try:
        if args.opengl_dll:
            if platform.system() != 'Windows':
                raise ValueError('Explicit DLL probe requires Windows')
            import ctypes
            dll = args.opengl_dll.resolve(strict=True)
            # Keep both handles alive. This affects only this candidate process,
            # never system DLLs, drivers, PATH registration or the installed app.
            dll_directory = os.add_dll_directory(str(dll.parent))
            graphics_library = ctypes.WinDLL(str(dll))
            os.environ.update(QT_OPENGL='desktop', QT_OPENGL_DLL=str(dll), GALLIUM_DRIVER='llvmpipe', LIBGL_ALWAYS_SOFTWARE='1')
            status['explicit_software_graphics'] = True
        phase('importing_runtime')
        from docking_universal.gui.qt import QtCore, QtWidgets
        from PyQt6.QtTest import QTest
        from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
        from docking_universal.viewer.full_pymol import create_full_pymol_window
        import docking_universal
        import pymol
        import pymol._cmd
        check('application imported from isolated copied code', Path(docking_universal.__file__).resolve().is_relative_to(source))
        check('PyMOL extension belongs to candidate prefix', Path(pymol._cmd.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()))
        status.update(python=sys.version.split()[0], qt=QtCore.QT_VERSION_STR)
        for scope in (QtCore.QSettings.Scope.UserScope, QtCore.QSettings.Scope.SystemScope):
            QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, scope, str(out / 'settings'))
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        phase('creating_qt_application')
        application = QtWidgets.QApplication([])
        application.setQuitOnLastWindowClosed(False)
        if platform.system() == 'Windows':
            from PyQt6 import QtGui
            import ctypes
            phase('checking_opengl_context')
            context, surface = QtGui.QOpenGLContext(), QtGui.QOffscreenSurface()
            surface.create()
            created = context.create()
            current = created and context.makeCurrent(surface)
            status['context'] = {'created': bool(created), 'made_current': bool(current),
                'format_version': [context.format().majorVersion(), context.format().minorVersion()]}
            if current:
                address = context.getProcAddress(b'glGetString')
                if address:
                    get_string = ctypes.WINFUNCTYPE(ctypes.c_char_p, ctypes.c_uint)(int(address))
                    status['context']['graphics'] = {name: (get_string(code) or b'').decode('ascii', errors='replace')
                        for name, code in (('vendor', 0x1F00), ('renderer', 0x1F01), ('version', 0x1F02))}
                context.doneCurrent()
            check('native OpenGL context usable', current and tuple(status['context']['format_version']) >= (2, 0))
            surface.destroy()
        phase('creating_pymol_widget')
        window = QtWidgets.QMainWindow()
        widget = create_embedded_pymol_widget()
        window.setCentralWidget(widget); window.resize(900, 700); window.show()
        adapter = EmbeddedPymolAdapter(widget)
        QTest.qWait(800)
        phase('launching_engine')
        adapter.launch()
        cmd = adapter.cmd
        cmd.fragment('trp', 'example')
        cmd.hide('everything'); cmd.show('sticks', 'example')
        cmd.show('surface', 'example'); cmd.set('transparency', .5, 'example')
        cmd.color('skyblue', 'example and elem C')
        cmd.label('example and name CA', '"TRP1"'); cmd.set('label_size', 18)
        adapter.show_box([0, 0, 0], [14, 14, 14])
        cmd.orient('example'); cmd.rotate('y', 25)
        QTest.qWait(600)
        check('native embedded engine alive', adapter.is_alive())
        check('synthetic fragment loaded', cmd.count_atoms('example') > 10)
        check('surface and CGO box available', 'du_box' in cmd.get_names('objects'))
        status['graphics'] = dict(zip(('vendor', 'renderer', 'version'), cmd.get_renderer()))
        phase('reading_framebuffer')
        frame = widget.grabFramebuffer()
        check('real OpenGL framebuffer available', not frame.isNull() and frame.width() > 100)
        pixels = {frame.pixelColor(x, y).rgba() for x in range(0, frame.width(), 7)
                  for y in range(0, frame.height(), 7)}
        check('framebuffer contains rendered colors', len(pixels) > 20)
        frame.save(str(out / 'embedded.local.png'))
        camera, engine = tuple(cmd.get_view())[:9], widget.pymol

        def restore():
            window.setCentralWidget(widget); widget.show()

        window.takeCentralWidget()
        phase('detaching_full_pymol')
        detached = create_full_pymol_window(widget, window, restore)
        detached.show(); QTest.qWait(500)
        check('full PyMOL retains the same engine', widget.pymol is engine)
        check('full command area exists', hasattr(detached, 'ext_window'))
        detached.close(); QTest.qWait(400); detached = None
        check('viewport returned to workspace', window.centralWidget() is widget)
        check('camera rotation preserved', max(abs(a-b) for a, b in zip(camera, cmd.get_view()[:9])) < 1e-5)
        check('engine alive after return', adapter.is_alive())
        phase('exporting_ray_image')
        cmd.png(str(out / 'ray.local.png'), width=640, height=480, ray=1, quiet=1)
        check('ray export succeeds', (out / 'ray.local.png').stat().st_size > 1000)
        check('Qt5 Python bindings not loaded', not any(name.split('.')[0] in {'PyQt5', 'PySide2'} for name in sys.modules))
        if platform.system() == 'Windows':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel.GetModuleHandleW.restype = ctypes.c_void_p
            check('Qt5 native DLL not loaded', not kernel.GetModuleHandleW('Qt5Core.dll'))
            check('Qt6 native DLL loaded', bool(kernel.GetModuleHandleW('Qt6Core.dll')))
        status.update(status='passed', phase='completed')
    except BaseException as exc:
        status.update(status='failed', error_type=type(exc).__name__,
                      code_locations=[{'file': Path(f.filename).name, 'function': f.name, 'line': f.lineno}
                                      for f in traceback.extract_tb(exc.__traceback__)[-4:]])
        with (out / 'error.local.log').open('w', encoding='utf-8') as stream:
            traceback.print_exc(file=stream)
    finally:
        try:
            if detached is not None:
                detached.close()
            if adapter is not None:
                adapter.close()
            if window is not None:
                window.close()
            if application is not None:
                application.processEvents()
        except BaseException as exc:
            status.update(status='failed', cleanup_error_type=type(exc).__name__)
        save()
    return 0 if status['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
