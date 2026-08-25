# Receptor-preparation validation record: two 50-PDB cohorts

## Purpose and scope

This record documents two complementary 50-PDB receptor-preparation cohorts: a broad general public-PDB sample and a deliberately difficult covalent-linkage sample. Together they cover 100 public structures. The general cohort measures broad preparation robustness; the linked-chemistry cohort stresses failure modes not represented by ordinary protein-only examples, including small-molecule adducts, glycans, cofactors, modified polymer residues, and metal-associated structures. This is a preparation and workflow robustness record, **not** a docking-accuracy benchmark.

Success means that a receptor PDBQT was written without silently removing unmatched components. It does not establish that Vina can recover a ligand pose for the target. A target-matched bound-ligand control remains required before prospective screening is called approved.

## Implemented safeguards, measured limitations, and evidence

The tested implementation uses strict Meeko first, conservative PDBFixer repair, audited disulfide/histidine handling, and a narrow ADFRsuite linked-component fallback for Meeko-diagnosed deposited links. It does not silently delete unmatched components. When all safe routes fail, removal is an explicit final user decision and is retained as an audit record; it is not a general solution for modified polymers, cofactors, metals, or unresolved connectivity.

The evidence is contained in this record's complete 100-PDB manifests below, its route/outcome tables, and the reproducible repository test materials: [reference workflow fixtures](../tests/expected_runs), [CLI/integration checks](../tests/test_cli.sh), [PDBFixer tests](../tests/test_pdbfixer_preclean.py), [CCD audit tests](../tests/test_ccd_audit.py), and [report tests](../tests/test_report_cavity.py). The linked PDB IDs identify the public coordinate inputs; no downloaded PDB coordinates are redistributed. The separate [main validation index](validation.md) records installed-command, CI, and end-to-end workflow evidence.

## Pipeline under test

The tested order is strict Meeko, conservative PDBFixer followed by strict Meeko, documented disulfide/histidine handling where applicable, then a narrow ADFRsuite fallback when a retained multi-atom `LINK`ed component is present and strict Meeko rejects it, or when Meeko explicitly reports linked deposited chemistry. The ADFRsuite route preserves those multi-atom linked components in the input path; coordination waters and unsupported single-atom ions are not treated as covalent components solely because they appear in a `LINK` record. Automatic unmatched-component deletion is not used. If all safe routes fail, an interactive user may explicitly request Meeko's `--allow_bad_res` attempt; its decision, exact removal inventory, and log are retained. It is not a safe chemistry repair and never creates approval by itself.

### Fresh report-generation stress reconciliation (2026-08-25)

A fresh 100-entry report-generation stress run initially completed 79 full PDF/protocol/bundle outputs and stopped during receptor preparation for 21 entries. Review identified a generic filtering regression: some coordination waters and unsupported single-atom ions in deposited `LINK` records were being retained as though they were covalent components. After correcting that distinction, focused reruns completed for all six examined affected receptors: `1GYN` through PDBFixer followed by strict Meeko; `5K8R`, `3ET8`, `1P5S`, and `4ER8` through strict Meeko; and `2NSY` through the narrow ADFRsuite fallback. This focused evidence implies 85 automatic completions in that run, but the complete 100-entry panel has not yet been rerun and 85/100 is therefore not reported as a final cohort result.

A separate interactive 5KRH test exercised the final model-changing route. The workflow stopped, required explicit approval, completed after approval, and recorded an exact inventory of 31 removed residues/components. The generated [5KRH site-guided protocol report](assets/5KRH-user-approved-removal-cavity-report.pdf) states that the receptor model changed and reports the removal count; the exact TSV inventory and raw log remain in the retained artifacts and bundle. This verifies audit and reporting behavior, not the biological suitability of the altered receptor.

## Cohort A: general 50-structure preparation sample

A separate historical public-PDB sample of 50 structures was used to exercise general receptor preparation. Its original reported 47/50 PDBQT total included five former automatic-cleanup cases. The current behavior was reconciled by rerunning those five structures:

### Complete general-cohort manifest

The first ten entries were the original representative preparation sample: `3ASZ`, `1H52`, `3A9G`, `4O3Q`, `7YWG`, `6FXS`, `5L4S`, `5KRH`, `1GYN`, and `4HK6`. They were selected as the original broad software examples and all produced PDBQTs in that historical run.

The additional 40 were selected reproducibly from RCSB's entry-ID holdings after excluding the first ten: downloadable legacy-format PDB files were selected using random seed `20260819`. Their historical routes are recorded below. This cohort was chosen to measure broad preparation robustness, not to enrich for covalent adducts. Its former automatic-cleanup cases prompted the focused linked-chemistry stress test in Cohort B.

| Historical route or outcome | PDB IDs |
| --- | --- |
| Strict Meeko PDBQT | `5K8R`, `6N5A`, `7UW4`, `3ET8`, `5KEC`, `1P5S`, `4ER8`, `2IF8`, `5WYS`, `3WX8`, `4Q3I`, `6AJC` |
| PDBFixer then strict Meeko PDBQT | `7ZAO`, `2AYH`, `3DS8`, `5THK`, `7Q0I`, `4F3K`, `5RYC`, `5Z0C`, `2NLB`, `9D6Z`, `2CWZ`, `3HVH`, `3F5D`, `1GI1`, `6A3W`, `3FGE`, `6R55`, `7DP4`, `7KFW` |
| Former automatic Meeko cleanup PDBQT | `3DWL`, `2OXH`, `4EXH`, `6DBF`, `7CMK` |
| Initially stopped; later guided histidine success | `5NBX` |
| Documented historical stop | `4JE9`, `5UA2`, `4W4O` |

The five former cleanup entries were rerun under the final explicit-approval policy as documented in the next table. The remaining general-cohort entries retain their historical route record pending a single fresh all-50 release rerun.

| PDB ID | Final observed behavior |
| --- | --- |
| `3DWL` | Stops if removal is declined; produces PDBQT only after explicit approval |
| `2OXH` | Stops if removal is declined; produces PDBQT only after explicit approval |
| `4EXH` | Stops if removal is declined; still fails after approval |
| `6DBF` | Now produces PDBQT without removal |
| `7CMK` | Now produces PDBQT without removal |

The reconciled count is 46/50 PDBQTs: 43 without unmatched-component removal, one after guided histidine selection, and two after explicit user-approved removal. Four stop. This is a reconciled result; a single fresh rerun of all 50 with the final release code remains future work.

## Cohort B: covalent-linkage stress-test panel

The first cohort's cleanup ambiguity motivated a focused 50-entry panel selected from public RCSB structures with covalent-linkage annotations. It deliberately over-represents difficult deposited chemistry; it is not a random sample of all PDB receptors. Each entry was downloaded as its legacy PDB coordinate file and given a 120-second preparation limit.

| Outcome | Count | PDB IDs |
| --- | ---: | --- |
| Strict Meeko PDBQT | 1 | `2NSY` |
| ADFRsuite linked-component fallback PDBQT | 38 | `1DWA`, `4M6S`, `1N6O`, `4P44`, `4L0L`, `3M2Z`, `1ASF`, `1HV7`, `3PQR`, `1F4D`, `1FDJ`, `2Q9E`, `5E65`, `4BOE`, `4OV0`, `3EJU`, `3DZ5`, `1JU2`, `3GMN`, `4GOE`, `4TW0`, `1XH1`, `3FYX`, `1CVZ`, `2VQ6`, `2ASI`, `1DUI`, `4WR3`, `3WF3`, `4MJ4`, `1HL2`, `4K7J`, `1MYR`, `2ID4`, `4RQX`, `4DVK`, `2WV3`, `1C63` |
| Documented preparation stop | 8 | `1QL4`, `3NTG`, `3M97`, `2C1D`, `1QNQ`, `1I5T`, `2L8H`, `2ZO5` |
| Incomplete: 120-second timeout | 3 | `4LXV`, `3OXO`, `4QVL` |

Thus 39/50 produced receptor PDBQTs: 38 through the narrow ADFRsuite linked-component compatibility route and one through strict Meeko. No historical panel success used Meeko's former automatic cleanup route.

### Stop diagnoses and explicit-removal test

The eight documented stops were rerun with the final interactive workflow and an explicit approval of the final removal attempt. **None produced a PDBQT.** This confirms that these are not simple removable extras and should remain documented stops.

| PDB ID | Recorded category | Result after explicit approval |
| --- | --- | --- |
| `1QL4` | Unsupported non-standard residue | Still stopped |
| `3NTG` | Unsupported heme/cofactor template | Still stopped |
| `3M97` | Unsupported non-standard residue | Still stopped |
| `2C1D` | Unsupported non-standard amino acid | Still stopped |
| `1QNQ` | Unclassified template/connectivity failure | Still stopped |
| `1I5T` | Unsupported non-standard residue | Still stopped |
| `2L8H` | Unclassified template/connectivity failure | Still stopped |
| `2ZO5` | Unsupported non-standard residue | Still stopped |

The three timeout entries were not assigned a chemical failure reason and are not counted as either safe successes or documented chemistry stops.

## End-to-end adduct workflow examples

Two successful preparation examples were taken through downstream workflows.

* `1N6O` contains linked BME and a deposited GNP ligand. ADFRsuite fallback prepared the receptor; CCD ligand verification, ensemble generation, two docking seeds, pose comparison, and control evaluation completed. The control failed scientifically (best RMSD 7.811 Å; top-scored RMSD 9.470 Å; 2 Å threshold), so screening was not approved. This is consistent with a charged nucleotide and magnesium-coordination target being poorly represented by rigid Vina-style scoring, not a receptor-preparation crash.
* `1ASF` contains covalently bound PLP and no suitable free-ligand control. ADFRsuite fallback preparation, fpocket selection, exploratory ligand preparation, docking, collection, clustering, HTML summary, and PDF reporting completed. It remains explicitly exploratory, not target-validated.

## Interpretation and limitations

This record supports a narrow claim: Docking Universal can preserve and prepare many `LINK`-annotated deposited structures for Vina-style PDBQT workflows without silently deleting the linked chemistry. It does not claim universal treatment of covalent adducts, glycans, metals, heme, modified backbones, or nucleic-acid complexes. Neither a prepared PDBQT nor a completed docking run establishes pose accuracy. Controls that fail RMSD validation may still be inspected or continued as explicitly uncalibrated exploratory studies, but must not be represented as approved screening protocols.
