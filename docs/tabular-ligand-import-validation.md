# Approved SMILES-table import — 2026-10-17

## User-facing behavior

CSV, TSV and XLSX files use the existing **Screen ligands** compound review.
Auto-detection only suggests SMILES and optional name/ID columns. Every header
is available in each dropdown, with column numbers distinguishing duplicate or
empty headers. Excel worksheet selection is separate. **Use these columns**
must be clicked before compounds load; approval alone selects no compounds.
Changing a column or worksheet clears selection, hides stale compounds and
invalidates the workload. Invalid rows remain visible and cannot be checked.

The existing paginated compound table, host-generated 2D previews, explicit
selection, workload and normalized SDF preparation path are reused. Raw tables
cannot bypass column approval via an unreviewed workload request or CLI launch.
Unattended CLI use requires the same hash-bound `--ligand-selection` JSON.
Interactive terminal file pickers remain SDF/MOL-only. Individual table import
does not widen folder import beyond SDF/MOL.

## Chemistry and provenance

Import reads literal SMILES without embedding, minimizing, deduplicating or
adjusting protonation/tautomers. Stereochemistry, explicit charge and disconnected
components are retained. Original source fields are namespaced molecular
properties. File hashes, approved column positions, worksheet, original source
line/row and submitted SMILES accompany selected compound materialization and
the complete `inputs/ligand_library_review.json` ledger.

Mapping participates in fingerprints/record IDs. Source changes between header
review and approval, or after selection, fail closed. Full hashes are rechecked
for workload and materialization; host restarts reconstruct the approved review
from mapping and source without trusting old row indices alone. Source files
and protocol chemistry remain unchanged.

## Excel boundary

The production reader uses standard-library ZIP/XML parsing, not a new Excel
dependency. It never evaluates formulas, macros or external links. Formula cells
are invalid as SMILES even when their saved result looks valid. Numeric/date/
boolean/error SMILES are rejected; numeric name/ID values remain useful labels.
Shared/inline strings and sparse cell addresses are handled. Duplicate ZIP/cell/
row/sheet identifiers, XML entities and external worksheet relationships fail
closed. Only ordinary `.xlsx` files are supported, not `.xls` or `.xlsm`.

Limits: 100,000 parsed data rows, 4,096 columns, 128 MB file/uncompressed workbook
data. CSV/TSV use explicit delimiters, quoting and UTF-8/BOM or UTF-16/BOM.
The first nonempty row is the header. Blank rows are ignored; nonempty rows with
missing/invalid SMILES remain reviewable. The full table is initially indexed;
pagination is not unlimited-memory streaming.

## Validation

Source regression logs under
`validation/runs/tabular-ligands-20261017/` record **87 scientific/import/workflow
checks** and **121 GUI/host checks**, including **15 table-specific checks** and
existing SDF/MOL coordinates/stereochemistry, selection, stale-file guards,
host read-only behavior, screening and chooser regressions.

The synthetic Excel fixture was created/exported through the spreadsheet
runtime, inspected and rendered. Its two worksheets include literal SMILES,
stereo, salt, invalid chemistry, numeric cells and a formula with a valid-looking
cached result. Unit checks also cover malformed workbooks, unsafe relationships,
XML entities, duplicate addresses, arbitrary/duplicate/blank headers, BOM/quoted
tables, subset materialization in all three formats, duplicate names, no-name
mapping, multiline source positions, host restart and 2,501-row libraries.
The existing GUI pagination test also verifies 10,000 source records create only
one page of widgets.

`validation/tabular_ligands_gui.py` runs the real Qt interface and supervised
scientific host, then the real high-level materializer in a fresh scientific
process. Its **22 checks** confirm explicit approval, no automatic compound
selection, selected-subset workload, mapping invalidation, reapproval, worksheet
choice, host depiction, materialized stereo/provenance and unchanged study
authority. Visual inspection at 1400- and 1100-pixel widths confirms controls
remain usable with normal page/table scrolling.

Source acceptance: `validation/runs/tabular-ligands-20261017/source-guarded/summary.json`.
Installed acceptance and backup/hash outcomes are recorded separately in
`validation/runs/tabular-ligands-20261017/installation.json` and
`validation/runs/tabular-ligands-20261017/installed-guarded/summary.json`.
Final installation passed all 87 scientific/workflow, 121 GUI/host and 22
acceptance checks. All ten deployed module hashes match source; protected
original study-state and retained-result hashes are unchanged. Recoverable
backups remain in the validation run directory.

An initial installation check could not import a test helper because the test
runner omitted the tests directory from its search path. The installer restored
the previous runtime. The failure and rollback are retained in
`installation-attempt1.json` and `installed-gui-tests-attempt1.log`; the corrected
test environment passed before final deployment. This was a validation harness
error, not a successful application test or a docking failure.

These are import/selection checks, not new scientific docking benchmarks.
No preparation, docking, protocol approvals or original-study mutations are
performed. Existing SDF/MOL and downstream engine preparation remain unchanged.
Windows/Linux native GUI execution was not validated in this macOS session.
