# Consistent report generation

The production PDF, HTML and Markdown reports share reader-facing protocol
settings and compound-overview tables in `docking_universal.reporting`.
GUI generation and CLI generation use the same report paths; there is no
engine-specific alternative production PDF template.

Target headings keep the protein name and append the compact structure ID,
for example `Pol protein [2R8N]`, without the redundant word "structure".
The shared identity formatter also supplies protocol-creation report text.

The GUI no longer browses static report figures directly. Open the generated
report to see those panels and captions. Interactive pocket plots, linked
2D/3D inspection, live PyMOL scenes and their image exports remain in the GUI.
Static figures are still generated and retained in the study and its bundles;
this is a presentation change, not deletion of evidence or report content.
The interactive-only change passes 384 GUI/report/workflow checks and 92
native PyMOL checks, with a backed-up local GUI installation. Validation is
recorded under `validation/runs/gui-interactive-only-20261017/`.

- Configured-protocol tables contain selectable settings, not a protocol-schema
  dump. Scoring-function identification belongs beside the best docking score:
  an adjacent overview column or an adjacent compound-summary row names AD4 or
  Vina. QuickVina-W uses the Vina scoring label. Unknown historical records say
  “Not recorded”; the current installed engine is not substituted.
- The main summary omits seed support, conformer support and the count of
  selected representatives. Full CSV/JSON records and run details retain these
  diagnostics. Cluster energies, populations, assignments, top-20 plotting and
  the actual globally lowest experimental-RMSD pose rules are unchanged.
- Pocket tables show the selected region's actual recorded prediction score
  and probability, not a pointer to another report. “Selected” is distinct from
  the highest-ranked prediction; preliminary review still says “Top.” Ligand-
  defined regions do not receive invented prediction scores.
- New protocol records and bundles embed numeric pocket metadata. Original
  diagnostic files are also bundled with hashes. Legacy recovery requires the
  exact recorded box hash and output index; missing evidence is reported as
  not retained. No pocket detection is repeated to fill a report field.
- Saved PLIP report callouts use the same compact Sans Bold style across
  engines. The underlying contacts, coordinates, camera and label positions
  are unchanged. HTML/Markdown remain text summaries, not replicas of the PDF's
  full scientific figure panels.

## Standalone protocol reports

Protocol-only reports use the same compact settings table for both engines.
Vina shows exhaustiveness, saved-pose limit and energy window. Experimental
AutoDock-GPU shows the AD4 genetic-run count and heuristic evaluation cap, not
irrelevant Vina options. A short explanation identifies the planned energy
model and warns against comparing AD4 and Vina energies directly. These are
future screening settings, not evidence that docking has already occurred.
AD4 requested box dimensions and actual grid dimensions remain together in
the pocket geometry table, not among selectable options.

With no docking run manifest, pocket reporting still follows the approved
region, not the first generated box. Portable embedded scores are used when
the original diagnostics are unavailable; genuinely missing values remain
explicit. Ligand-defined boxes never borrow a prediction score. Preliminary
review remains distinct and shows the top prediction before approval.
Protein identity, species, exploratory limitations and retained evidence remain
visible; no empty docking-results section or invented energy/RMSD is added.
This does not enable AD4 bound-ligand control calibration.

Standalone acceptance is recorded in
`validation/runs/protocol-only-reports-20261017_b/`: 230 report, protocol,
bundle and workflow checks pass. Both three-page portrait PDFs were generated
from isolated copies using retained pocket figures, and all six pages were
visually inspected. All 48 original source artifacts remain hash-identical.
No preparation, docking or clustering was repeated. The earlier failed check
is retained separately: the synthetic workflow fixture lacked a detector
version and was correctly rejected by the existing provenance guard. The
fixture now identifies itself explicitly; the production guard was not weakened.

These changes affect newly generated reports. Existing studies, locked
protocols and historical benchmark PDFs are not silently rewritten. The
validation copies reuse retained scientific outputs without preparation,
docking or clustering reruns.

Verification and local installation are recorded under
`validation/runs/report-sync-20261017/`. All 225 focused report, control,
protocol, bundle and screening regressions pass. The updated eight-page PDF
and HTML summary are visually inspected; all 553 original validation artifacts
remain hash-verified unchanged. Cross-platform report code is shared;
the native visual inspection in this record is on macOS, not Windows/Linux
GPU-engine certification.
