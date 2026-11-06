# 5IKR COH support investigation — 2026-11-05

Status, updated 2026-11-06: P2Rank and the independent ADFR runtime are repaired;
whole-receptor preparation with all deposited glycans remains stopped on
reported charge failures. The user explicitly requires keeping both COH cofactors.
Protein electrostatic visualization remains the first requested results addition;
this investigation addresses the current run and its charge-model prerequisite.

## Exact retained structure

The deposited mmCIF identifies COH as cobalt-containing protoporphyrin IX.
Keep COH A:602 and B:603, with their deposited heavy atoms and coordinates.
The mmCIF records metal coordination from HIS A:388 NE2 to COH A:602 CO,
and HIS B:388 NE2 to COH B:603 CO, both at a deposited distance of 2.143 Å.
Its component table declares four intracomponent Co–porphyrin-nitrogen bonds.
The embedded component atom table has no formal-charge column; it is not a
complete partial-charge parameter set.

The current selection remains ID8 B:602, P2Rank with additional-pocket prediction
enabled, and the original control/evidence settings. The source mmCIF hash remains
`a4a20672b28f87d32a4cdff8ae7dbdbe4c94af40bc86d4b7caf0122d860cf472`.
The current study and original source have no cofactor, glycan or metal removal
or substitution. Rejected private diagnostic candidates are described below.
No new docking control or hit screen ran.

## Independent fallback restoration and current result

The branch history retains ADFRsuite when Meeko becomes the default. ADFR was
installed separately from Conda; September's inventory records its presence,
and October's validation already records `Bad CPU type in executable`. This is
an unavailable legacy installation, not evidence that a newer Meeko replaced
every preparation route.

With explicit user approval, Rosetta and official Intel Mac ADFRsuite 1.0 are
installed. The nonacademic installer option is selected; its unused academic
surface module is outside the installed prefix. `prepare_receptor -h` succeeds.
The archive SHA-256 is
`9556680809c76859b159b7709fa1a6e84716e2cb41a0ab8bd72aecbb7960b413`.

An isolated real fallback revealed that ADFR's default `nonstdres` cleanup
deletes 78 retained heavy atoms from six sugar residues on chains C/D. Explicit
`-U nphs_lps_waters` prevents that loss. The corrected full pipeline retains all
9,132 heavy atoms at unchanged coordinates, including both COH cofactors. ADFR
has explicit elemental cobalt Gasteiger parameters and assigns each cobalt
approximately +0.873 e in this candidate; that establishes parameter coverage,
not target-specific charge/scoring accuracy or APBS acceptance.

The output is rejected despite exit code zero because ADFR reports five missing
Gasteiger assignments: NAG B:607 O6, C:1 O4, C:2 O4, D:1 O4 and D:2 O4. The
original source is byte-identical to the current public RCSB mmCIF. It contains
an O6–GLU B:416 OE1 distance of about 1.262 Å without alternate conformers;
legacy distance-based bond perception adds an unsupported O–O edge. Four
glycosidic NAG O4 sites also retain HO4 atoms identified as leaving atoms in
the branch-link table. Linked ASN sites and cross-chain connectivity need
complete review as well; removing only the five warnings is not a complete
topology correction. No source-connectivity adapter or hydrogen edit has been
adopted, and no real study was retried by this validation.

Open Babel's isolated Gasteiger charge calculation fails on COH even though its
PDBQT writer can still return success. Its QEq component probe produces finite
but unreviewed charges with an assumed total state; EQEq fails. These outputs
are not accepted as automatic substitutes.

The optional exact-exclusion review remains available. The 2026-11-06 user
clarification extends its GUI entry point to failed control preparation before
boxes exist. No exclusions are preselected. A reviewed derivative is prepared
separately, and later boxes receive persistent inside/distance warnings from
the original residue coordinates. The unchanged source and both COH cofactors
remain the current study model until the user explicitly approves a change.

## Findings and actual checks

| Layer | Evidence | Result |
| --- | --- | --- |
| P2Rank installation | Upstream tarball has `p2rank_2.5.1/`; runtime expects `p2rank-2.5.1/` | Extract into the explicit expected destination. Move the existing installed asset intact. |
| P2Rank execution | Existing JAR, P2Rank 2.5.1, Java 17.0.18 | Version check and actual local prediction on the retained filtered receptor succeed. Prediction output is private validation data. |
| Current run | Exact accepted setup, unchanged source hash | Original launcher failure is preserved. The normal-runner retry now reaches preparation and stops on cobalt support. |
| Meeko 0.7.1 | Installed radius table lacks Co; typing configuration lacks a Co rule; default templates lack COH/NAG/MAN | Cannot prepare this model with the current default path. |
| Vina | Installed engine accepts a synthetic one-atom receptor with type `Co`; upstream lists Co among non-AD4 metals | Atom-type recognition is supported. This is not a test of COH charges, coordination, scoring accuracy or pose recovery. |
| RDKit Gasteiger | Strict parameter tests on isolated Co and Co2+ reject missing cobalt parameters | Do not silently treat missing charge parameters as a supported computed charge. These tests do not define the oxidation state of the actual cofactor. |
| GeoStd at the pinned revision | NAG/MAN files exist; `c/data_COH.cif` returns 404 | Missing local sugar definitions can be acquired, but this alone does not solve COH support. |
| Meeko 0.8.0 isolated wheel | Unpacked in a private temporary directory; working installation untouched | Contains a cobalt covalent radius, but a strict receptor probe still rejects automatic COH and linked NAG/MAN template generation. No permissive residue deletion was used. |
| PDB2PQR 3.6.2, AMBER assign-only | Original filtered receptor, no new protonation, all output private | Warns about unknown COH/NAG/MAN and stops on nonintegral residue charges. No PQR was accepted for APBS. |

The newer Meeko probe downloaded only public chemical-component definitions.
Its wheel SHA-256 is
`38e73da7f0b11f7f8f0bfb2c481ccd148b8dfb9957522655b5cb0c4f6d68d1d6`.
The retained P2Rank JAR SHA-256 is
`4d73a85b796bd5ec5563d840abb5b1005f37b4651fd7f8aaad4b01a936ea1ece`.

The first monitoring wrapper ended after submitting its retry. Its worker was
confirmed stopped, the normal interrupted-job reconciliation recorded the
interruption, and a supervised retry then reached the chemistry failure. The
initial failed study snapshot and original logs remain in private backups.
The final study has no running job, no new approvals and the same accepted setup.

## Supported next increment and acceptance boundary

A cofactor-aware adapter needs all of the following before a new scientific run:

1. Explicit COH chemistry and source atom mapping, including how the deposited
   cobalt–histidine coordination is represented. Keep coordination distinct from
   automatically inferred covalent links.
2. Reviewed COH/linker and glycan templates covering the retained model. The
   existing CCD-to-Meeko bridge is limited to peptide-linking PTMs and must not
   be used to guess a porphyrin or glycan template.
3. An identified charge model and complete, finite atom charges with a justified
   total charge. Oxidation, protonation and coordination assumptions must be
   specified. Do not substitute iron parameters or zero charges for missing Co
   support. A radius constant alone is not a charge model.
4. Vina atom typing and strict output checks retaining both Co atoms, all retained
   heavy atoms, source frame, exact ligand/site choice and parameter provenance.
   A Vina-only candidate must not imply AD4 or APBS parameter acceptance.
5. A separate bound-ligand control and artifact/reopening checks before claiming
   successful transfer to screening. Parameter assignment alone is not accuracy.

Protein APBS surfaces additionally need compatible radii and a documented
electrostatic model. Do not use an incomplete PQR or a protein-only map under a
label implying that these retained cofactors were included. A generic charge map
cannot be called ready for this target while those parameters are unresolved.

Published cobalt-containing force fields are leads for a reviewed model, not
drop-in proof of applicability. The CoPP/REV-ERBβ work uses separate porphyrin and
metal parameterization in a different target. A newer paper that includes 5IKR's
Co-porphyrin in AI co-folding does not supply an accepted Meeko/APBS charge model
for this pipeline. No parameter set from either paper has been adopted.

## References inspected

- [Meeko 0.8.0 release](https://github.com/forlilab/Meeko/releases/tag/v0.8.0)
- [Meeko 0.8.0 cobalt-radius table](https://github.com/forlilab/Meeko/blob/v0.8.0/meeko/utils/covalent_radius_table.py)
- [Vina atom constants and metal recognition](https://github.com/ccsb-scripps/AutoDock-Vina/blob/develop/src/lib/atom_constants.h)
- [RDKit strict Gasteiger parameter behavior](https://www.rdkit.org/docs/source/rdkit.Chem.rdPartialCharges.html)
- [PDB2PQR workflow and force fields](https://pdb2pqr.readthedocs.io/en/latest/using/examples.html)
- [APBS workflow](https://apbs.readthedocs.io/en/stable/using/index.html)
- [Cobalt-system force-field derivation study](https://doi.org/10.1021/acs.jpcb.9b10739)
- [CoPP/REV-ERBβ simulation methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC8198987/)
- [5IKR-containing AI co-folding study](https://pmc.ncbi.nlm.nih.gov/articles/PMC13267107/)
