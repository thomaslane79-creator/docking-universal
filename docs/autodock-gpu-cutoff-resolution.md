# AD4 cutoff-reference resolution and remaining integration - 2026-10-16

The earlier tipranavir audit failure is explained, not deleted or accepted by
loosening an energy tolerance. This is scoped numerical evidence on the tested
Apple M2 Max, not a production installation or a universal accuracy claim.

## Direct evidence

Retained population entity 173 (run 2/entity 24), atoms 6/16 in zero-based order,
has a double-precision distance of **7.999999657621469 A**. The actual native
energy kernel computes **8.0 A** and excludes that pair from its strict `< 8`
van der Waals cutoff. The reference previously included it, adding
**-0.00093363621609 kcal/mol**. That accounts for the original
**-0.00093215013997 kcal/mol** discrepancy to within 0.00000149 kcal/mol.

A diagnostic build loads the exact raw retained population and original energy
arrays and executes **zero search generations**. Capturing distances inside the
real scoring function reproduces all original coordinates and reevaluated
energies exactly, both in the targeted replay and in the all-pair capture.
A smaller standalone distance kernel did not reproduce this cutoff branch;
its unsuccessful result is preserved and was not substituted for the real
kernel measurement. Compiler context matters at this rounding boundary.

The expanded capture retains **all 2,199,000 pair distances across 3,000 states**.
Each is checked independently against the coordinate-derived double distance;
maximum discrepancy is 3.244 float32 ULPs, below the declared four-ULP diagnostic
bound. Exactly one cutoff branch differs, the pair above, within one ULP of 8 A.

## Reference boundary and unchanged energy gates

The new check conditions only the discontinuous cutoff decisions on the
captured native distances. All continuous energy terms are still independently
evaluated in double precision. This is a component-level matched-native
reference, **not a wholly independent double-precision scorer**. A hard cutoff
can amplify a sub-ULP distance difference; demanding identical double/native
branch choices is not a correct description of the native scoring model.

No energies, coordinates, search code or output ranks are corrected to fit the
reference. No population member is excluded. The original energy gates remain:
bounded absolute residual <=0.001 kcal/mol, winner absolute residual <=0.0001,
and full-population scaled residual <=0.00001.

| Check | Tipranavir, native-branch conditioned | KNI-577, original reference |
| --- | ---: | ---: |
| Population states retained | 3,000 | 3,000 |
| Bounded absolute maximum, kcal/mol | 0.000558 | 0.000568 |
| Twenty winner absolute maximum, kcal/mol | 0.00000363 | 0.00000269 |
| Full-population scaled maximum | 0.00000421 | 0.00000654 |

KNI-577's previously unlaunched instrumented audit now completes. All twenty
poses pass chemical/coordinate stereochemistry checks, and pose, complete
printed-population and score fingerprints match the uninstrumented control.
It passes the original reference gates without cutoff conditioning.

Large absolute residuals in severely clashing high-energy states remain
recorded (66.54 and 34.00 kcal/mol); scaled checks include these states.
Winner agreement must not be presented as identical arithmetic everywhere.

## Retained records

Under `validation/runs/autodock-gpu-mac-20261016/`:

- `control-panel-atomtype-audit/summary.json`: original failed audit, unchanged.
- `cutoff-investigation/tipranavir-native/summary.json`: standalone-probe failure.
- `cutoff-investigation/native-kernel-replay/summary.json`: targeted actual-kernel replay.
- `cutoff-investigation/native-all-pairs-replay/summary.json`: complete capture,
  exact coordinate/energy agreement, zero search generations.
- `cutoff-investigation/tipranavir-actual-kernel/summary.json`: final reference
  and distance checks with unchanged energy gates.
- `kni-numerical-followup/summary.json`: completed KNI-577 instrumented audit.

Harnesses and the reference unit tests are retained outside ignored run data.
All original audit inputs stay hash-verified. Diagnostic replay additions are
not production patches: the candidate still has only the documented force
barrier and one-work-item safety guard. The one-work-item defect remains
quarantined, not repaired. Unsupported macrocycle pseudoatoms remain rejected.

## Integration follow-through

The explicitly experimental adapter now passes common-report, protocol/GUI,
cancellation/failure/skip/tamper, native viewer and reopen acceptance within this
tested scope. Local deployment is recorded separately; see
[integration acceptance](ad4-gpu-integration.md). Existing Vina defaults and
studies are unchanged. These integration checks do not broaden the numerical
reference into a universal accuracy claim.
