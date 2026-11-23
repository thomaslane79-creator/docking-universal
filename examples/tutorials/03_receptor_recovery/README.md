# Example 3 · Review and recover receptor preparation

Test Shannon exercises the site-guided workflow when a deposited structure has incomplete side chains. The reference study used the original 6E2P mmCIF, approved two predicted regions, and finalized an exploratory Vina protocol after a reviewed receptor repair.

- [Original 6E2P mmCIF](inputs/6E2P.cif)
- [Pyronaridine SDF, PubChem CID 107771](inputs/pyronaridine_pubchem_107771.sdf)
- [Reference settings, timings, and input SHA-256 hashes](reference-run.json)

## Run from scratch

1. Create a new study and load the bundled mmCIF. Choose a fresh output folder. Select predicted pockets with P2Rank and enable related-structure evidence. Leave the pose-recovery control off.
2. Review the evidence and approve P1 and P2 to match the reference run. Check the score graph and legend, the initial full-receptor view, and the independent pocket and box toggles.
3. Select **Prepare receptor**. If preparation fails, open **Review failure and model options**. Check the failure reason and review the exact residue suggestions. The residues reported can vary between repair attempts.
4. To reproduce the recorded recovery, preview the exclusions ARG B:215, ARG B:230, LEU B:359, GLU B:461, and LYS A:244 with **Allow guarded side-chain repair after removals** selected. Check the original positions against the approved boxes. All five were outside both boxes in the reference study. Apply this exact exclusion set only when reproducing the reviewed example.
5. Verify that guarded repair and strict Meeko complete. Finalize the exploratory Vina protocol with the settings in the reference record. Inspect the protocol PDF for the pocket figure and receptor-change notes.
6. Load the bundled SDF and preview the workload for both sites. Run screening and review the clusters, saved interactions, and paired figures. Record the approximate time for each stage and keep the report and any screenshots with that run.

## Save a reference run

Keep the original inputs and hashes with the walkthrough. For each attempt, retain the settings, decisions, stage status, and timing. Capture screenshots at the points that explain a choice or show a problem. Save each rerun in its own output folder so the reports and logs can be compared against the previous reference.

The Test Shannon reference completed receptor preparation, protocol export, and screening. Screening took about 8 minutes 46 seconds across both approved sites. A fresh end-to-end rerun remains to be verified.
