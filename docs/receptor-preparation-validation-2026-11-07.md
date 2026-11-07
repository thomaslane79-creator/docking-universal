# Receptor preparation: real-structure acceptance, 2026-11-07

The campaign exercised **14 public PDB entries, 23 distinct scenarios and 39
real preparation attempts**. The latest attempt for each scenario produced 13
completed preparations and 10 stops requiring review; no attempt timed out.
These are preparation outcomes, not a docking-accuracy or charge-accuracy score.
Default routes, explicit method settings and controlled missing-atom derivatives
are distinguished below. Unsupported chemistry was not removed to obtain passes.

The current application uses the shared preparation engine and GUI job service.
Direct engine invocations here are an isolated test harness, not redevelopment
of a user-facing CLI. The protected Cox-2 study stayed at revision 17, with its
source and state hashes unchanged. Both COH cofactors remained retained.

## Runtime and evidence

- Apple Silicon macOS; source baseline `c261366`, with the PDB2PQR adapter/audit
  corrections described below. Each attempt records exact source-file hashes;
  initial source and installed engine files matched before the fixes.
- Scientific Python 3.9; Meeko 0.7.1, RDKit 2023.09.6, PDBFixer 1.11.0,
  CCTBX 2024.8, PDB2PQR 3.6.2, Gemmi 0.7.3; installed ADFRsuite 1.0 through
  Rosetta. No tool upgrade was made to obtain these results.
- Fresh native mmCIF downloads from `files.rcsb.org`, with source URLs,
  retrieval headers, revision dates and SHA-256 receipts. Sources are preserved.
- Sequential jobs, 240-second limit per attempt; receptor parameterization
  only. Pocket prediction, redocking, screening and electrostatic surfaces were
  outside this campaign.
- Successful exports were checked for retained heavy atoms, elements, finite
  charges, recognized Vina types and coordinate changes against the actual
  adopted input. Separate inventories record filtering/repair changes.
  Meeko/RDKit O/OXT label exchanges are recorded separately from displacement
  of a coordinate; a strict identity-only audit is also retained.

Raw evidence is local and ignored by Git under `validation/runs/`:

| Folder | Attempts | Purpose |
| --- | ---: | --- |
| `receptor-prep-20261107` | 10 | Initial restricted-network campaign |
| `receptor-prep-online-20261107` | 10 | Same panel with public component lookup available |
| `receptor-prep-extra-20261107` | 8 | Disulfides, missing atoms, protonation, template settings, disabled fallback |
| `receptor-prep-protonation-fix-20261107` | 1 | Format correction exposed a protonation-name audit error |
| `receptor-prep-final-20261107` | 3 | Corrected pH route, zinc, NMR ensemble |
| `receptor-prep-service-20261107` | 3 | Real GUI preparation/job-service integration |
| `receptor-prep-protonation-panel-20261107` | 3 | Disulfide and cofactor protonation guards |
| `receptor-prep-disulfide-ph-fix-20261107` | 1 | Corrected CYX comparison; four sulfur pairs verified |

`receptor-prep-summary-20261107.json` aggregates all attempts. Each case retains
`receipt.json`, run/backend logs, available tool audits, output hashes and
`model-changes.json`; successful exports also have `output-inventory.json`.
An output file retained after a failed run is diagnostic evidence, not an
accepted prepared receptor.

## Public-structure panel

Counts refer to the adopted receptor and its export, after the established
component filter. Free ligands/waters excluded by that filter are not counted
as exporter atom loss. For rejected ADFR exports, counts below use ADFR's own
actual input audit, not an earlier PDBFixer candidate.

| Entry | Scenario and observed route | Result |
| --- | --- | --- |
| [1UBQ](https://www.rcsb.org/structure/1UBQ) | Standard ubiquitin; Reduce2 → strict Meeko | Completed; 602/602 heavy atoms |
| [2R8N](https://www.rcsb.org/structure/2R8N) | Unbound protease; supporting glycerol excluded by normal filter; Reduce2 → strict Meeko | Completed; 754/754 |
| [1HVR](https://www.rcsb.org/structure/1HVR) | Inhibitor complex with oxidized CSO residues; online component lookup → strict Meeko | Completed; 1,514/1,514; CSO preserved |
| [1AKI](https://www.rcsb.org/structure/1AKI) | Lysozyme with four deposited disulfides; Reduce2 → strict Meeko | Completed; 1,001/1,001 |
| [1LYZ](https://www.rcsb.org/structure/1LYZ) | Independent legacy lysozyme geometry; Meeko, PDBFixer retry and strict CYX retry | Stopped: RDKit valence/bond-inference errors persisted; no permissive retry or omission |
| [7ZAO](https://www.rcsb.org/structure/7ZAO) | Alternate conformations and Mg; PDBFixer → strict Meeko | Completed; 6,418/6,418; PDBFixer selected conformations, added no heavy atoms |
| [2AYH](https://www.rcsb.org/structure/2AYH) | Alternative conformations, disulfide and calcium; PDBFixer → strict Meeko | Completed; 1,698/1,698; no heavy-atom repair required |
| [5NBX](https://www.rcsb.org/structure/5NBX) | Linked nonstandard 8SN chemistry plus alternate conformations | Stopped: Meeko template failure; ADFR audit rejected unresolved duplicate source identities |
| [1ASF](https://www.rcsb.org/structure/1ASF) | Covalently linked PLP; automatic independent ADFR fallback | Completed; all 3,083 heavy atoms retained at unchanged coordinates; finite charges/recognized types; no missing-parameter warning |
| [1N6O](https://www.rcsb.org/structure/1N6O) | Linked BME, nucleotide and Mg; ADFR attempted | Stopped despite 1,376/1,376 retained: Mg charge parameters reported missing |
| [2C1D](https://www.rcsb.org/structure/2C1D) | CSS, covalently linked hemes, Fe/Zn; ADFR attempted | Stopped despite 12,727/12,727 retained: 24 missing-charge-parameter warnings |
| [5IKR](https://www.rcsb.org/structure/5IKR) | Original cobalt/glycan case; automatic ADFR attempted after Meeko retries | Stopped despite 9,132/9,132 retained: five glycan atoms lack charge parameters; both COH preserved |
| [1CA2](https://www.rcsb.org/structure/1CA2) | Zinc carbonic anhydrase; strict Meeko | Completed; 2,040/2,040, including Zn |
| [1D3Z](https://www.rcsb.org/structure/1D3Z) | Ten-model NMR ensemble | Stopped before preparation: select one coordinate model; no arbitrary model selected |

7ZAO/2AYH were historical repair candidates, but this campaign did **not** find
missing sidechain atoms in their PDBFixer inventories. Their successful repair
routes mainly exercised conformation handling. This distinction is why the
controlled missing-atom cases were also run.

## Controlled derivatives and explicit settings

Only the two missing-atom fixtures alter downloaded coordinates. Each preserves
an original copy/hash and removes exactly one named atom from 1UBQ LYS A27.
Other entries below retain the downloaded coordinates and vary engine settings.
These choices are validation fixtures, not approvals for the protected study.

| Scenario | Observed result |
| --- | --- |
| 1UBQ minus LYS A27 NZ | PDBFixer added exactly NZ; strict Meeko completed; 602/602 heavy atoms in adopted/exported receptor; generated geometry passed the existing overlap guard |
| 1UBQ minus LYS A27 CA | Stopped with `incomplete_backbone`; PDBFixer recorded CA and built no backbone atom; no prepared output accepted |
| 1UBQ, Reduce2 off and PDB2PQR required at pH 7.4 | Completed after the adapter/audit fixes; all 602 heavy atoms; HID assignment retained in audit/output |
| 1UBQ, external hydrogen engines off, no explicit histidine template | Strict Meeko completed; this source did not reproduce histidine ambiguity |
| Same input, explicit A68=HIE | Completed with the specified template; this tests the explicit setting, not a scientifically preferred tautomer |
| 1ASF, ADFR fallback disabled | Stopped; status explicitly `disabled`; no ADFR attempt |
| 1AKI, explicit PDB2PQR pH 7.4 | Completed after CYX audit correction; 1,001/1,001 heavy atoms; all four deposited SG pairs retained with zero sulfur displacement |
| 1CA2, explicit PDB2PQR pH 7.4 | Stopped for review: PDB2PQR added terminal PHE A260 OXT and warned that Zn lacked a residue definition; no altered candidate adopted |
| 1HVR, explicit PDB2PQR pH 7.4 | Stopped for review: CSO-definition warnings; heavy atoms retained, but required protonation was not accepted as supported |

## Repairs made and verified

1. The native filtered mmCIF lacks `_entity.pdbx_description`, which PDB2PQR
   requires. Its audit also reads PDB records. The handoff now uses the already
   retained compatibility PDB of the same filtered receptor. Reduce2 and Meeko
   keep their existing native-input behavior.
2. Expected HIS/HID/HIE/HIP and CYS/CYX naming, plus the existing recognized
   protonation aliases, are compared through parent heavy-atom identities.
   Actual output residue states and hydrogens are retained, not renamed away.
   CSO→CYS is still a chemistry change and fails this protonation audit.
3. Empty input inventories and unreviewed heavy-atom additions now fail the
   protonation guard. Explicit Hg element records are not mistaken for H.

Verification: **86 targeted Python tests passed**, plus preparation-route,
command-builder, diagnosis and structural-audit shell checks. The new real
mmCIF route regression requires a PDB handoff and a nonzero atom inventory.
The two corrected production files were backed up, installed into the Mac
application and verified by SHA-256. No fallback eligibility/order was changed.

The GUI job-service checks used isolated study state and real scientific tools:
PDB2PQR/1UBQ and automatic ADFR/1ASF became completed jobs with registered
prepared receptors. 5IKR became a failed job with no registered prepared
receptor and no active job left behind. This checks the GUI service boundary;
it is not a complete interactive GUI or cross-platform scientific acceptance.

## Remaining limits and follow-up evidence

- 5IKR remains blocked by NAG B607 O6 and C/D NAG1/NAG2 O4 charge assignment.
  The cobalt fallback works mechanically; full cofactor/glycan electrostatics
  are not thereby validated. No deletion or source-topology correction was made.
- Restricted-network 1HVR fell through to the existing PDBFixer CSO→CYS mapping
  and completed with `all_retained=false` in the CCD audit. Online strict Meeko
  preserved CSO. This network-dependent model change is a remaining policy/
  review concern; the campaign did not change automatic PDBFixer standardization.
- ADFR eligibility remains limited to the existing linked-component route.
  1LYZ's unsuccessful valence case did not trigger an unrelated legacy fallback.
- The real 5NBX input now stops on linked-fragment/alternate-conformation issues
  before reproducing its historical histidine-only decision. Guided ambiguity
  remains covered by the deterministic route fixture, not a new real positive.
- Reduce2 was installed. PDB2PQR's natural automatic entry when Reduce2 is
  unavailable was not reproduced by uninstalling it; explicit required-mode
  tests exercised the actual PDB2PQR handoff. An available Reduce2 failure still
  follows the existing policy and does not silently switch protonation engines.
- Successful preparation establishes these mechanical checks only. Retained
  glycans, metal coordination, protonation states, missing loops, charge-model
  accuracy, binding-site relevance and downstream docking still require their
  own scientific review and appropriate controls.

## Reproduction

Use the scientific environment's Python and a new ignored output directory:

```bash
python validation/receptor_prep_scenarios.py fetch --out validation/runs/new-panel --ids 1UBQ 1ASF 5IKR
python validation/receptor_prep_scenarios.py run --out validation/runs/new-panel --ids 1UBQ 1ASF 5IKR
python validation/receptor_prep_scenarios.py review --out validation/runs/new-panel
```

Use `service` instead of `run` to exercise the GUI preparation/job service with
isolated persisted state. `--protect PATH` may be repeated to ensure unrelated
study/source files remain unchanged after every attempt. `--ids` also accepts
the controlled/explicit-setting case names listed in the runner. Existing
campaign receipts are never overwritten; new runs require a new folder.
