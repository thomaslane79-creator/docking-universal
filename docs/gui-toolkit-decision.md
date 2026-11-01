# GUI toolkit decision

## Current status (2026-10-22)

The desktop uses Qt6/Python 3.12, separate from the scientific host. Supported
Apple-Silicon installations now include a pinned Qt6-compatible embedded PyMOL
runtime; the companion remains an explicit alternative. Full PyMOL detachment
borrows the same scene/engine and returns it to the workspace. Normal launch is
maximized, not locked full-screen. Static report-figure browsing was removed;
interactive review and image export remain. See
[Mac runtime packaging](mac-runtime-packaging.md),
[the user guide](guided-workflow.md) and
[current cross-platform boundaries](cross-platform-compatibility.md).

## Historical decision record (2026-09-12/13)

The following describes the original companion-only implementation, not current
installation instructions or the present embedded-viewer limitation.

Decision date: 2026-09-12; revised 2026-09-13. The initial desktop client used
Qt 5/PyQt5. The active migration target is Python 3.12 with PyQt6 in a dedicated
GUI environment.

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

The binding is isolated behind `docking_universal.gui.qt`. PyMOL Open Source
3.1 remains a required supervised companion in its own Python 3.12 environment
because its conda-forge build selects Qt 5. The split prevents Qt 5 and Qt 6
from entering one process while leaving scientific models, application-host
messages, viewer identities, bash engine runners, protocols, and reports
unchanged. Packaging on other platforms remains an open gate and must test
actual display/DPI/multiple-monitor behavior on those systems.

The initial client now has dockable/floating workflow-detail, selection, log,
report and artifact panels; reversible fullscreen; an explicit pocket-approval
control routed through the sole application host; and a required PyMOL review
launcher. A row selection is only a visual proposal. Approval is a separate
version-checked command carrying the selected candidate IDs and optional
scientific rationale.
