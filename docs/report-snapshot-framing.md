# Complete 3D report snapshot framing

Fixed and installed on the working Mac, 2026-10-22.

The original ray-rendered PyMOL images contained their residue labels. The
shared top-cluster report compositor then enlarged and center-cropped them to
fill wider cells, cutting some top/bottom labels off. It now proportionally fits
the entire image inside the cell. White-only border trimming and existing
panel sizes, colors, label fonts, captions and cluster selection are unchanged.
The correction is engine-neutral and also applies to a one- or two-cluster panel.

Validation covers tall, wide and square synthetic snapshots with edge markers
in every corner, independently checked in one-, two- and three-panel layouts.
The focused report suites pass 38 cases. The corrected installed compositor
produces byte-identical output to the six visually checked panels.
The complete suite also passes 738 Python cases and 21 shell checks.

Copied Vina, QuickVina-W and AD4 results produced three corrected eight-page
PDFs. All pages were rendered and inspected as contact sheets; each affected
3D-panel page was inspected at larger resolution. Report text and numerical
values match the original PDFs exactly after whitespace normalization. All
1,365 files in the original acceptance result trees remain hash-identical.
No docking, PyMOL re-render, PLIP analysis or preparation was repeated.

Only the installed figure compositor was replaced, with a recoverable backup.
Its patch is limited to panel sizing rather than unrelated newer source-runtime
changes. The 697-entry protection audit has no unexpected changes relative to
the accepted application updates; the pre-existing absent stale ReportLab
metadata entry remains absent. User studies/settings, dependencies and previous
reports are unchanged. Future report generation uses the fixed framing;
historical PDFs are not silently rewritten.

Local-only evidence and corrected PDFs:
`validation/runs/report-snapshot-framing-20261022-b/`. The first driver attempt,
preserved under the directory without `-b`, failed before report generation
because newer source imports were not present in the installed Mac runtime.
The successful check used a staged installed renderer with only the framing
patch. Source/staged compositor functions are structurally identical.
