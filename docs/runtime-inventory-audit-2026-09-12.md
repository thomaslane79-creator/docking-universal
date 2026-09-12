# Runtime inventory audit — macOS arm64 — 2026-09-12

This is a read-only observation of the development Mac used for the initial GUI
feasibility work. It is not a portable lock file or a compatibility verdict.
Reproduce it with:

```bash
docking-universal runtime-inventory --json
```

## Environment boundaries

| Environment | Python | Selected compiled stack |
| --- | --- | --- |
| `docking-universal` | 3.9.23 | PyMOL Open Source 3.0.0, Qt 5.15.8, PyQt 5.15.9 Conda package, Boost/Boost.Python 1.82.0, RDKit 2023.09.6, OpenMM 8.3.1 |
| `docking-universal-vina` | 3.10.20 | Vina 1.2.7, Boost 1.86.0, NumPy 2.2.6 |
| `docking-universal-qvinaw` | none observed | qvina package 2.1.0, QuickVina-W executable 1.1, Boost 1.84.0 |

The installation therefore uses two Python versions and three Conda
environments. QuickVina-W does not add a third observed Python interpreter.
The incompatible-looking Boost generations remain isolated by process.

## Main scientific environment

| Capability | Observed package/version |
| --- | --- |
| Structural viewer | `pymol-open-source` 3.0.0 |
| Viewer GUI | `qt-main` 5.15.8; `pyqt` 5.15.9 |
| Viewer/graphics runtime | `libboost` and `libboost-python` 1.82.0; Cairo 1.18.0; PyCairo 1.27.0; GLEW 2.1.0; GLM 1.0.1; libpng 1.6.58; libjpeg-turbo 3.2.0 |
| Receptor/ligand preparation | Meeko 0.7.1; PDBFixer 1.11; OpenMM 8.3.1; Gemmi 0.7.5; MolScrub 0.2.2; Open Babel 3.1.1 |
| Pocket/interactions | fpocket 4.2.2; PLIP 2.3.1 |
| Analysis/report support | RDKit 2023.09.6; NumPy 1.26.4; SciPy 1.13.1; Matplotlib 3.9.4; Pillow 11.3.0; ReportLab 5.0.0 |

The primary and legacy preparation executables, PyMOL, fpocket, Open Babel,
PLIP, Finder/AppleScript chooser, Tkinter fallback, Make, and Conda were found.
ADFRsuite is external to Conda and is present as a conditional compatibility
fallback; the probe records its executable paths and does not infer its version.

PySide6 was not present. This is expected while the toolkit decision remains
open and is not an installation failure.

## Declaration drift

The readable `environment.yml`, exact macOS lock, pip distribution snapshot,
and observed installed environment serve different purposes. The probe records
each declaration with a SHA-256 hash rather than merging them silently.

The installed environment differs from the current readable/pip declarations
in several visible places: Gemmi is 0.7.5 rather than the pip snapshot's 0.7.3;
NumPy is 1.26.4 rather than 1.23.5; ReportLab is 5.0.0 rather than the direct
environment declaration's 4.2.5. Biopython 1.79 and ProDy 2.4.1 appear in the
pip snapshot but were not observed in the current Conda environment and are not
imported by the current `libexec` workflow. This is environment-record drift,
not evidence that those packages conflict.

The PyMOL Conda package and Python distribution use different names
(`pymol-open-source` and `pymol`); the inventory treats them as aliases while
preserving the observed source. Conda's PyQt package version and the Python
distribution metadata may likewise differ, so the environment/package source
must accompany the version in any later compatibility comparison.

## GUI implication

Do not add, remove, or upgrade Qt packages before the PyMOL interaction spike.
Run the bridge inside the existing Python 3.9/PyMOL environment. Keep Vina and
QuickVina-W behind explicit executable paths. Evaluate a GUI toolkit only after
two-way PyMOL selection and box updates work in a normal desktop session.

No report dependency or generated report was changed by this audit.
