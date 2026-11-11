"""Approved, package-local Docking Universal branding assets."""

from __future__ import annotations

from pathlib import Path
import sys


_BRANDING_ROOT = Path(__file__).resolve().parent / "assets" / "branding"


def application_icon_path() -> Path:
    """Return the flat simplified full-color application icon."""

    return _BRANDING_ROOT / "docking-universal-app-icon-white.png"


def render_white_icon():
    """Place the approved, unchanged logo over a pure-white rounded tile."""
    from .qt import QtCore, QtGui
    source = QtGui.QPixmap(str(_BRANDING_ROOT / 'docking-universal-app-icon.png'))
    if source.isNull():
        raise ValueError('The approved Docking Universal logo is missing')
    result = QtGui.QPixmap(512, 512)
    result.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(result)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    # Native icons reserve transparent space around the rounded tile.
    painter.translate(48, 48)
    painter.scale(416 / 512, 416 / 512)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor('#ffffff'))
    painter.drawRoundedRect(QtCore.QRectF(0, 0, 512, 512), 90, 90)
    # Enlarge the transparent logo slightly so the white frame stays subtle.
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(QtCore.QRectF(-30, -30, 572, 572), source, QtCore.QRectF(source.rect()))
    painter.end()
    return result


def write_desktop_icons(directory: Path) -> None:
    """Build packaged PNG and multi-size Windows ICO from the approved mark."""
    import struct
    from .qt import QtCore
    icon = render_white_icon()
    directory = Path(directory)
    if not icon.save(str(directory / 'docking-universal-app-icon-white.png'), 'PNG'):
        raise OSError('Could not write the desktop icon')
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        scaled = icon.scaled(size, size, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if not scaled.save(buffer, 'PNG'):
            raise OSError('Could not encode a Windows icon size')
        buffer.close()
        images.append((size, bytes(data)))
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        dimension = size if size < 256 else 0
        entries.append(struct.pack('<BBBBHHII', dimension, dimension, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (directory / 'docking-universal-app-icon.ico').write_bytes(
        struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries) + b''.join(data for _, data in images))


def application_version() -> str:
    """Read the version shipped with the app or its source checkout."""
    for path in (Path(__file__).resolve().parents[2] / 'VERSION',
                 Path(__file__).resolve().parents[3] / 'VERSION'):
        if path.is_file():
            return path.read_text(encoding='utf-8').strip()
    return 'Unavailable'


def about_dialog(parent=None):
    """Create the same compact About window for the chooser and study."""
    from .qt import QtCore, QtGui, QtWidgets
    dialog = QtWidgets.QMessageBox(parent)
    dialog.setObjectName('about_docking_universal')
    dialog.setWindowTitle('About Docking Universal')
    dialog.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    dialog.setText('Docking Universal\nVersion ' + application_version())
    dialog.setInformativeText(
        'A scientific decision-support application for preparing receptor structures, '
        'reviewing docking regions, and screening compounds. '
        'It keeps the evidence and choices behind each study available for review.'
    )
    icon = QtGui.QPixmap(str(application_icon_path()))
    if not icon.isNull():
        dialog.setIconPixmap(icon.scaled(112, 112, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                          QtCore.Qt.TransformationMode.SmoothTransformation))
    dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
    return dialog


def show_about(parent=None) -> None:
    about_dialog(parent).exec()


def hide_macos_services() -> bool:
    """Hide this app's unused macOS Services item, without changing system settings.

    Qt creates the native application menu itself. Identify the Services item
    by its actual NSApplication submenu, rather than by localized menu text.
    """
    if sys.platform != 'darwin':
        return False
    import ctypes
    try:
        objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        count = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(address)
        at = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(address)
        set_hidden = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(address)
        sel = lambda name: objc.sel_registerName(name.encode('ascii'))
        app = get(objc.objc_getClass(b'NSApplication'), sel('sharedApplication'))
        services = get(app, sel('servicesMenu'))
        main = get(app, sel('mainMenu'))
        if not services or not main or not count(main, sel('numberOfItems')):
            return False
        first = at(main, sel('itemAtIndex:'), 0)
        application_menu = get(first, sel('submenu'))
        if not application_menu:
            return False
        for index in range(count(application_menu, sel('numberOfItems'))):
            item = at(application_menu, sel('itemAtIndex:'), index)
            if get(item, sel('submenu')) == services:
                set_hidden(item, sel('setHidden:'), True)
                return True
    except (OSError, AttributeError, TypeError, ValueError):
        # Branding must never stop the application from opening.
        return False
    return False


def set_windows_application_identity() -> None:
    """Give Windows a distinct taskbar group before Qt creates any windows."""
    if sys.platform == 'win32':
        import ctypes
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID('DockingUniversal.Desktop.1')
