# Real GUI workflow validation

This is the chronological acceptance plan for the rigid-receptor desktop. It
turns the decision inventory in `gui-decision-completeness-plan.md` into a small
set of reproducible studies. A completed-state mockup or an offscreen widget
test is not sufficient: each common case starts at **New study**, reaches a real
scientific result, and is inspected in the visible GUI.

## Acceptance rules

For every case, record the input identity and hash, operating system, Docking
Universal revision, dependency inventory, choices made, final state, report and
bundle paths, and any warning or intervention. The GUI must remain responsive,
show stage-level progress, stop only for a decision that is currently needed,
and close without leaving a scientific host or viewer process behind.

The CLI is the scientific reference. GUI and CLI runs are compared by normalized
receptor and box hashes, ligand identity, protocol authority, ensemble settings,
engine settings, evidence records, and report sections. PDFs do not need to be
byte-identical.

## Common-path suite

These five cases represent the workflows most users will encounter. They are the
release-blocking visible-GUI suite.

| ID | Situation and public example | Chronological GUI path | Required acceptance evidence |
| --- | --- | --- | --- |
| C1 | Ligand-free receptor and one new compound: PDB **2R8N** plus the retained indinavir SDF | New study → fetch PDB/mmCIF → inspect assembly/additives → P2Rank → related-PDB evidence → approve one box → finalize exploratory protocol → screen one ligand → results review | P2Rank plot and 3D scene agree; related evidence is explicit even when empty; `.duprotocol`, final protocol report, docking report, poses, clusters, PLIP and PoseEdit 2D output exist |
| C2 | Unique deposited control ligand: **1HVR**, `XK2:A:263`, followed by nevirapine or rilpivirine | New study → known-ligand control → exact ligand selection → CCD verification → receptor preparation → calibration → passing control bundle → screen new ligand | Experimental coordinates are withheld from conformer generation; RMSD result is visible; only a passing control grants control-validated authority |
| C3 | Repeated ligand name in a homodimer: **5IKT**, choose `TLF:A:601` or `TLF:B:601`, then screen PYR | New study → fetch structure → choose one exact ligand instance → strict CCD verification → calibration → screen | No merged centroid; selected chain/residue is preserved through preparation, box, crystal reference, report and bundle; the other copy remains evidence rather than contaminating the selected ligand |
| C4 | Existing protocol and a small multi-record library: a C2 or C3 bundle plus `examples/test_inputs/two_compounds.sdf` | New study → import protocol → integrity/preflight review → choose SDF → explicit start → sequential compound queue → results review | Locked receptor/box/settings cannot drift; both compounds are inventoried before execution; progress identifies the active compound; one compound's failure does not erase the other unless stop-on-error was selected |
| C5 | Local mmCIF input with assembly and deposited-component metadata: downloaded **2R8N mmCIF** plus indinavir | New study → local mmCIF → human-readable coordinate/assembly review → exploratory preparation and screening | Source format and selected coordinate model are retained; assembly and deposited components are understandable; conversion does not silently change the receptor; report provenance names the mmCIF source |

Use the compact public files already retained under `examples/tutorials/` for C1
and C2. C3 uses a fresh public 5IKT download and must not commit generated
coordinates or docking results. C4 may use a newly generated bundle from the
same acceptance session. C5 deliberately uses mmCIF rather than replacing the
PDB-based C1 route.

## High-impact boundary suite

These cases are less frequent but protect scientific correctness. They may use
small deterministic fixtures for branch control, followed by a visible real case
where one is available.

| ID | Boundary | Acceptance condition |
| --- | --- | --- |
| B1 | Several legitimate P2Rank regions and multi-site approval | Boxes remain separate, retain their colors/identities, and run sequentially; no oversized merged box |
| B2 | Deposited ligand evidence without a corresponding predicted cavity | The ligand-defined region remains available; conformational/rotamer evidence is shown; the GUI never claims that absent cavity prediction disproves the site |
| B3 | P2Rank unavailable, execution failure, and successful run with zero usable candidates | These states have different messages and actions; fpocket fallback is explicit and recorded |
| B4 | Ambiguous histidine or supported modified polymer component | The workflow pauses with retained evidence; accept, decline, sensitivity, and corrected-input paths preserve provenance and never invent a scientific answer |
| B5 | CCD unavailable or ligand chemistry inconsistent | Authoritative local SDF and provisional inference are clearly distinct; declining provisional chemistry stops before docking |
| B6 | Damaged or altered protocol bundle | Hash/preflight failure blocks screening and explains the exact mismatched artifact |
| B7 | Crash/restart at every durable decision | The pending decision reappears once; double submission and stale evidence are rejected; continuation creates no duplicate jobs |
| B8 | Viewer lifecycle and layout stress | Embedded PyMOL, figures, evidence tables, zoom/detach, resize, stage navigation and shutdown remain usable at a standard laptop resolution |

## Execution order

Run C1 first because it exercises the current exploratory vertical path. Fix all
blocking failures before moving to C2. Then run C2, C3, C4 and C5 in order. A
failure in a later case adds a focused regression test but does not broaden the
interface. After the common suite passes, close B1–B8 using the smallest real or
deterministic case that proves the behavior.

Each visible run receives an `acceptance_record.json` containing the case ID,
software inventory, inputs, decisions, outputs, result and known limitations.
Screenshots supplement this record for layout and viewer behavior; they are not
the scientific evidence themselves.
