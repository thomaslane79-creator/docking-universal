# Local ligand indicators and guided preparation recovery

The user requested the missing green circles first, followed by completion of
the generalized preparation-recovery guidance. Both corrections are implemented
in the existing application and installed on this Mac with recoverable backups.
The native recovery actions were exercised against a saved public 1N6O failure.
This is bounded acceptance of these corrections, not completion of every GUI
workflow or a claim that arbitrary receptor chemistry is supported.

## Green circles and consistent evidence

The plot previously counted only related-PDB observations. It now also derives
local evidence from the hash-pinned input-ligand and docking-box artifacts.
The full retained ligand must fit the actual box, with the existing 0.25 Å
boundary tolerance. Changed/missing files do not produce a local green ring.
No receptor coordinates, box geometry, detector score or approval is rewritten.
The projection works when reopening an existing study and requires no network.

The real saved example verifies all 32 GNP A:200 heavy atoms inside both P1 and
B1. Both points now have green rings. P1 retains its detector score; B1 remains
unscored. The evidence panel, candidate-table summary and detached PyMOL panel
identify the input ligand separately from related-PDB observations. The local
observation can be selected for 3D display. Its 2D contact-render action explains
that the interaction renderer lacks linked exact chemistry, while the existing
molecule inspector remains available for the 2D drawing.

The ring means retained input-ligand or related deposited-ligand site evidence.
Input coordinates alone do not establish experimental validation. Local input evidence does not
become independent validation or a passed pose-recovery control. Near-duplicate
box consolidation remains the next separate repair; it is not implemented here.

Local evidence: `validation/runs/gui-removal-20261107/circle-fix/receipt.json`,
`plot.png`, and the two evidence-panel renders. The fixture state is byte-identical.

## General recovery guidance

Every shared diagnostic category, including unknown failures, has a concrete
guided destination and expandable steps. Known required hydrogen/protonation
failures and rejected repair/output audits are recognized even when an older
attempt lacks an intervention message. An optional failed hydrogen stage cannot
be mistaken for the cause of an otherwise unclassified fatal error.

| Problem | Guided route |
| --- | --- |
| Unsupported element, component, modified residue, cofactor, linkage or charge | Review an available untried independent backend where eligible; otherwise identify required definitions or use a corrected input |
| Alternate conformations | Focus the existing exact deposited-conformation controls; no automatic choice |
| Missing standard side-chain atoms/template mismatch | Explain the attempted structural repair and open the existing reviewed-candidate receipt selector |
| Missing backbone | Corrected input; no automatic backbone/loop reconstruction |
| Rejected repair geometry | Inspect the rejected repair; corrected input or an eligible reviewed standard side-chain candidate |
| Bond connectivity/valence | Inspect the actual bonds and original/rejected repair, with corrected-input navigation |
| Histidine state | Explain the existing Scientific decision path and its scope; do not substitute a backend switch for a state decision |
| Required protonation assessment | Inspect requested pH, component warnings and atom changes; changing the typing backend does not satisfy the required stage |
| Missing hydrogen definitions or required hydrogen-stage failure | Explain the geometry definitions/runtime actually needed; distinguish these from docking charge parameters |
| Input format or program startup | Corrected input or installation/runtime diagnostics; no molecular omission proposed as a runtime repair |
| Unknown failure | Retained diagnostics and corrected-input route; explicitly no known automatic workaround |

Tool names remain under Advanced and in the explanation windows. The guide
distinguishes Meeko/ADFR atom typing and charge assignment from Reduce2 hydrogen
placement, PDBFixer structural repair and PDB2PQR/PROPKA protonation assessment.
It displays the recorded stages and names affected components/atoms when the
backend provides them.

Method suggestions now use the diagnosed problem, retained attempt provenance
and current host availability, rather than a cobalt-only drafting rule. An
independent method not yet attempted is labelled as a checked candidate with
unverified support for the whole model. The separately observed cobalt coverage
is retained as evidence, not generalized to other elements or all cofactors.
Both an ADFR primary run and an ADFR fallback are distinguished from their audit's
actual backend-log identity. Used/failed methods are not presented as fresh
suggestions. A disabled alternative is distinguished from a broken runtime.

Navigating help, tool controls, logs or a new-study window starts no scientific
work. A method/model change still needs an exact preview, rationale and explicit
acknowledgement. Exclusions remain blank. The reviewed-model hash, control
reference, retained warnings and finalization boundaries remain authoritative.
Relevant component failures also offer a secondary optional-omission route to
the existing exact-identity field. It proposes no identities and explains the
model change, preview, acknowledgement and permanent warnings.

## Actual native GUI checks

Use the installed application through a temporary native wrapper with isolated
state/preferences, ordinary Qt 6.11.2 and the existing Python 3.9 scientific host.
The saved 1N6O failure is a diagnostic replay, not another scientific run:

1. Open the failed-preparation page and its recovery action.
2. Verify the reported Mg atom, missing charges and already attempted methods.
   No backend is suggested as a fresh remedy; exclusions are empty and approval
   is disabled.
3. Open and close the separate recovery-steps window; verify relevant component
   definitions and the retained failure details.
4. Reveal Advanced and verify the current method and tool-role explanation.
5. Choose retained diagnostics. Verify actual logs, charge/repair audits and
   diagnostic files load even though the early failure registered no artifacts.
   Files are pinned when inspected; subsequent changes produce an unverified-file
   message rather than silently displaying them as the inspected evidence.
6. Reopen recovery and choose corrected input. The existing new-study window
   opens. Cancel it and return to the failed study at revision 2, with no active
   job, new study, approval or receptor change.

The native check found and repaired the previously empty early-failure Logs
pane. Read-only diagnostic display is tied to the inspected job; it does not
add scientific artifacts to the original study or borrow another job's files.
The original Cox-2 state and 5IKR source hashes remain unchanged.

Local evidence is under `validation/runs/recovery-guidance-gui-20261107`:
`baseline.json`, the isolated state, `guidance.json`, native `gui.log`, and the
read-only `real-failure-guidance-replay.json`. That replay covers 18 retained
failed attempts across charge, output-validation, linked-component, incomplete-
backbone, valence and required-protonation diagnoses, with actionable guidance
for all of them. These are not 18 new preparations or 18 independent proteins.

Final targeted checks pass 71 preparation/service tests and 151 GUI/workspace
tests. These groups overlap and are not a combined unique-test count. All 24
catalogue categories, including the unknown-failure route, are covered.
Automated checks cover every catalogue entry, GUI action destinations, current
host availability, unavailable/already-used methods, malformed or unknown
diagnostics, cancelled navigation and stale diagnostic hashes. Circle tests also
check rendered green pixels on P1 and unscored B1, separate external counts,
unrelated boxes, changed files and unchanged saved candidates.

## Remaining broader acceptance

The previously reproduced selected-table Qt Cocoa accessibility crash remains
open. This recovery-page check does not contain selected pocket tables and is
not a full pocket/control/finalization/export walkthrough. The prior
[native walkthrough record](gui-receptor-recovery-walkthrough-2026-11-07.md)
retains that limitation and the matching upstream issue. No dependency version,
accessibility permission or security setting was changed for this correction.
The protected 5IKR charge-parameter problem remains a separate chemistry stop.
