# GUI toolkit decision

Decision date: 2026-09-12. Initial desktop client: the installed Qt 5/PyQt5
stack in the main Docking Universal environment.

The runtime inventory observed Python 3.9.23, Qt 5.15.8 and PyQt5 5.15.9 in
the environment that already contains PyMOL Open Source 3.0.0. PySide6 was not
installed. The Vina and QuickVina-W engines remain isolated in their existing
environments and are launched through the scientific runners; their Python and
Qt dependencies do not enter the desktop process.

This selection avoids an environment migration during the first GUI slice and
supports `QMainWindow`, floating/dockable `QDockWidget` panels, fullscreen,
keyboard focus, high-DPI Qt behavior and multiple application windows. It does
not embed the external PyMOL window. PyMOL remains the required companion
viewer through the structured adapter.

The choice is deliberately isolated behind `docking_universal.gui`. A later
PySide6 migration changes the presentation binding rather than scientific
models, application-host messages, viewer identities, bash engine runners,
protocols, or reports. Packaging on other platforms remains an open gate and
must test actual display/DPI/multiple-monitor behavior on those systems.
