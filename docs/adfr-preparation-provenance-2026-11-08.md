# ADFRsuite preparation identity and screening PDF repair

The missing-version screening PDF blocker is corrected for fresh preparations.
Existing historical records are preserved; a report cannot infer which software
prepared an old receptor from the current installation.

## Cause and repair

The primary ADFR path did not record a version. The fallback startup audit
checked availability only. The report also had a heuristic that inferred 1.0
from a conventional folder on the report machine; that heuristic is removed.

The existing startup adapter now captures identity immediately before receptor
preparation. For the official suite launcher, its own Python environment locates
the ADFR package; literal package version metadata is read without importing
molecular libraries or changing user configuration. The installation-directory
name supplies no version. Unrecognized launchers explicitly retain unknown
identity, which cannot satisfy the PDF's used-software requirement.

The accepted-output record binds the version to the exact receptor hash and
preparation route, with hashes for the launcher, entry-point script, runtime,
runtime launcher, version source and preparation input. A changed implementation
or input cannot be sealed after execution. Strict atom/charge output validation
is unchanged. The primary route's diagnostic probe does not replace its actual
preparation outcome; failed fallback startup remains ineligible for execution.

The preparation service registers the receipt as a hashed study artifact.
Finalization and control calibration retain the identity inline, and portable
bundles include the exact receipt with integrity checks. Reports consume the
retained identity for both primary and fallback routes, including after protocol
reuse. The GUI finalization summary also now respects the recorded primary
ADFR route instead of interpreting the generic success log as strict Meeko.

## Actual validation

All generated scientific artifacts are local, ignored validation fixtures.

| Public example | Fresh route | Strict accepted output | Identity |
| --- | --- | --- | --- |
| 1UBQ | Primary ADFRsuite | 602 heavy atoms retained | ADFRsuite 1.0 |
| 1ASF | Automatic linked-component ADFR fallback | 3,083 heavy atoms retained | ADFRsuite 1.0 |
| 1HVR | Primary ADFRsuite, CSO preserved | 1,514 heavy atoms retained | ADFRsuite 1.0 |

1UBQ correctly yielded no usable P2Rank site. It was not forced into a docking
example. The ligand-bound public 1HVR example supplied one real retained P2Rank
proposal for the report acceptance. A clearly labeled isolated software test
approved P1 and used minimal exploratory settings: one conformer per state, one
seed, Vina exhaustiveness 1 and three modes. These settings test software
handoff, not docking accuracy or biological relevance.

The ordinary finalization service created a fresh three-page protocol PDF and
portable protocol bundle. One public example compound (Nevirapine, PubChem 4463)
was then screened using that exported bundle. The compound and study completed,
and the ordinary report path produced its five-page screening PDF. Both PDF
software tables identify **ADFRsuite 1.0 / primary receptor parameterization**.
The corresponding pages were rendered and inspected; the tables are legible
with no clipped text. No report validation guard was relaxed.

Preserved first attempts: 1UBQ's zero-candidate detection and the first isolated
screen invocation with an incomplete PATH. The latter could not locate MolScrub
and retained its failure report. Repeating in a new directory with the scientific
runtime PATH used by the GUI completed successfully. The original attempt was
not overwritten or counted as completed docking.

A final fresh 1UBQ run used the installed preparation/job service. It completed,
recorded 1.0, and registered the backend receipt and its SHA-256 in persisted
study state. The protected Cox-2 state and original 5IKR source hashes are
unchanged. No cofactor, charge parameter or original study was modified.

Validation includes `make test`, 225 real-Qt GUI contracts, 103 focused
report/protocol/control contracts, preparation route/attempt shell checks, and
37 focused checks after artifact-registration changes, plus 20 final
launcher-recognition/registration checks. Regressions cover
version/installation-name disagreement, unknown launchers, changed implementation,
wrong-receptor identity, portable reuse without the original suite, raw report
receipts and refusal to guess historical versions.

Local evidence:

- `validation/runs/backend-identity-primary-20261108/`
- `validation/runs/backend-identity-fallback-20261108/`
- `validation/runs/backend-identity-bound-primary-20261108/`
- `validation/runs/backend-identity-installed-service-20261108/`
- `local-fix-backups/backend-provenance-20261108/manifest.json`

The original 5IKR glycan charge-parameter problem and broader fresh GUI workflow
acceptance remain separate. Old preparations without a preparation-time identity
still require a fresh preparation to obtain a fully evidenced report. Restart
an already-running application before beginning the new workflow.
